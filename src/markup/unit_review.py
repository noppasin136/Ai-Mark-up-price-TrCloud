"""Unit review — the gate between raw receipts and pricing.

Cost arrives per *received* unit; price is published per *sale* unit. When those
differ the engine must convert, and the conversion is only as good as the ERP's
unit data. Two things go wrong in practice:

  * the sale unit is a W10 parallel unit, so cost must be scaled by the
    coefficient (legitimate, but worth seeing once); and
  * the receipt was keyed against the wrong unit — the ถุงร้อน items are bought
    by the pack but entered as bag — so the coefficient would be applied to a
    figure that is already in the target unit, multiplying the cost.

No formula distinguishes those two cases; only a person who knows the product
can. So every questionable SKU is written to ``config/unit_review.xlsx`` with the
evidence, and stays out of the price upload until it carries a decision.

Decisions (the ``Decision`` column, case-insensitive):

  ``PENDING``        not yet decided — SKU is held back
  ``ACCEPT``         the coefficient conversion is correct as-is
  ``TREAT_AS``       the receipt unit is mis-keyed; use ``Treat GR Unit As``
  ``EXCLUDE``        do not price this SKU at all
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

REVIEW_FILENAME = "unit_review.xlsx"
SHEET = "Unit Review"

PENDING, ACCEPT, TREAT_AS, EXCLUDE = "PENDING", "ACCEPT", "TREAT_AS", "EXCLUDE"
VALID_DECISIONS = {PENDING, ACCEPT, TREAT_AS, EXCLUDE}

COLUMNS = [
    "SKU", "Product Name", "Sale Unit", "GR Units Received", "Coefficient",
    "Cost per GR Unit", "Converted Cost", "Current Price", "Implied Markup %",
    "Markup Rule %", "Why Flagged", "Decision", "Treat GR Unit As", "Note",
    "First Seen", "Decided On",
]

# A conversion is suspicious when the converted cost lands far above the price
# the item currently sells for — the classic signature of a mis-keyed unit.
SUSPICIOUS_MARGIN_PCT = -25.0


@dataclass
class Decision:
    sku: str
    decision: str
    treat_as: str | None = None
    note: str = ""

    @property
    def is_resolved(self) -> bool:
        return self.decision in {ACCEPT, TREAT_AS, EXCLUDE}


def review_path(cfg) -> Path:
    return cfg.resolve(Path("config") / REVIEW_FILENAME)


# --------------------------------------------------------------------- reading
def load_decisions(cfg) -> dict[str, Decision]:
    """Read the review sheet. Missing file simply means nothing is decided yet."""
    path = review_path(cfg)
    if not path.exists():
        return {}

    df = pd.read_excel(path, sheet_name=SHEET)
    df.columns = [str(c).strip() for c in df.columns]
    out: dict[str, Decision] = {}

    for record in df.to_dict("records"):
        sku = str(record.get("SKU") or "").strip()
        if not sku or sku.lower() == "nan":
            continue
        raw = str(record.get("Decision") or "").strip().upper()
        if raw not in VALID_DECISIONS:
            if raw and raw != "NAN":
                log.warning(
                    "unit_review.xlsx: SKU %s has decision '%s', which is not one of %s "
                    "— treating as PENDING",
                    sku, raw, sorted(VALID_DECISIONS),
                )
            raw = PENDING
        treat = str(record.get("Treat GR Unit As") or "").strip()
        if treat.lower() in {"", "nan", "none"}:
            treat = None
        if raw == TREAT_AS and not treat:
            log.warning(
                "unit_review.xlsx: SKU %s is TREAT_AS but 'Treat GR Unit As' is blank "
                "— treating as PENDING", sku,
            )
            raw = PENDING
        note = str(record.get("Note") or "")
        out[sku] = Decision(sku, raw, treat, "" if note.lower() == "nan" else note)

    resolved = sum(1 for d in out.values() if d.is_resolved)
    log.info("Unit review: %d entry(ies), %d resolved, %d pending",
             len(out), resolved, len(out) - resolved)
    return out


def unit_remap(decisions: dict[str, Decision]) -> dict[str, str]:
    """sku -> the unit its receipts should be treated as (TREAT_AS decisions only)."""
    return {d.sku: d.treat_as for d in decisions.values() if d.decision == TREAT_AS and d.treat_as}


def excluded(decisions: dict[str, Decision]) -> set[str]:
    return {d.sku for d in decisions.values() if d.decision == EXCLUDE}


def unresolved(decisions: dict[str, Decision]) -> set[str]:
    return {d.sku for d in decisions.values() if not d.is_resolved}


# ------------------------------------------------------------------- detection
def detect(candidates: pd.DataFrame) -> pd.DataFrame:
    """Flag rows needing a human decision.

    ``candidates`` needs: sku, product_name, sale_uom, gr_units, coefficient,
    cost_per_gr_unit, converted_cost, current_price, markup_pct.
    """
    df = candidates.copy()
    reasons: list[str] = []

    for row in df.itertuples():
        why = []
        gr_units = [u.strip().lower() for u in str(row.gr_units or "").split(",") if u.strip()]
        sale = str(row.sale_uom or "").strip().lower()

        if not gr_units:
            reasons.append("")
            continue

        if sale and sale not in gr_units:
            why.append(f"sold per '{row.sale_uom}' but received per '{row.gr_units}'")

        coef = row.coefficient
        if pd.notna(coef) and coef and coef > 1:
            why.append(f"sale unit is a parallel unit (x{coef:g})")

        cost, price = row.converted_cost, row.current_price
        if pd.notna(cost) and pd.notna(price) and price > 0:
            margin = (price - cost) / price * 100
            if margin < SUSPICIOUS_MARGIN_PCT:
                why.append(
                    f"converted cost {cost:,.2f} exceeds the {price:,.2f} selling price "
                    f"({margin:.0f}% margin) — likely a mis-keyed receipt unit"
                )
        reasons.append("; ".join(why))

    df["why_flagged"] = reasons
    return df[df["why_flagged"].astype(bool)].reset_index(drop=True)


# --------------------------------------------------------------------- writing
def sync(cfg, flagged: pd.DataFrame, decisions: dict[str, Decision]) -> tuple[Path, int, int]:
    """Merge newly flagged SKUs into the review sheet, preserving existing decisions.

    Returns ``(path, newly_added, still_pending)``.
    """
    path = review_path(cfg)
    today = dt.date.today().isoformat()
    existing = pd.DataFrame(columns=COLUMNS)
    if path.exists():
        existing = pd.read_excel(path, sheet_name=SHEET)
        existing.columns = [str(c).strip() for c in existing.columns]

    known = {str(s).strip() for s in existing.get("SKU", [])}
    rows = []
    for r in flagged.itertuples():
        if str(r.sku) in known:
            continue
        rows.append({
            "SKU": r.sku,
            "Product Name": r.product_name,
            "Sale Unit": r.sale_uom,
            "GR Units Received": r.gr_units,
            "Coefficient": r.coefficient,
            "Cost per GR Unit": round(r.cost_per_gr_unit, 4)
            if pd.notna(r.cost_per_gr_unit) else None,
            "Converted Cost": round(r.converted_cost, 4) if pd.notna(r.converted_cost) else None,
            "Current Price": r.current_price,
            "Implied Markup %": round((r.current_price / r.converted_cost - 1) * 100, 1)
            if pd.notna(r.converted_cost) and r.converted_cost else None,
            "Markup Rule %": r.markup_pct,
            "Why Flagged": r.why_flagged,
            "Decision": PENDING,
            "Treat GR Unit As": None,
            "Note": None,
            "First Seen": today,
            "Decided On": None,
        })

    if rows:
        fresh = pd.DataFrame(rows)
        frames = [f for f in (existing, fresh) if not f.empty]
        merged = pd.concat(frames, ignore_index=True) if frames else fresh
    else:
        merged = existing
    for col in COLUMNS:
        if col not in merged.columns:
            merged[col] = None
    merged = merged[COLUMNS].sort_values("SKU").reset_index(drop=True)

    _write(path, merged)
    pending = int(
        merged["Decision"].astype(str).str.strip().str.upper().isin({PENDING, "", "NAN"}).sum()
    )
    return path, len(rows), pending


def _write(path: Path, df: pd.DataFrame) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        df.to_excel(xl, sheet_name=SHEET, index=False)
        ws = xl.book[SHEET]

        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="1F3864")
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 32
        ws.freeze_panes = "A2"

        widths = {"SKU": 12, "Product Name": 34, "Sale Unit": 11, "GR Units Received": 18,
                  "Coefficient": 12, "Cost per GR Unit": 15, "Converted Cost": 14,
                  "Current Price": 13, "Implied Markup %": 15, "Markup Rule %": 13,
                  "Why Flagged": 60, "Decision": 14, "Treat GR Unit As": 16,
                  "Note": 30, "First Seen": 12, "Decided On": 12}
        for i, col in enumerate(df.columns, start=1):
            ws.column_dimensions[get_column_letter(i)].width = widths.get(col, 14)

        # Dropdown on Decision so the sheet cannot acquire a typo.
        dcol = get_column_letter(list(df.columns).index("Decision") + 1)
        dv = DataValidation(
            type="list",
            formula1=f'"{PENDING},{ACCEPT},{TREAT_AS},{EXCLUDE}"',
            allow_blank=True,
            showDropDown=False,
        )
        dv.error = "Choose PENDING, ACCEPT, TREAT_AS or EXCLUDE"
        ws.add_data_validation(dv)
        dv.add(f"{dcol}2:{dcol}{max(len(df) + 1, 2)}")

        fills = {PENDING: "FFF2CC", ACCEPT: "E2EFDA", TREAT_AS: "DDEBF7", EXCLUDE: "F2F2F2"}
        dcol_idx = list(df.columns).index("Decision") + 1
        for r in range(2, len(df) + 2):
            key = str(ws.cell(row=r, column=dcol_idx).value or PENDING).strip().upper()
            fill = fills.get(key)
            if fill:
                ws.cell(row=r, column=dcol_idx).fill = PatternFill("solid", fgColor=fill)
            ws.cell(row=r, column=list(df.columns).index("Why Flagged") + 1).alignment = Alignment(
                wrap_text=True, vertical="top"
            )

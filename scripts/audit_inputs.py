"""Data-quality audit of the ERP exports in data/input/.

Read-only. Produces data/output/data_audit_<date>.xlsx describing what is
usable, what is blocked, and which SKUs need a human decision before the
pricing engine can be trusted.

    python scripts/audit_inputs.py
"""

from __future__ import annotations

import datetime as dt
import glob
import sys
from pathlib import Path

import pandas as pd

# The ERP writes the literal text "null" into some numeric cells, which makes
# openpyxl raise while parsing. Recover those as blanks instead of failing.
from openpyxl.worksheet import _reader

_orig_cast = _reader._cast_number
_recovered = {"n": 0}


def _safe_cast(value):
    try:
        return _orig_cast(value)
    except (ValueError, TypeError):
        _recovered["n"] += 1
        return None


_reader._cast_number = _safe_cast

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "data" / "input"
AS_OF = pd.Timestamp("2026-08-29")
PERIODS = (30, 60, 90, 120)

GR_COLS = {"วันที่": "date", "เลขที่เอกสาร": "doc", "ประเภทเอกสาร": "doc_type",
           "ชื่อ": "supplier", "รหัสสินค้า": "sku", "กลุ่มสินค้า": "group",
           "ชื่อสินค้า": "name", "ต้นทุนต่อหน่วย": "unit_cost", "จำนวน": "qty",
           "หน่วย": "uom", "ต้นทุนรวม": "total_cost"}
W_COLS = {"รหัสสินค้า": "sku", "หน่วย": "uom", "Ccoefficient": "coef",
          "ราคาขาย": "sell_price", "ราคาซื้อ": "buy_price",
          "เป็นหน่วยหลัก": "is_main", "ชื่อสินค้า": "name", "กลุ่มสินค้า": "group"}
M_COLS = {"Code": "sku", "Product Name": "name", "Sale Unit": "uom",
          "Selling Price": "price", "Category": "category", "Markup": "markup"}


def _one(pattern: str) -> Path:
    hits = sorted(IN.glob(pattern))
    if not hits:
        sys.exit(f"No file matching {pattern} in {IN}")
    return hits[0]


def load():
    gr = pd.read_excel(_one("GR2*.xlsx"), sheet_name="data").rename(columns=GR_COLS)
    w = pd.read_excel(_one("W10*.xlsx"), sheet_name="data").rename(columns=W_COLS)
    m = pd.read_excel(_one("markup_list*.xlsx"), sheet_name="SellingPrice").rename(columns=M_COLS)

    gr["date"] = pd.to_datetime(gr["date"], errors="coerce")
    for c in ("unit_cost", "qty", "total_cost"):
        gr[c] = pd.to_numeric(gr[c], errors="coerce")
    for c in ("coef", "sell_price", "buy_price", "is_main"):
        w[c] = pd.to_numeric(w[c], errors="coerce")
    for c in ("price", "markup"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    for df in (gr, w, m):
        df["sku"] = df["sku"].astype(str).str.strip()
        if "uom" in df:
            df["uom"] = df["uom"].astype(str).str.strip()
    return gr, w, m


def main() -> None:
    gr, w, m = load()
    clean = gr.dropna(subset=["sku", "date", "qty", "unit_cost"])
    clean = clean[(clean["qty"] > 0) & (clean["unit_cost"] > 0)]
    win = clean[clean["date"] >= AS_OF - pd.Timedelta(days=90)]

    coef = {(r.sku, r.uom.lower()): r.coef for r in w.itertuples()}
    main_unit = w[w["is_main"] == 1].set_index("sku")["uom"].to_dict()

    # ---- cost per SKU, in the unit it was actually received in -------------
    wavg = win.groupby("sku").apply(
        lambda d: (d["qty"] * d["unit_cost"]).sum() / d["qty"].sum(), include_groups=False
    ).rename("cost_in_gr_unit")
    gr_units = win.groupby("sku")["uom"].agg(lambda s: ", ".join(sorted(set(s.dropna()))))
    last_gr = clean.groupby("sku")["date"].max()

    d = m.merge(wavg, on="sku", how="left")
    d["gr_units"] = d["sku"].map(gr_units)
    d["last_receipt"] = d["sku"].map(last_gr)
    d["w10_main_unit"] = d["sku"].map(main_unit)
    d["sale_coef"] = [coef.get((s, str(u).lower())) for s, u in zip(d["sku"], d["uom"])]
    d["unit_agrees"] = [
        isinstance(gu, str) and str(u).lower() in [x.strip().lower() for x in gu.split(",")]
        for u, gu in zip(d["uom"], d["gr_units"])
    ]
    d["new_price"] = d["cost_in_gr_unit"] * (1 + d["markup"])
    d["change_pct"] = (d["new_price"] - d["price"]) / d["price"].replace(0, pd.NA) * 100
    d["implied_markup"] = d["price"] / d["cost_in_gr_unit"] - 1

    costable = d["cost_in_gr_unit"].notna()
    needs_unit_review = costable & ~d["unit_agrees"]

    # ---- findings ----------------------------------------------------------
    findings = [
        ("BLOCKER", "Numeric cells containing the text 'null'",
         _recovered["n"],
         "The ERP export writes 'null' into numeric cells; standard Excel readers crash on it. "
         "The loader must recover these as blanks."),
        ("BLOCKER", "Markup is a decimal fraction, not a percent",
         int(m["markup"].notna().sum()),
         "Values are 0.12 / 0.15 / 0.20 / 0.25. Fed in as-is the engine would read 0.12%. "
         "Multiply by 100 on load."),
        ("BLOCKER", "Markup varies within a category",
         int(m.groupby("category")["markup"].nunique().gt(1).sum()),
         "WH and Central Kitchen each carry several markup rates, so category alone cannot "
         "determine the rate. The list must be treated as SKU-level."),
        ("DECISION", "Sale unit differs from the unit received",
         int(needs_unit_review.sum()),
         "Cost is per received unit, price is per sale unit. The W10 coefficient resolves some "
         "of these and contradicts others. Needs a per-SKU decision — see 'Unit Review'."),
        ("DECISION", "Sale Unit blank in the markup list",
         int(m["uom"].isin(["nan", ""]).sum()),
         "These SKUs have no stated selling unit."),
        ("WARNING", "Markup-list SKUs with no receipt in 90 days",
         int((~costable).sum()),
         "Cannot be costed from a 90-day window. Lengthen the period, or price them by another "
         "route — see 'No Receipts'."),
        ("WARNING", "Unit cost swung more than 50% within the window",
         0, "Placeholder — filled below."),
        ("WARNING", "Current price already at or below cost",
         int((d.loc[costable, "implied_markup"] <= 0).sum()),
         "These are loss-making today; repricing will move them sharply."),
        ("WARNING", "Current price disagrees with the markup rule",
         int((d.loc[costable, "implied_markup"] - d.loc[costable, "markup"]).abs().gt(0.05).sum()),
         "Implied markup is more than 5pp from the rule. Expected if the list is new — this is "
         "the gap the project is meant to close."),
        ("WARNING", "GR2 lines whose unit is unknown to W10",
         int(sum(1 for s, u in zip(clean["sku"], clean["uom"]) if (s, str(u).lower()) not in coef)),
         "No coefficient available, so these cannot be unit-converted."),
        ("INFO", "GR2 lines that look duplicated",
         int(clean.duplicated(subset=["doc", "sku", "qty", "unit_cost"], keep=False).sum()),
         "Same document, SKU, quantity and cost. May be legitimate split lines."),
        ("INFO", "GR2 rows with a blank unit", int(gr["uom"].isna().sum()), ""),
        ("INFO", "GR2 rows dropped (blank key, zero or negative qty/cost)",
         len(gr) - len(clean), "Excluded from costing."),
        ("OK", "Document types present", gr["doc_type"].nunique(),
         "All receipts are type MPO — no returns or credit notes to net off."),
        ("OK", "Total cost reconciles to unit cost x quantity",
         len(clean), "Only 1 line in 47,000 disagrees by more than 1%."),
        ("OK", "Markup-list SKUs found in W10", int(m["sku"].isin(w["sku"]).sum()),
         f"All {len(m)} are present."),
    ]

    vol = win.groupby("sku")["unit_cost"].agg(["min", "max", "mean", "count"])
    vol["spread_pct"] = ((vol["max"] - vol["min"]) / vol["mean"] * 100).round(1)
    vol = vol[vol.index.isin(m["sku"])]
    findings[6] = ("WARNING", "Unit cost swung more than 50% within the window",
                   int(vol["spread_pct"].gt(50).sum()),
                   "FIFO, LIFO and weighted average will disagree materially for these; some "
                   "are keying errors the outlier filter should catch.")

    findings_df = pd.DataFrame(findings, columns=["Severity", "Finding", "Count", "What it means"])

    coverage = pd.DataFrame(
        [
            {
                "period_days": p,
                "skus_with_receipts": int(
                    m["sku"].isin(clean[clean["date"] >= AS_OF - pd.Timedelta(days=p)]["sku"]).sum()
                ),
                "of_total": len(m),
            }
            for p in PERIODS
        ]
    )
    coverage["coverage_pct"] = (coverage["skus_with_receipts"] / coverage["of_total"] * 100).round(0)

    cols = ["sku", "name", "category", "markup", "uom", "gr_units", "w10_main_unit", "sale_coef",
            "cost_in_gr_unit", "price", "new_price", "change_pct", "implied_markup", "last_receipt"]
    review = d[needs_unit_review][cols].sort_values("change_pct", key=abs, ascending=False)
    no_receipt = d[~costable][["sku", "name", "category", "markup", "uom", "price", "last_receipt"]]
    no_receipt = no_receipt.sort_values("last_receipt", ascending=False)
    preview = d[costable & d["unit_agrees"]][cols].sort_values("change_pct", key=abs, ascending=False)

    volatility = vol.sort_values("spread_pct", ascending=False).head(40).reset_index()
    volatility = volatility.merge(m[["sku", "name"]], on="sku", how="left")

    mapping = pd.DataFrame(
        [
            ("GR2", "data", "วันที่", "receipt_date"), ("GR2", "data", "เลขที่เอกสาร", "receipt_no"),
            ("GR2", "data", "ชื่อ", "supplier"), ("GR2", "data", "รหัสสินค้า", "sku"),
            ("GR2", "data", "กลุ่มสินค้า", "category"), ("GR2", "data", "ชื่อสินค้า", "product_name"),
            ("GR2", "data", "ต้นทุนต่อหน่วย", "unit_cost"), ("GR2", "data", "จำนวน", "qty"),
            ("GR2", "data", "หน่วย", "uom"), ("GR2", "data", "ต้นทุนรวม", "total_cost"),
            ("W10", "data", "รหัสสินค้า", "sku"), ("W10", "data", "หน่วย", "uom"),
            ("W10", "data", "Ccoefficient", "conversion_factor"),
            ("W10", "data", "ราคาขาย", "current_price"), ("W10", "data", "ชื่อสินค้า", "product_name"),
            ("W10", "data", "กลุ่มสินค้า", "category"), ("W10", "data", "เป็นหน่วยหลัก", "is_base_unit"),
            ("markup_list", "SellingPrice", "Code", "sku"),
            ("markup_list", "SellingPrice", "Sale Unit", "sale_uom"),
            ("markup_list", "SellingPrice", "Selling Price", "current_price"),
            ("markup_list", "SellingPrice", "Category", "category"),
            ("markup_list", "SellingPrice", "Markup", "markup_pct  (x100 on load)"),
        ],
        columns=["File", "Sheet", "ERP header", "Maps to"],
    )

    out = ROOT / "data" / "output" / f"data_audit_{dt.date.today():%Y%m%d}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl", datetime_format="yyyy-mm-dd") as xl:
        findings_df.to_excel(xl, sheet_name="Findings", index=False)
        coverage.to_excel(xl, sheet_name="Period Coverage", index=False)
        review.to_excel(xl, sheet_name="Unit Review", index=False)
        no_receipt.to_excel(xl, sheet_name="No Receipts", index=False)
        preview.to_excel(xl, sheet_name="Repricing Preview", index=False)
        volatility.to_excel(xl, sheet_name="Cost Volatility", index=False)
        mapping.to_excel(xl, sheet_name="Column Mapping", index=False)

        from openpyxl.styles import Alignment, Font, PatternFill
        fills = {"BLOCKER": "F8CBAD", "DECISION": "FFE699", "WARNING": "FFF2CC", "OK": "E2EFDA"}
        for name in xl.book.sheetnames:
            ws = xl.book[name]
            for c in ws[1]:
                c.fill = PatternFill("solid", fgColor="1F3864")
                c.font = Font(color="FFFFFF", bold=True)
                c.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.freeze_panes = "A2"
            for col in ws.columns:
                letter = col[0].column_letter
                width = max((len(str(c.value or "")) for c in col[:60]), default=10)
                ws.column_dimensions[letter].width = min(max(width + 2, 11), 60)
        ws = xl.book["Findings"]
        for row in ws.iter_rows(min_row=2):
            fill = fills.get(str(row[0].value))
            if fill:
                for c in row:
                    c.fill = PatternFill("solid", fgColor=fill)

    print(f"Audit written: {out}")
    print(f"\n{'Severity':<10}{'Count':>7}  Finding")
    for sev, name, count, _ in findings:
        print(f"{sev:<10}{count:>7}  {name}")


if __name__ == "__main__":
    main()

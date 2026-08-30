"""Run orchestration: load -> cost -> mark up -> round -> validate -> report."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import unit_review
from .config import AppConfig
from .costing import cost_skus
from .io import (
    load_gr2,
    load_markup_list,
    load_my_cargo,
    load_sale_list,
    load_w10,
    load_w10_units,
    mycargo_unit_issues,
    unit_table,
)
from .routing import build_routes
from .rules.markup import MarkupResolver, apply_markup, gross_margin_pct
from .rules.rounding import apply_rounding, pick_rule
from .uom import build_unit_rows, normalise_factor
from .validation import apply_guardrails, exceptions_view

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    detail: pd.DataFrame
    upload: pd.DataFrame
    exceptions: pd.DataFrame
    cost_audit: pd.DataFrame
    summary: pd.DataFrame
    stats: dict = field(default_factory=dict)


def run(
    cfg: AppConfig,
    gr2_path: str | Path,
    w10_path: str | Path,
    markup_path: str | Path,
    sale_list_path: str | Path | None = None,
    my_cargo_path: str | Path | None = None,
) -> RunResult:
    started = dt.datetime.now()

    gr2 = load_gr2(cfg.resolve(gr2_path), cfg.mapping)
    units = load_w10_units(cfg.resolve(w10_path), cfg.mapping)
    w10 = load_w10(cfg.resolve(w10_path), cfg.mapping)
    markups = load_markup_list(cfg.resolve(markup_path), cfg.mapping, cfg.markup_value_scale)
    sale_list = load_sale_list(cfg.resolve(sale_list_path) if sale_list_path else None, cfg.mapping)

    coefficients = unit_table(units)
    decisions = unit_review.load_decisions(cfg)

    my_cargo = routes = None
    if cfg.wh_routing_enabled:
        if my_cargo_path:
            my_cargo = load_my_cargo(cfg.resolve(my_cargo_path), cfg.mapping)
        scope_df = sale_list if (sale_list is not None and not sale_list.empty) else w10
        scope = list(dict.fromkeys(scope_df["sku"]))
        routes = build_routes(scope, markups, my_cargo, gr2, cfg)

    costs, audit = cost_skus(gr2, cfg, coefficients, unit_review.unit_remap(decisions), routes)
    if cfg.wh_routing_enabled:
        costs = _apply_routing(costs, routes, my_cargo, w10, cfg)
    detail = _build_detail(w10, costs, sale_list)
    detail = _resolve_sale_units(detail, coefficients, decisions, gr2)
    detail = _price(detail, MarkupResolver(markups, cfg), cfg)
    detail = apply_guardrails(detail, cfg)

    upload = _build_upload(detail, units, cfg)
    stats = _stats(detail, upload, gr2, cfg, started, decisions)

    return RunResult(
        detail=_order_detail(detail),
        upload=upload,
        exceptions=exceptions_view(detail),
        cost_audit=audit,
        summary=pd.DataFrame(list(stats.items()), columns=["Parameter", "Value"]),
        stats=stats,
    )


# ------------------------------------------------------------------ internals
def _apply_routing(
    costs: pd.DataFrame,
    routes: pd.DataFrame,
    my_cargo: pd.DataFrame | None,
    w10: pd.DataFrame,
    cfg: AppConfig,
) -> pd.DataFrame:
    """Fill in the non-receipt cost sources: My Cargo landed cost, a manual
    price, or the W10 standard cost. Receipt-costed rows pass through unchanged.

    ``cost_source`` on every row ends up one of: receipt, other_wh, mycargo,
    manual, w10, none.
    """
    base = costs.copy()
    if "cost_source" not in base.columns:
        base["cost_source"] = "receipt"
    by_sku = {r["sku"]: r for r in base.to_dict("records")}

    mc = my_cargo.set_index("sku") if my_cargo is not None and not my_cargo.empty else None
    mismatched = set(mycargo_unit_issues(my_cargo, w10)["sku"])
    buy = (
        w10.set_index("sku")["buy_price"]
        if "buy_price" in w10.columns
        else pd.Series(dtype="float64")
    )

    out_rows = []
    for r in routes.itertuples():
        sku = r.sku
        row = dict(by_sku.get(sku, {"sku": sku, "unit_cost": None, "cost_source": "none"}))
        row["sku"] = sku
        row["route"] = r.route
        row["expected_rate_pct"] = r.expected_rate_pct
        row["mc_unit_mismatch"] = sku in mismatched

        if r.is_import and r.is_manual_price and mc is not None and sku in mc.index:
            row.update(
                unit_cost=None, cost_source="manual",
                manual_price=float(mc.loc[sku, "manual_price"]),
                costing_method="my_cargo", cost_note="held at current price (My Cargo)",
            )
        elif r.is_import and mc is not None and sku in mc.index:
            row.update(
                unit_cost=float(mc.loc[sku, "landed_cost"]), cost_source="mycargo",
                costing_method="my_cargo", cost_note="goods + oversea freight (My Cargo)",
            )
        elif not r.is_import and (row.get("unit_cost") is None or pd.isna(row.get("unit_cost"))):
            b = buy.get(sku)
            if b is not None and pd.notna(b) and float(b) > 0:
                row.update(
                    unit_cost=float(b), cost_source="w10",
                    costing_method="w10_standard",
                    cost_note="W10 standard cost (no usable receipt)",
                )
        out_rows.append(row)

    priced_here = {r["sku"] for r in out_rows}
    leftover = base[~base["sku"].isin(priced_here)]
    routed = pd.DataFrame(out_rows)
    return pd.concat([routed, leftover], ignore_index=True) if not leftover.empty else routed


def _build_detail(w10: pd.DataFrame, costs: pd.DataFrame, sale_list) -> pd.DataFrame:
    """Scope = the sale list if one was supplied, otherwise everything in W10."""
    if sale_list is not None and not sale_list.empty:
        base = sale_list.merge(w10, on="sku", how="left", suffixes=("_sl", ""))
        # The sale list wins on any column both files carry. W10 prices are per
        # BASE unit and are frequently zero, so using them as the current price
        # would compare each new price against the wrong baseline — and blow up
        # the guardrails for every SKU sold in a parallel unit.
        for col in ("current_price", "product_name"):
            theirs = f"{col}_sl"
            if theirs in base.columns:
                base[col] = base[theirs].where(base[theirs].notna(), base.get(col))
                base = base.drop(columns=[theirs])
    else:
        base = w10.copy()
        base["sale_uom"] = base.get("uom")

    if "sale_uom" not in base.columns:
        base["sale_uom"] = base.get("uom")
    base["sale_uom"] = base["sale_uom"].fillna(base.get("uom"))

    out = base.merge(costs, on="sku", how="left")
    return out


def _resolve_sale_units(
    detail: pd.DataFrame,
    coefficients: dict[tuple[str, str], float],
    decisions: dict[str, "unit_review.Decision"],
    gr2: pd.DataFrame,
) -> pd.DataFrame:
    """Scale each SKU's base-unit cost into the unit it is actually sold in.

    Also stamps ``unit_status``, which drives the UNIT_* flags. The review sheet
    is the authority: anything sitting in config/unit_review.xlsx without a
    decision stays ``unverified`` — and therefore off the price upload — no
    matter which of the detector's rules put it there. A conflict that has never
    been through ``markup review`` is treated the same way, so a new one next
    month cannot quietly reach the ERP.
    """
    df = detail.copy()
    received = gr2.groupby("sku")["uom"].agg(
        lambda s: ", ".join(sorted({str(x).strip() for x in s.dropna()}))
    )
    df["gr_units_received"] = df["sku"].map(received)

    df["sale_coefficient"] = [
        coefficients.get((sku, str(uom).strip().lower()))
        for sku, uom in zip(df["sku"], df["sale_uom"])
    ]
    # unit_cost arrives per base unit; restate it per sale unit.
    df["unit_cost_base"] = df["unit_cost"]
    df["unit_cost"] = df["unit_cost_base"] * df["sale_coefficient"]

    statuses = []
    for row in df.itertuples():
        decision = decisions.get(row.sku)

        if decision is not None:
            if decision.decision == unit_review.EXCLUDE:
                statuses.append("excluded")
            elif decision.decision == unit_review.TREAT_AS:
                statuses.append("corrected")
            elif decision.decision == unit_review.ACCEPT:
                statuses.append("ok")
            else:                      # PENDING — listed for review, not yet decided
                statuses.append("unverified")
            continue

        if pd.isna(row.sale_coefficient):
            statuses.append("unknown_unit")
            continue

        # Not in the review sheet at all: only a live unit conflict holds it back.
        raw = row.gr_units_received
        got = (
            []
            if raw is None or (isinstance(raw, float) and pd.isna(raw))
            else [u.strip().lower() for u in str(raw).split(",") if u.strip()]
        )
        sale = str(row.sale_uom or "").strip().lower()
        statuses.append("ok" if (not got or not sale or sale in got) else "unverified")

    df["unit_status"] = statuses
    return df


def _price(detail: pd.DataFrame, resolver: MarkupResolver, cfg: AppConfig) -> pd.DataFrame:
    rows = []
    for _, row in detail.iterrows():
        rule = resolver.resolve(row)
        cost = row.get("unit_cost")
        current = row.get("current_price")

        # My Cargo manual-price rows: keep the current price, no re-mark-up.
        if row.get("cost_source") == "manual":
            keep = row.get("manual_price")
            keep = float(keep) if pd.notna(keep) else (float(current) if pd.notna(current) else None)
            change = (
                (keep - current) / current * 100.0
                if keep is not None and pd.notna(current) and current
                else None
            )
            rows.append({
                "markup_pct": None, "markup_basis": rule.basis, "markup_source": "manual",
                "markup_key": rule.key, "min_margin_pct": rule.min_margin_pct,
                "raw_price": None, "suggested_price": keep, "margin_pct": None,
                "change_pct": round(change, 2) if change is not None else None,
                "price_change": round(keep - current, 2)
                if keep is not None and pd.notna(current) else None,
            })
            continue

        raw = base = margin = None
        if pd.notna(cost):
            raw = apply_markup(float(cost), rule)
            base = apply_rounding(raw, pick_rule(float(cost), cfg))
            margin = gross_margin_pct(base, float(cost))

        change = (
            (base - current) / current * 100.0
            if base is not None and pd.notna(current) and current
            else None
        )

        rows.append(
            {
                "markup_pct": rule.pct,
                "markup_basis": rule.basis,
                "markup_source": rule.level,
                "markup_key": rule.key,
                "min_margin_pct": rule.min_margin_pct,
                "raw_price": round(raw, cfg.precision) if raw is not None else None,
                "suggested_price": base,
                "margin_pct": round(margin, 2) if margin is not None else None,
                "change_pct": round(change, 2) if change is not None else None,
                "price_change": round(base - current, 2)
                if base is not None and pd.notna(current)
                else None,
            }
        )
    return pd.concat([detail.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def _build_upload(detail: pd.DataFrame, units: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    """The lean ERP-import sheet: SKU, selling unit, sale price."""
    opts = cfg.upload_opts
    df = detail

    if opts.get("exclude_exceptions", True):
        df = df[~df["blocked"]]
    if opts.get("only_changed", True):
        moved = df["change_pct"].isna() | (df["change_pct"].abs() >= cfg.min_change_pct)
        df = df[moved]
    df = df[df["suggested_price"].notna()]

    if opts.get("include_parallel_rows", True) and cfg.parallel_enabled:
        rows = build_unit_rows(df, units, cfg)
    else:
        rows = df.assign(unit=df["sale_uom"], sale_price=df["suggested_price"])

    out = rows[["sku", "unit", "sale_price"]].copy()
    out.columns = ["SKU", "Unit", "Sale Price"]
    return out.dropna(subset=["Sale Price"]).reset_index(drop=True)


def _order_detail(detail: pd.DataFrame) -> pd.DataFrame:
    preferred = [
        "sku", "product_name", "department", "category", "subcategory", "brand",
        "sale_uom", "uom", "gr_units_received", "sale_coefficient", "unit_status",
        "route", "cost_source", "mc_unit_mismatch", "expected_rate_pct",
        "unit_cost_base",
        "unit_cost", "costing_method", "cost_note", "gr_lines_used", "gr_qty_used",
        "first_receipt", "last_receipt", "min_line_cost", "max_line_cost",
        "outliers_dropped",
        "markup_pct", "markup_basis", "markup_source", "markup_key",
        "raw_price", "suggested_price", "parallel_price",
        "current_price", "current_parallel_price", "price_change", "change_pct",
        "margin_pct", "min_margin_pct",
        "blocked", "flag_codes", "flag_reasons",
    ]
    cols = [c for c in preferred if c in detail.columns]
    cols += [c for c in detail.columns if c not in cols and c != "flags"]
    return detail[cols].reset_index(drop=True)


def _stats(detail, upload, gr2, cfg: AppConfig, started: dt.datetime, decisions=None) -> dict:
    priced = int(detail["suggested_price"].notna().sum())
    status = detail.get("unit_status")
    s = {
        "Run timestamp": started.strftime("%Y-%m-%d %H:%M:%S"),
        "As-of date": str(cfg.as_of_date),
        "Period (days)": cfg.period_days,
        "Costing window": f"{cfg.window_start} to {cfg.window_end}",
        "Costing method": cfg.method,
        "Fallback method": cfg.fallback_method or "(none)",
        "Layer coverage %": cfg.layer_coverage_pct,
        "Cost basis": cfg.cost_basis,
        "Markup basis": cfg.markup_basis,
        "Default markup %": cfg.default_pct,
        "Markup fallback chain": " > ".join(cfg.fallback_chain),
        "Rounding strategy": cfg.rounding.strategy,
        "Rounding step": cfg.rounding.step,
        "Rounding bands": len(cfg.rounding_bands),
        "Parallel unit pricing": "on" if cfg.parallel_enabled else "off",
        "Max increase %": cfg.max_increase_pct,
        "Max decrease %": cfg.max_decrease_pct,
        "Guardrail clamp": "on" if cfg.clamp else "off",
        "GR2 lines read": len(gr2),
        "SKUs in scope": len(detail),
        "SKUs priced": priced,
        "SKUs without cost": int(
            (detail["unit_cost"].isna() & detail["suggested_price"].isna()).sum()
        ),
        "SKUs flagged": int((detail["flag_codes"].astype(bool)).sum()),
        "SKUs blocked from upload": int(detail["blocked"].sum()),
        "SKUs on upload flagged for review": int(
            detail.loc[
                detail["flag_codes"].astype(bool) & ~detail["blocked"], "sku"
            ].isin(upload["SKU"]).sum()
        ),
        "Unit reviews outstanding": int((status == "unverified").sum()) if status is not None else 0,
        "Unit corrections applied": (
            sum(1 for d in (decisions or {}).values() if d.decision == unit_review.TREAT_AS)
        ),
        "SKUs excluded by review": int((status == "excluded").sum()) if status is not None else 0,
        "Upload rows": len(upload),
        "Average margin %": round(float(detail["margin_pct"].mean(skipna=True)), 2)
        if priced
        else None,
        "Currency": cfg.currency,
    }
    if cfg.wh_routing_enabled and "cost_source" in detail.columns:
        vc = detail["cost_source"].value_counts()
        s["Cost from receipts"] = int(vc.get("receipt", 0) + vc.get("other_wh", 0))
        s["Cost from My Cargo"] = int(vc.get("mycargo", 0))
        s["Cost from W10 standard"] = int(vc.get("w10", 0))
        s["Held at current price (manual)"] = int(vc.get("manual", 0))
    return s

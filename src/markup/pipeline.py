"""Run orchestration: load -> cost -> mark up -> round -> validate -> report."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import AppConfig
from .costing import cost_skus
from .io import load_gr2, load_markup_list, load_sale_list, load_w10
from .rules.markup import MarkupResolver, apply_markup, gross_margin_pct
from .rules.rounding import apply_rounding, pick_rule
from .uom import build_unit_rows, derive_parallel_price, normalise_factor
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
) -> RunResult:
    started = dt.datetime.now()

    gr2 = load_gr2(cfg.resolve(gr2_path), cfg.mapping)
    w10 = load_w10(cfg.resolve(w10_path), cfg.mapping)
    markups = load_markup_list(cfg.resolve(markup_path), cfg.mapping)
    sale_list = load_sale_list(cfg.resolve(sale_list_path) if sale_list_path else None, cfg.mapping)

    costs, audit = cost_skus(gr2, cfg)
    detail = _build_detail(w10, costs, sale_list)
    detail = _price(detail, MarkupResolver(markups, cfg), cfg)
    detail = apply_guardrails(detail, cfg)

    upload = _build_upload(detail, cfg)
    stats = _stats(detail, upload, gr2, cfg, started)

    return RunResult(
        detail=_order_detail(detail),
        upload=upload,
        exceptions=exceptions_view(detail),
        cost_audit=audit,
        summary=pd.DataFrame(list(stats.items()), columns=["Parameter", "Value"]),
        stats=stats,
    )


# ------------------------------------------------------------------ internals
def _build_detail(w10: pd.DataFrame, costs: pd.DataFrame, sale_list) -> pd.DataFrame:
    """Scope = the sale list if one was supplied, otherwise everything in W10."""
    if sale_list is not None and not sale_list.empty:
        base = sale_list.merge(w10, on="sku", how="left", suffixes=("_sl", ""))
        if "product_name_sl" in base.columns:
            base["product_name"] = base["product_name"].fillna(base["product_name_sl"])
            base = base.drop(columns=["product_name_sl"])
    else:
        base = w10.copy()
        base["sale_uom"] = base.get("uom")

    if "sale_uom" not in base.columns:
        base["sale_uom"] = base.get("uom")
    base["sale_uom"] = base["sale_uom"].fillna(base.get("uom"))

    out = base.merge(costs, on="sku", how="left")
    out["conversion_factor"] = out.get("conversion_factor", 1.0).map(normalise_factor)
    return out


def _price(detail: pd.DataFrame, resolver: MarkupResolver, cfg: AppConfig) -> pd.DataFrame:
    rows = []
    for _, row in detail.iterrows():
        rule = resolver.resolve(row)
        cost = row.get("unit_cost")

        raw = base = parallel = margin = None
        if pd.notna(cost):
            raw = apply_markup(float(cost), rule)
            base = apply_rounding(raw, pick_rule(float(cost), cfg))
            parallel = derive_parallel_price(base, raw, row.get("conversion_factor", 1.0), cfg)
            margin = gross_margin_pct(base, float(cost))

        current = row.get("current_price")
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
                "parallel_price": parallel,
                "margin_pct": round(margin, 2) if margin is not None else None,
                "change_pct": round(change, 2) if change is not None else None,
                "price_change": round(base - current, 2)
                if base is not None and pd.notna(current)
                else None,
            }
        )
    return pd.concat([detail.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def _build_upload(detail: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
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
        rows = build_unit_rows(df, cfg)
    else:
        rows = df.assign(unit=df["sale_uom"], sale_price=df["suggested_price"])

    out = rows[["sku", "unit", "sale_price"]].copy()
    out.columns = ["SKU", "Unit", "Sale Price"]
    return out.dropna(subset=["Sale Price"]).reset_index(drop=True)


def _order_detail(detail: pd.DataFrame) -> pd.DataFrame:
    preferred = [
        "sku", "product_name", "department", "category", "subcategory", "brand",
        "sale_uom", "uom", "parallel_uom", "conversion_factor",
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


def _stats(detail, upload, gr2, cfg: AppConfig, started: dt.datetime) -> dict:
    priced = int(detail["suggested_price"].notna().sum())
    return {
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
        "SKUs without cost": int(detail["unit_cost"].isna().sum()),
        "SKUs flagged": int((detail["flag_codes"].astype(bool)).sum()),
        "SKUs blocked from upload": int(detail["blocked"].sum()),
        "Upload rows": len(upload),
        "Average margin %": round(float(detail["margin_pct"].mean(skipna=True)), 2)
        if priced
        else None,
        "Currency": cfg.currency,
    }

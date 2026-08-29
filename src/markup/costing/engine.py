"""Turns GR2 receipt lines into one costed row per SKU."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..config import AppConfig
from .base import CostResult, get_method

log = logging.getLogger(__name__)


def effective_cost(gr2: pd.DataFrame, cost_basis: str) -> pd.Series:
    """Per-unit cost, optionally including landed components."""
    base = gr2["unit_cost"].astype(float)
    if cost_basis != "landed_cost":
        return base
    qty = gr2["qty"].astype(float).replace(0, np.nan)
    landed = (
        gr2.get("freight", 0).fillna(0)
        + gr2.get("duty", 0).fillna(0)
        + gr2.get("other_landed", 0).fillna(0)
    ).astype(float)
    return (base + (landed / qty).fillna(0.0)).astype(float)


def filter_window(gr2: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    """Keep only receipts inside ``[as_of_date - period_days, as_of_date]``."""
    start = pd.Timestamp(cfg.window_start)
    end = pd.Timestamp(cfg.window_end) + pd.Timedelta(days=1)
    df = gr2[(gr2["receipt_date"] >= start) & (gr2["receipt_date"] < end)].copy()
    log.info(
        "Period window %s .. %s (%d days): %d of %d GR lines in scope",
        cfg.window_start,
        cfg.window_end,
        cfg.period_days,
        len(df),
        len(gr2),
    )
    return df


def _drop_outliers(layers: pd.DataFrame, opts: dict) -> tuple[pd.DataFrame, int]:
    if not opts.get("enabled") or opts.get("method", "iqr") == "none":
        return layers, 0
    if len(layers) < int(opts.get("min_lines", 5)):
        return layers, 0

    costs = layers["effective_cost"].astype(float)
    method = opts.get("method", "iqr")
    threshold = float(opts.get("threshold", 1.5))

    if method == "zscore":
        sd = costs.std(ddof=0)
        keep = pd.Series(True, index=costs.index) if sd == 0 else (
            (costs - costs.mean()).abs() / sd <= threshold
        )
    else:  # iqr
        q1, q3 = costs.quantile(0.25), costs.quantile(0.75)
        iqr = q3 - q1
        keep = (
            pd.Series(True, index=costs.index)
            if iqr == 0
            else costs.between(q1 - threshold * iqr, q3 + threshold * iqr)
        )

    dropped = int((~keep).sum())
    return (layers[keep], dropped) if dropped < len(layers) else (layers, 0)


def cost_skus(gr2: pd.DataFrame, cfg: AppConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(cost_table, audit_table)`` — one row per SKU, plus the layer trail."""
    df = filter_window(gr2, cfg)
    df["effective_cost"] = effective_cost(df, cfg.cost_basis)

    if cfg.drop_nonpositive:
        before = len(df)
        df = df[(df["qty"] > 0) & (df["effective_cost"] > 0)]
        if before != len(df):
            log.info("Dropped %d non-positive GR line(s)", before - len(df))

    primary = get_method(cfg.method)
    fallback = get_method(cfg.fallback_method) if cfg.fallback_method else None

    results: list[CostResult] = []
    audit_rows: list[dict] = []

    for sku, layers in df.groupby("sku", sort=False):
        layers = layers.sort_values("receipt_date")
        clean, dropped = _drop_outliers(layers, cfg.outlier)

        try:
            unit_cost, note = primary.compute(clean, coverage_pct=cfg.layer_coverage_pct)
            method_used = cfg.method
        except Exception as exc:  # noqa: BLE001 — a bad SKU must not kill the run
            if fallback is None:
                results.append(CostResult(sku, None, cfg.method, note=f"failed: {exc}"))
                continue
            unit_cost, note = fallback.compute(clean, coverage_pct=100.0)
            method_used = f"{cfg.fallback_method} (fallback)"

        results.append(
            CostResult(
                sku=sku,
                unit_cost=round(float(unit_cost), cfg.precision),
                method=method_used,
                lines_used=len(clean),
                qty_used=float(clean["qty"].sum()),
                first_receipt=clean["receipt_date"].min(),
                last_receipt=clean["receipt_date"].max(),
                min_cost=float(clean["effective_cost"].min()),
                max_cost=float(clean["effective_cost"].max()),
                outliers_dropped=dropped,
                note=note,
            )
        )

        for _, row in layers.iterrows():
            audit_rows.append(
                {
                    "sku": sku,
                    "receipt_date": row["receipt_date"],
                    "receipt_no": row.get("receipt_no"),
                    "supplier": row.get("supplier"),
                    "qty": row["qty"],
                    "unit_cost": row["unit_cost"],
                    "freight": row.get("freight", 0),
                    "duty": row.get("duty", 0),
                    "other_landed": row.get("other_landed", 0),
                    "effective_cost": row["effective_cost"],
                    "used_in_costing": row.name in set(clean.index),
                }
            )

    cost_table = pd.DataFrame([r.as_row() for r in results])
    audit = pd.DataFrame(audit_rows)
    log.info("Costed %d SKU(s) using '%s'", len(cost_table), cfg.method)
    return cost_table, audit

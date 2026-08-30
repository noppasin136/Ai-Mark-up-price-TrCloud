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


def to_base_units(
    gr2: pd.DataFrame,
    coefficients: dict[tuple[str, str], float],
    remap: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Restate every receipt line in the SKU's BASE unit.

    Cost is recorded per received unit, which is not always the unit the item is
    sold in. W10's coefficient (base units per that unit) is the bridge:

        cost per base unit = unit cost / coefficient
        quantity in base units = quantity * coefficient

    ``remap`` applies approved corrections from the unit review first, for SKUs
    whose receipts are keyed against the wrong unit — the ถุงร้อน items are
    bought by the pack but entered as bag, so their receipts must be read as
    packs before any coefficient is applied.

    Lines whose unit W10 does not recognise get no coefficient and are dropped
    from costing rather than silently assumed to be base units; the SKU then
    shows up as uncosted instead of mispriced.
    """
    df = gr2.copy()
    df["uom_as_recorded"] = df["uom"]
    if remap:
        df["uom"] = [remap.get(sku, uom) for sku, uom in zip(df["sku"], df["uom"])]
        corrected = int((df["uom"] != df["uom_as_recorded"]).sum())
        if corrected:
            log.info("Unit review: %d GR line(s) re-read under a corrected unit", corrected)

    df["unit_coefficient"] = [
        coefficients.get((sku, str(uom).strip().lower()))
        for sku, uom in zip(df["sku"], df["uom"])
    ]

    unknown = df["unit_coefficient"].isna()
    if unknown.any():
        log.warning(
            "%d GR line(s) across %d SKU(s) use a unit W10 does not list — excluded from costing",
            int(unknown.sum()), df.loc[unknown, "sku"].nunique(),
        )
        df = df[~unknown]

    df["qty"] = df["qty"] * df["unit_coefficient"]
    df["effective_cost"] = df["effective_cost"] / df["unit_coefficient"]
    return df


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


def _audit_row(sku: str, row: pd.Series, used: bool) -> dict:
    return {
        "sku": sku,
        "receipt_date": row["receipt_date"],
        "receipt_no": row.get("receipt_no"),
        "supplier": row.get("supplier"),
        "warehouse": row.get("warehouse"),
        "qty": row["qty"],
        "unit_recorded": row.get("uom_as_recorded", row.get("uom")),
        "unit_costed_as": row.get("uom"),
        "unit_coefficient": row.get("unit_coefficient"),
        "unit_cost": row["unit_cost"],
        "freight": row.get("freight", 0),
        "duty": row.get("duty", 0),
        "other_landed": row.get("other_landed", 0),
        "effective_cost": row["effective_cost"],
        "used_in_costing": used,
    }


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


def cost_skus(
    gr2: pd.DataFrame,
    cfg: AppConfig,
    coefficients: dict[tuple[str, str], float] | None = None,
    unit_remap: dict[str, str] | None = None,
    routes: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(cost_table, audit_table)`` — one row per SKU, plus the layer trail.

    When ``coefficients`` is supplied the resulting ``unit_cost`` is per BASE
    unit; the caller scales it to whichever unit the item is sold in. Without
    them, costs stay in whatever unit each line was received in.

    With ``routes`` and ``warehouse_routing.enabled``, each SKU is costed only
    from its home warehouse (else the other head-office warehouse); storefront
    lines never count, and import SKUs are skipped here and costed from the
    My Cargo file by the caller.
    """
    df = filter_window(gr2, cfg)
    df["effective_cost"] = effective_cost(df, cfg.cost_basis)
    if coefficients:
        df = to_base_units(df, coefficients, unit_remap)

    if cfg.drop_nonpositive:
        before = len(df)
        df = df[(df["qty"] > 0) & (df["effective_cost"] > 0)]
        if before != len(df):
            log.info("Dropped %d non-positive GR line(s)", before - len(df))

    routing_on = cfg.wh_routing_enabled and routes is not None and "warehouse" in df.columns
    route_by_sku = {r.sku: r for r in routes.itertuples()} if routes is not None else {}
    head_office = {cfg.wh("main_warehouse"), cfg.wh("central_kitchen_warehouse")}
    if routing_on:
        storefront = ~df["warehouse"].isin(head_office)
        if storefront.any():
            log.info(
                "Warehouse routing: %d storefront GR line(s) excluded from costing",
                int(storefront.sum()),
            )

    primary = get_method(cfg.method)
    fallback = get_method(cfg.fallback_method) if cfg.fallback_method else None

    results: list[CostResult] = []
    audit_rows: list[dict] = []

    for sku, group in df.groupby("sku", sort=False):
        group = group.sort_values("receipt_date")
        r = route_by_sku.get(sku)
        if r is not None and getattr(r, "is_import", False):
            continue  # costed from the My Cargo file by the caller

        layers, cost_source = group, "receipt"
        if routing_on and r is not None and r.home_warehouse:
            home = group[group["warehouse"] == r.home_warehouse]
            other = group[group["warehouse"].isin(head_office)]
            if not home.empty:
                layers = home
            elif not other.empty:
                layers, cost_source = other, "other_wh"
            else:
                layers = group.iloc[0:0]  # only storefront receipts — no usable cost

        if layers.empty:
            results.append(
                CostResult(sku, None, cfg.method, cost_source="none",
                           note="no receipt in a head-office warehouse")
            )
            for _, row in group.iterrows():
                audit_rows.append(_audit_row(sku, row, used=False))
            continue

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
                cost_source=cost_source,
            )
        )

        used = set(clean.index)
        for _, row in group.iterrows():
            audit_rows.append(_audit_row(sku, row, used=row.name in used))

    cost_table = pd.DataFrame([r.as_row() for r in results])
    audit = pd.DataFrame(audit_rows)
    log.info("Costed %d SKU(s) using '%s'", len(cost_table), cfg.method)
    return cost_table, audit

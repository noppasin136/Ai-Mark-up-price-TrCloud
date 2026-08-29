"""Unit-of-measure handling.

W10 carries one row per SKU *and unit*, with a coefficient giving the number of
base units in that unit — 12 pieces to a box, 50 to a row. Costs are therefore
held per base unit inside the engine (see ``costing.engine.to_base_units``) and
scaled out to whichever unit a price is being published for.

The sale list names one selling unit per SKU. When ``parallel_unit.enabled`` is
on, every *other* unit W10 lists for that SKU is priced as well, so a product
sold by the piece can also be published by the box without a second run.
"""

from __future__ import annotations

import logging

import pandas as pd

from .config import AppConfig
from .rules.markup import MarkupRule, apply_markup
from .rules.rounding import apply_rounding, pick_rule

log = logging.getLogger(__name__)


def normalise_factor(value: object) -> float:
    """Coerce a conversion factor to a usable positive number (defaults to 1)."""
    try:
        factor = float(value)
    except (TypeError, ValueError):
        return 1.0
    return factor if factor > 0 else 1.0


def price_for_unit(
    unit_cost_base: float,
    coefficient: float,
    markup_pct: float,
    basis: str,
    cfg: AppConfig,
) -> tuple[float | None, float | None]:
    """Price one unit of a SKU. Returns ``(rounded, unrounded)``.

    Rounding is applied to this unit's own price rather than scaling an already
    rounded one, so a 24-pack does not inherit 24x the rounding error.
    """
    if pd.isna(unit_cost_base) or pd.isna(coefficient):
        return None, None

    cost = float(unit_cost_base) * float(coefficient)
    rule = MarkupRule(pct=markup_pct, level="", key="", basis=basis, min_margin_pct=0.0)
    raw = apply_markup(cost, rule)
    if cfg.bulk_discount_pct and coefficient > 1:
        raw *= 1 - cfg.bulk_discount_pct / 100.0
    return apply_rounding(raw, pick_rule(cost, cfg)), raw


def build_unit_rows(detail: pd.DataFrame, units: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    """One row per sellable unit: the sale unit, plus every other W10 unit.

    Rows are only produced for SKUs that priced cleanly — a SKU held back for
    review does not get a parallel row either.
    """
    base = detail.assign(
        unit=detail["sale_uom"],
        sale_price=detail["suggested_price"],
        unit_type="sale",
        unit_coefficient=detail["sale_coefficient"],
    )
    if not cfg.parallel_enabled or units is None or units.empty:
        return base.reset_index(drop=True)

    by_sku: dict[str, list[tuple[str, float]]] = {}
    for r in units.itertuples():
        by_sku.setdefault(r.sku, []).append((str(r.uom).strip(), normalise_factor(r.conversion_factor)))

    extra = []
    for row in detail.itertuples():
        if pd.isna(row.suggested_price) or pd.isna(row.unit_cost_base):
            continue
        sale = str(row.sale_uom or "").strip().lower()
        for unit, coefficient in by_sku.get(row.sku, []):
            if unit.lower() == sale:
                continue
            price, _ = price_for_unit(
                row.unit_cost_base, coefficient, row.markup_pct, row.markup_basis, cfg
            )
            if price is None:
                continue
            record = row._asdict()
            record.pop("Index", None)
            record.update(
                unit=unit,
                sale_price=price,
                unit_type="parallel",
                unit_coefficient=coefficient,
            )
            extra.append(record)

    if not extra:
        return base.reset_index(drop=True)

    log.info("Derived %d parallel-unit price(s) from W10", len(extra))
    out = pd.concat([base, pd.DataFrame(extra)], ignore_index=True)
    order = {"sale": 0, "parallel": 1}
    return (
        out.assign(_o=out["unit_type"].map(order))
        .sort_values(["sku", "_o"])
        .drop(columns="_o")
        .reset_index(drop=True)
    )

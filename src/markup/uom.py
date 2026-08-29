"""Unit-of-measure handling for the parallel (secondary) selling unit.

W10 carries a base UOM and a parallel UOM with a conversion factor — the number
of base units in one parallel unit (e.g. base ``PCS``, parallel ``BOX``,
factor 12). The parallel price is derived from the base price, then rounded on
its own so the pack price is a clean number in its own right rather than an
awkward multiple of a rounded unit price.
"""

from __future__ import annotations

import pandas as pd

from .config import AppConfig
from .rules.rounding import apply_rounding


def normalise_factor(value: object) -> float:
    """Coerce a conversion factor to a usable positive number (defaults to 1)."""
    try:
        factor = float(value)
    except (TypeError, ValueError):
        return 1.0
    return factor if factor > 0 else 1.0


def derive_parallel_price(
    base_price: float | None,
    unrounded_base: float | None,
    factor: float,
    cfg: AppConfig,
) -> float | None:
    """Price for one parallel unit.

    When ``parallel_unit.round_separately`` is true the calculation starts from
    the *unrounded* base price so rounding error is not multiplied by the pack
    size; otherwise the published base price is simply scaled up.
    """
    if not cfg.parallel_enabled or base_price is None:
        return None

    factor = normalise_factor(factor)
    if factor == 1.0:
        return None

    source = unrounded_base if (cfg.parallel_round_separately and unrounded_base) else base_price
    raw = source * factor
    if cfg.bulk_discount_pct:
        raw *= 1 - cfg.bulk_discount_pct / 100.0

    if not cfg.parallel_round_separately:
        return round(raw, 2)
    return apply_rounding(raw, cfg.parallel_rounding)


def build_unit_rows(detail: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    """Explode the detail frame into one row per sellable unit (base + parallel)."""
    base = detail.assign(
        unit=detail["sale_uom"].fillna(detail.get("uom")),
        sale_price=detail["suggested_price"],
        unit_type="base",
    )
    frames = [base]

    if cfg.parallel_enabled and "parallel_price" in detail.columns:
        par = detail[detail["parallel_price"].notna()].copy()
        if not par.empty:
            frames.append(
                par.assign(
                    unit=par["parallel_uom"],
                    sale_price=par["parallel_price"],
                    unit_type="parallel",
                )
            )

    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["sku", "unit_type"], ascending=[True, True]).reset_index(drop=True)

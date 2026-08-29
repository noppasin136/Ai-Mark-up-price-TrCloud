"""Price rounding strategies.

Each strategy is a small pure function registered by name, so adding a house
rule ("always end in 0 or 5", "never cross a 100 boundary") is a few lines here
plus a name in ``config.yaml`` — no changes anywhere else.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from ..config import RoundingRule

_STRATEGIES: dict[str, Callable[[float, RoundingRule], float]] = {}


def strategy(name: str) -> Callable[[Callable], Callable]:
    def _wrap(fn: Callable[[float, RoundingRule], float]) -> Callable:
        _STRATEGIES[name] = fn
        return fn

    return _wrap


def available() -> list[str]:
    return sorted(_STRATEGIES)


@strategy("none")
def _none(price: float, rule: RoundingRule) -> float:
    return round(price, 2)


@strategy("nearest")
def _nearest(price: float, rule: RoundingRule) -> float:
    step = rule.step
    if rule.direction == "up":
        return math.ceil(price / step) * step
    if rule.direction == "down":
        return math.floor(price / step) * step
    quantum = Decimal(str(step))
    return float((Decimal(str(price)) / quantum).quantize(Decimal("1"), ROUND_HALF_UP) * quantum)


@strategy("step_ceiling")
def _step_ceiling(price: float, rule: RoundingRule) -> float:
    return math.ceil(price / rule.step) * rule.step


@strategy("step_floor")
def _step_floor(price: float, rule: RoundingRule) -> float:
    return math.floor(price / rule.step) * rule.step


@strategy("psychological")
def _psychological(price: float, rule: RoundingRule) -> float:
    """Snap to the nearest charm ending at or above ``price``."""
    endings = sorted(rule.endings) or [0.99]
    base = math.floor(price)
    for end in endings:
        candidate = base + end
        if candidate >= price - 1e-9:
            return round(candidate, 2)
    return round(base + 1 + endings[0], 2)


def pick_rule(cost: float | None, cfg) -> RoundingRule:
    """Return the band rule matching ``cost``, else the global rule."""
    if cost is not None:
        for band in cfg.rounding_bands:
            if band.max_cost is None or cost <= float(band.max_cost):
                return band
    return cfg.rounding


def apply_rounding(price: float | None, rule: RoundingRule) -> float | None:
    if price is None or price != price:  # None or NaN
        return None
    fn = _STRATEGIES.get(rule.strategy)
    if fn is None:
        raise ValueError(f"Unknown rounding strategy '{rule.strategy}'. Available: {available()}")
    return round(fn(float(price), rule), 2)

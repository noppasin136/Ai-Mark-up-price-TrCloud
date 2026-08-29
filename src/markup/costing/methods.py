"""Concrete costing strategies.

GR2 is a receipts report, not a full inventory ledger: it records what came in,
never what went out. A textbook FIFO/LIFO needs issue transactions to consume
layers against. So within this engine:

  * ``fifo``  costs from the OLDEST receipt layers in the period
  * ``lifo``  costs from the NEWEST receipt layers in the period
  * ``costing.layer_coverage_pct`` controls how much of the period quantity is
    blended in. At 100 all three converge on the weighted average, which is why
    the shipped default is 30.

This is documented behaviour, not an approximation hidden in the code. If you
later export an issues/consumption report, add a true layer-consuming method
here and it will slot straight into the registry.
"""

from __future__ import annotations

import pandas as pd

from .base import CostingMethod, register


@register("weighted_average")
class WeightedAverage(CostingMethod):
    """Quantity-weighted mean cost across every receipt in the window."""

    def compute(self, layers: pd.DataFrame, *, coverage_pct: float = 100.0) -> tuple[float, str]:
        return self._wavg(layers), f"qty-weighted mean of {len(layers)} GR line(s)"


@register("fifo")
class Fifo(CostingMethod):
    """Blend of the oldest layers covering ``coverage_pct`` of period quantity."""

    def compute(self, layers: pd.DataFrame, *, coverage_pct: float = 100.0) -> tuple[float, str]:
        sel = self._take_coverage(layers, coverage_pct)
        return self._wavg(sel), f"oldest {coverage_pct:g}% of qty ({len(sel)} layer(s))"


@register("lifo")
class Lifo(CostingMethod):
    """Blend of the newest layers covering ``coverage_pct`` of period quantity."""

    def compute(self, layers: pd.DataFrame, *, coverage_pct: float = 100.0) -> tuple[float, str]:
        sel = self._take_coverage(layers.iloc[::-1], coverage_pct)
        return self._wavg(sel), f"newest {coverage_pct:g}% of qty ({len(sel)} layer(s))"


@register("last_cost")
class LastCost(CostingMethod):
    """The most recent receipt's unit cost. Most responsive to supplier moves."""

    def compute(self, layers: pd.DataFrame, *, coverage_pct: float = 100.0) -> tuple[float, str]:
        row = layers.iloc[-1]
        return float(row["effective_cost"]), f"last GR on {pd.to_datetime(row['receipt_date']).date()}"


@register("highest_cost")
class HighestCost(CostingMethod):
    """Worst-case cost in the window. Conservative / margin-protecting."""

    def compute(self, layers: pd.DataFrame, *, coverage_pct: float = 100.0) -> tuple[float, str]:
        return float(layers["effective_cost"].max()), "max GR line cost in window"


@register("lowest_cost")
class LowestCost(CostingMethod):
    """Best-case cost in the window. Aggressive / price-competitive."""

    def compute(self, layers: pd.DataFrame, *, coverage_pct: float = 100.0) -> tuple[float, str]:
        return float(layers["effective_cost"].min()), "min GR line cost in window"

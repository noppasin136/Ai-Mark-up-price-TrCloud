"""Costing strategy contract and registry.

Add a new costing method by subclassing :class:`CostingMethod` and decorating it
with ``@register("my_method")``. Nothing else needs to change — the name becomes
immediately valid in ``config.yaml`` under ``costing.method``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, ClassVar

import pandas as pd

_REGISTRY: dict[str, type["CostingMethod"]] = {}


def register(name: str) -> Callable[[type["CostingMethod"]], type["CostingMethod"]]:
    def _wrap(cls: type["CostingMethod"]) -> type["CostingMethod"]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _wrap


def get_method(name: str) -> "CostingMethod":
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"Unknown costing method '{name}'. Available: {sorted(_REGISTRY)}"
        ) from None


def available() -> list[str]:
    return sorted(_REGISTRY)


@dataclass
class CostResult:
    """The cost for one SKU, plus everything needed to defend the number."""

    sku: str
    unit_cost: float | None
    method: str
    lines_used: int = 0
    qty_used: float = 0.0
    first_receipt: object = None
    last_receipt: object = None
    min_cost: float | None = None
    max_cost: float | None = None
    outliers_dropped: int = 0
    note: str = ""
    detail: list[dict] = field(default_factory=list)

    def as_row(self) -> dict:
        return {
            "sku": self.sku,
            "unit_cost": self.unit_cost,
            "costing_method": self.method,
            "gr_lines_used": self.lines_used,
            "gr_qty_used": self.qty_used,
            "first_receipt": self.first_receipt,
            "last_receipt": self.last_receipt,
            "min_line_cost": self.min_cost,
            "max_line_cost": self.max_cost,
            "outliers_dropped": self.outliers_dropped,
            "cost_note": self.note,
        }


class CostingMethod(ABC):
    """Computes a single unit cost for one SKU from its receipt layers."""

    name: ClassVar[str] = "base"

    @abstractmethod
    def compute(self, layers: pd.DataFrame, *, coverage_pct: float = 100.0) -> tuple[float, str]:
        """Return ``(unit_cost, note)``.

        ``layers`` is that SKU's receipts within the period, sorted oldest first,
        carrying at minimum ``qty`` and ``effective_cost`` columns.
        """

    # -- shared helpers ----------------------------------------------------
    @staticmethod
    def _wavg(layers: pd.DataFrame) -> float:
        qty = layers["qty"].sum()
        if qty <= 0:
            return float(layers["effective_cost"].mean())
        return float((layers["qty"] * layers["effective_cost"]).sum() / qty)

    @staticmethod
    def _take_coverage(layers: pd.DataFrame, coverage_pct: float) -> pd.DataFrame:
        """Take layers from the top until ``coverage_pct`` of total quantity is met.

        Always returns at least one layer, and splits the boundary layer so the
        blend is exact rather than lumpy.
        """
        if coverage_pct >= 100:
            return layers
        total = layers["qty"].sum()
        if total <= 0:
            return layers
        target = total * coverage_pct / 100.0
        taken, running = [], 0.0
        for _, row in layers.iterrows():
            remaining = target - running
            if remaining <= 0:
                break
            row = row.copy()
            if row["qty"] > remaining:
                row["qty"] = remaining
            taken.append(row)
            running += row["qty"]
        return pd.DataFrame(taken) if taken else layers.head(1)

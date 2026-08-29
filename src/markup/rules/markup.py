"""Markup rule resolution.

Rules are keyed on product group / category. Each SKU walks
``markup.fallback_chain`` in order and takes the first rule that matches, so a
SKU-level exception beats a subcategory rule, which beats a category rule, and
so on down to the configured default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from ..config import AppConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkupRule:
    pct: float
    level: str
    key: str
    basis: str
    min_margin_pct: float

    @property
    def source(self) -> str:
        return "default" if self.level == "default" else f"{self.level}:{self.key}"


class MarkupResolver:
    """Indexes the markup list once, then answers per-SKU lookups cheaply."""

    def __init__(self, markup_list: pd.DataFrame, cfg: AppConfig):
        self.cfg = cfg
        self.chain = tuple(cfg.fallback_chain)
        self._index: dict[str, dict[str, MarkupRule]] = {}

        for _, row in markup_list.iterrows():
            level = str(row["level"]).strip().lower()
            key = str(row["key"]).strip().upper()
            self._index.setdefault(level, {})[key] = MarkupRule(
                pct=float(row["markup_pct"]),
                level=level,
                key=str(row["key"]).strip(),
                basis=str(row.get("basis") or cfg.markup_basis).lower(),
                min_margin_pct=float(
                    row["min_margin_pct"]
                    if pd.notna(row.get("min_margin_pct"))
                    else cfg.min_margin_pct
                ),
            )

        self._default = MarkupRule(
            pct=cfg.default_pct,
            level="default",
            key="*",
            basis=cfg.markup_basis,
            min_margin_pct=cfg.min_margin_pct,
        )
        log.info(
            "Markup rules indexed: %s",
            ", ".join(f"{lvl}={len(v)}" for lvl, v in self._index.items()) or "none",
        )

    def resolve(self, row: pd.Series) -> MarkupRule:
        for level in self.chain:
            if level == "default":
                return self._default
            value = row.get(level if level != "sku" else "sku")
            if pd.isna(value):
                continue
            hit = self._index.get(level, {}).get(str(value).strip().upper())
            if hit is not None:
                return hit
        return self._default


def apply_markup(cost: float, rule: MarkupRule) -> float:
    """Convert cost to an unrounded selling price under the rule's basis."""
    if rule.basis == "margin":
        if rule.pct >= 100:
            raise ValueError(f"margin-basis markup must be < 100% (got {rule.pct})")
        return cost / (1 - rule.pct / 100.0)
    return cost * (1 + rule.pct / 100.0)


def gross_margin_pct(price: float, cost: float) -> float:
    """Realised gross margin of a (possibly rounded) price."""
    return 0.0 if price in (0, None) else (price - cost) / price * 100.0

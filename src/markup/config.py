"""Configuration loading and validation.

Single source of truth for every tunable parameter. Nothing else in the codebase
reads YAML directly; everything receives a validated ``AppConfig``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VALID_COSTING = {
    "fifo",
    "lifo",
    "weighted_average",
    "last_cost",
    "highest_cost",
    "lowest_cost",
}
VALID_ROUNDING = {"none", "nearest", "step_ceiling", "step_floor", "psychological"}
VALID_BASIS = {"cost_plus", "margin"}


class ConfigError(ValueError):
    """Raised when config.yaml is internally inconsistent."""


def _get(d: dict, path: str, default: Any = None) -> Any:
    node: Any = d
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


@dataclass(frozen=True)
class RoundingRule:
    strategy: str = "nearest"
    step: float = 1.0
    direction: str = "half_up"
    endings: tuple[float, ...] = (0.95, 0.99)
    max_cost: float | None = None

    @classmethod
    def from_dict(cls, d: dict, base: "RoundingRule | None" = None) -> "RoundingRule":
        b = base or cls()
        return cls(
            strategy=d.get("strategy", b.strategy),
            step=float(d.get("step", b.step)),
            direction=d.get("direction", b.direction),
            endings=tuple(float(x) for x in d.get("endings", b.endings)),
            max_cost=d.get("max_cost", None),
        )


@dataclass
class AppConfig:
    raw: dict = field(repr=False)
    mapping: dict = field(repr=False)
    root: Path

    # run
    as_of_date: dt.date = dt.date.today()
    period_days: int = 90
    currency: str = "THB"
    precision: int = 4

    # costing
    method: str = "weighted_average"
    fallback_method: str | None = "last_cost"
    layer_coverage_pct: float = 30.0
    cost_basis: str = "landed_cost"
    drop_nonpositive: bool = True
    outlier: dict = field(default_factory=dict)

    # markup
    fallback_chain: tuple[str, ...] = ("sku", "subcategory", "category", "department", "default")
    default_pct: float = 30.0
    markup_basis: str = "cost_plus"
    min_margin_pct: float = 5.0
    markup_value_scale: float = 1.0

    # rounding
    rounding: RoundingRule = field(default_factory=RoundingRule)
    rounding_bands: tuple[RoundingRule, ...] = ()

    # parallel unit
    parallel_enabled: bool = True
    parallel_round_separately: bool = True
    parallel_rounding: RoundingRule = field(default_factory=RoundingRule)
    bulk_discount_pct: float = 0.0

    # guardrails
    max_increase_pct: float = 25.0
    max_decrease_pct: float = 10.0
    clamp: bool = False
    flag_price_decrease: bool = True
    min_change_pct: float = 0.5

    # output
    out_dir: Path = Path("data/output")
    out_filename: str = "markup_{method}_{period}d_{timestamp}.xlsx"
    sheets: tuple[str, ...] = ("price_upload", "detail", "exceptions", "cost_audit", "run_summary")
    upload_opts: dict = field(default_factory=dict)
    freeze_header: bool = True
    autofilter: bool = True

    log_level: str = "INFO"
    log_file: str | None = None

    # ---------------------------------------------------------------- loading
    @classmethod
    def load(
        cls,
        config_path: str | Path = "config/config.yaml",
        mapping_path: str | Path = "config/column_mapping.yaml",
        overrides: dict | None = None,
    ) -> "AppConfig":
        config_path = Path(config_path)
        root = config_path.resolve().parent.parent
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        mapping = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8")) or {}

        for key, value in (overrides or {}).items():
            if value is None:
                continue
            _assign(raw, key, value)

        as_of = _get(raw, "run.as_of_date")
        if isinstance(as_of, str):
            as_of_date = dt.date.fromisoformat(as_of)
        elif isinstance(as_of, dt.datetime):
            as_of_date = as_of.date()
        elif isinstance(as_of, dt.date):
            as_of_date = as_of
        else:
            as_of_date = dt.date.today()

        base_round = RoundingRule.from_dict(_get(raw, "rounding", {}) or {})
        bands = (
            tuple(
                RoundingRule.from_dict(b, base_round)
                for b in (_get(raw, "rounding.bands") or [])
            )
            if _get(raw, "rounding.use_bands", False)
            else ()
        )
        par = _get(raw, "parallel_unit", {}) or {}

        cfg = cls(
            raw=raw,
            mapping=mapping,
            root=root,
            as_of_date=as_of_date,
            period_days=int(_get(raw, "run.period_days", 90)),
            currency=_get(raw, "run.currency", "THB"),
            precision=int(_get(raw, "run.precision", 4)),
            method=str(_get(raw, "costing.method", "weighted_average")).lower(),
            fallback_method=(
                str(_get(raw, "costing.fallback_method")).lower()
                if _get(raw, "costing.fallback_method")
                else None
            ),
            layer_coverage_pct=float(_get(raw, "costing.layer_coverage_pct", 30)),
            cost_basis=_get(raw, "costing.cost_basis", "landed_cost"),
            drop_nonpositive=bool(_get(raw, "costing.drop_nonpositive", True)),
            outlier=_get(raw, "costing.outlier_filter", {}) or {},
            fallback_chain=tuple(
                _get(raw, "markup.fallback_chain")
                or ["sku", "subcategory", "category", "department", "default"]
            ),
            default_pct=float(_get(raw, "markup.default_pct", 30.0)),
            markup_basis=str(_get(raw, "markup.basis", "cost_plus")).lower(),
            markup_value_scale=float(_get(raw, "markup.value_scale", 1.0)),
            min_margin_pct=float(_get(raw, "markup.min_margin_pct", 5.0)),
            rounding=base_round,
            rounding_bands=bands,
            parallel_enabled=bool(par.get("enabled", True)),
            parallel_round_separately=bool(par.get("round_separately", True)),
            parallel_rounding=RoundingRule.from_dict(par, base_round),
            bulk_discount_pct=float(par.get("bulk_discount_pct", 0.0)),
            max_increase_pct=float(_get(raw, "guardrails.max_increase_pct", 25.0)),
            max_decrease_pct=float(_get(raw, "guardrails.max_decrease_pct", 10.0)),
            clamp=bool(_get(raw, "guardrails.clamp", False)),
            flag_price_decrease=bool(_get(raw, "guardrails.flag_price_decrease", True)),
            min_change_pct=float(_get(raw, "guardrails.min_change_pct", 0.5)),
            out_dir=Path(_get(raw, "output.directory", "data/output")),
            out_filename=_get(
                raw, "output.filename", "markup_{method}_{period}d_{timestamp}.xlsx"
            ),
            sheets=tuple(
                _get(raw, "output.sheets")
                or ["price_upload", "detail", "exceptions", "cost_audit", "run_summary"]
            ),
            upload_opts=_get(raw, "output.price_upload", {}) or {},
            freeze_header=bool(_get(raw, "output.freeze_header", True)),
            autofilter=bool(_get(raw, "output.autofilter", True)),
            log_level=str(_get(raw, "logging.level", "INFO")).upper(),
            log_file=_get(raw, "logging.file"),
        )
        cfg.validate()
        return cfg

    # ------------------------------------------------------------- validation
    def validate(self) -> None:
        if self.method not in VALID_COSTING:
            raise ConfigError(
                f"costing.method '{self.method}' is not one of {sorted(VALID_COSTING)}"
            )
        if self.fallback_method and self.fallback_method not in VALID_COSTING:
            raise ConfigError(f"costing.fallback_method '{self.fallback_method}' is invalid")
        if self.period_days <= 0:
            raise ConfigError("run.period_days must be a positive integer")
        if not 0 < self.layer_coverage_pct <= 100:
            raise ConfigError("costing.layer_coverage_pct must be in (0, 100]")
        if self.markup_value_scale <= 0:
            raise ConfigError("markup.value_scale must be greater than zero")
        if self.markup_basis not in VALID_BASIS:
            raise ConfigError(f"markup.basis must be one of {sorted(VALID_BASIS)}")
        if self.markup_basis == "margin" and self.default_pct >= 100:
            raise ConfigError("markup.default_pct must be < 100 when basis is 'margin'")
        for rule in (self.rounding, self.parallel_rounding, *self.rounding_bands):
            if rule.strategy not in VALID_ROUNDING:
                raise ConfigError(
                    f"rounding strategy '{rule.strategy}' is not one of {sorted(VALID_ROUNDING)}"
                )
            if rule.strategy in {"nearest", "step_ceiling", "step_floor"} and rule.step <= 0:
                raise ConfigError("rounding.step must be greater than zero")

    # ---------------------------------------------------------------- helpers
    @property
    def window_start(self) -> dt.date:
        return self.as_of_date - dt.timedelta(days=self.period_days)

    @property
    def window_end(self) -> dt.date:
        return self.as_of_date

    def resolve(self, path: str | Path) -> Path:
        p = Path(path)
        return p if p.is_absolute() else self.root / p


def _assign(d: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = d
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value

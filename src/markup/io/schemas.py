"""Canonical column contracts and header resolution.

The ERP exports arrive with whatever headers the report writer chose. Every
loader passes through :func:`resolve_columns`, which renames the incoming frame
to canonical names using ``config/column_mapping.yaml`` — so the rest of the
codebase never sees an ERP-specific header.
"""

from __future__ import annotations

import re

import pandas as pd

# Columns a dataset cannot function without.
REQUIRED: dict[str, tuple[str, ...]] = {
    "gr2": ("sku", "receipt_date", "qty", "unit_cost"),
    "w10": ("sku", "current_price"),
    "markup_list": ("key", "markup_pct"),
    "sale_list": ("sku",),
}

# Columns coerced to numeric / datetime on load.
NUMERIC: dict[str, tuple[str, ...]] = {
    "gr2": ("qty", "unit_cost", "total_cost", "freight", "duty", "other_landed"),
    "w10": ("current_price", "parallel_price", "conversion_factor"),
    "markup_list": ("markup_pct", "min_margin_pct"),
    "sale_list": (),
}
DATES: dict[str, tuple[str, ...]] = {"gr2": ("receipt_date",)}


class SchemaError(ValueError):
    """Raised when a required column cannot be located in an input file."""


def _norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def resolve_columns(df: pd.DataFrame, dataset: str, mapping: dict) -> pd.DataFrame:
    """Rename ``df`` in place to canonical names; raise if a required one is absent."""
    spec = (mapping.get(dataset) or {}).get("columns") or {}
    lookup = {_norm(c): c for c in df.columns}

    rename: dict[str, str] = {}
    for canonical, candidates in spec.items():
        for cand in candidates if isinstance(candidates, list) else [candidates]:
            hit = lookup.get(_norm(cand))
            if hit is not None and hit not in rename:
                rename[hit] = canonical
                break

    out = df.rename(columns=rename)

    missing = [c for c in REQUIRED.get(dataset, ()) if c not in out.columns]
    if missing:
        raise SchemaError(
            f"[{dataset}] missing required column(s): {', '.join(missing)}.\n"
            f"  Found headers: {list(df.columns)}\n"
            f"  Fix: add the real header name to config/column_mapping.yaml "
            f"under {dataset}.columns."
        )

    for col in NUMERIC.get(dataset, ()):
        if col in out.columns:
            out[col] = pd.to_numeric(
                out[col].astype(str).str.replace(r"[,\s]", "", regex=True), errors="coerce"
            )
    for col in DATES.get(dataset, ()):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    if "sku" in out.columns:
        out["sku"] = out["sku"].astype(str).str.strip()

    keep = [c for c in out.columns if c in set(spec.keys())]
    return out[keep].copy()

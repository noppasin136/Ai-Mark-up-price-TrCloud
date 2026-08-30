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
    "w10": ("sku", "uom"),
    "markup_list": ("key", "markup_pct"),
    "sale_list": ("sku",),
    "my_cargo": ("sku", "product_cost"),
}

# Columns coerced to numeric / datetime on load.
NUMERIC: dict[str, tuple[str, ...]] = {
    "gr2": ("qty", "unit_cost", "total_cost", "freight", "duty", "other_landed"),
    "w10": ("current_price", "buy_price", "conversion_factor", "is_base_unit"),
    "markup_list": ("markup_pct", "min_margin_pct", "current_price"),
    "sale_list": ("current_price",),
    "my_cargo": ("product_cost", "oversea_transport", "vat", "inland_transport", "manual_price"),
}
DATES: dict[str, tuple[str, ...]] = {"gr2": ("receipt_date",)}


class SchemaError(ValueError):
    """Raised when a required column cannot be located in an input file."""


def _norm(s: object) -> str:
    """Fold a header for comparison: lowercase, strip spaces and punctuation.

    Unicode-aware on purpose — ``[^a-z0-9]`` would erase Thai headers entirely
    and collapse every one of them to the same empty string.
    """
    return re.sub(r"[\W_]+", "", str(s).strip().lower(), flags=re.UNICODE)


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

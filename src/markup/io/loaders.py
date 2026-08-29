"""Readers for the four inputs: GR2, W10, the markup list and the sale list."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .schemas import resolve_columns

log = logging.getLogger(__name__)


def _read_any(path: str | Path, sheet: object = 0, header_row: int = 0) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Input file not found: {path}\n"
            f"  Fix: drop the export into data/input/ and check the path in config."
        )
    if path.suffix.lower() in {".csv", ".txt"}:
        return pd.read_csv(path, header=header_row, dtype=str, keep_default_na=False, na_values=[""])
    return pd.read_excel(path, sheet_name=sheet, header=header_row, dtype=object)


def _load(path: str | Path, dataset: str, mapping: dict) -> pd.DataFrame:
    spec = mapping.get(dataset) or {}
    df = _read_any(path, spec.get("sheet", 0), int(spec.get("header_row", 0)))
    df = df.dropna(how="all")
    out = resolve_columns(df, dataset, mapping)
    log.info("Loaded %s: %d rows from %s", dataset, len(out), Path(path).name)
    return out


def load_gr2(path: str | Path, mapping: dict) -> pd.DataFrame:
    """Goods receipts — one row per receipt line. The cost source."""
    df = _load(path, "gr2", mapping)
    for col in ("freight", "duty", "other_landed"):
        if col not in df.columns:
            df[col] = 0.0
    df[["freight", "duty", "other_landed"]] = df[["freight", "duty", "other_landed"]].fillna(0.0)
    df = df.dropna(subset=["sku", "receipt_date", "qty", "unit_cost"])
    return df.sort_values(["sku", "receipt_date"]).reset_index(drop=True)


def load_w10(path: str | Path, mapping: dict) -> pd.DataFrame:
    """Current selling prices, UOM, parallel unit and product hierarchy."""
    df = _load(path, "w10", mapping)
    if "conversion_factor" in df.columns:
        df["conversion_factor"] = df["conversion_factor"].fillna(1.0).replace(0, 1.0)
    else:
        df["conversion_factor"] = 1.0
    for col in ("category", "subcategory", "department", "parallel_uom", "uom"):
        if col not in df.columns:
            df[col] = pd.NA
    # Disambiguate: the ERP's existing parallel price is the CURRENT one; the
    # engine computes its own `parallel_price` later.
    if "parallel_price" in df.columns:
        df = df.rename(columns={"parallel_price": "current_parallel_price"})
    dupes = int(df["sku"].duplicated().sum())
    if dupes:
        log.warning("W10 has %d duplicate SKU rows — keeping the first of each", dupes)
        df = df.drop_duplicates(subset=["sku"], keep="first")
    return df.reset_index(drop=True)


def load_markup_list(path: str | Path, mapping: dict) -> pd.DataFrame:
    """Markup master. ``level`` defaults to 'category' when the column is absent."""
    df = _load(path, "markup_list", mapping)
    if "level" not in df.columns:
        df["level"] = "category"
    df["level"] = df["level"].fillna("category").astype(str).str.strip().str.lower()
    df["key"] = df["key"].astype(str).str.strip()
    df = df.dropna(subset=["markup_pct"])
    return df.reset_index(drop=True)


def load_sale_list(path: str | Path | None, mapping: dict) -> pd.DataFrame | None:
    """Optional scope list: which SKUs to price, and the unit they sell in."""
    if not path:
        return None
    df = _load(path, "sale_list", mapping)
    if "include" in df.columns:
        mask = ~df["include"].astype(str).str.strip().str.lower().isin(
            {"n", "no", "false", "0", "exclude"}
        )
        df = df[mask]
    return df.drop_duplicates(subset=["sku"]).reset_index(drop=True)

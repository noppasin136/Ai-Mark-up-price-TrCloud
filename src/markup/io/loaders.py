"""Readers for the four inputs: GR2, W10, the markup list and the sale list."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from openpyxl.worksheet import _reader

from .schemas import resolve_columns

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The ERP writes the literal text "null" into some numeric cells. openpyxl
# raises ValueError mid-parse on those, which takes the whole file down. Recover
# them as blanks instead and count them, so a genuinely corrupt export is still
# visible in the log rather than silently tolerated.
# ---------------------------------------------------------------------------
_orig_cast_number = _reader._cast_number
_recovered_cells = {"count": 0}


def _tolerant_cast_number(value):
    try:
        return _orig_cast_number(value)
    except (ValueError, TypeError):
        _recovered_cells["count"] += 1
        return None


_reader._cast_number = _tolerant_cast_number


def recovered_cell_count() -> int:
    """How many malformed numeric cells have been recovered as blanks so far."""
    return _recovered_cells["count"]


def _read_any(path: str | Path, sheet: object = 0, header_row: int = 0) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Input file not found: {path}\n"
            f"  Fix: drop the export into data/input/ and check the path in config."
        )
    if path.suffix.lower() in {".csv", ".txt"}:
        return pd.read_csv(path, header=header_row, dtype=str, keep_default_na=False, na_values=[""])

    try:
        return pd.read_excel(path, sheet_name=sheet, header=header_row, dtype=object)
    except ValueError as exc:
        if "Worksheet named" not in str(exc):
            raise
        # The configured sheet is missing — fall back to the first one, but say
        # so, since a renamed sheet is usually a changed report, not a non-event.
        available = pd.ExcelFile(path).sheet_names
        log.warning(
            "%s has no sheet '%s' (found: %s) — reading the first sheet instead",
            path.name, sheet, ", ".join(available),
        )
        return pd.read_excel(path, sheet_name=0, header=header_row, dtype=object)


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


def load_w10_units(path: str | Path, mapping: dict) -> pd.DataFrame:
    """Every sellable unit of every SKU — W10 carries one row per SKU *and unit*.

    This is the authority on which units a SKU may be sold in, and on the
    coefficient (base units per that unit) needed to convert costs between them.
    """
    df = _load(path, "w10", mapping)
    if "conversion_factor" not in df.columns:
        df["conversion_factor"] = 1.0
    df["conversion_factor"] = df["conversion_factor"].fillna(1.0).replace(0, 1.0)
    if "is_base_unit" not in df.columns:
        # No flag exported: infer the base unit as the one with coefficient 1.
        df["is_base_unit"] = (df["conversion_factor"] == 1).astype(int)
    df["is_base_unit"] = df["is_base_unit"].fillna(0).astype(int)
    df["uom"] = df["uom"].astype(str).str.strip()
    for col in ("category", "subcategory", "department", "product_name"):
        if col not in df.columns:
            df[col] = pd.NA
    if "current_price" not in df.columns:
        df["current_price"] = pd.NA
    return df.reset_index(drop=True)


def load_w10(path: str | Path, mapping: dict) -> pd.DataFrame:
    """One row per SKU: its BASE unit and the product hierarchy.

    Selected on the ``is_base_unit`` flag rather than on row order — W10 happens
    to list base units first today, but that is an accident of the export.
    """
    units = load_w10_units(path, mapping)
    base = units[units["is_base_unit"] == 1].copy()

    missing = set(units["sku"]) - set(base["sku"])
    if missing:
        log.warning(
            "%d SKU(s) have no base-unit row in W10; falling back to their "
            "lowest-coefficient unit", len(missing),
        )
        fallback = (
            units[units["sku"].isin(missing)]
            .sort_values("conversion_factor")
            .drop_duplicates(subset=["sku"], keep="first")
        )
        base = pd.concat([base, fallback], ignore_index=True)

    dupes = int(base["sku"].duplicated().sum())
    if dupes:
        log.warning("W10 marks %d SKU(s) with more than one base unit — keeping the first", dupes)
        base = base.drop_duplicates(subset=["sku"], keep="first")

    log.info("W10: %d unit rows across %d SKU(s)", len(units), base["sku"].nunique())
    return base.reset_index(drop=True)


def unit_table(w10_units: pd.DataFrame) -> dict[tuple[str, str], float]:
    """(sku, lowercased unit) -> coefficient, for cost conversion."""
    return {
        (r.sku, str(r.uom).strip().lower()): float(r.conversion_factor)
        for r in w10_units.itertuples()
    }


def load_markup_list(path: str | Path, mapping: dict, value_scale: float = 1.0) -> pd.DataFrame:
    """Markup master.

    ``value_scale`` converts the file's units into percent: set it to 100 when
    the list stores fractions (0.12 meaning 12%), which is how this ERP's export
    is written. ``level`` defaults to 'sku' when the column is absent, because a
    list with one row per product code is a per-SKU list.
    """
    df = _load(path, "markup_list", mapping)
    if value_scale != 1.0:
        df["markup_pct"] = df["markup_pct"] * value_scale
        log.info("Markup values scaled by x%g (file stores fractions, engine uses percent)",
                 value_scale)
    if "level" not in df.columns:
        df["level"] = "sku"
    df["level"] = df["level"].fillna("category").astype(str).str.strip().str.lower()
    df["key"] = df["key"].astype(str).str.strip()
    df = df.dropna(subset=["markup_pct"])
    return df.reset_index(drop=True)


def load_my_cargo(path: str | Path | None, mapping: dict) -> pd.DataFrame | None:
    """Import landed cost — one row per imported SKU.

    ``landed_cost`` = ``product_cost`` + ``oversea_transport`` (+ ``vat`` +
    ``inland_transport`` if those columns are ever filled), already per base
    unit. Rows with no cost but a ``manual_price`` are kept: the pricing step
    holds those SKUs at their current price rather than re-marking them up.

    The tab is renamed every upload, so ``my_cargo.sheet`` in the mapping is 0 —
    the first sheet is always read.
    """
    if not path:
        return None
    df = _load(path, "my_cargo", mapping)

    for col in ("oversea_transport", "vat", "inland_transport"):
        if col not in df.columns:
            df[col] = 0.0
    if "manual_price" not in df.columns:
        df["manual_price"] = pd.NA

    df["landed_cost"] = (
        df["product_cost"].fillna(0.0)
        + df["oversea_transport"].fillna(0.0)
        + df["vat"].fillna(0.0)
        + df["inland_transport"].fillna(0.0)
    )
    df["has_landed_cost"] = df["product_cost"].notna() & (df["landed_cost"] > 0)
    df["has_manual_price"] = df["manual_price"].notna() & (df["manual_price"] > 0)

    dupes = sorted(set(df.loc[df["sku"].duplicated(), "sku"]))
    if dupes:
        log.warning(
            "My Cargo: %d SKU(s) on more than one row — keeping the first: %s",
            len(dupes), ", ".join(dupes),
        )
        df = df.drop_duplicates(subset=["sku"], keep="first")

    unusable = df[~df["has_landed_cost"] & ~df["has_manual_price"]]
    if not unusable.empty:
        log.warning(
            "My Cargo: %d row(s) carry neither a cost nor a manual price — ignored: %s",
            len(unusable), ", ".join(unusable["sku"]),
        )
        df = df[df["has_landed_cost"] | df["has_manual_price"]]

    log.info(
        "My Cargo: %d SKU(s) (%d costed, %d manual-price only)",
        len(df),
        int(df["has_landed_cost"].sum()),
        int((~df["has_landed_cost"] & df["has_manual_price"]).sum()),
    )
    return df.reset_index(drop=True)


def mycargo_unit_issues(
    my_cargo: pd.DataFrame | None, w10_base: pd.DataFrame
) -> pd.DataFrame:
    """My Cargo rows whose ``unit`` is not the SKU's base unit in W10.

    The landed cost is quoted per base unit; a different unit here (``503-0071``
    keyed as ``bag`` where the base is ``pack``) would scale the cost wrongly, so
    the pricing step holds these SKUs back until the file is fixed at source.
    """
    cols = ["sku", "my_cargo_unit", "w10_base_unit"]
    if my_cargo is None or my_cargo.empty or "unit" not in my_cargo.columns:
        return pd.DataFrame(columns=cols)

    base_unit = {
        r.sku: str(r.uom).strip().lower() for r in w10_base.itertuples()
    }
    rows = []
    for r in my_cargo.itertuples():
        got = str(getattr(r, "unit", "") or "").strip()
        want = base_unit.get(r.sku)
        if not got or want is None:
            continue
        if got.lower() != want:
            rows.append({"sku": r.sku, "my_cargo_unit": got, "w10_base_unit": want})
    return pd.DataFrame(rows, columns=cols)


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

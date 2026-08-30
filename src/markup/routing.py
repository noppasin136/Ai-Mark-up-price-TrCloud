"""Warehouse-aware routing: how to cost and price each in-scope SKU.

One row per SKU, decided from the ``markup_list`` Category, the GR2 supplier
(Z Smart), and the My Cargo file. Full spec: docs/COSTING_MODEL.md §6.

``route``:
  * ``import``          — in the My Cargo file; cost = landed cost from that file
  * ``central_kitchen`` — CK / Central Kitchen category, or Z Smart majority
  * ``warehouse``       — everything else (WH / Chilled / Freeze)

The cost then comes from the route's home warehouse, else the other head-office
warehouse, else the W10 standard cost (handled in the pipeline).
"""

from __future__ import annotations

import logging

import pandas as pd

from .config import AppConfig

log = logging.getLogger(__name__)


def _z_smart_majority(gr2: pd.DataFrame, needle: str) -> set[str]:
    """SKUs where the Z Smart supplier is over half the received quantity."""
    if gr2.empty or "supplier" not in gr2.columns:
        return set()
    df = gr2[["sku", "supplier", "qty"]].copy()
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0.0).clip(lower=0)
    is_z = df["supplier"].astype(str).str.contains(needle, case=False, na=False, regex=False)
    total = df.groupby("sku")["qty"].sum()
    z_qty = df[is_z].groupby("sku")["qty"].sum().reindex(total.index, fill_value=0.0)
    return set(total.index[(total > 0) & (z_qty > 0.5 * total)])


def build_routes(
    scope: list[str],
    markups: pd.DataFrame,
    my_cargo: pd.DataFrame | None,
    gr2: pd.DataFrame,
    cfg: AppConfig,
) -> pd.DataFrame:
    """Return one row per SKU in ``scope`` with its route and expected rate."""
    main = cfg.wh("main_warehouse", "ST0001")
    ck_wh = cfg.wh("central_kitchen_warehouse", "ST0002")
    ck_cats = {str(c).strip().lower() for c in cfg.wh("central_kitchen_categories", [])}
    rate_by_cat = {
        str(k).strip().lower(): float(v)
        for k, v in (cfg.wh("category_rate_pct", {}) or {}).items()
    }
    import_rate = float(cfg.wh("import_rate_pct", 25.0))

    category = {
        str(r.key).strip(): (str(r.category).strip() if pd.notna(getattr(r, "category", None)) else "")
        for r in markups.itertuples()
    } if "category" in markups.columns else {}

    cargo_skus = set(my_cargo["sku"]) if my_cargo is not None and not my_cargo.empty else set()
    manual_skus = (
        set(my_cargo.loc[my_cargo["has_manual_price"] & ~my_cargo["has_landed_cost"], "sku"])
        if my_cargo is not None and not my_cargo.empty
        else set()
    )

    z_needle = cfg.wh("z_smart_supplier_match", "")
    z_smart = (
        _z_smart_majority(gr2, z_needle)
        if z_needle and cfg.wh("z_smart_needs_majority", True)
        else set()
    )

    rows = []
    for sku in scope:
        cat = category.get(sku, "")
        cat_l = cat.strip().lower()
        is_import = sku in cargo_skus

        if is_import:
            route, home, rate = "import", None, import_rate
        elif sku in z_smart or cat_l in ck_cats:
            route, home, rate = "central_kitchen", ck_wh, rate_by_cat.get(cat_l, import_rate)
        else:
            route, home, rate = "warehouse", main, rate_by_cat.get(cat_l)

        rows.append({
            "sku": sku,
            "mc_category": cat,
            "route": route,
            "home_warehouse": home,
            "expected_rate_pct": rate,
            "is_import": is_import,
            "is_manual_price": sku in manual_skus,
            "z_smart_majority": sku in z_smart,
        })

    routes = pd.DataFrame(rows)
    if not routes.empty:
        log.info(
            "Routes: %d import, %d central kitchen (%d via Z Smart), %d warehouse",
            int((routes["route"] == "import").sum()),
            int((routes["route"] == "central_kitchen").sum()),
            int(routes["z_smart_majority"].sum()),
            int((routes["route"] == "warehouse").sum()),
        )
    return routes

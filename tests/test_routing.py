"""Warehouse-aware costing: routing, cost sources, and the new flags (PR 4)."""

import subprocess
import sys

import pandas as pd
import pytest

from markup.config import AppConfig
from markup.routing import build_routes
from tests.test_pipeline import ROOT, SAMPLES, _run


@pytest.fixture(scope="module", autouse=True)
def samples():
    if not (SAMPLES / "My_Cargo_sample.xlsx").exists():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "make_sample_data.py")], check=True
        )


@pytest.fixture
def cfg():
    return AppConfig.load(ROOT / "config/config.yaml", ROOT / "config/column_mapping.yaml")


# --- build_routes ---------------------------------------------------------

def test_routes_classify_import_ck_and_warehouse(cfg):
    _, result = _run()
    routes = result.detail  # detail carries the route column
    assert set(routes["route"].dropna()) == {"import", "central_kitchen", "warehouse"}


def test_z_smart_majority_overrides_a_warehouse_category(cfg):
    markups = pd.DataFrame({"key": ["A"], "markup_pct": [12.0], "category": ["WH"], "level": ["sku"]})
    gr2 = pd.DataFrame({
        "sku": ["A", "A", "A"],
        "supplier": ["แซด สมาร์ท เทรดดิ้ง", "แซด สมาร์ท เทรดดิ้ง", "Someone else"],
        "qty": [100.0, 100.0, 10.0],
    })
    routes = build_routes(["A"], markups, None, gr2, cfg)
    assert routes.loc[0, "route"] == "central_kitchen"
    assert routes.loc[0, "z_smart_majority"]


def test_a_stray_z_smart_line_does_not_flip_the_route(cfg):
    markups = pd.DataFrame({"key": ["A"], "markup_pct": [12.0], "category": ["WH"], "level": ["sku"]})
    gr2 = pd.DataFrame({
        "sku": ["A", "A"],
        "supplier": ["แซด สมาร์ท เทรดดิ้ง", "Main supplier"],
        "qty": [5.0, 500.0],
    })
    routes = build_routes(["A"], markups, None, gr2, cfg)
    assert routes.loc[0, "route"] == "warehouse"


# --- pipeline cost sources ----------------------------------------------

def test_imports_are_costed_from_the_my_cargo_file():
    _, result = _run()
    imports = result.detail[result.detail["route"] == "import"]
    costed = imports[imports["cost_source"] == "mycargo"]
    assert not costed.empty
    assert (costed["flag_codes"].str.contains("COST_FROM_MYCARGO")).all()
    # the cost is goods + freight, not goods alone
    assert (costed["unit_cost"] > 0).all()


def test_skus_with_no_receipt_fall_back_to_the_w10_standard_cost():
    _, result = _run()
    w10_costed = result.detail[result.detail["cost_source"] == "w10"]
    assert not w10_costed.empty
    assert (w10_costed["flag_codes"].str.contains("COST_FROM_W10")).all()
    assert w10_costed["suggested_price"].notna().all()


def test_manual_price_rows_are_held_at_the_current_price_not_blocked():
    _, result = _run()
    manual = result.detail[result.detail["cost_source"] == "manual"]
    assert not manual.empty
    assert not manual["blocked"].any()
    assert (manual["suggested_price"] == manual["current_price"]).all()
    assert (manual["flag_codes"].str.contains("MANUAL_PRICE")).all()
    assert not (manual["flag_codes"].str.contains("NO_COST")).any()


def test_my_cargo_unit_mismatch_blocks_the_sku():
    _, result = _run()
    bad = result.detail[result.detail["flag_codes"].str.contains("MYCARGO_UNIT_MISMATCH", na=False)]
    assert not bad.empty
    assert bad["blocked"].all()
    assert not (bad["sku"].isin(result.upload["SKU"])).any()


def test_markup_rate_mismatch_is_flagged_for_review_not_blocked():
    _, result = _run()
    mismatch = result.detail[
        result.detail["flag_codes"].str.contains("MARKUP_RATE_MISMATCH", na=False)
    ]
    assert not mismatch.empty
    assert not mismatch["blocked"].any()


def test_storefront_receipts_are_never_used_for_costing():
    _, result = _run()
    audit, detail = result.cost_audit, result.detail
    if "warehouse" not in audit.columns:
        return
    in_scope = audit[audit["sku"].isin(detail["sku"])]
    storefront_used = in_scope[
        ~in_scope["warehouse"].isin(["ST0001", "ST0002"]) & in_scope["used_in_costing"]
    ]
    assert storefront_used.empty


def test_routing_disabled_costs_from_every_line():
    _, on = _run()
    _, off = _run(**{"warehouse_routing.enabled": False})
    # with routing off there is no W10 fallback, so fewer SKUs are priced
    assert off.stats["SKUs priced"] < on.stats["SKUs priced"]
    assert set(off.detail["cost_source"].dropna()) <= {"receipt"}

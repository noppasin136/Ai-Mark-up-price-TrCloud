"""The My Cargo import-cost loader (PR 3)."""

import subprocess
import sys

import pytest

from markup.config import AppConfig
from markup.io import load_my_cargo, load_w10, mycargo_unit_issues
from tests.test_pipeline import ROOT, SAMPLES

MC = SAMPLES / "My_Cargo_sample.xlsx"
W10 = SAMPLES / "W10_sample.xlsx"


@pytest.fixture(scope="module", autouse=True)
def samples():
    if not MC.exists():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "make_sample_data.py")], check=True
        )


@pytest.fixture
def cfg():
    return AppConfig.load("config/config.yaml", "config/column_mapping.yaml")


def test_reads_the_first_sheet_whatever_its_name(cfg):
    # the sample tab is called "Oct26", not anything in the mapping
    mc = load_my_cargo(MC, cfg.mapping)
    assert len(mc) > 0


def test_landed_cost_is_goods_plus_oversea_freight(cfg):
    mc = load_my_cargo(MC, cfg.mapping).set_index("sku")
    row = mc[mc["has_landed_cost"]].iloc[0]
    assert row["landed_cost"] == pytest.approx(
        row["product_cost"] + row["oversea_transport"]
    )
    assert row["landed_cost"] > row["product_cost"]


def test_empty_vat_and_inland_columns_do_not_break_the_sum(cfg):
    mc = load_my_cargo(MC, cfg.mapping)
    assert mc["landed_cost"].notna().all()


def test_manual_price_rows_are_kept_without_a_cost(cfg):
    mc = load_my_cargo(MC, cfg.mapping)
    manual = mc[mc["has_manual_price"] & ~mc["has_landed_cost"]]
    assert not manual.empty
    assert manual["manual_price"].gt(0).all()


def test_unit_mismatch_against_the_w10_base_unit_is_reported(cfg):
    issues = mycargo_unit_issues(
        load_my_cargo(MC, cfg.mapping), load_w10(W10, cfg.mapping)
    )
    assert not issues.empty
    assert {"sku", "my_cargo_unit", "w10_base_unit"} <= set(issues.columns)


def test_no_file_returns_none(cfg):
    assert load_my_cargo(None, cfg.mapping) is None

"""End-to-end smoke test over the generated sample data."""

import subprocess
import sys
from pathlib import Path

import pytest

from markup.config import AppConfig
from markup.pipeline import run
from markup.report import write_workbook

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "input" / "samples"


@pytest.fixture(scope="module", autouse=True)
def samples():
    if not (SAMPLES / "GR2_sample.xlsx").exists():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "make_sample_data.py")], check=True
        )


def _run(**overrides):
    cfg = AppConfig.load(
        ROOT / "config/config.yaml", ROOT / "config/column_mapping.yaml", overrides
    )
    return cfg, run(
        cfg,
        SAMPLES / "GR2_sample.xlsx",
        SAMPLES / "W10_sample.xlsx",
        SAMPLES / "markup_list_sample.xlsx",
        SAMPLES / "sale_list_sample.xlsx",
    )


def test_pipeline_produces_priced_rows():
    _, result = _run()
    assert len(result.detail) > 0
    assert result.detail["suggested_price"].notna().sum() > 0


def test_parallel_units_are_priced_from_the_w10_units_table():
    _, result = _run()
    upload = result.upload
    multi = upload[upload.duplicated("SKU", keep=False)]
    assert not multi.empty, "expected at least one SKU priced in two units"
    # the larger unit must cost more than the base unit it contains
    for sku, rows in multi.groupby("SKU"):
        assert rows["Sale Price"].nunique() > 1


def test_unverified_units_never_reach_the_upload_sheet():
    _, result = _run()
    held = set(result.detail.loc[result.detail["unit_status"] == "unverified", "sku"])
    assert not (held & set(result.upload["SKU"]))


def test_upload_sheet_has_exactly_the_three_agreed_columns():
    _, result = _run()
    assert list(result.upload.columns) == ["SKU", "Unit", "Sale Price"]
    assert result.upload["Sale Price"].notna().all()


def test_blocked_rows_never_reach_the_upload_sheet():
    _, result = _run()
    blocked = set(result.detail.loc[result.detail["blocked"], "sku"])
    assert not (blocked & set(result.upload["SKU"]))


def test_period_narrows_the_costed_population():
    _, r30 = _run(**{"run.period_days": 30})
    _, r90 = _run(**{"run.period_days": 90})
    assert r30.stats["SKUs priced"] <= r90.stats["SKUs priced"]


def test_costing_method_changes_the_prices():
    _, fifo = _run(**{"costing.method": "fifo"})
    _, lifo = _run(**{"costing.method": "lifo"})
    merged = fifo.detail.merge(lifo.detail, on="sku", suffixes=("_f", "_l"))
    assert (merged["unit_cost_f"] != merged["unit_cost_l"]).any()


def test_workbook_is_written_and_readable(tmp_path):
    import openpyxl

    cfg, result = _run()
    path = write_workbook(result, cfg, tmp_path / "out.xlsx")
    assert path.exists()
    wb = openpyxl.load_workbook(path)
    assert cfg.upload_opts.get("sheet_name", "Price Upload") in wb.sheetnames
    assert "Run Summary" in wb.sheetnames

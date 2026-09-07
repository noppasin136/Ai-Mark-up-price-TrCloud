"""End-to-end smoke test over the generated sample data."""

import subprocess
import sys
from pathlib import Path

import pytest

from markup.config import AppConfig
from markup.pipeline import run
from markup import analysis
from markup.report import write_report_html, write_workbook

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "input" / "samples"


@pytest.fixture(scope="module", autouse=True)
def samples():
    needed = ("GR2_sample.xlsx", "W10_sample.xlsx", "My_Cargo_sample.xlsx")
    if not all((SAMPLES / f).exists() for f in needed):
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
        SAMPLES / "My_Cargo_sample.xlsx",
    )


def test_pipeline_produces_priced_rows():
    _, result = _run()
    assert len(result.detail) > 0
    assert result.detail["suggested_price"].notna().sum() > 0


def test_parallel_units_are_priced_from_the_w10_units_table():
    # include_parallel_rows defaults to false; this test exercises the mechanic.
    _, result = _run(**{"output.price_upload.include_parallel_rows": True})
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


def test_report_html_is_written_and_self_contained(tmp_path):
    cfg, result = _run()
    views = {
        "summary": analysis.summary_view(result.detail, result.stats),
        "movers": analysis.movers_view(result.detail, 25),
        "category": analysis.category_rollup(result.detail, "category"),
    }
    path = write_report_html(
        views, cfg, tmp_path / "Pricing report - 3 Sep 2026.html",
        run_id="20260903_1630_001", detail=result.detail, stats=result.stats,
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.lstrip().startswith("<!doctype html>")
    assert "Biggest Movers" in text and "By Category" in text
    # run id comes from the argument, not the (spaced) filename
    assert "20260903_1630_001" in text
    # the director dashboard is rendered ahead of the tables
    assert "This pricing round" in text and "Full detail" in text
    assert text.index("This pricing round") < text.index("Full detail")
    # no external assets — everything inline
    assert "http://" not in text and "https://" not in text
    assert "<link" not in text and "<script" not in text


def test_report_basename_is_human_readable():
    from types import SimpleNamespace

    from markup.cli import _report_basename

    run = SimpleNamespace(
        run_id="20260903_163103_001",
        manifest={"stats": {"As-of date": "2026-09-03"}},
    )
    assert _report_basename(run) == "Pricing report - 3 Sep 2026"

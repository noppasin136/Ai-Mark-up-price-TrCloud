"""Flag tiering: hard flags block the upload, soft flags only ask for a review."""

import numpy as np
import pandas as pd
import pytest

from markup.config import AppConfig
from markup.validation import BLOCKING, FLAG_CATALOG, HARD, SOFT, apply_guardrails
from tests.test_pipeline import _run


@pytest.fixture
def cfg():
    return AppConfig.load("config/config.yaml", "config/column_mapping.yaml")


def _frame(**overrides):
    row = {
        "unit_cost": 100.0,
        "suggested_price": 130.0,
        "current_price": 120.0,
        "change_pct": 8.3,
        "margin_pct": 23.0,
        "min_margin_pct": 5.0,
        "markup_source": "category",
        "unit_status": "ok",
    }
    row.update(overrides)
    return pd.DataFrame([row])


# --- the catalog itself -----------------------------------------------------

def test_every_flag_has_a_known_tier():
    for code, (_, tier) in FLAG_CATALOG.items():
        assert tier in (HARD, SOFT), code


def test_blocking_set_is_exactly_the_hard_flags():
    assert BLOCKING == {c for c, (_, t) in FLAG_CATALOG.items() if t == HARD}


def test_guardrail_breaches_are_soft():
    assert "OVER_MAX_INCREASE" not in BLOCKING
    assert "OVER_MAX_DECREASE" not in BLOCKING


def test_missing_cost_and_negative_margin_stay_hard():
    assert "NO_COST" in BLOCKING
    assert "NEGATIVE_MARGIN" in BLOCKING
    assert "UNIT_UNVERIFIED" in BLOCKING


# --- apply_guardrails behaviour -------------------------------------------

def test_big_increase_is_flagged_but_not_blocked(cfg):
    out = apply_guardrails(_frame(suggested_price=400.0, change_pct=233.0), cfg)
    assert "OVER_MAX_INCREASE" in out.loc[0, "flags"]
    assert not out.loc[0, "blocked"]


def test_big_decrease_is_flagged_but_not_blocked(cfg):
    out = apply_guardrails(
        _frame(unit_cost=30.0, suggested_price=40.0, current_price=120.0, change_pct=-66.0),
        cfg,
    )
    assert "OVER_MAX_DECREASE" in out.loc[0, "flags"]
    assert not out.loc[0, "blocked"]


def test_no_cost_blocks(cfg):
    out = apply_guardrails(
        _frame(unit_cost=np.nan, suggested_price=np.nan, change_pct=np.nan), cfg
    )
    assert "NO_COST" in out.loc[0, "flags"]
    assert out.loc[0, "blocked"]


def test_price_below_cost_blocks(cfg):
    out = apply_guardrails(_frame(suggested_price=90.0, change_pct=-25.0), cfg)
    assert "NEGATIVE_MARGIN" in out.loc[0, "flags"]
    assert out.loc[0, "blocked"]


# --- end to end ----------------------------------------------------------

def test_guardrail_breaches_reach_the_upload_sheet():
    _, result = _run()
    breached = result.detail[result.detail["flag_codes"].str.contains("OVER_MAX", na=False)]
    assert not breached.empty, "sample data should contain at least one guardrail breach"
    assert not breached["blocked"].any()
    assert set(breached["sku"]) <= set(result.upload["SKU"])


def test_exceptions_sheet_shows_which_rows_still_shipped():
    _, result = _run()
    assert "blocked" in result.exceptions.columns
    # at least one exception row that was not blocked (a soft flag)
    assert (~result.exceptions["blocked"]).any()

"""Opt-out price review: a HOLD keeps a soft-flagged row off the upload (PR 1b)."""

import pandas as pd
import pytest

from markup import price_review
from markup.pipeline import _apply_price_holds


@pytest.fixture
def review_file(tmp_path, monkeypatch):
    path = tmp_path / "price_review.xlsx"
    monkeypatch.setattr(price_review, "review_path", lambda cfg: path)
    return path


def _rows(*skus):
    return pd.DataFrame({
        "sku": list(skus),
        "product_name": [f"Item {s}" for s in skus],
        "category": ["WH"] * len(skus),
        "cost_source": ["receipt"] * len(skus),
        "current_price": [100.0] * len(skus),
        "suggested_price": [140.0] * len(skus),
        "change_pct": [40.0] * len(skus),
        "flag_codes": ["OVER_MAX_INCREASE"] * len(skus),
    })


def test_sync_creates_the_sheet_and_no_holds_by_default(review_file):
    path, added, held = price_review.sync(None, _rows("A", "B", "C"))
    assert path.exists()
    assert (added, held) == (3, 0)
    assert price_review.load_holds(None) == set()


def _set(review_file, sku, **cells):
    df = pd.read_excel(review_file, sheet_name=price_review.SHEET).astype(object)
    for col, val in cells.items():
        df.loc[df["SKU"] == sku, col] = val
    df.to_excel(review_file, sheet_name=price_review.SHEET, index=False)


def test_a_hold_decision_is_read_back(review_file):
    price_review.sync(None, _rows("A", "B"))
    _set(review_file, "A", Decision="HOLD")
    assert price_review.load_holds(None) == {"A"}


def test_sync_preserves_an_existing_decision(review_file):
    price_review.sync(None, _rows("A", "B"))
    _set(review_file, "A", Decision="HOLD", Note="cost looks wrong")

    # a later run with A still flagged plus a new SKU
    _, added, held = price_review.sync(None, _rows("A", "B", "D"))
    assert added == 1  # only D is new
    assert held == 1
    after = pd.read_excel(review_file, sheet_name=price_review.SHEET).set_index("SKU")
    assert after.loc["A", "Decision"] == "HOLD"
    assert after.loc["A", "Note"] == "cost looks wrong"


def test_apply_price_holds_blocks_and_flags():
    detail = pd.DataFrame({
        "sku": ["A", "B"],
        "flag_codes": ["OVER_MAX_INCREASE", ""],
        "flag_reasons": ["Increase exceeds the guardrail limit", ""],
        "blocked": [False, False],
    })
    out = _apply_price_holds(detail, {"A"})
    assert out.loc[0, "blocked"]
    assert "PRICE_HELD" in out.loc[0, "flag_codes"]
    assert not out.loc[1, "blocked"]


def test_apply_price_holds_is_a_noop_without_holds():
    detail = pd.DataFrame({"sku": ["A"], "flag_codes": [""], "flag_reasons": [""], "blocked": [False]})
    out = _apply_price_holds(detail, set())
    assert not out.loc[0, "blocked"]

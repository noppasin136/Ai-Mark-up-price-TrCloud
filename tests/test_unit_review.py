import pandas as pd
import pytest

from markup import unit_review
from markup.costing import to_base_units


def _frame(**over):
    row = {
        "sku": "A", "product_name": "Item A", "sale_uom": "pack",
        "gr_units": "bag", "coefficient": 4.0, "cost_per_gr_unit": 90.0,
        "converted_cost": 360.0, "current_price": 99.5, "markup_pct": 12.0,
    }
    row.update(over)
    return pd.DataFrame([row])


def test_detect_flags_a_unit_mismatch():
    out = unit_review.detect(_frame())
    assert len(out) == 1
    assert "received per" in out.iloc[0]["why_flagged"]


def test_detect_flags_a_cost_that_exceeds_the_selling_price():
    out = unit_review.detect(_frame(gr_units="pack", coefficient=1.0, converted_cost=360.0))
    assert "mis-keyed" in out.iloc[0]["why_flagged"]


def test_detect_flags_a_parallel_sale_unit():
    out = unit_review.detect(_frame(gr_units="pack", converted_cost=90.0))
    assert "parallel unit" in out.iloc[0]["why_flagged"]


def test_detect_passes_a_clean_row():
    assert unit_review.detect(
        _frame(gr_units="pack", coefficient=1.0, converted_cost=90.0, current_price=120.0)
    ).empty


def test_detect_ignores_a_sku_with_no_receipts():
    assert unit_review.detect(_frame(gr_units=None)).empty


def test_treat_as_remaps_the_receipt_unit_before_conversion():
    """The ถุงร้อน case: bought by the pack, keyed as bag."""
    gr = pd.DataFrame({
        "sku": ["A", "A"], "uom": ["bag", "pack"], "qty": [1.0, 1.0],
        "effective_cost": [90.0, 90.0],
    })
    coefficients = {("A", "bag"): 1.0, ("A", "pack"): 4.0}

    # Untreated, the "bag" line is read as one base unit and drags the cost down.
    plain = to_base_units(gr, coefficients)
    assert plain["effective_cost"].tolist() == [90.0, 22.5]

    # Treated, both lines are packs and agree.
    fixed = to_base_units(gr, coefficients, {"A": "pack"})
    assert fixed["effective_cost"].tolist() == [22.5, 22.5]
    assert fixed["uom_as_recorded"].tolist() == ["bag", "pack"]


def test_lines_with_a_unit_w10_does_not_know_are_dropped():
    gr = pd.DataFrame({"sku": ["A", "A"], "uom": ["bag", "mystery"],
                       "qty": [1.0, 1.0], "effective_cost": [90.0, 90.0]})
    out = to_base_units(gr, {("A", "bag"): 1.0})
    assert len(out) == 1 and out.iloc[0]["uom"] == "bag"


@pytest.mark.parametrize("decision,expected", [
    (unit_review.ACCEPT, True), (unit_review.TREAT_AS, True),
    (unit_review.EXCLUDE, True), (unit_review.PENDING, False),
])
def test_resolved_states(decision, expected):
    d = unit_review.Decision("A", decision, treat_as="pack")
    assert d.is_resolved is expected

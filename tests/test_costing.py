import pandas as pd
import pytest

from markup.costing import get_method


def layers():
    """Three receipts, cost rising over time: 10 @ 100, 10 @ 110, 10 @ 120."""
    return pd.DataFrame(
        {
            "receipt_date": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
            "qty": [10.0, 10.0, 10.0],
            "effective_cost": [100.0, 110.0, 120.0],
        }
    )


def test_weighted_average_is_the_qty_weighted_mean():
    cost, _ = get_method("weighted_average").compute(layers())
    assert cost == pytest.approx(110.0)


def test_fifo_takes_the_oldest_layers():
    cost, _ = get_method("fifo").compute(layers(), coverage_pct=33.33)
    assert cost == pytest.approx(100.0)


def test_lifo_takes_the_newest_layers():
    cost, _ = get_method("lifo").compute(layers(), coverage_pct=33.33)
    assert cost == pytest.approx(120.0)


def test_full_coverage_converges_on_weighted_average():
    fifo, _ = get_method("fifo").compute(layers(), coverage_pct=100)
    lifo, _ = get_method("lifo").compute(layers(), coverage_pct=100)
    wavg, _ = get_method("weighted_average").compute(layers())
    assert fifo == pytest.approx(wavg)
    assert lifo == pytest.approx(wavg)


def test_partial_layer_is_split_not_dropped():
    # 50% of 30 units = 15 -> all of layer 1 (10 @ 100) + half of layer 2 (5 @ 110)
    cost, _ = get_method("fifo").compute(layers(), coverage_pct=50)
    assert cost == pytest.approx((10 * 100 + 5 * 110) / 15)


def test_last_and_extreme_costs():
    assert get_method("last_cost").compute(layers())[0] == pytest.approx(120.0)
    assert get_method("highest_cost").compute(layers())[0] == pytest.approx(120.0)
    assert get_method("lowest_cost").compute(layers())[0] == pytest.approx(100.0)


def test_unknown_method_raises():
    with pytest.raises(ValueError, match="Unknown costing method"):
        get_method("vibes")

import pytest

from markup.config import RoundingRule
from markup.rules.rounding import apply_rounding


@pytest.mark.parametrize(
    "price,strategy,step,direction,expected",
    [
        (127.34, "nearest", 1.0, "half_up", 127.00),
        (127.60, "nearest", 1.0, "half_up", 128.00),
        (127.50, "nearest", 1.0, "half_up", 128.00),
        (127.10, "nearest", 1.0, "up", 128.00),
        (127.90, "nearest", 1.0, "down", 127.00),
        (127.30, "nearest", 0.50, "half_up", 127.50),
        (127.10, "step_ceiling", 5.0, "half_up", 130.00),
        (127.90, "step_floor", 5.0, "half_up", 125.00),
        (127.34, "none", 1.0, "half_up", 127.34),
    ],
)
def test_strategies(price, strategy, step, direction, expected):
    rule = RoundingRule(strategy=strategy, step=step, direction=direction)
    assert apply_rounding(price, rule) == pytest.approx(expected)


def test_psychological_snaps_up_to_charm_ending():
    rule = RoundingRule(strategy="psychological", endings=(0.95, 0.99))
    assert apply_rounding(127.20, rule) == pytest.approx(127.95)
    assert apply_rounding(127.97, rule) == pytest.approx(127.99)
    assert apply_rounding(128.00, rule) == pytest.approx(128.95)


def test_none_price_passes_through():
    assert apply_rounding(None, RoundingRule()) is None


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="Unknown rounding strategy"):
        apply_rounding(10.0, RoundingRule(strategy="wishful"))

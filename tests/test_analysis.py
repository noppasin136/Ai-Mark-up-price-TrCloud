import pandas as pd
import pytest

from markup import analysis


def frame(prices, costs=None, categories=None, skus=None):
    n = len(prices)
    return pd.DataFrame(
        {
            "sku": skus or [f"S{i}" for i in range(n)],
            "product_name": [f"Item {i}" for i in range(n)],
            "category": categories or ["BEV"] * n,
            "unit_cost": costs or [100.0] * n,
            "markup_pct": [30.0] * n,
            "suggested_price": prices,
            "current_price": [120.0] * n,
            "change_pct": [8.33] * n,
            "margin_pct": [23.0] * n,
            "blocked": [False] * n,
            "flag_codes": [""] * n,
        }
    )


def test_comparison_marks_changed_new_and_dropped():
    current = frame([130.0, 140.0, 150.0], skus=["A", "B", "NEW"])
    previous = frame([130.0, 135.0, 160.0], skus=["A", "B", "GONE"])

    out = analysis.comparison_view(current, previous)
    status = dict(zip(out["sku"], out["status"]))

    assert status["A"] == "unchanged"
    assert status["B"] == "changed"
    assert status["NEW"] == "new"
    assert status["GONE"] == "dropped"


def test_comparison_computes_price_delta_and_pct():
    current = frame([135.0], skus=["A"])
    previous = frame([130.0], skus=["A"])
    row = analysis.comparison_view(current, previous).iloc[0]
    assert row["price_delta"] == pytest.approx(5.0)
    assert row["price_delta_pct"] == pytest.approx(3.85, abs=0.01)


def test_comparison_summary_counts_match_the_detail():
    current = frame([130.0, 140.0], skus=["A", "B"])
    previous = frame([130.0, 135.0], skus=["A", "B"])
    comparison = analysis.comparison_view(current, previous)
    summary = dict(
        zip(
            analysis.comparison_summary(comparison, "now", "before")["Metric"],
            analysis.comparison_summary(comparison, "now", "before")["Value"],
        )
    )
    assert summary["Changed"] == 1
    assert summary["Unchanged"] == 1


def test_category_rollup_groups_and_counts():
    df = frame([130.0, 140.0, 150.0], categories=["BEV", "BEV", "SNK"])
    roll = analysis.category_rollup(df)
    assert set(roll["category"]) == {"BEV", "SNK"}
    assert int(roll.loc[roll["category"] == "BEV", "skus"].iloc[0]) == 2


def test_category_rollup_handles_a_missing_group_column():
    df = frame([130.0]).drop(columns=["category"])
    assert analysis.category_rollup(df, "category").empty


def test_movers_are_ordered_by_absolute_change():
    df = frame([130.0, 140.0, 150.0])
    df["change_pct"] = [2.0, -25.0, 10.0]
    movers = analysis.movers_view(df, top_n=2)
    assert movers.iloc[0]["change_pct"] == pytest.approx(-25.0)
    assert len(movers) == 2


def test_summary_view_includes_flag_counts():
    df = frame([130.0, 140.0])
    df["flag_codes"] = ["NO_COST", "NO_COST, PRICE_DECREASE"]
    out = analysis.summary_view(df, {"Costing method": "fifo"})
    metrics = dict(zip(out["Metric"], out["Value"]))
    assert metrics["NO_COST"] == 2
    assert metrics["PRICE_DECREASE"] == 1

import pandas as pd
import pytest

from markup.config import AppConfig
from markup.rules.markup import MarkupResolver, apply_markup, gross_margin_pct


@pytest.fixture
def cfg(tmp_path):
    return AppConfig.load("config/config.yaml", "config/column_mapping.yaml")


@pytest.fixture
def rules():
    return pd.DataFrame(
        [
            {"level": "category", "key": "BEV", "markup_pct": 25.0},
            {"level": "subcategory", "key": "BEV-1", "markup_pct": 40.0},
            {"level": "sku", "key": "BEV-0003", "markup_pct": 18.0},
        ]
    )


def test_sku_rule_beats_subcategory_and_category(cfg, rules):
    r = MarkupResolver(rules, cfg).resolve(
        pd.Series({"sku": "BEV-0003", "subcategory": "BEV-1", "category": "BEV"})
    )
    assert (r.pct, r.level) == (18.0, "sku")


def test_subcategory_beats_category(cfg, rules):
    r = MarkupResolver(rules, cfg).resolve(
        pd.Series({"sku": "BEV-0009", "subcategory": "BEV-1", "category": "BEV"})
    )
    assert (r.pct, r.level) == (40.0, "subcategory")


def test_falls_back_to_default_when_nothing_matches(cfg, rules):
    r = MarkupResolver(rules, cfg).resolve(pd.Series({"sku": "XXX", "category": "ZZZ"}))
    assert r.level == "default" and r.pct == cfg.default_pct


def test_cost_plus_vs_margin_basis(cfg, rules):
    rule = MarkupResolver(rules, cfg).resolve(pd.Series({"category": "BEV"}))
    assert apply_markup(100.0, rule) == pytest.approx(125.0)

    margin_rule = type(rule)(pct=25.0, level="category", key="BEV", basis="margin",
                             min_margin_pct=5.0)
    assert apply_markup(100.0, margin_rule) == pytest.approx(133.333, rel=1e-4)


def test_gross_margin_is_computed_on_price_not_cost():
    assert gross_margin_pct(125.0, 100.0) == pytest.approx(20.0)

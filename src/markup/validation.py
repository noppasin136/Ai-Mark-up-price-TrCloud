"""Quality control: every reason a suggested price should not go straight to the ERP.

Each check appends a short code to the row's ``flags`` list. Flags are one of two
tiers:

* **hard** — the row is excluded from the Price Upload sheet. Something is missing
  or unsafe (no cost, an unreviewed unit, a price below cost); there is nothing
  to hand the ERP.
* **soft** — the row *still ships* on the Price Upload sheet, but is listed on
  Exceptions for a human to look at. A large price move is the main case: the
  number is defensible, it just deserves a second pair of eyes. Silence means the
  price goes.

``FLAG_CATALOG`` records the tier for every code. See docs/COSTING_MODEL.md §8.C.
"""

from __future__ import annotations

import pandas as pd

from .config import AppConfig

HARD = "hard"
SOFT = "soft"

# code -> (human explanation, tier)
FLAG_CATALOG: dict[str, tuple[str, str]] = {
    "NO_COST": ("No goods receipt in the selected period — cannot compute a cost", HARD),
    "NO_MARKUP_RULE": ("No markup rule matched; the default percentage was used", SOFT),
    "BELOW_MIN_MARGIN": ("Resulting margin is under the configured floor", HARD),
    "NEGATIVE_MARGIN": ("Suggested price is below cost", HARD),
    "OVER_MAX_INCREASE": ("Increase exceeds the guardrail limit — review, then it ships", SOFT),
    "OVER_MAX_DECREASE": ("Decrease exceeds the guardrail limit — review, then it ships", SOFT),
    "PRICE_DECREASE": ("Suggested price is lower than the current ERP price", SOFT),
    "NO_CURRENT_PRICE": ("SKU has no current price in W10 — new item", SOFT),
    "BELOW_MIN_CHANGE": ("Change is too small to be worth republishing", SOFT),
    "MISSING_IN_W10": ("SKU is in the sale list but absent from W10", HARD),
    "BAD_CONVERSION": ("Parallel unit present but conversion factor is missing or 1", SOFT),
    "UNIT_UNVERIFIED": (
        "Sale unit and receipt unit differ and the conversion has not been reviewed yet "
        "— decide it in config/unit_review.xlsx", HARD,
    ),
    "UNIT_EXCLUDED": ("Excluded by a decision in config/unit_review.xlsx", HARD),
    "UNIT_CORRECTED": ("Receipt unit re-read under an approved correction", SOFT),
    "UNKNOWN_SALE_UNIT": ("Sale unit is not listed for this SKU in W10", HARD),
    "MYCARGO_UNIT_MISMATCH": (
        "My Cargo quotes this SKU in a unit that is not its W10 base unit "
        "— fix the file's 'unit' column", HARD,
    ),
    "COST_FROM_MYCARGO": ("Costed from the My Cargo import file (goods + freight)", SOFT),
    "COST_FROM_OTHER_WH": (
        "No receipt in this SKU's home warehouse — costed from its other "
        "head-office warehouse", SOFT,
    ),
    "COST_FROM_W10": ("No usable receipt — costed from the W10 standard cost", SOFT),
    "MANUAL_PRICE": ("Held at its current price — My Cargo gives a price, not a cost", SOFT),
    "MARKUP_RATE_MISMATCH": (
        "markup_list Markup differs from the rate the routing rules expect", SOFT,
    ),
}

BLOCKING = {code for code, (_, tier) in FLAG_CATALOG.items() if tier == HARD}


def apply_guardrails(detail: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    """Populate ``flags``, ``blocked`` and (optionally) clamp out-of-range prices."""
    df = detail.copy()
    df["flags"] = [[] for _ in range(len(df))]

    def flag(mask: pd.Series, code: str) -> None:
        for idx in df.index[mask.fillna(False)]:
            df.at[idx, "flags"].append(code)

    # No cost AND no price — nothing to send. A My Cargo manual-price row has no
    # cost but does have a price, so it is not NO_COST.
    flag(df["unit_cost"].isna() & df["suggested_price"].isna(), "NO_COST")
    if "unit_status" in df.columns:
        flag(df["unit_status"] == "unverified", "UNIT_UNVERIFIED")
        flag(df["unit_status"] == "excluded", "UNIT_EXCLUDED")
        flag(df["unit_status"] == "corrected", "UNIT_CORRECTED")
        flag(df["unit_status"] == "unknown_unit", "UNKNOWN_SALE_UNIT")
    if "markup_source" in df.columns:
        flag(df["markup_source"] == "default", "NO_MARKUP_RULE")
    flag(df["current_price"].isna(), "NO_CURRENT_PRICE")

    priced = df["suggested_price"].notna() & df["unit_cost"].notna()
    flag(priced & (df["suggested_price"] < df["unit_cost"]), "NEGATIVE_MARGIN")
    flag(priced & (df["margin_pct"] < df["min_margin_pct"]), "BELOW_MIN_MARGIN")

    movable = priced & df["current_price"].notna() & (df["current_price"] > 0)
    flag(movable & (df["change_pct"] > cfg.max_increase_pct), "OVER_MAX_INCREASE")
    flag(movable & (df["change_pct"] < -cfg.max_decrease_pct), "OVER_MAX_DECREASE")
    if cfg.flag_price_decrease:
        flag(movable & (df["change_pct"] < 0), "PRICE_DECREASE")
    flag(movable & (df["change_pct"].abs() < cfg.min_change_pct), "BELOW_MIN_CHANGE")

    _flag_routing(df, cfg, flag)


    if cfg.clamp:
        _clamp(df, cfg)

    df["blocked"] = df["flags"].apply(lambda fl: bool(set(fl) & BLOCKING))
    df["flag_codes"] = df["flags"].apply(lambda fl: ", ".join(fl))
    df["flag_reasons"] = df["flags"].apply(
        lambda fl: "; ".join(FLAG_CATALOG[c][0] for c in fl if c in FLAG_CATALOG)
    )
    return df


def _flag_routing(df: pd.DataFrame, cfg: AppConfig, flag) -> None:
    """Flags from the warehouse-routing columns (present only when routing ran)."""
    src = df.get("cost_source")
    if src is not None:
        flag(src == "mycargo", "COST_FROM_MYCARGO")
        flag(src == "other_wh", "COST_FROM_OTHER_WH")
        flag(src == "w10", "COST_FROM_W10")
        flag(src == "manual", "MANUAL_PRICE")

    if "mc_unit_mismatch" in df.columns:
        flag(df["mc_unit_mismatch"].fillna(False).astype(bool), "MYCARGO_UNIT_MISMATCH")

    if "expected_rate_pct" in df.columns and "markup_pct" in df.columns:
        tol = float(cfg.wh("rate_mismatch_tolerance_pct", 0.5))
        expected = pd.to_numeric(df["expected_rate_pct"], errors="coerce")
        actual = pd.to_numeric(df["markup_pct"], errors="coerce")
        flag(expected.notna() & actual.notna() & ((actual - expected).abs() > tol),
             "MARKUP_RATE_MISMATCH")


def _clamp(df: pd.DataFrame, cfg: AppConfig) -> None:
    """Cap out-of-range moves at the guardrail instead of blocking the row."""
    upper = df["current_price"] * (1 + cfg.max_increase_pct / 100.0)
    lower = df["current_price"] * (1 - cfg.max_decrease_pct / 100.0)

    hi = df["flags"].apply(lambda fl: "OVER_MAX_INCREASE" in fl)
    lo = df["flags"].apply(lambda fl: "OVER_MAX_DECREASE" in fl)

    for idx in df.index[hi]:
        df.at[idx, "suggested_price"] = round(float(upper[idx]), 2)
        df.at[idx, "flags"] = [f for f in df.at[idx, "flags"] if f != "OVER_MAX_INCREASE"]
        df.at[idx, "flags"].append("CLAMPED_UP")
    for idx in df.index[lo]:
        df.at[idx, "suggested_price"] = round(float(lower[idx]), 2)
        df.at[idx, "flags"] = [f for f in df.at[idx, "flags"] if f != "OVER_MAX_DECREASE"]
        df.at[idx, "flags"].append("CLAMPED_DOWN")

    FLAG_CATALOG.setdefault("CLAMPED_UP", ("Increase capped at the guardrail limit", SOFT))
    FLAG_CATALOG.setdefault("CLAMPED_DOWN", ("Decrease capped at the guardrail limit", SOFT))


def exceptions_view(detail: pd.DataFrame) -> pd.DataFrame:
    """Only the rows a human needs to look at.

    ``blocked`` is carried through so the sheet shows which rows were kept off
    the upload (hard flags) and which still shipped and only want a review
    (soft flags).
    """
    cols = [
        "sku", "product_name", "category", "sale_uom", "blocked", "unit_cost", "markup_pct",
        "markup_source", "current_price", "suggested_price", "change_pct",
        "margin_pct", "flag_codes", "flag_reasons",
    ]
    out = detail[detail["flag_codes"].astype(bool)]
    return out[[c for c in cols if c in out.columns]].reset_index(drop=True)

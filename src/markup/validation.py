"""Quality control: every reason a suggested price should not go straight to the ERP.

Each check appends a short code to the row's ``flags`` list. Any row carrying a
blocking flag is excluded from the Price Upload sheet and shown on Exceptions
with a plain-language reason.
"""

from __future__ import annotations

import pandas as pd

from .config import AppConfig

# code -> (human explanation, blocks upload?)
FLAG_CATALOG: dict[str, tuple[str, bool]] = {
    "NO_COST": ("No goods receipt in the selected period — cannot compute a cost", True),
    "NO_MARKUP_RULE": ("No markup rule matched; the default percentage was used", False),
    "BELOW_MIN_MARGIN": ("Resulting margin is under the configured floor", True),
    "NEGATIVE_MARGIN": ("Suggested price is below cost", True),
    "OVER_MAX_INCREASE": ("Increase exceeds the guardrail limit", True),
    "OVER_MAX_DECREASE": ("Decrease exceeds the guardrail limit", True),
    "PRICE_DECREASE": ("Suggested price is lower than the current ERP price", False),
    "NO_CURRENT_PRICE": ("SKU has no current price in W10 — new item", False),
    "BELOW_MIN_CHANGE": ("Change is too small to be worth republishing", False),
    "MISSING_IN_W10": ("SKU is in the sale list but absent from W10", True),
    "BAD_CONVERSION": ("Parallel unit present but conversion factor is missing or 1", False),
    "UNIT_UNVERIFIED": (
        "Sale unit and receipt unit differ and the conversion has not been reviewed yet "
        "— decide it in config/unit_review.xlsx", True,
    ),
    "UNIT_EXCLUDED": ("Excluded by a decision in config/unit_review.xlsx", True),
    "UNIT_CORRECTED": ("Receipt unit re-read under an approved correction", False),
    "UNKNOWN_SALE_UNIT": ("Sale unit is not listed for this SKU in W10", True),
}

BLOCKING = {code for code, (_, blocks) in FLAG_CATALOG.items() if blocks}


def apply_guardrails(detail: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    """Populate ``flags``, ``blocked`` and (optionally) clamp out-of-range prices."""
    df = detail.copy()
    df["flags"] = [[] for _ in range(len(df))]

    def flag(mask: pd.Series, code: str) -> None:
        for idx in df.index[mask.fillna(False)]:
            df.at[idx, "flags"].append(code)

    flag(df["unit_cost"].isna(), "NO_COST")
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


    if cfg.clamp:
        _clamp(df, cfg)

    df["blocked"] = df["flags"].apply(lambda fl: bool(set(fl) & BLOCKING))
    df["flag_codes"] = df["flags"].apply(lambda fl: ", ".join(fl))
    df["flag_reasons"] = df["flags"].apply(
        lambda fl: "; ".join(FLAG_CATALOG[c][0] for c in fl if c in FLAG_CATALOG)
    )
    return df


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

    FLAG_CATALOG.setdefault("CLAMPED_UP", ("Increase capped at the guardrail limit", False))
    FLAG_CATALOG.setdefault("CLAMPED_DOWN", ("Decrease capped at the guardrail limit", False))


def exceptions_view(detail: pd.DataFrame) -> pd.DataFrame:
    """Only the rows a human needs to look at."""
    cols = [
        "sku", "product_name", "category", "sale_uom", "unit_cost", "markup_pct",
        "markup_source", "current_price", "suggested_price", "change_pct",
        "margin_pct", "flag_codes", "flag_reasons",
    ]
    out = detail[detail["flag_codes"].astype(bool)]
    return out[[c for c in cols if c in out.columns]].reset_index(drop=True)

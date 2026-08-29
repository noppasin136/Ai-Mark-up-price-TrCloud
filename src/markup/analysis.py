"""Reporting views built on top of a completed run.

Three questions, three frames:
  * how did this run go            -> :func:`summary_view`, :func:`movers_view`
  * how does it differ from before -> :func:`comparison_view`
  * where is the money by group    -> :func:`category_rollup`
"""

from __future__ import annotations

import pandas as pd

TOP_N = 25


def summary_view(detail: pd.DataFrame, stats: dict) -> pd.DataFrame:
    """The run's parameters and headline counts, as a two-column table."""
    rows = list(stats.items())
    priced = detail[detail["suggested_price"].notna()]

    if not priced.empty and "change_pct" in priced.columns:
        moved = priced[priced["change_pct"].notna()]
        rows += [
            ("", ""),
            ("— Price movement —", ""),
            ("SKUs moving up", int((moved["change_pct"] > 0).sum())),
            ("SKUs moving down", int((moved["change_pct"] < 0).sum())),
            ("SKUs unchanged", int((moved["change_pct"] == 0).sum())),
            ("Median change %", round(float(moved["change_pct"].median()), 2) if len(moved) else None),
            ("Largest increase %", round(float(moved["change_pct"].max()), 2) if len(moved) else None),
            ("Largest decrease %", round(float(moved["change_pct"].min()), 2) if len(moved) else None),
        ]

    if "flag_codes" in detail.columns:
        counts: dict[str, int] = {}
        for codes in detail["flag_codes"].fillna(""):
            for code in [c.strip() for c in str(codes).split(",") if c.strip()]:
                counts[code] = counts.get(code, 0) + 1
        if counts:
            rows.append(("", ""))
            rows.append(("— Exceptions by flag —", ""))
            rows += sorted(counts.items(), key=lambda kv: -kv[1])

    return pd.DataFrame(rows, columns=["Metric", "Value"])


def movers_view(detail: pd.DataFrame, top_n: int = TOP_N) -> pd.DataFrame:
    """The biggest price moves in this run, largest absolute change first."""
    cols = [
        "sku", "product_name", "category", "sale_uom", "unit_cost",
        "markup_pct", "current_price", "suggested_price", "price_change",
        "change_pct", "margin_pct", "flag_codes",
    ]
    df = detail[detail["change_pct"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=[c for c in cols if c in detail.columns])
    df["_abs"] = df["change_pct"].abs()
    out = df.nlargest(top_n, "_abs")
    return out[[c for c in cols if c in out.columns]].reset_index(drop=True)


def category_rollup(detail: pd.DataFrame, group_col: str = "category") -> pd.DataFrame:
    """Margin and movement aggregated by product group."""
    if group_col not in detail.columns:
        return pd.DataFrame({"(no category column)": []})

    df = detail.copy()
    df[group_col] = df[group_col].fillna("(unassigned)")

    agg = df.groupby(group_col).apply(
        lambda g: pd.Series(
            {
                "skus": len(g),
                "priced": int(g["suggested_price"].notna().sum()),
                "blocked": int(g["blocked"].sum()) if "blocked" in g else 0,
                "avg_markup_pct": round(float(g["markup_pct"].mean(skipna=True)), 2),
                "avg_margin_pct": round(float(g["margin_pct"].mean(skipna=True)), 2),
                "avg_cost": round(float(g["unit_cost"].mean(skipna=True)), 2),
                "avg_current_price": round(float(g["current_price"].mean(skipna=True)), 2),
                "avg_new_price": round(float(g["suggested_price"].mean(skipna=True)), 2),
                "avg_change_pct": round(float(g["change_pct"].mean(skipna=True)), 2),
                "moving_up": int((g["change_pct"] > 0).sum()),
                "moving_down": int((g["change_pct"] < 0).sum()),
            }
        ),
        include_groups=False,
    )
    return agg.reset_index().sort_values("skus", ascending=False).reset_index(drop=True)


def comparison_view(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """SKU-level diff of this run against the previous one.

    ``status`` is one of: new (not priced before), dropped (priced before,
    not now), changed, or unchanged.
    """
    keep = ["sku", "product_name", "category", "unit_cost", "markup_pct", "suggested_price"]
    cur = current[[c for c in keep if c in current.columns]].copy()
    prev = previous[[c for c in keep if c in previous.columns]].copy()

    merged = cur.merge(prev, on="sku", how="outer", suffixes=("", "_prev"), indicator=True)

    merged["cost_delta"] = (merged["unit_cost"] - merged.get("unit_cost_prev")).round(4)
    merged["price_delta"] = (merged["suggested_price"] - merged.get("suggested_price_prev")).round(2)
    merged["price_delta_pct"] = (
        merged["price_delta"] / merged["suggested_price_prev"].replace(0, pd.NA) * 100
    ).round(2)

    def status(row) -> str:
        if row["_merge"] == "left_only" or pd.isna(row.get("suggested_price_prev")):
            return "new"
        if row["_merge"] == "right_only" or pd.isna(row.get("suggested_price")):
            return "dropped"
        return "unchanged" if (row["price_delta"] or 0) == 0 else "changed"

    merged["status"] = merged.apply(status, axis=1)
    merged = merged.drop(columns=["_merge"])

    cols = [
        "sku", "product_name", "category", "status",
        "unit_cost_prev", "unit_cost", "cost_delta",
        "suggested_price_prev", "suggested_price", "price_delta", "price_delta_pct",
        "markup_pct_prev", "markup_pct",
    ]
    out = merged[[c for c in cols if c in merged.columns]]
    order = {"changed": 0, "new": 1, "dropped": 2, "unchanged": 3}
    return (
        out.assign(_o=out["status"].map(order))
        .sort_values(["_o", "price_delta_pct"], ascending=[True, False], na_position="last")
        .drop(columns="_o")
        .reset_index(drop=True)
    )


def comparison_summary(comparison: pd.DataFrame, cur_label: str, prev_label: str) -> pd.DataFrame:
    counts = comparison["status"].value_counts().to_dict()
    changed = comparison[comparison["status"] == "changed"]
    rows = [
        ("This run", cur_label),
        ("Compared against", prev_label),
        ("", ""),
        ("Changed", counts.get("changed", 0)),
        ("Unchanged", counts.get("unchanged", 0)),
        ("New (not priced before)", counts.get("new", 0)),
        ("Dropped (no longer priced)", counts.get("dropped", 0)),
    ]
    if not changed.empty:
        rows += [
            ("", ""),
            ("Average change %", round(float(changed["price_delta_pct"].mean(skipna=True)), 2)),
            ("Largest increase %", round(float(changed["price_delta_pct"].max()), 2)),
            ("Largest decrease %", round(float(changed["price_delta_pct"].min()), 2)),
            ("Net price delta", round(float(changed["price_delta"].sum()), 2)),
        ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])

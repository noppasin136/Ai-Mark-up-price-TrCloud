"""Generate realistic sample GR2 / W10 / markup / sale-list workbooks.

Run this once so the pipeline works end-to-end before your real ERP extracts
arrive, and so the column-mapping contract is visible as concrete files.

    python scripts/make_sample_data.py
"""

from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

import pandas as pd

random.seed(7)
OUT = Path(__file__).resolve().parent.parent / "data" / "input" / "samples"

CATEGORIES = {
    "BEV": ("Beverage", 25.0),
    "SNK": ("Snack", 35.0),
    "HHC": ("Household Care", 30.0),
    "PCR": ("Personal Care", 42.0),
}
UOMS = [("PCS", "BOX", 12), ("PCS", "CTN", 24), ("BTL", "PACK", 6), ("KG", None, 1)]


def build():
    today = dt.date.today()
    gr_rows, w10_rows, sale_rows = [], [], []

    for i in range(1, 61):
        cat = random.choice(list(CATEGORIES))
        sku = f"{cat}-{i:04d}"
        name = f"{CATEGORIES[cat][0]} Item {i:03d}"
        uom, par_uom, factor = random.choice(UOMS)
        base_cost = round(random.uniform(8, 480), 2)

        # 4 SKUs deliberately get no receipts, to exercise the NO_COST path
        n_receipts = 0 if i % 15 == 0 else random.randint(1, 9)
        for r in range(n_receipts):
            days_ago = random.randint(0, 120)          # some fall outside a 90-day window
            drift = 1 + random.uniform(-0.10, 0.14)    # cost trend over the period
            qty = random.choice([12, 24, 48, 60, 120, 240])
            unit_cost = round(base_cost * drift, 2)
            if i % 23 == 0 and r == 0:
                unit_cost = round(unit_cost * 9, 2)    # keying error -> outlier filter
            gr_rows.append({
                "Item Code": sku,
                "Item Name": name,
                "GR Date": today - dt.timedelta(days=days_ago),
                "GR No": f"GR{2600000 + len(gr_rows)}",
                "Vendor Name": f"Supplier {random.randint(1, 12):02d}",
                "Received Qty": qty,
                "UOM": uom,
                "Unit Cost": unit_cost,
                "Total Cost": round(unit_cost * qty, 2),
                "Freight": round(qty * random.uniform(0.1, 1.4), 2),
                "Import Duty": round(unit_cost * qty * random.uniform(0, 0.03), 2),
                "Currency": "THB",
            })

        current = round(base_cost * random.uniform(1.15, 1.55), 0)
        # W10 holds one row per SKU *and unit*: the base unit, then any parallel
        # unit with the number of base units it contains.
        w10_rows.append({
            "Item Code": sku, "Item Name": name, "Sales Unit": uom,
            "Ccoefficient": 1, "Is Main": 1, "Sale Price": current,
            "Product Group": cat, "Sub Group": f"{cat}-{(i % 3) + 1}",
            "Division": "RETAIL", "Item Status": "Active",
        })
        if par_uom:
            w10_rows.append({
                "Item Code": sku, "Item Name": name, "Sales Unit": par_uom,
                "Ccoefficient": factor, "Is Main": 0,
                "Sale Price": round(current * factor * 0.97, 0),
                "Product Group": cat, "Sub Group": f"{cat}-{(i % 3) + 1}",
                "Division": "RETAIL", "Item Status": "Active",
            })
        sale_rows.append({
            "Item Code": sku, "Sale Unit": uom, "Item Name": name,
            "Selling Price": current,
            "Include": "N" if i % 20 == 0 else "Y",
        })

    # Markup is stored as a FRACTION (0.25 = 25%), matching the real ERP export.
    # config.yaml's markup.value_scale turns it back into a percentage on load.
    markup_rows = [
        {"Level": "category", "Key": k, "Markup %": pct / 100, "Note": f"{label} standard"}
        for k, (label, pct) in CATEGORIES.items()
    ]
    markup_rows += [
        {"Level": "subcategory", "Key": "PCR-1", "Markup %": 0.50, "Note": "Premium sub-group"},
        {"Level": "sku", "Key": "BEV-0003", "Markup %": 0.18, "Note": "KVI — price-sensitive"},
        {"Level": "department", "Key": "RETAIL", "Markup %": 0.28, "Note": "Catch-all"},
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    # Sheet names match config/column_mapping.yaml, as the real exports do.
    pd.DataFrame(gr_rows).to_excel(OUT / "GR2_sample.xlsx", sheet_name="data", index=False)
    pd.DataFrame(w10_rows).to_excel(OUT / "W10_sample.xlsx", sheet_name="data", index=False)
    pd.DataFrame(markup_rows).to_excel(
        OUT / "markup_list_sample.xlsx", sheet_name="SellingPrice", index=False)
    pd.DataFrame(sale_rows).to_excel(
        OUT / "sale_list_sample.xlsx", sheet_name="SellingPrice", index=False)

    print(f"Sample data written to {OUT}")
    print(f"  GR2  {len(gr_rows):>4} receipt lines")
    print(f"  W10  {len(w10_rows):>4} unit rows")
    print(f"  Markup rules {len(markup_rows)}")


if __name__ == "__main__":
    build()

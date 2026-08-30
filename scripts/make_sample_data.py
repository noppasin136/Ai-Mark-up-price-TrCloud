"""Generate realistic sample GR2 / W10 / markup / sale-list / My Cargo workbooks.

Run this once so the pipeline works end-to-end before your real ERP extracts
arrive, and so the column-mapping contract is visible as concrete files.

    python scripts/make_sample_data.py

The sample mirrors the real shape closely enough to exercise warehouse-aware
costing (docs/COSTING_MODEL.md): GR2 carries a warehouse column, markup_list has
one row per SKU with a pricing Category, W10 has a standard buy price, and a
My Cargo file supplies landed import cost.
"""

from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

import pandas as pd

random.seed(7)
OUT = Path(__file__).resolve().parent.parent / "data" / "input" / "samples"

# SKU-code families, purely for variety in the codes.
FAMILIES = {"BEV": "Beverage", "SNK": "Snack", "HHC": "Household Care", "PCR": "Personal Care"}

# markup_list pricing Category -> (expected markup fraction, home warehouse)
PRICING = {
    "WH": (0.12, "ST0001"),
    "Chilled": (0.15, "ST0001"),
    "Freeze": (0.20, "ST0001"),
    "CK": (0.25, "ST0002"),
}
UOMS = [("PCS", "BOX", 12), ("PCS", "CTN", 24), ("BTL", "PACK", 6), ("KG", None, 1)]
STOREFRONTS = ["ST0003", "ST0004", "ST-MEGA"]
Z_SMART = "แซด สมาร์ท เทรดดิ้ง"


def build():
    today = dt.date.today()
    gr_rows, w10_rows, sale_rows, markup_rows, cargo_rows = [], [], [], [], []

    for i in range(1, 61):
        fam = random.choice(list(FAMILIES))
        sku = f"{fam}-{i:04d}"
        name = f"{FAMILIES[fam]} Item {i:03d}"
        uom, par_uom, factor = random.choice(UOMS)
        base_cost = round(random.uniform(8, 480), 2)

        category = random.choices(list(PRICING), weights=[6, 2, 3, 4])[0]
        expected_markup, home_wh = PRICING[category]

        # A handful of SKUs are bought predominantly from Z Smart -> they should
        # price as Central Kitchen (25%) whatever their Category says.
        z_smart_sku = i % 11 == 0

        # 4 SKUs get no receipts at all (NO_COST / W10-fallback path).
        n_receipts = 0 if i % 15 == 0 else random.randint(1, 9)
        for r in range(n_receipts):
            days_ago = random.randint(0, 120)          # some fall outside a 90-day window
            drift = 1 + random.uniform(-0.10, 0.14)
            qty = random.choice([12, 24, 48, 60, 120, 240])
            unit_cost = round(base_cost * drift, 2)
            if i % 23 == 0 and r == 0:
                unit_cost = round(unit_cost * 9, 2)    # keying error -> outlier filter

            if z_smart_sku:
                wh, vendor = "ST0002", f"{Z_SMART}"
            elif i % 17 == 0:
                wh, vendor = random.choice(STOREFRONTS), f"Supplier {random.randint(1, 12):02d}"
            else:
                # mostly the home warehouse, sometimes a storefront
                wh = home_wh if random.random() < 0.75 else random.choice(STOREFRONTS)
                vendor = f"Supplier {random.randint(1, 12):02d}"

            gr_rows.append({
                "Item Code": sku,
                "Item Name": name,
                "GR Date": today - dt.timedelta(days=days_ago),
                "GR No": f"GR{2600000 + len(gr_rows)}",
                "Warehouse": wh,
                "Vendor Name": vendor,
                "Received Qty": qty,
                "UOM": uom,
                "Unit Cost": unit_cost,
                "Total Cost": round(unit_cost * qty, 2),
                "Freight": round(qty * random.uniform(0.1, 1.4), 2),
                "Import Duty": round(unit_cost * qty * random.uniform(0, 0.03), 2),
                "Currency": "THB",
            })

        current = round(base_cost * random.uniform(1.15, 1.55), 0)
        buy_price = round(base_cost * random.uniform(0.95, 1.08), 2)
        w10_rows.append({
            "Item Code": sku, "Item Name": name, "Sales Unit": uom,
            "Ccoefficient": 1, "Is Main": 1, "Sale Price": current, "Buy Price": buy_price,
            "Product Group": category, "Sub Group": f"{fam}-{(i % 3) + 1}",
            "Division": "RETAIL", "Item Status": "Active",
        })
        if par_uom:
            w10_rows.append({
                "Item Code": sku, "Item Name": name, "Sales Unit": par_uom,
                "Ccoefficient": factor, "Is Main": 0,
                "Sale Price": round(current * factor * 0.97, 0),
                "Buy Price": round(buy_price * factor, 2),
                "Product Group": category, "Sub Group": f"{fam}-{(i % 3) + 1}",
                "Division": "RETAIL", "Item Status": "Active",
            })

        # markup_list: one row per SKU. Rate = the Category's expected rate, or
        # 0.25 for an import (My Cargo is always 25%). Two SKUs deliberately
        # carry the wrong rate, to exercise MARKUP_RATE_MISMATCH.
        markup_value = 0.25 if i % 7 == 0 else expected_markup
        if i in (6, 40):
            markup_value = 0.25 if markup_value != 0.25 else 0.12
        markup_rows.append({
            "Code": sku, "Product Name": name, "Sale Unit": uom,
            "Selling Price": current, "Category": category, "Markup": markup_value,
        })
        sale_rows.append({
            "Code": sku, "Sale Unit": uom, "Product Name": name,
            "Selling Price": current, "Include": "N" if i % 20 == 0 else "Y",
        })

        # Every 7th SKU is a My Cargo import: goods cost near its receipts, with
        # a real freight slice on top.
        if i % 7 == 0:
            goods = round(base_cost, 4)
            freight = round(base_cost * random.uniform(0.15, 0.6), 4)
            row = {
                "code": sku, "name": name, "unit": uom,
                "ราคา-หน่วยหลัก": goods,
                "VAT(CARGO)": None,
                "Oversea Transport+Import duty (Optional)": freight,
                "Inland Transport (เฉลี่ย)": None,
                "Sale Price": None,
            }
            if i % 21 == 0:                    # manual price, no cost
                row["ราคา-หน่วยหลัก"] = None
                row["Oversea Transport+Import duty (Optional)"] = None
                row["Sale Price"] = current
            if i % 35 == 0 and par_uom:        # unit != base unit
                row["unit"] = par_uom
            cargo_rows.append(row)

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(gr_rows).to_excel(OUT / "GR2_sample.xlsx", sheet_name="data", index=False)
    pd.DataFrame(w10_rows).to_excel(OUT / "W10_sample.xlsx", sheet_name="data", index=False)
    pd.DataFrame(markup_rows).to_excel(
        OUT / "markup_list_sample.xlsx", sheet_name="SellingPrice", index=False)
    pd.DataFrame(sale_rows).to_excel(
        OUT / "sale_list_sample.xlsx", sheet_name="SellingPrice", index=False)
    # The real file's tab is renamed every upload, so the loader reads the first
    # sheet regardless of name — the sample uses a deliberately odd one.
    pd.DataFrame(cargo_rows).to_excel(
        OUT / "My_Cargo_sample.xlsx", sheet_name="Oct26", index=False)

    print(f"Sample data written to {OUT}")
    print(f"  GR2  {len(gr_rows):>4} receipt lines")
    print(f"  W10  {len(w10_rows):>4} unit rows")
    print(f"  markup_list {len(markup_rows)} SKU rows")
    print(f"  My Cargo {len(cargo_rows)} import rows")


if __name__ == "__main__":
    build()

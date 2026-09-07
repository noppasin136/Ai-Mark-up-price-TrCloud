"""Build the pre-upload review sheet: data/output/erp_upload/Updated price.xlsx

`markup update` writes the lean Price Upload sheet (SKU | Unit | Sale Price) that
the ERP imports. This script takes those rows and widens them into a 5-column
sheet a person can eyeball *before* pasting into the ERP:

    SKU | Product Name | Sale Unit | W10 Base Unit | Sale Price

  - Row-for-row with Price Upload. With `output.price_upload.include_parallel_rows`
    off (the default) that is one row per SKU — the sale_list unit.
  - Product Name is looked up from sale_list.xlsx (the scope file), keyed by SKU.
  - Sale Unit is the unit on the Price Upload row.
  - W10 Base Unit is the `เป็นหน่วยหลัก` flag from the W10 unit master for that
    SKU *and that unit*: 1 if it is the SKU's base unit, 0 if it is a
    parallel/pack unit, blank if W10 does not list that unit for the SKU.

It never touches the Price Upload sheet itself and never records a run. Re-run it
any time after `markup update`; it always reflects the newest workbook.

    .venv\\Scripts\\python.exe scripts/build_erp_upload.py
    .venv\\Scripts\\python.exe scripts/build_erp_upload.py --workbook data/output/markup_....xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from markup.cli import _find_input  # noqa: E402
from markup.config import AppConfig  # noqa: E402
from markup.io.loaders import load_sale_list, load_w10_units  # noqa: E402

SUBFOLDER = "erp_upload"
OUT_NAME = "Updated price.xlsx"
COLUMNS = ["SKU", "Product Name", "Sale Unit", "W10 Base Unit", "Sale Price"]

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)


def _newest_workbook(out_dir: Path) -> Path:
    hits = [
        p for p in out_dir.glob("markup_*.xlsx")
        if not p.name.startswith("~$")
    ]
    if not hits:
        sys.exit(
            f"No pricing workbook (markup_*.xlsx) in {out_dir}. Run 'markup update' first."
        )
    return max(hits, key=lambda p: p.stat().st_mtime)


def _read_upload_sheet(path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    name = next(
        (s for s in xl.sheet_names if s.strip().lower() in ("price upload", "upload")),
        xl.sheet_names[0],
    )
    df = pd.read_excel(path, sheet_name=name)
    df.columns = [str(c).strip() for c in df.columns]
    if "SKU" not in df.columns:
        sys.exit(f"'{name}' in {path.name} has no SKU column (found: {list(df.columns)})")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook", help="Pricing workbook to widen (default: newest in data/output/)")
    ap.add_argument("--out", help="Destination file (default: data/output/erp_upload/Updated price.xlsx)")
    ap.add_argument("--config", default=str(ROOT / "config" / "config.yaml"))
    ap.add_argument("--mapping", default=str(ROOT / "config" / "column_mapping.yaml"))
    args = ap.parse_args()

    cfg = AppConfig.load(args.config, args.mapping)
    out_dir = cfg.resolve(cfg.out_dir)

    workbook = Path(args.workbook) if args.workbook else _newest_workbook(out_dir)
    if not workbook.exists():
        sys.exit(f"Workbook not found: {workbook}")

    upload = _read_upload_sheet(workbook)
    price_col = next((c for c in upload.columns if c.lower() in ("sale price", "price")), None)
    unit_col = next((c for c in upload.columns if c.lower() in ("unit", "sale unit")), None)

    # sale_list — Product Name and Sale Unit, keyed by SKU
    sale_path = _find_input(cfg, "sale_list")
    if sale_path is None:
        sys.exit("sale_list not found in data/input/ — cannot look up product name / sale unit.")
    sale = load_sale_list(sale_path, cfg.mapping)
    sale["sku"] = sale["sku"].astype(str).str.strip()
    sl_name = dict(zip(sale["sku"], sale.get("product_name", pd.Series(dtype=str))))

    # W10 — (sku, unit) -> base-unit flag
    w10_path = _find_input(cfg, "w10")
    if w10_path is None:
        sys.exit("W10 not found in data/input/ — cannot look up the base-unit flag.")
    w10 = load_w10_units(w10_path, cfg.mapping)
    w10["sku"] = w10["sku"].astype(str).str.strip()
    base_flag = {
        (r.sku, str(r.uom).strip().lower()): int(r.is_base_unit)
        for r in w10.itertuples()
    }

    if not unit_col:
        sys.exit(f"{workbook.name} Price Upload has no Unit column (found: {list(upload.columns)})")

    rows = []
    for r in upload.to_dict("records"):
        sku = str(r.get("SKU")).strip()
        unit = str(r.get(unit_col)).strip()
        flag = base_flag.get((sku, unit.lower()))
        rows.append({
            "SKU": sku,
            "Product Name": sl_name.get(sku) or "",
            "Sale Unit": unit,
            "W10 Base Unit": "" if flag is None else flag,
            "Sale Price": r.get(price_col) if price_col else "",
        })

    out = pd.DataFrame(rows, columns=COLUMNS)
    if args.out:
        dest = Path(args.out)
        dest.parent.mkdir(parents=True, exist_ok=True)
    else:
        dest_dir = out_dir / SUBFOLDER
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / OUT_NAME

    with pd.ExcelWriter(dest, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="Updated price", index=False)
        ws = writer.book["Updated price"]
        for i, col in enumerate(COLUMNS, start=1):
            c = ws.cell(row=1, column=i)
            c.fill, c.font = HEADER_FILL, HEADER_FONT
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            longest = out[col].astype(str).str.len().max() or 10
            ws.column_dimensions[get_column_letter(i)].width = max(len(col) + 4, min(int(longest) + 3, 46))
        ws.row_dimensions[1].height = 26
        ws.freeze_panes = "A2"
        for row_idx in range(2, len(out) + 2):
            ws.cell(row=row_idx, column=5).number_format = "#,##0.00"

    missing = int((out["W10 Base Unit"] == "").sum())
    print(f"Wrote {dest}")
    print(f"  rows                {len(out)}  (from {workbook.name})")
    print(f"  base unit (1)       {int((out['W10 Base Unit'] == 1).sum())}")
    print(f"  parallel unit (0)   {int((out['W10 Base Unit'] == 0).sum())}")
    print(f"  not in W10 ( )      {missing}")
    dups = out["SKU"].duplicated().sum()
    if dups:
        print(f"  note: {dups} SKU(s) on more than one row (include_parallel_rows is on)")


if __name__ == "__main__":
    main()

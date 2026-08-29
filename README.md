# Markup Pricing Engine

Turns two ERP extracts and a markup master into an Excel price file, with the
period and the costing method as parameters rather than as code.

```
GR2  (goods receipts) ─┐
W10  (current prices) ─┼─► cost per SKU ─► markup ─► rounding ─► guardrails ─► pricing.xlsx
markup list           ─┤
sale list (optional)  ─┘
```

## Quick start

**Windows / VS Code** — run `setup.bat`, or in VS Code use
Terminal > Run Task > "Setup: create environment". Full walkthrough:
[docs/VSCODE_SETUP.md](docs/VSCODE_SETUP.md).

Manually, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pip install -e .

markup check
markup review
markup update
markup report
```

The workbook lands in `data/output/`.

**Everything you will want to change lives in [`config/config.yaml`](config/config.yaml).
[INSTRUCTIONS.md](INSTRUCTIONS.md) explains each parameter.**

## Inputs

Drop the ERP exports into **`data/input/`** using the standard names below —
that folder has its own [PUT_ERP_FILES_HERE.md](data/input/PUT_ERP_FILES_HERE.md)
with the same list. Then run `markup check` to confirm they parse. Header names are matched through
`config/column_mapping.yaml`, so no renaming in Excel is needed — add your real
header spelling to the candidate list and the engine finds it.

| File | What it provides | Required columns |
|---|---|---|
| `GR2*.xlsx` | Goods receipts — the cost source | SKU, GR date, qty, unit cost |
| `W10*.xlsx` | Every sellable unit per SKU, with coefficients | SKU, unit |
| `markup_list*.xlsx` | Markup per SKU or product group | key, markup |
| `sale_list*.xlsx` *(optional)* | Which SKUs to price and in which unit | SKU |

W10 carries **one row per SKU and unit**, not one per SKU. That is what makes
cost conversion between units possible, and where the base unit is identified.

## Output

`markup update` writes the pricing workbook; `markup report` writes a separate
analysis workbook (Summary, Biggest Movers, By Category, vs Previous Run).

| Sheet | Contents |
|---|---|
| **Price Upload** | `SKU · Unit · Sale Price` — lean and import-ready |
| Detail | Every column behind each price: cost, markup, margin, variance |
| Exceptions | Rows a human must clear; each carries a plain-language reason |
| Cost Audit | The GR2 lines each cost was built from, and which were used |
| Run Summary | The exact parameters that produced the file |

Rows that trip a blocking guardrail never reach the Price Upload sheet.

## Commands

Everyday use is four commands, in this order:

```bash
markup check      # is data/input/ ready? which columns mapped?
markup review     # any SKU whose selling unit and receipt unit disagree
markup update     # price everything, write the workbook, record the run
markup report     # summary, category rollup, and a diff vs the previous run
```

`update` finds the ERP files by prefix in `data/input/`, so the long names the
ERP exports (`GR2_รายงานใบรับสินค้าแสดงต้นทุน_....xlsx`) work unrenamed. Every
run is snapshotted, which is what lets `report` compare this month against last.

`review` is the safety gate. Cost is recorded per unit *received* and price is
published per unit *sold*; where those differ the conversion has to be right,
and only a person who knows the product can confirm it. Anything questionable
goes to `config/unit_review.xlsx` and stays off the upload sheet until you set
its Decision. See [INSTRUCTIONS.md](INSTRUCTIONS.md#unit-review).

Supporting commands:

```bash
markup runs                             # list recorded runs
markup review --show-all                # every review entry, decided or not
markup validate                         # check config.yaml for contradictions
markup methods                          # list costing methods and rounding rules
markup update --period 30 --method fifo # override parameters for one run
markup report --against 20260731_090000_001  # compare against a specific run
markup run --gr2 ... --w10 ...          # explicit paths, no history recorded
```

`python -m markup <command>` works identically if you skip `pip install -e .`.

## Project layout

```
config/         config.yaml (all parameters) + column_mapping.yaml (ERP headers)
src/markup/
  config.py     loads and validates every parameter — the single source of truth
  io/           loaders + canonical column contracts
  costing/      base.py (registry) · methods.py (FIFO/LIFO/WAVG/...) · engine.py
  rules/        markup.py (category lookup) · rounding.py (rounding strategies)
  uom.py        parallel-unit derivation
  validation.py guardrails and the exception catalogue
  pipeline.py   orchestration
  report/       Excel writer
tests/          unit tests + an end-to-end run over the sample data
scripts/        sample data generator
```

Each layer is independently testable and swappable. A new costing method is one
class with a `@register("name")` decorator; a new rounding rule is one function
with `@strategy("name")`. Both become valid `config.yaml` values immediately.

## Notes on FIFO / LIFO

GR2 records what came **in**, never what went **out**, so there is no
consumption ledger to consume layers against. Within this engine FIFO means
*"cost from the oldest receipt layers in the period"* and LIFO *"from the
newest"*, with `costing.layer_coverage_pct` controlling how much of the period
quantity is blended. This is documented behaviour, not a hidden approximation —
see [INSTRUCTIONS.md](INSTRUCTIONS.md#costing-method).

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Data handling

`.gitignore` excludes `data/input/` and `data/output/` — ERP extracts and priced
output must not be committed. Only the config, code and tests belong in git.

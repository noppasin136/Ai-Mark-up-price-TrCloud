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

```bash
python -m venv .venv && . .venv/Scripts/activate     # Windows
pip install -r requirements.txt
pip install -e .

python scripts/make_sample_data.py                   # optional: sample inputs
markup run --period 90 --method weighted_average
```

The workbook lands in `data/output/`.

**Everything you will want to change lives in [`config/config.yaml`](config/config.yaml).
[INSTRUCTIONS.md](INSTRUCTIONS.md) explains each parameter.**

## Inputs

Drop the ERP exports into `data/input/`. Header names are matched through
`config/column_mapping.yaml`, so no renaming in Excel is needed — add your real
header spelling to the candidate list and the engine finds it.

| File | What it provides | Required columns |
|---|---|---|
| `GR2.xlsx` | Goods receipts — the cost source | SKU, GR date, qty, unit cost |
| `W10.xlsx` | Current sale price, UOM, parallel unit, category | SKU, price |
| `markup_list.xlsx` | Markup % by product group | key, markup % |
| `sale_list.xlsx` *(optional)* | Which SKUs to price and in which unit | SKU |

## Output

| Sheet | Contents |
|---|---|
| **Price Upload** | `SKU · Unit · Sale Price` — lean and import-ready |
| Detail | Every column behind each price: cost, markup, margin, variance |
| Exceptions | Rows a human must clear; each carries a plain-language reason |
| Cost Audit | The GR2 lines each cost was built from, and which were used |
| Run Summary | The exact parameters that produced the file |

Rows that trip a blocking guardrail never reach the Price Upload sheet.

## Commands

```bash
markup run                          # use config.yaml as-is
markup run --period 30 --method fifo    # override for one run
markup run --dry-run                # compute and summarise, write nothing
markup validate                     # check config.yaml for contradictions
markup methods                      # list costing methods and rounding rules
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

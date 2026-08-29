# Architecture

## Why it is split this way

Pricing logic changes constantly — a new costing method, a different rounding
convention, one more guardrail. The split exists so each of those is a change in
exactly one place, and so every step can be tested without Excel.

```
config.py      validated parameters — the only module that reads YAML
   │
io/            ERP file  →  canonical DataFrame   (headers absorbed here)
   │
costing/       GR2 lines →  one unit cost per SKU (strategy registry)
   │
rules/         cost      →  price                 (markup lookup, then rounding)
uom.py         price     →  parallel-unit price
   │
validation.py  price     →  flags                 (one catalogue, one place)
   │
report/        results   →  workbook              (presentation only)
```

`pipeline.py` is the only module that knows the order.

## The two registries

Costing methods and rounding strategies are both name → implementation maps
populated by decorators. Adding either is one class or function plus a name in
`config.yaml`; no dispatch table, no `if/elif` chain, no other file to touch.
`markup methods` lists what is currently registered.

## Design decisions worth knowing

**Canonical column names.** Every loader renames incoming headers to a fixed
internal vocabulary. ERP report changes are absorbed in one YAML file rather than
rippling through the codebase.

**Costing is separate from pricing.** `cost_skus()` produces a cost per SKU and
knows nothing about markup; the markup layer knows nothing about receipts. Either
side can be replaced independently.

**Flags, not exclusions.** Validation never drops a row. It attaches flag codes,
and `blocked` is derived from the catalogue. A SKU that does not get priced is
always visible, with a reason, on the Exceptions sheet.

**Rounding is applied once, at the end.** Markup produces `raw_price`; rounding
produces `suggested_price`. Both are kept, so realised margin is computed against
the price actually charged, not the theoretical one.

**Parallel price is derived from the unrounded base.** Multiplying a rounded unit
price by 24 multiplies the rounding error by 24. See `uom.py`.

**The workbook is a view.** `report/excel.py` contains no business logic — it
formats what the pipeline already decided. Changing the output format cannot
change a price.

## Adding a real FIFO

When an issues/consumption report becomes available, add a method that consumes
layers against actual issue quantities:

```python
@register("fifo_consumed")
class FifoConsumed(CostingMethod):
    def compute(self, layers, *, coverage_pct=100.0):
        ...  # walk layers oldest-first against issued qty
```

`engine.py` passes each SKU's layers already filtered, sorted and outlier-cleaned,
so the new method only implements the consumption walk. Everything downstream is
unchanged.

# Changelog

## 0.2.0

- `markup check` — validates `data/input/` and reports column-mapping problems
  before anything is priced
- `markup update` — the everyday command: finds the ERP files by their standard
  names, prices them, writes the workbook, snapshots the run
- `markup report` — run summary, biggest movers, category rollup, and a
  SKU-level diff against the previous run
- `markup runs` — lists recorded runs
- Run history in `data/output/history/`, with automatic pruning
- `data/input/` drop folder with naming instructions and an `archive/` subfolder

## 0.1.0

Initial framework.

- Config-driven run parameters: period, costing method, markup, rounding,
  guardrails, output
- Costing strategies: `weighted_average`, `fifo`, `lifo`, `last_cost`,
  `highest_cost`, `lowest_cost`, with a configurable fallback
- Landed-cost basis (freight + duty + other, spread per unit)
- IQR / z-score outlier suppression, fully traceable on the Cost Audit sheet
- Markup resolution with a configurable fallback chain
  (sku → subcategory → category → department → default)
- `cost_plus` and `margin` bases, with per-row overrides in the markup list
- Rounding strategies: `nearest`, `step_ceiling`, `step_floor`, `psychological`,
  `none`, plus optional cost bands
- Parallel-unit pricing derived from the unrounded base price
- Guardrails with block-or-clamp behaviour and an 11-code exception catalogue
- Five-sheet Excel output with a lean `SKU · Unit · Sale Price` upload sheet
- CLI: `run`, `validate`, `methods`, with per-run overrides and `--dry-run`
- Unit tests plus an end-to-end run over generated sample data

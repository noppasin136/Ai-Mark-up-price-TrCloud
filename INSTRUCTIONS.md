# How to change the parameters

Everything tunable lives in **`config/config.yaml`**. Edit that file, save, and
re-run — no Python changes. Anything you can set there you can also override for
a single run from the command line.

Sanity-check a change before running the whole thing:

```bash
markup validate
```

---

## 1. Period — how far back to cost

```yaml
run:
  as_of_date: null      # null = today; or a fixed date like 2026-08-31
  period_days: 90       # 30 | 60 | 90 | any positive integer
```

The costing window is `as_of_date - period_days` to `as_of_date`. Only GR2
receipt lines inside that window are used.

```bash
markup run --period 30
markup run --period 60 --as-of 2026-06-30     # reproduce a month-end run
```

**Choosing a period.** A short window tracks supplier price moves quickly but
prices fewer SKUs — anything without a receipt in the window gets no cost and
lands on the Exceptions sheet. A long window covers more SKUs but reacts slowly.
Watch `SKUs without cost` in the run summary: if it climbs, lengthen the period.

Pin `as_of_date` whenever you need to reproduce an old run exactly.

---

## 2. Costing method

```yaml
costing:
  method: weighted_average
  fallback_method: last_cost
  layer_coverage_pct: 30
  cost_basis: landed_cost
```

| Method | What it does | Use it when |
|---|---|---|
| `weighted_average` | Quantity-weighted mean of every receipt in the window | Default. Stable, hard to argue with. |
| `fifo` | Oldest receipt layers in the window | You sell down old stock first and want prices to reflect what is actually on the shelf |
| `lifo` | Newest receipt layers in the window | Costs are moving fast and you want prices to follow |
| `last_cost` | The single most recent receipt | Volatile imports; maximum responsiveness |
| `highest_cost` | Worst case in the window | Margin protection during an unstable period |
| `lowest_cost` | Best case in the window | Deliberate price aggression on selected lines |

```bash
markup run --method fifo
markup run --method lifo --period 60
```

### About FIFO and LIFO here

GR2 is a **receipts** report. It records what came in, never what went out, so
there is no consumption ledger for a textbook FIFO to consume layers against.
This engine therefore defines:

- **FIFO** → cost from the **oldest** receipt layers in the period
- **LIFO** → cost from the **newest** receipt layers in the period

`layer_coverage_pct` decides how much of the period's receipt quantity gets
blended in:

| Value | Effect |
|---|---|
| `100` | Every layer blended — FIFO, LIFO and weighted average all give the same number |
| `30` (default) | Only the oldest / newest 30% of the period quantity |
| `10` | Sharper — close to "the earliest / latest receipts only" |

A boundary layer is split proportionally rather than dropped, so the blend is
exact. If you later export an issues/consumption report, a true layer-consuming
method drops into `src/markup/costing/methods.py` without touching anything else.

### Fallback

`fallback_method` catches SKUs the primary method cannot cost (usually a single
receipt where layer logic has nothing to work with). Set it to `null` to send
those SKUs to Exceptions instead. The Detail sheet marks any row where the
fallback was used.

### Cost basis

```yaml
cost_basis: landed_cost   # unit_cost | landed_cost
```

`landed_cost` adds freight + duty + other landed components, spread per unit.
`unit_cost` uses the purchase price alone. Map those GR2 columns in
`config/column_mapping.yaml`; missing ones are treated as zero.

### Outlier suppression

```yaml
outlier_filter:
  enabled: true
  method: iqr        # iqr | zscore | none
  threshold: 1.5
  min_lines: 5
```

Stops one mis-keyed GR line from dragging a whole SKU's cost. Dropped lines are
still visible on the Cost Audit sheet with `used_in_costing = FALSE`, and the
count appears in the Detail sheet — nothing disappears silently. SKUs with fewer
than `min_lines` receipts are left alone.

---

## 3. Markup rules

```yaml
markup:
  fallback_chain: [sku, subcategory, category, department, default]
  default_pct: 30.0
  basis: cost_plus
  min_margin_pct: 5.0
```

Each SKU walks the chain in order and takes the **first** rule that matches, so
a SKU-level exception beats a subcategory rule, which beats a category rule.
Shorten the chain to simplify: `[category, default]` uses category rules only.

### The markup list file

| Level | Key | Markup % | Note |
|---|---|---|---|
| category | BEV | 25 | Beverage standard |
| subcategory | PCR-1 | 50 | Premium sub-group |
| sku | BEV-0003 | 18 | Known-value item |
| department | RETAIL | 28 | Catch-all |

`Level` is optional — omit the column and every row is treated as `category`.
Optional `Basis` and `Min Margin` columns override the global setting per row.

### cost_plus vs margin

| Basis | Formula | 30% on a cost of 100 |
|---|---|---|
| `cost_plus` | `cost × (1 + pct/100)` | **130.00** |
| `margin` | `cost ÷ (1 − pct/100)` | **142.86** |

Getting this wrong is the single most expensive mistake available here, so check
which one your markup list actually means before the first live run.

`min_margin_pct` is a floor on the **realised** margin after rounding. Rows below
it are flagged `BELOW_MIN_MARGIN` and held back from the upload sheet.

---

## 4. Rounding

```yaml
rounding:
  strategy: nearest     # none | nearest | step_ceiling | step_floor | psychological
  step: 1.00
  direction: half_up    # half_up | up | down
  endings: [0.95, 0.99]
  use_bands: false
```

| Strategy | 127.34 with `step: 1` becomes |
|---|---|
| `none` | 127.34 |
| `nearest` (`half_up`) | 127.00 |
| `nearest` (`up`) | 128.00 |
| `step_ceiling` (`step: 5`) | 130.00 |
| `step_floor` (`step: 5`) | 125.00 |
| `psychological` | 127.95 |

```bash
markup run --rounding psychological
markup run --rounding step_ceiling --step 5
```

### Cost bands

Set `use_bands: true` to vary the rule by cost — cheap lines to the nearest 0.50,
mid-range to the nearest 1, expensive lines rounded up to the nearest 5:

```yaml
  use_bands: true
  bands:
    - {max_cost: 50,    strategy: nearest,      step: 0.50}
    - {max_cost: 500,   strategy: nearest,      step: 1.00}
    - {max_cost: null,  strategy: step_ceiling, step: 5.00}
```

The first band whose `max_cost` covers the SKU's cost wins; `null` means no upper
bound, so keep that entry last. While `use_bands` is true the top-level
`strategy` and `step` are ignored — a `--rounding` flag on the command line turns
bands off for that run so your override actually takes effect.

---

## 5. Parallel unit

```yaml
parallel_unit:
  enabled: true
  round_separately: true
  strategy: nearest
  step: 1.00
  bulk_discount_pct: 0.0
```

The parallel price is the base price × the conversion factor from W10 (the
number of base units in one parallel unit — 12 pieces per box, say).

With `round_separately: true` the calculation starts from the **unrounded** base
price, so rounding error is not multiplied by the pack size, and the pack price
is then rounded on its own. Set it to `false` to scale the published base price
directly, which keeps `pack = unit × factor` exactly true at the cost of an
uglier number.

`bulk_discount_pct` shaves a percentage off the pack price to reward buying the
larger unit. A SKU with no parallel unit, or a factor of 1, simply gets no
parallel row.

Set `enabled: false` to price base units only.

---

## 6. Guardrails

```yaml
guardrails:
  max_increase_pct: 25.0
  max_decrease_pct: 10.0
  clamp: false
  flag_price_decrease: true
  min_change_pct: 0.5
```

Movement limits are measured against the current W10 price.

- `clamp: false` — a breach **blocks** the row; it appears on Exceptions and is
  kept off the upload sheet. Safer, and the default.
- `clamp: true` — the price is **capped** at the limit and shipped, flagged
  `CLAMPED_UP` / `CLAMPED_DOWN`.

`min_change_pct` suppresses trivial moves so you are not republishing the whole
catalogue over a few satang.

### Flags you will see on the Exceptions sheet

| Code | Meaning | Blocks upload |
|---|---|---|
| `NO_COST` | No goods receipt in the period | yes |
| `NEGATIVE_MARGIN` | Suggested price is below cost | yes |
| `BELOW_MIN_MARGIN` | Margin under the floor | yes |
| `OVER_MAX_INCREASE` | Increase past the guardrail | yes |
| `OVER_MAX_DECREASE` | Decrease past the guardrail | yes |
| `MISSING_IN_W10` | In the sale list but not in W10 | yes |
| `NO_MARKUP_RULE` | Default percentage was used | no |
| `PRICE_DECREASE` | Lower than the current price | no |
| `NO_CURRENT_PRICE` | New item, nothing to compare | no |
| `BELOW_MIN_CHANGE` | Move too small to bother with | no |
| `BAD_CONVERSION` | Parallel unit present, factor missing | no |

---

## 7. Output

```yaml
output:
  directory: data/output
  filename: markup_{method}_{period}d_{timestamp}.xlsx
  sheets: [price_upload, detail, exceptions, cost_audit, run_summary]
  price_upload:
    sheet_name: "Price Upload"
    include_parallel_rows: true
    only_changed: true
    exclude_exceptions: true
```

Filename placeholders: `{method}` `{period}` `{timestamp}` `{as_of}`.

Drop any sheet you do not want from the `sheets` list. Set `only_changed: false`
to emit every SKU rather than just the movers.

---

## 8. Mapping your ERP column names

`config/column_mapping.yaml` maps canonical names (left, never rename these) to
the header spellings your ERP produces (right). Matching ignores case, spaces and
underscores.

```yaml
gr2:
  sheet: 0          # sheet name, or 0-based index
  header_row: 0     # 0-based row holding the headers
  columns:
    sku:         [SKU, Item Code, Item No, Your Actual Header]
    receipt_date: [GR Date, Posting Date]
```

If a required column cannot be found the run stops immediately and prints the
headers it *did* see, so you can paste the right one straight into this file.
When the report has a title block above the headers, set `header_row` to the
0-based row index of the real header line.

---

## 9. A typical workflow

1. Export GR2 and W10 from the ERP and save them into `data/input/` as
   **`GR2.xlsx`** and **`W10.xlsx`**. Add `markup_list.xlsx`, and
   `sale_list.xlsx` if you use one.
2. `markup check` — confirms each file parses and every required column mapped.
   Fix any header spelling it reports in `config/column_mapping.yaml`.
3. `markup update` — prices everything and writes the workbook.
4. `markup report` — summary, category rollup, and a diff against your last run.
5. Open **Exceptions** first. Clear or accept each row.
6. Upload the **Price Upload** sheet to the ERP.
7. Move this month's exports into `data/input/archive/` so next month starts clean.

Each workbook carries its own **Run Summary** sheet, so there is never any doubt
about which parameters produced which prices.

### Changing parameters for one run only

```bash
markup update --period 30
markup update --method fifo --period 60
markup update --as-of 2026-06-30        # reproduce a month-end
```

`config.yaml` stays the team's agreed baseline; the flags apply to that run only.

### Run history

`markup update` snapshots every run into `data/output/history/` — the priced
detail plus the parameters that produced it. That is what makes comparison
possible.

```bash
markup runs                              # what has been recorded
markup report                            # latest vs the one before it
markup report --against 20260731_090000_001   # latest vs a specific run
markup report --group-by department      # roll up by something else
markup update --keep-history 36          # retain more snapshots (default 24)
```

Deleting `data/output/history/` is safe — it only costs you the comparison.

### Comparing scenarios side by side

```bash
markup run --method fifo             --out data/output/scenario_fifo.xlsx
markup run --method lifo             --out data/output/scenario_lifo.xlsx
markup run --method weighted_average --out data/output/scenario_wavg.xlsx
```

`run` takes explicit paths and does **not** record history, so scenario testing
never pollutes the month-to-month comparison. Use `update` for real runs.

## 10. Extending the engine

**A new costing method** — add to `src/markup/costing/methods.py`:

```python
@register("median_cost")
class MedianCost(CostingMethod):
    """Median receipt cost — outlier-resistant without a filter."""

    def compute(self, layers, *, coverage_pct=100.0):
        return float(layers["effective_cost"].median()), "median of GR lines"
```

`costing.method: median_cost` now works. Nothing else changes.

**A new rounding rule** — add to `src/markup/rules/rounding.py`:

```python
@strategy("nearest_ten_or_five")
def _ten_or_five(price, rule):
    return round(price / 5) * 5
```

**A new guardrail** — add a code to `FLAG_CATALOG` in `src/markup/validation.py`
(with `True` if it should block upload) and one `flag(...)` call in
`apply_guardrails`. It flows through to the Exceptions sheet automatically.

Run `pytest -q` after any change.

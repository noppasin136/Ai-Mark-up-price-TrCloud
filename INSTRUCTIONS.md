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
  value_scale: 100
```

**`value_scale`** turns the file's markup values into percentages. This ERP's
list stores fractions — `0.12` meaning 12% — so the scale is `100`. Set it to
`1` if your list ever switches to whole percentages. Getting this wrong is
silent and severe: at `value_scale: 1` a 0.12 markup would price everything at
cost plus a tenth of a percent.

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

Set `enabled: false` to price base units only. Whether a parallel price reaches
the **Price Upload** sheet is a separate switch,
`output.price_upload.include_parallel_rows` (§7), which is off by default — so
out of the box the upload carries one row per SKU, the `sale_list` unit.

---

## 6. Guardrails

```yaml
guardrails:
  max_increase_pct: 25.0
  max_decrease_pct: 25.0
  clamp: false
  flag_price_decrease: true
  min_change_pct: 0.5
```

Movement limits are measured against the current W10 price, as a percentage.
A SKU that moves more than the limit is flagged `OVER_MAX_INCREASE` /
`OVER_MAX_DECREASE` and listed on Exceptions — but it **still ships** on the
Price Upload sheet. The flag is a "look at this", not a block; a big move is
usually a stale current price catching up, not an error. Nothing is required to
let it through.

**To loosen or tighten the limits**, edit these two numbers in
`config/config.yaml` (they sit under the `>>> GUARDRAIL PARAMETERS <<<` banner,
in the same file as every other setting), then re-run `markup update`:

- **Raise** them and fewer SKUs get the review flag.
- **Lower** them and more do.
- They are independent: allow a large drop while keeping rises tight.

There is no command-line flag for these — they are `config.yaml` only, so a
change is deliberate and stays the team's baseline until edited back.

- `clamp: false` (default) — the breaching price ships as calculated, with the
  review flag.
- `clamp: true` — the price is instead **capped** at the limit and shipped,
  flagged `CLAMPED_UP` / `CLAMPED_DOWN`.

**To veto a specific soft-flagged row**, open `config/price_review.xlsx` (rebuilt
by every `markup update`), set its `Decision` to `HOLD`, and re-run — that SKU is
then kept off the upload (`PRICE_HELD`). Blank or `OK` means it ships.

`min_change_pct` suppresses trivial moves so you are not republishing the whole
catalogue over a few satang.

### Flags you will see on the Exceptions sheet

Two tiers. **Hard** flags keep the row off Price Upload — there is nothing safe
to send. **Soft** flags stay on Price Upload and only ask for a look.

| Code | Meaning | Tier |
|---|---|---|
| `NO_COST` | No goods receipt in the period | hard |
| `NEGATIVE_MARGIN` | Suggested price is below cost | hard |
| `BELOW_MIN_MARGIN` | Margin under the floor | hard |
| `MISSING_IN_W10` | In the sale list but not in W10 | hard |
| `UNIT_UNVERIFIED` | Unit conflict not yet decided in the review sheet | hard |
| `UNIT_EXCLUDED` | Excluded by a decision in the review sheet | hard |
| `UNKNOWN_SALE_UNIT` | Sale unit is not listed for this SKU in W10 | hard |
| `MYCARGO_UNIT_MISMATCH` | My Cargo unit ≠ the SKU's W10 base unit | hard |
| `PRICE_HELD` | Vetoed by a `HOLD` in `config/price_review.xlsx` | hard |
| `OVER_MAX_INCREASE` | Increase past the guardrail | soft |
| `OVER_MAX_DECREASE` | Decrease past the guardrail | soft |
| `PRICE_DECREASE` | Lower than the current price | soft |
| `NO_CURRENT_PRICE` | New item, nothing to compare | soft |
| `NO_MARKUP_RULE` | Default percentage was used | soft |
| `BELOW_MIN_CHANGE` | Move too small to bother with | soft |
| `UNIT_CORRECTED` | Costed under an approved unit correction | soft |
| `COST_FROM_MYCARGO` | Costed from the My Cargo import file | soft |
| `COST_FROM_OTHER_WH` | Costed from the other head-office warehouse | soft |
| `COST_FROM_W10` | Costed from the W10 standard cost (no receipt) | soft |
| `MANUAL_PRICE` | Held at its current price (My Cargo gives a price, not a cost) | soft |
| `MARKUP_RATE_MISMATCH` | `markup_list` rate ≠ the routing rule's expected rate | soft |

---

## 7. Output

```yaml
output:
  directory: data/output
  filename: markup_{method}_{period}d_{timestamp}.xlsx
  sheets: [price_upload, detail, exceptions, cost_audit, run_summary]
  price_upload:
    sheet_name: "Price Upload"
    include_parallel_rows: false
    only_changed: true
    exclude_exceptions: true
```

Filename placeholders: `{method}` `{period}` `{timestamp}` `{as_of}`.

Drop any sheet you do not want from the `sheets` list. Set `only_changed: false`
to emit every SKU rather than just the movers.

`include_parallel_rows` controls whether the Price Upload sheet also carries a
row for each *other* unit W10 lists for a SKU (the pack as well as the bag).
Default `false`: one row per SKU, the `sale_list` selling unit only. Set it to
`true` to publish every unit in one run — the extra prices are derived per
§5 (`parallel_unit`). The Detail sheet always carries one row per SKU (the
sale unit) regardless. `scripts/build_erp_upload.py` mirrors whatever the upload
sheet contains.

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

## 9. Unit review

Cost arrives per unit **received**; price is published per unit **sold**. When
those differ the engine converts using W10's coefficient — and the conversion is
only ever as good as the ERP's unit data. Two different things happen in
practice, and no formula can tell them apart:

- the sale unit is genuinely a parallel unit, so the coefficient is correct; or
- the receipt was keyed against the wrong unit. The ถุงร้อน items are bought by
  the pack but entered as bag, so applying the ×4 would quadruple a cost that is
  already per pack.

So every questionable SKU is written to **`config/unit_review.xlsx`** and held
off the price upload until you decide it.

```bash
markup review              # refresh the sheet with anything new
markup review --show-all   # include rows already decided
```

A SKU is flagged when any of these is true:

| Trigger | Meaning |
|---|---|
| sale unit is not among the units received | the two reports disagree |
| sale unit is a W10 parallel unit (coefficient > 1) | conversion applies — confirm once |
| converted cost exceeds the selling price by more than 25% | the classic signature of a mis-keyed unit |

### Deciding

Open the file and set the **Decision** column (it has a dropdown):

| Decision | Effect |
|---|---|
| `PENDING` | *(default)* held back — excluded from Price Upload |
| `ACCEPT` | the conversion is right; price it normally |
| `TREAT_AS` | the receipt unit is wrong — put the real unit in **Treat GR Unit As** |
| `EXCLUDE` | do not price this SKU at all |

`TREAT_AS` re-reads that SKU's receipts under the unit you name, *before* any
coefficient is applied. For the ถุงร้อน items, `Treat GR Unit As = pack` turns a
90.06 "bag" receipt into a 90.06 pack — which is what was actually bought.

Decisions persist. Re-running `markup review` only adds newly-flagged SKUs and
never overwrites a decision you have made, so the sheet doubles as the audit
trail for why a price is what it is. The **Note** column is yours.

A SKU still awaiting a decision carries the `UNIT_UNVERIFIED` flag, appears on
the Exceptions sheet, and cannot reach Price Upload. The run still completes, so
the rest of the catalogue is usable while you work through them.

---

## 10. A typical workflow

1. Export GR2 and W10 from the ERP into `data/input/`. Filenames do not matter
   as long as they start with `GR2`, `W10`, `markup_list` and `sale_list` — the
   ERP's long Thai names work unrenamed.
2. `markup check` — confirms each file parses and every required column mapped.
   Fix any header spelling it reports in `config/column_mapping.yaml`.
3. `markup review` — decide any newly flagged units. Usually nothing new.
4. `markup update` — prices everything and writes the workbook.
5. `markup report` — a director dashboard (round-at-a-glance tiles and a verdict,
   margin and movement by category) followed by the analyst tables: summary,
   category rollup, and a diff against your last run. Written as
   `data/output/Pricing report - <D Mon YYYY>.html` and a fixed-name
   `Report - latest.html` copy (open either in a browser). Every average is an
   unweighted per-SKU mean — the inputs carry no sales volume.
6. Open **Exceptions** first. Clear or accept each row.
7. Upload the **Price Upload** sheet to the ERP.
8. Move this month's exports into `data/input/archive/` so next month starts clean.

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

---

## 11. Warehouse routing

```yaml
warehouse_routing:
  enabled: true
  main_warehouse: ST0001
  central_kitchen_warehouse: ST0002
  central_kitchen_categories: [CK, "Central Kitchen"]
  z_smart_supplier_match: "แซด สมาร์ท"
  z_smart_needs_majority: true
  category_rate_pct: {WH: 12.0, Chilled: 15.0, Freeze: 20.0, CK: 25.0, "Central Kitchen": 25.0}
  import_rate_pct: 25.0
  rate_mismatch_tolerance_pct: 0.5
```

Full rationale: **`docs/COSTING_MODEL.md`**. In short, with `enabled: true` each
in-scope SKU is:

1. **Routed** — `import` (in the My Cargo file), `central_kitchen` (Category
   `CK`/`Central Kitchen`, or bought mostly from Z Smart), or `warehouse`.
2. **Costed**, first match: the My Cargo landed cost → the route's home warehouse
   (`ST0001` / `ST0002`) receipts → the other head-office warehouse
   (`COST_FROM_OTHER_WH`) → the W10 standard `buy_price` (`COST_FROM_W10`) →
   `NO_COST`. **Storefront receipts are never used.**
3. **Priced** at the `markup_list` Markup rate. `category_rate_pct` /
   `import_rate_pct` are only the *expected* rate — a disagreement raises the
   soft `MARKUP_RATE_MISMATCH` flag.

The My Cargo file (`data/input/My Cargo.xlsx`) is optional and matched by prefix;
its tab is read as the first sheet regardless of name. A row quoted in a unit
that is not the SKU's W10 base unit is held back with `MYCARGO_UNIT_MISMATCH`.

Set `enabled: false` for the old behaviour — every receipt line costed together,
no My Cargo file, no W10 fallback.

## 12. Extending the engine

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
with its tier (`HARD` keeps the row off Price Upload, `SOFT` ships it and lists
it for review) and one `flag(...)` call in `apply_guardrails`. It flows through
to the Exceptions sheet automatically.

Run `pytest -q` after any change.

# Markup Pricing Engine

Turns ERP goods-receipt costs into a suggested selling price per SKU, and writes
an Excel workbook the ERP can import. The user is a finance/operations person,
not a developer — explain results in business terms, not log output.

## The flow

Always this order. Each step is a slash command.

| Command | Does |
|---|---|
| `/check` | Are the ERP exports present, and do the columns map? |
| `/review` | SKUs whose selling unit and receipt unit disagree — needs a human decision |
| `/update` | Price everything, write the workbook, record the run |
| `/report` | Summary, category rollup, diff against the previous run |

`/markup` runs the whole sequence with judgement. `/setup` builds the
environment. `/audit` produces a full data-quality report.

## How to run the engine

Windows, and the environment may not be activated. In order of preference:

```
.\markup.bat check                       # works with no activation, any policy
.venv\Scripts\python.exe -m markup check # if markup.bat is missing
```

On macOS/Linux: `.venv/bin/python -m markup check`.

If `.venv` does not exist, the environment has not been built — run `/setup`.

Never use `markup ...` bare: it needs an activated terminal, and activation is a
PowerShell script that Windows blocks by default.

## What the inputs are

All in `data/input/`, matched by **prefix**, so the ERP's long Thai filenames
work unrenamed.

- **GR2** — goods receipts. The cost source. One row per receipt line. Inbound
  only: there is no issues/consumption ledger. Column Q is the receiving
  warehouse, which drives routing (see below).
- **W10** — the unit master. **One row per SKU *and unit***, not one per SKU,
  with `Ccoefficient` = base units per that unit and `เป็นหน่วยหลัก` = 1 for the
  base unit. W10 is the authority on which units a SKU may be sold in. Its
  *selling* prices are per base unit and often zero — do **not** treat W10 as the
  current selling price source. Its `ราคาซื้อ` (`buy_price`) *is* used as a
  fallback **cost** when a SKU has no usable receipt.
- **markup_list** — one row per SKU: Code, Sale Unit, Selling Price, Category,
  Markup. The current-price source, and the routing key (`Category`).
- **sale_list** — same shape without Category/Markup. Defines scope and selling
  unit. Sale Unit and Selling Price must stay identical between the two files.
- **My Cargo** — optional. Landed import cost (goods + freight) per base unit,
  one row per imported SKU. First sheet, matched by the `My Cargo` prefix.

## Warehouse routing (`config/config.yaml → warehouse_routing`, `docs/COSTING_MODEL.md`)

When `enabled`, each SKU is routed by `markup_list.Category` + Z Smart supplier +
My Cargo membership, then costed first-match: My Cargo landed cost → its home
warehouse (`ST0001` WH/Chilled/Freeze, `ST0002` CK) receipts → the other
head-office warehouse (`COST_FROM_OTHER_WH`) → W10 `buy_price` (`COST_FROM_W10`)
→ `NO_COST`. **Storefront receipts (`ST0003`+) never count.** The rate still
comes from `markup_list`; `MARKUP_RATE_MISMATCH` (soft) flags where it disagrees
with the expected rate. `MYCARGO_UNIT_MISMATCH` (hard) holds a SKU whose My Cargo
unit ≠ its W10 base unit.

## Things that are easy to get wrong

- **Markup is stored as a fraction.** `0.12` means 12%. `markup.value_scale: 100`
  in `config/config.yaml` converts it. At `1`, everything prices at roughly cost
  and the error is silent.
- **Markup is resolved per SKU, not per category.** WH and Central Kitchen each
  carry several rates.
- **Costs are held per base unit internally**, then scaled to the selling unit.
  A GR line whose unit W10 does not list is dropped from costing rather than
  assumed — the SKU shows as uncosted instead of mispriced.
- **FIFO/LIFO are layer-coverage over receipts**, because GR2 has no consumption
  data. FIFO = oldest receipt layers in the period, LIFO = newest, blended up to
  `costing.layer_coverage_pct`. At 100 all three methods converge on weighted
  average. This is documented behaviour, not an approximation to hide.
- **The unit review gate.** A mis-keyed receipt unit is indistinguishable from a
  legitimate parallel unit without product knowledge. Anything questionable sits
  in `config/unit_review.xlsx` with a Decision column and is kept off the price
  upload until decided. Never invent a decision — a wrong unit multiplies or
  divides a real cost.
- **Only ~70% of in-scope SKUs have a receipt in any 90-day window.** Partial
  coverage is normal, not a bug. With warehouse routing on, the rest fall back
  to the W10 standard cost, so ~98% end up priced — the `COST_FROM_W10` count
  is the tell.

## Rules

- **Never edit files in `data/input/` directly.** They are the user's ERP
  exports. Corrections go through `scripts/fix_sale_units.py`, which backs up
  first and writes a change log.
- **Use `update`, never `run`.** Only `update` records history, and that
  recording is what makes the next `/report` comparison possible. `run` takes
  explicit paths and is for scenario testing.
- **Never re-run `update` to "refresh" a report.** That creates a new run and
  changes what is being compared.
- **Never widen the Price Upload sheet.** It is exactly `SKU · Unit · Sale Price`
  so it can be pasted into the ERP. Extra columns belong on Detail.
- Exceptions come in two tiers. **Hard** flags (`NO_COST`, `UNIT_UNVERIFIED`,
  `NEGATIVE_MARGIN`, `BELOW_MIN_MARGIN`, `UNKNOWN_SALE_UNIT`, `MISSING_IN_W10`,
  `UNIT_EXCLUDED`, `MYCARGO_UNIT_MISMATCH`, `PRICE_HELD`) keep the row **off**
  Price Upload — there is nothing safe to send, or a human vetoed it. **Soft**
  flags (a guardrail breach, a new item, a price decrease, a routing cost
  source) stay **on** Price Upload and are only listed for a look; silence ships
  them. A person can veto one soft row by setting `HOLD` in
  `config/price_review.xlsx`. So an upload is safe to hand over, but always say
  what was held back *and* what shipped with a review flag.
- Parameters live in `config/config.yaml`; `INSTRUCTIONS.md` documents every one.
  Flags like `--period` and `--method` override for a single run.

## Layout

```
config/        config.yaml (parameters), column_mapping.yaml (ERP headers),
               unit_review.xlsx (unit decisions — open in Excel, has dropdowns)
data/input/    ERP exports (gitignored)
data/output/   workbooks, reports, run history (gitignored)
src/markup/    the engine — io/ costing/ rules/ pipeline.py validation.py report/
tests/         pytest suite
scripts/       audit_inputs.py, fix_sale_units.py, make_sample_data.py
```

## Testing

`.venv\Scripts\python.exe -m pytest -q` — 54 tests. Run them after any change to
`src/markup/`. Costing, rounding, markup resolution, unit review and the
end-to-end pipeline are all covered.

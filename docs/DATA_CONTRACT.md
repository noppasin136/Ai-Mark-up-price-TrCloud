# Input data contract

What each ERP export must contain. Header *names* are flexible — map them in
`config/column_mapping.yaml`. The columns themselves are not.

## GR2 — goods receipts (cost source)

One row per receipt line. Multiple rows per SKU are expected; that is what makes
FIFO/LIFO/weighted-average meaningful.

| Canonical | Required | Notes |
|---|---|---|
| `sku` | yes | Must match W10 exactly after trimming |
| `receipt_date` | yes | Any parseable date; defines the period window |
| `qty` | yes | Received quantity in the base UOM |
| `unit_cost` | yes | Cost per base unit |
| `freight`, `duty`, `other_landed` | no | Line totals, spread per unit when `cost_basis: landed_cost`. Missing = 0 |
| `warehouse` | for routing | Receiving warehouse (column Q). Needed when `warehouse_routing.enabled` — see `docs/COSTING_MODEL.md` |
| `receipt_no`, `supplier` | no | Carried to the Cost Audit sheet; `supplier` also drives the Z Smart route |
| `product_name`, `uom`, `currency`, `total_cost` | no | Reference only |

Export at least one full period's worth — a 90-day run needs 90 days of receipts.
Mixed currencies are **not** converted; export in one currency.

## W10 — current selling prices

One row per SKU. Duplicates are reduced to the first occurrence with a warning.

| Canonical | Required | Notes |
|---|---|---|
| `sku` | yes | |
| `current_price` | yes | Current base-unit selling price; drives variance and guardrails |
| `uom` | no | Base selling unit |
| `parallel_uom` | no | Secondary unit (BOX, CTN, PACK) |
| `conversion_factor` | no | Base units per parallel unit. Missing or 0 → 1 |
| `parallel_price` | no | Read as the *current* pack price; the engine computes its own |
| `category` | strongly recommended | The markup lookup key |
| `subcategory`, `department`, `brand` | no | Extra levels for the fallback chain |
| `product_name`, `status` | no | Reference only |

Without `category`, every SKU falls through to `markup.default_pct`.

## Markup list

| Canonical | Required | Notes |
|---|---|---|
| `level` | no | `sku` / `subcategory` / `category` / `department`. Defaults to `category` |
| `key` | yes | The value to match at that level |
| `markup_pct` | yes | Number, not text: `25`, not `25%` |
| `basis` | no | Per-row `cost_plus` / `margin` override |
| `min_margin_pct` | no | Per-row margin floor |
| `note` | no | Reference only |

## Sale list (optional)

Restricts the run to specific SKUs and names the unit each one sells in. Without
it, every SKU in W10 is priced.

| Canonical | Required | Notes |
|---|---|---|
| `sku` | yes | |
| `sale_uom` | no | The selling unit shown on the Price Upload sheet |
| `include` | no | `N` / `No` / `False` / `0` excludes the row |

## My Cargo (optional — imports)

Landed cost for imported SKUs, used only when `warehouse_routing.enabled`.
Matched by the `My Cargo` filename prefix; the **first sheet** is read whatever
its name. One row per SKU.

| Canonical | Required | Notes |
|---|---|---|
| `sku` | yes | Matches `markup_list` after trimming |
| `product_cost` | yes | Goods cost **per base unit**, ex-freight. Blank only on manual-price rows |
| `oversea_transport` | for a cost | Overseas freight + import duty per base unit |
| `vat`, `inland_transport` | no | Summed into the cost if ever populated (empty today) |
| `unit` | recommended | Must equal the SKU's W10 base unit, or the SKU is held back |
| `manual_price` | no | A price to hold the SKU at when it carries no cost |
| `product_name` | no | Reference only |

Landed cost = `product_cost + oversea_transport (+ vat + inland_transport)`.

## Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `missing required column` | Header not in the mapping | Add the real spelling to `column_mapping.yaml`; the error prints what it saw |
| Everything on Exceptions as `NO_COST` | Window has no receipts | Lengthen `period_days` or check `as_of_date` |
| Every SKU shows `NO_MARKUP_RULE` | Category values differ between W10 and the markup list | Matching is case-insensitive but not fuzzy — align the codes |
| Prices far too high | `basis: margin` where the list means `cost_plus` | See INSTRUCTIONS.md §3 |
| Few SKUs match between GR2 and W10 | SKU formatting differs (leading zeros, prefixes) | Normalise in the ERP export |

# Costing model — warehouse routing, Central Kitchen, and imports

**Status: design complete 2026-08-30, not yet built.** Every decision is
resolved (§7 / §8); implementation follows the build sequence in §9.
Today's engine costs every receipt line regardless of warehouse, does not read
the My Cargo file, and hard-blocks guardrail breaches from the upload — all of
which changes here.

Read alongside `INSTRUCTIONS.md` (parameters) and `docs/DATA_CONTRACT.md`
(input columns).

**Inputs referenced here:** GR2, W10, `markup_list`, `sale_list` (all present),
and `data/input/My Cargo.xlsx` (uploaded 2026-08-30, §5).

---

## 1. The warehouse dimension

GR2 carries the receiving warehouse on **two** columns:

| Col | Thai header | Meaning |
|---|---|---|
| **Q** | `คลังสินค้า (ตามเอกสาร)` | warehouse on the document header |
| V | `คลังสินค้า (ตามรายการ)` | warehouse on the individual line |

They agree on all but 57 of 47,064 rows. The rule below uses **column Q**, as
requested.

### Codes seen in the current export

| Code | Lines (all dates) | Meaning (per finance) |
|---|---:|---|
| `ST0001` | 1,836 | **Main warehouse** (WH) |
| `ST0002` | 1,898 | **Central Kitchen** (CK) |
| `ST0003`–`ST0031`, `ST-MEGA`, `ST-CPN Khonkaen`, `ST-RD`, `ST-Stationery` | ~43,000 | **Storefronts / branches** — excluded from costing |
| blank | 51 | excluded (no warehouse) |

---

## 2. The intended flow

For each SKU on the price list (`sale_list` / `markup_list`), pick **one** markup
rate and **one** cost source. This section is the plain-English version; **§6 is
the precise, authoritative algorithm** (a two-step first-match).

```
        ┌─ SKU is in the My Cargo file? ──────────► RULE 3  (import)
        │        cost = goods + freight from the file;  markup 25%
        │
        ├─ Z Smart is its majority supplier, OR Category CK / "Central Kitchen"?
        │        ─► RULE 2   cost from its ST0002 receipts;  markup 25%
        │
        └─ otherwise (Category WH / Chilled / Freeze) ─► RULE 1
                 cost from its ST0001 receipts
                 markup 12% WH / 15% Chilled / 20% Freeze
```

All markups are **cost-plus** (`price = cost × (1 + rate)`). If a rule's home
warehouse has no receipts, the cost falls to the other head-office warehouse,
then W10 `buy_price`, then `NO_COST` (§6 step 2). Storefront receipts are never
used.

### Rule 1 — Main warehouse (ST0001)

- **Cost:** weighted average of the SKU's GR2 receipt lines **where column Q =
  `ST0001`**, inside the period window. Storefront lines are never used; if there
  are no `ST0001` lines the cost falls back per §6 step 2 (`ST0002`, then W10).
- **Markup:** by `markup_list` Category —

  | Category | Markup | Basis |
  |---|---|---|
  | `WH` | 12% | cost-plus |
  | `Chilled` | 15% | cost-plus |
  | `Freeze` | 20% | cost-plus |

  Basis is **cost-plus** (`price = cost × (1 + pct/100)`), confirmed by finance
  2026-08-30.

### Rule 2 — Central Kitchen, markup **25% cost-plus** (`cost × 1.25` ≈ 20.0% gross margin — confirmed by finance 2026-08-30)

A SKU is priced as Central Kitchen when **either**:

- its `markup_list` Category is `CK` / `Central Kitchen`, **or**
- GR2 shows it was **bought from Z Smart Trading** (`บริษัท แซด สมาร์ท เทรดดิ้ง
  จำกัด`) — regardless of its Category. A `WH` Category on a Z Smart item only
  means it is *sold from* the warehouse; Z Smart is the Central Kitchen supply
  channel, so it is costed and marked up as Central Kitchen.

Then:

- **2.1 — bought in.** Cost = weighted average of the SKU's `ST0002` receipt
  lines. Markup 25% cost-plus.
- **2.2 — no `ST0002` receipt.** Cost falls back per §6 step 2 — its `ST0001`
  lines if any, else the **standard cost in W10** (`ราคาซื้อ` → `buy_price`, per
  base unit). Markup still 25% cost-plus. (Covers in-house semi-products and
  items last received before the GR2 export's date range.)

### Rule 3 — Imports via My Cargo, markup **25% cost-plus on landed cost**

- SKU appears in the **My Cargo** workbook (`data/input/My Cargo.xlsx`, uploaded
  2026-08-30 — see §5 for the layout). Supplier in GR2 is `บริษัท มาย มาย
  คาร์โก้ จำกัด`. The file is the authority — a SKU is a My Cargo import iff it
  has a row here.
- **Landed cost = `ราคา-หน่วยหลัก` + `Oversea Transport+Import duty`**, already
  per base unit. (`VAT(CARGO)` and `Inland Transport` columns are ignored —
  §8.H.)
- **Price = landed cost × 1.25** (confirmed by finance 2026-08-30 — *always*
  25% for My Cargo, on the full goods + freight figure). This is the same 25%
  already in `markup_list` for these SKUs; **only the cost basis changes** —
  from GR2 goods-only to landed. No markup-list edit needed.
- Any GR2 lines for the same SKU are **excluded** from costing — GR2 for these
  SKUs holds only the goods cost, not the freight (§4.14).
- **`504-0055`, `504-0057`, `903-0460`** are My Cargo imports too but not in the
  current file (last imported long ago). Cost falls back to W10 `buy_price`,
  markup 25% — same as Rule 3.
- **`701-0039`, `702-0052`** carry a `Sale Price` and no cost. Leave the SKU at
  its **current price** — do not re-mark-up.

---

## 3. Assumptions this depends on

| # | Assumption | Evidence in the current export |
|---|---|---|
| A1 | The receiving warehouse (col Q) tells us how a SKU is sold and priced. | ST0001 = 674 window lines, ST0002 = 597, storefronts = 680 for in-scope SKUs. |
| A2 | `markup_list.Category` is the routing key, **not** col Q directly — because col Q is per-line and one SKU has receipts in several warehouses. | 150 in-scope SKUs have ≥1 ST0001 line **and** other-warehouse lines in the same window. |
| A3 | `WH` / `Chilled` / `Freeze` ⇒ main warehouse; `CK` / `Central Kitchen` ⇒ Central Kitchen. | Dominant warehouse per category: WH→ST0001 (96 SKUs), CK→ST0002 (12), Central Kitchen→ST0002 (29). |
| A4 | Storefront receipts are not representative of purchase cost and are dropped. | Removing them strands only **5** more in-scope SKUs as uncosted. |
| A5 | Z Smart Trading purchases are the Central Kitchen inbound channel. | 973 of 975 Z Smart lines land in `ST0002`. |
| A6 | W10 `buy_price` is a maintained standard cost, usable when there is no receipt. | Populated (> 0) for 299 of 302 in-scope SKUs; 77 of the 80 never-received SKUs have it. |
| A7 | My Cargo = `บริษัท มาย มาย คาร์โก้ จำกัด`, an import consolidator; the uploaded file is the authority on which SKUs are imports. | File has 77 rows, 45 on the price list (44 `WH`, 1 `CK`); its GR2 lines carry goods cost only, no freight. |
| A8 | One national price per SKU — a branch that pays more does not get its own price. | consequence of A4. |

---

## 4. Errors, gaps and contradictions — how each was resolved

### 4.1 "Warehouse" is a line attribute, not a SKU attribute — RESOLVED
The same SKU is received into ST0001, ST0002 and storefronts in one period, so
"which warehouse owns the SKU" is not in the data. Resolved: route on
`markup_list.Category` (A2/A3); column Q only decides *which lines to average*.

### 4.2 Two different "category" columns
GR2 has its own group column (`กลุ่มสินค้า`: `NAL-Soft Drink`, `FFR-Food
Frozen`, …). That is **not** the `markup_list` Category (`WH`, `CK`, `Freeze`,
…). The routing rule uses the **markup_list** Category. Do not join on the GR2
one.

### 4.3 The 25% on `WH` SKUs — mostly correct, it is the *cost* that was wrong
`markup_list` Markup values by Category today:

| Category | 0.12 | 0.15 | 0.20 | 0.25 |
|---|---:|---:|---:|---:|
| WH | 130 | – | 3 | **48** |
| Chilled | – | 9 | – | – |
| Freeze | – | – | 39 | – |
| CK | – | – | – | 18 |
| Central Kitchen | **1** | – | – | 54 |

The **48 `WH` SKUs keyed at 25%** break down as:

| Group | Count | Verdict |
|---|---:|---|
| **In the My Cargo file** | 44 | 25% is **right** — it is cost-plus on the *landed* cost. Rule 3. The bug was never the rate; it was that GR2 (and so the engine) only had the goods cost, not the freight (§4.14). |
| **My Cargo imports not in the current file** | 3 | `504-0055`, `504-0057`, `903-0460` — keep 25%, cost from W10 `buy_price` (Rule 3 fallback). |
| **Bought from Z Smart** | 1 | `502-0013` tomato-sauce gallon — 25% via Rule 2 (Central Kitchen). |

**Corrections confirmed 2026-08-30 (apply to `markup_list` via the correction
process, backing up first):**

- `702-0026`, `602-0010`, `704-0014` — re-tag Category `WH` → **`Freeze`**
  (rate becomes 20%).
- `502-0007` น้ำมันชา — Central Kitchen, rate `0.12` → **`0.25`**.

### 4.4 Central Kitchen SKUs not bought from Z Smart — RESOLVED
Rule 2 covers **any** SKU whose Category is `CK` / `Central Kitchen`, costed from
its ST0002 GR2 lines regardless of supplier, at 25% cost-plus. Z Smart is the
*common* channel, not the only one. (~27 of 55 Central Kitchen SKUs are bought
elsewhere and are handled the same way.)

### 4.5 "No receipt" ≠ "semi-product" — RESOLVED
80 in-scope SKUs never appear in GR2 (46 `WH`, 21 `Central Kitchen`, 6 `Freeze`,
6 `CK`, 1 `Chilled`). Per finance these are **not all in-house semi-products** —
most were simply last received before the GR2 export's date range
(2026-05-01 →), or are being sold from existing inventory. Treatment is the same
either way: **cost from W10 `buy_price` (per base unit), markup at the SKU's
category / rule rate**, flagged `COST_FROM_W10`. Applies to every category, not
just Central Kitchen. 77 of the 80 have a usable W10 `buy_price`.

### 4.6 Z Smart purchase overrides Category for markup — RESOLVED
Of 56 in-scope Z Smart SKUs, 14 are Category `WH`. Per finance: **if GR2 says the
SKU was bought from Z Smart Trading, it is priced as Central Kitchen (25%
cost-plus)** — the `WH` Category only records that it is *sold from* the
warehouse. So the markup signal is: `Z Smart supplier  OR  Category ∈ {CK,
Central Kitchen}` → 25%. Category alone decides the rate only for non-Z-Smart
items.

### 4.7 Category ↔ warehouse mismatch — RESOLVED: no review gate
Some SKUs carry a Category that disagrees with where they are actually received
(14 `WH`/`Freeze`/`Chilled` received only into `ST0002` — 12 of them Z Smart;
3 `Central Kitchen` received only into `ST0001`). Finance decided **not** to gate
these. Category always sets the rate. Cost comes from the SKU's real receipt
lines: its Category's home warehouse first, then the other head-office warehouse,
then W10 `buy_price` (§8.D, §6 step 2).

### 4.8 My Cargo GR2 lines hold goods cost only — RESOLVED: file replaces GR2
My Cargo SKUs have GR2 receipt lines into ST0001, but comparing them to the
uploaded file shows GR2 `unit_cost` ≈ `ราคา-หน่วยหลัก` (goods only) with **no
freight**. Freight is +30–95% on top for most lines. So for a My Cargo SKU the
engine **uses the file and ignores the GR2 lines** (Rule 3). The file has 77
rows / 45 on the price list — a superset of the 34 seen via the GR2 supplier
name, so the file itself is the authority on what is "a My Cargo import".

### 4.9 Markup basis — RESOLVED: cost-plus
Finance confirmed (2026-08-30) that "25%" means **cost-plus**: `price = cost ×
1.25`, giving a 20.0% gross margin. All rules (1, 2, 3) use cost-plus. This
matches the engine's current `markup.basis: cost_plus` and the markup-list
values, so no config change is needed on this point.

### 4.10 W10 `buy_price` as a fallback cost — RESOLVED
`CLAUDE.md` / `docs/DATA_CONTRACT.md` warn *"do not treat W10 as the current
price source."* The fallback here uses a **different** column — `ราคาซื้อ` /
`buy_price`, the standard *cost*, not the selling price — populated for 299 of
302 in-scope SKUs. Confirmed: it is per **base unit**, it is **maintained by the
Purchasing department**, and it is used **only** when a SKU has no usable
receipt / My Cargo row. When the routing is built, the docs' W10 warning should
be narrowed to "not as a *selling* price".

### 4.11 The period cannot be lengthened much
GR2 in this export only spans **2026-05-01 → 2026-08-29** (~4 months). A 90-day
window already captures almost all of it, so lengthening `period_days` will not
rescue the 12 "stale" SKUs. If more history matters, export a longer GR2.

### 4.12 Storefront exclusion — RESOLVED: exclude
Confirmed 2026-08-30: receipts into any warehouse other than `ST0001` /
`ST0002` are **not used for costing**. Costing runs on head-office cost only,
for one national price per SKU. This drops ~680 of ~1,950 in-scope window
receipt lines; a SKU received only into storefronts falls to the W10 `buy_price`
fallback, then `NO_COST`.

### 4.13 My Cargo `unit` label vs the W10 base unit — RESOLVED
`503-0071` (ซอสบะหมี่เย็น) is written as `bag` in the My Cargo file but should be
`pack` — finance confirmed 2026-08-30. The cost figure (28.30 + 27.32 = 55.62)
is already **per pack**, so it needs **no scaling** — only the label is wrong.
Fix the label in `data/input/My Cargo.xlsx` at source; the number stands. Every
other My Cargo `unit` already matches its W10 base unit.

### 4.14 Imports are under-priced today — Rule 3 fixes a real error
For My Cargo SKUs the engine currently costs from GR2 (goods only) and adds 25%.
Freight is 30–95% of goods cost and never reaches GR2, so the *suggested* price
is far below the real selling price — e.g. `501-0010` วุ้นเส้นจีน:
GR2 cost 34.60 → suggests 34.60 × 1.25 ≈ **43**, against a real price of
**85.75**. The last `/update` run flagged this SKU `OVER_MAX_DECREASE` (−50%)
and held it back — correctly. Rule 3 costs it at (34.60 + 33.02) × 1.25 ≈
**85**, on top of the real 85.75 — the flag disappears. The markup rate (25%)
was fine all along; the fix is the **cost basis**, not the rate. Several import
SKUs on the current Exceptions sheet are the same story.

---

## 5. My Cargo file — as uploaded

`data/input/My Cargo.xlsx`, sheet **`Seb26`**, header on row 1, **77 rows**.

| Col | Header | Canonical | Notes |
|---|---|---|---|
| A | `code` | `sku` | matches `markup_list.Code`; 45 of 77 are on the price list |
| B | `name` | `product_name` | reference |
| C | `unit` | `unit` | the unit the costs are quoted in — **treated as the base unit** (see §4.13) |
| D | `ราคา-หน่วยหลัก` | `product_cost` | goods cost **per base unit**, ex-freight. Blank on 2 rows |
| E | `VAT(CARGO)` | — | **ignored** (never populated — §8.H) |
| F | `Oversea Transport+Import duty (Optional)` | `oversea_transport` | freight + import duty per base unit. Blank on the same 2 rows |
| G | `Inland Transport (เฉลี่ย)` | — | **ignored** (never populated — §8.H) |
| H | `Sale Price` | `manual_price` | filled on **only 2 rows** (`701-0039`, `702-0052`) — a manual price, used when D/F are blank |

**Landed cost = `ราคา-หน่วยหลัก` + `Oversea Transport+Import duty`** (D + F).
Already per base unit, so **no coefficient scaling** — scaled straight to the
selling unit like any base-unit cost.

Loader rules (§8.F, §8.G): read the **first sheet** (the tab name changes each
upload); match the file by the **`My Cargo` filename prefix**; expect **one row
per SKU** (duplicate = error); on each SKU compare `unit` to the W10 base unit
and raise `MYCARGO_UNIT_MISMATCH` on a mismatch. A new upload fully replaces the
previous file.

---

## 6. Recommended routing model (concrete)

First match wins. `Category` = `markup_list.Category`. "Z Smart" / "My Cargo" =
GR2 supplier name contains that firm.

**Step 1 — pick the markup rate.** First match wins:

| | SKU is… | Rate (cost-plus) |
|---|---|---|
| a | in the My Cargo file | **25%** |
| b | Z Smart is its **majority** supplier this window (§8.B) | **25%** |
| c | Category ∈ {CK, Central Kitchen} | **25%** |
| d | Category `WH` / `Chilled` / `Freeze` | **12 / 15 / 20%** |

The rate is read from the `markup_list` **Markup column**; the table above is the
*expected* value — a disagreement raises `MARKUP_RATE_MISMATCH` (§8.A), which
does not block the upload.

**Step 2 — pick the cost.** First match wins:

| | Condition | Cost source | Flag |
|---|---|---|---|
| 1 | in My Cargo, has a cost | `ราคา-หน่วยหลัก + Oversea Transport+Import duty` | `COST_FROM_MYCARGO` |
| 1b | in My Cargo, `Sale Price` only (`701-0039`, `702-0052`) | keep current price, no re-mark-up | `MANUAL_PRICE` |
| 2 | has receipts in its Category's **home warehouse** (`ST0002` for rate a/b/c, `ST0001` for d) this window | weighted avg of those lines | — |
| 3 | has receipts in the **other** head-office warehouse | weighted avg of those lines | `COST_FROM_OTHER_WH` |
| 4 | has a W10 `buy_price` | W10 `buy_price` (base unit) | `COST_FROM_W10` |
| 5 | none of the above | — | `NO_COST` (held back) |

Notes:

- **Storefront lines (`ST0003`+, `ST-MEGA`, …) are never used for costing** — a
  SKU received only into storefronts skips to step 3, then 4, then 5.
- My Cargo membership beats everything: a My Cargo SKU that is also Z Smart / CK
  is still costed from the file. (Only `101-0083` today — rate 25% either way.)
- No category↔warehouse review gate (§8.D). A `Freeze` SKU received only into
  `ST0002` is costed from those `ST0002` lines at the `Freeze` rate; a CK SKU
  received only into `ST0001` is costed from those `ST0001` lines at 25%.

### What this would change vs. today (rough, on the current export)

- **~44 My Cargo import SKUs re-cost with freight included.** The markup stays
  25% but now sits on the landed cost, so their suggested price rises to near
  the real selling price. Several are on today's Exceptions sheet as big price
  *drops* (`501-0010` −50%, `501-0011`, `901-0081`, …) — those flags disappear
  because the drop was only ever the missing freight (§4.14).
- **~75 SKUs move off `NO_COST`** — priced from the My Cargo file (~30) or from
  W10 `buy_price` (~45, step-2 row 4).
- ~3–5 SKUs become `NO_COST` (storefront-only receipts and no W10 cost).
- Central Kitchen SKUs re-price at a flat 25% cost-plus instead of the current
  12–25% mix; the 25% now sits on an ST0002-only weighted average.
- ST0001 SKUs cost slightly differently — storefront receipt lines drop out of
  their weighted average.
- **Guardrail behaviour changes (§8.C):** SKUs over the ±% limit stay **on** the
  Price Upload and are listed for review instead of being removed. The current
  ~124 held-back count drops to just the hard blocks (`NO_COST`,
  `UNIT_UNVERIFIED`, …).

---

## 7. Decisions checklist

**Resolved 2026-08-30:**

- §4.4 — all CK / Central Kitchen at 25% cost-plus, any supplier.
- §4.5 — no-receipt SKUs → W10 `buy_price`, all categories.
- §4.6 — Z Smart purchase → 25%; Category is sale-location only.
- §4.9 — basis = cost-plus.
- §4.13 — `503-0071` is per `pack`; cost stands, fix the label in the file.
- **Rule 3** — My Cargo is **always `(goods + freight) × 1.25`** (25% cost-plus
  on landed cost). The list's 25% stays; only the cost basis changes.
- `504-0055`, `504-0057`, `903-0460` — My Cargo imports last shipped long ago;
  keep 25%, cost from W10 `buy_price`.
- `701-0039`, `702-0052` — hold at current price (Sale Price only, no cost).
- §4.3 — re-tag `702-0026`, `602-0010`, `704-0014` as `Freeze` (→ 20%); set
  `502-0007` to 25%. Apply via the `markup_list` correction process.
- §4.7 / §8.D — **no** category↔warehouse review gate; category sets the rate,
  cost comes from the SKU's real receipt lines (home WH → other WH → W10).
- §4.10 — W10 `buy_price` is maintained by the **Purchasing department**.
- §4.12 — storefront receipts (not `ST0001` / `ST0002`) are **excluded** from
  costing.
- §8.A — `markup_list.Markup` stays the source of truth; the model audits it
  (`MARKUP_RATE_MISMATCH`).
- §8.B — Z Smart routes to 25% only when it is the **majority** supplier.
- §8.C — guardrail breaches become a **soft** review list, not a hard block;
  silence ships the price.
- §8.E — no receipt and no W10 `buy_price` → `NO_COST` (hard block).
- §8.F — My Cargo `unit` ≠ W10 base unit → `MYCARGO_UNIT_MISMATCH` (hard block).
- §8.G — loader reads the first sheet, matches the `My Cargo` filename prefix,
  one row per SKU; a new upload replaces the old file.
- §8.H — `VAT(CARGO)` / `Inland Transport` ignored; landed cost = D + F only;
  file is a live standard cost, no ageing.

**Every design decision is now settled.** Nothing outstanding — the doc is a
complete spec.

**Next step — implement in `src/markup/`:**

| Piece | Detail |
|---|---|
| My Cargo loader | new `column_mapping.yaml` block (`my_cargo`); first sheet; `My Cargo` prefix; one row per SKU |
| Warehouse-aware costing | §6 two-step: rate (a→d), then cost (1→5); storefront lines dropped |
| Soft flags (on Exceptions, do **not** block upload) | `COST_FROM_MYCARGO`, `COST_FROM_OTHER_WH`, `COST_FROM_W10`, `MANUAL_PRICE`, `MARKUP_RATE_MISMATCH`, `OVER_MAX_INCREASE`, `OVER_MAX_DECREASE` |
| Hard blocks (kept off upload) | `NO_COST`, `UNIT_UNVERIFIED`, `NEGATIVE_MARGIN`, `UNKNOWN_SALE_UNIT`, `MYCARGO_UNIT_MISMATCH` |
| Soft-guardrail behaviour | rework `apply_guardrails`; update the "upload is always safe" wording in `CLAUDE.md` and `INSTRUCTIONS.md §6` |
| `markup_list` corrections | via `scripts/fix_sale_units.py` (extend it) or a new backed-up script: `702-0026`/`602-0010`/`704-0014` → `Freeze`; `502-0007` → `0.25` |
| Tests | one per rate branch, one per cost branch, soft vs hard flag routing, My Cargo loader |

---

## 8. Follow-up questions — all resolved

### A. Where the markup *rate* lives — RESOLVED: A2 + audit
The `markup_list` **Markup column stays the source of truth** so it can be
exported straight to the ERP. The engine additionally computes the *expected*
rate from Category + Z Smart + My Cargo and, where the column disagrees, raises
a **`MARKUP_RATE_MISMATCH`** review item (does not block the upload). Keeps the
list self-contained while catching drift.

### B. "Bought from Z Smart" — RESOLVED: B2 (majority)
A SKU is priced as Central Kitchen via Z Smart only when **Z Smart is the
majority of its receipts** (by received quantity) in the window. Rare or
small one-off Z Smart purchases are ignored — the SKU keeps its Category rule.
Confirmed on the data: the 12 in-scope SKUs this affects are 100% Z Smart, so
the threshold is not borderline for any of them today.

### C. Guardrails — RESOLVED: soft gate, silence = ship
Change from today's behaviour: a SKU that breaches `max_increase_pct` /
`max_decrease_pct` is **no longer held off the Price Upload**. It goes onto the
upload **and** onto a review list (Exceptions), with its old and new price and
the % move. The user reviews the list; **a row with no comment ships as-is**. A
comment / objection on a row is what holds that one row back. This applies to
`OVER_MAX_INCREASE` / `OVER_MAX_DECREASE` and to `MARKUP_RATE_MISMATCH`.
**Hard blocks stay hard:** `NO_COST`, `UNIT_UNVERIFIED`, `NEGATIVE_MARGIN`,
`UNKNOWN_SALE_UNIT` never reach the upload — you cannot ship a price you do not
have.

### D. Category ↔ warehouse edge cases — RESOLVED: cost from real lines
Checked on the data:

- **14** `WH`/`Freeze`/`Chilled` SKUs are received only into `ST0002` in the
  window. **12** are Z Smart-majority → Central Kitchen, 25%, via Rule B.
- The other **2** — `504-0032` หอยเชลล์อบแห้ง, `701-0015` วัวเอ็นแก้ว (both
  `Freeze`, normal food wholesalers, **no `ST0001` receipt ever**, not in My
  Cargo) → keep the `Freeze` rate (20%), **cost from their real `ST0002`
  lines**.
- Mirror case: **3** `Central Kitchen` SKUs (`201-0170`, `201-0171`,
  `502-0006`) are received only into `ST0001` → keep the CK rate (25%), **cost
  from their real `ST0001` lines**.

General rule (replaces the "jump straight to W10" in §6): **the rate always
comes from Category (+ Z Smart / My Cargo). The cost comes from the SKU's real
receipt lines — preferring the Category's home warehouse, then the other
head-office warehouse, then W10 `buy_price`, then `NO_COST`.** Storefront lines
never count.

### E. No W10 `buy_price` and no receipt — RESOLVED: `NO_COST`
The 3 SKUs with no receipt and no W10 `buy_price` stay `NO_COST` and off the
Price Upload — there is nothing to price them from. (Hard block.)

### F. My Cargo `unit` check — RESOLVED: flag it
On load, compare each My Cargo `unit` to the SKU's W10 base unit. A mismatch
(like `503-0071`) raises a **`MYCARGO_UNIT_MISMATCH`** review item and that SKU
is **held back** (hard block) until the file is fixed — a wrong unit silently
multiplies or divides the landed cost.

### G. My Cargo file conventions — RESOLVED
- **Filename** always begins `My Cargo` — matched by prefix like the other
  inputs.
- **Sheet** tab is renamed each upload (`Seb26` → next period's name) — the
  loader **always reads the first sheet**, never a fixed name.
- **One row per SKU.** No per-shipment rows to average; a duplicate SKU is a
  data error → flag it.

### H. My Cargo file upkeep — RESOLVED
- `VAT(CARGO)` and `Inland Transport` will **not** be populated — they stay in
  the sheet but the engine ignores them. **Landed cost = `ราคา-หน่วยหลัก` +
  `Oversea Transport+Import duty`** only.
- The file is a **live standard cost** — every row is current, no ageing, no
  date column needed. A new upload fully replaces the previous one.

---

## 9. Build sequence

Land this as a series of small PRs, each keeping `pytest -q` green and adding its
own cases. Do **not** bundle — incremental commits are the handoff.

| PR | Scope | Depends on | Doc |
|---|---|---|---|
| **1** ✅ | **Flag tiering + soft guardrail.** `FLAG_CATALOG` now records a `hard` / `soft` tier. Hard flags (`NO_COST`, `UNIT_UNVERIFIED`, `NEGATIVE_MARGIN`, `BELOW_MIN_MARGIN`, `MISSING_IN_W10`, `UNIT_EXCLUDED`, `UNKNOWN_SALE_UNIT`) keep the row off Price Upload as before; soft flags (`OVER_MAX_INCREASE` / `OVER_MAX_DECREASE`, `PRICE_DECREASE`, `NO_CURRENT_PRICE`, …) ship on the upload and are listed on Exceptions. New stat `SKUs on upload flagged for review`; Exceptions sheet carries `blocked`. `CLAUDE.md` / `INSTRUCTIONS.md §6` updated. | — | §8.C |
| **1b** | **Per-row objection** (optional, later). A `config/price_review.xlsx` round-trip like `unit_review.xlsx`: a soft-flagged row gets held back only if a human writes an objection against it; silence ships. Skip unless finance wants the override. | 1 | §8.C |
| **2** ✅ | **`markup_list` corrections** via `scripts/fix_markup_list.py` (backs up to `data/input/archive/`, logs to `data/output/`, idempotent). `702-0026` / `602-0010` / `704-0014` Category → `Freeze` (latent until PR 4 — the engine ignores `markup_list.Category` today); `502-0007` Markup `0.12` → `0.25` (took effect: was about to mis-price at −10%). | — | §4.3 |
| **3** ✅ | **My Cargo loader.** `my_cargo` block in `column_mapping.yaml`; `load_my_cargo()` reads the first sheet, matched by the `My Cargo` prefix, one row per SKU (dupes/unusable rows dropped with a warning); `landed_cost` = product + oversea (+ vat/inland if ever filled); `has_landed_cost` / `has_manual_price` flags. `mycargo_unit_issues()` compares `unit` to the W10 base unit. `MYCARGO_UNIT_MISMATCH` (hard) added to the flag catalog. `/check` reports the file and any unit mismatch. No pricing change — `run()` does not read it yet. Sample: `make_sample_data.py` now emits `My_Cargo_sample.xlsx`. | — | §5, §8.F/G |
| **4** | **Warehouse-aware costing.** The §6 two-step: rate (a→d) then cost (1→5). Storefront lines dropped from costing. New flags `COST_FROM_MYCARGO` / `COST_FROM_OTHER_WH` / `COST_FROM_W10` / `MANUAL_PRICE` / `MARKUP_RATE_MISMATCH` (all soft). | 1, 3 | §6 |
| **5** | **Doc wording.** Narrow the "upload is always safe to hand over" line in `CLAUDE.md` and `INSTRUCTIONS.md §6` to reflect soft vs hard. Do the relevant part with PR 1, the rest with PR 4. | 1, 4 | — |

Each PR references its `COSTING_MODEL.md` section in the commit message.

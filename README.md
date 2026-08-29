# Markup Pricing Engine

Turns your ERP's goods-receipt costs into suggested selling prices and writes an
Excel workbook the ERP can import.

**You drive it by talking to Claude in a terminal.** Open the folder, type a
slash command, and Claude runs the work, reads the output and explains it.

```
/markup     run the whole monthly workflow
/check      are the ERP exports present and readable?
/review     units needing your decision
/update     price everything, write the workbook
/report     summary, category rollup, diff vs last month
/audit      full data-quality report on the exports
/setup      build or repair the environment
```

Typical month:

```
/markup
```

That is it. Claude checks the files, stops if a unit needs your decision,
prices everything, and tells you what moved and what was held back.

---

## First time — three steps

**1. Install Claude Code** (PowerShell, no admin needed):

```powershell
irm https://claude.ai/install.ps1 | iex
```

Then open a **new** terminal and confirm: `claude --version`.

**2. Open this folder and start Claude:**

```powershell
cd "C:\Ai Mark up price"
claude
```

**3. Type `/setup`.** Claude builds the Python environment, installs the
dependencies and runs the tests. A few minutes the first time.

Then `/check` to confirm your ERP exports parse, and you are working.

Full walkthrough, including the Windows snags: [docs/SETUP.md](docs/SETUP.md).

---

## The four steps

Always this order. `/markup` does all of it; the individual commands are there
when you want one piece.

| Step | What it answers |
|---|---|
| **check** | Are the exports present, and do the columns map? |
| **review** | Does any SKU's selling unit disagree with the unit it was received in? |
| **update** | What should each price be? |
| **report** | What changed, and where is the margin? |

**Why `review` exists.** Cost is recorded per unit *received*; price is
published per unit *sold*. When those differ the engine converts using W10's
coefficient — but a mis-keyed receipt unit looks exactly like a legitimate
parallel unit, and only someone who knows the product can tell them apart. Those
SKUs wait in `config/unit_review.xlsx` until you decide, and never reach the
upload sheet before then.

---

## Inputs

Drop the ERP exports into `data/input/`. Files are matched by **prefix**, so the
long names your ERP produces work unrenamed.

| File | What it provides |
|---|---|
| `GR2*` | Goods receipts — the cost source |
| `W10*` | Every sellable unit per SKU, with conversion coefficients |
| `markup_list*` | Markup and current price per SKU |
| `sale_list*` | Which SKUs to price and in which unit (optional) |

Nothing in `data/` is committed to git.

## Output

| Sheet | Contents |
|---|---|
| **Price Upload** | `SKU · Unit · Sale Price` — paste straight into the ERP |
| Detail | Every column behind each price |
| Exceptions | Rows needing a human, each with a plain-language reason |
| Cost Audit | The GR2 lines each cost was built from |
| Run Summary | The exact parameters that produced the file |

Rows that trip a guardrail never reach Price Upload, so an upload is always safe
to hand over.

---

## Changing how it prices

Everything tunable is in [`config/config.yaml`](config/config.yaml) — period,
costing method, markup basis, rounding, guardrails.
[INSTRUCTIONS.md](INSTRUCTIONS.md) explains every parameter.

You can also just say what you want:

> price it on a 30-day window using FIFO

> the rounding should go up to the nearest 5 baht

Claude edits the config or passes the flag, and tells you which it changed.

---

## Without Claude

The engine is a normal Python package; Claude is a convenience, not a
dependency. Every command works from a terminal:

```powershell
.\markup.bat check
.\markup.bat review
.\markup.bat update --period 30 --method fifo
.\markup.bat report
```

`markup.bat` calls the project's own Python, so it needs no activation and is
unaffected by PowerShell's execution policy.

---

## Project layout

```
CLAUDE.md          what Claude reads at the start of every session
.claude/skills/    the slash commands
config/            config.yaml, column_mapping.yaml, unit_review.xlsx
data/input/        ERP exports go here
data/output/       workbooks, reports, run history
src/markup/        the engine
tests/             54 tests
scripts/           audit and repair tools
```

A new costing method is one class with a `@register("name")` decorator; a new
rounding rule is one function with `@strategy("name")`. Both become valid
`config.yaml` values immediately. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Notes on FIFO / LIFO

GR2 records what came **in**, never what went **out**, so there is no
consumption ledger to consume layers against. Here FIFO means *"cost from the
oldest receipt layers in the period"* and LIFO *"from the newest"*, with
`costing.layer_coverage_pct` controlling the blend. Documented behaviour, not a
hidden approximation — [INSTRUCTIONS.md](INSTRUCTIONS.md#2-costing-method).

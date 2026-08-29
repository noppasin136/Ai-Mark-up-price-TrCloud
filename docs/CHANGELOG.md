# Changelog

## 0.4.0 — Claude Code as the interface

The project is now driven by slash commands in a terminal. The CLI still works
unchanged underneath; Claude is a front door, not a dependency.

- `.claude/skills/` provides `/markup`, `/check`, `/review`, `/update`,
  `/report`, `/audit` and `/setup`. They are committed, so anyone who clones the
  repository gets the same commands.
- `CLAUDE.md` gives every session the domain context: what GR2 and W10 are, that
  W10 holds one row per SKU *and unit*, that markup is stored as a fraction,
  that costs are held per base unit, and the rules that must not be broken.
- `.claude/settings.json` pre-approves the runner commands so the flow does not
  prompt at every step, and denies edits to `data/input/` so the user's ERP
  exports can only be changed through the backed-up repair script.
- README rewritten around the commands; `docs/VSCODE_SETUP.md` renamed to
  `docs/SETUP.md` and reordered to lead with Claude Code.

## 0.3.1

- VS Code workspace: tasks, F5 debug entries, recommended extensions, and
  interpreter/analysis settings for the src layout
- `setup.ps1` builds the environment and self-verifies; `setup.bat` and
  `markup.bat` wrap it for machines where PowerShell script execution is blocked
- Tasks and debug entries call the environment's Python directly, so they work
  regardless of the execution policy
- Fixed: setup used the `py -3` launcher to create the virtual environment, but
  some installations do not forward its arguments and Python received `-3`
  itself. Setup now asks the interpreter for its own absolute path and uses that
- `.gitattributes` keeps `.ps1` and `.bat` files as CRLF
- Fixed: `.gitignore` excluded `.vscode/`, so none of the workspace setup would
  have reached a clone

## 0.3.0 — unit review

Cost is recorded per unit received and price is published per unit sold. Where
those differ, a conversion is needed — and a mis-keyed receipt unit is
indistinguishable from a legitimate parallel unit without human knowledge. This
release adds the gate.

- `markup review` and `config/unit_review.xlsx`: flagged SKUs with the evidence
  and a Decision column (PENDING / ACCEPT / TREAT_AS / EXCLUDE). Decisions
  persist across runs and double as the audit trail.
- `TREAT_AS` re-reads a SKU's receipts under a corrected unit before any
  coefficient is applied — the ถุงร้อน case, bought by the pack, keyed as bag.
- Unreviewed conflicts carry `UNIT_UNVERIFIED`, land on Exceptions and never
  reach Price Upload; the run still completes for everything else.
- W10 is now read as a full unit table (one row per SKU *and* unit). Costs are
  held per base unit internally and scaled to the unit being priced. Parallel
  prices are derived from that table rather than from columns.
- Base unit selected on the `เป็นหน่วยหลัก` flag rather than row order.
- `markup.value_scale` converts a markup list stored as fractions into percent.
- Input files matched by prefix, so long ERP export names work unrenamed.
- Loader recovers the literal text `null` that the ERP writes into numeric
  cells, instead of dying mid-parse.
- Header matching is Unicode-aware — the previous rule erased Thai headers
  entirely and collapsed them all to the same empty string.
- Sale list wins over W10 on current price; W10 prices are per base unit and
  frequently zero, which was corrupting every variance and guardrail.
- Missing configured sheet falls back to the first sheet, with a warning.

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

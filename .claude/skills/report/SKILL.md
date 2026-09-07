---
name: report
description: Summarise the latest pricing run, compare it against the previous one, and roll margins up by product category. Use when the user says /report, "how did the run go", "what changed since last month", "show me margins by category", or asks about exceptions from a run.
argument-hint: "[optional: --against <run_id>] [--group-by category|department|brand]"
allowed-tools: Bash(./markup.bat *) Bash(markup.bat *) Bash(.venv/Scripts/python.exe *) Bash(.venv/bin/python *) Bash(python -m markup *) Read Glob Grep
---

# Pricing report

Read-only. Explains the most recent run: how it went, how it differs from the
one before, and where the margin sits by product group.

```
.\markup.bat report                            # latest vs the run before it
.\markup.bat report --against <run_id>         # vs a specific run
.\markup.bat report --group-by department      # roll up by something else
.\markup.bat report --top 50                   # more movers
.\markup.bat runs                              # list recorded run ids
```

Output is a single self-contained HTML page, open in any browser. No Excel
workbook is produced. Two copies are written to `data/output/`:

- `Pricing report - <D Mon YYYY>.html` — dated by the run's pricing date
- `Report - latest.html` — a fixed-name copy of the newest report

The page opens with two **director-facing dashboard sections** — "This pricing
round at a glance" (stat tiles, a plain-English verdict, what is held for a
decision, where each cost came from) and "Margin & movement by category" (a
per-category margin bar chart and the margin spread of the whole book) — then a
"Full detail" heading and the analyst tables. All averages are unweighted
per-SKU means; the data carries no sales volume. Give the user the dated path in
the report-back.

If it reports no run history, `/update` has not been run yet — say so and offer
to run it.

## What to cover

**The last run** — costing method, period, SKUs priced, SKUs held back, average
margin, biggest movers, exception counts by flag.

**Versus the previous run** — how many prices changed, how many are new or
dropped, the average and extreme moves. Name both runs *including their method
and period*: a difference caused by a parameter change is a completely different
story from one caused by cost movement, and conflating them misleads.

**By category** — margin and average change per product group, so the user can
see which groups carry the movement.

## Interpret, don't transcribe

The HTML page already holds the tables; the value here is the reading. Call out:

- a category whose average margin sits below the others, or below the floor;
- movement concentrated in one group rather than spread across the catalogue;
- a comparison where the two runs used different parameters — state that plainly
  rather than presenting it as a cost trend;
- any SKU whose price moved far more than its cost did, which usually means a
  markup rule changed or a rounding band applies.

## Notes

- Never re-run `update` to "refresh" the data — that creates a new run and
  changes what is being compared. If the user wants fresh numbers, that is
  `/update`.
- Scenario runs made with `run` are deliberately not recorded, so they never
  appear in comparisons.
- Check the run being reported is the one the user meant. If they said "this
  month", verify the timestamp and costing window rather than assuming the
  latest run is the right one.

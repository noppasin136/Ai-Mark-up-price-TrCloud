---
name: markup
description: Run the whole monthly pricing workflow end to end — check the ERP exports, clear any unit reviews, price everything, and explain the result. Use when the user says /markup, "run the pricing", "do the markup", "price this month", or has just dropped fresh ERP exports in and wants the workbook.
argument-hint: "[optional: 30|60|90 and/or fifo|lifo|weighted_average]"
allowed-tools: Bash(./markup.bat *) Bash(markup.bat *) Bash(.venv/Scripts/python.exe *) Bash(.venv/bin/python *) Bash(python -m markup *) Read Glob Grep
---

# Run the pricing workflow

Drive the whole sequence, stopping only where a human decision is genuinely
needed. The user wants a workbook and an explanation, not a transcript.

`$ARGUMENTS` may name a period (30/60/90) and/or a costing method — pass them
through to the update step. Ignore anything you cannot interpret and say so.

## Steps

1. **Environment.** If `.venv` is missing, stop and run the `/setup` workflow
   first; there is nothing to run without it.

2. **Check** — `.\markup.bat check`.
   Missing file → name the prefix it expects (`GR2*`, `W10*`, `markup_list*`,
   `sale_list*`) and stop. Column problem → the fix is a header spelling in
   `config/column_mapping.yaml`; show the headers it actually found, propose the
   edit, apply it once the user agrees, then re-check.

3. **Review** — `.\markup.bat review`.
   If anything is pending, **stop and put it to the user**. Explain each in
   business terms: what unit it sells in, what it was received in, the
   coefficient, and what cost that produces against the current selling price.
   Do not guess a decision — a wrong unit multiplies or divides a real cost.
   Once they answer, write it into `config/unit_review.xlsx` (Decision, and
   "Treat GR Unit As" for TREAT_AS), put their reasoning in Note, date
   Decided On, and re-run review to confirm the queue cleared.

   If nothing is pending, say so in a few words and carry on.

4. **Update** — `.\markup.bat update` plus any `--period` / `--method` from
   `$ARGUMENTS`.

5. **Report** — `.\markup.bat report`.

## What to say at the end

Lead with the outcome: SKUs priced, upload rows, average margin, where the
workbook is. Then only what deserves attention:

- SKUs held back and the honest reason — guardrail breaches are real price
  movement, not errors.
- `SKUs without cost` climbing means the period is too short for the receipt
  pattern; suggest lengthening it.
- Anything from the report worth a second look: a category whose margin sits
  below the rest, movement concentrated in one group, a SKU whose price moved
  far more than its cost did.

Tell them to open the **Exceptions** sheet before uploading, and that the
**Price Upload** sheet is safe to paste into the ERP because blocked rows never
reach it.

## Verification

Confirm the workbook path printed exists and `SKUs priced` is above zero. A run
that prices nothing is a failure to report, not a success — usually a period
window with no receipts, or a SKU-format mismatch between GR2 and W10.

---
name: update
description: Re-price the catalogue from the ERP exports in data/input, write the Excel workbook, and record the run. Use when the user says /update, "update the prices", "re-run the markup", "price the new GR2", or wants a fresh pricing workbook.
argument-hint: "[optional: --period 30|60|90] [--method fifo|lifo|weighted_average]"
allowed-tools: Bash(./markup.bat *) Bash(markup.bat *) Bash(.venv/Scripts/python.exe *) Bash(.venv/bin/python *) Bash(python -m markup *) Read Glob Grep
---

# Update prices

## Steps

1. **Check first — never skip it.** `.\markup.bat check`. A missing file or an
   unmapped column stops the run; fix that before pricing anything.

2. **Run the update**, honouring anything in `$ARGUMENTS`:

   ```
   .\markup.bat update
   .\markup.bat update --period 30
   .\markup.bat update --method fifo --period 60
   .\markup.bat update --as-of 2026-06-30      # reproduce a month-end
   ```

   Anything that is not a flag — a markup rate, a rounding rule, a guardrail —
   is a `config/config.yaml` edit. `INSTRUCTIONS.md` documents every parameter.
   Say which key you changed.

3. **Report back in prose.** Lead with SKUs priced, SKUs held back, average
   margin, and where the workbook landed. Then only what matters:

   - `Unit reviews outstanding` above zero means those SKUs were kept off the
     upload sheet. Name them and point at `/review`.
   - `SKUs without cost` climbing means the period is too short for the receipt
     pattern. Roughly 70% of in-scope SKUs have a receipt in any 90-day window,
     so partial coverage is normal — a jump is not.
   - A large blocked count means guardrails caught real price movement.
     Summarise *why* from the Exceptions sheet rather than quoting the number.

4. Point at the **Exceptions** sheet before they upload. Blocked rows never
   reach **Price Upload**, so the upload itself is safe — but those SKUs still
   need a decision.

5. Offer `/report` for the comparison against the previous run.

## Notes

- Use `update`, not `run`. Only `update` records the run, and that recording is
  what makes the next `/report` comparison possible.
- Never edit anything in `data/input/` — those are the user's ERP exports.
  `scripts/fix_sale_units.py` is the supported way to correct sale units, and it
  backs up first.

## Verification

Confirm the workbook path printed exists and `SKUs priced` is above zero. A run
that prices nothing is a failure to report, not a success. If `Unit corrections
applied` drops unexpectedly to zero, someone cleared decisions in the review
sheet — say so rather than letting prices change silently.

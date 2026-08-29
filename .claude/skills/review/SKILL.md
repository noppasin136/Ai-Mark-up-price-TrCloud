---
name: review
description: Surface and resolve SKUs whose selling unit disagrees with the unit goods were received in, before any markup is applied. Use when the user says /review, "check the units", "what needs my decision", "why is this SKU held back", or asks about UNIT_UNVERIFIED flags.
allowed-tools: Bash(./markup.bat *) Bash(markup.bat *) Bash(.venv/Scripts/python.exe *) Bash(.venv/bin/python *) Bash(python -m markup *) Read Glob Grep Edit Write
---

# Unit review

Cost is recorded per unit **received**; price is published per unit **sold**.
Where those differ the engine converts using W10's coefficient — and a mis-keyed
receipt unit looks identical to a legitimate parallel unit. Only someone who
knows the product can tell them apart, so flagged SKUs are held off the price
upload until they carry a decision.

```
.\markup.bat review              # pending only
.\markup.bat review --show-all   # including decided rows
```

This adds newly flagged SKUs to `config/unit_review.xlsx` and never overwrites a
decision already made.

## Explaining a pending item

Do not repeat the flag text. For each, give: the unit it sells in, the unit it
was received in, the coefficient, the resulting cost, and what that implies
against the current selling price. The three reasons a SKU appears:

- sale unit is not among the units received — the two reports disagree;
- sale unit is a W10 parallel unit (coefficient > 1) — conversion applies,
  confirm once;
- converted cost exceeds the selling price by more than 25% — the signature of a
  mis-keyed receipt unit.

A converted cost far above the selling price is the strongest signal: the
company would be selling at a heavy loss, which is nearly always a data-entry
error rather than a real price.

## Recording a decision

When the user tells you the answer, write it into `config/unit_review.xlsx` and
state exactly what you set.

| Decision | When |
|---|---|
| `ACCEPT` | the coefficient conversion is correct |
| `TREAT_AS` | the receipt unit is wrong — put the true unit in **Treat GR Unit As** |
| `EXCLUDE` | do not price this SKU at all |

Put their reasoning in **Note** and the date in **Decided On** — that is what
makes the sheet an audit trail rather than a list of settings.

**Never guess.** If the evidence is ambiguous, say what would settle it — usually
"what unit does the company actually buy this in?" — and leave it pending.

Then re-run review and confirm the pending count fell.

## Standing corrections

The ถุงร้อน items `902-0009`, `902-0010`, `902-0011`, `902-0012` are bought by the
pack but consistently keyed as bag in the goods receipt. They are set to
`TREAT_AS` → `pack`. If they reappear as pending, someone cleared the decision —
restore it rather than re-deciding from scratch.

## Notes

- This step never prices anything; `/update` does that.
- A SKU with no receipts is not a unit problem — it shows as `NO_COST` and needs
  a longer period, not a decision.
- If a decision you wrote is still pending, the Decision value did not match one
  of the four keywords, or `TREAT_AS` was set without a unit in "Treat GR Unit
  As". Both fall back to PENDING by design.

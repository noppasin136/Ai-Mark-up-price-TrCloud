---
name: audit
description: Produce a full data-quality report on the ERP exports — coverage by period, unit conflicts, cost volatility, SKUs with no receipts, and the column mapping. Use when the user says /audit, "check the data", "is the data any good", or before trusting a first run on new exports.
allowed-tools: Bash(.venv/Scripts/python.exe *) Bash(.venv/bin/python *) Bash(python scripts/*) Read Glob Grep
---

# Audit the input data

Read-only. Writes `data/output/data_audit_<date>.xlsx`.

```
.venv\Scripts\python.exe scripts/audit_inputs.py
```

Sheets: Findings (severity-ranked), Period Coverage, Unit Review, No Receipts,
Repricing Preview, Cost Volatility, Column Mapping.

## What to say

Group the findings by severity and explain each in business terms:

- **BLOCKER** — would produce wrong prices silently. The markup scale and the
  markup-level questions belong here.
- **DECISION** — needs the user's product knowledge, chiefly unit conflicts.
- **WARNING** — real but expected: SKUs with no receipts in the window, cost
  volatility, prices that have drifted from their rule.
- **OK** — worth stating so the user knows what was verified, not just what
  failed.

Coverage by period is the most actionable number: it tells the user which
`--period` gives enough receipts to price on. Do not present partial coverage as
a defect — roughly 70% at 90 days is normal for this catalogue.

Use `/review` to act on unit conflicts; this command only reports them.

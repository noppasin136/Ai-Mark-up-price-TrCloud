---
name: check
description: Verify the ERP exports in data/input are present and that every required column maps, before anything is priced. Use when the user says /check, "are the files ok", "did the export work", or has just added new ERP files.
allowed-tools: Bash(./markup.bat *) Bash(markup.bat *) Bash(.venv/Scripts/python.exe *) Bash(.venv/bin/python *) Bash(python -m markup *) Read Glob Grep
---

# Check the inputs

```
.\markup.bat check
```

Read-only. Reports each file, its row count, and whether every required column
was found.

## Interpreting the result

**A missing file** — the engine matches by prefix, so name the prefix it wants
(`GR2*`, `W10*`, `markup_list*`, `sale_list*`) rather than a literal filename.
The ERP's long Thai export names work unrenamed. `sale_list` is optional;
without it every W10 SKU is priced.

**A column problem** — the message lists the headers it actually found. Map the
right one in `config/column_mapping.yaml`: canonical names on the left are
fixed, the candidate list on the right is what you add to. Matching is
case-insensitive and Unicode-aware, so Thai headers work. Propose the specific
edit, apply it once the user agrees, and re-run.

**"unmapped optional columns"** is informational, not a problem. It means the
export has no freight, duty or note column — expected for this ERP.

## What to say

If everything passes, say so in one line and offer `/review` as the next step.
Do not recite row counts unless something looks off — a sudden drop in GR2 rows
compared with what the user expects is worth mentioning.

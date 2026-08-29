---
name: setup
description: Build or repair the Python environment this project runs in, and diagnose why a command is failing. Use when the user says /setup, "set it up", "nothing works", "ModuleNotFoundError", or when .venv is missing.
disable-model-invocation: true
allowed-tools: Bash(./setup.bat) Bash(./setup.ps1 *) Bash(powershell *) Bash(.venv/Scripts/python.exe *) Bash(.venv/bin/python *) Bash(python *) Bash(py *) Read Glob Grep
---

# Set up the environment

Creates `.venv/` inside the project — a private Python that touches nothing else
on the machine — installs the dependencies, registers the `markup` command and
runs the test suite.

```
.\setup.bat            # Windows; works even when script execution is blocked
.\setup.ps1            # Windows, if the execution policy allows scripts
.\setup.ps1 -Recreate  # rebuild from scratch
```

First run downloads pandas and takes a few minutes. Say that up front so the
wait is expected.

## Known failures

| Symptom | Cause | Fix |
|---|---|---|
| `running scripts is disabled on this system` | PowerShell execution policy | `.\setup.bat`, or `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (no admin needed). If Group Policy enforces it, the Set- command refuses — use the `.bat` wrappers |
| `The term 'setup.ps1' is not recognized` | PowerShell will not run from the current folder by bare name | `.\setup.ps1` — the leading `.\` is required |
| `Python was not found` | Not on PATH | Reinstall from python.org with **Add python.exe to PATH** ticked |
| `ModuleNotFoundError: No module named 'pandas'` | A different Python is being used | In VS Code: Select Interpreter → the one under `.venv`. In a terminal: use `.\markup.bat`, which calls the environment's Python directly |
| Install fails with a proxy or network error | Corporate network blocks PyPI | `pip install --proxy http://proxy:port -r requirements-dev.txt` |

Nothing in `config/`, `data/` or `src/` is touched by setup, so `-Recreate` is
always safe — no settings, decisions or exports are lost.

## Verify

```
.venv\Scripts\python.exe -m markup validate
.venv\Scripts\python.exe -m pytest -q
```

54 tests should pass. Then run `/check` to confirm the ERP exports parse, and
tell the user the flow is `/check` → `/review` → `/update` → `/report`.

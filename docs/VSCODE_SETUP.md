# Running this in VS Code (Windows)

One-time setup, then four buttons.

---

## One-time setup

### 1. Open the folder

VS Code → **File > Open Folder** → `C:\Ai Mark up price`

Open the folder itself, not a single file. Everything below depends on VS Code
knowing this folder is the project.

### 2. Install the recommended extensions

A prompt appears in the bottom right: **"This workspace has extension
recommendations"** → **Install**.

If you miss it: Extensions panel (`Ctrl+Shift+X`) → type `@recommended` → install
the list. You need **Python** and **Pylance**; the rest are conveniences. The
Excel Viewer one lets you open the output workbooks without leaving VS Code.

### 3. Build the environment

**Terminal > Run Task…** → **Setup: create environment**

This creates `.venv\` inside the project — a private Python installation just
for this work, so nothing else on your machine is touched. It installs pandas,
openpyxl and the rest, registers the `markup` command, and finishes by running
the test suite.

First run takes a few minutes because pandas is a large download. Later runs
take seconds.

> If the task does not appear, run it yourself. In a PowerShell terminal
> (`` Ctrl+` ``), from the project folder:
>
> ```powershell
> .\setup.ps1
> ```
>
> The leading `.\` is not optional — PowerShell refuses to run a script from the
> current folder without it, and reports `The term 'setup.ps1' is not
> recognized`. If the execution policy blocks it, use `.\setup.bat`, which works
> around that for the one run. Double-clicking `setup.bat` in File Explorer works
> too.

### 4. Point VS Code at the new environment

`Ctrl+Shift+P` → **Python: Select Interpreter** → choose the one whose path
contains `.venv\Scripts\python.exe`. It is usually top of the list and marked
**Recommended**.

This is the step people skip. Without it, VS Code uses some other Python that
does not have pandas installed, and everything fails with `ModuleNotFoundError`.

**Close any terminal that was already open** (bin icon) so the next one picks up
the environment.

You are done. The rest of this page is day-to-day use.

---

## Running the four commands

### With buttons — Tasks

**Terminal > Run Task…** then pick:

| Task | What it does |
|---|---|
| **1. Check inputs** | Are the ERP files present, and do the columns map? |
| **2. Review units** | SKUs whose selling unit and receipt unit disagree |
| **3. Update prices** | Price everything, write the workbook, record the run |
| **4. Report** | Summary, category rollup, diff against the previous run |
| Update: choose period and method | Prompts for 30/60/90 and the costing method |
| Audit input data | Full data-quality report on the exports |
| Open the latest output folder | Opens `data\output\` in File Explorer |
| Run tests | Confirms the engine still behaves after a change |

**3. Update prices** is the default build task, so `Ctrl+Shift+B` runs it
straight away.

### Without activating anything

If PowerShell's execution policy is locked down and you cannot change it, use the
wrapper — it calls the environment's own Python directly, so no activation and no
policy change is needed:

```powershell
.\markup.bat check
.\markup.bat review
.\markup.bat update --period 30 --method fifo
.\markup.bat report
```

The VS Code tasks and F5 entries already work this way, so they are unaffected by
the policy either way.

### With the debugger — F5

`Ctrl+Shift+D` opens the Run and Debug panel. Pick a command from the dropdown
at the top and press **F5**.

The difference from a task: you can set a **breakpoint** (click to the left of a
line number in any `.py` file) and the program stops there so you can inspect
what it is doing. That is how you answer "why did this SKU get that price?" —
put a breakpoint in `src/markup/pipeline.py` and step through it.

### In the terminal

`` Ctrl+` `` opens a terminal. If the prompt does not already start with
`(.venv)`, activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If that is blocked by the execution policy, either fix the policy once (below) or
use `.\markup.bat <command>` instead, which needs no activation.

Then:

```powershell
markup check
markup review
markup update
markup report
```

With parameters:

```powershell
markup update --period 30
markup update --method fifo --period 60
markup update --as-of 2026-06-30
markup report --group-by department
markup runs
```

`INSTRUCTIONS.md` documents every parameter.

---

## Editing the settings

`config\config.yaml` is the file you will change most. VS Code gives you syntax
colouring and will underline a structural mistake in red before you run
anything. After editing, check it:

```powershell
markup validate
```

`config\unit_review.xlsx` is the decisions sheet. Open it in Excel rather than
VS Code — it has dropdowns that VS Code's viewer will not show.

---

## Where things are

```
config\        config.yaml (parameters), column_mapping.yaml (ERP headers),
               unit_review.xlsx (your unit decisions)
data\input\    the ERP exports go here
data\output\   workbooks, reports and run history come out here
src\markup\    the engine
tests\         the test suite
scripts\       audit and repair tools
```

---

## When something goes wrong

| What you see | What it means | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'pandas'` | VS Code is using the wrong Python | Select Interpreter → the `.venv` one, then open a new terminal |
| `markup : The term 'markup' is not recognized` | The environment is not activated in this terminal | `.\.venv\Scripts\Activate.ps1`, or use `python -m markup ...` |
| `The term 'setup.ps1' is not recognized` | PowerShell will not run a script from the current folder without a path | Type `.\setup.ps1` — the leading `.\` is required |
| `running scripts is disabled on this system` | PowerShell's execution policy — see below | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use `.\setup.bat` and `.\markup.bat` |
| `Activate.ps1 cannot be loaded` | Same execution policy, blocking environment activation | Same fix, or skip activation entirely with `.\markup.bat <command>` |
| `Python was not found` | Python is not on PATH | Reinstall from python.org with **Add python.exe to PATH** ticked |
| `Missing required input(s)` | An export is not in `data\input\` | File names must start with `GR2`, `W10`, `markup_list`, `sale_list` |
| `missing required column(s)` | An ERP header changed | The message lists the headers it found — add the right one to `column_mapping.yaml` |
| `No run history yet` | `report` before `update` | Run `markup update` first |
| Debugger does nothing on F5 | No configuration selected | Open Run and Debug (`Ctrl+Shift+D`) and pick one from the dropdown |
| Editor is sluggish | The 62 MB GR2 file | Already excluded from search and file watching; do not open it in the editor |

If dependency installation fails behind a corporate network, the proxy is the
usual cause. `pip install --proxy http://your-proxy:port -r requirements-dev.txt`
works once you have the address from IT.

---

## About PowerShell's execution policy

Windows ships with script execution switched off. Both `setup.ps1` and the
environment's own `Activate.ps1` are scripts, so on a fresh machine you will see:

```
running scripts is disabled on this system
```

**The clean fix**, which needs no administrator rights and changes nothing for
any other user of the machine:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

`RemoteSigned` means scripts written locally may run, while anything downloaded
from the internet must carry a valid signature. This is the setting Microsoft
recommends for development machines, and it is what makes both the setup script
and normal environment activation work.

**If your IT department enforces the policy by Group Policy**, the command above
fails with *"overridden by a policy defined at a more specific scope"*. In that
case do not fight it — use the `.bat` wrappers, which never invoke PowerShell
scripts at all:

```powershell
.\setup.bat                  # instead of .\setup.ps1
.\markup.bat check           # instead of activating, then markup check
```

VS Code tasks and F5 debugging call the environment's Python directly, so they
work regardless of the policy.

---

## Rebuilding from scratch

If the environment gets into a confusing state:

```powershell
.\setup.ps1 -Recreate
```

That deletes `.venv\` and rebuilds it. Nothing in `config\`, `data\` or `src\`
is touched, so no settings, decisions or exports are lost.

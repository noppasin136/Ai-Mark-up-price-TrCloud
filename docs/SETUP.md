# Setup

The intended way to use this project is to talk to Claude in a terminal and type
slash commands — `/markup`, `/update`, `/report`. This page covers getting there,
and the manual route if you prefer to type the commands yourself.

Written against a real install on a fresh Windows machine, in the order things
actually happen, including the two places Windows gets in the way.

---

## The short version

```powershell
# 1. Install Claude Code (no admin needed)
irm https://claude.ai/install.ps1 | iex

# 2. New terminal, then:
cd "C:\Ai Mark up price"
claude
```

Then type `/setup` and let Claude build the environment. Then `/check`.

If that works, you can stop reading. The rest of this page is for when it
doesn't, and for running things without Claude.

---

## Before you start

- **Python 3.10 or newer.** From [python.org](https://www.python.org/downloads/),
  with **Add python.exe to PATH** ticked on the installer's first screen.
- **VS Code.**
- Roughly 10 minutes, most of it waiting for pandas to download.

---

## Step 1 — Allow PowerShell to run scripts

Do this first. Windows ships with script execution switched off, and both the
setup script and the environment's own activation script are blocked by it. You
will otherwise meet this twice:

```
running scripts is disabled on this system
```

In PowerShell:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

`RemoteSigned` means scripts written locally may run, while anything downloaded
from the internet must carry a valid signature. It needs no administrator
rights, affects only your account, and is the setting Microsoft recommends for
development machines.

**If your IT department enforces the policy** the command fails with *"overridden
by a policy defined at a more specific scope"*. Don't fight it — this project
ships `.bat` wrappers that never invoke a PowerShell script:

| Instead of | Use |
|---|---|
| `.\setup.ps1` | `.\setup.bat` |
| activating, then `markup check` | `.\markup.bat check` |

VS Code tasks and F5 debugging call the environment's Python directly, so they
work either way.

> **A PowerShell habit worth knowing:** it will not run a script from the current
> folder by bare name. `setup.bat` gives *"The term 'setup.bat' is not
> recognized"*; `.\setup.bat` works. The leading `.\` is required, and Command
> Prompt not needing it is why this catches everyone once.

---

## Step 2 — Open the folder

VS Code → **File > Open Folder** → `C:\Ai Mark up price`

Open the folder itself, not a single file. Everything below depends on VS Code
knowing this folder is the project.

---

## Step 3 — Install the recommended extensions

A prompt appears bottom-right: **"This workspace has extension
recommendations"** → **Install**.

If you miss it: Extensions panel (`Ctrl+Shift+X`) → type `@recommended`. You need
**Python** and **Pylance**; the rest are conveniences. Excel Viewer lets you open
the output workbooks without leaving VS Code.

---

## Step 4 — Build the environment

**Terminal > Run Task…** → **Setup: create environment**

Or from a terminal in the project folder:

```powershell
.\setup.ps1        # or .\setup.bat if the policy is locked down
```

This creates `.venv\` inside the project — a private Python just for this work,
so nothing else on your machine is touched. It installs pandas, openpyxl and the
rest, registers the `markup` command, and finishes by running the test suite.

The first run takes a few minutes because pandas is a large download. Later runs
take seconds.

You should see it work through four numbered stages and end with **Setup
complete**. If it stops earlier, find the message in
[When something goes wrong](#when-something-goes-wrong) below.

---

## Step 5 — Point VS Code at the new environment

`Ctrl+Shift+P` → **Python: Select Interpreter** → choose the one whose path
contains `.venv\Scripts\python.exe`. It is usually top of the list, marked
**Recommended**.

**This is the step people skip.** Without it VS Code uses some other Python that
has no pandas, and every command fails with `ModuleNotFoundError`.

Then **close any terminal that was already open** (the bin icon) so the next one
starts with the environment active.

Setup is done. The rest of this page is day-to-day use.

---

## Running the four commands

The flow is always the same order:

```
check  →  review  →  update  →  report
```

### With Claude — the normal way

```
/markup     the whole sequence, with Claude judging what needs your input
/check      are the exports readable?
/review     units needing a decision
/update     price everything
/report     summary and comparison
/audit      full data-quality report
```

Claude runs the command, reads the output and explains it. You can also just
describe what you want — "price it on 30 days using FIFO" — and it will pass the
right flags.

### With buttons — VS Code Tasks

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
directly.

### With the debugger — F5

`Ctrl+Shift+D` opens Run and Debug. Pick a command from the dropdown and press
**F5**.

The difference from a task: you can set a **breakpoint** — click to the left of a
line number in any `.py` file — and the program stops there so you can inspect
what it is doing. That is how you answer "why did this SKU get that price?": put
a breakpoint in `src/markup/pipeline.py` and step through.

### In the terminal

`` Ctrl+` `` opens a terminal. If the prompt does not already start with
`(.venv)`, activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

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

### Without activating anything

If activation is blocked, the wrapper calls the environment's Python directly:

```powershell
.\markup.bat check
.\markup.bat review
.\markup.bat update --period 30 --method fifo
.\markup.bat report
```

---

## Claude Code — the intended interface

Claude Code lets you drive this project with slash commands from any terminal,
including the one inside VS Code. The engine is plain Python and runs perfectly
well without it, but the commands (`/markup`, `/check`, `/review`, `/update`,
`/report`) live in this repository and only work through Claude Code.

Install from PowerShell (no administrator rights needed):

```powershell
irm https://claude.ai/install.ps1 | iex
```

This is not blocked by the execution policy, because it runs in memory rather
than as a `.ps1` file on disk. If it fails anyway,
`winget install Anthropic.ClaudeCode` is the alternative — it registers PATH
itself, at the cost of not auto-updating.

Then:

1. **Open a new PowerShell window** and run `claude --version`. A version number
   such as `2.1.251 (Claude Code)` means it worked.
2. **Quit VS Code completely** — File > Exit, not just closing the window — and
   reopen. VS Code reads PATH once at launch.
3. In the terminal: `claude`. First run sends you to the browser to log in. It
   needs a Pro, Max, Team or Enterprise account.

Once inside, type `/` to see the project's commands. They come from
`.claude/skills/` in this repository, so anyone who clones it gets the same set.
`CLAUDE.md` at the root is what Claude reads at the start of every session — the
domain rules, the input formats, and the mistakes that are easy to make.

[Git for Windows](https://git-scm.com/downloads/win) is optional but recommended
— it gives Claude Code Git Bash instead of PowerShell for shell commands.

**If `claude` is not recognised after installing**, the binary landed but PATH
was not updated. Check and fix:

```powershell
$dir = "$env:USERPROFILE\.local\bin"
$exe = Join-Path $dir 'claude.exe'
if (Test-Path $exe) {
    & $exe --version
    $user = [Environment]::GetEnvironmentVariable('Path','User')
    if ($user -notlike "*$dir*") {
        [Environment]::SetEnvironmentVariable('Path', ($user.TrimEnd(';') + ';' + $dir), 'User')
        "PATH updated - open a new window"
    }
} else {
    "Not installed - re-run the installer"
}
```

Use `[Environment]::GetEnvironmentVariable('Path','User')` rather than
`$env:Path` here. `$env:Path` is the machine and user paths already merged, so
writing it back into the user scope duplicates every system entry into your
account.

---

## Editing the settings

`config\config.yaml` is the file you will change most. VS Code colours the syntax
and underlines a structural mistake before you run anything. After editing:

```powershell
markup validate
```

`config\unit_review.xlsx` holds your unit decisions. Open it in **Excel**, not
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
| `The term 'setup.ps1' is not recognized` | PowerShell will not run a script from the current folder by bare name | `.\setup.ps1` — the leading `.\` is required |
| `running scripts is disabled on this system` | Execution policy — see [Step 1](#step-1--allow-powershell-to-run-scripts) | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use `.\setup.bat` |
| `Activate.ps1 cannot be loaded` | Same policy, blocking environment activation | Same fix, or skip activation with `.\markup.bat <command>` |
| `ModuleNotFoundError: No module named 'pandas'` | VS Code is using the wrong Python | Select Interpreter → the `.venv` one, then open a new terminal |
| `markup : The term 'markup' is not recognized` | Environment not activated in this terminal | `.\.venv\Scripts\Activate.ps1`, or use `.\markup.bat` |
| `Python was not found` | Python is not on PATH | Reinstall from python.org with **Add python.exe to PATH** ticked |
| `Unknown option: -3` during setup | An old bug — setup used the `py` launcher, which does not forward arguments on every machine | Fixed; pull the latest `setup.ps1` and re-run |
| `Could not locate the Claude CLI on PATH` | VS Code started before Claude Code was installed, or PATH was never updated | Fix PATH (above), then **File > Exit** and reopen VS Code |
| `Missing required input(s)` | An export is not in `data\input\` | File names must start with `GR2`, `W10`, `markup_list`, `sale_list` |
| `missing required column(s)` | An ERP header changed | The message lists the headers it found — add the right one to `column_mapping.yaml` |
| `No run history yet` | `report` before `update` | Run `markup update` first |
| Debugger does nothing on F5 | No configuration selected | Open Run and Debug (`Ctrl+Shift+D`) and pick one from the dropdown |
| Editor is sluggish | The 62 MB GR2 file | Already excluded from search and file watching; don't open it in the editor |

Dependency installation failing behind a corporate network is usually the proxy:

```powershell
pip install --proxy http://your-proxy:port -r requirements-dev.txt
```

---

## Rebuilding from scratch

If the environment gets into a confusing state:

```powershell
.\setup.ps1 -Recreate
```

That deletes `.venv\` and rebuilds it. Nothing in `config\`, `data\` or `src\` is
touched, so no settings, decisions or exports are lost.

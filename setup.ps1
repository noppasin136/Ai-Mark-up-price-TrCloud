<#
    Markup Pricing Engine — Windows setup

    Creates a private Python environment for this folder and installs everything
    the engine needs. Safe to run again at any time; it will reuse or repair the
    existing environment rather than starting over.

    Run it from VS Code:  Terminal > Run Task > "Setup: create environment"
    Or from PowerShell:   .\setup.ps1
#>

[CmdletBinding()]
param(
    [switch]$Recreate,   # delete and rebuild the environment from scratch
    [switch]$SkipTests   # skip the verification test run
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Say  ($m) { Write-Host $m }
function Good ($m) { Write-Host "  OK    $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "  note  $m" -ForegroundColor Yellow }
function Bad  ($m) { Write-Host "  FAIL  $m" -ForegroundColor Red }

Say ""
Say "Markup Pricing Engine — setup"
Say "Folder: $root"
Say ("-" * 62)

# --- 1. Find a usable Python ------------------------------------------------
Say ""
Say "1. Looking for Python 3.10 or newer"

$python = $null
foreach ($candidate in @(
    @{ Exe = 'py';     Args = @('-3', '--version') },
    @{ Exe = 'python'; Args = @('--version') },
    @{ Exe = 'python3'; Args = @('--version') }
)) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
    try {
        $raw = & $candidate.Exe @($candidate.Args) 2>&1 | Out-String
        if ($raw -match 'Python (\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 10) {
                $python = $candidate
                Good "$($raw.Trim())  (via '$($candidate.Exe)')"
                break
            }
            Warn "$($raw.Trim()) found via '$($candidate.Exe)' — too old, need 3.10+"
        }
    } catch { }
}

if (-not $python) {
    Bad "No Python 3.10 or newer found."
    Say ""
    Say "  Install it from https://www.python.org/downloads/"
    Say "  During installation, tick 'Add python.exe to PATH' on the first screen."
    Say "  Then close every PowerShell window, open a new one, and run this again."
    exit 1
}

# The launcher needs its version flag; a bare python.exe does not.
$pyExe  = $python.Exe
$pyArgs = if ($pyExe -eq 'py') { @('-3') } else { @() }

# --- 2. Virtual environment -------------------------------------------------
Say ""
Say "2. Preparing the virtual environment (.venv)"

$venv       = Join-Path $root '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

if ($Recreate -and (Test-Path $venv)) {
    Warn "Removing the existing environment because -Recreate was given"
    Remove-Item $venv -Recurse -Force
}

if (Test-Path $venvPython) {
    Good "Reusing the existing environment"
} else {
    if (Test-Path $venv) {
        Warn ".venv exists but has no python.exe — rebuilding it"
        Remove-Item $venv -Recurse -Force
    }
    & $pyExe @($pyArgs + @('-m', 'venv', $venv))
    if (-not (Test-Path $venvPython)) {
        Bad "Could not create the virtual environment."
        Say "  Try:  $pyExe $pyArgs -m ensurepip --upgrade"
        exit 1
    }
    Good "Created .venv"
}

# --- 3. Dependencies --------------------------------------------------------
Say ""
Say "3. Installing dependencies"
Say "   (first run downloads pandas and openpyxl — this can take a few minutes)"

& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Bad "Could not upgrade pip."; exit 1 }
Good "pip up to date"

& $venvPython -m pip install -r (Join-Path $root 'requirements-dev.txt') --quiet
if ($LASTEXITCODE -ne 0) {
    Bad "Dependency install failed."
    Say "  If your company network blocks PyPI, you will need its proxy settings,"
    Say "  or an internal package index, before this can complete."
    exit 1
}
Good "pandas, openpyxl, PyYAML, click, pytest, ruff"

& $venvPython -m pip install -e $root --quiet
if ($LASTEXITCODE -ne 0) {
    Warn "Editable install failed — the 'markup' shortcut will not exist."
    Warn "Use 'python -m markup ...' instead. Everything else still works."
} else {
    Good "'markup' command registered"
}

# --- 4. Verify --------------------------------------------------------------
Say ""
Say "4. Verifying"

& $venvPython -m markup validate
if ($LASTEXITCODE -ne 0) { Bad "Configuration did not validate."; exit 1 }

if (-not $SkipTests) {
    Say ""
    Say "   Running the test suite"
    & $venvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        Warn "Some tests failed. The engine may still run, but check this before"
        Warn "trusting the output."
    } else {
        Good "All tests passed"
    }
}

# --- Done -------------------------------------------------------------------
Say ""
Say ("-" * 62)
Say "Setup complete."
Say ""
Say "In VS Code:"
Say "  Ctrl+Shift+P > 'Python: Select Interpreter' > the one inside .venv"
Say "  Then Terminal > Run Task, or press F5 and pick a command."
Say ""
Say "In this terminal, activate the environment first:"
Say "  .\.venv\Scripts\Activate.ps1"
Say ""
Say "Then the four commands, in order:"
Say "  markup check     is data\input\ ready?"
Say "  markup review    units needing your decision"
Say "  markup update    price everything"
Say "  markup report    summary and comparison"
Say ""

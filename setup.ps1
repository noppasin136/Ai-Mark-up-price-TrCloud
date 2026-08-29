<#
    Markup Pricing Engine — Windows setup

    Creates a private Python environment for this folder and installs everything
    the engine needs. Safe to run again at any time; it reuses or repairs the
    existing environment rather than starting over.

    From VS Code:    Terminal > Run Task > "Setup: create environment"
    From PowerShell: .\setup.ps1
    Policy blocked?  .\setup.bat
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
# Ask each candidate for its own absolute path and version. Everything after
# this point uses that path directly: the 'py' launcher is only a way to FIND
# an interpreter, never a way to run one, because its argument forwarding
# varies between installations.
Say ""
Say "1. Looking for Python 3.10 or newer"

# No quotes in this snippet — quoting rules differ between PowerShell hosts.
$probe = 'import sys;print(sys.executable);print(sys.version_info[0]);print(sys.version_info[1])'

function Get-PythonInfo {
    param([string]$Command, [string]$VersionFlag)
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) { return $null }
    try {
        if ($VersionFlag) { $raw = & $Command $VersionFlag -c $probe 2>&1 | Out-String }
        else              { $raw = & $Command            -c $probe 2>&1 | Out-String }
    } catch { return $null }

    $lines = ($raw -split "`r?`n") | Where-Object { $_.Trim() -ne '' }
    if ($lines.Count -lt 3) { return $null }
    $exe = $lines[0].Trim()
    if (-not (Test-Path $exe)) { return $null }
    $major = 0; $minor = 0
    if (-not [int]::TryParse($lines[1].Trim(), [ref]$major)) { return $null }
    if (-not [int]::TryParse($lines[2].Trim(), [ref]$minor)) { return $null }
    return [pscustomobject]@{ Exe = $exe; Major = $major; Minor = $minor; Via = $Command }
}

$python = $null
foreach ($try in @(
    @{ Command = 'py';      Flag = '-3' },
    @{ Command = 'python';  Flag = ''   },
    @{ Command = 'python3'; Flag = ''   }
)) {
    $found = Get-PythonInfo -Command $try.Command -VersionFlag $try.Flag
    if (-not $found) { continue }
    if ($found.Major -eq 3 -and $found.Minor -ge 10) {
        $python = $found
        Good "Python $($found.Major).$($found.Minor)  ($($found.Exe))"
        break
    }
    Warn "Python $($found.Major).$($found.Minor) found via '$($try.Command)' — too old, need 3.10+"
}

if (-not $python) {
    Bad "No Python 3.10 or newer found."
    Say ""
    Say "  Install it from https://www.python.org/downloads/"
    Say "  Tick 'Add python.exe to PATH' on the first screen of the installer."
    Say "  Then close every PowerShell window, open a new one, and run this again."
    exit 1
}

$pythonExe = $python.Exe

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
    & $pythonExe -m venv $venv
    if (-not (Test-Path $venvPython)) {
        Bad "Could not create the virtual environment."
        Say "  Try running this by hand to see the underlying error:"
        Say "    & '$pythonExe' -m venv '$venv'"
        exit 1
    }
    Good "Created .venv"
}

# --- 3. Dependencies --------------------------------------------------------
Say ""
Say "3. Installing dependencies"
Say "   (the first run downloads pandas and openpyxl — this can take a few minutes)"

& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Bad "Could not upgrade pip."; exit 1 }
Good "pip up to date"

& $venvPython -m pip install -r (Join-Path $root 'requirements-dev.txt') --quiet
if ($LASTEXITCODE -ne 0) {
    Bad "Dependency install failed."
    Say "  If your network blocks PyPI, you will need the company proxy first:"
    Say "    & '$venvPython' -m pip install --proxy http://proxy:port -r requirements-dev.txt"
    exit 1
}
Good "pandas, openpyxl, PyYAML, click, pytest, ruff"

& $venvPython -m pip install -e $root --quiet
if ($LASTEXITCODE -ne 0) {
    Warn "Editable install failed — the bare 'markup' shortcut will not exist."
    Warn "Use '.\markup.bat <command>' instead. Everything else still works."
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
Say "In this terminal — no activation needed:"
Say "  .\markup.bat check     is data\input\ ready?"
Say "  .\markup.bat review    units needing your decision"
Say "  .\markup.bat update    price everything"
Say "  .\markup.bat report    summary and comparison"
Say ""

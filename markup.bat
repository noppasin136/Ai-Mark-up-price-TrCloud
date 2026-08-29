@echo off
REM Run any markup command without activating the environment, and without
REM PowerShell's script-execution policy getting in the way.
REM
REM   .\markup.bat check
REM   .\markup.bat review
REM   .\markup.bat update --period 30 --method fifo
REM   .\markup.bat report
REM
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo The environment is not set up yet. Run  .\setup.bat  first.
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m markup %*

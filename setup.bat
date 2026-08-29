@echo off
REM Double-click this if PowerShell refuses to run setup.ps1 directly.
REM -ExecutionPolicy Bypass applies to this one run only; nothing on the
REM machine is changed permanently.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause

@echo off
setlocal
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0update.ps1" -HomeDir "%~dp0."
if errorlevel 1 pause

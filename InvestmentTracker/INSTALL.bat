@echo off
:: Right-click this file -> "Run as administrator"
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\install.ps1"
pause

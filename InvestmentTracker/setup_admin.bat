@echo off
:: Create a new administrator, or reset an administrator's password
set "APP=%~dp0"
if exist "C:\InvestmentTracker\venv\Scripts\python.exe" set "APP=C:\InvestmentTracker\"
cd /d "%APP%"
if exist "%APP%venv\Scripts\python.exe" ("%APP%venv\Scripts\python.exe" run_server.py --create-admin) else (python run_server.py --create-admin)
pause

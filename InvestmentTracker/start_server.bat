@echo off
:: Run the server in this window (for testing). Normally it runs automatically in the background.
set "APP=%~dp0"
if exist "C:\InvestmentTracker\venv\Scripts\python.exe" set "APP=C:\InvestmentTracker\"
cd /d "%APP%"
schtasks /end /tn InvestmentTracker >nul 2>&1
if exist "%APP%venv\Scripts\python.exe" ("%APP%venv\Scripts\python.exe" run_server.py) else (python run_server.py)
pause

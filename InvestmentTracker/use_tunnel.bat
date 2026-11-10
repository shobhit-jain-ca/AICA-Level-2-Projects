@echo off
:: Run as administrator. Makes the app reachable ONLY through the Cloudflare Tunnel:
::  - server listens on 127.0.0.1 only
::  - Windows Firewall rule for the port is removed
::  - desktop icon opens the public address
set "APP=%~dp0"
if exist "C:\InvestmentTracker\venv\Scripts\python.exe" set "APP=C:\InvestmentTracker\"
if not exist "%APP%venv\Scripts\python.exe" (
  echo Could not find the installed program. Run INSTALL.bat first.
  pause
  exit /b 1
)
cd /d "%APP%"
set /p PUBHOST=Public address (example: tracker.capbridgegrowth.com): 
"%APP%venv\Scripts\python.exe" tools\use_tunnel.py %PUBHOST%
if errorlevel 1 (
  echo Nothing was changed.
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Investment Tracker" >nul 2>&1
schtasks /end /tn InvestmentTracker >nul 2>&1
schtasks /run /tn InvestmentTracker
echo.
echo Wait about 20 seconds, then open  https://%PUBHOST%
pause

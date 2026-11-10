@echo off
:: Run as administrator. Creates a self-signed certificate and switches the server to HTTPS.
set "APP=%~dp0"
if exist "C:\InvestmentTracker\venv\Scripts\python.exe" set "APP=C:\InvestmentTracker\"
if not exist "%APP%venv\Scripts\python.exe" (
  echo Could not find the installed program. Run INSTALL.bat first.
  pause
  exit /b 1
)
cd /d "%APP%"
set /p HOSTNAME=Enter the public IP address or domain name clients will use: 
"%APP%venv\Scripts\python.exe" -m pip install cryptography
"%APP%venv\Scripts\python.exe" tools\make_cert.py %HOSTNAME%
schtasks /end /tn InvestmentTracker >nul 2>&1
schtasks /run /tn InvestmentTracker
echo.
echo Now open  https://%HOSTNAME%:8080  (accept the one-time browser warning).
pause

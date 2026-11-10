@echo off
:: Run as administrator AFTER copying a new version of the files over C:\InvestmentTracker.
:: Installs any new Python packages and restarts the server. Your data is not touched.
set "APP=C:\InvestmentTracker\"
if not exist "%APP%venv\Scripts\python.exe" (
  echo Could not find C:\InvestmentTracker. Run INSTALL.bat first.
  pause
  exit /b 1
)
cd /d "%APP%"
"%APP%venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Package installation failed - check the internet connection and try again.
  pause
  exit /b 1
)
schtasks /end /tn InvestmentTracker >nul 2>&1
schtasks /run /tn InvestmentTracker
echo.
echo Done. Wait about 20 seconds, then refresh the page in the browser.
pause

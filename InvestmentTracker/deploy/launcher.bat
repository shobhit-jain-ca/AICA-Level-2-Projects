@echo off
:: Desktop icon target: makes sure the server is running, then opens Chrome.
setlocal
set "APPDIR=%~dp0.."
set "PORT=8080"
set "SCHEME=http"
set "PUBLIC_URL="
if exist "%~dp0launcher.cfg" call "%~dp0launcher.cfg"
set "URL=%SCHEME%://localhost:%PORT%/"
if defined PUBLIC_URL set "URL=%PUBLIC_URL%"

call :isup
if errorlevel 1 (
  schtasks /run /tn InvestmentTracker >nul 2>&1
  call :wait
)
call :isup
if errorlevel 1 (
  start "" /min /d "%APPDIR%" "%APPDIR%\venv\Scripts\pythonw.exe" "%APPDIR%\run_server.py"
  call :wait
)

set "CHROME="
for %%P in ("%ProgramFiles%\Google\Chrome\Application\chrome.exe" "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" "%LocalAppData%\Google\Chrome\Application\chrome.exe") do if exist %%P set "CHROME=%%~P"
if defined CHROME (start "" "%CHROME%" --new-window "%URL%") else (start "" "%URL%")
exit /b 0

:isup
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%);$c.Close();exit 0}catch{exit 1}"
exit /b %errorlevel%

:wait
for /l %%i in (1,1,15) do (
  call :isup
  if not errorlevel 1 exit /b 0
  ping -n 2 127.0.0.1 >nul
)
exit /b 1

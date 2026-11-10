# Investment Tracker - one-time installer (run as Administrator via INSTALL.bat)
param([int]$Port = 8080, [string]$InstallDir = "C:\InvestmentTracker")
$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Host "Please run INSTALL.bat as Administrator (right-click -> Run as administrator)." -ForegroundColor Red; exit 1 }

$src = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Step "Looking for Python 3.9 or newer"
$py = $null
$cands = New-Object System.Collections.ArrayList
foreach ($n in @("python", "py")) { $c = Get-Command $n -ErrorAction SilentlyContinue; if ($c) { [void]$cands.Add($c.Source) } }
foreach ($pat in @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                   "C:\Program Files\Python3*\python.exe", "C:\Program Files (x86)\Python3*\python.exe",
                   "C:\Python3*\python.exe", "C:\Users\*\AppData\Local\Programs\Python\Python3*\python.exe")) {
  Get-ChildItem $pat -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object { [void]$cands.Add($_.FullName) }
}
foreach ($cand in $cands) {
  try {
    $ver = & $cand -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($ver -and [version]$ver -ge [version]"3.9") { $py = $cand; break }
  } catch {}
}
if (-not $py) { Write-Host "Python 3.9 or newer was not found. Install it from python.org (tick 'Add python.exe to PATH' and 'Install for all users'), then run this again." -ForegroundColor Red; exit 1 }
$pyExe = & $py -c "import sys;print(sys.executable)"
Write-Host "Using $pyExe"
if ($pyExe -match "\\Users\\") { Write-Host "NOTE: Python is installed for one user only. Other Windows users may not be able to start the server from the icon (the background service will still work). Installing Python 'for all users' is recommended." -ForegroundColor Yellow }

Step "Copying files to $InstallDir (existing data is kept)"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
if ((Resolve-Path $src).Path -ne (Resolve-Path $InstallDir).Path) {
  robocopy $src $InstallDir /E /XD data venv __pycache__ .git /XF *.pyc server.log | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "File copy failed (robocopy code $LASTEXITCODE)" }
}
New-Item -ItemType Directory -Force -Path "$InstallDir\data" | Out-Null

Step "Creating private Python environment and installing packages"
if (-not (Test-Path "$InstallDir\venv\Scripts\python.exe")) { & $py -m venv "$InstallDir\venv" }
& "$InstallDir\venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$InstallDir\venv\Scripts\python.exe" -m pip install -r "$InstallDir\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) { throw "Package installation failed. Check the server's internet connection." }

Step "Setting folder permissions so every Windows user can run the app"
icacls "$InstallDir" /grant "BUILTIN\Users:(OI)(CI)RX" /T /Q | Out-Null
icacls "$InstallDir\data" /grant "BUILTIN\Users:(OI)(CI)M" /T /Q | Out-Null

Step "Writing configuration (port $Port)"
$cfgPath = "$InstallDir\data\config.json"
if (-not (Test-Path $cfgPath)) { Set-Content -Path $cfgPath -Value ('{"host": "0.0.0.0", "port": ' + $Port + ', "https": false}') -Encoding ASCII }
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$Port = [int]$cfg.port
$scheme = if ($cfg.https) { "https" } else { "http" }
Set-Content -Path "$InstallDir\deploy\launcher.cfg" -Value "set PORT=$Port`r`nset SCHEME=$scheme" -Encoding ASCII

Step "Creating the administrator account"
$ans = Read-Host "Create or reset an administrator login now? (Y/N)"
if ($ans -match "^[Yy]") { & "$InstallDir\venv\Scripts\python.exe" "$InstallDir\run_server.py" --create-admin }

Step "Opening Windows Firewall for port $Port"
Get-NetFirewallRule -DisplayName "Investment Tracker" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "Investment Tracker" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Any | Out-Null

Step "Registering the background service (starts automatically with Windows)"
$taskName = "InvestmentTracker"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action    = New-ScheduledTaskAction -Execute "$InstallDir\venv\Scripts\pythonw.exe" -Argument "run_server.py" -WorkingDirectory $InstallDir
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $taskName

Step "Creating the desktop icon (visible to all users)"
$ws = New-Object -ComObject WScript.Shell
foreach ($lnkPath in @("$env:PUBLIC\Desktop\Investment Tracker.lnk", "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Investment Tracker.lnk")) {
  $l = $ws.CreateShortcut($lnkPath)
  $l.TargetPath = "$InstallDir\deploy\launcher.bat"
  $l.WorkingDirectory = "$InstallDir\deploy"
  $l.IconLocation = "$InstallDir\static\img\app.ico"
  $l.Description = "Open Investment Tracker in Chrome"
  $l.WindowStyle = 7
  $l.Save()
}

Step "Preparing a shortcut you can send to the client"
$pub = $null
try { $pub = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 8).Trim() } catch {}
New-Item -ItemType Directory -Force -Path "$InstallDir\SendToClient" | Out-Null
if ($pub) {
  Set-Content -Path "$InstallDir\SendToClient\Investment Tracker.url" -Value "[InternetShortcut]`r`nURL=${scheme}://${pub}:$Port/" -Encoding ASCII
}

Start-Sleep -Seconds 3
Write-Host "`n=====================================================" -ForegroundColor Green
Write-Host " Installation complete" -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Green
Write-Host " On this server : ${scheme}://localhost:$Port/   (double-click the 'Investment Tracker' icon on the desktop)"
if ($pub) { Write-Host " From anywhere   : ${scheme}://${pub}:$Port/   (needs the port opened at your router / cloud firewall - see README)" }
else      { Write-Host " From anywhere   : ${scheme}://<your-public-IP>:$Port/" }
Write-Host " Data folder     : $InstallDir\data   (database, uploaded files, backups)"

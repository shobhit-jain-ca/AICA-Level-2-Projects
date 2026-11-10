@echo off
:: Run as administrator. Removes the background task, shortcuts and firewall rule. DATA IS NOT DELETED.
schtasks /end /tn InvestmentTracker >nul 2>&1
schtasks /delete /tn InvestmentTracker /f
del "%PUBLIC%\Desktop\Investment Tracker.lnk" >nul 2>&1
del "%ProgramData%\Microsoft\Windows\Start Menu\Programs\Investment Tracker.lnk" >nul 2>&1
netsh advfirewall firewall delete rule name="Investment Tracker" >nul 2>&1
echo Done. The folder C:\InvestmentTracker (including your data) was left untouched.
pause

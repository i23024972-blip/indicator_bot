@echo off
REM Daily IDX konglo scanner — launched by Windows Task Scheduler on weekdays.
REM Runs after the IDX close and appends output to a log.
cd /d D:\indicator_bot
set PY="C:\Users\lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
echo ================================================== >> idx_scan.log
echo Run: %DATE% %TIME% >> idx_scan.log
%PY% idx_scan.py >> idx_scan.log 2>&1
echo. >> idx_scan.log

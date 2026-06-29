@echo off
REM Daily "waking up" radar — launched by Windows Task Scheduler on weekdays after close.
REM Scans the broad IDX universe for stocks waking up (turnover surging off a quiet base).
cd /d D:\indicator_bot
set PY="C:\Users\lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
echo ================================================== >> idx_radar.log
echo Run: %DATE% %TIME% >> idx_radar.log
%PY% idx_radar.py >> idx_radar.log 2>&1
echo. >> idx_radar.log

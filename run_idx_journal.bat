@echo off
REM Telegram trade-journal listener — launched at logon by Task Scheduler.
REM Runs continuously while you're logged in; logs trades you type to @ususkonglobot.
cd /d D:\indicator_bot
set PY="C:\Users\lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
:loop
%PY% idx_journal.py >> idx_journal.log 2>&1
REM if it ever crashes, wait 15s and restart so the journal stays available
timeout /t 15 /nobreak >nul
goto loop

@echo off
REM Loads MIS registers into the Supabase database.
REM Double-click to run, or point Windows Task Scheduler at this file for a daily refresh.
cd /d "%~dp0"
python "%~dp0load_register.py" %*
echo.
type "%~dp0logs\last_run_status.txt"
echo.
if "%~1"=="" pause

@echo off
REM Loads MIS registers into SQL Server database [Register].
REM Double-click to run, or point Windows Task Scheduler at this file for a daily refresh.
cd /d "%~dp0"
"F:\HR Assistant\.venv\Scripts\python.exe" "%~dp0load_register.py" %*
echo.
type "%~dp0logs\last_run_status.txt"
echo.
if "%~1"=="" pause

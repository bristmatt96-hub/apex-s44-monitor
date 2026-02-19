@echo off
REM =====================================================
REM  European Filing Monitor -- Scheduled Task Runner
REM  Runs every 15 minutes via Windows Task Scheduler
REM =====================================================

cd /d C:\Users\toget\apex-s44-monitor

REM Ensure output directory exists
if not exist "outputs" mkdir outputs

REM Timestamp for log
echo. >> outputs\monitor_log.txt
echo ============================================== >> outputs\monitor_log.txt
echo  Monitor run: %date% %time% >> outputs\monitor_log.txt
echo ============================================== >> outputs\monitor_log.txt

REM Run the European filing monitor (1-day lookback)
"C:\Program Files\Python310\python.exe" -m monitors.european_monitor --days 1 >> outputs\monitor_log.txt 2>&1

echo  Exit code: %errorlevel% >> outputs\monitor_log.txt
echo ============================================== >> outputs\monitor_log.txt

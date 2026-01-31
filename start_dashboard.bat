@echo off
echo ========================================
echo        Trading Dashboard Startup
echo ========================================
echo.

cd /d C:\Users\toget\apex-s44-monitor

echo Syncing latest code...
git pull origin claude/test-powershell-trading-app-V06kG

echo.
echo Starting dashboard...
echo.
echo Dashboard will open at: http://localhost:8501
echo Press Ctrl+C to stop
echo.

py -m streamlit run dashboard/app.py

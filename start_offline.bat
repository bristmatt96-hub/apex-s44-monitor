@echo off
echo ========================================
echo     Trading Dashboard (Offline Mode)
echo ========================================
echo.

cd /d C:\Users\toget\apex-s44-monitor

echo Starting dashboard...
echo Dashboard: http://localhost:8501
echo Press Ctrl+C to stop
echo.

py -m streamlit run dashboard/app.py

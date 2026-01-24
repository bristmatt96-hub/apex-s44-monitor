@echo off
REM ============================================================================
REM APEX S44 Monitor - Windows Setup Script
REM Run this on Windows to get everything working
REM ============================================================================

echo ======================================
echo   APEX S44 Monitor - Windows Setup
echo ======================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Please install Python 3.10+ from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation!
    pause
    exit /b 1
)

echo Python found.
python --version
echo.

REM Create virtual environment
echo Setting up virtual environment...
if not exist "venv" (
    python -m venv venv
    echo Created virtual environment
)

REM Activate virtual environment
call venv\Scripts\activate.bat
echo Activated virtual environment
echo.

REM Upgrade pip
python -m pip install --upgrade pip

REM Install core requirements
echo Installing core dependencies...
pip install -r requirements.txt

REM Install transcription tools
echo.
echo Installing transcription tools...
pip install openai-whisper
pip install deepgram-sdk

REM ffmpeg instructions
echo.
echo ======================================
echo   FFMPEG INSTALLATION REQUIRED
echo ======================================
echo.
echo For transcription, you need ffmpeg:
echo.
echo Option 1 - Chocolatey (recommended):
echo   choco install ffmpeg
echo.
echo Option 2 - Manual:
echo   1. Download from: https://ffmpeg.org/download.html
echo   2. Extract to C:\ffmpeg
echo   3. Add C:\ffmpeg\bin to your PATH
echo.

REM Audio setup for LIVE transcription
echo.
echo ======================================
echo   AUDIO SETUP FOR LIVE TRANSCRIPTION
echo ======================================
echo.
echo To capture earnings call audio:
echo.
echo Option 1 - Stereo Mix (built-in, if available):
echo   1. Right-click speaker icon ^> Sound settings
echo   2. Sound Control Panel ^> Recording tab
echo   3. Right-click ^> Show Disabled Devices
echo   4. Enable "Stereo Mix"
echo.
echo Option 2 - VB-Cable (free virtual audio):
echo   Download from: https://vb-audio.com/Cable/
echo.

REM Create .env template
if not exist ".env" (
    echo Creating .env template...
    (
        echo # API Keys - Fill these in
        echo # Get from: https://platform.openai.com/api-keys
        echo OPENAI_API_KEY=
        echo.
        echo # Get from: https://console.deepgram.com
        echo DEEPGRAM_API_KEY=
        echo.
        echo # Get from: https://developer.twitter.com
        echo TWITTER_BEARER_TOKEN=
        echo.
        echo # Telegram Bot ^(optional^)
        echo TELEGRAM_BOT_TOKEN=
        echo TELEGRAM_CHAT_ID=
    ) > .env
    echo Created .env - fill in your API keys!
)

REM Test installation
echo.
echo ======================================
echo   TESTING INSTALLATION
echo ======================================
python -c "import streamlit; print(f'Streamlit {streamlit.__version__} OK')"
python -c "import pandas; print(f'Pandas {pandas.__version__} OK')"
python -c "import openai; print('OpenAI OK')"

echo.
echo ======================================
echo   SETUP COMPLETE!
echo ======================================
echo.
echo To start the monitor:
echo.
echo   venv\Scripts\activate.bat
echo   streamlit run apex_monitor.py
echo.
echo To sync with GitHub:
echo.
echo   git pull origin main
echo   git add .
echo   git commit -m "Update"
echo   git push origin main
echo.
echo Access at: http://localhost:8501
echo.

pause

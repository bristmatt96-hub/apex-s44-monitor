#!/bin/bash
# ============================================================================
# APEX S44 Monitor - MacBook Setup Script
# Run this on your Mac to get everything working
# ============================================================================

set -e  # Exit on error

echo "======================================"
echo "  APEX S44 Monitor - Mac Setup"
echo "======================================"
echo ""

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Check Python version
echo "Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "Installing Python 3..."
    brew install python@3.11
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "Python version: $PYTHON_VERSION"

# Create virtual environment
echo ""
echo "Setting up virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Created virtual environment"
fi

# Activate virtual environment
source venv/bin/activate
echo "Activated virtual environment"

# Upgrade pip
pip install --upgrade pip

# Install core requirements
echo ""
echo "Installing core dependencies..."
pip install -r requirements.txt

# Install transcription dependencies
echo ""
echo "Installing transcription tools..."

# ffmpeg for audio processing
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
fi

# OpenAI Whisper for local transcription (optional but recommended)
echo "Installing OpenAI Whisper (local transcription)..."
pip install openai-whisper

# Deepgram for live transcription
echo "Installing Deepgram SDK (live transcription)..."
pip install deepgram-sdk

# BlackHole for system audio capture (for LIVE transcription)
echo ""
echo "======================================"
echo "  AUDIO SETUP FOR LIVE TRANSCRIPTION"
echo "======================================"
echo ""
echo "To capture earnings call audio for LIVE transcription, install BlackHole:"
echo ""
echo "  brew install blackhole-2ch"
echo ""
echo "Then configure in System Settings > Sound:"
echo "  1. Create Multi-Output Device in Audio MIDI Setup"
echo "  2. Include BlackHole 2ch + your speakers"
echo "  3. Set as output device"
echo ""

# Create .env template if not exists
if [ ! -f ".env" ]; then
    echo "Creating .env template..."
    cat > .env << 'EOF'
# API Keys - Fill these in
# Get from: https://platform.openai.com/api-keys
OPENAI_API_KEY=

# Get from: https://console.deepgram.com (free tier available)
DEEPGRAM_API_KEY=

# Get from: https://developer.twitter.com
TWITTER_BEARER_TOKEN=

# Telegram Bot (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
    echo "Created .env - fill in your API keys!"
fi

# Test the installation
echo ""
echo "======================================"
echo "  TESTING INSTALLATION"
echo "======================================"
python3 -c "import streamlit; print(f'Streamlit {streamlit.__version__} OK')"
python3 -c "import pandas; print(f'Pandas {pandas.__version__} OK')"
python3 -c "import openai; print('OpenAI OK')"

echo ""
echo "======================================"
echo "  SETUP COMPLETE!"
echo "======================================"
echo ""
echo "To start the monitor:"
echo ""
echo "  source venv/bin/activate"
echo "  streamlit run apex_monitor.py"
echo ""
echo "To sync with GitHub:"
echo ""
echo "  git pull origin main     # Get latest changes"
echo "  git add ."
echo "  git commit -m 'Update'"
echo "  git push origin main     # Push your changes"
echo ""
echo "Access at: http://localhost:8501"
echo ""

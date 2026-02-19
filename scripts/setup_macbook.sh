#!/bin/bash
# MacBook Setup Script for Credit Catalyst
# Run this after cloning the repo on your MacBook

set -e

echo "🍎 Setting up Credit Catalyst on MacBook..."
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Install it first:"
    echo "   brew install python3"
    exit 1
fi

echo "✓ Python3 found: $(python3 --version)"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate
echo "✓ Virtual environment activated"

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "✓ Dependencies installed"

# Check for .env file
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  No .env file found!"
    echo ""
    echo "Option 1: Copy from VPS"
    echo "   ssh root@157.245.36.127 'cat /root/apex-s44-monitor/.env' > .env"
    echo ""
    echo "Option 2: Create manually with these keys:"
    cat << 'EOF'
# .env template
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
IB_HOST=127.0.0.1
IB_PORT=4002
IB_CLIENT_ID=1
EOF
    echo ""
else
    echo "✓ .env file exists"
fi

echo ""
echo "=========================================="
echo "✅ Setup complete!"
echo "=========================================="
echo ""
echo "To run the system:"
echo "   source venv/bin/activate"
echo "   python main.py"
echo ""
echo "To run in dev mode (no IB connection):"
echo "   DRY_RUN=true python main.py"
echo ""
echo "Workflow:"
echo "   1. Make changes on MacBook"
echo "   2. git add -A && git commit -m 'message' && git push"
echo "   3. On VPS: cd /root/apex-s44-monitor && git pull"
echo "   4. On VPS: sudo systemctl restart trading-system"
echo ""

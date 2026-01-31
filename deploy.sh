#!/bin/bash
# ===========================================
# One-Click Deploy to Digital Ocean
# ===========================================
# Run this on your Digital Ocean droplet:
# curl -sSL https://raw.githubusercontent.com/bristmatt96-hub/apex-s44-monitor/claude/test-powershell-trading-app-V06kG/deploy.sh | bash

set -e

echo "=========================================="
echo "   Trading System - Digital Ocean Deploy"
echo "=========================================="
echo ""

# Check if docker is installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    sudo systemctl enable docker
    sudo systemctl start docker
fi

# Check if docker-compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

# Create app directory
APP_DIR="/opt/trading-system"
echo "Setting up in $APP_DIR..."
sudo mkdir -p $APP_DIR
cd $APP_DIR

# Clone or update repo
if [ -d ".git" ]; then
    echo "Updating existing installation..."
    git pull origin claude/test-powershell-trading-app-V06kG
else
    echo "Cloning repository..."
    git clone -b claude/test-powershell-trading-app-V06kG https://github.com/bristmatt96-hub/apex-s44-monitor.git .
fi

# Check for .env file
if [ ! -f ".env" ]; then
    echo ""
    echo "=========================================="
    echo "  SETUP REQUIRED: Create .env file"
    echo "=========================================="
    echo ""
    echo "Copy and edit the environment file:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
    echo "At minimum, set these for Telegram alerts:"
    echo "  TELEGRAM_BOT_TOKEN=your_bot_token"
    echo "  TELEGRAM_CHAT_ID=your_chat_id"
    echo ""
    echo "Then run: docker-compose up -d"
    exit 0
fi

# Start services
echo ""
echo "Starting 24/7 Market Watcher..."
docker-compose up -d market-watcher

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "Market Watcher is now running 24/7"
echo ""
echo "Useful commands:"
echo "  View logs:     docker-compose logs -f market-watcher"
echo "  Stop:          docker-compose down"
echo "  Restart:       docker-compose restart market-watcher"
echo "  Update:        git pull && docker-compose up -d --build"
echo ""
echo "Optional - Start dashboard (port 8501):"
echo "  docker-compose up -d dashboard"
echo ""

#!/bin/bash
# ============================================
# VPS Setup Script for Trading System
# Run this on a fresh Ubuntu 22.04+ VPS
# ============================================

set -e

echo "=========================================="
echo "  Trading System VPS Setup"
echo "=========================================="

# Update system
echo "[1/6] Updating system..."
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
echo "[2/6] Installing Python and tools..."
sudo apt install -y python3 python3-pip python3-venv git screen htop ffmpeg

# Install TA-Lib (required for technical analysis)
echo "[3/6] Installing TA-Lib..."
sudo apt install -y build-essential wget
cd /tmp
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make
sudo make install
cd ~

# Clone repository
echo "[4/6] Cloning repository..."
cd ~
if [ -d "apex-s44-monitor" ]; then
    cd apex-s44-monitor
    git pull
else
    git clone https://github.com/bristmatt96-hub/apex-s44-monitor.git
    cd apex-s44-monitor
fi

# Create virtual environment
echo "[5/6] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create .env from example
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env file - EDIT THIS WITH YOUR API KEYS!"
fi

# Install systemd service
echo "[6/6] Installing systemd service..."
sudo cp deploy/trading-system.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable trading-system

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit your .env file:  nano ~/apex-s44-monitor/.env"
echo "2. Start the service:    sudo systemctl start trading-system"
echo "3. Check status:         sudo systemctl status trading-system"
echo "4. View logs:            sudo journalctl -u trading-system -f"
echo ""
echo "To run manually instead:"
echo "  cd ~/apex-s44-monitor"
echo "  source venv/bin/activate"
echo "  python main.py --scan"
echo ""

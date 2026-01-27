#!/bin/bash
# ============================================
# Install all systemd services for APEX Trading
# Run from the project root: bash deploy/install-services.sh
# ============================================

set -e

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$DEPLOY_DIR")"

echo "=========================================="
echo "  Installing APEX Trading Services"
echo "=========================================="

# Copy service files
echo "[1/4] Copying service files..."
sudo cp "$DEPLOY_DIR/xvfb.service" /etc/systemd/system/
sudo cp "$DEPLOY_DIR/ibgateway.service" /etc/systemd/system/
sudo cp "$DEPLOY_DIR/trading-system.service" /etc/systemd/system/

# Reload systemd
echo "[2/4] Reloading systemd..."
sudo systemctl daemon-reload

# Enable services (start on boot)
echo "[3/4] Enabling services..."
sudo systemctl enable xvfb
sudo systemctl enable ibgateway
sudo systemctl enable trading-system

echo "[4/4] Done!"

echo ""
echo "=========================================="
echo "  Services Installed"
echo "=========================================="
echo ""
echo "Start all services (in order):"
echo "  sudo systemctl start xvfb"
echo "  sudo systemctl start ibgateway"
echo "  sudo systemctl start trading-system"
echo ""
echo "Or start everything at once:"
echo "  sudo systemctl start xvfb && sleep 2 && sudo systemctl start ibgateway && sleep 30 && sudo systemctl start trading-system"
echo ""
echo "Check status:"
echo "  sudo systemctl status xvfb ibgateway trading-system"
echo ""
echo "View trading logs:"
echo "  sudo journalctl -u trading-system -f"
echo ""
echo "Stop everything:"
echo "  sudo systemctl stop trading-system ibgateway xvfb"
echo ""

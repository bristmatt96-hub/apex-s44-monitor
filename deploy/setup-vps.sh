#!/bin/bash
# VPS Setup Script for APEX Dashboard
# Run on the VPS: bash setup-vps.sh

set -e

echo "=== Setting up APEX Dashboard on VPS ==="

# Create dashboard systemd service
echo "Creating dashboard service..."
cat > /etc/systemd/system/dashboard.service << 'EOF'
[Unit]
Description=APEX Trading Dashboard API
After=trading-system.service network-online.target
Wants=trading-system.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/apex-s44-monitor
Environment="PATH=/root/apex-s44-monitor/venv/bin"
ExecStart=/root/apex-s44-monitor/venv/bin/uvicorn dashboard.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the dashboard service
systemctl daemon-reload
systemctl enable dashboard
systemctl start dashboard

echo ""
echo "=== Setup Complete ==="
echo "Dashboard API: http://$(curl -s ifconfig.me):8000"
echo ""
echo "To check status: systemctl status dashboard"
echo "To view logs: journalctl -u dashboard -f"

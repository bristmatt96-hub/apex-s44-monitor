#!/bin/bash
# VPS Setup Script for Credit Catalyst
# Run on the VPS: bash setup-vps.sh

set -e

echo "=== Setting up Credit Catalyst on VPS ==="

# Create dashboard systemd service
echo "Creating Credit Catalyst API service..."
cat > /etc/systemd/system/credit-catalyst.service << 'EOF'
[Unit]
Description=Credit Catalyst API
After=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/apex-s44-monitor
Environment="PATH=/root/apex-s44-monitor/venv/bin"
ExecStart=/root/apex-s44-monitor/venv/bin/uvicorn app.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the service
systemctl daemon-reload
systemctl enable credit-catalyst
systemctl start credit-catalyst

echo ""
echo "=== Setup Complete ==="
echo "Credit Catalyst API: http://$(curl -s ifconfig.me):8000"
echo ""
echo "To check status: systemctl status credit-catalyst"
echo "To view logs: journalctl -u credit-catalyst -f"

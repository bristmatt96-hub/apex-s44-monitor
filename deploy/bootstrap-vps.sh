#!/bin/bash
# ============================================
# APEX Trading System — Fresh VPS Bootstrap
# SSH into 143.198.56.117 and run:
#   curl -sL https://raw.githubusercontent.com/bristmatt96-hub/apex-s44-monitor/main/deploy/bootstrap-vps.sh | bash
# OR copy this file over and run: bash bootstrap-vps.sh
# ============================================
set -e

echo "=========================================="
echo "  APEX Trading System — VPS Bootstrap"
echo "  Droplet: 143.198.56.117"
echo "=========================================="

# ---- 1. System packages ----
echo ""
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    git nginx certbot python3-certbot-nginx \
    xvfb scrot curl unzip jq \
    default-jre \
    > /dev/null 2>&1
echo "  Done."

# ---- 2. Clone repo ----
echo ""
echo "[2/7] Cloning repo..."
REPO_DIR="/root/apex-s44-monitor"
if [ -d "$REPO_DIR" ]; then
    echo "  Repo already exists, pulling latest..."
    cd "$REPO_DIR"
    git pull origin main || true
else
    git clone https://github.com/bristmatt96-hub/apex-s44-monitor.git "$REPO_DIR"
    cd "$REPO_DIR"
fi
echo "  Done."

# ---- 3. Python venv + deps ----
echo ""
echo "[3/7] Setting up Python environment..."
if [ ! -d "$REPO_DIR/venv" ]; then
    python3 -m venv "$REPO_DIR/venv"
fi
source "$REPO_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$REPO_DIR/requirements.txt" -q 2>/dev/null || {
    echo "  Some packages failed — installing core deps only..."
    pip install -q fastapi uvicorn websockets python-dotenv pydantic httpx aiohttp \
        pandas numpy requests yfinance scikit-learn xgboost \
        ib_insync anthropic schedule loguru scipy
}
echo "  Done."

# ---- 4. .env file ----
echo ""
echo "[4/7] Checking .env..."
if [ ! -f "$REPO_DIR/.env" ]; then
    echo "  Creating .env from template — YOU MUST EDIT THIS!"
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    echo "  *** IMPORTANT: Edit /root/apex-s44-monitor/.env with your keys ***"
    echo "  nano /root/apex-s44-monitor/.env"
    echo ""
else
    echo "  .env already exists."
fi

# ---- 5. Install systemd services ----
echo ""
echo "[5/7] Installing systemd services..."

# Xvfb
cp "$REPO_DIR/deploy/xvfb.service" /etc/systemd/system/
# IB Gateway
cp "$REPO_DIR/deploy/ibgateway.service" /etc/systemd/system/
# Trading system
cp "$REPO_DIR/deploy/trading-system.service" /etc/systemd/system/

# Dashboard API service
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
EnvironmentFile=/root/apex-s44-monitor/.env
ExecStart=/root/apex-s44-monitor/venv/bin/uvicorn dashboard.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable xvfb ibgateway trading-system dashboard
echo "  Done."

# ---- 6. nginx + HTTPS ----
echo ""
echo "[6/7] Setting up nginx..."

cat > /etc/nginx/sites-available/dashboard << 'NGINX'
server {
    listen 80;
    server_name app.mb-trading.co.uk;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX

ln -sf /etc/nginx/sites-available/dashboard /etc/nginx/sites-enabled/dashboard
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl restart nginx
echo "  Done."

echo ""
echo "  To add HTTPS (after DNS points app.mb-trading.co.uk → 143.198.56.117):"
echo "    certbot --nginx -d app.mb-trading.co.uk"

# ---- 7. IBC (IB Gateway controller) ----
echo ""
echo "[7/7] Checking IBC..."
if [ ! -d "/root/ibc" ]; then
    echo "  IBC not found. Download it:"
    echo "    mkdir -p /root/ibc"
    echo "    # Get IBC from https://github.com/IbcAlpha/IBC/releases"
    echo "    # Get IB Gateway from https://www.interactivebrokers.com/en/trading/ibgateway-stable.php"
    echo "    # Then configure /root/ibc/config.ini with your IBKR credentials"
else
    echo "  IBC directory exists."
fi

echo ""
echo "=========================================="
echo "  Bootstrap Complete!"
echo "=========================================="
echo ""
echo "NEXT STEPS:"
echo ""
echo "  1. Edit .env with your API keys:"
echo "     nano /root/apex-s44-monitor/.env"
echo ""
echo "  2. Set up IBC + IB Gateway (if not done):"
echo "     - Download IBC + IB Gateway"
echo "     - Configure /root/ibc/config.ini"
echo ""
echo "  3. Update GoDaddy DNS:"
echo "     app.mb-trading.co.uk  A  143.198.56.117"
echo ""
echo "  4. Get HTTPS cert (after DNS propagates):"
echo "     certbot --nginx -d app.mb-trading.co.uk"
echo ""
echo "  5. Start everything:"
echo "     systemctl start xvfb"
echo "     sleep 2"
echo "     systemctl start ibgateway"
echo "     sleep 30"
echo "     systemctl start trading-system"
echo "     systemctl start dashboard"
echo ""
echo "  6. Verify:"
echo "     systemctl status xvfb ibgateway trading-system dashboard"
echo "     curl http://localhost:8000/api/health"
echo ""

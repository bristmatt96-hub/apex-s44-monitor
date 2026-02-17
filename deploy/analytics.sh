#!/bin/bash
# ============================================
# APEX S44 Analytics Suite — Deploy Script
# Usage: bash deploy/analytics.sh
# ============================================
set -euo pipefail

REPO_DIR="/root/apex-s44-monitor"
VENV_DIR="$REPO_DIR/.venv-analytics"
PORT=5000

echo "=== APEX S44 Analytics Suite — Deploy ==="

# 1. Pull latest code
cd "$REPO_DIR"
git fetch origin claude/setup-workspace-W9eYq
git checkout claude/setup-workspace-W9eYq
git pull origin claude/setup-workspace-W9eYq

# 2. Set up virtualenv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtualenv..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 3. Install dependencies
pip install -q -r analytics/requirements.txt

# 4. Kill any existing analytics process
pkill -f "gunicorn.*analytics.app" 2>/dev/null || true
sleep 1

# 5. Start with gunicorn (production WSGI server)
echo "Starting gunicorn on 0.0.0.0:$PORT..."
cd "$REPO_DIR"
nohup gunicorn \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --timeout 120 \
    --access-logfile /tmp/analytics-access.log \
    --error-logfile /tmp/analytics-error.log \
    "analytics.app:app" > /dev/null 2>&1 &

sleep 2

# 6. Verify
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$PORT/ | grep -q 200; then
    echo ""
    echo "=== SUCCESS ==="
    echo "Analytics Suite is live at:"
    echo "  http://143.198.56.117:$PORT"
    echo ""
    echo "Logs: tail -f /tmp/analytics-access.log"
    echo "Stop: pkill -f 'gunicorn.*analytics.app'"
else
    echo "ERROR: App failed to start. Check /tmp/analytics-error.log"
    cat /tmp/analytics-error.log
    exit 1
fi

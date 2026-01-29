#!/bin/bash
# ============================================
# Quick monitoring script for APEX Trading System
# ============================================

echo "=========================================="
echo "  APEX Trading System Status"
echo "=========================================="
echo ""

# Service statuses
echo "--- Services ---"
for svc in xvfb ibgateway trading-system; do
    STATUS=$(systemctl is-active $svc 2>/dev/null || echo "not installed")
    if [ "$STATUS" = "active" ]; then
        echo "  $svc: RUNNING"
    else
        echo "  $svc: $STATUS"
    fi
done
echo ""

# IB Gateway connection
echo "--- IB Gateway ---"
if ss -tlnp | grep -q ':4002'; then
    echo "  Port 4002: LISTENING (paper trading)"
elif ss -tlnp | grep -q ':4001'; then
    echo "  Port 4001: LISTENING (live trading)"
else
    echo "  Port 4002: NOT LISTENING"
fi
echo ""

# Recent trading logs
echo "--- Recent Activity (last 15 lines) ---"
sudo journalctl -u trading-system -n 15 --no-pager 2>/dev/null || echo "  No logs available"
echo ""

# System resources
echo "--- System Resources ---"
echo "  CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}')% used"
echo "  RAM: $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
echo "  Disk: $(df -h / | awk 'NR==2 {print $3 "/" $2}')"
echo ""

#!/bin/bash
# ============================================
# Quick monitoring script
# ============================================

echo "=========================================="
echo "  Trading System Status"
echo "=========================================="
echo ""

# Service status
echo "Service Status:"
sudo systemctl status trading-system --no-pager | head -15
echo ""

# Recent logs
echo "Recent Activity (last 20 lines):"
echo "------------------------------------------"
sudo journalctl -u trading-system -n 20 --no-pager
echo ""

# System resources
echo "System Resources:"
echo "------------------------------------------"
echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}')% used"
echo "RAM: $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
echo "Disk: $(df -h / | awk 'NR==2 {print $3 "/" $2}')"
echo ""

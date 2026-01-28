#!/bin/bash
# ============================================
# APEX Trading System - Quick Reference
# Run: bash deploy/help.sh
# ============================================

cat << 'EOF'
==========================================
  APEX Trading System - Cheat Sheet
==========================================

--- Services ---
  Start all:      sudo systemctl start xvfb && sleep 2 && sudo systemctl start ibgateway && sleep 30 && sudo systemctl start trading-system
  Stop all:       sudo systemctl stop trading-system ibgateway xvfb
  Restart trading: sudo systemctl restart trading-system
  Status:         sudo systemctl status xvfb ibgateway trading-system

--- Logs ---
  Live logs:      sudo journalctl -u trading-system -f
  Last 50 lines:  sudo journalctl -u trading-system -n 50 --no-pager
  Gateway logs:   sudo journalctl -u ibgateway -n 50 --no-pager
  Today only:     sudo journalctl -u trading-system --since today --no-pager

--- Monitoring ---
  Full status:    bash deploy/monitor.sh
  IB port check:  ss -tlnp | grep 4002
  Screen list:    screen -ls

--- Manual Run ---
  Scan only:      cd /root/agentic-trader && source venv/bin/activate && python3 main.py --scan
  Full system:    cd /root/agentic-trader && source venv/bin/activate && python3 main.py

--- Git ---
  Pull updates:   cd /root/agentic-trader && git pull origin claude/setup-multi-agent-project-0URFA

--- Troubleshooting ---
  Gateway stuck:  sudo systemctl restart ibgateway
  No signals:     sudo journalctl -u trading-system -n 100 --no-pager | grep -i error
  Port not open:  sudo systemctl restart xvfb && sleep 2 && sudo systemctl restart ibgateway
  Kill everything: sudo systemctl stop trading-system ibgateway xvfb && pkill -f Xvfb && pkill -f java

EOF

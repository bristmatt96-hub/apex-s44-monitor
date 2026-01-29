#!/bin/bash
# APEX Trading System - Isolated Runner
# Runs the trading bot in its own virtual environment, separate from the monitoring tool

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv-trading"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  APEX Trading System - Isolated Mode  ${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating isolated virtual environment...${NC}"
    python3 -m venv "$VENV_DIR"

    echo -e "${YELLOW}Installing trading dependencies...${NC}"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    pip install -r "$SCRIPT_DIR/requirements-trading.txt"
else
    source "$VENV_DIR/bin/activate"
fi

echo -e "${GREEN}Virtual environment: $VENV_DIR${NC}"
echo -e "${GREEN}Python: $(which python)${NC}"
echo ""

# Parse arguments
ARGS=""
MODE="live"

while [[ $# -gt 0 ]]; do
    case $1 in
        --paper)
            ARGS="$ARGS --paper"
            MODE="paper"
            shift
            ;;
        --scan)
            ARGS="$ARGS --scan"
            MODE="scan-only"
            shift
            ;;
        --auto)
            echo -e "${RED}WARNING: Auto-execute mode enabled!${NC}"
            read -p "Are you sure? (yes/no): " confirm
            if [ "$confirm" = "yes" ]; then
                ARGS="$ARGS --auto"
            else
                echo "Auto-execute cancelled."
            fi
            shift
            ;;
        --config)
            ARGS="$ARGS --config"
            MODE="config"
            shift
            ;;
        --install)
            echo -e "${YELLOW}Reinstalling dependencies...${NC}"
            pip install -r "$SCRIPT_DIR/requirements-trading.txt"
            exit 0
            ;;
        --help)
            echo "Usage: ./run_trading.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --paper    Use paper trading (port 7497)"
            echo "  --scan     Run market scan only (no execution)"
            echo "  --auto     Enable auto-execution (DANGEROUS)"
            echo "  --config   Show current configuration"
            echo "  --install  Reinstall dependencies"
            echo "  --help     Show this help"
            exit 0
            ;;
        *)
            ARGS="$ARGS $1"
            shift
            ;;
    esac
done

echo -e "${GREEN}Mode: $MODE${NC}"
echo -e "${GREEN}Starting trading system...${NC}"
echo ""

# Run the trading system
cd "$SCRIPT_DIR"
python main.py $ARGS

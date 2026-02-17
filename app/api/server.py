#!/usr/bin/env python3
"""
Dashboard Server Runner

Starts the FastAPI dashboard server.
Can run standalone (with mock data) or connected to trading system.
"""
import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import uvicorn
from loguru import logger


def main():
    parser = argparse.ArgumentParser(description='APEX Trading Dashboard Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload')
    parser.add_argument('--mock', action='store_true', help='Use mock data (no trading system)')

    args = parser.parse_args()

    logger.info(f"Starting Dashboard API on {args.host}:{args.port}")

    if args.mock:
        logger.info("Running in MOCK mode - using simulated data")

    uvicorn.run(
        "dashboard.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()

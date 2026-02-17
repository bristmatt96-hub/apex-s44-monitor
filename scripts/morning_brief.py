#!/usr/bin/env python3
"""
Morning Brief Script

Generates and sends the daily morning brief via Telegram.
Designed to be run via cron at 7am UK time.

Cron example:
    0 7 * * 1-5 cd /path/to/credit-catalyst && python scripts/morning_brief.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.briefing import BriefingAgent
from loguru import logger


async def run():
    briefer = BriefingAgent()
    brief = await briefer.generate_morning_brief()

    # Print to stdout
    clean = brief.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    print(clean)

    # Send via Telegram
    sent = await briefer.send_morning_brief()
    if sent:
        logger.info("Morning brief sent via Telegram")
    else:
        logger.warning("Telegram send failed or not configured")


if __name__ == "__main__":
    asyncio.run(run())

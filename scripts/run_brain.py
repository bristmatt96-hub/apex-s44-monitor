#!/usr/bin/env python3
"""
Market Brain Runner

Runs the inefficiency detection engine independently.
Continuously scans for exploitable market inefficiencies and displays them.

Usage:
    python scripts/run_brain.py              # Run with console output
    python scripts/run_brain.py --telegram   # Also send to Telegram
    python scripts/run_brain.py --once       # Single scan, then exit
"""
import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from agents.brain import MarketBrain, get_market_brain
from agents.brain.inefficiency_scanners import (
    RetailCrowdingScanner,
    VolatilityMispricingScanner,
    TimeZoneGapScanner,
    LiquidityPatternScanner,
    ExogenousShockScanner,
    EuphoriaDetector,
    ProductDiscoveryScanner,
    GeopoliticalNewsScanner
)
from agents.brain.panic_risk_manager import get_panic_risk_manager

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)


async def run_brain(telegram: bool = False, once: bool = False):
    """Run the market brain"""

    print("""
╔══════════════════════════════════════════════════════════════╗
║                     MARKET BRAIN                             ║
║              Inefficiency Detection Engine                   ║
║                                                              ║
║  Philosophy: Find edges where algorithms CAN'T compete       ║
║  • Behavioral inefficiencies (human panic/greed)            ║
║  • Volatility mispricings                                    ║
║  • Time-based patterns (gaps, lunch dip, power hour)        ║
║  • Exogenous shocks (Trump headlines, etc.) → Recovery plays║
║  • Euphoria detection → Know when to take profits           ║
║  • Product discovery → Find new instruments that fit us     ║
║  • News scanner → China/US, war, geopolitical risks         ║
║                                                              ║
║  "Be fearful when others are greedy,                        ║
║   and greedy when others are fearful" - Buffett             ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Initialize brain
    brain = get_market_brain()

    # Initialize panic risk manager
    panic_rm = get_panic_risk_manager()

    # Register all scanners
    brain.register_scanner(RetailCrowdingScanner())
    brain.register_scanner(VolatilityMispricingScanner())
    brain.register_scanner(TimeZoneGapScanner())
    brain.register_scanner(LiquidityPatternScanner())

    # Exogenous shock scanner (Trump headlines, geopolitical events, etc.)
    shock_scanner = ExogenousShockScanner()
    brain.register_scanner(shock_scanner)

    # Euphoria detector (know when to take profits)
    euphoria_detector = EuphoriaDetector()
    brain.register_scanner(euphoria_detector)

    # Product discovery (find new instruments that fit our edge)
    product_scanner = ProductDiscoveryScanner()
    brain.register_scanner(product_scanner)

    # Geopolitical news scanner (China/US, war, tariffs, etc.)
    news_scanner = GeopoliticalNewsScanner()
    brain.register_scanner(news_scanner)

    logger.info(f"Brain initialized with {len(brain.scanners)} scanners")

    # Telegram notifier
    notifier = None
    if telegram:
        try:
            from utils.telegram_notifier import get_notifier
            notifier = get_notifier()
            logger.info("Telegram notifications enabled")
        except Exception as e:
            logger.warning(f"Telegram not available: {e}")

    if once:
        # Single scan mode
        logger.info("Running single scan...")
        for scanner in brain.scanners:
            try:
                ineffs = await scanner.scan()
                for ineff in ineffs:
                    brain._add_inefficiency(ineff)
            except Exception as e:
                logger.error(f"Scanner error: {e}")

        # Display results
        print("\n" + brain.format_dashboard())

        if notifier and brain.inefficiencies:
            await notifier.send_message(brain.get_telegram_message())

        return

    # Continuous mode
    logger.info("Starting continuous scanning (Ctrl+C to stop)")
    brain.running = True

    try:
        while brain.running:
            # Run scan cycle
            for scanner in brain.scanners:
                try:
                    ineffs = await scanner.scan()
                    for ineff in ineffs:
                        brain._add_inefficiency(ineff)
                except Exception as e:
                    logger.debug(f"Scanner error: {e}")

            # Clean expired
            brain._cleanup_expired()

            # Display dashboard
            print("\033[2J\033[H")  # Clear screen
            print(brain.format_dashboard())

            # Show panic status if active (BUY signal)
            panic_status = shock_scanner.get_panic_status()
            if panic_status.get('is_panic'):
                print(f"\n  🚨 PANIC MODE: VIX {panic_status['vix']:.1f} | SPY {panic_status['spy_drawdown']} from high")
                print("  → Be GREEDY when others are fearful - look for recovery plays")
                print(panic_rm.format_risk_rules())

            # Show greed status if active (SELL signal)
            greed_status = euphoria_detector.get_greed_status()
            if greed_status.get('is_greedy'):
                print(f"\n  🎰 GREED MODE: VIX {greed_status['vix']:.1f} | RSI {greed_status['rsi']}")
                print(f"  → Be FEARFUL when others are greedy - TAKE PROFITS")
                print(euphoria_detector.format_greed_rules())

            # Show geopolitical news risk status
            news_status = news_scanner.get_risk_status()
            if news_status.get('risk_level') not in ['NORMAL', None]:
                print(f"\n  📰 NEWS RISK: {news_status['risk_level']} ({news_status['recent_alerts']} alerts)")
                print(f"  → {news_status['action']}")

            # Show market sentiment summary
            if not panic_status.get('is_panic') and not greed_status.get('is_greedy'):
                print("\n  📊 MARKET SENTIMENT: Neutral - normal operations")

            print(f"\n  Scanners: {len(brain.scanners)} | Ideas Generated: {brain.ideas_generated}")
            print(f"  Press Ctrl+C to stop\n")

            # Send to Telegram (only on new high-score opportunities)
            if notifier:
                top = brain.get_top_inefficiencies(1)
                if top and top[0].score > 0.7:
                    await notifier.send_message(brain.get_telegram_message())

            await asyncio.sleep(30)  # Scan every 30 seconds

    except KeyboardInterrupt:
        logger.info("Stopping brain...")
        brain.running = False

    brain._save_history()
    logger.info("Brain stopped")


def main():
    parser = argparse.ArgumentParser(description='Market Brain - Inefficiency Detection')
    parser.add_argument('--telegram', action='store_true', help='Enable Telegram alerts')
    parser.add_argument('--once', action='store_true', help='Run single scan and exit')

    args = parser.parse_args()

    asyncio.run(run_brain(telegram=args.telegram, once=args.once))


if __name__ == '__main__':
    main()

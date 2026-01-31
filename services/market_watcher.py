"""
24/7 Market Watcher Service
Runs continuously in the background monitoring markets and sending alerts

This is the "always on" brain that:
- Scans for opportunities
- Monitors positions
- Sends Telegram alerts
- Learns from market data
"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, time
from loguru import logger
import schedule

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logger.add(
    "logs/market_watcher.log",
    rotation="1 day",
    retention="7 days",
    level="INFO"
)


class MarketWatcher:
    """24/7 Market Monitoring Service"""

    def __init__(self):
        self.running = False
        self.scan_interval_minutes = 5  # How often to scan
        self.last_scan = None

        # Market hours (US Eastern)
        self.market_open = time(9, 30)
        self.market_close = time(16, 0)
        self.pre_market_open = time(4, 0)
        self.after_hours_close = time(20, 0)

        # Load config
        self.config = self._load_config()

        # Initialize components
        self._init_components()

    def _load_config(self) -> dict:
        """Load watcher configuration"""
        config_file = Path("config/watcher_config.json")
        if config_file.exists():
            with open(config_file, 'r') as f:
                return json.load(f)
        return {
            "telegram_enabled": True,
            "scan_interval": 5,
            "watchlist": ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"],
            "alert_thresholds": {
                "price_change_pct": 2.0,
                "volume_spike_multiplier": 2.0
            }
        }

    def _init_components(self):
        """Initialize monitoring components"""
        logger.info("Initializing Market Watcher components...")

        # Try to import each scanner (may not all be available)
        self.scanners = {}

        try:
            from brain.geopolitical_news import GeopoliticalNewsScanner
            self.scanners['news'] = GeopoliticalNewsScanner()
            logger.info("  ✓ News Scanner loaded")
        except Exception as e:
            logger.warning(f"  ✗ News Scanner not available: {e}")

        try:
            from brain.euphoria_detector import EuphoriaDetector
            self.scanners['euphoria'] = EuphoriaDetector()
            logger.info("  ✓ Euphoria Detector loaded")
        except Exception as e:
            logger.warning(f"  ✗ Euphoria Detector not available: {e}")

        try:
            from brain.product_discovery import ProductDiscoveryScanner
            self.scanners['discovery'] = ProductDiscoveryScanner()
            logger.info("  ✓ Product Discovery Scanner loaded")
        except Exception as e:
            logger.warning(f"  ✗ Product Discovery not available: {e}")

        try:
            from portfolio.stop_monitor import get_stop_monitor
            self.stop_monitor = get_stop_monitor()
            logger.info("  ✓ Stop Monitor loaded")
        except Exception as e:
            logger.warning(f"  ✗ Stop Monitor not available: {e}")
            self.stop_monitor = None

        # Telegram notifier
        try:
            import os
            from dotenv import load_dotenv
            load_dotenv()

            # Check both naming conventions for Telegram credentials
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TRADE_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_TRADE_CHAT_ID")

            if bot_token and chat_id:
                from utils.telegram_notifier import TelegramNotifier
                self.telegram = TelegramNotifier(bot_token, chat_id)
                logger.info("  ✓ Telegram Notifier loaded")
            else:
                logger.warning("  ✗ Telegram not configured (missing bot token or chat ID)")
                self.telegram = None
        except Exception as e:
            logger.warning(f"  ✗ Telegram not available: {e}")
            self.telegram = None

    def is_market_hours(self) -> bool:
        """Check if currently in market hours"""
        now = datetime.now().time()
        return self.market_open <= now <= self.market_close

    def is_extended_hours(self) -> bool:
        """Check if in pre-market or after-hours"""
        now = datetime.now().time()
        return (self.pre_market_open <= now < self.market_open) or \
               (self.market_close < now <= self.after_hours_close)

    async def scan_markets(self):
        """Run all market scans"""
        logger.info(f"Running market scan at {datetime.now()}")
        self.last_scan = datetime.now()

        alerts = []

        # Run news scanner
        if 'news' in self.scanners:
            try:
                news_alerts = await self.scanners['news'].scan()
                if news_alerts:
                    alerts.extend(news_alerts)
                    logger.info(f"  News alerts: {len(news_alerts)}")
            except Exception as e:
                logger.error(f"News scan failed: {e}")

        # Run euphoria detector
        if 'euphoria' in self.scanners:
            try:
                euphoria_alerts = await self.scanners['euphoria'].scan()
                if euphoria_alerts:
                    alerts.extend(euphoria_alerts)
                    logger.info(f"  Euphoria alerts: {len(euphoria_alerts)}")
            except Exception as e:
                logger.error(f"Euphoria scan failed: {e}")

        # Run discovery scanner (less frequently)
        if 'discovery' in self.scanners and datetime.now().minute % 15 == 0:
            try:
                discovery_alerts = await self.scanners['discovery'].scan()
                if discovery_alerts:
                    alerts.extend(discovery_alerts)
                    logger.info(f"  Discovery alerts: {len(discovery_alerts)}")
            except Exception as e:
                logger.error(f"Discovery scan failed: {e}")

        # Check stops
        if self.stop_monitor:
            try:
                stop_alerts = await self.stop_monitor.check_all_stops()
                if stop_alerts:
                    alerts.extend(stop_alerts)
                    logger.info(f"  Stop alerts: {len(stop_alerts)}")
            except Exception as e:
                logger.error(f"Stop monitor failed: {e}")

        # Send alerts
        if alerts and self.telegram:
            await self._send_alerts(alerts)

        logger.info(f"Scan complete. {len(alerts)} total alerts.")
        return alerts

    async def _send_alerts(self, alerts: list):
        """Send alerts via Telegram"""
        for alert in alerts:
            try:
                message = self._format_alert(alert)
                if self.telegram:
                    await self.telegram.send_message(message)
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")

    def _format_alert(self, alert: dict) -> str:
        """Format alert for Telegram"""
        alert_type = alert.get('type', 'ALERT')
        symbol = alert.get('symbol', '')
        message = alert.get('message', '')

        emoji_map = {
            'news': '📰',
            'euphoria': '🔥',
            'discovery': '🔍',
            'stop': '🛑',
            'opportunity': '💡'
        }
        emoji = emoji_map.get(alert_type.lower(), '⚠️')

        return f"{emoji} **{alert_type.upper()}**\n{symbol}\n{message}"

    async def run_forever(self):
        """Main loop - runs 24/7"""
        logger.info("=" * 50)
        logger.info("Market Watcher Starting")
        logger.info(f"Scan interval: {self.scan_interval_minutes} minutes")
        logger.info("=" * 50)

        self.running = True

        # Send startup notification
        if self.telegram:
            try:
                await self.telegram.send_message(
                    "🟢 **Market Watcher Online**\n"
                    f"Scanning every {self.scan_interval_minutes} minutes\n"
                    f"Watchlist: {', '.join(self.config.get('watchlist', []))}"
                )
            except:
                pass

        while self.running:
            try:
                # During market hours: scan frequently
                if self.is_market_hours():
                    await self.scan_markets()
                    await asyncio.sleep(self.scan_interval_minutes * 60)

                # Extended hours: scan less frequently
                elif self.is_extended_hours():
                    await self.scan_markets()
                    await asyncio.sleep(self.scan_interval_minutes * 2 * 60)

                # Overnight: minimal scanning (news only)
                else:
                    # Just check news every 30 mins overnight
                    if 'news' in self.scanners:
                        try:
                            alerts = await self.scanners['news'].scan()
                            if alerts and self.telegram:
                                await self._send_alerts(alerts)
                        except:
                            pass
                    await asyncio.sleep(30 * 60)

            except KeyboardInterrupt:
                logger.info("Shutdown requested")
                self.running = False
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying

        logger.info("Market Watcher stopped")
        if self.telegram:
            try:
                await self.telegram.send_message("🔴 **Market Watcher Offline**")
            except:
                pass

    def stop(self):
        """Stop the watcher"""
        self.running = False


def main():
    """Entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="24/7 Market Watcher Service")
    parser.add_argument("--interval", type=int, default=5, help="Scan interval in minutes")
    args = parser.parse_args()

    watcher = MarketWatcher()
    watcher.scan_interval_minutes = args.interval

    # Create logs directory
    Path("logs").mkdir(exist_ok=True)

    # Run
    asyncio.run(watcher.run_forever())


if __name__ == "__main__":
    main()

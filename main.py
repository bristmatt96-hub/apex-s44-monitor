#!/usr/bin/env python3
"""
APEX Trading System - Multi-Agent Trading Bot
Aggressive risk/reward trading across all markets

Usage:
    python main.py              # Start the trading system
    python main.py --scan       # Run market scan only (no execution)
    python main.py --status     # Show system status
"""
import asyncio
import argparse
import signal
import sys
from datetime import datetime
from loguru import logger

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/trading_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG"
)

from config.settings import config
from agents.coordinator import Coordinator
from agents.scanners import EquityScanner, CryptoScanner, ForexScanner, OptionsScanner, EdgarInsiderScanner, OptionsFlowScanner
from agents.signals import TechnicalAnalyzer, MLPredictor, OpportunityRanker
from agents.execution import TradeExecutor


class TradingSystem:
    """Main trading system controller"""

    def __init__(self):
        self.coordinator = Coordinator()
        self.running = False

        # Initialize agents
        self._setup_agents()

    def _setup_agents(self):
        """Set up all trading agents"""
        # Market Scanners
        if config.scanner.equities_enabled:
            self.coordinator.register_agent(EquityScanner())

        if config.scanner.crypto_enabled:
            self.coordinator.register_agent(CryptoScanner())

        if config.scanner.forex_enabled:
            self.coordinator.register_agent(ForexScanner())

        if config.scanner.options_enabled:
            self.coordinator.register_agent(OptionsScanner())

        # Event-Driven Scanners
        self.coordinator.register_agent(EdgarInsiderScanner())

        # Flow-Based Scanners
        if config.scanner.options_enabled:
            self.coordinator.register_agent(OptionsFlowScanner())

        # Signal Processing
        self.coordinator.register_agent(TechnicalAnalyzer())
        self.coordinator.register_agent(MLPredictor())
        self.coordinator.register_agent(OpportunityRanker())

        # Execution
        self.coordinator.register_agent(TradeExecutor())

        logger.info(f"Registered {len(self.coordinator.agents)} agents")

    async def start(self, auto_execute: bool = False):
        """Start the trading system"""
        logger.info("=" * 60)
        logger.info("APEX Trading System Starting")
        logger.info(f"Capital: ${config.risk.starting_capital:,.2f}")
        logger.info(f"Max Position: {config.risk.max_position_pct:.0%}")
        logger.info(f"PDT Restricted: {config.pdt_restricted}")
        logger.info(f"Auto-Execute: {auto_execute}")
        logger.info("=" * 60)

        self.coordinator.set_auto_execute(auto_execute)
        self.running = True

        # Start all agents
        await self.coordinator.start_all_agents()

        logger.info("All agents started - System is LIVE")

        # Main loop
        try:
            while self.running:
                await asyncio.sleep(10)
                self._print_status()

        except asyncio.CancelledError:
            logger.info("Shutdown signal received")

        finally:
            await self.stop()

    async def stop(self):
        """Stop the trading system"""
        logger.info("Stopping trading system...")
        self.running = False
        await self.coordinator.stop_all_agents()
        logger.info("Trading system stopped")

    def _print_status(self):
        """Print current status"""
        status = self.coordinator.get_status()

        signals = status['signals']
        trading = status['trading']

        logger.info(
            f"Status: Signals[raw:{signals['raw']}, analyzed:{signals['analyzed']}, ranked:{signals['ranked']}] | "
            f"Positions: {trading['positions']} | "
            f"Pending: {trading['pending_executions']}"
        )

        # Show top opportunities
        top = self.coordinator.get_top_opportunities(3)
        if top:
            logger.info("Top Opportunities:")
            for opp in top:
                logger.info(
                    f"  #{opp['rank']} {opp['symbol']} ({opp['market_type']}) - "
                    f"Score: {opp['composite_score']:.2f}, R:R: {opp['risk_reward']:.1f}"
                )


async def run_scan_only():
    """Run a single market scan without trading"""
    logger.info("Running market scan (no execution)...")

    # Create scanners based on config
    scanners = []
    if config.scanner.equities_enabled:
        scanners.append(EquityScanner())
    if config.scanner.crypto_enabled:
        scanners.append(CryptoScanner())
    if config.scanner.forex_enabled:
        scanners.append(ForexScanner())
    if config.scanner.options_enabled:
        scanners.append(OptionsFlowScanner())
    scanners.append(EdgarInsiderScanner())  # Always included for insider signals

    all_signals = []

    for scanner in scanners:
        await scanner.start()
        await scanner.process()
        all_signals.extend(scanner.signals_generated)
        await scanner.stop()

    # Display results
    logger.info(f"\nScan complete - Found {len(all_signals)} signals:\n")

    for signal in sorted(all_signals, key=lambda s: s.risk_reward_ratio, reverse=True)[:10]:
        logger.info(
            f"{signal.symbol:12} | {signal.market_type.value:8} | "
            f"R:R: {signal.risk_reward_ratio:5.1f} | "
            f"Conf: {signal.confidence:.0%} | "
            f"Entry: ${signal.entry_price:.2f} | "
            f"Target: ${signal.target_price:.2f} | "
            f"Stop: ${signal.stop_loss:.2f}"
        )


def show_config():
    """Display current configuration"""
    print("\n" + "=" * 60)
    print("APEX Trading System Configuration")
    print("=" * 60)
    print(f"\nCapital: ${config.risk.starting_capital:,.2f}")
    print(f"Max Position Size: {config.risk.max_position_pct:.0%} (${config.risk.starting_capital * config.risk.max_position_pct:,.2f})")
    print(f"Max Positions: {config.risk.max_positions}")
    print(f"Max Daily Loss: {config.risk.max_daily_loss_pct:.0%}")
    print(f"\nPDT Restricted: {config.pdt_restricted}")
    print(f"Min Risk/Reward: {config.signals.min_risk_reward}:1")
    print(f"Min Confidence: {config.signals.min_confidence:.0%}")
    print(f"\nMarkets Enabled:")
    print(f"  - Equities: {config.scanner.equities_enabled}")
    print(f"  - Crypto: {config.scanner.crypto_enabled}")
    print(f"  - Forex: {config.scanner.forex_enabled}")
    print(f"  - Options: {config.scanner.options_enabled}")
    print(f"\nIB Connection:")
    print(f"  - Host: {config.ib.host}")
    print(f"  - Port: {config.ib.port} (TWS Live=7496, Paper=7497, Gateway=4001/4002)")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description='APEX Multi-Agent Trading System')
    parser.add_argument('--scan', action='store_true', help='Run market scan only (no execution)')
    parser.add_argument('--config', action='store_true', help='Show configuration')
    parser.add_argument('--auto', action='store_true', help='Enable auto-execution (DANGEROUS)')
    parser.add_argument('--paper', action='store_true', help='Use paper trading port (7497)')

    args = parser.parse_args()

    if args.config:
        show_config()
        return

    if args.paper:
        config.ib.port = 7497  # Paper trading

    if args.scan:
        asyncio.run(run_scan_only())
        return

    # Create and run trading system
    system = TradingSystem()

    # Handle shutdown gracefully
    def signal_handler(sig, frame):
        logger.info("Interrupt received, shutting down...")
        system.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run
    try:
        asyncio.run(system.start(auto_execute=args.auto))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

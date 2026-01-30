#!/usr/bin/env python3
"""
Portfolio Dashboard

Unified view of all portfolio management tools:
- Position Tracker / Portfolio Heat
- Trade Journal
- Stop Loss Monitor
- Earnings Calendar
- Options Greeks
- Performance Analytics

Usage:
    python scripts/run_portfolio.py                    # Full dashboard
    python scripts/run_portfolio.py --positions        # Positions only
    python scripts/run_portfolio.py --journal          # Trade journal
    python scripts/run_portfolio.py --stops            # Stop monitor
    python scripts/run_portfolio.py --earnings         # Earnings calendar
    python scripts/run_portfolio.py --greeks           # Options Greeks
    python scripts/run_portfolio.py --performance      # Performance analytics
    python scripts/run_portfolio.py --monitor          # Live monitoring mode
"""
import asyncio
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)


def print_banner():
    """Print dashboard banner"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                   PORTFOLIO DASHBOARD                        ║
║                                                              ║
║  Capital Preservation is Rule #1                             ║
║                                                              ║
║  "It's not about how much you make,                          ║
║   it's about how much you keep."                             ║
╚══════════════════════════════════════════════════════════════╝
    """)


async def show_positions():
    """Show position tracker dashboard"""
    from portfolio import get_position_tracker

    tracker = get_position_tracker()
    await tracker.refresh_prices()
    print(tracker.format_dashboard())


async def show_journal():
    """Show trade journal summary"""
    from portfolio import get_trade_journal

    journal = get_trade_journal()
    print(journal.format_journal_summary(days=30))


async def show_stops():
    """Show stop loss monitor"""
    from portfolio import get_stop_monitor

    monitor = get_stop_monitor()
    await monitor.check_all_positions()
    print(monitor.format_monitor_display())


async def show_earnings():
    """Show earnings calendar"""
    from portfolio import get_earnings_calendar

    calendar = get_earnings_calendar()
    await calendar.refresh_earnings()
    print(calendar.format_calendar_display())


async def show_greeks():
    """Show options Greeks dashboard"""
    from portfolio import get_options_greeks

    greeks = get_options_greeks()
    await greeks.refresh_greeks()
    print(greeks.format_greeks_dashboard())


async def show_performance():
    """Show performance analytics"""
    from portfolio import get_performance_analytics

    analytics = get_performance_analytics()
    print(analytics.format_performance_report(days=30))


async def show_full_dashboard():
    """Show complete portfolio dashboard"""
    from portfolio import (
        get_position_tracker,
        get_trade_journal,
        get_stop_monitor,
        get_performance_analytics
    )

    print_banner()

    # Positions
    tracker = get_position_tracker()
    await tracker.refresh_prices()
    print(tracker.format_dashboard())

    # Stop warnings
    monitor = get_stop_monitor()
    await monitor.check_all_positions()
    summary = monitor.get_stop_summary()
    if summary['warning_alerts'] > 0 or summary['critical_alerts'] > 0:
        print(monitor.format_monitor_display())

    # Performance snapshot
    analytics = get_performance_analytics()
    metrics = analytics.get_metrics(days=7)
    if metrics.total_trades > 0:
        print("\n  LAST 7 DAYS:")
        print(f"    Trades: {metrics.total_trades} | Win Rate: {metrics.win_rate:.0f}%")
        print(f"    P&L: ${metrics.total_pnl:+,.2f} | Expectancy: ${metrics.expectancy:+.2f}/trade")

    # Edge assessment
    edge = analytics.get_edge_assessment()
    edge_status = "EDGE CONFIRMED" if edge['has_edge'] else "NO EDGE YET"
    print(f"\n  Edge Status: {edge_status} ({edge['confidence']} confidence)")


async def run_monitor_mode(interval: int = 60):
    """Run continuous monitoring mode"""
    from portfolio import (
        get_position_tracker,
        get_stop_monitor,
        get_options_greeks
    )

    print_banner()
    print("Starting continuous monitoring mode...")
    print("Press Ctrl+C to stop\n")

    tracker = get_position_tracker()
    stop_monitor = get_stop_monitor()
    greeks = get_options_greeks()

    while True:
        try:
            # Refresh all
            await tracker.refresh_prices()
            alerts = await stop_monitor.check_all_positions()
            await greeks.refresh_greeks()

            # Clear and display
            print("\033[2J\033[H")  # Clear screen
            print_banner()

            # Positions summary
            print(tracker.format_dashboard())

            # Stop warnings
            if alerts:
                print("\n  ⚠️  STOP WARNINGS:")
                for alert in alerts[:3]:
                    print(f"    {alert.symbol}: {alert.distance_pct:.1f}% from stop")

            # Options warnings
            greeks_summary = greeks.get_portfolio_greeks_summary()
            if greeks_summary['positions_in_danger_zone'] > 0:
                print(f"\n  ⚠️  OPTIONS: {greeks_summary['positions_in_danger_zone']} positions in DTE danger zone")
                print(f"      Daily theta decay: -${greeks_summary['total_theta_daily']:.2f}")

            # Send Telegram alerts if needed
            if alerts:
                await stop_monitor.send_telegram_alerts()

            await asyncio.sleep(interval)

        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
            break
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description='Portfolio Dashboard')
    parser.add_argument('--positions', action='store_true', help='Show positions only')
    parser.add_argument('--journal', action='store_true', help='Show trade journal')
    parser.add_argument('--stops', action='store_true', help='Show stop loss monitor')
    parser.add_argument('--earnings', action='store_true', help='Show earnings calendar')
    parser.add_argument('--greeks', action='store_true', help='Show options Greeks')
    parser.add_argument('--performance', action='store_true', help='Show performance analytics')
    parser.add_argument('--monitor', action='store_true', help='Run continuous monitoring')
    parser.add_argument('--interval', type=int, default=60, help='Monitor interval (seconds)')

    args = parser.parse_args()

    if args.positions:
        asyncio.run(show_positions())
    elif args.journal:
        asyncio.run(show_journal())
    elif args.stops:
        asyncio.run(show_stops())
    elif args.earnings:
        asyncio.run(show_earnings())
    elif args.greeks:
        asyncio.run(show_greeks())
    elif args.performance:
        asyncio.run(show_performance())
    elif args.monitor:
        asyncio.run(run_monitor_mode(args.interval))
    else:
        asyncio.run(show_full_dashboard())


if __name__ == '__main__':
    main()

"""
Credit Catalyst Trading System - Main Entry Point

Monitors credit deterioration signals to identify equity options opportunities
before the market reprices credit risk into equity valuations.

Key Signal Sources:
1. SEC EDGAR filings (8-K covenant violations, NT late filings, 10-Q amendments)
2. Credit rating agency actions (downgrades, negative outlooks, watch placements)
3. Bond spread movements (CDS, corporate bond OAS widening)

Usage:
    python -m credit_catalyst.main --watchlist
    python -m credit_catalyst.main --monitor
    python -m credit_catalyst.main --add-company TICKER "Company Name"
"""

import argparse
import logging
import sys
from datetime import datetime

from .config.settings import settings
from .database.watchlist import WatchlistDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def setup_database() -> WatchlistDB:
    """Initialize database connection."""
    db = WatchlistDB(settings.database.path)
    logger.info(f"Database initialized at {settings.database.path}")
    return db


def show_watchlist(db: WatchlistDB):
    """Display current watchlist."""
    companies = db.get_active_watchlist()

    if not companies:
        print("\nWatchlist is empty. Add companies with --add-company")
        return

    print(f"\n{'='*70}")
    print("CREDIT CATALYST WATCHLIST")
    print(f"{'='*70}")
    print(f"{'Ticker':<10} {'Company':<30} {'Rating':<10} {'Priority':<10}")
    print(f"{'-'*70}")

    for company in companies:
        rating = company.get('current_rating') or 'N/A'
        priority_map = {1: 'Low', 2: 'Medium', 3: 'High'}
        priority = priority_map.get(company.get('priority', 1), 'Low')

        print(f"{company['ticker']:<10} {company['company_name'][:28]:<30} {rating:<10} {priority:<10}")

    # Stats
    stats = db.get_watchlist_stats()
    print(f"\n{'-'*70}")
    print(f"Total: {stats['total_companies']} companies | "
          f"IG: {stats['investment_grade']} | HY: {stats['high_yield']} | "
          f"Pending Alerts: {stats['pending_alerts']}")


def add_company(db: WatchlistDB, ticker: str, name: str, rating: str = None, cik: str = None):
    """Add a company to the watchlist."""
    try:
        company_id = db.add_company(
            ticker=ticker,
            company_name=name,
            current_rating=rating,
            cik=cik,
            priority=2  # Default medium priority
        )
        print(f"Added {ticker} ({name}) to watchlist [ID: {company_id}]")
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            print(f"Error: {ticker} is already in the watchlist")
        else:
            print(f"Error adding company: {e}")


def run_monitor(db: WatchlistDB):
    """Run the credit monitoring loop."""
    from .monitors.sec_monitor import SECFilingMonitor
    from .monitors.ratings_monitor import RatingsMonitor
    from .monitors.spreads_monitor import BondSpreadsMonitor

    print("\n" + "="*70)
    print("CREDIT CATALYST MONITOR - Starting")
    print("="*70)

    # Get watchlist
    ciks = db.get_watchlist_ciks()
    tickers = db.get_watchlist_tickers()

    if not tickers:
        print("No companies in watchlist. Add companies first.")
        return

    print(f"Monitoring {len(tickers)} companies: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")

    # Initialize monitors
    sec_monitor = SECFilingMonitor(ciks)
    ratings_monitor = RatingsMonitor(tickers)
    spreads_monitor = BondSpreadsMonitor(tickers)

    print("\nMonitors initialized:")
    print(f"  - SEC EDGAR Filing Monitor (CIKs: {len(ciks)})")
    print(f"  - Credit Ratings Monitor")
    print(f"  - Bond Spreads Monitor")

    # TODO: Implement monitoring loop with scheduling
    print("\n[Monitor loop not yet implemented - structure ready]")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Credit Catalyst Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --watchlist                     Show current watchlist
  %(prog)s --add-company AAPL "Apple Inc"  Add company to watchlist
  %(prog)s --add-company TSLA "Tesla Inc" --rating BBB- --cik 0001318605
  %(prog)s --monitor                        Start monitoring
        """
    )

    parser.add_argument('--watchlist', action='store_true',
                        help='Display current watchlist')
    parser.add_argument('--add-company', nargs=2, metavar=('TICKER', 'NAME'),
                        help='Add company to watchlist')
    parser.add_argument('--rating', type=str,
                        help='Credit rating for new company')
    parser.add_argument('--cik', type=str,
                        help='SEC CIK number for new company')
    parser.add_argument('--monitor', action='store_true',
                        help='Start monitoring loop')
    parser.add_argument('--init-db', action='store_true',
                        help='Initialize database only')

    args = parser.parse_args()

    # Initialize database
    db = setup_database()

    if args.init_db:
        print("Database initialized successfully.")
        return

    if args.add_company:
        ticker, name = args.add_company
        add_company(db, ticker, name, args.rating, args.cik)
        return

    if args.monitor:
        run_monitor(db)
        return

    # Default: show watchlist
    show_watchlist(db)


if __name__ == "__main__":
    main()

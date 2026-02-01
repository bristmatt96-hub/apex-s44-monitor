"""
Credit Catalyst Trading System

Monitors credit deterioration signals (SEC filings, rating downgrades,
bond spread moves) to identify equity options opportunities before
the market reprices.

Modules:
- monitors: SEC filings, ratings, bond spreads, news
- parsers: Extract actionable signals from raw data
- database: Watchlist and alert persistence
- alerts: Telegram notifications for trading opportunities
"""

__version__ = "0.1.0"
__author__ = "Credit Catalyst Team"

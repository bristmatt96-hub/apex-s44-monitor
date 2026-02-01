"""
Credit Catalyst Database

SQLite database for:
- Company watchlist management
- Filing history tracking
- Alert state persistence
- Trade opportunity logging
"""

from .watchlist import WatchlistDB

__all__ = ['WatchlistDB']

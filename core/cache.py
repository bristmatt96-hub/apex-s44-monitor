"""
Credit Catalyst - Data Cache

In-memory cache for market data, spread history, and computed analytics.
Reduces redundant API calls and provides fast access to frequently-used data.
"""

import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from loguru import logger


class DataCache:
    """
    Thread-safe singleton cache for credit market data.

    Stores:
    - CDS spread snapshots
    - Computed analytics (valuations, RV scores)
    - Knowledge base chunks
    - API responses with TTL
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._cache: Dict[str, Tuple[Any, datetime]] = {}
        self._default_ttl = timedelta(minutes=5)

    @classmethod
    def get_instance(cls) -> "DataCache":
        """Get or create singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def get(self, key: str) -> Optional[Any]:
        """Get a cached value if it exists and hasn't expired."""
        if key not in self._cache:
            return None

        value, cached_at = self._cache[key]
        if datetime.now() - cached_at > self._default_ttl:
            del self._cache[key]
            return None

        return value

    def set(self, key: str, value: Any, ttl: timedelta = None) -> None:
        """Set a cached value with optional TTL."""
        self._cache[key] = (value, datetime.now())
        if ttl:
            self._default_ttl = ttl

    def invalidate(self, key: str) -> None:
        """Remove a specific key from cache."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        logger.debug("Cache cleared")

    @property
    def size(self) -> int:
        """Number of items in cache."""
        return len(self._cache)


def get_cache() -> DataCache:
    """Convenience function to get the global cache instance."""
    return DataCache.get_instance()

"""
Shared Data Cache for Market Data

Centralized caching layer for yfinance data to:
- Prevent redundant API calls across agents
- Handle rate limiting centrally
- Reduce latency for frequently-accessed symbols
"""
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import pandas as pd
from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


class DataCache:
    """
    Thread-safe singleton cache for market data.

    Usage:
        cache = DataCache.get_instance()
        df = await cache.get_history('AAPL', 'equity', '3mo', '1d')
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        # Cache structure: {cache_key: (dataframe, fetch_time)}
        self._cache: Dict[str, Tuple[pd.DataFrame, datetime]] = {}
        self._cache_lock = asyncio.Lock()

        # Rate limiting
        self._last_fetch_time: Optional[datetime] = None
        self._min_fetch_interval = 0.5  # seconds between API calls
        self._rate_lock = asyncio.Lock()

        # Cache TTL settings by data type
        self._ttl_seconds = {
            'intraday': 60,      # 1 minute for intraday data
            'daily': 300,        # 5 minutes for daily data
            'options': 120,      # 2 minutes for options data
        }

        self._fetch_count = 0
        self._cache_hits = 0

    @classmethod
    def get_instance(cls) -> 'DataCache':
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    logger.info("DataCache singleton initialized")
        return cls._instance

    def _normalize_symbol(self, symbol: str, market_type: str) -> str:
        """Normalize symbol for yfinance based on market type."""
        if market_type == 'forex':
            # EUR/USD -> EURUSD=X
            clean = symbol.replace('/', '')
            if not clean.endswith('=X'):
                clean = f"{clean}=X"
            return clean
        elif market_type == 'crypto':
            # BTC/USDT -> BTC-USD
            clean = symbol.replace('/', '-').replace('USDT', 'USD').replace('usdt', 'usd')
            return clean
        else:
            # Equity - return as-is
            return symbol.upper()

    def _get_cache_key(self, symbol: str, market_type: str, period: str, interval: str) -> str:
        """Generate a unique cache key."""
        normalized = self._normalize_symbol(symbol, market_type)
        return f"{normalized}:{period}:{interval}"

    def _get_ttl(self, interval: str) -> int:
        """Get TTL in seconds based on data interval."""
        if interval in ('1m', '2m', '5m', '15m', '30m'):
            return self._ttl_seconds['intraday']
        return self._ttl_seconds['daily']

    def _is_expired(self, fetch_time: datetime, ttl_seconds: int) -> bool:
        """Check if cached data has expired."""
        return datetime.now() - fetch_time > timedelta(seconds=ttl_seconds)

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls."""
        async with self._rate_lock:
            if self._last_fetch_time is not None:
                elapsed = (datetime.now() - self._last_fetch_time).total_seconds()
                if elapsed < self._min_fetch_interval:
                    await asyncio.sleep(self._min_fetch_interval - elapsed)
            self._last_fetch_time = datetime.now()

    async def get_history(
        self,
        symbol: str,
        market_type: str = 'equity',
        period: str = '3mo',
        interval: str = '1d'
    ) -> Optional[pd.DataFrame]:
        """
        Get historical price data with caching.

        Args:
            symbol: The ticker symbol
            market_type: 'equity', 'forex', 'crypto', or 'options'
            period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)

        Returns:
            DataFrame with OHLCV data, or None if fetch fails
        """
        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available")
            return None

        cache_key = self._get_cache_key(symbol, market_type, period, interval)
        ttl = self._get_ttl(interval)

        # Check cache
        async with self._cache_lock:
            if cache_key in self._cache:
                df, fetch_time = self._cache[cache_key]
                if not self._is_expired(fetch_time, ttl):
                    self._cache_hits += 1
                    logger.debug(f"Cache hit for {cache_key} (hits: {self._cache_hits})")
                    return df.copy()

        # Cache miss - fetch from API
        await self._rate_limit()

        try:
            normalized_symbol = self._normalize_symbol(symbol, market_type)
            ticker = yf.Ticker(normalized_symbol)

            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: ticker.history(period=period, interval=interval)
            )

            self._fetch_count += 1

            if df is None or df.empty:
                logger.debug(f"No data returned for {normalized_symbol}")
                return None

            # Normalize column names
            df.columns = [c.lower() for c in df.columns]

            # Store in cache
            async with self._cache_lock:
                self._cache[cache_key] = (df.copy(), datetime.now())

            logger.debug(f"Fetched {normalized_symbol}: {len(df)} rows (total fetches: {self._fetch_count})")
            return df

        except (ConnectionError, ValueError, OSError) as e:
            logger.debug(f"Error fetching {symbol}: {e}")
            return None

    async def get_options_chain(
        self,
        symbol: str,
        expiration: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get options chain data with caching.

        Args:
            symbol: The underlying ticker symbol
            expiration: Optional specific expiration date (YYYY-MM-DD)

        Returns:
            Dict with 'calls' and 'puts' DataFrames, or None if fetch fails
        """
        if not YFINANCE_AVAILABLE:
            return None

        cache_key = f"options:{symbol.upper()}:{expiration or 'all'}"
        ttl = self._ttl_seconds['options']

        # Check cache
        async with self._cache_lock:
            if cache_key in self._cache:
                data, fetch_time = self._cache[cache_key]
                if not self._is_expired(fetch_time, ttl):
                    self._cache_hits += 1
                    return data

        # Fetch from API
        await self._rate_limit()

        try:
            ticker = yf.Ticker(symbol.upper())

            loop = asyncio.get_event_loop()

            if expiration:
                chain = await loop.run_in_executor(
                    None,
                    lambda: ticker.option_chain(expiration)
                )
                result = {
                    'calls': chain.calls,
                    'puts': chain.puts,
                    'expiration': expiration
                }
            else:
                # Get all expirations
                expirations = await loop.run_in_executor(
                    None,
                    lambda: ticker.options
                )
                if not expirations:
                    return None

                # Get first expiration chain
                chain = await loop.run_in_executor(
                    None,
                    lambda: ticker.option_chain(expirations[0])
                )
                result = {
                    'calls': chain.calls,
                    'puts': chain.puts,
                    'expirations': expirations,
                    'current_expiration': expirations[0]
                }

            self._fetch_count += 1

            # Store in cache
            async with self._cache_lock:
                self._cache[cache_key] = (result, datetime.now())

            return result

        except (ConnectionError, ValueError, OSError, KeyError) as e:
            logger.debug(f"Error fetching options for {symbol}: {e}")
            return None

    async def prefetch(
        self,
        symbols: list,
        market_type: str = 'equity',
        period: str = '3mo',
        interval: str = '1d'
    ) -> int:
        """
        Prefetch data for multiple symbols.

        Args:
            symbols: List of symbols to prefetch
            market_type: Market type for all symbols
            period: Data period
            interval: Data interval

        Returns:
            Number of symbols successfully fetched
        """
        success_count = 0
        for symbol in symbols:
            df = await self.get_history(symbol, market_type, period, interval)
            if df is not None and not df.empty:
                success_count += 1
        return success_count

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """Clear cache for a specific symbol or all cached data."""
        if symbol:
            keys_to_remove = [k for k in self._cache if k.startswith(symbol.upper())]
            for key in keys_to_remove:
                del self._cache[key]
            logger.debug(f"Cleared cache for {symbol} ({len(keys_to_remove)} entries)")
        else:
            count = len(self._cache)
            self._cache.clear()
            logger.debug(f"Cleared entire cache ({count} entries)")

    def get_stats(self) -> Dict:
        """Get cache statistics."""
        return {
            'cached_entries': len(self._cache),
            'total_fetches': self._fetch_count,
            'cache_hits': self._cache_hits,
            'hit_rate': self._cache_hits / (self._cache_hits + self._fetch_count) if (self._cache_hits + self._fetch_count) > 0 else 0
        }


# Convenience function for getting the singleton
def get_data_cache() -> DataCache:
    """Get the shared DataCache instance."""
    return DataCache.get_instance()

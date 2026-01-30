"""
Market Data Providers - Unified interface for multiple data sources.

Provides redundant market data fetching with automatic failover:
1. yfinance (primary - free, no API key, 2000 calls/hour)
2. Finnhub (backup - 60 calls/min free tier)
3. Twelve Data (backup - 800 calls/day free tier)

Usage:
    from data.market_data_providers import MarketDataProvider

    provider = MarketDataProvider()
    quote = await provider.get_quote("AAPL")
    candles = await provider.get_candles("AAPL", interval="1d", limit=100)
"""

import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import asyncio

# Try to import data libraries
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


@dataclass
class Quote:
    """Standardized quote data"""
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    timestamp: datetime
    source: str
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    prev_close: Optional[float] = None


@dataclass
class Candle:
    """OHLCV candle data"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class RateLimiter:
    """Simple rate limiter for API calls"""

    def __init__(self, calls_per_minute: int):
        self.calls_per_minute = calls_per_minute
        self.calls: List[float] = []

    def can_call(self) -> bool:
        """Check if we can make a call"""
        now = time.time()
        # Remove calls older than 1 minute
        self.calls = [t for t in self.calls if now - t < 60]
        return len(self.calls) < self.calls_per_minute

    def record_call(self):
        """Record a call"""
        self.calls.append(time.time())

    async def wait_if_needed(self):
        """Wait if rate limited"""
        while not self.can_call():
            await asyncio.sleep(1)


class FinnhubProvider:
    """
    Finnhub.io market data provider.

    Free tier: 60 API calls/minute
    Provides: Real-time quotes, candles, company info, news

    Get API key: https://finnhub.io/register
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY", "")
        self.rate_limiter = RateLimiter(60)  # 60 calls/min
        self.available = bool(self.api_key) and REQUESTS_AVAILABLE

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get real-time quote for a symbol"""
        if not self.available:
            return None

        await self.rate_limiter.wait_if_needed()

        try:
            response = requests.get(
                f"{self.BASE_URL}/quote",
                params={"symbol": symbol.upper(), "token": self.api_key},
                timeout=10
            )
            self.rate_limiter.record_call()

            if response.status_code != 200:
                return None

            data = response.json()

            # Finnhub returns: c (current), d (change), dp (change %), h, l, o, pc, t
            if data.get('c') is None or data['c'] == 0:
                return None

            return Quote(
                symbol=symbol.upper(),
                price=data['c'],
                change=data.get('d', 0) or 0,
                change_percent=data.get('dp', 0) or 0,
                volume=0,  # Not in quote endpoint
                timestamp=datetime.fromtimestamp(data.get('t', time.time())),
                source='finnhub',
                high=data.get('h'),
                low=data.get('l'),
                open=data.get('o'),
                prev_close=data.get('pc')
            )
        except Exception as e:
            return None

    async def get_candles(self, symbol: str, interval: str = "D",
                          limit: int = 100) -> Optional[List[Candle]]:
        """
        Get historical candles.

        Intervals: 1, 5, 15, 30, 60, D, W, M
        """
        if not self.available:
            return None

        await self.rate_limiter.wait_if_needed()

        # Calculate time range
        now = int(time.time())
        if interval == "D":
            from_time = now - (limit * 86400)
        elif interval == "W":
            from_time = now - (limit * 7 * 86400)
        elif interval == "M":
            from_time = now - (limit * 30 * 86400)
        else:
            # Intraday (minutes)
            minutes = int(interval) if interval.isdigit() else 60
            from_time = now - (limit * minutes * 60)

        try:
            response = requests.get(
                f"{self.BASE_URL}/stock/candle",
                params={
                    "symbol": symbol.upper(),
                    "resolution": interval,
                    "from": from_time,
                    "to": now,
                    "token": self.api_key
                },
                timeout=15
            )
            self.rate_limiter.record_call()

            if response.status_code != 200:
                return None

            data = response.json()

            if data.get('s') != 'ok':
                return None

            candles = []
            for i in range(len(data['t'])):
                candles.append(Candle(
                    timestamp=datetime.fromtimestamp(data['t'][i]),
                    open=data['o'][i],
                    high=data['h'][i],
                    low=data['l'][i],
                    close=data['c'][i],
                    volume=data['v'][i]
                ))

            return candles

        except Exception as e:
            return None


class TwelveDataProvider:
    """
    Twelve Data market data provider.

    Free tier: 800 API calls/day, 8 calls/minute
    Provides: Real-time & historical data, forex, crypto, technicals

    Get API key: https://twelvedata.com/account/api-keys
    """

    BASE_URL = "https://api.twelvedata.com"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("TWELVE_DATA_API_KEY", "")
        self.rate_limiter = RateLimiter(8)  # 8 calls/min on free tier
        self.available = bool(self.api_key) and REQUESTS_AVAILABLE
        self.daily_calls = 0
        self.daily_limit = 800
        self.last_reset = datetime.now().date()

    def _check_daily_limit(self) -> bool:
        """Check and reset daily limit"""
        today = datetime.now().date()
        if today > self.last_reset:
            self.daily_calls = 0
            self.last_reset = today
        return self.daily_calls < self.daily_limit

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get real-time quote"""
        if not self.available or not self._check_daily_limit():
            return None

        await self.rate_limiter.wait_if_needed()

        try:
            response = requests.get(
                f"{self.BASE_URL}/quote",
                params={"symbol": symbol.upper(), "apikey": self.api_key},
                timeout=10
            )
            self.rate_limiter.record_call()
            self.daily_calls += 1

            if response.status_code != 200:
                return None

            data = response.json()

            if 'code' in data:  # Error response
                return None

            return Quote(
                symbol=data.get('symbol', symbol.upper()),
                price=float(data.get('close', 0)),
                change=float(data.get('change', 0)),
                change_percent=float(data.get('percent_change', '0').rstrip('%')),
                volume=int(data.get('volume', 0)),
                timestamp=datetime.now(),
                source='twelve_data',
                high=float(data.get('high', 0)) if data.get('high') else None,
                low=float(data.get('low', 0)) if data.get('low') else None,
                open=float(data.get('open', 0)) if data.get('open') else None,
                prev_close=float(data.get('previous_close', 0)) if data.get('previous_close') else None
            )
        except Exception as e:
            return None

    async def get_candles(self, symbol: str, interval: str = "1day",
                          limit: int = 100) -> Optional[List[Candle]]:
        """
        Get historical time series.

        Intervals: 1min, 5min, 15min, 30min, 45min, 1h, 2h, 4h, 1day, 1week, 1month
        """
        if not self.available or not self._check_daily_limit():
            return None

        await self.rate_limiter.wait_if_needed()

        # Map common interval names
        interval_map = {
            "1d": "1day", "D": "1day", "d": "1day",
            "1w": "1week", "W": "1week",
            "1M": "1month", "M": "1month",
            "1h": "1h", "60": "1h",
            "5m": "5min", "5": "5min",
            "15m": "15min", "15": "15min",
            "30m": "30min", "30": "30min",
        }
        interval = interval_map.get(interval, interval)

        try:
            response = requests.get(
                f"{self.BASE_URL}/time_series",
                params={
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "outputsize": limit,
                    "apikey": self.api_key
                },
                timeout=15
            )
            self.rate_limiter.record_call()
            self.daily_calls += 1

            if response.status_code != 200:
                return None

            data = response.json()

            if 'code' in data:  # Error
                return None

            values = data.get('values', [])
            candles = []

            for v in values:
                candles.append(Candle(
                    timestamp=datetime.fromisoformat(v['datetime'].replace(' ', 'T')),
                    open=float(v['open']),
                    high=float(v['high']),
                    low=float(v['low']),
                    close=float(v['close']),
                    volume=int(v.get('volume', 0))
                ))

            # Reverse to chronological order (oldest first)
            candles.reverse()
            return candles

        except Exception as e:
            return None


class YFinanceProvider:
    """
    Yahoo Finance provider (via yfinance library).

    Free, no API key required
    Rate limit: ~2000 calls/hour (unofficial)
    """

    def __init__(self):
        self.available = YFINANCE_AVAILABLE
        self.rate_limiter = RateLimiter(30)  # Be conservative

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get quote using yfinance"""
        if not self.available:
            return None

        await self.rate_limiter.wait_if_needed()

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info

            self.rate_limiter.record_call()

            price = info.last_price
            prev_close = info.previous_close

            if not price:
                return None

            change = price - prev_close if prev_close else 0
            change_pct = (change / prev_close * 100) if prev_close else 0

            return Quote(
                symbol=symbol.upper(),
                price=price,
                change=change,
                change_percent=change_pct,
                volume=info.last_volume or 0,
                timestamp=datetime.now(),
                source='yfinance',
                prev_close=prev_close
            )
        except Exception as e:
            return None

    async def get_candles(self, symbol: str, interval: str = "1d",
                          limit: int = 100) -> Optional[List[Candle]]:
        """Get historical data using yfinance"""
        if not self.available:
            return None

        await self.rate_limiter.wait_if_needed()

        # Map interval to yfinance format
        interval_map = {
            "D": "1d", "1day": "1d",
            "W": "1wk", "1week": "1wk", "1w": "1wk",
            "M": "1mo", "1month": "1mo", "1M": "1mo",
            "1h": "1h", "60": "1h",
            "5min": "5m", "5m": "5m", "5": "5m",
            "15min": "15m", "15m": "15m", "15": "15m",
            "30min": "30m", "30m": "30m", "30": "30m",
        }
        yf_interval = interval_map.get(interval, interval)

        # Calculate period based on interval and limit
        if yf_interval in ['1d', '1wk', '1mo']:
            period = f"{min(limit * 2, 730)}d"  # Max 2 years
        else:
            period = f"{min(limit, 60)}d"  # Intraday limited

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=yf_interval)

            self.rate_limiter.record_call()

            if df.empty:
                return None

            # Take last 'limit' rows
            df = df.tail(limit)

            candles = []
            for idx, row in df.iterrows():
                candles.append(Candle(
                    timestamp=idx.to_pydatetime().replace(tzinfo=None),
                    open=row['Open'],
                    high=row['High'],
                    low=row['Low'],
                    close=row['Close'],
                    volume=int(row['Volume'])
                ))

            return candles

        except Exception as e:
            return None


class MarketDataProvider:
    """
    Unified market data provider with automatic failover.

    Priority order:
    1. yfinance (free, no key needed)
    2. Finnhub (if API key configured)
    3. Twelve Data (if API key configured)

    Usage:
        provider = MarketDataProvider()

        # Get single quote
        quote = await provider.get_quote("AAPL")

        # Get historical candles
        candles = await provider.get_candles("AAPL", interval="1d", limit=100)

        # Get candles as DataFrame
        df = await provider.get_candles_df("AAPL", interval="1d", limit=100)
    """

    def __init__(self):
        self.yfinance = YFinanceProvider()
        self.finnhub = FinnhubProvider()
        self.twelve_data = TwelveDataProvider()

        # Track provider health
        self.failures: Dict[str, int] = {
            'yfinance': 0,
            'finnhub': 0,
            'twelve_data': 0
        }
        self.max_failures = 3  # After 3 failures, skip provider temporarily

    def _get_provider_order(self) -> List[str]:
        """Get providers ordered by health/availability"""
        providers = []

        # yfinance first if healthy
        if self.yfinance.available and self.failures['yfinance'] < self.max_failures:
            providers.append('yfinance')

        # Then Finnhub if available
        if self.finnhub.available and self.failures['finnhub'] < self.max_failures:
            providers.append('finnhub')

        # Then Twelve Data
        if self.twelve_data.available and self.failures['twelve_data'] < self.max_failures:
            providers.append('twelve_data')

        # Include failed providers at end as last resort
        for name in ['yfinance', 'finnhub', 'twelve_data']:
            if name not in providers:
                providers.append(name)

        return providers

    async def get_quote(self, symbol: str,
                        preferred_source: str = None) -> Optional[Quote]:
        """
        Get quote with automatic failover.

        Args:
            symbol: Stock/crypto symbol
            preferred_source: Force specific provider ('yfinance', 'finnhub', 'twelve_data')
        """
        if preferred_source:
            providers = [preferred_source]
        else:
            providers = self._get_provider_order()

        for provider_name in providers:
            provider = getattr(self, provider_name.replace('_', '_'), None)
            if provider_name == 'yfinance':
                provider = self.yfinance
            elif provider_name == 'finnhub':
                provider = self.finnhub
            elif provider_name == 'twelve_data':
                provider = self.twelve_data
            else:
                continue

            if not provider or not provider.available:
                continue

            quote = await provider.get_quote(symbol)

            if quote:
                self.failures[provider_name] = 0  # Reset failures
                return quote
            else:
                self.failures[provider_name] += 1

        return None

    async def get_candles(self, symbol: str, interval: str = "1d",
                          limit: int = 100,
                          preferred_source: str = None) -> Optional[List[Candle]]:
        """
        Get historical candles with automatic failover.

        Args:
            symbol: Stock/crypto symbol
            interval: Time interval (1d, 1h, 5m, etc.)
            limit: Number of candles
            preferred_source: Force specific provider
        """
        if preferred_source:
            providers = [preferred_source]
        else:
            providers = self._get_provider_order()

        for provider_name in providers:
            if provider_name == 'yfinance':
                provider = self.yfinance
            elif provider_name == 'finnhub':
                provider = self.finnhub
            elif provider_name == 'twelve_data':
                provider = self.twelve_data
            else:
                continue

            if not provider or not provider.available:
                continue

            candles = await provider.get_candles(symbol, interval, limit)

            if candles and len(candles) > 0:
                self.failures[provider_name] = 0
                return candles
            else:
                self.failures[provider_name] += 1

        return None

    async def get_candles_df(self, symbol: str, interval: str = "1d",
                             limit: int = 100,
                             preferred_source: str = None) -> Optional[Any]:
        """
        Get historical candles as a pandas DataFrame.

        Returns DataFrame with columns: open, high, low, close, volume
        Index is datetime.
        """
        if not PANDAS_AVAILABLE:
            return None

        candles = await self.get_candles(symbol, interval, limit, preferred_source)

        if not candles:
            return None

        data = {
            'open': [c.open for c in candles],
            'high': [c.high for c in candles],
            'low': [c.low for c in candles],
            'close': [c.close for c in candles],
            'volume': [c.volume for c in candles]
        }

        df = pd.DataFrame(data, index=[c.timestamp for c in candles])
        df.index.name = 'datetime'

        return df

    async def get_quotes_batch(self, symbols: List[str]) -> Dict[str, Optional[Quote]]:
        """Get quotes for multiple symbols"""
        results = {}

        for symbol in symbols:
            results[symbol] = await self.get_quote(symbol)
            await asyncio.sleep(0.1)  # Small delay between calls

        return results

    def get_status(self) -> Dict[str, Any]:
        """Get provider status"""
        return {
            'providers': {
                'yfinance': {
                    'available': self.yfinance.available,
                    'failures': self.failures['yfinance'],
                    'requires_key': False
                },
                'finnhub': {
                    'available': self.finnhub.available,
                    'failures': self.failures['finnhub'],
                    'requires_key': True,
                    'rate_limit': '60/min'
                },
                'twelve_data': {
                    'available': self.twelve_data.available,
                    'failures': self.failures['twelve_data'],
                    'requires_key': True,
                    'rate_limit': '8/min, 800/day',
                    'daily_calls': self.twelve_data.daily_calls
                }
            }
        }


# Convenience function for quick access
_default_provider = None

def get_provider() -> MarketDataProvider:
    """Get singleton market data provider"""
    global _default_provider
    if _default_provider is None:
        _default_provider = MarketDataProvider()
    return _default_provider


async def get_quote(symbol: str) -> Optional[Quote]:
    """Quick quote fetch"""
    return await get_provider().get_quote(symbol)


async def get_candles(symbol: str, interval: str = "1d",
                      limit: int = 100) -> Optional[List[Candle]]:
    """Quick candles fetch"""
    return await get_provider().get_candles(symbol, interval, limit)


# CLI test
if __name__ == "__main__":
    import sys

    async def test():
        provider = MarketDataProvider()

        print("Market Data Provider Status:")
        print("-" * 40)
        status = provider.get_status()
        for name, info in status['providers'].items():
            avail = "YES" if info['available'] else "NO"
            key_note = " (needs API key)" if info['requires_key'] and not info['available'] else ""
            print(f"  {name}: {avail}{key_note}")
        print()

        symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"

        print(f"Testing quote for {symbol}...")
        quote = await provider.get_quote(symbol)
        if quote:
            print(f"  Price: ${quote.price:.2f}")
            print(f"  Change: {quote.change:+.2f} ({quote.change_percent:+.2f}%)")
            print(f"  Source: {quote.source}")
        else:
            print("  Failed to get quote")

        print(f"\nTesting candles for {symbol}...")
        candles = await provider.get_candles(symbol, "1d", 5)
        if candles:
            print(f"  Got {len(candles)} candles")
            for c in candles[-3:]:
                print(f"    {c.timestamp.date()}: O:{c.open:.2f} H:{c.high:.2f} L:{c.low:.2f} C:{c.close:.2f}")
        else:
            print("  Failed to get candles")

    asyncio.run(test())

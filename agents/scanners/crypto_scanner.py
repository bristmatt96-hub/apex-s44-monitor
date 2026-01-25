"""
Crypto Market Scanner
Scans cryptocurrency markets 24/7 for trading opportunities
No PDT restrictions - can day trade freely
"""
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False

from .base_scanner import BaseScanner
from core.models import Signal, MarketType, SignalType


class CryptoScanner(BaseScanner):
    """
    24/7 Crypto market scanner.

    Advantages:
    - No PDT rule
    - 24/7 markets
    - High volatility = opportunities
    - Many exchanges/liquidity

    Strategies:
    - Trend following
    - Breakouts
    - Altcoin momentum
    - BTC correlation trades
    - Funding rate arbitrage signals
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("CryptoScanner", MarketType.CRYPTO, config)

        # Exchange setup
        self.exchange_id = config.get('exchange', 'binance') if config else 'binance'
        self.exchange = None

        # Aggressive crypto watchlist
        self.default_watchlist = [
            # Major coins
            'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT',
            'AVAX/USDT', 'DOT/USDT', 'MATIC/USDT', 'LINK/USDT', 'UNI/USDT',
            # High volatility alts
            'DOGE/USDT', 'SHIB/USDT', 'PEPE/USDT', 'FLOKI/USDT', 'BONK/USDT',
            # DeFi
            'AAVE/USDT', 'MKR/USDT', 'SNX/USDT', 'CRV/USDT', 'LDO/USDT',
            # Layer 2
            'ARB/USDT', 'OP/USDT', 'IMX/USDT',
            # Gaming/Metaverse
            'AXS/USDT', 'SAND/USDT', 'MANA/USDT', 'GALA/USDT',
            # AI tokens
            'FET/USDT', 'AGIX/USDT', 'OCEAN/USDT', 'RNDR/USDT',
            # Other movers
            'APE/USDT', 'LTC/USDT', 'BCH/USDT', 'ETC/USDT', 'FIL/USDT',
            'NEAR/USDT', 'ATOM/USDT', 'ALGO/USDT', 'VET/USDT', 'HBAR/USDT'
        ]

        self.timeframe = '1h'  # 1 hour candles for signals
        self.lookback = 100  # Candles to fetch

    async def _init_exchange(self):
        """Initialize exchange connection"""
        if not CCXT_AVAILABLE:
            logger.error("ccxt not available")
            return

        if self.exchange is None:
            try:
                exchange_class = getattr(ccxt, self.exchange_id)
                self.exchange = exchange_class({
                    'enableRateLimit': True,
                })
                await asyncio.sleep(0)  # Yield to event loop
                logger.info(f"Connected to {self.exchange_id}")
            except Exception as e:
                logger.error(f"Failed to init exchange: {e}")

    async def get_universe(self) -> List[str]:
        """Get crypto pairs to scan"""
        return self.default_watchlist

    async def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch OHLCV from exchange"""
        if not CCXT_AVAILABLE:
            return None

        await self._init_exchange()

        if self.exchange is None:
            return None

        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=self.timeframe,
                limit=self.lookback
            )

            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)

            return df

        except Exception as e:
            logger.debug(f"Error fetching {symbol}: {e}")
            return None

    async def analyze(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Analyze crypto pair for signals"""
        if len(data) < 30:
            return None

        signals = []

        # Strategy 1: Trend Following
        trend_signal = await self._check_trend_following(symbol, data)
        if trend_signal:
            signals.append(trend_signal)

        # Strategy 2: Breakout
        breakout_signal = await self._check_breakout(symbol, data)
        if breakout_signal:
            signals.append(breakout_signal)

        # Strategy 3: RSI Divergence
        divergence_signal = await self._check_rsi_divergence(symbol, data)
        if divergence_signal:
            signals.append(divergence_signal)

        # Strategy 4: EMA Crossover
        ema_signal = await self._check_ema_crossover(symbol, data)
        if ema_signal:
            signals.append(ema_signal)

        if signals:
            return max(signals, key=lambda s: s.confidence * s.risk_reward_ratio)

        return None

    async def _check_trend_following(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Trend following with multiple timeframe confirmation"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            # Indicators
            data['ema21'] = ta.ema(close, length=21)
            data['ema55'] = ta.ema(close, length=55)
            data['rsi'] = ta.rsi(close, length=14)
            data['atr'] = ta.atr(high, low, close, length=14)
            data['adx'] = ta.adx(high, low, close, length=14)['ADX_14']

            current = data.iloc[-1]
            prev = data.iloc[-2]

            price = current['close']
            ema21 = current['ema21']
            ema55 = current['ema55']
            rsi = current['rsi']
            adx = current['adx']
            atr = current['atr']

            # Strong trend conditions
            trend_up = ema21 > ema55
            price_above_ema = price > ema21
            strong_trend = adx > 25
            rsi_ok = 45 < rsi < 70

            # EMA 21 acting as support (price bouncing off it)
            near_ema21 = abs(price - ema21) / price < 0.02
            ema_bounce = prev['low'] <= prev['ema21'] and current['close'] > current['ema21']

            if trend_up and price_above_ema and strong_trend and rsi_ok and (near_ema21 or ema_bounce):
                entry = price
                stop_loss = ema55 - (0.5 * atr)
                target = entry + (2.5 * (entry - stop_loss))

                rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                if rr_ratio >= 2.0:
                    return Signal(
                        symbol=symbol,
                        market_type=MarketType.CRYPTO,
                        signal_type=SignalType.BUY,
                        confidence=0.72,
                        entry_price=entry,
                        target_price=target,
                        stop_loss=stop_loss,
                        risk_reward_ratio=rr_ratio,
                        source="crypto_trend_following",
                        metadata={
                            'strategy': 'trend_following',
                            'adx': adx,
                            'rsi': rsi,
                            'atr': atr
                        }
                    )

        except Exception as e:
            logger.debug(f"Trend following error for {symbol}: {e}")

        return None

    async def _check_breakout(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Check for range breakout"""
        try:
            close = data['close']
            high = data['high']
            low = data['low']
            volume = data['volume']

            # 24-hour range
            range_high = high[-24:].max()
            range_low = low[-24:].min()

            current = data.iloc[-1]
            price = current['close']

            # Breakout above range
            if price > range_high:
                avg_volume = volume[-24:].mean()
                current_volume = current['volume']

                # Volume confirmation
                if current_volume > avg_volume * 1.5:
                    if PANDAS_TA_AVAILABLE:
                        data['atr'] = ta.atr(high, low, close, length=14)
                        atr = data['atr'].iloc[-1]
                    else:
                        atr = (high - low).mean()

                    entry = price
                    stop_loss = range_high - atr  # Just below breakout
                    range_size = range_high - range_low
                    target = entry + (1.5 * range_size)  # Measured move

                    rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                    if rr_ratio >= 2.0:
                        return Signal(
                            symbol=symbol,
                            market_type=MarketType.CRYPTO,
                            signal_type=SignalType.BUY,
                            confidence=0.70,
                            entry_price=entry,
                            target_price=target,
                            stop_loss=stop_loss,
                            risk_reward_ratio=rr_ratio,
                            source="crypto_breakout",
                            metadata={
                                'strategy': 'range_breakout',
                                'range_high': range_high,
                                'range_low': range_low,
                                'volume_ratio': current_volume / avg_volume
                            }
                        )

        except Exception as e:
            logger.debug(f"Breakout check error for {symbol}: {e}")

        return None

    async def _check_rsi_divergence(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Check for bullish RSI divergence"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            data['rsi'] = ta.rsi(close, length=14)
            data['atr'] = ta.atr(high, low, close, length=14)

            # Look for divergence in last 20 candles
            recent = data.iloc[-20:]

            # Find price lows
            price_lows = []
            for i in range(2, len(recent) - 2):
                if recent['low'].iloc[i] < recent['low'].iloc[i-1] and \
                   recent['low'].iloc[i] < recent['low'].iloc[i-2] and \
                   recent['low'].iloc[i] < recent['low'].iloc[i+1] and \
                   recent['low'].iloc[i] < recent['low'].iloc[i+2]:
                    price_lows.append((i, recent['low'].iloc[i], recent['rsi'].iloc[i]))

            # Check for bullish divergence
            if len(price_lows) >= 2:
                first_low = price_lows[-2]
                second_low = price_lows[-1]

                # Price making lower low, RSI making higher low
                if second_low[1] < first_low[1] and second_low[2] > first_low[2]:
                    current = data.iloc[-1]
                    atr = current['atr']
                    price = current['close']

                    entry = price
                    stop_loss = second_low[1] - atr
                    target = entry + (2.5 * (entry - stop_loss))

                    rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                    if rr_ratio >= 2.0 and current['rsi'] < 40:
                        return Signal(
                            symbol=symbol,
                            market_type=MarketType.CRYPTO,
                            signal_type=SignalType.BUY,
                            confidence=0.68,
                            entry_price=entry,
                            target_price=target,
                            stop_loss=stop_loss,
                            risk_reward_ratio=rr_ratio,
                            source="crypto_rsi_divergence",
                            metadata={
                                'strategy': 'bullish_divergence',
                                'rsi': current['rsi']
                            }
                        )

        except Exception as e:
            logger.debug(f"RSI divergence check error for {symbol}: {e}")

        return None

    async def _check_ema_crossover(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Check for EMA crossover"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            data['ema9'] = ta.ema(close, length=9)
            data['ema21'] = ta.ema(close, length=21)
            data['atr'] = ta.atr(high, low, close, length=14)
            data['rsi'] = ta.rsi(close, length=14)

            current = data.iloc[-1]
            prev = data.iloc[-2]

            # Bullish crossover
            if prev['ema9'] <= prev['ema21'] and current['ema9'] > current['ema21']:
                price = current['close']
                atr = current['atr']
                rsi = current['rsi']

                # Filter
                if rsi > 40 and rsi < 70:
                    entry = price
                    stop_loss = current['ema21'] - atr
                    target = entry + (2 * (entry - stop_loss))

                    rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                    if rr_ratio >= 2.0:
                        return Signal(
                            symbol=symbol,
                            market_type=MarketType.CRYPTO,
                            signal_type=SignalType.BUY,
                            confidence=0.65,
                            entry_price=entry,
                            target_price=target,
                            stop_loss=stop_loss,
                            risk_reward_ratio=rr_ratio,
                            source="crypto_ema_crossover",
                            metadata={
                                'strategy': 'ema_crossover',
                                'rsi': rsi
                            }
                        )

        except Exception as e:
            logger.debug(f"EMA crossover check error for {symbol}: {e}")

        return None

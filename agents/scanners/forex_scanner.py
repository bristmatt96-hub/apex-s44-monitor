"""
Forex Market Scanner
Scans FX pairs for trading opportunities
No PDT restrictions - 24/5 market
"""
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger

from core.data_cache import get_data_cache

try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False

from .base_scanner import BaseScanner
from core.models import Signal, MarketType, SignalType


class ForexScanner(BaseScanner):
    """
    Forex market scanner.

    Advantages:
    - No PDT rule
    - High liquidity
    - 24/5 trading
    - Leverage available through IB

    Strategies:
    - Trend following
    - Support/Resistance breakouts
    - Session momentum
    - News-driven moves
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("ForexScanner", MarketType.FOREX, config)

        # Major and cross pairs
        self.default_watchlist = [
            # Majors
            'EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'USDCHF=X',
            'AUDUSD=X', 'USDCAD=X', 'NZDUSD=X',
            # Crosses
            'EURGBP=X', 'EURJPY=X', 'GBPJPY=X', 'AUDJPY=X',
            'EURAUD=X', 'GBPAUD=X', 'EURCHF=X', 'GBPCHF=X',
            'AUDCAD=X', 'AUDNZD=X', 'CADJPY=X', 'CHFJPY=X',
            # Exotics (higher volatility)
            'USDZAR=X', 'USDMXN=X', 'USDTRY=X', 'USDSEK=X', 'USDNOK=X'
        ]

        self.pip_values = {
            'JPY': 0.01,  # Yen pairs
            'DEFAULT': 0.0001  # Most pairs
        }

    async def get_universe(self) -> List[str]:
        """Get forex pairs to scan"""
        return self.default_watchlist

    async def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch forex data via shared cache"""
        cache = get_data_cache()
        return await cache.get_history(symbol, 'forex', '1mo', '1h')

    def _get_pip_value(self, symbol: str) -> float:
        """Get pip value for pair"""
        if 'JPY' in symbol:
            return self.pip_values['JPY']
        return self.pip_values['DEFAULT']

    async def analyze(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Analyze forex pair for signals"""
        if len(data) < 50:
            return None

        signals = []

        # Strategy 1: Trend Following
        trend_signal = await self._check_trend(symbol, data)
        if trend_signal:
            signals.append(trend_signal)

        # Strategy 2: Breakout
        breakout_signal = await self._check_breakout(symbol, data)
        if breakout_signal:
            signals.append(breakout_signal)

        # Strategy 3: Mean Reversion
        reversion_signal = await self._check_mean_reversion(symbol, data)
        if reversion_signal:
            signals.append(reversion_signal)

        if signals:
            return max(signals, key=lambda s: s.confidence * s.risk_reward_ratio)

        return None

    async def _check_trend(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Trend following strategy"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            # Calculate indicators
            data['ema20'] = ta.ema(close, length=20)
            data['ema50'] = ta.ema(close, length=50)
            data['ema200'] = ta.ema(close, length=200) if len(data) >= 200 else ta.ema(close, length=100)
            data['atr'] = ta.atr(high, low, close, length=14)
            data['rsi'] = ta.rsi(close, length=14)
            data['macd'] = ta.macd(close)['MACD_12_26_9']
            data['macd_signal'] = ta.macd(close)['MACDs_12_26_9']

            current = data.iloc[-1]
            prev = data.iloc[-2]

            price = current['close']
            ema20 = current['ema20']
            ema50 = current['ema50']
            atr = current['atr']
            rsi = current['rsi']
            macd = current['macd']
            macd_signal = current['macd_signal']

            # Trend conditions
            uptrend = ema20 > ema50
            price_above_ema = price > ema20
            rsi_ok = 40 < rsi < 70
            macd_bullish = macd > macd_signal

            # Entry on pullback to EMA20
            pullback_to_ema = abs(price - ema20) / price < 0.003  # Within 0.3%

            if uptrend and price_above_ema and rsi_ok and macd_bullish and pullback_to_ema:
                entry = price
                stop_loss = ema50 - (0.5 * atr)
                target = entry + (2 * (entry - stop_loss))

                rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                if rr_ratio >= 2.0:
                    return Signal(
                        symbol=symbol.replace('=X', ''),
                        market_type=MarketType.FOREX,
                        signal_type=SignalType.BUY,
                        confidence=0.70,
                        entry_price=entry,
                        target_price=target,
                        stop_loss=stop_loss,
                        risk_reward_ratio=rr_ratio,
                        source="forex_trend_following",
                        metadata={
                            'strategy': 'trend_pullback',
                            'rsi': rsi,
                            'atr': atr,
                            'macd': macd
                        }
                    )

        except Exception as e:
            logger.debug(f"Trend check error for {symbol}: {e}")

        return None

    async def _check_breakout(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Check for range breakout"""
        try:
            close = data['close']
            high = data['high']
            low = data['low']
            volume = data['volume']

            # 48-hour range (2 days)
            range_high = high[-48:].max()
            range_low = low[-48:].min()
            range_size = range_high - range_low

            current = data.iloc[-1]
            price = current['close']

            # Breakout above range with some buffer
            if price > range_high * 1.001:
                if PANDAS_TA_AVAILABLE:
                    data['atr'] = ta.atr(high, low, close, length=14)
                    atr = data['atr'].iloc[-1]
                else:
                    atr = (high - low).mean()

                entry = price
                stop_loss = range_high - (0.5 * atr)  # Just below breakout
                target = entry + range_size  # Measured move

                rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                if rr_ratio >= 2.0:
                    return Signal(
                        symbol=symbol.replace('=X', ''),
                        market_type=MarketType.FOREX,
                        signal_type=SignalType.BUY,
                        confidence=0.68,
                        entry_price=entry,
                        target_price=target,
                        stop_loss=stop_loss,
                        risk_reward_ratio=rr_ratio,
                        source="forex_breakout",
                        metadata={
                            'strategy': 'range_breakout',
                            'range_pips': range_size / self._get_pip_value(symbol)
                        }
                    )

        except Exception as e:
            logger.debug(f"Breakout check error for {symbol}: {e}")

        return None

    async def _check_mean_reversion(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Mean reversion at extremes"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            data['rsi'] = ta.rsi(close, length=14)
            _bb = ta.bbands(close, length=20)
            _bb_cols = _bb.columns.tolist()
            data['bb_upper'] = _bb[[c for c in _bb_cols if c.startswith('BBU')][0]]
            data['bb_lower'] = _bb[[c for c in _bb_cols if c.startswith('BBL')][0]]
            data['bb_mid'] = _bb[[c for c in _bb_cols if c.startswith('BBM')][0]]
            data['atr'] = ta.atr(high, low, close, length=14)

            current = data.iloc[-1]
            prev = data.iloc[-2]

            price = current['close']
            rsi = current['rsi']
            bb_lower = current['bb_lower']
            bb_mid = current['bb_mid']
            atr = current['atr']

            # Oversold bounce
            oversold = rsi < 30
            at_lower_band = price < bb_lower * 1.002
            reversal_candle = current['close'] > current['open'] and prev['close'] < prev['open']

            if oversold and at_lower_band and reversal_candle:
                entry = price
                stop_loss = low[-5:].min() - (0.5 * atr)
                target = bb_mid  # Target middle of band

                rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                if rr_ratio >= 1.5:  # Lower threshold for mean reversion
                    return Signal(
                        symbol=symbol.replace('=X', ''),
                        market_type=MarketType.FOREX,
                        signal_type=SignalType.BUY,
                        confidence=0.65,
                        entry_price=entry,
                        target_price=target,
                        stop_loss=stop_loss,
                        risk_reward_ratio=rr_ratio,
                        source="forex_mean_reversion",
                        metadata={
                            'strategy': 'oversold_bounce',
                            'rsi': rsi
                        }
                    )

        except Exception as e:
            logger.debug(f"Mean reversion check error for {symbol}: {e}")

        return None

"""
Equity Market Scanner
Scans stocks, ETFs, and SPACs for trading opportunities
"""
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False

# Unified market data provider with Finnhub/Twelve Data failover
try:
    from data.market_data_providers import MarketDataProvider, get_provider
    MULTI_PROVIDER_AVAILABLE = True
except ImportError:
    MULTI_PROVIDER_AVAILABLE = False

from .base_scanner import BaseScanner
from core.models import Signal, MarketType, SignalType


class EquityScanner(BaseScanner):
    """
    Scans equities for high risk/reward opportunities.

    Strategies:
    - Momentum breakouts
    - Mean reversion
    - Gap plays
    - Volume surges
    - SPAC arbitrage
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("EquityScanner", MarketType.EQUITY, config)

        # Watchlist optimized from backtest results (Jan 2026)
        # Prioritizes symbols where strategies proved edge
        self.default_watchlist = [
            # High retail options volume (4 strategies with edge)
            'SPY', 'QQQ', 'TSLA', 'AAPL', 'NVDA', 'AMD', 'META',
            'AMZN', 'MSFT', 'GOOGL', 'NFLX', 'COIN',
            # Meme / retail stocks (mean reversion + volume spike edge)
            'GME', 'AMC', 'PLTR', 'SOFI', 'BB', 'HOOD',
            'RIVN', 'LCID', 'MARA', 'RIOT', 'DKNG',
            # Small cap momentum (mean reversion + RSI divergence edge)
            'JOBY', 'IONQ', 'RKLB', 'DNA', 'OPEN',
            # ETFs with retail behavioral patterns (NOT commodities/bonds)
            'IWM', 'ARKK', 'TQQQ',  # Index/innovation - retail favorites
            'XLE', 'XLF', 'XLK',    # Sectors with behavioral patterns
            # NO GLD, SLV, TLT, USO - macro/commodity driven, no behavioral edge
        ]

        self.min_volume = 1_000_000  # Minimum daily volume
        self.min_price = 1.0  # Minimum price
        self.max_price = 500.0  # Maximum price for position sizing

    async def get_universe(self) -> List[str]:
        """Get equity universe to scan"""
        # Start with default watchlist
        universe = self.default_watchlist.copy()

        # Could expand with screener results
        # For now, use predefined list

        return universe

    async def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data with automatic failover.
        Priority: yfinance (free) -> Finnhub -> Twelve Data
        """
        # Try unified provider first (has automatic failover)
        if MULTI_PROVIDER_AVAILABLE:
            try:
                provider = get_provider()
                df = await provider.get_candles_df(symbol, interval="1d", limit=90)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.debug(f"Multi-provider fetch failed for {symbol}: {e}")

        # Fallback to direct yfinance if provider failed
        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available")
            return None

        try:
            ticker = yf.Ticker(symbol)
            # Get 3 months of daily data + intraday
            df = ticker.history(period="3mo", interval="1d")

            if df.empty:
                return None

            # Standardize column names
            df.columns = [c.lower() for c in df.columns]

            return df

        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return None

    async def analyze(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """
        Analyze equity for trading signals.
        Prioritizes backtest-proven strategies:
        1. Mean Reversion (PF 1.43-5.29 across all markets)
        2. Volume Spike Reversal (PF 1.99-14.42)
        3. Momentum Breakout (PF 1.87-1.96 on options/ETF/crypto stocks)
        """
        if len(data) < 20:
            return None

        signals = []

        # PROVEN Strategy 1: Mean Reversion (edge in ALL markets)
        reversion_signal = await self._check_mean_reversion(symbol, data)
        if reversion_signal:
            signals.append(reversion_signal)

        # PROVEN Strategy 2: Volume Spike Reversal (buy panic selling)
        vol_reversal_signal = await self._check_volume_spike_reversal(symbol, data)
        if vol_reversal_signal:
            signals.append(vol_reversal_signal)

        # PROVEN Strategy 3: Momentum Breakout
        momentum_signal = await self._check_momentum_breakout(symbol, data)
        if momentum_signal:
            signals.append(momentum_signal)

        # Strategy 4: Volume Surge (bullish)
        volume_signal = await self._check_volume_surge(symbol, data)
        if volume_signal:
            signals.append(volume_signal)

        # Return highest confidence signal
        if signals:
            return max(signals, key=lambda s: s.confidence * s.risk_reward_ratio)

        return None

    async def _check_momentum_breakout(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Check for momentum breakout above resistance"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            volume = data['volume']

            # Calculate indicators
            data['sma20'] = ta.sma(close, length=20)
            data['sma50'] = ta.sma(close, length=50)
            data['rsi'] = ta.rsi(close, length=14)
            data['atr'] = ta.atr(high, data['low'], close, length=14)

            current = data.iloc[-1]
            prev = data.iloc[-2]

            # Check breakout conditions
            price = current['close']
            sma20 = current['sma20']
            sma50 = current['sma50']
            rsi = current['rsi']
            atr = current['atr']

            # 20-day high breakout
            twenty_day_high = high[-20:].max()
            is_breakout = price > twenty_day_high * 0.99

            # Trend confirmation
            trend_up = sma20 > sma50
            above_sma = price > sma20

            # Volume confirmation
            avg_volume = volume[-20:].mean()
            volume_surge = volume.iloc[-1] > avg_volume * 1.5

            # RSI not overbought
            rsi_ok = 40 < rsi < 75

            if is_breakout and trend_up and above_sma and volume_surge and rsi_ok:
                # Calculate targets
                entry = price
                stop_loss = entry - (2 * atr)  # 2 ATR stop
                target = entry + (4 * atr)  # 4 ATR target (2:1 R:R)

                rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                if rr_ratio >= 2.0:
                    return Signal(
                        symbol=symbol,
                        market_type=MarketType.EQUITY,
                        signal_type=SignalType.BUY,
                        confidence=0.72,
                        entry_price=entry,
                        target_price=target,
                        stop_loss=stop_loss,
                        risk_reward_ratio=rr_ratio,
                        source="equity_momentum_breakout",
                        metadata={
                            'strategy': 'momentum_breakout',
                            'rsi': rsi,
                            'volume_ratio': volume.iloc[-1] / avg_volume,
                            'atr': atr
                        }
                    )

        except Exception as e:
            logger.debug(f"Momentum check error for {symbol}: {e}")

        return None

    async def _check_mean_reversion(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Check for oversold mean reversion setup"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            # Calculate indicators
            data['rsi'] = ta.rsi(close, length=14)
            data['bb_lower'] = ta.bbands(close, length=20)['BBL_20_2.0']
            data['atr'] = ta.atr(high, low, close, length=14)
            data['sma50'] = ta.sma(close, length=50)

            current = data.iloc[-1]

            price = current['close']
            rsi = current['rsi']
            bb_lower = current['bb_lower']
            atr = current['atr']
            sma50 = current['sma50']

            # Oversold conditions
            is_oversold = rsi < 30
            at_bb_lower = price < bb_lower * 1.01
            above_trend = price > sma50 * 0.95  # Still in overall uptrend

            # Look for reversal candle
            prev = data.iloc[-2]
            reversal = current['close'] > current['open'] and prev['close'] < prev['open']

            if is_oversold and at_bb_lower and reversal:
                entry = price
                stop_loss = low[-5:].min() - (0.5 * atr)  # Below recent lows
                target = entry + (3 * atr)  # 3 ATR target

                rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                if rr_ratio >= 2.0:
                    return Signal(
                        symbol=symbol,
                        market_type=MarketType.EQUITY,
                        signal_type=SignalType.BUY,
                        confidence=0.68,
                        entry_price=entry,
                        target_price=target,
                        stop_loss=stop_loss,
                        risk_reward_ratio=rr_ratio,
                        source="equity_mean_reversion",
                        metadata={
                            'strategy': 'mean_reversion',
                            'rsi': rsi,
                            'bb_position': 'at_lower'
                        }
                    )

        except Exception as e:
            logger.debug(f"Mean reversion check error for {symbol}: {e}")

        return None

    async def _check_volume_surge(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Check for unusual volume with price action"""
        try:
            close = data['close']
            volume = data['volume']
            high = data['high']
            low = data['low']

            # Volume analysis
            avg_volume = volume[-20:].mean()
            current_volume = volume.iloc[-1]
            volume_ratio = current_volume / avg_volume

            # Need significant volume surge
            if volume_ratio < 3.0:
                return None

            # Price action
            current = data.iloc[-1]
            price_change = (current['close'] - current['open']) / current['open']

            # Bullish volume surge
            if volume_ratio > 3.0 and price_change > 0.02:
                if PANDAS_TA_AVAILABLE:
                    data['atr'] = ta.atr(high, low, close, length=14)
                    atr = data['atr'].iloc[-1]
                else:
                    atr = (high - low).mean()

                entry = current['close']
                stop_loss = current['low'] - (0.5 * atr)
                target = entry + (3 * atr)

                rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                if rr_ratio >= 2.0:
                    return Signal(
                        symbol=symbol,
                        market_type=MarketType.EQUITY,
                        signal_type=SignalType.BUY,
                        confidence=0.65 + min(0.15, (volume_ratio - 3) * 0.03),
                        entry_price=entry,
                        target_price=target,
                        stop_loss=stop_loss,
                        risk_reward_ratio=rr_ratio,
                        source="equity_volume_surge",
                        metadata={
                            'strategy': 'volume_surge',
                            'volume_ratio': volume_ratio,
                            'price_change_pct': price_change * 100
                        }
                    )

        except Exception as e:
            logger.debug(f"Volume surge check error for {symbol}: {e}")

        return None

    async def _check_volume_spike_reversal(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """
        Volume spike reversal - buy when retail panics on big red volume.
        Backtest: PF 14.42 (crypto), PF 1.99 (meme stocks), PF 2.98 (options stocks)
        Win rate: 52-86% across markets
        """
        try:
            close = data['close']
            volume = data['volume']
            high = data['high']
            low = data['low']

            # Volume analysis
            avg_volume = volume[-20:].mean()
            current_volume = volume.iloc[-1]
            volume_ratio = current_volume / avg_volume

            # Need significant volume spike (2.5x+)
            if volume_ratio < 2.5:
                return None

            current = data.iloc[-1]

            # Must be a RED day (retail panic)
            is_red = current['close'] < current['open']
            # Must be a big drop (2%+)
            pct_change = (current['close'] - current['open']) / current['open']
            is_big_drop = pct_change < -0.02

            if not (is_red and is_big_drop):
                return None

            # This is the reversal signal - smart money absorbs panic selling
            if PANDAS_TA_AVAILABLE:
                data['atr'] = ta.atr(high, low, close, length=14)
                atr = data['atr'].iloc[-1]
            else:
                atr = (high - low).rolling(14).mean().iloc[-1]

            entry = current['close']
            stop_loss = current['low'] - (0.5 * atr)  # Below panic low
            target = entry + (3 * atr)  # 3 ATR target

            rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

            if rr_ratio >= 2.0:
                # Higher confidence with bigger volume spike
                conf = 0.70 + min(0.15, (volume_ratio - 2.5) * 0.03)

                return Signal(
                    symbol=symbol,
                    market_type=MarketType.EQUITY,
                    signal_type=SignalType.BUY,
                    confidence=conf,
                    entry_price=entry,
                    target_price=target,
                    stop_loss=stop_loss,
                    risk_reward_ratio=rr_ratio,
                    source="equity_volume_spike_reversal",
                    metadata={
                        'strategy': 'volume_spike',
                        'volume_ratio': volume_ratio,
                        'drop_pct': pct_change * 100,
                        'backtest_pf': 1.99
                    }
                )

        except Exception as e:
            logger.debug(f"Volume spike reversal check error for {symbol}: {e}")

        return None

    async def _check_gap_play(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Check for gap plays"""
        try:
            if len(data) < 2:
                return None

            current = data.iloc[-1]
            prev = data.iloc[-2]

            # Calculate gap
            gap_pct = (current['open'] - prev['close']) / prev['close']

            # Gap up play
            if gap_pct > 0.03:  # 3%+ gap up
                # Check if holding above gap
                if current['low'] > prev['close']:
                    if PANDAS_TA_AVAILABLE:
                        data['atr'] = ta.atr(data['high'], data['low'], data['close'], length=14)
                        atr = data['atr'].iloc[-1]
                    else:
                        atr = (data['high'] - data['low']).mean()

                    entry = current['close']
                    stop_loss = prev['close'] - (0.5 * atr)  # Below gap fill
                    target = entry + (2 * (entry - stop_loss))  # 2:1 target

                    rr_ratio = self.calculate_risk_reward(entry, target, stop_loss)

                    if rr_ratio >= 2.0:
                        return Signal(
                            symbol=symbol,
                            market_type=MarketType.EQUITY,
                            signal_type=SignalType.BUY,
                            confidence=0.70,
                            entry_price=entry,
                            target_price=target,
                            stop_loss=stop_loss,
                            risk_reward_ratio=rr_ratio,
                            source="equity_gap_play",
                            metadata={
                                'strategy': 'gap_up',
                                'gap_pct': gap_pct * 100
                            }
                        )

        except Exception as e:
            logger.debug(f"Gap play check error for {symbol}: {e}")

        return None

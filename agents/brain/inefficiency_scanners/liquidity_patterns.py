"""
Liquidity Pattern Scanner

Detects predictable liquidity patterns that create trading opportunities.

WHY THIS WORKS:
- Market open (9:30-10:00) is chaotic - wide spreads, reversals
- Lunch hour (12:00-1:00) is thin - bigger moves on small volume
- Power hour (3:00-4:00) sees institutional positioning
- These patterns are PREDICTABLE and exploitable

THE EDGE:
- Best fills: 10:30am and 2:30pm (post-volatility, pre-close)
- Fade open moves: First 30min reversals are common
- Lunch dip buying: Stocks often bottom around 12:30

WHY ALGOS STRUGGLE:
- Algos trade AT these times, not AGAINST them
- They follow volume, not anti-volume patterns
- Position sizing for thin liquidity is hard to model
"""
import asyncio
from typing import List, Optional
from datetime import datetime, time as dt_time, timedelta
from loguru import logger

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from agents.brain.market_brain import (
    Inefficiency, InefficiencyType, EdgeReason
)


class LiquidityPatternScanner:
    """
    Scans for intraday liquidity-based inefficiencies.

    Patterns:
    1. Opening Range Breakout/Reversal (9:30-10:00)
    2. Lunch Dip (12:00-1:00)
    3. Power Hour Momentum (3:00-4:00)
    4. VWAP reversion
    """

    def __init__(self):
        self.watchlist = [
            # Most liquid with clear patterns
            'SPY', 'QQQ', 'IWM',
            'AAPL', 'MSFT', 'TSLA', 'NVDA', 'AMD', 'META',
            'GOOGL', 'AMZN', 'NFLX',
            # Retail favorites with predictable patterns
            'GME', 'AMC', 'PLTR', 'SOFI'
        ]

        # Time windows (EST)
        self.opening_range = (dt_time(9, 30), dt_time(10, 0))
        self.morning_reversal = (dt_time(10, 0), dt_time(10, 30))
        self.lunch_dip = (dt_time(12, 0), dt_time(13, 0))
        self.power_hour = (dt_time(15, 0), dt_time(16, 0))

    async def scan(self) -> List[Inefficiency]:
        """Scan for liquidity pattern opportunities"""
        if not YFINANCE_AVAILABLE:
            return []

        now = datetime.now()
        current_time = now.time()

        # Only during market hours
        if not (dt_time(9, 30) <= current_time <= dt_time(16, 0)):
            return []

        inefficiencies = []

        # Determine which pattern to look for based on time
        pattern_type = self._get_current_pattern(current_time)
        if not pattern_type:
            return []

        for symbol in self.watchlist:
            try:
                ineff = await self._analyze_pattern(symbol, pattern_type, current_time)
                if ineff:
                    inefficiencies.append(ineff)
            except Exception as e:
                logger.debug(f"Error analyzing {symbol} liquidity: {e}")
                continue

        return inefficiencies

    def _get_current_pattern(self, current_time: dt_time) -> Optional[str]:
        """Determine which pattern to scan for"""
        if self.morning_reversal[0] <= current_time <= self.morning_reversal[1]:
            return "morning_reversal"
        elif self.lunch_dip[0] <= current_time <= self.lunch_dip[1]:
            return "lunch_dip"
        elif self.power_hour[0] <= current_time <= self.power_hour[1]:
            return "power_hour"
        return None

    async def _analyze_pattern(
        self, symbol: str, pattern: str, current_time: dt_time
    ) -> Optional[Inefficiency]:
        """Analyze a symbol for the specific pattern"""
        try:
            ticker = yf.Ticker(symbol)

            # Get intraday data
            hist = ticker.history(period="1d", interval="5m")
            if hist.empty or len(hist) < 10:
                return None

            current_price = hist['Close'].iloc[-1]
            open_price = hist['Open'].iloc[0]
            day_high = hist['High'].max()
            day_low = hist['Low'].min()
            day_range = day_high - day_low

            # Calculate VWAP
            typical_price = (hist['High'] + hist['Low'] + hist['Close']) / 3
            vwap = (typical_price * hist['Volume']).cumsum() / hist['Volume'].cumsum()
            current_vwap = vwap.iloc[-1]

            if pattern == "morning_reversal":
                return await self._morning_reversal_signal(
                    symbol, hist, current_price, open_price, day_high, day_low, current_vwap
                )
            elif pattern == "lunch_dip":
                return await self._lunch_dip_signal(
                    symbol, hist, current_price, open_price, day_high, day_low, current_vwap
                )
            elif pattern == "power_hour":
                return await self._power_hour_signal(
                    symbol, hist, current_price, open_price, day_high, day_low, current_vwap
                )

            return None

        except Exception as e:
            logger.debug(f"Pattern analysis failed for {symbol}: {e}")
            return None

    async def _morning_reversal_signal(
        self, symbol, hist, current_price, open_price, day_high, day_low, vwap
    ) -> Optional[Inefficiency]:
        """
        Morning Reversal (10:00-10:30):
        Opening moves often reverse. Fade extended moves.
        """
        # Check if extended from VWAP
        vwap_distance = (current_price - vwap) / vwap

        # Need significant extension (>0.5% from VWAP)
        if abs(vwap_distance) < 0.005:
            return None

        if vwap_distance > 0.005:  # Extended above VWAP
            direction = "short"
            action = f"FADE MORNING EXTENSION: {symbol} extended {vwap_distance:.1%} above VWAP"
            target = vwap
            stop = day_high * 1.002
        else:  # Extended below VWAP
            direction = "long"
            action = f"FADE MORNING WEAKNESS: {symbol} extended {abs(vwap_distance):.1%} below VWAP"
            target = vwap
            stop = day_low * 0.998

        entry_zone = (current_price * 0.998, current_price * 1.002)
        risk = abs(current_price - stop)
        reward = abs(target - current_price)
        risk_reward = reward / risk if risk > 0 else 0

        if risk_reward < 1.5:
            return None

        score = min(0.8, abs(vwap_distance) * 10)  # Higher extension = higher score

        return Inefficiency(
            id=f"liq_{symbol}_morning_{datetime.now().strftime('%H%M')}",
            type=InefficiencyType.LIQUIDITY_WINDOW,
            symbol=symbol,
            score=score,
            edge_reason=EdgeReason.TIME_HORIZON,
            direction=direction,
            suggested_action=action,
            entry_zone=entry_zone,
            target=target,
            stop=stop,
            risk_reward=risk_reward,
            explanation=f"Morning moves often reverse 10-10:30am. {symbol} extended from VWAP, expect mean reversion.",
            data_points={
                'vwap': vwap,
                'vwap_distance': vwap_distance,
                'day_high': day_high,
                'day_low': day_low
            },
            confidence=score * 0.85,
            time_sensitivity="minutes"
        )

    async def _lunch_dip_signal(
        self, symbol, hist, current_price, open_price, day_high, day_low, vwap
    ) -> Optional[Inefficiency]:
        """
        Lunch Dip (12:00-1:00):
        Stocks often make intraday lows during lunch, then rally.
        """
        # Check if near day lows during lunch
        range_position = (current_price - day_low) / (day_high - day_low) if (day_high - day_low) > 0 else 0.5

        # Want to be in bottom 30% of day's range
        if range_position > 0.3:
            return None

        # Also should be below VWAP (weak)
        if current_price > vwap:
            return None

        direction = "long"
        action = f"LUNCH DIP BUY: {symbol} near day lows during thin lunch hour"
        target = vwap  # Target VWAP recovery
        stop = day_low * 0.995  # Stop just below day low

        entry_zone = (current_price * 0.998, current_price * 1.002)
        risk = abs(current_price - stop)
        reward = abs(target - current_price)
        risk_reward = reward / risk if risk > 0 else 0

        if risk_reward < 1.5:
            return None

        score = (0.3 - range_position) / 0.3  # Lower = better score
        score = min(0.85, score + 0.2)

        return Inefficiency(
            id=f"liq_{symbol}_lunch_{datetime.now().strftime('%H%M')}",
            type=InefficiencyType.LIQUIDITY_WINDOW,
            symbol=symbol,
            score=score,
            edge_reason=EdgeReason.TIME_HORIZON,
            direction=direction,
            suggested_action=action,
            entry_zone=entry_zone,
            target=target,
            stop=stop,
            risk_reward=risk_reward,
            explanation=f"Lunch hour dip pattern: {symbol} at {range_position:.0%} of day range, below VWAP. Typical bounce zone.",
            data_points={
                'range_position': range_position,
                'vwap': vwap,
                'day_low': day_low
            },
            confidence=score * 0.8,
            time_sensitivity="hours"
        )

    async def _power_hour_signal(
        self, symbol, hist, current_price, open_price, day_high, day_low, vwap
    ) -> Optional[Inefficiency]:
        """
        Power Hour (3:00-4:00):
        Institutions position for close. Follow the trend.
        """
        # Check day's trend
        day_return = (current_price / open_price) - 1
        vwap_position = (current_price - vwap) / vwap

        # Strong trend = continue
        if day_return > 0.01 and vwap_position > 0:  # Up day, above VWAP
            direction = "long"
            action = f"POWER HOUR MOMENTUM: {symbol} up {day_return:.1%}, riding into close"
            target = day_high * 1.005
            stop = vwap * 0.998
        elif day_return < -0.01 and vwap_position < 0:  # Down day, below VWAP
            direction = "short"
            action = f"POWER HOUR WEAKNESS: {symbol} down {day_return:.1%}, fading into close"
            target = day_low * 0.995
            stop = vwap * 1.002
        else:
            return None  # No clear trend

        entry_zone = (current_price * 0.998, current_price * 1.002)
        risk = abs(current_price - stop)
        reward = abs(target - current_price)
        risk_reward = reward / risk if risk > 0 else 0

        if risk_reward < 1.2:
            return None

        score = min(0.8, abs(day_return) * 20 + abs(vwap_position) * 10)

        return Inefficiency(
            id=f"liq_{symbol}_power_{datetime.now().strftime('%H%M')}",
            type=InefficiencyType.LIQUIDITY_WINDOW,
            symbol=symbol,
            score=score,
            edge_reason=EdgeReason.TIME_HORIZON,
            direction=direction,
            suggested_action=action,
            entry_zone=entry_zone,
            target=target,
            stop=stop,
            risk_reward=risk_reward,
            explanation=f"Power hour trend continuation. Day return: {day_return:.1%}, {'above' if vwap_position > 0 else 'below'} VWAP.",
            data_points={
                'day_return': day_return,
                'vwap_position': vwap_position,
                'vwap': vwap
            },
            confidence=score * 0.75,
            time_sensitivity="minutes"
        )

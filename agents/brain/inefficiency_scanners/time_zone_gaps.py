"""
Time Zone Gap Scanner

Detects overnight and pre-market gaps that often fill during regular hours.

WHY THIS WORKS:
- Markets open/close at different times globally
- Overnight news creates gaps that often overshoot
- Gap fills are statistically reliable (60-70% fill rate)
- Pre-market is thin liquidity = exaggerated moves

THE EDGE:
- Most gaps fill within the same day (especially small gaps)
- Large gaps often fill partially
- Gaps on no news fill faster than news-driven gaps

WHY ALGOS STRUGGLE:
- Gap trading requires PATIENCE (algos want instant fills)
- News interpretation (is this gap justified?)
- Thin pre-market = bad fills for large orders
- Position sizing for overnight risk
"""
import asyncio
from typing import List, Optional
from datetime import datetime, time as dt_time
from loguru import logger

try:
    import yfinance as yf
    import pandas as pd
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from agents.brain.market_brain import (
    Inefficiency, InefficiencyType, EdgeReason
)


class TimeZoneGapScanner:
    """
    Scans for gap fill opportunities.

    Types of gaps:
    1. Overnight gap (previous close vs today open)
    2. Pre-market gap (today open vs pre-market high/low)
    3. Weekend gap (Friday close vs Monday open)

    Strategy: Fade gaps, expect partial/full fills
    """

    def __init__(self):
        # Stocks that gap frequently and fill reliably
        self.watchlist = [
            # Index ETFs (most reliable gap fills)
            'SPY', 'QQQ', 'IWM', 'DIA',
            # Liquid large caps
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA',
            # Volatile stocks (bigger gaps)
            'AMD', 'NFLX', 'COIN', 'GME', 'AMC',
            # Leveraged (exaggerated gaps)
            'TQQQ', 'SQQQ', 'SPXL', 'SPXS'
        ]

        # Thresholds
        self.min_gap_pct = 0.5    # Minimum 0.5% gap to consider
        self.max_gap_pct = 5.0    # Gaps > 5% often don't fill same day
        self.gap_fill_prob = 0.65  # Historical gap fill rate

    async def scan(self) -> List[Inefficiency]:
        """Scan for gap fill opportunities"""
        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available for gap scan")
            return []

        # Only run during market hours or pre-market
        now = datetime.now()
        current_time = now.time()

        # Pre-market (4am-9:30am) or market hours (9:30am-4pm) EST
        # Adjust for your timezone
        if not (dt_time(4, 0) <= current_time <= dt_time(16, 0)):
            logger.debug("Gap scanner: Outside trading hours")
            return []

        inefficiencies = []

        for symbol in self.watchlist:
            try:
                ineff = await self._analyze_gap(symbol)
                if ineff:
                    inefficiencies.append(ineff)
            except Exception as e:
                logger.debug(f"Error analyzing gap for {symbol}: {e}")
                continue

        return inefficiencies

    async def _analyze_gap(self, symbol: str) -> Optional[Inefficiency]:
        """Analyze a single symbol for gap opportunity"""
        try:
            ticker = yf.Ticker(symbol)

            # Get today's and yesterday's data
            hist = ticker.history(period="5d", interval="1d")
            if hist.empty or len(hist) < 2:
                return None

            # Get intraday data for today
            intraday = ticker.history(period="1d", interval="5m")

            # Previous close and today's open
            prev_close = hist['Close'].iloc[-2]
            today_open = hist['Open'].iloc[-1]
            current_price = hist['Close'].iloc[-1]

            # Calculate gap
            gap_pct = ((today_open / prev_close) - 1) * 100
            gap_direction = "up" if gap_pct > 0 else "down"

            # Skip if gap too small or too large
            if abs(gap_pct) < self.min_gap_pct:
                return None
            if abs(gap_pct) > self.max_gap_pct:
                return None  # Large gaps often don't fill same day

            # Check if gap already filled
            if gap_direction == "up":
                gap_filled = current_price <= prev_close
                fill_progress = 1 - ((current_price - prev_close) / (today_open - prev_close)) if (today_open - prev_close) != 0 else 0
            else:
                gap_filled = current_price >= prev_close
                fill_progress = 1 - ((prev_close - current_price) / (prev_close - today_open)) if (prev_close - today_open) != 0 else 0

            fill_progress = max(0, min(1, fill_progress))

            # Skip if gap already filled
            if gap_filled:
                return None

            # Calculate score based on gap characteristics
            # Smaller gaps fill more reliably
            size_factor = 1 - (abs(gap_pct) / self.max_gap_pct)

            # Gaps that have started filling are more likely to complete
            momentum_factor = fill_progress * 0.3

            # Base probability
            score = (self.gap_fill_prob * size_factor) + momentum_factor
            score = min(0.95, score)

            # Direction: FADE the gap
            if gap_direction == "up":
                direction = "short"
                action = f"FADE GAP DOWN: {symbol} gapped up {gap_pct:.1f}%, expect fill to ${prev_close:.2f}"
                target = prev_close
                stop = today_open * 1.01  # Stop just above gap high
            else:
                direction = "long"
                action = f"FADE GAP UP: {symbol} gapped down {gap_pct:.1f}%, expect fill to ${prev_close:.2f}"
                target = prev_close
                stop = today_open * 0.99  # Stop just below gap low

            # Entry zone around current price
            entry_zone = (current_price * 0.998, current_price * 1.002)

            # Risk/Reward
            risk = abs(current_price - stop)
            reward = abs(target - current_price)
            risk_reward = reward / risk if risk > 0 else 0

            # Skip if R:R is bad
            if risk_reward < 1.5:
                return None

            explanation = (
                f"Gap {gap_direction} {abs(gap_pct):.1f}% from ${prev_close:.2f} to ${today_open:.2f}. "
                f"Currently at ${current_price:.2f} ({fill_progress:.0%} filled). "
                f"Gaps fill ~{self.gap_fill_prob:.0%} of the time. "
                f"Smaller gaps fill more reliably."
            )

            return Inefficiency(
                id=f"gap_{symbol}_{datetime.now().strftime('%Y%m%d%H%M')}",
                type=InefficiencyType.TIME_ZONE_GAP,
                symbol=symbol,
                score=score,
                edge_reason=EdgeReason.TIME_HORIZON,
                direction=direction,
                suggested_action=action,
                entry_zone=entry_zone,
                target=target,
                stop=stop,
                risk_reward=risk_reward,
                explanation=explanation,
                data_points={
                    'gap_pct': gap_pct,
                    'gap_direction': gap_direction,
                    'prev_close': prev_close,
                    'today_open': today_open,
                    'current_price': current_price,
                    'fill_progress': fill_progress
                },
                confidence=score * 0.9,
                time_sensitivity="hours"  # Gaps usually fill same day
            )

        except Exception as e:
            logger.debug(f"Gap analysis failed for {symbol}: {e}")
            return None

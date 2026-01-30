"""
Volatility Mispricing Scanner

Detects when implied volatility (IV) diverges significantly from realized volatility.

WHY THIS WORKS:
- Options are priced on EXPECTED volatility (IV)
- But IV often overshoots or undershoots ACTUAL volatility
- After earnings/events, IV often stays elevated too long
- Fear spikes cause IV to overshoot (premium selling opportunity)

THE EDGE:
- IV > Realized by 20%+ = Sell premium (iron condors, strangles)
- IV < Realized by 20%+ = Buy options (cheap vol)
- Post-earnings IV crush is predictable

WHY ALGOS STRUGGLE:
- Vol forecasting is HARD - models disagree
- Event interpretation (will earnings move it 5% or 15%?)
- Algos often follow each other, creating overshoots
- Small accounts can trade illiquid strikes algos avoid
"""
import asyncio
from typing import List, Optional
from datetime import datetime
from loguru import logger
import math

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


class VolatilityMispricingScanner:
    """
    Scans for volatility mispricings between IV and realized vol.

    Opportunities:
    1. IV >> Realized: Sell premium (market overpricing fear)
    2. IV << Realized: Buy options (market underpricing movement)
    3. IV Crush setup: High IV before known event
    """

    def __init__(self):
        # High-volume options stocks
        self.watchlist = [
            # Most liquid options
            'SPY', 'QQQ', 'IWM', 'AAPL', 'TSLA', 'NVDA', 'AMD', 'META',
            'AMZN', 'GOOGL', 'MSFT', 'NFLX',
            # High IV stocks
            'GME', 'AMC', 'COIN', 'MARA', 'RIOT',
            # Sector ETFs
            'XLF', 'XLE', 'XLK',
            # Retail macro - LOOK macro but retail-heavy
            'GLD', 'SLV',  # Precious metals (fear trade)
            'TQQQ', 'SQQQ'  # Leveraged (pure retail speculation)
            # NO TLT, bonds - truly Fed driven
        ]

        # Thresholds
        self.iv_premium_threshold = 0.25  # IV 25% above realized = sell
        self.iv_discount_threshold = 0.20  # IV 20% below realized = buy
        self.min_iv = 0.15  # Ignore if IV below 15% (not interesting)

    async def scan(self) -> List[Inefficiency]:
        """Scan for volatility mispricings"""
        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available for vol mispricing scan")
            return []

        inefficiencies = []

        for symbol in self.watchlist:
            try:
                ineff = await self._analyze_symbol(symbol)
                if ineff:
                    inefficiencies.append(ineff)
            except Exception as e:
                logger.debug(f"Error analyzing {symbol} vol: {e}")
                continue

        return inefficiencies

    async def _analyze_symbol(self, symbol: str) -> Optional[Inefficiency]:
        """Analyze volatility for a single symbol"""
        try:
            ticker = yf.Ticker(symbol)

            # Get historical data for realized vol calculation
            hist = ticker.history(period="60d", interval="1d")
            if hist.empty or len(hist) < 20:
                return None

            # Calculate realized volatility (20-day)
            returns = hist['Close'].pct_change().dropna()
            realized_vol_20d = returns.tail(20).std() * math.sqrt(252)

            # Calculate 10-day realized vol (recent)
            realized_vol_10d = returns.tail(10).std() * math.sqrt(252)

            # Get options data for IV
            try:
                options_dates = ticker.options
                if not options_dates:
                    return None

                # Get ATM options for IV estimate
                current_price = hist['Close'].iloc[-1]
                nearest_exp = options_dates[0]
                opt_chain = ticker.option_chain(nearest_exp)

                # Find ATM call
                calls = opt_chain.calls
                if calls.empty:
                    return None

                # Get closest to ATM
                calls['diff'] = abs(calls['strike'] - current_price)
                atm_call = calls.loc[calls['diff'].idxmin()]

                implied_vol = atm_call.get('impliedVolatility', 0)
                if implied_vol == 0 or pd.isna(implied_vol):
                    return None

            except Exception as e:
                logger.debug(f"Options data error for {symbol}: {e}")
                return None

            # Skip low IV environments
            if implied_vol < self.min_iv:
                return None

            # Calculate IV vs Realized ratio
            iv_premium = (implied_vol / realized_vol_20d) - 1 if realized_vol_20d > 0 else 0

            # Detect mispricing
            score = 0.0
            direction = "neutral"
            explanation = ""
            action = ""

            # IV TOO HIGH (sell premium opportunity)
            if iv_premium > self.iv_premium_threshold:
                score = min(1.0, iv_premium / 0.5)  # Normalize: 50% premium = score 1.0
                direction = "short"  # Short vol = sell options
                explanation = (
                    f"IV overpriced: {implied_vol:.0%} IV vs {realized_vol_20d:.0%} realized "
                    f"(premium: {iv_premium:.0%}). Market overpricing fear/movement. "
                    f"Recent 10d realized: {realized_vol_10d:.0%}."
                )
                action = f"SELL PREMIUM: Iron condor or strangle on {symbol}"

            # IV TOO LOW (buy options opportunity)
            elif iv_premium < -self.iv_discount_threshold:
                score = min(1.0, abs(iv_premium) / 0.4)
                direction = "long"  # Long vol = buy options
                explanation = (
                    f"IV underpriced: {implied_vol:.0%} IV vs {realized_vol_20d:.0%} realized "
                    f"(discount: {abs(iv_premium):.0%}). Options are cheap. "
                    f"Recent 10d realized: {realized_vol_10d:.0%}."
                )
                action = f"BUY OPTIONS: Straddle or calls/puts on {symbol} - cheap vol"

            else:
                return None  # No mispricing

            if score < 0.3:
                return None

            # Calculate trade parameters
            # For vol trades, we use % of stock price as targets
            entry_zone = (current_price * 0.98, current_price * 1.02)

            if direction == "short":
                # Selling premium: target is premium decay, risk is vol spike
                # Use iron condor logic: wings at 1 std dev
                target = current_price  # Price stays here = win
                stop = current_price * (1 + realized_vol_20d / 4)  # Stop at 1 weekly std dev move
                risk_reward = 2.0  # Typical for premium selling
            else:
                # Buying options: target is movement, risk is premium paid
                target = current_price * (1 + realized_vol_20d / 4)  # 1 weekly move
                stop = current_price * 0.97  # 3% stop (premium loss)
                risk_reward = 3.0  # We want big payoffs when buying vol

            return Inefficiency(
                id=f"vol_{symbol}_{datetime.now().strftime('%Y%m%d%H%M')}",
                type=InefficiencyType.VOLATILITY_MISPRICING,
                symbol=symbol,
                score=score,
                edge_reason=EdgeReason.COMPLEXITY,
                direction=direction,
                suggested_action=action,
                entry_zone=entry_zone,
                target=target,
                stop=stop,
                risk_reward=risk_reward,
                explanation=explanation,
                data_points={
                    'implied_vol': implied_vol,
                    'realized_vol_20d': realized_vol_20d,
                    'realized_vol_10d': realized_vol_10d,
                    'iv_premium': iv_premium,
                    'current_price': current_price
                },
                confidence=min(0.85, score),
                time_sensitivity="days"  # Vol trades can take days to play out
            )

        except Exception as e:
            logger.debug(f"Vol analysis failed for {symbol}: {e}")
            return None

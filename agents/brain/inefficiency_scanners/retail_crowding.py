"""
Retail Crowding Scanner

Detects when retail traders are piling into a stock - prime fade opportunity.

WHY THIS WORKS:
- Retail tends to buy at tops (FOMO) and sell at bottoms (panic)
- When put/call ratio is extremely low = retail is all-in bullish
- When social media sentiment hits extreme = usually wrong
- Retail chases momentum AFTER the move, not before

SIGNALS WE TRACK:
1. Put/Call ratio extremes (< 0.5 = too bullish, > 1.5 = too bearish)
2. Unusual call buying in OTM strikes (lottery ticket behavior)
3. Volume spikes on no news (retail discovery)
4. Social sentiment extremes (future feature: Reddit/Twitter)

ALGO EDGE: Algos can't model human FOMO well. They see order flow,
but can't distinguish "smart" institutional flow from retail YOLO.
"""
import asyncio
from typing import List, Optional
from datetime import datetime, timedelta
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


class RetailCrowdingScanner:
    """
    Scans for retail crowding inefficiencies.

    When retail piles in:
    - Extremely low put/call = FADE (go short/buy puts)
    - Extremely high put/call = contrarian BUY

    We're trading against the crowd, not with them.
    """

    def __init__(self):
        # Stocks retail loves to crowd into
        self.watchlist = [
            # Meme favorites
            'GME', 'AMC', 'BBBY', 'BB', 'PLTR', 'SOFI',
            # Tech retail loves
            'TSLA', 'NVDA', 'AMD', 'AAPL', 'META',
            # Speculative
            'RIVN', 'LCID', 'HOOD', 'COIN', 'MARA', 'RIOT',
            # ETFs retail trades
            'SPY', 'QQQ', 'TQQQ', 'SQQQ', 'ARKK',
            # Small caps with retail interest
            'IONQ', 'RKLB', 'JOBY', 'DNA'
        ]

        # Thresholds
        self.bullish_extreme_pc = 0.5   # P/C below this = too bullish
        self.bearish_extreme_pc = 1.5   # P/C above this = too bearish
        self.volume_spike_threshold = 2.5  # 2.5x average volume

    async def scan(self) -> List[Inefficiency]:
        """Scan for retail crowding inefficiencies"""
        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available for retail crowding scan")
            return []

        inefficiencies = []

        for symbol in self.watchlist:
            try:
                ineff = await self._analyze_symbol(symbol)
                if ineff:
                    inefficiencies.append(ineff)
            except Exception as e:
                logger.debug(f"Error analyzing {symbol}: {e}")
                continue

        return inefficiencies

    async def _analyze_symbol(self, symbol: str) -> Optional[Inefficiency]:
        """Analyze a single symbol for retail crowding"""
        try:
            ticker = yf.Ticker(symbol)

            # Get recent price data
            hist = ticker.history(period="5d", interval="1h")
            if hist.empty or len(hist) < 10:
                return None

            # Get options data for put/call analysis
            try:
                options_dates = ticker.options
                if not options_dates:
                    return None

                # Get nearest expiration
                nearest_exp = options_dates[0]
                opt_chain = ticker.option_chain(nearest_exp)
                calls = opt_chain.calls
                puts = opt_chain.puts
            except:
                return None

            # Calculate put/call ratio by volume
            total_call_vol = calls['volume'].sum() if 'volume' in calls.columns else 0
            total_put_vol = puts['volume'].sum() if 'volume' in puts.columns else 0

            if total_call_vol == 0:
                return None

            pc_ratio = total_put_vol / total_call_vol if total_call_vol > 0 else 1.0

            # Calculate volume spike
            current_vol = hist['Volume'].iloc[-1] if 'Volume' in hist.columns else 0
            avg_vol = hist['Volume'].mean() if 'Volume' in hist.columns else 1
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

            # Current price info
            current_price = hist['Close'].iloc[-1]
            price_change_5d = ((current_price / hist['Close'].iloc[0]) - 1) * 100

            # Detect crowding
            crowding_score = 0.0
            direction = "neutral"
            explanation = ""
            action = ""

            # BULLISH CROWDING (retail too bullish = FADE)
            if pc_ratio < self.bullish_extreme_pc:
                crowding_score = (self.bullish_extreme_pc - pc_ratio) / self.bullish_extreme_pc
                direction = "short"
                explanation = (
                    f"Retail extremely bullish: P/C ratio {pc_ratio:.2f} "
                    f"(threshold: {self.bullish_extreme_pc}). "
                    f"Price up {price_change_5d:+.1f}% in 5 days. "
                    f"Crowd is likely wrong at extremes."
                )
                action = f"FADE: Buy puts or short {symbol} - retail overextended"

                # Boost score if also volume spike (retail discovery)
                if vol_ratio > self.volume_spike_threshold:
                    crowding_score = min(1.0, crowding_score + 0.2)
                    explanation += f" Volume {vol_ratio:.1f}x normal (retail piling in)."

            # BEARISH CROWDING (retail too bearish = contrarian BUY)
            elif pc_ratio > self.bearish_extreme_pc:
                crowding_score = (pc_ratio - self.bearish_extreme_pc) / self.bearish_extreme_pc
                crowding_score = min(1.0, crowding_score)
                direction = "long"
                explanation = (
                    f"Retail extremely bearish: P/C ratio {pc_ratio:.2f} "
                    f"(threshold: {self.bearish_extreme_pc}). "
                    f"Price down {price_change_5d:+.1f}% in 5 days. "
                    f"Contrarian opportunity - retail capitulating."
                )
                action = f"CONTRARIAN BUY: {symbol} - retail fear at extreme"

            else:
                return None  # No extreme = no inefficiency

            # Only return if score is significant
            if crowding_score < 0.3:
                return None

            # Calculate trade levels
            atr = self._calculate_atr(hist)
            if direction == "short":
                entry_zone = (current_price * 0.99, current_price * 1.01)
                target = current_price - (2 * atr)
                stop = current_price + (1 * atr)
            else:
                entry_zone = (current_price * 0.99, current_price * 1.01)
                target = current_price + (2 * atr)
                stop = current_price - (1 * atr)

            risk = abs(current_price - stop)
            reward = abs(target - current_price)
            risk_reward = reward / risk if risk > 0 else 0

            return Inefficiency(
                id=f"retail_{symbol}_{datetime.now().strftime('%Y%m%d%H%M')}",
                type=InefficiencyType.RETAIL_CROWDING,
                symbol=symbol,
                score=crowding_score,
                edge_reason=EdgeReason.BEHAVIORAL,
                direction=direction,
                suggested_action=action,
                entry_zone=entry_zone,
                target=target,
                stop=stop,
                risk_reward=risk_reward,
                explanation=explanation,
                data_points={
                    'put_call_ratio': pc_ratio,
                    'volume_ratio': vol_ratio,
                    'price_change_5d': price_change_5d,
                    'current_price': current_price
                },
                confidence=min(0.9, crowding_score + 0.1),
                time_sensitivity="hours"
            )

        except Exception as e:
            logger.debug(f"Retail crowding analysis failed for {symbol}: {e}")
            return None

    def _calculate_atr(self, hist, period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(hist) < period:
            return hist['Close'].std() if 'Close' in hist.columns else 1.0

        high = hist['High']
        low = hist['Low']
        close = hist['Close'].shift(1)

        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]

        return atr if pd.notna(atr) else hist['Close'].std()

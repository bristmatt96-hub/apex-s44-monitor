"""
Behavioral Edge Analyzer - Core Trading Philosophy

THE ALPHA: Trade against human psychological weaknesses.

Retail traders consistently make predictable emotional mistakes:
- PANIC SELLING: Dump at the bottom on fear (we buy)
- FOMO BUYING: Chase at the top on greed (we sell/short)
- REVENGE TRADING: Double down after losses (we fade)
- CAPITULATION: Give up at worst moment (we accumulate)
- EUPHORIA: "This time is different" (we take profits)

This module identifies these emotional extremes and generates
high-probability counter-trades.

"Be fearful when others are greedy, greedy when others are fearful."
- Warren Buffett
"""

import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
from loguru import logger

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import pandas_ta as ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False


class EmotionalState(Enum):
    """Market emotional states we can exploit"""
    EXTREME_FEAR = "extreme_fear"       # Buy signal
    FEAR = "fear"                        # Potential buy
    NEUTRAL = "neutral"                  # No edge
    GREED = "greed"                      # Potential sell
    EXTREME_GREED = "extreme_greed"     # Sell/short signal
    CAPITULATION = "capitulation"        # Strong buy
    EUPHORIA = "euphoria"                # Strong sell


@dataclass
class BehavioralSignal:
    """A signal based on human behavioral weakness"""
    symbol: str
    emotional_state: EmotionalState
    weakness_type: str  # What human weakness are we exploiting
    confidence: float   # 0-1
    direction: str      # 'buy' or 'sell'
    reasoning: List[str]
    indicators: Dict[str, float]
    timestamp: datetime


class BehavioralEdgeAnalyzer:
    """
    Identifies opportunities to trade against human emotional mistakes.

    This is the CORE EDGE of the system. All other analysis (technical,
    fundamental) is secondary to identifying emotional extremes.

    Key Principles:
    1. Retail loses money because they trade emotionally
    2. Emotions create predictable price patterns
    3. We profit by taking the other side of emotional decisions
    4. The books teach us HOW to identify emotions, but the
       strategy is simple: fade the crowd at extremes
    """

    def __init__(self):
        self.min_confidence = 0.60

        # Thresholds for emotional detection
        self.thresholds = {
            # RSI extremes
            'rsi_panic': 25,           # Below = panic selling
            'rsi_fear': 30,            # Below = fear
            'rsi_greed': 70,           # Above = greed
            'rsi_euphoria': 80,        # Above = euphoria

            # Volume spikes (vs 20-day average)
            'volume_panic': 3.0,       # 3x volume on red day = panic
            'volume_fomo': 2.5,        # 2.5x volume on green day = FOMO
            'volume_capitulation': 4.0, # 4x volume = capitulation

            # Price moves (single day)
            'panic_drop_pct': -5.0,    # 5%+ drop on volume = panic
            'fomo_spike_pct': 7.0,     # 7%+ spike = FOMO

            # Consecutive moves
            'consecutive_red': 5,       # 5+ red days = fear building
            'consecutive_green': 5,     # 5+ green days = greed building
        }

    async def analyze(self, symbol: str, data: pd.DataFrame) -> Optional[BehavioralSignal]:
        """
        Analyze price/volume data for emotional extremes.

        Returns a signal if human weakness is detected.
        """
        if not PANDAS_AVAILABLE or data is None or len(data) < 20:
            return None

        try:
            # Standardize column names
            data.columns = [c.lower() for c in data.columns]

            # Calculate indicators
            indicators = self._calculate_indicators(data)

            # Check for each type of emotional extreme
            signals = []

            # 1. PANIC SELLING - Best opportunity
            panic_signal = self._check_panic_selling(symbol, data, indicators)
            if panic_signal:
                signals.append(panic_signal)

            # 2. CAPITULATION - Even stronger buy
            cap_signal = self._check_capitulation(symbol, data, indicators)
            if cap_signal:
                signals.append(cap_signal)

            # 3. FOMO BUYING - Fade the rally
            fomo_signal = self._check_fomo_buying(symbol, data, indicators)
            if fomo_signal:
                signals.append(fomo_signal)

            # 4. EUPHORIA - Strong sell signal
            euph_signal = self._check_euphoria(symbol, data, indicators)
            if euph_signal:
                signals.append(euph_signal)

            # 5. FEAR BUILDING - Early buy opportunity
            fear_signal = self._check_fear_building(symbol, data, indicators)
            if fear_signal:
                signals.append(fear_signal)

            # Return highest confidence signal
            if signals:
                best = max(signals, key=lambda s: s.confidence)
                if best.confidence >= self.min_confidence:
                    return best

            return None

        except Exception as e:
            logger.debug(f"Behavioral analysis error for {symbol}: {e}")
            return None

    def _calculate_indicators(self, data: pd.DataFrame) -> Dict[str, float]:
        """Calculate indicators for emotional state detection"""
        close = data['close']
        volume = data['volume']
        high = data['high']
        low = data['low']

        indicators = {}

        # RSI
        if TA_AVAILABLE:
            rsi = ta.rsi(close, length=14)
            indicators['rsi'] = rsi.iloc[-1] if rsi is not None else 50
        else:
            # Simple RSI calculation
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            indicators['rsi'] = float(100 - (100 / (1 + rs.iloc[-1])))

        # Volume analysis
        avg_volume = volume.rolling(20).mean().iloc[-1]
        current_volume = volume.iloc[-1]
        indicators['volume_ratio'] = current_volume / avg_volume if avg_volume > 0 else 1

        # Price change
        indicators['daily_change_pct'] = ((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2]) * 100

        # Multi-day change
        indicators['5day_change_pct'] = ((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6]) * 100

        # Consecutive days
        indicators['consecutive_red'] = self._count_consecutive_red(data)
        indicators['consecutive_green'] = self._count_consecutive_green(data)

        # Distance from recent high/low
        recent_high = high.tail(20).max()
        recent_low = low.tail(20).min()
        current = close.iloc[-1]
        indicators['pct_from_high'] = ((current - recent_high) / recent_high) * 100
        indicators['pct_from_low'] = ((current - recent_low) / recent_low) * 100

        # Volatility spike
        daily_returns = close.pct_change()
        avg_volatility = daily_returns.tail(20).std()
        today_move = abs(daily_returns.iloc[-1])
        indicators['volatility_ratio'] = today_move / avg_volatility if avg_volatility > 0 else 1

        # Is today red or green?
        indicators['is_red_day'] = close.iloc[-1] < data['open'].iloc[-1]
        indicators['is_green_day'] = close.iloc[-1] > data['open'].iloc[-1]

        return indicators

    def _count_consecutive_red(self, data: pd.DataFrame) -> int:
        """Count consecutive red (down) days"""
        count = 0
        for i in range(len(data) - 1, 0, -1):
            if data['close'].iloc[i] < data['close'].iloc[i-1]:
                count += 1
            else:
                break
        return count

    def _count_consecutive_green(self, data: pd.DataFrame) -> int:
        """Count consecutive green (up) days"""
        count = 0
        for i in range(len(data) - 1, 0, -1):
            if data['close'].iloc[i] > data['close'].iloc[i-1]:
                count += 1
            else:
                break
        return count

    def _check_panic_selling(
        self, symbol: str, data: pd.DataFrame, ind: Dict
    ) -> Optional[BehavioralSignal]:
        """
        Detect panic selling - retail dumping on fear.

        We BUY when:
        - Big red candle (5%+ drop)
        - High volume (3x+ average)
        - RSI oversold (<30)

        Human weakness: Fear causes selling at worst prices
        Our edge: Buy when they panic, sell when they calm down
        """
        reasons = []
        confidence = 0.0

        # Big red day with volume
        if ind['daily_change_pct'] <= self.thresholds['panic_drop_pct']:
            if ind['volume_ratio'] >= self.thresholds['volume_panic']:
                confidence += 0.35
                reasons.append(f"Panic drop: {ind['daily_change_pct']:.1f}% on {ind['volume_ratio']:.1f}x volume")

        # RSI in panic zone
        if ind['rsi'] <= self.thresholds['rsi_panic']:
            confidence += 0.30
            reasons.append(f"RSI at panic levels: {ind['rsi']:.0f}")
        elif ind['rsi'] <= self.thresholds['rsi_fear']:
            confidence += 0.15
            reasons.append(f"RSI showing fear: {ind['rsi']:.0f}")

        # Multiple red days building fear
        if ind['consecutive_red'] >= 3:
            confidence += 0.10 * min(ind['consecutive_red'] - 2, 3)
            reasons.append(f"{ind['consecutive_red']} consecutive red days - fear building")

        # Volatility spike (emotional trading)
        if ind['volatility_ratio'] > 2.0:
            confidence += 0.10
            reasons.append(f"Volatility spike: {ind['volatility_ratio']:.1f}x normal")

        if confidence >= 0.50 and reasons:
            return BehavioralSignal(
                symbol=symbol,
                emotional_state=EmotionalState.EXTREME_FEAR,
                weakness_type="PANIC_SELLING",
                confidence=min(confidence, 0.95),
                direction='buy',
                reasoning=[
                    "🎯 HUMAN WEAKNESS: Retail panic selling on fear",
                    "💡 OUR EDGE: Buy their fear, sell their relief",
                    *reasons
                ],
                indicators=ind,
                timestamp=datetime.now()
            )

        return None

    def _check_capitulation(
        self, symbol: str, data: pd.DataFrame, ind: Dict
    ) -> Optional[BehavioralSignal]:
        """
        Detect capitulation - complete surrender by retail.

        This is the BEST buy signal. Retail has given up entirely.

        Signs:
        - Extreme volume (4x+)
        - Deep oversold RSI (<25)
        - Multiple red days
        - "It will never recover" sentiment

        Human weakness: Giving up at the bottom
        Our edge: Maximum pessimism = maximum opportunity
        """
        reasons = []
        confidence = 0.0

        # Extreme volume on red day
        if ind['is_red_day'] and ind['volume_ratio'] >= self.thresholds['volume_capitulation']:
            confidence += 0.40
            reasons.append(f"Capitulation volume: {ind['volume_ratio']:.1f}x average on red day")

        # Extreme RSI
        if ind['rsi'] <= 20:
            confidence += 0.35
            reasons.append(f"Extreme oversold RSI: {ind['rsi']:.0f}")

        # Far from recent high (capitulation often happens after big drawdown)
        if ind['pct_from_high'] <= -20:
            confidence += 0.15
            reasons.append(f"Down {abs(ind['pct_from_high']):.0f}% from recent high")

        # Many consecutive red days
        if ind['consecutive_red'] >= 5:
            confidence += 0.15
            reasons.append(f"{ind['consecutive_red']} straight red days - capitulation territory")

        if confidence >= 0.60 and reasons:
            return BehavioralSignal(
                symbol=symbol,
                emotional_state=EmotionalState.CAPITULATION,
                weakness_type="CAPITULATION",
                confidence=min(confidence, 0.95),
                direction='buy',
                reasoning=[
                    "🎯 HUMAN WEAKNESS: Complete capitulation - retail has given up",
                    "💡 OUR EDGE: 'Blood in the streets' = best buying opportunity",
                    "📚 Book wisdom: 'Maximum pessimism is the best time to buy'",
                    *reasons
                ],
                indicators=ind,
                timestamp=datetime.now()
            )

        return None

    def _check_fomo_buying(
        self, symbol: str, data: pd.DataFrame, ind: Dict
    ) -> Optional[BehavioralSignal]:
        """
        Detect FOMO (Fear Of Missing Out) buying.

        Retail chases after the price has already moved.
        They buy the top because they're afraid of missing more gains.

        Signs:
        - Big green candle (7%+)
        - High volume chase (2.5x+)
        - RSI overbought (>70)

        Human weakness: FOMO causes buying at worst prices
        Our edge: Let them chase, we take profits
        """
        reasons = []
        confidence = 0.0

        # Big green day with volume
        if ind['daily_change_pct'] >= self.thresholds['fomo_spike_pct']:
            if ind['volume_ratio'] >= self.thresholds['volume_fomo']:
                confidence += 0.35
                reasons.append(f"FOMO spike: +{ind['daily_change_pct']:.1f}% on {ind['volume_ratio']:.1f}x volume")

        # RSI overbought
        if ind['rsi'] >= self.thresholds['rsi_greed']:
            confidence += 0.25
            reasons.append(f"RSI overbought: {ind['rsi']:.0f}")

        # Multiple green days (FOMO building)
        if ind['consecutive_green'] >= 4:
            confidence += 0.15
            reasons.append(f"{ind['consecutive_green']} green days in a row - FOMO building")

        # Near recent high (chasing)
        if ind['pct_from_high'] >= -2:
            confidence += 0.10
            reasons.append("Trading near recent highs - late buyers entering")

        if confidence >= 0.55 and reasons:
            return BehavioralSignal(
                symbol=symbol,
                emotional_state=EmotionalState.GREED,
                weakness_type="FOMO_BUYING",
                confidence=min(confidence, 0.90),
                direction='sell',  # Take profits or short
                reasoning=[
                    "🎯 HUMAN WEAKNESS: FOMO - retail chasing after the move",
                    "💡 OUR EDGE: We sell to the FOMO buyers",
                    *reasons
                ],
                indicators=ind,
                timestamp=datetime.now()
            )

        return None

    def _check_euphoria(
        self, symbol: str, data: pd.DataFrame, ind: Dict
    ) -> Optional[BehavioralSignal]:
        """
        Detect euphoria - "This time is different" mentality.

        Peak greed. Everyone is bullish. "Easy money."
        This is when smart money sells to retail.

        Signs:
        - Extreme RSI (>80)
        - Parabolic move (multiple big green days)
        - Volume exhaustion

        Human weakness: Euphoria blinds to risk
        Our edge: Sell the euphoria, buy the despair
        """
        reasons = []
        confidence = 0.0

        # Extreme RSI
        if ind['rsi'] >= self.thresholds['rsi_euphoria']:
            confidence += 0.40
            reasons.append(f"Euphoric RSI: {ind['rsi']:.0f}")

        # Multiple strong green days
        if ind['consecutive_green'] >= 5 and ind['5day_change_pct'] >= 15:
            confidence += 0.30
            reasons.append(f"Parabolic move: +{ind['5day_change_pct']:.0f}% in 5 days")

        # At all-time or recent highs with volume
        if ind['pct_from_high'] >= -1 and ind['volume_ratio'] >= 2.0:
            confidence += 0.20
            reasons.append("Breaking highs on volume - euphoria peak")

        if confidence >= 0.60 and reasons:
            return BehavioralSignal(
                symbol=symbol,
                emotional_state=EmotionalState.EUPHORIA,
                weakness_type="EUPHORIA",
                confidence=min(confidence, 0.90),
                direction='sell',
                reasoning=[
                    "🎯 HUMAN WEAKNESS: Euphoria - 'This time is different'",
                    "💡 OUR EDGE: When everyone is bullish, we take profits",
                    "📚 Book wisdom: 'Sell when others are greedy'",
                    *reasons
                ],
                indicators=ind,
                timestamp=datetime.now()
            )

        return None

    def _check_fear_building(
        self, symbol: str, data: pd.DataFrame, ind: Dict
    ) -> Optional[BehavioralSignal]:
        """
        Detect fear building - not panic yet, but getting close.

        Early opportunity to position before capitulation.

        Signs:
        - RSI approaching oversold (30-40)
        - Multiple red days (3-4)
        - Increasing volume on down days

        Human weakness: Fear snowballs
        Our edge: Start building position before the panic
        """
        reasons = []
        confidence = 0.0

        # RSI in fear zone but not panic yet
        if 30 < ind['rsi'] <= 40:
            confidence += 0.30
            reasons.append(f"RSI in fear zone: {ind['rsi']:.0f}")

        # Several red days
        if 3 <= ind['consecutive_red'] < 5:
            confidence += 0.25
            reasons.append(f"{ind['consecutive_red']} red days - fear building")

        # Down from highs
        if -15 <= ind['pct_from_high'] <= -8:
            confidence += 0.20
            reasons.append(f"Down {abs(ind['pct_from_high']):.0f}% from high - weakness showing")

        # Volume increasing (emotional trading starting)
        if 1.5 <= ind['volume_ratio'] < 3.0:
            confidence += 0.15
            reasons.append(f"Volume increasing: {ind['volume_ratio']:.1f}x - emotion entering")

        if confidence >= 0.55 and reasons:
            return BehavioralSignal(
                symbol=symbol,
                emotional_state=EmotionalState.FEAR,
                weakness_type="FEAR_BUILDING",
                confidence=min(confidence, 0.80),
                direction='buy',
                reasoning=[
                    "🎯 HUMAN WEAKNESS: Fear building - panic may follow",
                    "💡 OUR EDGE: Start position before full capitulation",
                    *reasons
                ],
                indicators=ind,
                timestamp=datetime.now()
            )

        return None

    def get_edge_multiplier(self, signal: BehavioralSignal) -> float:
        """
        Get score multiplier based on behavioral edge strength.

        Stronger human weakness = higher multiplier.
        """
        multipliers = {
            EmotionalState.CAPITULATION: 1.30,    # Best opportunity
            EmotionalState.EXTREME_FEAR: 1.25,
            EmotionalState.FEAR: 1.15,
            EmotionalState.EXTREME_GREED: 1.20,   # Short/exit signal
            EmotionalState.EUPHORIA: 1.18,
            EmotionalState.GREED: 1.10,
            EmotionalState.NEUTRAL: 1.00,
        }

        base = multipliers.get(signal.emotional_state, 1.0)

        # Confidence adjustment
        return base * (0.8 + 0.4 * signal.confidence)


# Singleton
_analyzer_instance: Optional[BehavioralEdgeAnalyzer] = None


def get_behavioral_analyzer() -> BehavioralEdgeAnalyzer:
    """Get or create the behavioral edge analyzer"""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = BehavioralEdgeAnalyzer()
    return _analyzer_instance

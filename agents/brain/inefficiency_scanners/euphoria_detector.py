"""
Euphoria/Greed Detector

Detects when markets are overly bullish and it's time to take profits.

THE PHILOSOPHY:
"Be fearful when others are greedy, and greedy when others are fearful"
- Warren Buffett

WHEN EVERYONE IS GREEDY:
- VIX crushed below 12 (complacency)
- Put/call ratio very low (everyone buying calls)
- Stocks far above moving averages
- RSI overbought across the board
- "This time is different" headlines
- Retail FOMO at all-time highs

ACTION WHEN GREED DETECTED:
1. TAKE PROFITS on winners (lock in gains)
2. TIGHTEN STOPS (protect profits)
3. REDUCE POSITION SIZES (less exposure)
4. RAISE CASH (be ready for the dip)
5. DON'T CHASE (resist FOMO)

CAPITAL PRESERVATION IS #1:
- Profits aren't real until you sell
- Markets can stay irrational, but your capital can't
- Better to sell too early than too late
"""
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from loguru import logger

try:
    import yfinance as yf
    import numpy as np
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from agents.brain.market_brain import (
    Inefficiency, InefficiencyType, EdgeReason
)


@dataclass
class GreedState:
    """Current state of market greed/euphoria"""
    is_greedy: bool
    greed_score: float  # 0-1, higher = more greedy
    vix_level: float
    vix_percentile: float  # Where VIX is vs last year (low = complacent)
    put_call_ratio: float
    spy_above_200ma_pct: float  # How far SPY is above 200MA
    rsi: float
    detected_at: datetime

    # Components
    vix_signal: str  # "COMPLACENT", "NORMAL", "FEARFUL"
    momentum_signal: str  # "OVERBOUGHT", "NORMAL", "OVERSOLD"
    sentiment_signal: str  # "EUPHORIC", "NORMAL", "FEARFUL"


@dataclass
class ProfitTarget:
    """Suggestion to take profits"""
    symbol: str
    current_price: float
    gain_pct: float
    reason: str
    action: str  # "TAKE_PARTIAL", "TAKE_FULL", "TIGHTEN_STOP"
    urgency: str  # "HIGH", "MEDIUM", "LOW"


class EuphoriaDetector:
    """
    Detects market euphoria/greed conditions.

    When greed is high:
    - Suggests taking profits
    - Recommends tightening stops
    - Warns against new positions

    Key principle: SELL INTO STRENGTH
    """

    # Greed thresholds
    VIX_COMPLACENT = 13  # VIX below this = complacent
    VIX_VERY_COMPLACENT = 11  # Extreme complacency
    PUT_CALL_BULLISH = 0.7  # Below this = too bullish
    PUT_CALL_VERY_BULLISH = 0.5  # Extreme bullishness
    RSI_OVERBOUGHT = 70
    RSI_VERY_OVERBOUGHT = 80
    ABOVE_200MA_EXTENDED = 0.10  # 10% above 200MA = extended
    ABOVE_200MA_VERY_EXTENDED = 0.15  # 15% = very extended

    def __init__(self):
        self.greed_state: Optional[GreedState] = None
        self.last_check = None
        self.profit_suggestions: List[ProfitTarget] = []

        # Track positions for profit-taking suggestions
        self.tracked_positions: Dict[str, dict] = {}

    async def scan(self) -> List[Inefficiency]:
        """Main scan - detect greed and suggest profit-taking"""
        if not YFINANCE_AVAILABLE:
            return []

        inefficiencies = []

        # Step 1: Check greed conditions
        self.greed_state = await self._check_greed_conditions()

        if not self.greed_state.is_greedy:
            # Not in greed territory - no action needed
            return []

        logger.warning(
            f"🎰 GREED DETECTED: VIX {self.greed_state.vix_level:.1f} "
            f"(percentile: {self.greed_state.vix_percentile:.0%}), "
            f"Greed Score: {self.greed_state.greed_score:.2f}"
        )

        # Step 2: Create profit-taking suggestions
        self.profit_suggestions = await self._generate_profit_suggestions()

        # Step 3: Convert to inefficiencies (opportunities to take profits)
        for suggestion in self.profit_suggestions:
            ineff = self._create_profit_inefficiency(suggestion)
            if ineff:
                inefficiencies.append(ineff)

        # Step 4: Add general greed warning
        if self.greed_state.greed_score > 0.7:
            warning = Inefficiency(
                id=f"GREED_WARNING_{datetime.now().strftime('%Y%m%d')}",
                type=InefficiencyType.BEHAVIORAL,
                symbol="MARKET",
                score=self.greed_state.greed_score,
                edge_reason=EdgeReason.RETAIL_FOMO,
                description=self._get_greed_warning(),
                entry_trigger="Market showing signs of euphoria",
                time_sensitivity="days",
                expires_at=datetime.now() + timedelta(days=7),
                metadata={
                    'greed_score': self.greed_state.greed_score,
                    'vix': self.greed_state.vix_level,
                    'action': 'REDUCE_EXPOSURE'
                }
            )
            inefficiencies.append(warning)

        return inefficiencies

    async def _check_greed_conditions(self) -> GreedState:
        """Check all greed indicators"""
        try:
            # Get VIX data
            vix = yf.Ticker("^VIX")
            vix_hist = vix.history(period="1y")
            vix_current = vix_hist['Close'].iloc[-1] if len(vix_hist) > 0 else 20

            # VIX percentile (where current VIX sits vs last year)
            vix_percentile = (vix_hist['Close'] < vix_current).mean()

            # Get SPY data for momentum
            spy = yf.Ticker("SPY")
            spy_hist = spy.history(period="1y")

            if len(spy_hist) < 200:
                return self._default_greed_state()

            spy_current = spy_hist['Close'].iloc[-1]
            spy_200ma = spy_hist['Close'].rolling(200).mean().iloc[-1]
            spy_above_200ma = (spy_current - spy_200ma) / spy_200ma

            # Calculate RSI
            rsi = self._calculate_rsi(spy_hist['Close'])

            # Get put/call ratio (approximate from options volume)
            put_call = await self._get_put_call_ratio()

            # Calculate greed score components
            vix_score = self._score_vix(vix_current, vix_percentile)
            momentum_score = self._score_momentum(spy_above_200ma, rsi)
            sentiment_score = self._score_sentiment(put_call)

            # Combined greed score (0-1)
            greed_score = (vix_score + momentum_score + sentiment_score) / 3

            # Determine signals
            vix_signal = "COMPLACENT" if vix_current < self.VIX_COMPLACENT else "NORMAL"
            if vix_current < self.VIX_VERY_COMPLACENT:
                vix_signal = "VERY_COMPLACENT"

            momentum_signal = "NORMAL"
            if rsi > self.RSI_OVERBOUGHT:
                momentum_signal = "OVERBOUGHT"
            if rsi > self.RSI_VERY_OVERBOUGHT:
                momentum_signal = "VERY_OVERBOUGHT"

            sentiment_signal = "NORMAL"
            if put_call < self.PUT_CALL_BULLISH:
                sentiment_signal = "EUPHORIC"
            if put_call < self.PUT_CALL_VERY_BULLISH:
                sentiment_signal = "VERY_EUPHORIC"

            # Is greedy if score > 0.5
            is_greedy = greed_score > 0.5

            return GreedState(
                is_greedy=is_greedy,
                greed_score=greed_score,
                vix_level=vix_current,
                vix_percentile=vix_percentile,
                put_call_ratio=put_call,
                spy_above_200ma_pct=spy_above_200ma,
                rsi=rsi,
                detected_at=datetime.now(),
                vix_signal=vix_signal,
                momentum_signal=momentum_signal,
                sentiment_signal=sentiment_signal
            )

        except Exception as e:
            logger.debug(f"Error checking greed conditions: {e}")
            return self._default_greed_state()

    def _default_greed_state(self) -> GreedState:
        """Default state when data unavailable"""
        return GreedState(
            is_greedy=False,
            greed_score=0.0,
            vix_level=20,
            vix_percentile=0.5,
            put_call_ratio=0.8,
            spy_above_200ma_pct=0.0,
            rsi=50,
            detected_at=datetime.now(),
            vix_signal="NORMAL",
            momentum_signal="NORMAL",
            sentiment_signal="NORMAL"
        )

    def _score_vix(self, vix: float, percentile: float) -> float:
        """Score VIX for greed (lower VIX = higher greed)"""
        # VIX below 12 = very greedy (score 1.0)
        # VIX at 20 = neutral (score 0.5)
        # VIX above 30 = fearful (score 0.0)

        if vix < 10:
            return 1.0
        elif vix < 12:
            return 0.9
        elif vix < 14:
            return 0.7
        elif vix < 16:
            return 0.6
        elif vix < 20:
            return 0.5
        elif vix < 25:
            return 0.3
        elif vix < 30:
            return 0.2
        else:
            return 0.0

    def _score_momentum(self, above_200ma: float, rsi: float) -> float:
        """Score momentum for greed (higher = more extended)"""
        score = 0.0

        # Above 200MA component
        if above_200ma > 0.15:
            score += 0.5
        elif above_200ma > 0.10:
            score += 0.4
        elif above_200ma > 0.05:
            score += 0.3
        elif above_200ma > 0:
            score += 0.2

        # RSI component
        if rsi > 80:
            score += 0.5
        elif rsi > 70:
            score += 0.4
        elif rsi > 60:
            score += 0.3
        elif rsi > 50:
            score += 0.2

        return min(score, 1.0)

    def _score_sentiment(self, put_call: float) -> float:
        """Score sentiment for greed (lower put/call = more greedy)"""
        if put_call < 0.5:
            return 1.0
        elif put_call < 0.6:
            return 0.8
        elif put_call < 0.7:
            return 0.6
        elif put_call < 0.8:
            return 0.5
        elif put_call < 0.9:
            return 0.4
        elif put_call < 1.0:
            return 0.3
        else:
            return 0.2  # High put/call = fear

    def _calculate_rsi(self, prices, period: int = 14) -> float:
        """Calculate RSI"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            return float(rsi.iloc[-1])
        except Exception:
            return 50.0

    async def _get_put_call_ratio(self) -> float:
        """Get put/call ratio estimate"""
        # In practice, you'd get this from CBOE or options data
        # For now, estimate from SPY options
        try:
            spy = yf.Ticker("SPY")
            # Get nearest expiration
            expirations = spy.options
            if not expirations:
                return 0.8

            chain = spy.option_chain(expirations[0])

            put_volume = chain.puts['volume'].sum()
            call_volume = chain.calls['volume'].sum()

            if call_volume > 0:
                return put_volume / call_volume
            return 0.8

        except Exception:
            return 0.8  # Default neutral

    async def _generate_profit_suggestions(self) -> List[ProfitTarget]:
        """Generate profit-taking suggestions based on greed level"""
        suggestions = []

        # For tracked positions, suggest profit-taking
        for symbol, pos in self.tracked_positions.items():
            gain_pct = pos.get('gain_pct', 0)

            # Higher greed = more aggressive profit-taking
            if self.greed_state.greed_score > 0.8:
                # Extreme greed - take profits on anything green
                if gain_pct > 0:
                    suggestions.append(ProfitTarget(
                        symbol=symbol,
                        current_price=pos.get('current_price', 0),
                        gain_pct=gain_pct,
                        reason="EXTREME GREED - lock in any gains",
                        action="TAKE_FULL",
                        urgency="HIGH"
                    ))
            elif self.greed_state.greed_score > 0.6:
                # High greed - take partial on big winners
                if gain_pct > 0.15:  # 15%+ gain
                    suggestions.append(ProfitTarget(
                        symbol=symbol,
                        current_price=pos.get('current_price', 0),
                        gain_pct=gain_pct,
                        reason="HIGH GREED - secure partial profits",
                        action="TAKE_PARTIAL",
                        urgency="MEDIUM"
                    ))
                elif gain_pct > 0:
                    suggestions.append(ProfitTarget(
                        symbol=symbol,
                        current_price=pos.get('current_price', 0),
                        gain_pct=gain_pct,
                        reason="HIGH GREED - tighten stops",
                        action="TIGHTEN_STOP",
                        urgency="LOW"
                    ))

        return suggestions

    def _create_profit_inefficiency(self, suggestion: ProfitTarget) -> Optional[Inefficiency]:
        """Convert profit suggestion to inefficiency"""
        try:
            return Inefficiency(
                id=f"PROFIT_{suggestion.symbol}_{datetime.now().strftime('%Y%m%d%H%M')}",
                type=InefficiencyType.BEHAVIORAL,
                symbol=suggestion.symbol,
                score=0.5 + (self.greed_state.greed_score * 0.5),  # Higher greed = more urgent
                edge_reason=EdgeReason.RETAIL_FOMO,
                description=f"TAKE PROFIT: {suggestion.reason}",
                entry_trigger=f"Gain: {suggestion.gain_pct:.1%} | Action: {suggestion.action}",
                time_sensitivity="hours",
                expires_at=datetime.now() + timedelta(days=1),
                metadata={
                    'action': suggestion.action,
                    'urgency': suggestion.urgency,
                    'gain_pct': suggestion.gain_pct
                }
            )
        except Exception as e:
            logger.debug(f"Error creating profit inefficiency: {e}")
            return None

    def _get_greed_warning(self) -> str:
        """Get greed warning message"""
        if self.greed_state.greed_score > 0.8:
            return (
                "🎰 EXTREME GREED: Markets euphoric! "
                "VIX crushed, everyone bullish. "
                "TAKE PROFITS NOW - don't be the last one holding."
            )
        elif self.greed_state.greed_score > 0.6:
            return (
                "🎰 HIGH GREED: Markets overextended. "
                f"VIX at {self.greed_state.vix_level:.1f} (complacent). "
                "Consider taking partial profits, tighten stops."
            )
        else:
            return (
                "🎰 ELEVATED GREED: Markets getting frothy. "
                "Not crisis level, but be cautious with new positions."
            )

    def track_position(self, symbol: str, entry_price: float, current_price: float) -> None:
        """Track a position for profit-taking suggestions"""
        gain_pct = (current_price - entry_price) / entry_price
        self.tracked_positions[symbol] = {
            'entry_price': entry_price,
            'current_price': current_price,
            'gain_pct': gain_pct
        }

    def get_greed_status(self) -> Dict:
        """Get current greed status"""
        if not self.greed_state:
            return {'is_greedy': False, 'message': 'Not yet checked'}

        return {
            'is_greedy': self.greed_state.is_greedy,
            'greed_score': f"{self.greed_state.greed_score:.2f}",
            'vix': self.greed_state.vix_level,
            'vix_signal': self.greed_state.vix_signal,
            'momentum_signal': self.greed_state.momentum_signal,
            'sentiment_signal': self.greed_state.sentiment_signal,
            'rsi': f"{self.greed_state.rsi:.1f}",
            'spy_above_200ma': f"{self.greed_state.spy_above_200ma_pct:.1%}",
            'action': self._get_recommended_action()
        }

    def _get_recommended_action(self) -> str:
        """Get recommended action based on greed level"""
        if not self.greed_state:
            return "NORMAL"

        if self.greed_state.greed_score > 0.8:
            return "SELL_INTO_STRENGTH"
        elif self.greed_state.greed_score > 0.6:
            return "TAKE_PARTIAL_PROFITS"
        elif self.greed_state.greed_score > 0.5:
            return "TIGHTEN_STOPS"
        else:
            return "NORMAL"

    def format_greed_rules(self) -> str:
        """Format current greed status for display"""
        if not self.greed_state:
            return "Greed detector not yet initialized"

        score = self.greed_state.greed_score
        action = self._get_recommended_action()

        return f"""
╔══════════════════════════════════════════════════════════════╗
║                 GREED DETECTOR ({"ACTIVE" if self.greed_state.is_greedy else "NORMAL"})                     ║
╠══════════════════════════════════════════════════════════════╣
║  Greed Score:    {score:.0%} {"🔴" if score > 0.7 else "🟡" if score > 0.5 else "🟢"}                                     ║
║  VIX Level:      {self.greed_state.vix_level:.1f} ({self.greed_state.vix_signal})                        ║
║  RSI:            {self.greed_state.rsi:.0f} ({self.greed_state.momentum_signal})                         ║
║  SPY vs 200MA:   {self.greed_state.spy_above_200ma_pct:+.1%}                                   ║
║  Put/Call:       {self.greed_state.put_call_ratio:.2f} ({self.greed_state.sentiment_signal})                        ║
╠══════════════════════════════════════════════════════════════╣
║  RECOMMENDED ACTION: {action:<25}                  ║
╠══════════════════════════════════════════════════════════════╣
║  PHILOSOPHY: Be fearful when others are greedy              ║
║  - Profits aren't real until you sell                       ║
║  - Better to sell too early than too late                   ║
║  - Capital preservation is #1                               ║
╚══════════════════════════════════════════════════════════════╝
"""

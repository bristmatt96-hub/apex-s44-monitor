"""
Technical Analysis Signal Generator
Uses multiple TA indicators to validate and enhance signals
"""
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger

try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False

from core.base_agent import BaseAgent, AgentMessage
from core.models import Signal, SignalType, MarketType


class TechnicalAnalyzer(BaseAgent):
    """
    Technical Analysis agent that validates and scores signals.

    Analyzes:
    - Trend strength (ADX, moving averages)
    - Momentum (RSI, MACD, Stochastic)
    - Volatility (ATR, Bollinger Bands)
    - Volume patterns
    - Support/Resistance levels
    - Chart patterns
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("TechnicalAnalyzer", config)
        self.pending_signals: List[Dict] = []
        self.analyzed_signals: List[Dict] = []

    async def process(self) -> None:
        """Process pending signals"""
        # Check for signals to analyze
        if not self.pending_signals:
            await asyncio.sleep(1)
            return

        # Process each pending signal
        while self.pending_signals:
            signal_data = self.pending_signals.pop(0)
            analysis = await self.analyze_signal(signal_data)

            if analysis['validated']:
                self.analyzed_signals.append(analysis)
                await self._send_analysis(analysis)

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming signals to analyze"""
        if message.msg_type == 'analyze_signal':
            self.pending_signals.append(message.payload)
            logger.debug(f"Received signal to analyze: {message.payload.get('symbol')}")

    async def analyze_signal(self, signal_data: Dict) -> Dict:
        """
        Perform comprehensive technical analysis on a signal.
        Returns enhanced signal with TA scores.
        """
        symbol = signal_data.get('symbol')
        market_type = signal_data.get('market_type')

        # Fetch fresh data for analysis
        data = await self._fetch_data(symbol, market_type)

        if data is None or len(data) < 50:
            return {**signal_data, 'validated': False, 'reason': 'Insufficient data'}

        # Run all analyses
        trend_score = await self._analyze_trend(data)
        momentum_score = await self._analyze_momentum(data)
        volatility_analysis = await self._analyze_volatility(data)
        volume_score = await self._analyze_volume(data)
        sr_levels = await self._find_support_resistance(data)

        # Composite score
        composite_score = (
            trend_score * 0.30 +
            momentum_score * 0.30 +
            volume_score * 0.20 +
            (1 - volatility_analysis['risk_score']) * 0.20  # Lower volatility = better
        )

        # Validate signal
        validated = composite_score > 0.5 and trend_score > 0.4

        # Adjust confidence based on TA
        original_confidence = signal_data.get('confidence', 0.5)
        adjusted_confidence = (original_confidence + composite_score) / 2

        return {
            **signal_data,
            'validated': validated,
            'ta_scores': {
                'trend': trend_score,
                'momentum': momentum_score,
                'volume': volume_score,
                'volatility': volatility_analysis,
                'composite': composite_score
            },
            'support_resistance': sr_levels,
            'adjusted_confidence': adjusted_confidence,
            'ta_timestamp': datetime.now().isoformat()
        }

    async def _fetch_data(self, symbol: str, market_type: str) -> Optional[pd.DataFrame]:
        """Fetch data for analysis"""
        try:
            import yfinance as yf

            # Adjust symbol format
            if market_type == 'forex':
                symbol = f"{symbol}=X"
            elif market_type == 'crypto':
                symbol = f"{symbol.replace('/', '-').replace('USDT', 'USD').replace('usdt', 'usd')}"

            ticker = yf.Ticker(symbol)
            df = ticker.history(period="3mo", interval="1d")

            if df.empty:
                return None

            df.columns = [c.lower() for c in df.columns]
            return df

        except (ImportError, ConnectionError, ValueError) as e:
            logger.debug(f"Error fetching data for {symbol}: {e}")
            return None

    async def _analyze_trend(self, data: pd.DataFrame) -> float:
        """Analyze trend strength - returns score 0-1"""
        if not PANDAS_TA_AVAILABLE:
            return 0.5

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            # Moving averages
            ema20 = ta.ema(close, length=20)
            ema50 = ta.ema(close, length=50)
            sma200 = ta.sma(close, length=200) if len(data) >= 200 else ta.sma(close, length=100)

            if ema20 is None or ema50 is None or sma200 is None:
                return 0.5

            # ADX for trend strength
            adx_data = ta.adx(high, low, close, length=14)
            adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None else 20

            current = data.iloc[-1]
            price = current['close']

            # Score components
            scores = []

            # Price vs EMAs
            if price > ema20.iloc[-1]:
                scores.append(0.2)
            if price > ema50.iloc[-1]:
                scores.append(0.2)
            if price > sma200.iloc[-1]:
                scores.append(0.2)

            # EMA alignment
            if ema20.iloc[-1] > ema50.iloc[-1]:
                scores.append(0.15)
            if ema50.iloc[-1] > sma200.iloc[-1]:
                scores.append(0.15)

            # ADX strength
            adx_score = min(adx / 50, 1.0) * 0.3
            scores.append(adx_score)

            return min(sum(scores), 1.0)

        except (ValueError, TypeError, KeyError) as e:
            logger.debug(f"Trend analysis error: {e}")
            return 0.5

    async def _analyze_momentum(self, data: pd.DataFrame) -> float:
        """Analyze momentum - returns score 0-1"""
        if not PANDAS_TA_AVAILABLE:
            return 0.5

        try:
            close = data['close']

            # RSI
            rsi = ta.rsi(close, length=14)
            if rsi is None:
                return 0.5
            rsi_val = rsi.iloc[-1]

            # MACD
            macd_data = ta.macd(close)
            if macd_data is None:
                return 0.5
            macd = macd_data['MACD_12_26_9'].iloc[-1]
            macd_signal = macd_data['MACDs_12_26_9'].iloc[-1]
            macd_hist = macd_data['MACDh_12_26_9'].iloc[-1]

            # Stochastic
            stoch = ta.stoch(data['high'], data['low'], close)
            if stoch is None:
                return 0.5
            stoch_k = stoch['STOCHk_14_3_3'].iloc[-1]
            stoch_d = stoch['STOCHd_14_3_3'].iloc[-1]

            scores = []

            # RSI score (optimal range 40-60)
            if 40 < rsi_val < 60:
                scores.append(0.3)
            elif 30 < rsi_val < 70:
                scores.append(0.2)
            else:
                scores.append(0.1)

            # MACD score
            if macd > macd_signal:
                scores.append(0.2)
            if macd_hist > 0:
                scores.append(0.15)

            # Stochastic score
            if stoch_k > stoch_d:
                scores.append(0.15)
            if 20 < stoch_k < 80:
                scores.append(0.1)

            # Momentum (rate of change)
            roc = ta.roc(close, length=10)
            if roc is not None and roc.iloc[-1] > 0:
                scores.append(0.1)

            return min(sum(scores), 1.0)

        except (ValueError, TypeError, KeyError) as e:
            logger.debug(f"Momentum analysis error: {e}")
            return 0.5

    async def _analyze_volatility(self, data: pd.DataFrame) -> Dict:
        """Analyze volatility - returns analysis dict"""
        if not PANDAS_TA_AVAILABLE:
            return {'atr': 0, 'bb_width': 0, 'risk_score': 0.5}

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            # ATR
            atr = ta.atr(high, low, close, length=14)
            if atr is None:
                return {'atr': 0, 'bb_width': 0, 'risk_score': 0.5}
            atr_val = atr.iloc[-1]
            atr_pct = atr_val / close.iloc[-1]

            # Bollinger Band width
            bb = ta.bbands(close, length=20)
            if bb is None:
                return {'atr': atr_val, 'bb_width': 0, 'risk_score': 0.5}
            bb_cols = bb.columns.tolist()
            bb_upper = bb[[c for c in bb_cols if c.startswith('BBU')][0]].iloc[-1]
            bb_lower = bb[[c for c in bb_cols if c.startswith('BBL')][0]].iloc[-1]
            bb_width = (bb_upper - bb_lower) / close.iloc[-1]

            # Historical volatility
            returns = close.pct_change().dropna()
            hist_vol = returns.std() * np.sqrt(252)  # Annualized

            # Risk score (higher = more risky)
            risk_score = min((atr_pct * 20 + bb_width * 10 + hist_vol) / 3, 1.0)

            return {
                'atr': atr_val,
                'atr_pct': atr_pct,
                'bb_width': bb_width,
                'hist_volatility': hist_vol,
                'risk_score': risk_score
            }

        except (ValueError, TypeError, KeyError) as e:
            logger.debug(f"Volatility analysis error: {e}")
            return {'atr': 0, 'bb_width': 0, 'risk_score': 0.5}

    async def _analyze_volume(self, data: pd.DataFrame) -> float:
        """Analyze volume patterns - returns score 0-1"""
        try:
            volume = data['volume']
            close = data['close']

            # Average volume
            avg_volume = volume[-20:].mean()
            current_volume = volume.iloc[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

            # Volume trend
            recent_avg = volume[-5:].mean()
            prior_avg = volume[-20:-5].mean()
            volume_trend = recent_avg / prior_avg if prior_avg > 0 else 1

            # Price-volume correlation (up days should have higher volume)
            price_changes = close.pct_change()
            last_5_days = list(zip(price_changes[-5:], volume[-5:]))

            positive_volume = sum(v for p, v in last_5_days if p > 0)
            negative_volume = sum(v for p, v in last_5_days if p < 0)
            pv_ratio = positive_volume / negative_volume if negative_volume > 0 else 2

            scores = []

            # Volume ratio score
            if volume_ratio > 1.5:
                scores.append(0.3)
            elif volume_ratio > 1.0:
                scores.append(0.2)
            else:
                scores.append(0.1)

            # Volume trend score
            if volume_trend > 1.2:
                scores.append(0.25)
            elif volume_trend > 1.0:
                scores.append(0.15)

            # Price-volume score
            if pv_ratio > 1.5:
                scores.append(0.25)
            elif pv_ratio > 1.0:
                scores.append(0.15)

            # Adequate liquidity
            if current_volume > 100000:
                scores.append(0.2)

            return min(sum(scores), 1.0)

        except (ValueError, TypeError, ZeroDivisionError) as e:
            logger.debug(f"Volume analysis error: {e}")
            return 0.5

    async def _find_support_resistance(self, data: pd.DataFrame) -> Dict:
        """Find key support and resistance levels"""
        try:
            high = data['high']
            low = data['low']
            close = data['close']

            current_price = close.iloc[-1]

            # Simple pivot points
            pivot = (high.iloc[-1] + low.iloc[-1] + close.iloc[-1]) / 3
            r1 = 2 * pivot - low.iloc[-1]
            r2 = pivot + (high.iloc[-1] - low.iloc[-1])
            s1 = 2 * pivot - high.iloc[-1]
            s2 = pivot - (high.iloc[-1] - low.iloc[-1])

            # Recent swing highs/lows
            swing_highs = []
            swing_lows = []

            for i in range(2, len(data) - 2):
                if high.iloc[i] > high.iloc[i-1] and high.iloc[i] > high.iloc[i-2] and \
                   high.iloc[i] > high.iloc[i+1] and high.iloc[i] > high.iloc[i+2]:
                    swing_highs.append(high.iloc[i])

                if low.iloc[i] < low.iloc[i-1] and low.iloc[i] < low.iloc[i-2] and \
                   low.iloc[i] < low.iloc[i+1] and low.iloc[i] < low.iloc[i+2]:
                    swing_lows.append(low.iloc[i])

            # Key levels
            resistance_levels = sorted([r1, r2] + swing_highs[-3:], reverse=True)
            support_levels = sorted([s1, s2] + swing_lows[-3:])

            # Nearest levels
            nearest_resistance = min([r for r in resistance_levels if r > current_price], default=r1)
            nearest_support = max([s for s in support_levels if s < current_price], default=s1)

            return {
                'pivot': pivot,
                'resistance_1': r1,
                'resistance_2': r2,
                'support_1': s1,
                'support_2': s2,
                'nearest_resistance': nearest_resistance,
                'nearest_support': nearest_support,
                'distance_to_resistance_pct': (nearest_resistance - current_price) / current_price * 100,
                'distance_to_support_pct': (current_price - nearest_support) / current_price * 100
            }

        except (ValueError, TypeError, IndexError) as e:
            logger.debug(f"S/R analysis error: {e}")
            return {}

    async def _send_analysis(self, analysis: Dict) -> None:
        """Send completed analysis to coordinator"""
        await self.send_message(
            target='coordinator',
            msg_type='signal_analyzed',
            payload=analysis,
            priority=3
        )

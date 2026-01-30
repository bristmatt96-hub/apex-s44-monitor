"""
Exogenous Shock & Panic Recovery Scanner

Detects market-wide panic events (Trump headlines, geopolitical shocks, etc.)
and identifies which stocks will recover FIRST and FASTEST.

WHY THIS WORKS:
- During panic, correlation → 1 (everything sells together)
- But recovery is NOT correlated - quality bounces first
- "Baby thrown out with bathwater" creates opportunities
- Stocks less affected by the actual news recover fastest

THE EDGE:
- When VIX spikes > 25, start looking for recovery plays
- Oversold + strong fundamentals = fastest bounce
- Sector rotation: unaffected sectors recover first
- Retail panic creates extreme oversold conditions

WHAT WE DETECT:
1. Market-wide panic (VIX spike, broad selloff, correlation spike)
2. Individual stock oversold conditions
3. Fundamental strength (to filter quality from junk)
4. Sector exposure to the shock (less exposed = faster recovery)

HISTORICAL EXAMPLES:
- Liberation Day (Trump tariffs): Tech oversold, recovered 15% in days
- COVID crash: Quality names (AAPL, MSFT) bounced first
- SVB collapse: Non-bank tech recovered while banks stayed down
"""
import asyncio
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
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
from agents.brain.crisis_memory import (
    identify_crisis_type, get_recovery_patterns, get_all_lessons,
    GFC_2008, COVID_2020, BEAR_2022
)


@dataclass
class PanicState:
    """Current state of market panic"""
    is_panic: bool
    vix_level: float
    vix_spike: float  # % above 20-day average
    spy_drawdown: float  # % from recent high
    correlation: float  # Average correlation (high = panic)
    panic_score: float  # 0-1, higher = more panic
    detected_at: str


@dataclass
class RecoveryCandidate:
    """A stock positioned for fast recovery"""
    symbol: str
    sector: str

    # Oversold metrics
    rsi: float
    percent_from_high: float
    days_oversold: int

    # Fundamental strength
    has_strong_balance_sheet: bool
    is_profitable: bool

    # Recovery potential
    recovery_score: float
    expected_bounce_pct: float

    # Sector exposure
    sector_exposure_to_shock: str  # 'high', 'medium', 'low'


class ExogenousShockScanner:
    """
    Detects market-wide panic and identifies fastest recovery candidates.

    Philosophy: "Be greedy when others are fearful"

    Process:
    1. Monitor for panic conditions (VIX, correlation, drawdown)
    2. When panic detected, scan for oversold quality names
    3. Rank by recovery potential (fundamentals + technicals + sector)
    4. Produce ranked list of "buy the dip" candidates
    """

    def __init__(self):
        # Panic detection thresholds
        self.vix_panic_level = 25  # VIX above this = panic
        self.vix_spike_threshold = 0.30  # 30% above average = spike
        self.spy_drawdown_threshold = 0.03  # 3% drawdown = concern
        self.correlation_panic_level = 0.7  # Avg correlation above this = panic

        # Recovery candidate criteria
        self.rsi_oversold = 35  # RSI below this = oversold
        self.min_drawdown = 0.05  # At least 5% from high to consider

        # Watchlist organized by sector
        self.watchlist_by_sector = {
            'tech': ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD', 'CRM', 'ADBE'],
            'consumer': ['AMZN', 'TSLA', 'HD', 'NKE', 'SBUX', 'MCD', 'COST'],
            'financials': ['JPM', 'BAC', 'GS', 'MS', 'V', 'MA', 'AXP'],
            'healthcare': ['UNH', 'JNJ', 'PFE', 'ABBV', 'MRK', 'LLY'],
            'industrials': ['CAT', 'BA', 'UPS', 'HON', 'GE', 'RTX'],
            'energy': ['XOM', 'CVX', 'COP', 'SLB', 'EOG'],
            'etfs': ['SPY', 'QQQ', 'IWM', 'XLF', 'XLE', 'XLK', 'XLV']
        }

        # Flatten for scanning
        self.all_symbols = []
        for symbols in self.watchlist_by_sector.values():
            self.all_symbols.extend(symbols)

        # Current panic state
        self.panic_state: Optional[PanicState] = None
        self.last_panic_check = None
        self.days_declining = 0
        self.crisis_analysis: Optional[Dict] = None

        # Historical recovery patterns (from crisis memory)
        self.recovery_patterns = get_recovery_patterns()
        self.historical_lessons = get_all_lessons()

    async def scan(self) -> List[Inefficiency]:
        """Main scan - detect panic and find recovery plays"""
        if not YFINANCE_AVAILABLE:
            return []

        inefficiencies = []

        # Step 1: Check for panic conditions
        self.panic_state = await self._detect_panic()

        if not self.panic_state.is_panic:
            logger.debug(f"No panic detected (VIX: {self.panic_state.vix_level:.1f}, Score: {self.panic_state.panic_score:.2f})")
            return []

        logger.info(
            f"🚨 PANIC DETECTED: VIX {self.panic_state.vix_level:.1f} "
            f"(+{self.panic_state.vix_spike:.0%}), SPY {self.panic_state.spy_drawdown:.1%} from high"
        )

        # Step 1b: Identify what type of crisis (using historical memory)
        self.crisis_analysis = identify_crisis_type(
            vix_level=self.panic_state.vix_level,
            vix_spike_pct=self.panic_state.vix_spike,
            spy_drawdown_pct=self.panic_state.spy_drawdown,
            days_declining=self.days_declining
        )

        logger.info(
            f"📚 CRISIS TYPE: {self.crisis_analysis['most_similar']} "
            f"(similarity: {self.crisis_analysis['similarity_score']:.0%})"
        )
        logger.info(f"📚 EXPECTED PATTERN: {self.crisis_analysis['expected_pattern']}")

        # Step 2: Find recovery candidates
        candidates = await self._find_recovery_candidates()

        if not candidates:
            logger.info("Panic detected but no quality recovery candidates yet")
            return []

        # Step 3: Convert to Inefficiency objects
        for candidate in candidates[:10]:  # Top 10
            ineff = self._create_inefficiency(candidate)
            if ineff:
                inefficiencies.append(ineff)

        return inefficiencies

    async def _detect_panic(self) -> PanicState:
        """Detect if market is in panic mode"""
        try:
            # Get VIX
            vix = yf.Ticker("^VIX")
            vix_hist = vix.history(period="30d")
            if vix_hist.empty:
                return PanicState(False, 0, 0, 0, 0, 0, datetime.now().isoformat())

            current_vix = vix_hist['Close'].iloc[-1]
            avg_vix = vix_hist['Close'].mean()
            vix_spike = (current_vix / avg_vix) - 1

            # Get SPY for drawdown
            spy = yf.Ticker("SPY")
            spy_hist = spy.history(period="30d")
            if spy_hist.empty:
                return PanicState(False, current_vix, vix_spike, 0, 0, 0, datetime.now().isoformat())

            spy_current = spy_hist['Close'].iloc[-1]
            spy_high = spy_hist['High'].max()
            spy_drawdown = (spy_high - spy_current) / spy_high

            # Calculate correlation (simplified: check if everything moving together)
            correlation = await self._calculate_market_correlation()

            # Calculate panic score
            vix_score = min(1.0, (current_vix - 15) / 20)  # 15=calm, 35=panic
            drawdown_score = min(1.0, spy_drawdown / 0.10)  # 10% drawdown = max score
            correlation_score = min(1.0, correlation / 0.8)

            panic_score = (vix_score * 0.4 + drawdown_score * 0.3 + correlation_score * 0.3)

            is_panic = (
                current_vix >= self.vix_panic_level or
                vix_spike >= self.vix_spike_threshold or
                (spy_drawdown >= self.spy_drawdown_threshold and correlation >= self.correlation_panic_level)
            )

            return PanicState(
                is_panic=is_panic,
                vix_level=current_vix,
                vix_spike=vix_spike,
                spy_drawdown=spy_drawdown,
                correlation=correlation,
                panic_score=panic_score,
                detected_at=datetime.now().isoformat()
            )

        except Exception as e:
            logger.error(f"Panic detection error: {e}")
            return PanicState(False, 0, 0, 0, 0, 0, datetime.now().isoformat())

    async def _calculate_market_correlation(self) -> float:
        """Calculate average correlation between major stocks"""
        try:
            # Sample of major stocks
            symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'JPM', 'XOM']

            data = yf.download(symbols, period="10d", interval="1h", progress=False)
            if data.empty:
                return 0.5

            returns = data['Close'].pct_change().dropna()
            if len(returns) < 5:
                return 0.5

            corr_matrix = returns.corr()

            # Average correlation (excluding diagonal)
            mask = np.triu(np.ones_like(corr_matrix, dtype=bool), k=1)
            avg_corr = corr_matrix.where(mask).stack().mean()

            return avg_corr if pd.notna(avg_corr) else 0.5

        except Exception as e:
            logger.debug(f"Correlation calc error: {e}")
            return 0.5

    async def _find_recovery_candidates(self) -> List[RecoveryCandidate]:
        """Find stocks positioned for fast recovery"""
        candidates = []

        for sector, symbols in self.watchlist_by_sector.items():
            for symbol in symbols:
                try:
                    candidate = await self._analyze_recovery_potential(symbol, sector)
                    if candidate and candidate.recovery_score > 0.5:
                        candidates.append(candidate)
                except Exception as e:
                    logger.debug(f"Error analyzing {symbol}: {e}")
                    continue

        # Sort by recovery score (highest first)
        candidates.sort(key=lambda x: x.recovery_score, reverse=True)

        return candidates

    async def _analyze_recovery_potential(
        self, symbol: str, sector: str
    ) -> Optional[RecoveryCandidate]:
        """Analyze a single stock's recovery potential"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="30d")

            if hist.empty or len(hist) < 14:
                return None

            current_price = hist['Close'].iloc[-1]
            high_30d = hist['High'].max()
            low_30d = hist['Low'].min()

            # Calculate drawdown from high
            drawdown = (high_30d - current_price) / high_30d

            # Skip if not oversold enough
            if drawdown < self.min_drawdown:
                return None

            # Calculate RSI
            rsi = self._calculate_rsi(hist['Close'])

            # Skip if not oversold
            if rsi > self.rsi_oversold:
                return None

            # Days oversold (RSI below threshold)
            rsi_series = self._calculate_rsi_series(hist['Close'])
            days_oversold = (rsi_series.tail(10) < self.rsi_oversold).sum()

            # Get fundamental info (simplified)
            try:
                info = ticker.info
                is_profitable = info.get('profitMargins', 0) > 0
                # Strong balance sheet: positive free cash flow or low debt
                has_strong_balance = (
                    info.get('freeCashflow', 0) > 0 or
                    info.get('debtToEquity', 999) < 100
                )
            except:
                is_profitable = True  # Assume quality if can't get data
                has_strong_balance = True

            # Sector exposure to typical shocks
            # (This would be dynamic based on actual news, simplified here)
            sector_exposure = self._estimate_sector_exposure(sector)

            # Calculate recovery score
            recovery_score = self._calculate_recovery_score(
                rsi=rsi,
                drawdown=drawdown,
                days_oversold=days_oversold,
                is_profitable=is_profitable,
                has_strong_balance=has_strong_balance,
                sector_exposure=sector_exposure
            )

            # Estimate bounce potential
            # Oversold stocks typically bounce 3-8% on recovery
            expected_bounce = min(0.15, drawdown * 0.6)  # Expect 60% of drawdown to recover

            return RecoveryCandidate(
                symbol=symbol,
                sector=sector,
                rsi=rsi,
                percent_from_high=drawdown,
                days_oversold=days_oversold,
                has_strong_balance_sheet=has_strong_balance,
                is_profitable=is_profitable,
                recovery_score=recovery_score,
                expected_bounce_pct=expected_bounce,
                sector_exposure_to_shock=sector_exposure
            )

        except Exception as e:
            logger.debug(f"Recovery analysis failed for {symbol}: {e}")
            return None

    def _calculate_rsi(self, prices, period: int = 14) -> float:
        """Calculate RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi.iloc[-1] if pd.notna(rsi.iloc[-1]) else 50

    def _calculate_rsi_series(self, prices, period: int = 14) -> pd.Series:
        """Calculate RSI series"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _estimate_sector_exposure(self, sector: str) -> str:
        """
        Estimate sector's typical exposure to exogenous shocks.

        In reality, this would analyze the ACTUAL news/shock.
        For now, use general patterns:
        - Trade wars: industrials, tech hardware HIGH; healthcare LOW
        - Rate hikes: financials HIGH (positive); tech HIGH (negative)
        - Geopolitical: energy HIGH; consumer staples LOW
        """
        # Default exposures (would be dynamic based on news)
        exposures = {
            'tech': 'medium',
            'consumer': 'medium',
            'financials': 'high',
            'healthcare': 'low',
            'industrials': 'high',
            'energy': 'high',
            'etfs': 'medium'
        }
        return exposures.get(sector, 'medium')

    def _calculate_recovery_score(
        self,
        rsi: float,
        drawdown: float,
        days_oversold: int,
        is_profitable: bool,
        has_strong_balance: bool,
        sector_exposure: str
    ) -> float:
        """
        Calculate recovery potential score (0-1).

        Higher score = faster expected recovery.
        """
        score = 0.0

        # RSI component (lower = more oversold = higher bounce potential)
        rsi_score = (self.rsi_oversold - rsi) / self.rsi_oversold if rsi < self.rsi_oversold else 0
        score += rsi_score * 0.25

        # Drawdown component (bigger drop = bigger bounce, but not too extreme)
        if 0.05 <= drawdown <= 0.20:
            drawdown_score = drawdown / 0.15  # Sweet spot 5-20%
        elif drawdown > 0.20:
            drawdown_score = 0.5  # Too much = might be broken
        else:
            drawdown_score = 0
        score += drawdown_score * 0.20

        # Days oversold (some persistence is good, too much is bad)
        if 1 <= days_oversold <= 5:
            days_score = 0.8
        elif days_oversold > 5:
            days_score = 0.4  # Extended oversold = slower recovery
        else:
            days_score = 0.3
        score += days_score * 0.15

        # Fundamental quality
        if is_profitable:
            score += 0.15
        if has_strong_balance:
            score += 0.10

        # Sector exposure (low exposure = faster recovery)
        exposure_scores = {'low': 0.15, 'medium': 0.10, 'high': 0.05}
        score += exposure_scores.get(sector_exposure, 0.10)

        return min(1.0, score)

    def _create_inefficiency(self, candidate: RecoveryCandidate) -> Optional[Inefficiency]:
        """Convert recovery candidate to Inefficiency"""
        try:
            ticker = yf.Ticker(candidate.symbol)
            hist = ticker.history(period="5d")

            if hist.empty:
                return None

            current_price = hist['Close'].iloc[-1]

            # Entry zone: current price ± 1%
            entry_zone = (current_price * 0.99, current_price * 1.01)

            # Target: expected bounce
            target = current_price * (1 + candidate.expected_bounce_pct)

            # Stop: below recent low or 3%
            recent_low = hist['Low'].min()
            stop = min(recent_low * 0.99, current_price * 0.97)

            risk = current_price - stop
            reward = target - current_price
            risk_reward = reward / risk if risk > 0 else 0

            if risk_reward < 1.5:
                return None

            explanation = (
                f"PANIC RECOVERY: {candidate.symbol} ({candidate.sector}) "
                f"RSI {candidate.rsi:.0f}, down {candidate.percent_from_high:.1%} from high. "
                f"{'Profitable' if candidate.is_profitable else 'Unprofitable'}, "
                f"{'strong' if candidate.has_strong_balance_sheet else 'weak'} balance sheet. "
                f"Sector exposure: {candidate.sector_exposure_to_shock}. "
                f"Expected bounce: {candidate.expected_bounce_pct:.1%}."
            )

            action = (
                f"BUY THE DIP: {candidate.symbol} - Quality name oversold in panic. "
                f"Target ${target:.2f} ({candidate.expected_bounce_pct:.1%} bounce)"
            )

            return Inefficiency(
                id=f"panic_{candidate.symbol}_{datetime.now().strftime('%Y%m%d%H%M')}",
                type=InefficiencyType.SENTIMENT_EXTREME,
                symbol=candidate.symbol,
                score=candidate.recovery_score,
                edge_reason=EdgeReason.BEHAVIORAL,
                direction="long",
                suggested_action=action,
                entry_zone=entry_zone,
                target=target,
                stop=stop,
                risk_reward=risk_reward,
                explanation=explanation,
                data_points={
                    'rsi': candidate.rsi,
                    'drawdown': candidate.percent_from_high,
                    'days_oversold': candidate.days_oversold,
                    'sector': candidate.sector,
                    'sector_exposure': candidate.sector_exposure_to_shock,
                    'is_profitable': candidate.is_profitable,
                    'vix_level': self.panic_state.vix_level if self.panic_state else 0,
                    'panic_score': self.panic_state.panic_score if self.panic_state else 0
                },
                confidence=candidate.recovery_score * 0.9,
                time_sensitivity="days"  # Recovery plays take days
            )

        except Exception as e:
            logger.debug(f"Failed to create inefficiency for {candidate.symbol}: {e}")
            return None

    def get_panic_status(self) -> Dict:
        """Get current panic status with historical context"""
        if not self.panic_state:
            return {'is_panic': False, 'message': 'Not yet checked'}

        status = {
            'is_panic': self.panic_state.is_panic,
            'vix': self.panic_state.vix_level,
            'vix_spike': f"{self.panic_state.vix_spike:.1%}",
            'spy_drawdown': f"{self.panic_state.spy_drawdown:.1%}",
            'correlation': f"{self.panic_state.correlation:.2f}",
            'panic_score': f"{self.panic_state.panic_score:.2f}",
            'detected_at': self.panic_state.detected_at
        }

        # Add historical crisis analysis if available
        if self.crisis_analysis:
            status['crisis_type'] = self.crisis_analysis['most_similar']
            status['similarity'] = f"{self.crisis_analysis['similarity_score']:.0%}"
            status['expected_pattern'] = self.crisis_analysis['expected_pattern']
            status['recommendations'] = self.crisis_analysis['recommendations']

        return status

    def get_historical_context(self) -> str:
        """Get historical context for current conditions"""
        if not self.crisis_analysis:
            return "No crisis analysis available yet."

        lines = [
            f"\n📚 HISTORICAL CONTEXT: {self.crisis_analysis['most_similar']}",
            f"   Similarity: {self.crisis_analysis['similarity_score']:.0%}",
            f"   Expected: {self.crisis_analysis['expected_pattern']}",
            "",
            "   RECOMMENDATIONS (from history):"
        ]

        for rec in self.crisis_analysis.get('recommendations', []):
            lines.append(f"   • {rec}")

        # Add sector recovery expectations
        lines.append("")
        lines.append("   SECTOR RECOVERY ORDER (historical):")
        lines.append("   • FIRST: Tech, Healthcare (quality names)")
        lines.append("   • SLOW: Financials, Energy")
        lines.append("   • AVOID: Whatever caused the crisis")

        return "\n".join(lines)

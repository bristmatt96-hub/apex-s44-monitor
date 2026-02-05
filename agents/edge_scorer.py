"""
Edge Scorer for Credit Catalyst

Combines multiple signals into a single edge score that determines:
1. Whether to trade (min score 5.0)
2. Position sizing (aggression multiplier)

EDGE_SCORE = weighted average of:
- Credit signal strength (0-10)     weight: 25%
- Psychology alignment (0-10)       weight: 25%
- Options mispricing (0-10)         weight: 20%
- Catalyst clarity (0-10)           weight: 15%
- Historical pattern match (0-10)   weight: 15%
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json
from pathlib import Path

from core.edge_component_learner import get_edge_learner
from core.pattern_learner import get_pattern_learner


class SignalStrength(Enum):
    """Signal strength levels."""
    NONE = 0
    WEAK = 3
    MODERATE = 5
    STRONG = 7
    VERY_STRONG = 9
    EXTREME = 10


@dataclass
class SignalComponent:
    """Individual signal component of edge score."""
    name: str
    score: float  # 0-10
    weight: float  # 0-1
    reasoning: str
    data_points: List[str] = field(default_factory=list)


@dataclass
class EdgeScore:
    """Complete edge score with all components."""
    company: str
    ticker: str
    timestamp: datetime

    # Component scores
    credit_signal: SignalComponent
    psychology_alignment: SignalComponent
    options_mispricing: SignalComponent
    catalyst_clarity: SignalComponent
    pattern_match: SignalComponent

    # Calculated values
    total_score: float = 0.0
    aggression_multiplier: float = 0.0
    trade_recommendation: str = "NO_TRADE"
    confidence_level: str = "low"

    # Context for learning
    playbook: Optional[str] = None
    sector: Optional[str] = None

    # Trade parameters (if recommended)
    recommended_direction: Optional[str] = None  # LONG_PUT, LONG_CALL, STRADDLE
    recommended_size_multiplier: Optional[float] = None
    max_loss_threshold: Optional[float] = None

    def __post_init__(self):
        self.calculate_total()

    def calculate_total(self):
        """Calculate total edge score and trading parameters."""
        # Weighted average
        components = [
            self.credit_signal,
            self.psychology_alignment,
            self.options_mispricing,
            self.catalyst_clarity,
            self.pattern_match
        ]

        weighted_sum = sum(c.score * c.weight for c in components)
        total_weight = sum(c.weight for c in components)

        self.total_score = round(weighted_sum / total_weight if total_weight > 0 else 0, 2)

        # Determine aggression and recommendation
        if self.total_score < 5.0:
            self.aggression_multiplier = 0.0
            self.trade_recommendation = "NO_TRADE"
            self.confidence_level = "insufficient"
        elif self.total_score < 6.0:
            self.aggression_multiplier = 0.5
            self.trade_recommendation = "CAUTIOUS"
            self.confidence_level = "low"
        elif self.total_score < 7.0:
            self.aggression_multiplier = 1.0
            self.trade_recommendation = "STANDARD"
            self.confidence_level = "medium"
        elif self.total_score < 8.0:
            self.aggression_multiplier = 1.5
            self.trade_recommendation = "INCREASED"
            self.confidence_level = "high"
        elif self.total_score < 9.0:
            self.aggression_multiplier = 2.0
            self.trade_recommendation = "HIGH_CONVICTION"
            self.confidence_level = "very_high"
        else:
            self.aggression_multiplier = 2.5
            self.trade_recommendation = "MAXIMUM"
            self.confidence_level = "extreme"

        self.recommended_size_multiplier = self.aggression_multiplier

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/serialization."""
        return {
            "company": self.company,
            "ticker": self.ticker,
            "timestamp": self.timestamp.isoformat(),
            "total_score": self.total_score,
            "aggression_multiplier": self.aggression_multiplier,
            "trade_recommendation": self.trade_recommendation,
            "confidence_level": self.confidence_level,
            "recommended_direction": self.recommended_direction,
            "playbook": self.playbook,
            "sector": self.sector,
            "components": {
                "credit_signal": {
                    "score": self.credit_signal.score,
                    "weight": self.credit_signal.weight,
                    "reasoning": self.credit_signal.reasoning
                },
                "psychology_alignment": {
                    "score": self.psychology_alignment.score,
                    "weight": self.psychology_alignment.weight,
                    "reasoning": self.psychology_alignment.reasoning
                },
                "options_mispricing": {
                    "score": self.options_mispricing.score,
                    "weight": self.options_mispricing.weight,
                    "reasoning": self.options_mispricing.reasoning
                },
                "catalyst_clarity": {
                    "score": self.catalyst_clarity.score,
                    "weight": self.catalyst_clarity.weight,
                    "reasoning": self.catalyst_clarity.reasoning
                },
                "pattern_match": {
                    "score": self.pattern_match.score,
                    "weight": self.pattern_match.weight,
                    "reasoning": self.pattern_match.reasoning
                }
            }
        }

    def format_telegram(self) -> str:
        """Format edge score for Telegram notification."""
        lines = [
            f"📊 EDGE SCORE: {self.company}",
            f"",
            f"Ticker: {self.ticker}",
            f"Total Score: {self.total_score}/10",
            f"Recommendation: {self.trade_recommendation}",
            f"Aggression: {self.aggression_multiplier}x",
            f"",
            f"COMPONENTS:",
            f"• Credit Signal: {self.credit_signal.score}/10 ({self.credit_signal.reasoning[:50]}...)",
            f"• Psychology: {self.psychology_alignment.score}/10 ({self.psychology_alignment.reasoning[:50]}...)",
            f"• Options: {self.options_mispricing.score}/10 ({self.options_mispricing.reasoning[:50]}...)",
            f"• Catalyst: {self.catalyst_clarity.score}/10 ({self.catalyst_clarity.reasoning[:50]}...)",
            f"• Pattern: {self.pattern_match.score}/10 ({self.pattern_match.reasoning[:50]}...)",
        ]

        if self.recommended_direction:
            lines.extend([
                f"",
                f"TRADE: {self.recommended_direction}",
                f"Size: {self.recommended_size_multiplier}x standard"
            ])

        return "\n".join(lines)


class EdgeScorer:
    """
    Calculates edge scores for trading opportunities.

    Integrates:
    - Credit analysis (situation classifier, maturity wall)
    - Psychology model (market positioning, sentiment)
    - Options analysis (IV, mispricing)
    - Catalyst calendar
    - Pattern database
    """

    def __init__(self, data_path: str = None):
        if data_path is None:
            data_path = Path(__file__).parent.parent / "data"
        self.data_path = Path(data_path)
        self.pattern_db: List[Dict] = self._load_patterns()
        self._edge_learner = get_edge_learner()
        self._pattern_learner = get_pattern_learner()

    @property
    def weights(self) -> Dict[str, float]:
        """Get current component weights (learned or default)."""
        return self._edge_learner.get_current_weights()

    def _load_patterns(self) -> List[Dict]:
        """Load historical patterns for matching."""
        patterns_file = self.data_path / "patterns.json"
        if patterns_file.exists():
            with open(patterns_file) as f:
                return json.load(f)
        return []

    def score_credit_signal(
        self,
        playbook: str,
        maturity_risk: str,
        sponsor_aggression: int,
        recent_events: List[str] = None
    ) -> SignalComponent:
        """
        Score credit signal strength (0-10).

        1-3: Minor concern, no action needed
        4-5: Watching - early warning signs
        6-7: Material deterioration - active monitoring
        8-9: Serious distress - high conviction signal
        10: Imminent default/restructuring
        """
        score = 0.0
        reasons = []
        data_points = recent_events or []

        # Playbook contribution
        if playbook == "A":
            score += 4  # Aggressive sponsor = elevated risk
            reasons.append("Aggressive sponsor situation")
        elif playbook == "B":
            score += 5  # Maturity wall = clear deterioration path
            reasons.append("Maturity wall pressure")
        elif playbook == "MIXED":
            score += 3
            reasons.append("Mixed signals")

        # Maturity risk
        maturity_scores = {
            "very_high": 3,
            "high": 2,
            "medium": 1,
            "low": 0
        }
        score += maturity_scores.get(maturity_risk, 0)
        if maturity_risk in ["very_high", "high"]:
            reasons.append(f"Maturity risk: {maturity_risk}")

        # Sponsor aggression (for Playbook A situations)
        if playbook == "A" and sponsor_aggression >= 8:
            score += 2
            reasons.append(f"Very high sponsor aggression ({sponsor_aggression}/10)")
        elif sponsor_aggression >= 7:
            score += 1
            reasons.append(f"High sponsor aggression ({sponsor_aggression}/10)")

        # Recent events boost
        if recent_events:
            event_keywords = ["downgrade", "default", "restructur", "covenant", "waiver"]
            for event in recent_events:
                if any(kw in event.lower() for kw in event_keywords):
                    score += 0.5
                    data_points.append(event)

        score = min(10, max(0, score))

        return SignalComponent(
            name="credit_signal",
            score=round(score, 1),
            weight=self.weights["credit_signal"],
            reasoning="; ".join(reasons) if reasons else "No significant credit concerns",
            data_points=data_points
        )

    def score_psychology(
        self,
        equity_performance_30d: Optional[float] = None,
        analyst_sentiment: Optional[str] = None,
        retail_positioning: Optional[str] = None,
        news_sentiment: Optional[str] = None
    ) -> SignalComponent:
        """
        Score psychology alignment (0-10).

        1-3: Market already pricing risk - no edge
        4-5: Some awareness, but not fully priced
        6-7: Market complacent - clear mispricing
        8-9: Extreme complacency or denial
        10: Total disconnect between credit reality and equity pricing
        """
        score = 5.0  # Neutral starting point
        reasons = []

        # Equity performance (if credit is deteriorating but equity is up = disconnect)
        if equity_performance_30d is not None:
            if equity_performance_30d > 10:
                score += 2
                reasons.append(f"Equity up {equity_performance_30d:.1f}% despite credit stress")
            elif equity_performance_30d > 5:
                score += 1
                reasons.append("Equity resilient")
            elif equity_performance_30d < -15:
                score -= 2
                reasons.append("Equity already pricing distress")
            elif equity_performance_30d < -5:
                score -= 1
                reasons.append("Some equity weakness")

        # Analyst sentiment
        if analyst_sentiment:
            sentiment_scores = {
                "bullish": 2,  # Analysts bullish while credit deteriorates = edge
                "neutral": 0,
                "bearish": -2  # Already aware
            }
            score += sentiment_scores.get(analyst_sentiment.lower(), 0)
            if analyst_sentiment.lower() == "bullish":
                reasons.append("Analysts still bullish")

        # Retail positioning
        if retail_positioning:
            if retail_positioning.lower() == "long":
                score += 1.5
                reasons.append("Retail positioned long")
            elif retail_positioning.lower() == "short":
                score -= 1
                reasons.append("Retail already short")

        # News sentiment
        if news_sentiment:
            if news_sentiment.lower() == "positive":
                score += 1
                reasons.append("Positive news narrative")
            elif news_sentiment.lower() == "negative":
                score -= 1
                reasons.append("Negative narrative established")

        score = min(10, max(0, score))

        return SignalComponent(
            name="psychology_alignment",
            score=round(score, 1),
            weight=self.weights["psychology_alignment"],
            reasoning="; ".join(reasons) if reasons else "Neutral market positioning"
        )

    def score_options(
        self,
        iv_percentile: Optional[float] = None,
        iv_vs_realized: Optional[float] = None,
        put_call_ratio: Optional[float] = None,
        skew: Optional[float] = None
    ) -> SignalComponent:
        """
        Score options mispricing (0-10).

        1-3: Options fairly priced - no edge
        4-5: Slight mispricing
        6-7: Clear mispricing - IV too low given credit risk
        8-9: Significant mispricing - cheap protection
        10: Extreme mispricing - gift
        """
        score = 5.0  # Neutral
        reasons = []

        # IV percentile (lower = cheaper options)
        if iv_percentile is not None:
            if iv_percentile < 15:
                score += 3
                reasons.append(f"IV at {iv_percentile:.0f}th percentile - very cheap")
            elif iv_percentile < 30:
                score += 2
                reasons.append(f"IV at {iv_percentile:.0f}th percentile - cheap")
            elif iv_percentile < 50:
                score += 1
                reasons.append(f"IV at {iv_percentile:.0f}th percentile - reasonable")
            elif iv_percentile > 80:
                score -= 2
                reasons.append(f"IV at {iv_percentile:.0f}th percentile - expensive")
            elif iv_percentile > 65:
                score -= 1
                reasons.append(f"IV elevated at {iv_percentile:.0f}th percentile")

        # IV vs realized (IV < realized = cheap options)
        if iv_vs_realized is not None:
            if iv_vs_realized < 0.8:
                score += 2
                reasons.append("IV significantly below realized vol")
            elif iv_vs_realized < 1.0:
                score += 1
                reasons.append("IV below realized vol")
            elif iv_vs_realized > 1.3:
                score -= 1
                reasons.append("IV above realized vol")

        # Put/call ratio (low = puts are cheap/overlooked)
        if put_call_ratio is not None:
            if put_call_ratio < 0.5:
                score += 1.5
                reasons.append("Low put/call ratio - puts overlooked")
            elif put_call_ratio > 1.5:
                score -= 1
                reasons.append("High put/call ratio - puts already crowded")

        # Skew (steep skew = puts expensive relative to calls)
        if skew is not None:
            if skew < -0.05:
                score += 1
                reasons.append("Flat skew - puts not expensive")
            elif skew > 0.10:
                score -= 1
                reasons.append("Steep skew - puts relatively expensive")

        score = min(10, max(0, score))

        return SignalComponent(
            name="options_mispricing",
            score=round(score, 1),
            weight=self.weights["options_mispricing"],
            reasoning="; ".join(reasons) if reasons else "Options fairly priced"
        )

    def score_catalyst(
        self,
        catalyst_type: Optional[str] = None,
        days_to_catalyst: Optional[int] = None,
        catalyst_certainty: Optional[str] = None
    ) -> SignalComponent:
        """
        Score catalyst clarity (0-10).

        1-3: No clear catalyst - vague timing
        4-5: Potential catalyst within 6 months
        6-7: Known catalyst within 3 months
        8-9: Imminent catalyst within 1 month
        10: Catalyst this week
        """
        score = 3.0  # Default: vague timing
        reasons = []

        if catalyst_type:
            # Catalyst type contribution
            type_scores = {
                "earnings": 2,
                "maturity": 3,
                "rating_review": 2,
                "covenant_test": 3,
                "refinancing": 2,
                "m&a": 1,
                "restructuring": 3
            }
            score += type_scores.get(catalyst_type.lower(), 1)
            reasons.append(f"Catalyst: {catalyst_type}")

        if days_to_catalyst is not None:
            if days_to_catalyst <= 7:
                score += 4
                reasons.append(f"Catalyst in {days_to_catalyst} days")
            elif days_to_catalyst <= 30:
                score += 3
                reasons.append(f"Catalyst within 1 month")
            elif days_to_catalyst <= 90:
                score += 2
                reasons.append(f"Catalyst within 3 months")
            elif days_to_catalyst <= 180:
                score += 1
                reasons.append(f"Catalyst within 6 months")

        if catalyst_certainty:
            certainty_scores = {
                "confirmed": 1,
                "likely": 0.5,
                "possible": 0,
                "unlikely": -1
            }
            score += certainty_scores.get(catalyst_certainty.lower(), 0)

        score = min(10, max(0, score))

        return SignalComponent(
            name="catalyst_clarity",
            score=round(score, 1),
            weight=self.weights["catalyst_clarity"],
            reasoning="; ".join(reasons) if reasons else "No clear catalyst identified"
        )

    def score_pattern(
        self,
        company: str,
        playbook: str,
        sector: str,
        component_scores: Optional[Dict[str, float]] = None
    ) -> SignalComponent:
        """
        Score historical pattern match (0-10).

        Uses the pattern learner for enhanced matching against the full
        pattern database (seed + learned patterns).

        1-3: No similar patterns in database
        4-5: Weak pattern match
        6-7: Strong pattern match - similar setup worked before
        8-9: Very close match to successful past trades
        10: Almost identical to high-conviction winner
        """
        score = self._pattern_learner.get_pattern_match_score(
            company=company,
            playbook=playbook,
            sector=sector,
            component_scores=component_scores
        )

        stats = self._pattern_learner.get_stats()
        reasons = [
            f"Matched against {stats['total_patterns']} patterns "
            f"({stats['learned_patterns']} learned)"
        ]

        if score >= 7:
            reasons.append("Strong historical precedent found")
        elif score >= 5:
            reasons.append("Moderate pattern match")
        else:
            reasons.append("Weak or no pattern match")

        return SignalComponent(
            name="pattern_match",
            score=round(min(10, max(0, score)), 1),
            weight=self.weights["pattern_match"],
            reasoning="; ".join(reasons)
        )

    def calculate_edge(
        self,
        company: str,
        ticker: str,
        # Credit inputs
        playbook: str,
        maturity_risk: str,
        sponsor_aggression: int = 0,
        recent_events: List[str] = None,
        # Psychology inputs
        equity_performance_30d: float = None,
        analyst_sentiment: str = None,
        # Options inputs
        iv_percentile: float = None,
        iv_vs_realized: float = None,
        # Catalyst inputs
        catalyst_type: str = None,
        days_to_catalyst: int = None,
        # Pattern inputs
        sector: str = "Unknown"
    ) -> EdgeScore:
        """
        Calculate complete edge score for a trading opportunity.
        """
        # Score each component
        credit = self.score_credit_signal(
            playbook=playbook,
            maturity_risk=maturity_risk,
            sponsor_aggression=sponsor_aggression,
            recent_events=recent_events
        )

        psychology = self.score_psychology(
            equity_performance_30d=equity_performance_30d,
            analyst_sentiment=analyst_sentiment
        )

        options = self.score_options(
            iv_percentile=iv_percentile,
            iv_vs_realized=iv_vs_realized
        )

        catalyst = self.score_catalyst(
            catalyst_type=catalyst_type,
            days_to_catalyst=days_to_catalyst
        )

        # Collect component scores for pattern matching
        component_scores = {
            "credit_signal": credit.score,
            "psychology_alignment": psychology.score,
            "options_mispricing": options.score,
            "catalyst_clarity": catalyst.score
        }

        pattern = self.score_pattern(
            company=company,
            playbook=playbook,
            sector=sector,
            component_scores=component_scores
        )

        # Determine recommended direction based on playbook
        if playbook == "A":
            direction = "STRADDLE"  # Binary outcome
        elif playbook == "B":
            direction = "LONG_PUT"  # Predictable deterioration
        elif playbook == "MIXED":
            direction = "LONG_PUT"  # Default to puts with caution
        else:
            direction = None

        # Create edge score
        edge = EdgeScore(
            company=company,
            ticker=ticker,
            timestamp=datetime.now(),
            credit_signal=credit,
            psychology_alignment=psychology,
            options_mispricing=options,
            catalyst_clarity=catalyst,
            pattern_match=pattern,
            playbook=playbook,
            sector=sector,
            recommended_direction=direction
        )

        return edge


def main():
    """Test the edge scorer."""
    print("=" * 60)
    print("EDGE SCORER - TEST")
    print("=" * 60)

    scorer = EdgeScorer()

    # Test case 1: Grifols (Playbook B, high maturity risk)
    print("\n--- Test: Grifols ---")
    edge1 = scorer.calculate_edge(
        company="Grifols, S.A.",
        ticker="GRFS",
        playbook="B",
        maturity_risk="high",
        sponsor_aggression=3,
        recent_events=["Short seller attack 2024", "Governance concerns"],
        equity_performance_30d=5.2,  # Equity up despite issues
        analyst_sentiment="neutral",
        iv_percentile=68,
        catalyst_type="maturity",
        days_to_catalyst=180,
        sector="Consumers"
    )
    print(edge1.format_telegram())

    # Test case 2: SBB (Playbook B, very high maturity risk)
    print("\n--- Test: SBB ---")
    edge2 = scorer.calculate_edge(
        company="SBB",
        ticker="SBB-B.ST",
        playbook="B",
        maturity_risk="very_high",
        sponsor_aggression=4,
        recent_events=["CCC rating", "Swedish RE crisis", "Capital markets unreceptive"],
        equity_performance_30d=-8.5,
        analyst_sentiment="bearish",
        iv_percentile=45,
        catalyst_type="refinancing",
        days_to_catalyst=90,
        sector="Financials"
    )
    print(edge2.format_telegram())

    # Test case 3: INEOS (Playbook A, aggressive sponsor)
    print("\n--- Test: INEOS ---")
    edge3 = scorer.calculate_edge(
        company="INEOS Finance plc",
        ticker="N/A",
        playbook="A",
        maturity_risk="medium",
        sponsor_aggression=7,
        analyst_sentiment="bullish",
        equity_performance_30d=12.0,  # Equity up = disconnect
        iv_percentile=25,  # Cheap options
        catalyst_type="earnings",
        days_to_catalyst=45,
        sector="Autos & Industrials"
    )
    print(edge3.format_telegram())

    # Summary
    print("\n--- Summary ---")
    for edge in [edge1, edge2, edge3]:
        print(f"{edge.company}: Score {edge.total_score}/10 | {edge.trade_recommendation} | {edge.recommended_direction}")


if __name__ == "__main__":
    main()

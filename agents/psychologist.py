"""
Psychologist Agent for Credit Catalyst

Predicts how and when humans will react to credit deterioration.
Key insight: Credit signals can fire weeks/months before equity reprices.

The agent models:
1. Market participant positioning (who owns this?)
2. Cognitive biases (anchoring, confirmation bias, recency)
3. Information asymmetry (who knows what?)
4. Reaction timing (when will the market wake up?)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json


class MarketParticipant(Enum):
    """Types of market participants with different behaviors."""
    RETAIL = "retail"
    HEDGE_FUNDS = "hedge_funds"
    PENSION_FUNDS = "pension_funds"
    PASSIVE_ETF = "passive_etf"
    CREDIT_INVESTORS = "credit_investors"
    EQUITY_ANALYSTS = "equity_analysts"


class CognitiveBias(Enum):
    """Cognitive biases that create mispricing."""
    ANCHORING = "anchoring"  # Stuck on old price/thesis
    CONFIRMATION = "confirmation"  # Ignoring contrary evidence
    RECENCY = "recency"  # Overweighting recent events
    HERDING = "herding"  # Following the crowd
    AVAILABILITY = "availability"  # Overweighting memorable events
    NORMALCY = "normalcy"  # "It won't happen here"


class ReactionTiming(Enum):
    """When market will react to credit deterioration."""
    IMMEDIATE = "immediate"  # Already pricing it
    DAYS = "days"  # Will react within days
    WEEKS = "weeks"  # 1-4 weeks
    MONTHS = "months"  # 1-3 months
    QUARTERS = "quarters"  # 3+ months
    NEVER = "never"  # May never fully price it


@dataclass
class ParticipantProfile:
    """Profile of a market participant group."""
    type: MarketParticipant
    estimated_ownership_pct: float
    typical_holding_period: str  # "days", "weeks", "months", "years"
    reaction_speed: str  # "fast", "medium", "slow"
    information_sources: List[str]
    biases: List[CognitiveBias]
    trigger_events: List[str]  # What causes them to act


@dataclass
class PsychologyAssessment:
    """Complete psychology assessment for a company."""
    company: str
    timestamp: datetime

    # Participant analysis
    dominant_participants: List[ParticipantProfile]
    positioning: str  # "crowded_long", "balanced", "crowded_short"

    # Bias analysis
    active_biases: List[Tuple[CognitiveBias, str]]  # (bias, evidence)
    bias_strength: float  # 0-10

    # Information asymmetry
    information_gap: float  # 0-10 (how much do credit investors know that equity doesn't?)
    gap_description: str

    # Timing prediction
    predicted_reaction: ReactionTiming
    catalyst_required: bool
    potential_triggers: List[str]

    # Edge calculation
    psychology_score: float  # 0-10 for edge scorer
    notes: List[str] = field(default_factory=list)


class Psychologist:
    """
    Models market psychology to identify mispricing opportunities.

    Key principles:
    1. Different participants have different information and biases
    2. Credit investors often know before equity investors
    3. Passive flows can delay or accelerate repricing
    4. Cognitive biases create predictable patterns
    """

    # Standard participant profiles
    PARTICIPANT_PROFILES = {
        MarketParticipant.RETAIL: ParticipantProfile(
            type=MarketParticipant.RETAIL,
            estimated_ownership_pct=15,
            typical_holding_period="weeks",
            reaction_speed="slow",
            information_sources=["news", "social_media", "broker_research"],
            biases=[CognitiveBias.RECENCY, CognitiveBias.HERDING, CognitiveBias.ANCHORING],
            trigger_events=["price_drop", "news_headline", "social_media_buzz"]
        ),
        MarketParticipant.HEDGE_FUNDS: ParticipantProfile(
            type=MarketParticipant.HEDGE_FUNDS,
            estimated_ownership_pct=20,
            typical_holding_period="months",
            reaction_speed="fast",
            information_sources=["credit_analysis", "primary_research", "expert_networks"],
            biases=[CognitiveBias.CONFIRMATION],
            trigger_events=["credit_events", "earnings", "rating_actions", "covenant_breach"]
        ),
        MarketParticipant.PENSION_FUNDS: ParticipantProfile(
            type=MarketParticipant.PENSION_FUNDS,
            estimated_ownership_pct=25,
            typical_holding_period="years",
            reaction_speed="slow",
            information_sources=["ratings", "benchmark_inclusion"],
            biases=[CognitiveBias.NORMALCY, CognitiveBias.ANCHORING],
            trigger_events=["rating_downgrade_to_junk", "index_exclusion"]
        ),
        MarketParticipant.PASSIVE_ETF: ParticipantProfile(
            type=MarketParticipant.PASSIVE_ETF,
            estimated_ownership_pct=30,
            typical_holding_period="permanent",
            reaction_speed="delayed",
            information_sources=["index_rules"],
            biases=[],
            trigger_events=["index_rebalance", "index_exclusion"]
        ),
        MarketParticipant.CREDIT_INVESTORS: ParticipantProfile(
            type=MarketParticipant.CREDIT_INVESTORS,
            estimated_ownership_pct=0,  # Own bonds, not equity
            typical_holding_period="months",
            reaction_speed="fast",
            information_sources=["covenants", "cash_flows", "maturity_schedule", "restructuring_advisors"],
            biases=[],
            trigger_events=["covenant_breach", "maturity_approaching", "sponsor_behavior"]
        ),
    }

    # Bias indicators
    BIAS_INDICATORS = {
        CognitiveBias.ANCHORING: [
            "stock_near_52w_high",
            "analysts_maintaining_price_targets",
            "comparing_to_historical_multiples"
        ],
        CognitiveBias.CONFIRMATION: [
            "ignoring_negative_news",
            "cherry_picking_positive_data",
            "dismissing_short_reports"
        ],
        CognitiveBias.RECENCY: [
            "extrapolating_recent_performance",
            "ignoring_structural_changes",
            "overweighting_last_quarter"
        ],
        CognitiveBias.HERDING: [
            "following_analyst_consensus",
            "momentum_driven_buying",
            "fear_of_missing_out"
        ],
        CognitiveBias.NORMALCY: [
            "assuming_refinancing_success",
            "ignoring_maturity_wall",
            "believing_sponsor_support"
        ]
    }

    def __init__(self):
        pass

    def assess_positioning(
        self,
        short_interest_pct: Optional[float] = None,
        institutional_ownership_pct: Optional[float] = None,
        retail_sentiment: Optional[str] = None,
        analyst_ratings: Optional[Dict] = None
    ) -> Tuple[str, float]:
        """
        Assess market positioning.

        Returns (positioning, crowd_score)
        - positioning: crowded_long, balanced, crowded_short
        - crowd_score: 0-10 (10 = extremely crowded long = more edge for shorts)
        """
        score = 5.0  # Neutral

        if short_interest_pct is not None:
            if short_interest_pct < 2:
                score += 2  # Low short interest = crowded long
            elif short_interest_pct < 5:
                score += 1
            elif short_interest_pct > 15:
                score -= 2  # High short interest = already crowded short
            elif short_interest_pct > 10:
                score -= 1

        if institutional_ownership_pct is not None:
            if institutional_ownership_pct > 80:
                score += 1.5  # High inst. ownership can mean crowded
            elif institutional_ownership_pct < 40:
                score -= 1  # Low inst. = retail dominated, different dynamics

        if retail_sentiment:
            sentiment_scores = {
                "very_bullish": 2,
                "bullish": 1,
                "neutral": 0,
                "bearish": -1,
                "very_bearish": -2
            }
            score += sentiment_scores.get(retail_sentiment.lower(), 0)

        if analyst_ratings:
            buy_pct = analyst_ratings.get("buy", 0) / max(sum(analyst_ratings.values()), 1)
            if buy_pct > 0.7:
                score += 1.5  # Analysts very bullish = potential edge
            elif buy_pct < 0.3:
                score -= 1

        score = min(10, max(0, score))

        if score >= 7:
            positioning = "crowded_long"
        elif score <= 3:
            positioning = "crowded_short"
        else:
            positioning = "balanced"

        return positioning, score

    def detect_biases(
        self,
        stock_vs_52w_high: Optional[float] = None,
        analyst_target_vs_current: Optional[float] = None,
        recent_news_sentiment: Optional[str] = None,
        credit_vs_equity_spread: Optional[float] = None
    ) -> List[Tuple[CognitiveBias, str, float]]:
        """
        Detect active cognitive biases.

        Returns list of (bias, evidence, strength)
        """
        biases = []

        # Anchoring detection
        if stock_vs_52w_high is not None and stock_vs_52w_high > 0.85:
            biases.append((
                CognitiveBias.ANCHORING,
                f"Stock at {stock_vs_52w_high*100:.0f}% of 52w high - anchoring likely",
                7.0
            ))

        if analyst_target_vs_current is not None and analyst_target_vs_current > 1.3:
            biases.append((
                CognitiveBias.ANCHORING,
                f"Analyst targets {(analyst_target_vs_current-1)*100:.0f}% above current - anchored to old thesis",
                6.0
            ))

        # Normalcy bias detection
        if credit_vs_equity_spread is not None and credit_vs_equity_spread > 200:
            biases.append((
                CognitiveBias.NORMALCY,
                f"Credit spreads {credit_vs_equity_spread}bps wide but equity stable - normalcy bias",
                8.0
            ))

        # Confirmation bias
        if recent_news_sentiment == "mixed_ignored_negative":
            biases.append((
                CognitiveBias.CONFIRMATION,
                "Negative news being dismissed - confirmation bias active",
                7.0
            ))

        return biases

    def estimate_information_gap(
        self,
        playbook: str,
        credit_rating: Optional[str] = None,
        recent_covenant_breach: bool = False,
        restructuring_advisors_hired: bool = False,
        insider_selling: bool = False
    ) -> Tuple[float, str]:
        """
        Estimate information asymmetry between credit and equity investors.

        Returns (gap_score, description)
        - gap_score: 0-10 (10 = massive information gap = big edge)
        """
        gap = 3.0  # Base level of asymmetry
        reasons = []

        # Playbook A situations often have information gaps
        if playbook == "A":
            gap += 2
            reasons.append("Aggressive sponsor - insider information advantage")

        # Rating changes signal credit awareness
        if credit_rating and credit_rating.startswith("C"):
            gap += 2
            reasons.append("CCC-rated - credit investors aware of distress")

        if recent_covenant_breach:
            gap += 2.5
            reasons.append("Recent covenant breach - credit docs public but overlooked")

        if restructuring_advisors_hired:
            gap += 3
            reasons.append("Restructuring advisors hired - equity may not know")

        if insider_selling:
            gap += 1.5
            reasons.append("Insider selling - management knows something")

        gap = min(10, gap)
        description = "; ".join(reasons) if reasons else "Normal information environment"

        return gap, description

    def predict_reaction_timing(
        self,
        positioning: str,
        information_gap: float,
        days_to_catalyst: Optional[int] = None,
        passive_ownership_pct: Optional[float] = None
    ) -> Tuple[ReactionTiming, List[str]]:
        """
        Predict when market will react to credit deterioration.

        Returns (timing, potential_triggers)
        """
        triggers = []

        # High information gap = delayed reaction
        if information_gap >= 8:
            if days_to_catalyst and days_to_catalyst <= 30:
                timing = ReactionTiming.DAYS
                triggers.append(f"Catalyst in {days_to_catalyst} days will force recognition")
            else:
                timing = ReactionTiming.WEEKS
                triggers.append("High info gap but no imminent catalyst")
        elif information_gap >= 5:
            timing = ReactionTiming.WEEKS
            triggers.append("Moderate info gap - will react on next news")
        else:
            timing = ReactionTiming.IMMEDIATE
            triggers.append("Low info gap - market already pricing risk")

        # Crowded positioning affects timing
        if positioning == "crowded_long":
            triggers.append("Crowded long - forced selling on any catalyst")
        elif positioning == "crowded_short":
            timing = ReactionTiming.IMMEDIATE
            triggers.append("Already crowded short - no edge")

        # Passive ownership delays reaction
        if passive_ownership_pct and passive_ownership_pct > 40:
            if timing == ReactionTiming.DAYS:
                timing = ReactionTiming.WEEKS
            triggers.append(f"High passive ownership ({passive_ownership_pct:.0f}%) delays repricing")

        return timing, triggers

    def assess(
        self,
        company: str,
        playbook: str,
        # Positioning inputs
        short_interest_pct: float = None,
        institutional_ownership_pct: float = None,
        retail_sentiment: str = None,
        analyst_ratings: Dict = None,
        # Bias detection inputs
        stock_vs_52w_high: float = None,
        analyst_target_vs_current: float = None,
        credit_vs_equity_spread: float = None,
        # Information gap inputs
        credit_rating: str = None,
        recent_covenant_breach: bool = False,
        restructuring_advisors_hired: bool = False,
        insider_selling: bool = False,
        # Timing inputs
        days_to_catalyst: int = None,
        passive_ownership_pct: float = None
    ) -> PsychologyAssessment:
        """
        Complete psychology assessment for a company.
        """
        # Assess positioning
        positioning, crowd_score = self.assess_positioning(
            short_interest_pct=short_interest_pct,
            institutional_ownership_pct=institutional_ownership_pct,
            retail_sentiment=retail_sentiment,
            analyst_ratings=analyst_ratings
        )

        # Detect biases
        biases = self.detect_biases(
            stock_vs_52w_high=stock_vs_52w_high,
            analyst_target_vs_current=analyst_target_vs_current,
            credit_vs_equity_spread=credit_vs_equity_spread
        )

        # Estimate information gap
        info_gap, gap_desc = self.estimate_information_gap(
            playbook=playbook,
            credit_rating=credit_rating,
            recent_covenant_breach=recent_covenant_breach,
            restructuring_advisors_hired=restructuring_advisors_hired,
            insider_selling=insider_selling
        )

        # Predict timing
        timing, triggers = self.predict_reaction_timing(
            positioning=positioning,
            information_gap=info_gap,
            days_to_catalyst=days_to_catalyst,
            passive_ownership_pct=passive_ownership_pct
        )

        # Calculate psychology score for edge scorer
        # Higher score = more edge from psychology
        psych_score = 0.0

        # Positioning contribution (0-3)
        if positioning == "crowded_long":
            psych_score += 3
        elif positioning == "balanced":
            psych_score += 1.5

        # Bias contribution (0-3)
        if biases:
            avg_bias_strength = sum(b[2] for b in biases) / len(biases)
            psych_score += min(3, avg_bias_strength / 3)

        # Information gap contribution (0-2.5)
        psych_score += info_gap / 4

        # Timing penalty - if immediate, less edge
        if timing == ReactionTiming.IMMEDIATE:
            psych_score *= 0.5
        elif timing == ReactionTiming.NEVER:
            psych_score *= 0.3

        psych_score = min(10, max(0, psych_score))

        # Build notes
        notes = []
        if positioning == "crowded_long":
            notes.append("Market crowded long - forced selling likely on catalyst")
        if biases:
            notes.append(f"Active biases: {', '.join(b[0].value for b in biases)}")
        if info_gap >= 7:
            notes.append("Large information gap - credit knows more than equity")
        notes.append(f"Expected reaction timing: {timing.value}")

        return PsychologyAssessment(
            company=company,
            timestamp=datetime.now(),
            dominant_participants=[
                self.PARTICIPANT_PROFILES[MarketParticipant.PASSIVE_ETF],
                self.PARTICIPANT_PROFILES[MarketParticipant.PENSION_FUNDS]
            ],
            positioning=positioning,
            active_biases=[(b[0], b[1]) for b in biases],
            bias_strength=sum(b[2] for b in biases) / len(biases) if biases else 0,
            information_gap=info_gap,
            gap_description=gap_desc,
            predicted_reaction=timing,
            catalyst_required=timing in [ReactionTiming.WEEKS, ReactionTiming.MONTHS],
            potential_triggers=triggers,
            psychology_score=round(psych_score, 1),
            notes=notes
        )


def main():
    """Test the psychologist agent."""
    print("=" * 60)
    print("PSYCHOLOGIST AGENT - TEST")
    print("=" * 60)

    psych = Psychologist()

    # Test 1: Grifols - post short-seller attack
    print("\n--- Test: Grifols ---")
    assessment1 = psych.assess(
        company="Grifols",
        playbook="B",
        short_interest_pct=8.5,
        institutional_ownership_pct=65,
        retail_sentiment="bearish",
        analyst_ratings={"buy": 8, "hold": 12, "sell": 3},
        stock_vs_52w_high=0.45,  # Beaten down
        analyst_target_vs_current=1.8,  # Targets still high
        credit_rating="B+",
        days_to_catalyst=180
    )
    print(f"Company: {assessment1.company}")
    print(f"Positioning: {assessment1.positioning}")
    print(f"Information Gap: {assessment1.information_gap}/10 - {assessment1.gap_description}")
    print(f"Reaction Timing: {assessment1.predicted_reaction.value}")
    print(f"Psychology Score: {assessment1.psychology_score}/10")
    print(f"Notes: {assessment1.notes}")

    # Test 2: SBB - Swedish RE crisis
    print("\n--- Test: SBB ---")
    assessment2 = psych.assess(
        company="SBB",
        playbook="B",
        short_interest_pct=3.2,
        institutional_ownership_pct=55,
        retail_sentiment="neutral",
        stock_vs_52w_high=0.25,  # Collapsed
        analyst_target_vs_current=2.5,  # Still anchored
        credit_vs_equity_spread=800,  # Very wide
        credit_rating="CCC",
        recent_covenant_breach=True,
        restructuring_advisors_hired=True,
        days_to_catalyst=90,
        passive_ownership_pct=20
    )
    print(f"Company: {assessment2.company}")
    print(f"Positioning: {assessment2.positioning}")
    print(f"Active Biases: {[b[0].value for b in assessment2.active_biases]}")
    print(f"Information Gap: {assessment2.information_gap}/10")
    print(f"Reaction Timing: {assessment2.predicted_reaction.value}")
    print(f"Triggers: {assessment2.potential_triggers}")
    print(f"Psychology Score: {assessment2.psychology_score}/10")

    # Test 3: INEOS - aggressive sponsor
    print("\n--- Test: INEOS ---")
    assessment3 = psych.assess(
        company="INEOS",
        playbook="A",
        short_interest_pct=1.5,  # Low shorts
        institutional_ownership_pct=70,
        retail_sentiment="bullish",
        analyst_ratings={"buy": 15, "hold": 5, "sell": 1},
        stock_vs_52w_high=0.92,  # Near highs
        analyst_target_vs_current=1.15,
        credit_rating="B",
        insider_selling=True,
        days_to_catalyst=45,
        passive_ownership_pct=35
    )
    print(f"Company: {assessment3.company}")
    print(f"Positioning: {assessment3.positioning}")
    print(f"Active Biases: {[b[0].value for b in assessment3.active_biases]}")
    print(f"Information Gap: {assessment3.information_gap}/10 - {assessment3.gap_description}")
    print(f"Psychology Score: {assessment3.psychology_score}/10")
    print(f"Notes: {assessment3.notes}")

    # Summary
    print("\n--- Summary ---")
    for a in [assessment1, assessment2, assessment3]:
        print(f"{a.company}: Psychology Score {a.psychology_score}/10 | {a.positioning} | Timing: {a.predicted_reaction.value}")


if __name__ == "__main__":
    main()

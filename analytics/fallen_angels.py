"""
Fallen Angel / Rising Star Screener

Identifies credits at risk of:
- Fallen angel: IG → HY downgrade (forced selling, spread widening)
- Rising star: HY → IG upgrade (forced buying, spread tightening)

Based on:
- Rating agency outlook/watch status
- Fundamental trajectory (leverage, coverage, FCF)
- Spread levels relative to rating boundaries
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class TransitionCandidate:
    """A credit with potential rating transition."""
    entity_name: str
    current_rating: str
    outlook: str                    # stable / negative / positive / watch_negative / watch_positive
    transition_type: str            # fallen_angel / rising_star
    probability: float              # Estimated probability (0-1)
    timeline_months: int            # Expected timeline
    spread_bps: float               # Current spread
    spread_at_transition: float     # Expected spread post-transition
    pnl_impact_pct: float           # Expected P&L impact
    triggers: List[str]             # Key triggers to watch
    sector: str = ""


# Rating boundaries (S&P scale)
IG_RATINGS = {"AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"}
HY_RATINGS = {"BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D"}

# Ratings at the IG/HY boundary
FALLEN_ANGEL_RISK = {"BBB-", "BBB"}      # Low IG, at risk of falling
RISING_STAR_CANDIDATES = {"BB+", "BB"}    # High HY, may be upgraded


def screen_fallen_angels(
    credits: List[Dict],
) -> List[TransitionCandidate]:
    """
    Screen universe for fallen angel risk.

    Args:
        credits: List of dicts with keys: entity_name, rating, outlook,
                 spread_bps, leverage, interest_coverage, sector

    Returns:
        List of fallen angel candidates sorted by probability
    """
    candidates = []

    for credit in credits:
        rating = credit.get("rating", "")
        if rating not in FALLEN_ANGEL_RISK:
            continue

        outlook = credit.get("outlook", "stable")
        spread = credit.get("spread_bps", 0.0)
        leverage = credit.get("leverage", 0.0)
        coverage = credit.get("interest_coverage", 0.0)

        # Score probability
        prob = 0.0
        triggers = []

        # Outlook/watch status
        if "watch_negative" in outlook.lower():
            prob += 0.40
            triggers.append("On negative CreditWatch")
        elif "negative" in outlook.lower():
            prob += 0.25
            triggers.append("Negative outlook")

        # Fundamental deterioration
        if leverage > 4.0:
            prob += 0.15
            triggers.append(f"High leverage: {leverage:.1f}x")
        if coverage < 3.0:
            prob += 0.10
            triggers.append(f"Low interest coverage: {coverage:.1f}x")

        # Spread already pricing HY
        if rating == "BBB-" and spread > 250:
            prob += 0.10
            triggers.append(f"Spread at {spread:.0f}bps (HY-like)")

        if prob >= 0.15:
            candidates.append(TransitionCandidate(
                entity_name=credit["entity_name"],
                current_rating=rating,
                outlook=outlook,
                transition_type="fallen_angel",
                probability=min(prob, 0.95),
                timeline_months=6 if "watch" in outlook.lower() else 12,
                spread_bps=spread,
                spread_at_transition=spread * 1.5,  # Typical 50% widening
                pnl_impact_pct=-30.0,  # Typical FA impact
                triggers=triggers,
                sector=credit.get("sector", ""),
            ))

    candidates.sort(key=lambda c: c.probability, reverse=True)
    return candidates


def screen_rising_stars(
    credits: List[Dict],
) -> List[TransitionCandidate]:
    """
    Screen universe for rising star potential.

    Args:
        credits: Same format as screen_fallen_angels

    Returns:
        List of rising star candidates sorted by probability
    """
    candidates = []

    for credit in credits:
        rating = credit.get("rating", "")
        if rating not in RISING_STAR_CANDIDATES:
            continue

        outlook = credit.get("outlook", "stable")
        spread = credit.get("spread_bps", 0.0)
        leverage = credit.get("leverage", 0.0)
        coverage = credit.get("interest_coverage", 0.0)

        prob = 0.0
        triggers = []

        if "watch_positive" in outlook.lower():
            prob += 0.40
            triggers.append("On positive CreditWatch")
        elif "positive" in outlook.lower():
            prob += 0.25
            triggers.append("Positive outlook")

        if leverage < 3.0:
            prob += 0.15
            triggers.append(f"Improving leverage: {leverage:.1f}x")
        if coverage > 5.0:
            prob += 0.10
            triggers.append(f"Strong coverage: {coverage:.1f}x")

        # Spread already pricing IG
        if rating == "BB+" and spread < 200:
            prob += 0.10
            triggers.append(f"Spread at {spread:.0f}bps (IG-like)")

        if prob >= 0.15:
            candidates.append(TransitionCandidate(
                entity_name=credit["entity_name"],
                current_rating=rating,
                outlook=outlook,
                transition_type="rising_star",
                probability=min(prob, 0.95),
                timeline_months=6 if "watch" in outlook.lower() else 12,
                spread_bps=spread,
                spread_at_transition=spread * 0.70,  # Typical 30% tightening
                pnl_impact_pct=20.0,
                triggers=triggers,
                sector=credit.get("sector", ""),
            ))

    candidates.sort(key=lambda c: c.probability, reverse=True)
    return candidates

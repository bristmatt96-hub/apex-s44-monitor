"""
Options Trade Structure Recommender

Given a catalyst type and market context, recommends the optimal
options structure (puts, spreads, straddles) with strike/expiry guidance.

Decision tree based on:
  - Catalyst type (maturity_wall, aggressive_sponsor, earnings, rating, sector)
  - IV percentile (cheap vol vs expensive vol)
  - Gap signal strength (STRONG, MODERATE, WEAK)
  - CDS spread level (distressed vs investment grade)

Usage:
    from analytics.trade_structurer import recommend_trade
    rec = recommend_trade("maturity_wall", iv_percentile=25, gap_signal="STRONG", spread_bps=600)
"""

from dataclasses import dataclass, asdict


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

@dataclass
class TradeRecommendation:
    """Recommended options trade structure."""
    structure: str            # OTM_PUT, ATM_PUT_SPREAD, STRADDLE, CALENDAR_PUT, FAR_OTM_PUT, SKIP
    strike_pct: float         # Strike as % of current price (0.85 = 85% of spot)
    expiry_months: int        # Recommended months to expiry
    rationale: str            # Human-readable explanation
    max_premium_pct: float    # Max premium as % of notional to risk
    target_delta: float       # Target option delta (negative for puts)
    catalyst_type: str        # The catalyst driving the recommendation
    conviction: str           # HIGH / MEDIUM / LOW
    risk_reward: str          # Description of risk/reward profile
    entry_notes: list[str]    # Tactical entry guidance

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Catalyst classifiers
# ---------------------------------------------------------------------------

CATALYST_TYPES = {
    "maturity_wall": "Near-term maturities with high refinancing risk",
    "aggressive_sponsor": "PE sponsor extracting value, binary outcome",
    "earnings_downgrade": "Deteriorating fundamentals, earnings misses",
    "rating_action": "Rating downgrade or negative outlook",
    "sector_stress": "Broad sector deterioration / contagion",
    "restructuring": "Active restructuring or distressed exchange",
    "unknown": "General credit deterioration",
}


def classify_catalyst(
    spread_bps: float,
    maturity_risk: str | None = None,
    sponsor_aggression: int | None = None,
    recent_filing_type: str | None = None,
) -> str:
    """Classify the primary catalyst type for a credit.

    Uses available information to determine the most likely driver.
    """
    if maturity_risk and maturity_risk.lower() in ("high", "very_high"):
        return "maturity_wall"

    if sponsor_aggression and sponsor_aggression >= 7:
        return "aggressive_sponsor"

    if recent_filing_type:
        ft = recent_filing_type.lower()
        if "restructur" in ft or "default" in ft:
            return "restructuring"
        if "downgrade" in ft or "rating" in ft:
            return "rating_action"
        if "earnings" in ft or "guidance" in ft:
            return "earnings_downgrade"

    if spread_bps > 800:
        return "restructuring"
    elif spread_bps > 500:
        return "maturity_wall"

    return "unknown"


# ---------------------------------------------------------------------------
# Trade recommendation engine
# ---------------------------------------------------------------------------

def recommend_trade(
    catalyst_type: str,
    iv_percentile: float | None = None,
    gap_signal: str = "NONE",
    spread_bps: float = 0,
    options_available: bool = True,
) -> TradeRecommendation:
    """Recommend an options trade structure.

    Args:
        catalyst_type: Type of credit catalyst
        iv_percentile: Current IV percentile (0-100, None if unknown)
        gap_signal: Gap signal strength (STRONG, MODERATE, WEAK, NONE)
        spread_bps: Current CDS spread
        options_available: Whether liquid options exist

    Returns:
        TradeRecommendation with structure, strikes, and guidance
    """
    # Default IV if unknown
    iv = iv_percentile if iv_percentile is not None else 50.0

    # No options available
    if not options_available:
        return TradeRecommendation(
            structure="SKIP",
            strike_pct=0,
            expiry_months=0,
            rationale="No liquid options available for this name",
            max_premium_pct=0,
            target_delta=0,
            catalyst_type=catalyst_type,
            conviction="LOW",
            risk_reward="N/A",
            entry_notes=["Consider index hedge (iTraxx Xover puts) instead"],
        )

    # Weak gap = no clear opportunity
    if gap_signal == "NONE":
        return TradeRecommendation(
            structure="MONITOR",
            strike_pct=0,
            expiry_months=0,
            rationale="No meaningful credit-equity gap detected",
            max_premium_pct=0,
            target_delta=0,
            catalyst_type=catalyst_type,
            conviction="LOW",
            risk_reward="N/A",
            entry_notes=["Continue monitoring for gap widening"],
        )

    # ------------------------------------------------------------------
    # MATURITY WALL
    # ------------------------------------------------------------------
    if catalyst_type == "maturity_wall":
        if iv < 25:
            return TradeRecommendation(
                structure="OTM_PUT",
                strike_pct=0.80,
                expiry_months=6,
                rationale="Maturity wall stress + cheap vol = buy OTM puts outright",
                max_premium_pct=2.0,
                target_delta=-0.20,
                catalyst_type=catalyst_type,
                conviction="HIGH" if gap_signal == "STRONG" else "MEDIUM",
                risk_reward="Asymmetric: risk 2% premium for 5-10x payoff on default/restructuring",
                entry_notes=[
                    "Buy 80% strike puts, 6 months out",
                    "Vol is cheap (bottom quartile) -- good entry",
                    "Size: risk max 2% of position notional",
                    "Add on further spread widening if vol stays low",
                ],
            )
        elif iv < 50:
            return TradeRecommendation(
                structure="ATM_PUT_SPREAD",
                strike_pct=0.95,
                expiry_months=3,
                rationale="Maturity wall + moderate vol = put spread to reduce premium",
                max_premium_pct=3.0,
                target_delta=-0.35,
                catalyst_type=catalyst_type,
                conviction="HIGH" if gap_signal == "STRONG" else "MEDIUM",
                risk_reward="Capped downside: pay 3% for 95/80 put spread, max gain ~15%",
                entry_notes=[
                    "Buy 95% put, sell 80% put, 3 months",
                    "Spread reduces premium cost vs outright put",
                    "Cap on downside gain at 80% strike",
                    "Roll if approaching expiry without move",
                ],
            )
        else:
            return TradeRecommendation(
                structure="FAR_OTM_PUT",
                strike_pct=0.70,
                expiry_months=9,
                rationale="Maturity wall but vol expensive = go far OTM + longer dated",
                max_premium_pct=1.5,
                target_delta=-0.10,
                catalyst_type=catalyst_type,
                conviction="MEDIUM" if gap_signal == "STRONG" else "LOW",
                risk_reward="Cheap lottery: risk 1.5% for tail payoff on restructuring",
                entry_notes=[
                    "Buy 70% strike puts, 9 months out",
                    "Vol expensive -- minimise premium with far OTM",
                    "Only works on actual restructuring/default",
                    "Consider waiting for vol to come down",
                ],
            )

    # ------------------------------------------------------------------
    # AGGRESSIVE SPONSOR
    # ------------------------------------------------------------------
    if catalyst_type == "aggressive_sponsor":
        if iv < 30:
            return TradeRecommendation(
                structure="STRADDLE",
                strike_pct=1.00,
                expiry_months=3,
                rationale="Aggressive sponsor = binary outcome, cheap vol = buy straddle",
                max_premium_pct=5.0,
                target_delta=0.0,
                catalyst_type=catalyst_type,
                conviction="MEDIUM",
                risk_reward="Pay ~5% premium for directional move; need >5% move to profit",
                entry_notes=[
                    "ATM straddle, 3 months",
                    "Sponsor actions create binary outcomes",
                    "Upside: recovery rally. Downside: dividend recap/LBO stress",
                    "Vol cheap enough to justify non-directional bet",
                ],
            )
        else:
            return TradeRecommendation(
                structure="SKIP",
                strike_pct=0,
                expiry_months=0,
                rationale="Aggressive sponsor but vol too expensive for straddle",
                max_premium_pct=0,
                target_delta=0,
                catalyst_type=catalyst_type,
                conviction="LOW",
                risk_reward="N/A",
                entry_notes=[
                    "Vol too high for straddle -- theta decay will eat premium",
                    "Wait for vol to normalise before entering",
                    "Consider single-name CDS instead",
                ],
            )

    # ------------------------------------------------------------------
    # EARNINGS DOWNGRADE
    # ------------------------------------------------------------------
    if catalyst_type == "earnings_downgrade":
        if iv < 40:
            return TradeRecommendation(
                structure="PUT_SPREAD",
                strike_pct=0.90,
                expiry_months=2,
                rationale="Earnings deterioration + moderate vol = buy put spread",
                max_premium_pct=3.0,
                target_delta=-0.30,
                catalyst_type=catalyst_type,
                conviction="HIGH" if gap_signal == "STRONG" else "MEDIUM",
                risk_reward="Risk 3% for 90/80 spread; needs 10% decline for max gain",
                entry_notes=[
                    "Buy 90% put, sell 80% put, 2 months",
                    "Time to earnings/guidance update",
                    "Spread reduces cost vs outright puts",
                    "Enter 3-4 weeks before expected catalyst",
                ],
            )
        else:
            return TradeRecommendation(
                structure="CALENDAR_PUT_SPREAD",
                strike_pct=0.90,
                expiry_months=3,
                rationale="Earnings risk but vol elevated = calendar spread to harvest near-term theta",
                max_premium_pct=2.0,
                target_delta=-0.25,
                catalyst_type=catalyst_type,
                conviction="MEDIUM" if gap_signal == "STRONG" else "LOW",
                risk_reward="Sell near-month put, buy far-month put at same strike; harvest term structure",
                entry_notes=[
                    "Sell 1-month 90% put, buy 3-month 90% put",
                    "Near-term theta decay partially funds position",
                    "Works if move is gradual not sudden",
                    "Close near-month leg before expiry",
                ],
            )

    # ------------------------------------------------------------------
    # RATING ACTION
    # ------------------------------------------------------------------
    if catalyst_type == "rating_action":
        return TradeRecommendation(
            structure="OTM_PUT",
            strike_pct=0.85,
            expiry_months=3,
            rationale="Rating downgrade = buy OTM puts, equity typically reprices -5-15%",
            max_premium_pct=2.5,
            target_delta=-0.25,
            catalyst_type=catalyst_type,
            conviction="HIGH" if gap_signal == "STRONG" else "MEDIUM",
            risk_reward="Risk 2.5% for 3-5x payoff on 10-15% equity decline post-downgrade",
            entry_notes=[
                "Buy 85% strike puts, 3 months out",
                "Rating actions are well-telegraphed in credit",
                "Equity typically reacts 1-5 days after downgrade",
                "Enter BEFORE the announcement, not after",
            ],
        )

    # ------------------------------------------------------------------
    # SECTOR STRESS
    # ------------------------------------------------------------------
    if catalyst_type == "sector_stress":
        return TradeRecommendation(
            structure="ETF_PUT",
            strike_pct=0.90,
            expiry_months=3,
            rationale="Sector-wide stress = use sector ETF puts for diversified exposure",
            max_premium_pct=3.0,
            target_delta=-0.30,
            catalyst_type=catalyst_type,
            conviction="MEDIUM",
            risk_reward="Sector ETF puts: less name-specific risk, broader beta exposure",
            entry_notes=[
                "Identify sector ETF (e.g. XLI for industrials)",
                "Buy 90% strike puts, 3 months",
                "Less idiosyncratic risk than single name",
                "Add single-name puts on highest-gap names within sector",
            ],
        )

    # ------------------------------------------------------------------
    # RESTRUCTURING
    # ------------------------------------------------------------------
    if catalyst_type == "restructuring":
        if iv < 40:
            return TradeRecommendation(
                structure="OTM_PUT",
                strike_pct=0.50,
                expiry_months=6,
                rationale="Active restructuring + reasonable vol = deep OTM puts for equity wipeout",
                max_premium_pct=1.0,
                target_delta=-0.10,
                catalyst_type=catalyst_type,
                conviction="HIGH" if gap_signal == "STRONG" else "MEDIUM",
                risk_reward="Lottery ticket: risk 1% for 20-50x on equity wipeout scenario",
                entry_notes=[
                    "Deep OTM puts (50% strike) -- cheap lottery",
                    "Restructuring often means equity approaches zero",
                    "Small position -- max 1% of notional",
                    "Credit trading > 800bp implies real default risk",
                ],
            )
        else:
            return TradeRecommendation(
                structure="OTM_PUT",
                strike_pct=0.60,
                expiry_months=9,
                rationale="Restructuring risk with expensive vol = extend duration, go deeper OTM",
                max_premium_pct=1.5,
                target_delta=-0.08,
                catalyst_type=catalyst_type,
                conviction="MEDIUM",
                risk_reward="Extended lottery: risk 1.5% over 9 months for tail payoff",
                entry_notes=[
                    "Go deeper OTM and longer-dated to reduce premium",
                    "Vol expensive but restructuring is binary",
                    "Consider put spread to further reduce cost",
                ],
            )

    # ------------------------------------------------------------------
    # UNKNOWN / DEFAULT
    # ------------------------------------------------------------------
    if gap_signal == "STRONG":
        return TradeRecommendation(
            structure="OTM_PUT",
            strike_pct=0.85,
            expiry_months=3,
            rationale="Strong gap detected but catalyst unclear = standard OTM puts",
            max_premium_pct=2.0,
            target_delta=-0.25,
            catalyst_type=catalyst_type,
            conviction="MEDIUM",
            risk_reward="Standard put: risk 2% for 3-5x on 15%+ equity decline",
            entry_notes=[
                "Generic OTM put as catalyst is unclear",
                "Monitor for catalyst development",
                "Tighten or exit if gap narrows",
            ],
        )

    return TradeRecommendation(
        structure="MONITOR",
        strike_pct=0,
        expiry_months=0,
        rationale="Weak gap or unclear catalyst = continue monitoring",
        max_premium_pct=0,
        target_delta=0,
        catalyst_type=catalyst_type,
        conviction="LOW",
        risk_reward="N/A",
        entry_notes=["Wait for stronger signal before committing capital"],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  TRADE STRUCTURER -- Tests")
    print("=" * 70)

    tests = [
        ("maturity_wall", 20, "STRONG", 600),
        ("maturity_wall", 45, "MODERATE", 400),
        ("maturity_wall", 75, "STRONG", 500),
        ("aggressive_sponsor", 25, "MODERATE", 350),
        ("aggressive_sponsor", 60, "STRONG", 400),
        ("earnings_downgrade", 30, "STRONG", 300),
        ("rating_action", 40, "STRONG", 250),
        ("sector_stress", 50, "MODERATE", 350),
        ("restructuring", 35, "STRONG", 900),
    ]

    for cat, iv, gap, spread in tests:
        rec = recommend_trade(cat, iv, gap, spread)
        print(f"\n  Catalyst: {cat:<22} IV: {iv:>3}%  Gap: {gap:<10} Spread: {spread}bp")
        print(f"  -> {rec.structure:<20} Strike: {rec.strike_pct:.0%}  "
              f"Expiry: {rec.expiry_months}m  Conv: {rec.conviction}")
        print(f"     {rec.rationale}")

    print("\n" + "=" * 70)

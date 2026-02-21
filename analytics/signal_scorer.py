"""
Credit-Equity Signal Scoring Engine

Computes two independent scores (0-100) for each iTraxx Xover name:
  1. Credit Signal Score -- how stressed is the credit?
  2. Equity Repricing Score -- how much has equity already moved?

The GAP between them is the alpha: high credit stress + low equity repricing
means the options market hasn't caught up with credit deterioration.

Usage:
    from analytics.signal_scorer import compute_credit_signal_score, compute_equity_repricing_score, compute_gap_score
"""

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Credit signal component weights (sum = 1.0)
W_SPREAD_LEVEL    = 0.20
W_SPREAD_MOMENTUM = 0.15
W_RV_COMPOSITE    = 0.15
W_FILING_SEVERITY = 0.15
W_MATURITY_WALL   = 0.15
W_CONVICTION_DIR  = 0.10
W_SECTOR_CONTAGION = 0.10

# Equity repricing component weights (sum = 1.0)
W_PRICE_CHG_5D    = 0.30
W_PRICE_CHG_20D   = 0.20
W_IV_PERCENTILE   = 0.30
W_PUT_CALL_RATIO  = 0.20

# Gap thresholds
GAP_STRONG   = 50
GAP_MODERATE = 30
GAP_WEAK     = 10


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CreditSignalResult:
    """Credit signal score breakdown."""
    entity_name: str
    total_score: float
    components: dict = field(default_factory=dict)


@dataclass
class EquityRepricingResult:
    """Equity repricing score breakdown."""
    ticker: str
    total_score: float
    components: dict = field(default_factory=dict)


@dataclass
class GapResult:
    """Gap score between credit and equity."""
    entity_name: str
    ticker: str
    credit_score: float
    equity_score: float
    gap_score: float
    gap_signal: str          # STRONG / MODERATE / WEAK / NONE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp a value between lo and hi."""
    return max(lo, min(hi, value))


def _scale_linear(value: float, lo: float, hi: float) -> float:
    """Scale value linearly from [lo, hi] to [0, 100]."""
    if hi <= lo:
        return 50.0
    return _clamp((value - lo) / (hi - lo) * 100)


# ---------------------------------------------------------------------------
# Credit Signal Score
# ---------------------------------------------------------------------------

def _score_spread_level(spread_bps: float) -> float:
    """Score the absolute CDS spread level.

    Maps implied 5Y PD to 0-100:
      <100bp (PD ~8%)  = low stress (0-20)
      100-300bp (PD ~22%) = moderate (20-50)
      300-600bp (PD ~39%) = elevated (50-75)
      600-1000bp (PD ~57%) = high (75-90)
      >1000bp (PD >60%)   = distressed (90-100)
    """
    # Use spread directly for a simple scaling
    if spread_bps <= 0:
        return 0.0
    # Sigmoid-like mapping: 0-1500bp → 0-100
    return _clamp(100 * (1 - math.exp(-spread_bps / 500)))


def _score_spread_momentum(
    current_spread: float,
    spread_5d_ago: float | None = None,
    spread_20d_ago: float | None = None,
) -> float:
    """Score spread momentum (widening = higher score).

    5d widening > 20% = score 90+
    5d widening > 10% = score 60-80
    Flat = 30-40
    Tightening = 0-20
    """
    if current_spread <= 0:
        return 0.0

    score = 30.0  # Neutral baseline

    if spread_5d_ago and spread_5d_ago > 0:
        chg_5d_pct = (current_spread - spread_5d_ago) / spread_5d_ago * 100
        if chg_5d_pct > 20:
            score += 40
        elif chg_5d_pct > 10:
            score += 30
        elif chg_5d_pct > 5:
            score += 20
        elif chg_5d_pct > 0:
            score += 10
        elif chg_5d_pct < -5:
            score -= 20
        elif chg_5d_pct < 0:
            score -= 10

    if spread_20d_ago and spread_20d_ago > 0:
        chg_20d_pct = (current_spread - spread_20d_ago) / spread_20d_ago * 100
        if chg_20d_pct > 15:
            score += 20
        elif chg_20d_pct > 5:
            score += 10
        elif chg_20d_pct < -10:
            score -= 15

    return _clamp(score)


def _score_rv_composite(rv_composite: float | None) -> float:
    """Score from relative value composite.

    Positive composite = CHEAP (wider than peers) = credit stress signal.
    rv_composite > 2.0 = very stressed = score 90
    rv_composite > 1.0 = stressed = score 70
    rv_composite 0-1   = mild = score 40-60
    rv_composite < 0   = rich = score 0-30
    """
    if rv_composite is None:
        return 30.0  # Neutral when unavailable

    if rv_composite > 2.0:
        return 95.0
    elif rv_composite > 1.5:
        return 85.0
    elif rv_composite > 1.0:
        return 70.0
    elif rv_composite > 0.5:
        return 55.0
    elif rv_composite > 0.0:
        return 40.0
    elif rv_composite > -0.5:
        return 25.0
    elif rv_composite > -1.0:
        return 15.0
    else:
        return 5.0


def _score_filing_severity(
    filings: list[dict] | None = None,
) -> float:
    """Score based on recent filing severity.

    Looks at filings in last 7 days. NEGATIVE/RESTRUCTURING = high score.
    """
    if not filings:
        return 10.0  # Low baseline when no filings

    score = 10.0
    for f in filings:
        impact = str(f.get("credit_impact", "")).upper()
        severity = str(f.get("severity", "")).upper()

        if "RESTRUCTURING" in impact or "DEFAULT" in impact:
            score += 40
        elif "NEGATIVE" in impact or "DOWNGRADE" in impact:
            score += 25
        elif "WATCH" in impact or "REVIEW" in impact:
            score += 15
        elif "POSITIVE" in impact:
            score -= 10

        if severity == "HIGH":
            score += 10
        elif severity == "CRITICAL":
            score += 20

    return _clamp(score)


def _score_maturity_wall(maturity_risk: str | None) -> float:
    """Score based on maturity wall risk level."""
    if not maturity_risk:
        return 15.0

    risk_map = {
        "very_high": 95.0,
        "high": 75.0,
        "medium": 45.0,
        "low": 15.0,
        "none": 5.0,
    }
    return risk_map.get(maturity_risk.lower(), 20.0)


def _score_conviction_direction(direction: str | None, conviction: int = 3) -> float:
    """Score based on analyst conviction direction.

    SHORT_RISK with high conviction = high credit concern.
    """
    if not direction:
        return 30.0

    base = 30.0
    if direction.upper() == "SHORT_RISK":
        base = 60.0
        # Higher conviction amplifies
        base += (conviction - 3) * 8  # conviction 1-5 → +/- 16
    elif direction.upper() == "LONG_RISK":
        base = 15.0
        base -= (conviction - 3) * 5

    return _clamp(base)


def _score_sector_contagion(
    sector_avg_spread: float | None,
    sector_spread_chg_pct: float | None = None,
) -> float:
    """Score sector-level stress.

    If the entire sector is widening, individual names face contagion risk.
    """
    score = 25.0

    if sector_avg_spread is not None:
        if sector_avg_spread > 500:
            score += 25
        elif sector_avg_spread > 300:
            score += 15
        elif sector_avg_spread > 200:
            score += 5

    if sector_spread_chg_pct is not None:
        if sector_spread_chg_pct > 10:
            score += 30
        elif sector_spread_chg_pct > 5:
            score += 20
        elif sector_spread_chg_pct > 0:
            score += 5
        elif sector_spread_chg_pct < -5:
            score -= 15

    return _clamp(score)


def compute_credit_signal_score(
    entity_name: str,
    spread_bps: float,
    fair_spread: float | None = None,
    direction: str | None = None,
    conviction: int = 3,
    filings: list[dict] | None = None,
    maturity_risk: str | None = None,
    rv_composite: float | None = None,
    sector_avg_spread: float | None = None,
    sector_spread_chg_pct: float | None = None,
    spread_5d_ago: float | None = None,
    spread_20d_ago: float | None = None,
) -> CreditSignalResult:
    """Compute the credit signal score (0-100).

    Higher = more credit stress detected.
    """
    c1 = _score_spread_level(spread_bps)
    c2 = _score_spread_momentum(spread_bps, spread_5d_ago, spread_20d_ago)
    c3 = _score_rv_composite(rv_composite)
    c4 = _score_filing_severity(filings)
    c5 = _score_maturity_wall(maturity_risk)
    c6 = _score_conviction_direction(direction, conviction)
    c7 = _score_sector_contagion(sector_avg_spread, sector_spread_chg_pct)

    total = (
        W_SPREAD_LEVEL     * c1
        + W_SPREAD_MOMENTUM * c2
        + W_RV_COMPOSITE    * c3
        + W_FILING_SEVERITY * c4
        + W_MATURITY_WALL   * c5
        + W_CONVICTION_DIR  * c6
        + W_SECTOR_CONTAGION * c7
    )

    return CreditSignalResult(
        entity_name=entity_name,
        total_score=round(total, 1),
        components={
            "spread_level": round(c1, 1),
            "spread_momentum": round(c2, 1),
            "rv_composite": round(c3, 1),
            "filing_severity": round(c4, 1),
            "maturity_wall": round(c5, 1),
            "conviction_direction": round(c6, 1),
            "sector_contagion": round(c7, 1),
        },
    )


# ---------------------------------------------------------------------------
# Equity Repricing Score
# ---------------------------------------------------------------------------

def _score_price_change(pct_change: float | None, scale: float = 10.0) -> float:
    """Score equity price change.

    Negative price change = equity already repriced = HIGH score.
    -10% → score ~80
    -5% → score ~50
    0% → score ~20
    +5% → score ~5 (equity rallying = not repriced)
    """
    if pct_change is None:
        return 20.0  # Neutral

    if pct_change >= 0:
        # Equity up = NOT repriced = low score
        return _clamp(20 - pct_change * 3)
    else:
        # Equity down = repriced
        return _clamp(20 + abs(pct_change) / scale * 80)


def _score_iv_percentile(iv_pctile: float | None) -> float:
    """Score IV percentile.

    High IV percentile = options market already pricing risk = HIGH repricing score.
    IV percentile > 80 → score 90
    IV percentile 50-80 → score 50-80
    IV percentile < 20 → score 10 (vol cheap = NOT repriced)
    """
    if iv_pctile is None:
        return 25.0  # Neutral

    return _clamp(iv_pctile * 1.1)  # Roughly linear mapping


def _score_put_call_ratio(pc_ratio: float | None) -> float:
    """Score put/call ratio.

    High P/C = already bearish positioning = HIGH repricing score.
    P/C > 2.0 → score 90
    P/C 1.0-2.0 → score 50-80
    P/C < 0.5 → score 10 (not bearish = NOT repriced)
    """
    if pc_ratio is None:
        return 25.0  # Neutral

    if pc_ratio > 3.0:
        return 95.0
    elif pc_ratio > 2.0:
        return 85.0
    elif pc_ratio > 1.5:
        return 70.0
    elif pc_ratio > 1.0:
        return 55.0
    elif pc_ratio > 0.7:
        return 35.0
    elif pc_ratio > 0.5:
        return 20.0
    else:
        return 10.0


def compute_equity_repricing_score(
    ticker: str,
    stock_price_5d_chg: float | None = None,
    stock_price_20d_chg: float | None = None,
    iv_percentile: float | None = None,
    put_call_ratio: float | None = None,
) -> EquityRepricingResult:
    """Compute the equity repricing score (0-100).

    Higher = equity/options have ALREADY moved. Low gap opportunity.
    Lower = equity hasn't repriced. High gap opportunity.
    """
    e1 = _score_price_change(stock_price_5d_chg, scale=10.0)
    e2 = _score_price_change(stock_price_20d_chg, scale=15.0)
    e3 = _score_iv_percentile(iv_percentile)
    e4 = _score_put_call_ratio(put_call_ratio)

    total = (
        W_PRICE_CHG_5D   * e1
        + W_PRICE_CHG_20D * e2
        + W_IV_PERCENTILE  * e3
        + W_PUT_CALL_RATIO * e4
    )

    return EquityRepricingResult(
        ticker=ticker,
        total_score=round(total, 1),
        components={
            "price_change_5d": round(e1, 1),
            "price_change_20d": round(e2, 1),
            "iv_percentile": round(e3, 1),
            "put_call_ratio": round(e4, 1),
        },
    )


# ---------------------------------------------------------------------------
# Gap Score
# ---------------------------------------------------------------------------

def compute_gap_score(
    entity_name: str,
    ticker: str,
    credit_result: CreditSignalResult,
    equity_result: EquityRepricingResult,
) -> GapResult:
    """Compute gap score = credit_signal - equity_repricing.

    Positive gap = credit deteriorating but equity hasn't caught up = OPPORTUNITY.
    """
    gap = credit_result.total_score - equity_result.total_score

    if gap >= GAP_STRONG:
        signal = "STRONG"
    elif gap >= GAP_MODERATE:
        signal = "MODERATE"
    elif gap >= GAP_WEAK:
        signal = "WEAK"
    else:
        signal = "NONE"

    return GapResult(
        entity_name=entity_name,
        ticker=ticker,
        credit_score=credit_result.total_score,
        equity_score=equity_result.total_score,
        gap_score=round(gap, 1),
        gap_signal=signal,
    )


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick test with synthetic data
    print("=" * 70)
    print("  SIGNAL SCORER -- Test")
    print("=" * 70)

    # Test: Stressed credit, low equity repricing
    credit = compute_credit_signal_score(
        entity_name="Worldline SA",
        spread_bps=450,
        direction="SHORT_RISK",
        conviction=4,
        rv_composite=1.5,
        maturity_risk="high",
    )
    print(f"\n  Credit Signal: {credit.total_score}/100")
    for k, v in credit.components.items():
        print(f"    {k:25s} = {v:5.1f}")

    equity = compute_equity_repricing_score(
        ticker="WLN.PA",
        stock_price_5d_chg=-2.0,
        stock_price_20d_chg=-5.0,
        iv_percentile=35,
        put_call_ratio=0.8,
    )
    print(f"\n  Equity Repricing: {equity.total_score}/100")
    for k, v in equity.components.items():
        print(f"    {k:25s} = {v:5.1f}")

    gap = compute_gap_score("Worldline SA", "WLN.PA", credit, equity)
    print(f"\n  Gap Score: {gap.gap_score:+.1f} ({gap.gap_signal})")
    print(f"  Credit={gap.credit_score:.1f} - Equity={gap.equity_score:.1f}")
    print("=" * 70)

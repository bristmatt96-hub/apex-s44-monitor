"""
Credit Cycle Regime Classifier — Credit Catalyst

Determines the current credit regime from market data using a multi-factor
scoring model across four phases:

    EXPANSION   — Spreads tightening, low defaults, compression
    LATE_CYCLE  — Spreads stable but dispersion rising, fallen angel activity
    DISTRESS    — Spreads widening, high dispersion, defaults rising
    RECOVERY    — Spreads tightening from wide levels, high carry

Inputs:
    1. Current Xover index spread level
    2. Dispersion stats (from analytics.dispersion)
    3. Fallen angel / rising star counts (from analytics.fallen_angels)
    4. Spread distribution shape (skewness, kurtosis)
    5. Rating migration signals

Output:
    Regime classification with confidence + recommended positioning

Usage:
    python -m analytics.credit_cycle                    # Full analysis
    python -m analytics.credit_cycle --json             # JSON output
    python -m analytics.credit_cycle --detail           # Verbose factor breakdown
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev

from openpyxl import load_workbook

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Historical Xover spread benchmarks (bps)
XOVER_HISTORICAL_MEDIAN = 340      # Long-run median
XOVER_EXPANSION_TIGHT = 250        # Below = expansion territory
XOVER_LATE_CYCLE_WIDE = 400        # Above = late cycle / stress
XOVER_DISTRESS_WIDE = 500          # Above = distress
XOVER_RECOVERY_THRESHOLD = 450     # Tightening from above this = recovery

# Dispersion thresholds
HIGH_DISPERSION_CV = 1.0           # CV > 1.0 = high dispersion
LOW_DISPERSION_CV = 0.5            # CV < 0.5 = low dispersion

# Migration thresholds
RISING_STAR_THRESHOLD = 150
FALLEN_ANGEL_THRESHOLD = 250
DISTRESSED_THRESHOLD = 800

# Distribution shape thresholds
HIGH_SKEW = 1.5                    # Right-skewed = distressed tail
LOW_SKEW = 0.5                     # Symmetric = healthy

# Rating bucket boundaries
RATING_BUCKETS = [
    ("BB+",  0,    150),
    ("BB",   150,  300),
    ("B",    300,  500),
    ("B-",   500,  800),
    ("CCC",  800,  9999),
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CycleFactors:
    """Raw factor inputs for the regime classifier."""
    # Spread level
    index_spread: float = 0.0
    index_spread_percentile: float = 0.0      # vs historical

    # Dispersion
    universe_cv: float = 0.0
    universe_dispersion_regime: str = ""       # HIGH, MODERATE, LOW

    # Distribution shape
    skewness: float = 0.0
    kurtosis: float = 0.0
    pct_above_500: float = 0.0                # % of names > 500bp
    pct_below_150: float = 0.0                # % of names < 150bp

    # Migration signals
    rising_star_count: int = 0
    fallen_angel_count: int = 0
    distressed_count: int = 0

    # Carry & compression
    avg_carry_bps: float = 0.0                # Avg spread (proxy for carry)
    spread_compression: float = 0.0           # IQR / median (lower = tighter)

    # Name count
    total_names: int = 0


@dataclass
class CycleScore:
    """Scores for each regime phase (0-100)."""
    expansion: float = 0.0
    late_cycle: float = 0.0
    distress: float = 0.0
    recovery: float = 0.0


@dataclass
class PositioningAdvice:
    """Recommended positioning based on regime."""
    direction_bias: str = ""          # NET_LONG, NET_SHORT, NEUTRAL
    bias_strength: str = ""           # STRONG, MODERATE, LIGHT
    tranche_preference: str = ""      # SENIOR, MEZZANINE, EQUITY, INDEX
    single_name_alpha: str = ""       # HIGH, MODERATE, LOW
    carry_strategy: str = ""          # OVERWEIGHT, NEUTRAL, UNDERWEIGHT
    hedge_recommendation: str = ""
    key_trades: list = field(default_factory=list)


@dataclass
class CycleReport:
    """Full credit cycle regime report."""
    report_date: str = ""
    regime: str = ""                  # EXPANSION, LATE_CYCLE, DISTRESS, RECOVERY
    confidence: float = 0.0           # 0-100%
    secondary_regime: str = ""
    factors: CycleFactors = field(default_factory=CycleFactors)
    scores: CycleScore = field(default_factory=CycleScore)
    positioning: PositioningAdvice = field(default_factory=PositioningAdvice)
    commentary: str = ""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_sector_mapping() -> dict[str, str]:
    """Load entity -> sector from xover_s44.json."""
    path = "indices/xover_s44.json"
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    mapping = {}
    for sector, names in data.get("sectors", {}).items():
        for name in names:
            mapping[name] = sector
    return mapping


def classify_rating(spread: float) -> str:
    """Classify into rating bucket by spread."""
    for rating, low, high in RATING_BUCKETS:
        if low <= spread < high:
            return rating
    return "CCC"


def find_latest_screen() -> str | None:
    """Find most recent xover_screen Excel."""
    output_dir = Path("outputs")
    if not output_dir.exists():
        return None
    candidates = sorted(
        output_dir.glob("xover_screen_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def load_spreads(screen_path: str = None) -> list[dict]:
    """Load spread data from xover_screen Excel.

    Returns list of dicts with entity_name, sector, current_spread,
    fair_spread, direction, conviction, implied_rating.
    """
    if not screen_path:
        screen_path = find_latest_screen()
    if not screen_path or not os.path.exists(screen_path):
        return []

    sector_map = load_sector_mapping()
    wb = load_workbook(screen_path, read_only=True, data_only=True)
    ws = wb["Screen Results"]

    names = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        entity = str(row[0])
        spread = float(row[4]) if row[4] else 0.0
        fair = float(row[5]) if row[5] else 0.0
        direction = str(row[1]) if row[1] else "FLAT"
        conviction = int(row[2]) if row[2] else 3

        if spread <= 0:
            continue

        names.append({
            "entity_name": entity,
            "sector": sector_map.get(entity, "Unknown"),
            "current_spread": spread,
            "fair_spread": fair,
            "direction": direction,
            "conviction": conviction,
            "implied_rating": classify_rating(spread),
        })

    wb.close()
    return names


# ---------------------------------------------------------------------------
# Factor computation
# ---------------------------------------------------------------------------

def compute_factors(names: list[dict]) -> CycleFactors:
    """Compute all cycle factors from spread data."""
    if not names:
        return CycleFactors()

    spreads = [n["current_spread"] for n in names]
    n = len(spreads)

    # Index spread (weighted average as proxy since we have single-name data)
    avg_spread = mean(spreads)
    med_spread = median(spreads)

    # Percentile vs historical
    percentile = max(0, min(100, (avg_spread / XOVER_HISTORICAL_MEDIAN) * 50))

    # Dispersion (CV)
    sd = stdev(spreads) if n > 1 else 0.0
    cv = sd / avg_spread if avg_spread > 0 else 0.0
    if cv > HIGH_DISPERSION_CV:
        disp_regime = "HIGH"
    elif cv < LOW_DISPERSION_CV:
        disp_regime = "LOW"
    else:
        disp_regime = "MODERATE"

    # Skewness and kurtosis
    if n > 2 and sd > 0:
        mu = mean(spreads)
        skew = sum((x - mu)**3 for x in spreads) / (n * sd**3)
        kurt = sum((x - mu)**4 for x in spreads) / (n * sd**4) - 3.0
    else:
        skew = 0.0
        kurt = 0.0

    # Distribution tails
    pct_above_500 = sum(1 for s in spreads if s > 500) / n * 100
    pct_below_150 = sum(1 for s in spreads if s < 150) / n * 100

    # Migration counts
    rising = sum(1 for s in spreads if s < RISING_STAR_THRESHOLD)
    fallen = sum(1 for n_d in names
                 if n_d["current_spread"] > FALLEN_ANGEL_THRESHOLD
                 and n_d["direction"] == "SHORT_RISK")
    distressed = sum(1 for s in spreads if s > DISTRESSED_THRESHOLD)

    # Spread compression (IQR / median)
    sorted_spreads = sorted(spreads)
    q1 = sorted_spreads[n // 4]
    q3 = sorted_spreads[3 * n // 4]
    iqr = q3 - q1
    compression = iqr / med_spread if med_spread > 0 else 0.0

    return CycleFactors(
        index_spread=round(avg_spread, 1),
        index_spread_percentile=round(percentile, 1),
        universe_cv=round(cv, 3),
        universe_dispersion_regime=disp_regime,
        skewness=round(skew, 2),
        kurtosis=round(kurt, 2),
        pct_above_500=round(pct_above_500, 1),
        pct_below_150=round(pct_below_150, 1),
        rising_star_count=rising,
        fallen_angel_count=fallen,
        distressed_count=distressed,
        avg_carry_bps=round(avg_spread, 1),
        spread_compression=round(compression, 3),
        total_names=n,
    )


# ---------------------------------------------------------------------------
# Regime scoring
# ---------------------------------------------------------------------------

def score_regimes(factors: CycleFactors) -> CycleScore:
    """Score each regime phase 0-100 based on factor values.

    Each factor contributes a weighted score. The highest-scoring regime
    is the classified phase.
    """
    scores = CycleScore()

    # ── EXPANSION scoring ────────────────────────────────────────────
    # Tight spreads + low dispersion + few distressed + low skew
    s = 0.0
    if factors.index_spread < XOVER_EXPANSION_TIGHT:
        s += 30
    elif factors.index_spread < XOVER_HISTORICAL_MEDIAN:
        s += 20 * (1 - (factors.index_spread - XOVER_EXPANSION_TIGHT) /
                   (XOVER_HISTORICAL_MEDIAN - XOVER_EXPANSION_TIGHT))

    if factors.universe_cv < LOW_DISPERSION_CV:
        s += 25
    elif factors.universe_cv < 0.7:
        s += 15

    if factors.pct_above_500 < 5:
        s += 20
    elif factors.pct_above_500 < 10:
        s += 10

    if factors.skewness < LOW_SKEW:
        s += 15
    elif factors.skewness < 1.0:
        s += 8

    if factors.rising_star_count > 10:
        s += 10
    elif factors.rising_star_count > 5:
        s += 5

    scores.expansion = min(100, s)

    # ── LATE CYCLE scoring ───────────────────────────────────────────
    # Moderate spreads + RISING dispersion + fallen angel activity + positive skew
    s = 0.0
    if XOVER_EXPANSION_TIGHT <= factors.index_spread <= XOVER_LATE_CYCLE_WIDE:
        s += 25
    elif factors.index_spread < XOVER_DISTRESS_WIDE:
        s += 15

    if factors.universe_cv > 0.7:
        s += 25
    elif factors.universe_cv > 0.5:
        s += 15

    if factors.fallen_angel_count >= 3:
        s += 20
    elif factors.fallen_angel_count >= 1:
        s += 10

    if factors.skewness > 1.0:
        s += 15
    elif factors.skewness > 0.5:
        s += 8

    if factors.pct_above_500 > 5 and factors.pct_above_500 < 20:
        s += 15
    elif factors.pct_above_500 > 2:
        s += 8

    scores.late_cycle = min(100, s)

    # ── DISTRESS scoring ─────────────────────────────────────────────
    # Wide spreads + high dispersion + many distressed + high skew
    s = 0.0
    if factors.index_spread > XOVER_DISTRESS_WIDE:
        s += 30
    elif factors.index_spread > XOVER_LATE_CYCLE_WIDE:
        s += 15

    if factors.universe_cv > HIGH_DISPERSION_CV:
        s += 25
    elif factors.universe_cv > 0.8:
        s += 12

    if factors.distressed_count >= 5:
        s += 20
    elif factors.distressed_count >= 2:
        s += 10

    if factors.skewness > HIGH_SKEW:
        s += 15
    elif factors.skewness > 1.0:
        s += 8

    if factors.pct_above_500 > 15:
        s += 10
    elif factors.pct_above_500 > 8:
        s += 5

    scores.distress = min(100, s)

    # ── RECOVERY scoring ─────────────────────────────────────────────
    # Tightening from wide + high carry + moderate dispersion
    s = 0.0
    # Wide spreads with tightening signal (fair < current = analyst expects tightening)
    if factors.index_spread > XOVER_HISTORICAL_MEDIAN:
        s += 20
    if factors.index_spread > XOVER_RECOVERY_THRESHOLD:
        s += 10

    if factors.avg_carry_bps > 350:
        s += 20
    elif factors.avg_carry_bps > 300:
        s += 12

    if 0.5 <= factors.universe_cv <= 1.0:
        s += 15
    elif factors.universe_cv > 0.3:
        s += 8

    if factors.rising_star_count >= 3 and factors.distressed_count >= 2:
        s += 20  # Bifurcation = recovery-phase dynamic

    if factors.spread_compression > 0.8:
        s += 15
    elif factors.spread_compression > 0.5:
        s += 8

    scores.recovery = min(100, s)

    return scores


def classify_regime(scores: CycleScore) -> tuple[str, float, str]:
    """Classify regime from scores.

    Returns (primary_regime, confidence, secondary_regime).
    """
    regime_scores = {
        "EXPANSION": scores.expansion,
        "LATE_CYCLE": scores.late_cycle,
        "DISTRESS": scores.distress,
        "RECOVERY": scores.recovery,
    }

    sorted_regimes = sorted(regime_scores.items(), key=lambda x: -x[1])
    primary = sorted_regimes[0]
    secondary = sorted_regimes[1]

    total = sum(regime_scores.values())
    confidence = primary[1] / total * 100 if total > 0 else 25.0

    return primary[0], round(confidence, 1), secondary[0]


# ---------------------------------------------------------------------------
# Positioning advice
# ---------------------------------------------------------------------------

def generate_positioning(regime: str, factors: CycleFactors) -> PositioningAdvice:
    """Generate positioning recommendations based on regime."""

    advice = PositioningAdvice()

    if regime == "EXPANSION":
        advice.direction_bias = "NET_LONG"
        advice.bias_strength = "MODERATE"
        advice.tranche_preference = "INDEX"
        advice.single_name_alpha = "LOW"
        advice.carry_strategy = "OVERWEIGHT"
        advice.hedge_recommendation = (
            "Light tail hedges via 0-3% tranche protection. "
            "Low dispersion means index/tranche trades outperform single-name alpha."
        )
        advice.key_trades = [
            "Long iTraxx Xover index for carry",
            "Sell mezzanine tranche protection (3-7%) for premium",
            "Reduce single-name shorts — limited alpha in compressed spreads",
            "Fallen angel longs: capture rising star momentum pre-roll",
        ]

    elif regime == "LATE_CYCLE":
        advice.direction_bias = "NEUTRAL"
        advice.bias_strength = "LIGHT"
        advice.tranche_preference = "MEZZANINE"
        advice.single_name_alpha = "HIGH"
        advice.carry_strategy = "NEUTRAL"
        advice.hedge_recommendation = (
            "Buy 0-3% equity tranche protection as tail hedge. "
            "Rising dispersion favours single-name alpha over index."
        )
        advice.key_trades = [
            "Single-name shorts on fallen angel candidates (widening BB names)",
            "Pair trades exploiting sector dispersion",
            "Long rising stars vs short fallen angels",
            "Sell 5Y/3Y CDS steepeners on credits with near-term catalysts",
        ]

    elif regime == "DISTRESS":
        advice.direction_bias = "NET_SHORT"
        advice.bias_strength = "STRONG"
        advice.tranche_preference = "EQUITY"
        advice.single_name_alpha = "HIGH"
        advice.carry_strategy = "UNDERWEIGHT"
        advice.hedge_recommendation = (
            "Maximum protection via equity tranche (0-3%). "
            "Single-name shorts on distressed names approaching restructuring."
        )
        advice.key_trades = [
            "Buy equity tranche protection for convex downside hedge",
            "Short distressed names approaching credit events",
            "Selective longs only in secured/senior claims with recovery value",
            "Short iTraxx Xover index as beta hedge",
        ]

    elif regime == "RECOVERY":
        advice.direction_bias = "NET_LONG"
        advice.bias_strength = "STRONG"
        advice.tranche_preference = "SENIOR"
        advice.single_name_alpha = "MODERATE"
        advice.carry_strategy = "OVERWEIGHT"
        advice.hedge_recommendation = (
            "Minimal hedging — carry offsets moderate volatility. "
            "Focus on single-name longs in recovery candidates."
        )
        advice.key_trades = [
            "Long distressed names with recovery catalysts",
            "Long iTraxx Xover index for carry + tightening",
            "Sell equity tranche protection (0-3%) for premium capture",
            "Pair trade: long recovery credits vs short late-cycle deteriorators",
        ]

    return advice


# ---------------------------------------------------------------------------
# Commentary generation
# ---------------------------------------------------------------------------

def generate_commentary(regime: str, confidence: float,
                         factors: CycleFactors, scores: CycleScore) -> str:
    """Generate human-readable regime commentary."""

    regime_labels = {
        "EXPANSION": "Expansion",
        "LATE_CYCLE": "Late Cycle",
        "DISTRESS": "Distress",
        "RECOVERY": "Recovery",
    }

    label = regime_labels.get(regime, regime)
    cv_label = factors.universe_dispersion_regime

    parts = [
        f"The European HY credit cycle is in {label} phase "
        f"(confidence: {confidence:.0f}%).",

        f"The iTraxx Xover universe average spread is {factors.index_spread:.0f}bp "
        f"(historical median: {XOVER_HISTORICAL_MEDIAN}bp), "
        f"with {cv_label} dispersion (CV={factors.universe_cv:.2f}).",
    ]

    if factors.distressed_count > 0:
        parts.append(
            f"{factors.distressed_count} name(s) trading above 800bp "
            f"({factors.pct_above_500:.0f}% above 500bp) indicate "
            f"idiosyncratic stress pockets."
        )

    if factors.rising_star_count > 5:
        parts.append(
            f"{factors.rising_star_count} names below 150bp suggest "
            f"potential rising star candidates at the next roll."
        )

    if factors.skewness > 1.0:
        parts.append(
            f"Positive skewness ({factors.skewness:.1f}) indicates "
            f"a right tail of distressed names pulling the distribution wider."
        )

    score_breakdown = (
        f"Regime scores: Expansion={scores.expansion:.0f}, "
        f"Late Cycle={scores.late_cycle:.0f}, "
        f"Distress={scores.distress:.0f}, "
        f"Recovery={scores.recovery:.0f}."
    )
    parts.append(score_breakdown)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------

def run_credit_cycle_analysis(screen_path: str = None) -> CycleReport:
    """Run full credit cycle regime classification."""

    names = load_spreads(screen_path)
    if not names:
        return CycleReport(
            report_date=datetime.now().strftime("%Y-%m-%d"),
            regime="UNKNOWN",
            confidence=0.0,
            commentary="No spread data available.",
        )

    factors = compute_factors(names)
    scores = score_regimes(factors)
    regime, confidence, secondary = classify_regime(scores)
    positioning = generate_positioning(regime, factors)
    commentary = generate_commentary(regime, confidence, factors, scores)

    return CycleReport(
        report_date=datetime.now().strftime("%Y-%m-%d"),
        regime=regime,
        confidence=confidence,
        secondary_regime=secondary,
        factors=factors,
        scores=scores,
        positioning=positioning,
        commentary=commentary,
    )


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def print_report(report: CycleReport, detail: bool = False) -> None:
    """Pretty-print the credit cycle report."""
    W = 72

    regime_emoji = {
        "EXPANSION": "+",
        "LATE_CYCLE": "~",
        "DISTRESS": "!",
        "RECOVERY": "^",
    }

    print()
    print("=" * W)
    print("  CREDIT CATALYST — Credit Cycle Regime Classifier")
    print(f"  {report.report_date}")
    print("=" * W)

    # Regime classification
    icon = regime_emoji.get(report.regime, "?")
    print()
    print(f"  [{icon}] REGIME: {report.regime}  "
          f"(confidence: {report.confidence:.0f}%)")
    if report.secondary_regime:
        print(f"      Secondary: {report.secondary_regime}")

    # Score breakdown
    print()
    print("  REGIME SCORES")
    print("  " + "-" * 45)
    s = report.scores
    max_bar = 30
    for label, score in [
        ("Expansion ", s.expansion),
        ("Late Cycle", s.late_cycle),
        ("Distress  ", s.distress),
        ("Recovery  ", s.recovery),
    ]:
        bar_len = int(score / 100 * max_bar)
        bar = "#" * bar_len + "." * (max_bar - bar_len)
        marker = " <--" if label.strip().upper().replace(" ", "_") == report.regime else ""
        print(f"  {label} [{bar}] {score:5.1f}{marker}")

    # Key factors
    f = report.factors
    print()
    print("  KEY FACTORS")
    print("  " + "-" * 45)
    print(f"  Avg Spread:       {f.index_spread:>7.0f} bp "
          f"(median={XOVER_HISTORICAL_MEDIAN}bp)")
    print(f"  Dispersion (CV):  {f.universe_cv:>7.3f}   ({f.universe_dispersion_regime})")
    print(f"  Skewness:         {f.skewness:>7.2f}")
    print(f"  Kurtosis:         {f.kurtosis:>7.2f}")
    print(f"  Names > 500bp:    {f.pct_above_500:>6.1f}%   ({f.distressed_count} distressed)")
    print(f"  Names < 150bp:    {f.pct_below_150:>6.1f}%   ({f.rising_star_count} rising stars)")
    print(f"  Fallen Angels:    {f.fallen_angel_count:>7d}")
    print(f"  Compression:      {f.spread_compression:>7.3f}")
    print(f"  Total Names:      {f.total_names:>7d}")

    # Positioning
    p = report.positioning
    print()
    print("  RECOMMENDED POSITIONING")
    print("  " + "-" * 45)
    print(f"  Direction Bias:   {p.direction_bias} ({p.bias_strength})")
    print(f"  Tranche Pref:     {p.tranche_preference}")
    print(f"  Single-Name Alpha:{p.single_name_alpha:>5}")
    print(f"  Carry Strategy:   {p.carry_strategy}")
    print()
    print(f"  Hedge: {p.hedge_recommendation}")

    print()
    print("  KEY TRADES:")
    for t in p.key_trades:
        print(f"    - {t}")

    # Commentary
    print()
    print("  COMMENTARY")
    print("  " + "-" * 45)
    for line in _wrap(report.commentary, 65):
        print(f"  {line}")

    if detail:
        print()
        print("  FACTOR DETAIL (JSON)")
        print("  " + "-" * 45)
        print(json.dumps(asdict(report.factors), indent=2))

    print()
    print("=" * W)


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap."""
    words = text.split()
    lines, current = [], ""
    for w in words:
        if current and len(current) + 1 + len(w) > width:
            lines.append(current)
            current = w
        else:
            current = current + " " + w if current else w
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Credit Catalyst — Credit Cycle Regime Classifier"
    )
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--detail", action="store_true",
                        help="Show detailed factor breakdown")
    parser.add_argument("--screen", type=str, default=None,
                        help="Path to xover_screen Excel file")
    args = parser.parse_args()

    report = run_credit_cycle_analysis(args.screen)

    if args.json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print_report(report, detail=args.detail)


if __name__ == "__main__":
    main()

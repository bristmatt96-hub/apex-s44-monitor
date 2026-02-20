"""
Credit Cycle Regime Classifier — Strategies in Credit

Determines the current credit regime from market data using a multi-factor
scoring model across four phases:

    EXPANSION   — Spreads tightening, low defaults, compression
    LATE_CYCLE  — Spreads stable but dispersion rising, fallen angel activity
    DISTRESS    — Spreads widening, high dispersion, defaults rising
    RECOVERY    — Spreads tightening from wide levels, high carry

Four-Layer Macro Stack:
    Layer 1 (Howell):  Global liquidity — LQD/HYG quality rotation signal
    Layer 2 (Pal):     ISM sequencing — PMI level relative to 50
    Layer 3 (Steno):   Commodity thematic — copper futures trend
    Layer 4 (Visser):  AI disruption — per-entity risk classification

Inputs:
    1. Current Xover index spread level
    2. Dispersion stats (from analytics.dispersion)
    3. Fallen angel / rising star counts (from analytics.fallen_angels)
    4. Spread distribution shape (skewness, kurtosis)
    5. Rating migration signals
    6. LQD/HYG ETF price ratio trend (Layer 1)
    7. ISM PMI level (Layer 2)
    8. Copper futures trend (Layer 3)
    9. AI disruption risk per entity (Layer 4)

Output:
    Regime classification with confidence + recommended positioning
    + liquidity_signal, quality_rotation, recommended_net_exposure,
      sector_tilts, ai_disruption_flags

Usage:
    python -m analytics.credit_cycle                    # Full analysis
    python -m analytics.credit_cycle --json             # JSON output
    python -m analytics.credit_cycle --detail           # Verbose factor breakdown
    python -m analytics.credit_cycle --set-regime LATE_CYCLE --confidence 80 --note "Pal/Bittel Feb 2026: ISM decelerating, liquidity cresting Q2"
    python -m analytics.credit_cycle --clear-override   # Remove manual override
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

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

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
# Layer 1 (Howell): Liquidity — LQD/HYG quality rotation
# ---------------------------------------------------------------------------

LQD_TICKER = "LQD"     # iShares IG Corporate Bond ETF
HYG_TICKER = "HYG"     # iShares HY Corporate Bond ETF
QUALITY_LOOKBACK_DAYS = 60  # 3-month rolling window

# ---------------------------------------------------------------------------
# Layer 2 (Pal): ISM PMI
# ---------------------------------------------------------------------------

# We store ISM data in a simple config file; no API needed
ISM_DATA_PATH = Path("data/ism_pmi.json")
ISM_EXPANSION_THRESHOLD = 50.0

# ---------------------------------------------------------------------------
# Layer 3 (Steno): Copper thematic
# ---------------------------------------------------------------------------

COPPER_TICKER = "HG=F"  # Copper futures via yfinance
COPPER_LOOKBACK_DAYS = 60

# ---------------------------------------------------------------------------
# Layer 4 (Visser): AI disruption risk classification
# ---------------------------------------------------------------------------

# Per-sector AI disruption risk: names in these sectors face automation/
# digital disruption headwinds. Mapped to HIGH/MEDIUM/LOW.
AI_DISRUPTION_MAP = {
    # HIGH: sectors where AI/automation directly disrupts core business
    "Worldline SA/France": "HIGH",            # Payment processing — fintech disruption
    "Nexi SpA": "HIGH",                       # Payment processing
    "TeamSystem SpA": "HIGH",                 # Enterprise software — AI competition
    "Nokia Oyj": "HIGH",                      # Telecom equipment — commoditisation
    "Telefonaktiebolaget LM Ericsson": "HIGH",  # Telecom equipment
    "CECONOMY AG": "HIGH",                    # Consumer electronics retail — e-commerce
    "EG Global Finance PLC": "HIGH",          # Convenience retail — automated retail
    # MEDIUM: moderate AI/digital exposure
    "Eutelsat SA": "MEDIUM",                  # Satellite — Starlink competition
    "SES SA": "MEDIUM",                       # Satellite — LEO competition
    "Telecom Italia SpA/Milano": "MEDIUM",    # Telco — capex pressure from AI infra
    "Fibercop SpA": "MEDIUM",                 # Fiber infra — capex intensive
    "Virgin Media Finance PLC": "MEDIUM",     # Cable — cord-cutting
    "Ziggo Bond Co BV": "MEDIUM",             # Cable — cord-cutting
    "Zegona Finance PLC": "MEDIUM",           # Telecom
    "Kaixo Bondco Telecom SA": "MEDIUM",      # Telecom
    "Maya SAS/Paris France": "MEDIUM",        # Telecom (Iliad)
    "NJJ Continental SA": "MEDIUM",           # Telecom (Salt)
    "Sunrise HoldCo IV BV": "MEDIUM",         # Telecom
    "United Group BV": "MEDIUM",              # Telecom
    "Lagardere SA": "MEDIUM",                 # Media/publishing — AI content
    "Picard Bondco SA": "MEDIUM",             # Frozen food retail
    "Iceland Bondco PLC": "MEDIUM",           # Frozen food retail
    "Pachelbel Bidco SpA": "MEDIUM",          # Education (Pegaso) — AI learning
    "Forvia SE": "MEDIUM",                    # Auto parts — EV transition
    "Valeo SE": "MEDIUM",                     # Auto parts — EV transition
    "Schaeffler AG": "MEDIUM",                # Auto parts — EV transition
    "ZF Europe Finance BV": "MEDIUM",         # Auto parts — EV transition
    "Jaguar Land Rover Automotive PLC": "MEDIUM",  # OEM — EV transition
    "Volvo Car AB": "MEDIUM",                 # OEM — EV transition
    "Renault SA": "MEDIUM",                   # OEM — EV transition
}

# Everything not listed = LOW risk (chemicals, shipping, gaming, travel, etc.)
DEFAULT_AI_DISRUPTION = "LOW"


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

    # Layer 1 (Howell): Liquidity / quality rotation
    lqd_hyg_ratio: float = 0.0               # Current LQD/HYG price ratio
    lqd_hyg_ratio_change: float = 0.0        # Change over lookback (%)
    liquidity_signal: str = ""               # expanding, decelerating, contracting
    quality_rotation: str = ""               # underway, not_yet, reversed

    # Layer 2 (Pal): ISM PMI
    ism_pmi: float = 0.0
    ism_direction: str = ""                  # above_50, at_50, below_50

    # Layer 3 (Steno): Copper
    copper_trend: float = 0.0                # % change over lookback
    copper_signal: str = ""                  # rising, flat, falling

    # Layer 4 (Visser): AI disruption
    high_ai_disruption_count: int = 0
    medium_ai_disruption_count: int = 0


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
    liquidity_signal: str = ""        # expanding, decelerating, contracting
    quality_rotation: str = ""        # underway, not_yet, reversed
    recommended_net_exposure: float = 0.0   # % net long/short
    sector_tilts: dict = field(default_factory=dict)   # sector -> OW/UW/N
    ai_disruption_flags: list = field(default_factory=list)  # highest risk names
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
# Macro layer data loading
# ---------------------------------------------------------------------------

def fetch_lqd_hyg_ratio() -> tuple[float, float, str, str]:
    """Layer 1 (Howell): Fetch LQD/HYG price ratio to detect quality rotation.

    When LQD outperforms HYG (ratio rising), investors are rotating to quality
    = liquidity contracting.  When HYG outperforms (ratio falling), risk
    appetite expanding = liquidity expanding.

    Returns (current_ratio, pct_change, liquidity_signal, quality_rotation).
    """
    if not YFINANCE_AVAILABLE:
        return 0.0, 0.0, "unknown", "unknown"

    try:
        period = f"{QUALITY_LOOKBACK_DAYS}d"
        lqd = yf.Ticker(LQD_TICKER).history(period=period)
        hyg = yf.Ticker(HYG_TICKER).history(period=period)

        if lqd.empty or hyg.empty or len(lqd) < 5 or len(hyg) < 5:
            return 0.0, 0.0, "unknown", "unknown"

        current_ratio = float(lqd["Close"].iloc[-1] / hyg["Close"].iloc[-1])
        start_ratio = float(lqd["Close"].iloc[0] / hyg["Close"].iloc[0])
        pct_change = (current_ratio / start_ratio - 1) * 100

        # Quality rotation: ratio rising = flight to quality
        if pct_change > 1.0:
            liquidity = "contracting"
            quality = "underway"
        elif pct_change < -1.0:
            liquidity = "expanding"
            quality = "reversed"
        else:
            liquidity = "decelerating"
            quality = "not_yet"

        return round(current_ratio, 4), round(pct_change, 2), liquidity, quality

    except Exception as e:
        print(f"  Warning: LQD/HYG fetch failed: {e}", file=sys.stderr)
        return 0.0, 0.0, "unknown", "unknown"


def load_ism_pmi() -> tuple[float, str]:
    """Layer 2 (Pal): Load ISM Manufacturing PMI.

    Reads from data/ism_pmi.json which should be updated manually or via
    a separate data feed.  Format: {"date": "2026-02-01", "pmi": 49.2}

    Returns (pmi_value, direction: above_50/at_50/below_50).
    """
    if not ISM_DATA_PATH.exists():
        return 0.0, "unknown"

    try:
        with open(ISM_DATA_PATH) as f:
            data = json.load(f)
        pmi = float(data.get("pmi", 0))
        if pmi > ISM_EXPANSION_THRESHOLD:
            direction = "above_50"
        elif pmi == ISM_EXPANSION_THRESHOLD:
            direction = "at_50"
        else:
            direction = "below_50"
        return pmi, direction
    except Exception:
        return 0.0, "unknown"


def fetch_copper_trend() -> tuple[float, str]:
    """Layer 3 (Steno): Fetch copper futures trend.

    Copper as a leading indicator for global industrial activity.
    Rising copper = expansion signal; falling = contraction.

    Returns (pct_change, signal: rising/flat/falling).
    """
    if not YFINANCE_AVAILABLE:
        return 0.0, "unknown"

    try:
        period = f"{COPPER_LOOKBACK_DAYS}d"
        cu = yf.Ticker(COPPER_TICKER).history(period=period)

        if cu.empty or len(cu) < 5:
            return 0.0, "unknown"

        current = float(cu["Close"].iloc[-1])
        start = float(cu["Close"].iloc[0])
        pct_change = (current / start - 1) * 100

        if pct_change > 5:
            signal = "rising"
        elif pct_change < -5:
            signal = "falling"
        else:
            signal = "flat"

        return round(pct_change, 2), signal

    except Exception as e:
        print(f"  Warning: Copper fetch failed: {e}", file=sys.stderr)
        return 0.0, "unknown"


def classify_ai_disruption(names: list[dict]) -> tuple[int, int, list[str]]:
    """Layer 4 (Visser): Classify AI disruption risk per entity.

    Returns (high_count, medium_count, list_of_high_risk_names).
    """
    high_names = []
    high_count = 0
    medium_count = 0

    for n in names:
        entity = n["entity_name"]
        risk = AI_DISRUPTION_MAP.get(entity, DEFAULT_AI_DISRUPTION)
        if risk == "HIGH":
            high_count += 1
            high_names.append(entity)
        elif risk == "MEDIUM":
            medium_count += 1

    return high_count, medium_count, high_names


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

    # Layer 1 (Howell): LQD/HYG quality rotation
    lqd_hyg_ratio, lqd_hyg_change, liquidity_sig, quality_rot = (
        fetch_lqd_hyg_ratio()
    )

    # Layer 2 (Pal): ISM PMI
    ism_pmi, ism_dir = load_ism_pmi()

    # Layer 3 (Steno): Copper trend
    copper_change, copper_sig = fetch_copper_trend()

    # Layer 4 (Visser): AI disruption
    ai_high, ai_med, _ = classify_ai_disruption(names)

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
        lqd_hyg_ratio=lqd_hyg_ratio,
        lqd_hyg_ratio_change=lqd_hyg_change,
        liquidity_signal=liquidity_sig,
        quality_rotation=quality_rot,
        ism_pmi=ism_pmi,
        ism_direction=ism_dir,
        copper_trend=copper_change,
        copper_signal=copper_sig,
        high_ai_disruption_count=ai_high,
        medium_ai_disruption_count=ai_med,
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

    # Macro overlays for expansion
    if factors.liquidity_signal == "expanding":
        s += 10
    if factors.ism_direction == "above_50":
        s += 8
    if factors.copper_signal == "rising":
        s += 7

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

    # Macro overlays for late cycle
    if factors.liquidity_signal == "decelerating":
        s += 8
    if factors.quality_rotation == "underway":
        s += 10
    if factors.ism_direction == "below_50":
        s += 7

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

    # Macro overlays for distress
    if factors.liquidity_signal == "contracting":
        s += 10
    if factors.quality_rotation == "underway":
        s += 5
    if factors.copper_signal == "falling":
        s += 8
    if factors.ism_direction == "below_50":
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

    # Macro overlays for recovery
    if factors.liquidity_signal == "expanding":
        s += 8
    if factors.copper_signal == "rising":
        s += 7
    if factors.ism_direction == "above_50":
        s += 5

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
# Manual regime override (human judgment > model)
# ---------------------------------------------------------------------------

REGIME_OVERRIDE_PATH = Path("data/macro_regime_override.json")

VALID_REGIMES = {"EXPANSION", "LATE_CYCLE", "DISTRESS", "RECOVERY"}


def load_regime_override() -> dict | None:
    """Load manual regime override if set.

    Returns dict with regime, confidence, note, set_at or None.
    """
    if not REGIME_OVERRIDE_PATH.exists():
        return None
    try:
        with open(REGIME_OVERRIDE_PATH) as f:
            data = json.load(f)
        if data.get("regime") in VALID_REGIMES:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_regime_override(regime: str, confidence: float, note: str) -> None:
    """Save a manual regime override."""
    REGIME_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "regime": regime,
        "confidence": confidence,
        "note": note,
        "set_at": datetime.now().isoformat(),
        "set_by": "manual",
    }
    with open(REGIME_OVERRIDE_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Regime override saved: {regime} ({confidence}%)")
    print(f"  Note: {note}")


def clear_regime_override() -> None:
    """Remove any active regime override."""
    if REGIME_OVERRIDE_PATH.exists():
        REGIME_OVERRIDE_PATH.unlink()
        print("  Regime override cleared.")
    else:
        print("  No regime override active.")


# ---------------------------------------------------------------------------
# Sector tilts & net exposure
# ---------------------------------------------------------------------------

# Net exposure targets by regime (% of NAV, positive = net long)
REGIME_NET_EXPOSURE = {
    "EXPANSION": 40.0,
    "LATE_CYCLE": 10.0,
    "DISTRESS": -20.0,
    "RECOVERY": 50.0,
}


def compute_sector_tilts(
    regime: str,
    factors: CycleFactors,
    names: list[dict],
) -> dict[str, str]:
    """Compute sector overweight/underweight/neutral recommendations."""
    tilts: dict[str, str] = {}

    # Count names per sector
    sector_counts: dict[str, int] = {}
    sector_avg_spread: dict[str, list[float]] = {}
    for n in names:
        sec = n.get("sector", "Unknown")
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
        sector_avg_spread.setdefault(sec, []).append(n["current_spread"])

    for sec, spreads in sector_avg_spread.items():
        avg = mean(spreads)

        if regime == "EXPANSION":
            # In expansion: OW tight sectors (carry), UW wide sectors
            tilts[sec] = "OVERWEIGHT" if avg < 300 else "NEUTRAL"
        elif regime == "LATE_CYCLE":
            # In late cycle: UW cyclicals (Autos), OW defensives
            if sec in ("Autos & Industrials",):
                tilts[sec] = "UNDERWEIGHT"
            elif sec in ("TMT", "Consumers"):
                tilts[sec] = "NEUTRAL"
            else:
                tilts[sec] = "OVERWEIGHT"
        elif regime == "DISTRESS":
            # In distress: UW everything except secured/senior
            tilts[sec] = "UNDERWEIGHT"
        elif regime == "RECOVERY":
            # In recovery: OW wide sectors (tightening potential)
            tilts[sec] = "OVERWEIGHT" if avg > 400 else "NEUTRAL"

    # AI disruption adjustment: downgrade HIGH-AI sectors
    if factors.high_ai_disruption_count > 3:
        if "TMT" in tilts and tilts["TMT"] != "UNDERWEIGHT":
            tilts["TMT"] = "UNDERWEIGHT"

    return tilts


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
                         factors: CycleFactors, scores: CycleScore,
                         override: dict = None,
                         model_regime: str = None) -> str:
    """Generate human-readable regime commentary including macro layers."""

    regime_labels = {
        "EXPANSION": "Expansion",
        "LATE_CYCLE": "Late Cycle",
        "DISTRESS": "Distress",
        "RECOVERY": "Recovery",
    }

    label = regime_labels.get(regime, regime)
    cv_label = factors.universe_dispersion_regime

    parts = []

    # Override notice
    if override:
        parts.append(
            f"MANUAL OVERRIDE ACTIVE: Regime set to {label} "
            f"({confidence:.0f}%) by analyst on {override.get('set_at', 'unknown')[:10]}."
        )
        if model_regime and model_regime != regime:
            model_label = regime_labels.get(model_regime, model_regime)
            parts.append(
                f"DIVERGENCE WARNING: Automated model classifies {model_label} — "
                f"review whether override remains valid."
            )
    else:
        parts.append(
            f"The European HY credit cycle is in {label} phase "
            f"(confidence: {confidence:.0f}%)."
        )

    parts.append(
        f"The iTraxx Xover universe average spread is {factors.index_spread:.0f}bp "
        f"(historical median: {XOVER_HISTORICAL_MEDIAN}bp), "
        f"with {cv_label} dispersion (CV={factors.universe_cv:.2f})."
    )

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

    # Macro layer summary
    macro_parts = []
    if factors.liquidity_signal and factors.liquidity_signal != "unknown":
        macro_parts.append(f"Liquidity {factors.liquidity_signal}")
    if factors.quality_rotation and factors.quality_rotation != "unknown":
        macro_parts.append(f"quality rotation {factors.quality_rotation}")
    if factors.ism_pmi > 0:
        macro_parts.append(f"ISM PMI {factors.ism_pmi:.1f} ({factors.ism_direction})")
    if factors.copper_signal and factors.copper_signal != "unknown":
        macro_parts.append(f"copper {factors.copper_signal} ({factors.copper_trend:+.1f}%)")
    if macro_parts:
        parts.append(f"Macro stack: {', '.join(macro_parts)}.")

    if factors.high_ai_disruption_count > 0:
        parts.append(
            f"AI disruption: {factors.high_ai_disruption_count} HIGH-risk, "
            f"{factors.medium_ai_disruption_count} MEDIUM-risk names."
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
    """Run full credit cycle regime classification.

    Checks for a manual regime override first (human judgment > model).
    If an override is active, uses the override regime/confidence but still
    computes model scores for comparison and divergence warnings.
    """

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
    model_regime, model_confidence, secondary = classify_regime(scores)

    # Check for manual regime override (human judgment > model)
    override = load_regime_override()
    if override:
        regime = override["regime"]
        confidence = override.get("confidence", 75.0)
        # Keep model secondary for divergence info
        if model_regime != regime:
            secondary = model_regime  # Show what model would have chosen
    else:
        regime = model_regime
        confidence = model_confidence

    positioning = generate_positioning(regime, factors)

    # Sector tilts & AI disruption
    sector_tilts = compute_sector_tilts(regime, factors, names)
    _, _, ai_high_names = classify_ai_disruption(names)
    net_exposure = REGIME_NET_EXPOSURE.get(regime, 0.0)

    commentary = generate_commentary(
        regime, confidence, factors, scores, override=override,
        model_regime=model_regime,
    )

    return CycleReport(
        report_date=datetime.now().strftime("%Y-%m-%d"),
        regime=regime,
        confidence=confidence,
        secondary_regime=secondary,
        liquidity_signal=factors.liquidity_signal,
        quality_rotation=factors.quality_rotation,
        recommended_net_exposure=net_exposure,
        sector_tilts=sector_tilts,
        ai_disruption_flags=ai_high_names,
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
    print("  STRATEGIES IN CREDIT — Credit Cycle Regime Classifier")
    print(f"  {report.report_date}")
    print("=" * W)

    # Override notice
    override = load_regime_override()
    if override:
        print()
        print("  ** MANUAL OVERRIDE ACTIVE **")
        print(f"  Set by: {override.get('set_by', 'analyst')} "
              f"on {override.get('set_at', '')[:10]}")
        if override.get("note"):
            for line in _wrap(override["note"], 62):
                print(f"    {line}")

    # Regime classification
    icon = regime_emoji.get(report.regime, "?")
    print()
    print(f"  [{icon}] REGIME: {report.regime}  "
          f"(confidence: {report.confidence:.0f}%)")
    if report.secondary_regime:
        label = "Model says" if override else "Secondary"
        print(f"      {label}: {report.secondary_regime}")

    # Recommended net exposure
    print(f"  Net Exposure:     {report.recommended_net_exposure:+.0f}%")

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

    # Macro layers
    print()
    print("  MACRO STACK")
    print("  " + "-" * 45)
    liq = f.liquidity_signal if f.liquidity_signal != "unknown" else "n/a"
    qr = f.quality_rotation if f.quality_rotation != "unknown" else "n/a"
    print(f"  L1 Howell  Liquidity:  {liq:<15} "
          f"(LQD/HYG ratio: {f.lqd_hyg_ratio:.4f}, "
          f"chg: {f.lqd_hyg_ratio_change:+.2f}%)")
    print(f"             Quality Rot: {qr}")

    ism_str = f"{f.ism_pmi:.1f} ({f.ism_direction})" if f.ism_pmi > 0 else "n/a"
    print(f"  L2 Pal     ISM PMI:     {ism_str}")

    cu_str = f"{f.copper_signal} ({f.copper_trend:+.1f}%)" if f.copper_signal != "unknown" else "n/a"
    print(f"  L3 Steno   Copper:      {cu_str}")

    print(f"  L4 Visser  AI Disruption: "
          f"{f.high_ai_disruption_count} HIGH, "
          f"{f.medium_ai_disruption_count} MEDIUM")

    # Sector tilts
    if report.sector_tilts:
        print()
        print("  SECTOR TILTS")
        print("  " + "-" * 45)
        for sec in sorted(report.sector_tilts.keys()):
            tilt = report.sector_tilts[sec]
            marker = {"OVERWEIGHT": "OW", "UNDERWEIGHT": "UW", "NEUTRAL": " N"}
            print(f"  [{marker.get(tilt, ' ?')}] {sec}")

    # AI disruption flags
    if report.ai_disruption_flags:
        print()
        print("  AI DISRUPTION — HIGH RISK NAMES")
        print("  " + "-" * 45)
        for name in report.ai_disruption_flags:
            print(f"    ! {name}")

    # Positioning
    p = report.positioning
    print()
    print("  RECOMMENDED POSITIONING")
    print("  " + "-" * 45)
    print(f"  Direction Bias:   {p.direction_bias} ({p.bias_strength})")
    print(f"  Net Exposure:     {report.recommended_net_exposure:+.0f}%")
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
        description="Strategies in Credit — Credit Cycle Regime Classifier"
    )
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--detail", action="store_true",
                        help="Show detailed factor breakdown")
    parser.add_argument("--screen", type=str, default=None,
                        help="Path to xover_screen Excel file")

    # Manual regime override (human judgment > model)
    parser.add_argument(
        "--set-regime", type=str, choices=sorted(VALID_REGIMES),
        metavar="REGIME",
        help="Set manual regime override (EXPANSION, LATE_CYCLE, DISTRESS, RECOVERY)",
    )
    parser.add_argument(
        "--confidence", type=float, default=75.0,
        help="Confidence level for the override (0-100, default: 75)",
    )
    parser.add_argument(
        "--note", type=str, default="",
        help="Analyst note for the override (e.g. 'Pal/Bittel Feb 2026: ISM decelerating')",
    )
    parser.add_argument(
        "--clear-override", action="store_true",
        help="Remove any active regime override",
    )

    args = parser.parse_args()

    # Handle override commands first
    if args.clear_override:
        clear_regime_override()
        return

    if args.set_regime:
        save_regime_override(args.set_regime, args.confidence, args.note)
        return

    report = run_credit_cycle_analysis(args.screen)

    if args.json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print_report(report, detail=args.detail)


if __name__ == "__main__":
    main()

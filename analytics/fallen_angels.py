"""
Fallen Angel / Rising Star Screener -- iTraxx Xover Index Roll Dynamics

Identifies names likely to enter or exit the iTraxx Crossover index on the
next semi-annual roll, based on spread-implied rating migration signals.

Categories:
    Rising Stars     -- HY names tightening toward IG (<150bp), potential
                        upgrade and index EXIT on next roll
    Fallen Angels    -- names at the wide end of BB (>250bp) drifting toward B,
                        deepening HY entrenchment
    Distressed Exit  -- names widening past 800bp, potential removal from index
                        due to distress/restructuring
    Stable Core      -- names trading in-line with index, no migration signal

iTraxx Roll Mechanics:
    - Xover rolls every 6 months (March & September, IMM dates)
    - Names upgraded to IG (BBB- or above) EXIT Xover, ENTER iTraxx Main
    - Names downgraded to CCC/default may be removed from index
    - Index rebalancing creates predictable technical flows:
        * Rising stars: short squeeze as protection sellers cover
        * Fallen angels entering: initial widening as market absorbs new risk
        * Distressed exits: basis trades unwind, CDS-bond basis widens

Cross-references analyst assessments for convergence between spread-implied
migration and fundamental credit views.

Usage:
    python -m analytics.fallen_angels              # Full screen
    python -m analytics.fallen_angels --detail      # With analyst thesis
    python -m analytics.fallen_angels --entity SBB  # Search specific name
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median

from openpyxl import load_workbook

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Spread thresholds for migration signals (bps)
RISING_STAR_THRESHOLD = 150     # Trading like IG -- potential upgrade
RISING_STAR_STRONG = 100        # Very strong IG signal
FALLEN_ANGEL_DRIFT = 250        # BB names drifting wider
DISTRESSED_THRESHOLD = 800      # Potential distress exit
SEVERE_DISTRESS = 1000          # Highly likely removal

# Next roll date (March 2026, IMM = 3rd Wednesday = 18 March)
NEXT_ROLL = "20 March 2026"
NEXT_ROLL_SERIES = "S45"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MigrationSignal:
    """Migration signal for a single name."""
    entity_name: str
    sector: str
    current_spread: float
    fair_spread: float
    direction: str          # Analyst direction
    conviction: int
    mispricing_bps: float
    rel_mispricing_pct: float

    # Migration analysis
    category: str           # rising_star, fallen_angel, distressed_exit, stable
    migration_direction: str  # tightening, widening, stable
    implied_rating: str
    target_rating: str      # Where the spread says it's heading
    migration_probability: float  # 0-100%
    spread_vs_median: float      # How far from universe median
    roll_impact: str             # Description of roll impact
    thesis: str = ""
    catalyst: str = ""
    convergence: str = ""   # Whether RV agrees with analyst view


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_index_data() -> dict[str, str]:
    """Load entity -> sector mapping."""
    path = Path("indices/xover_s44.json")
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    mapping = {}
    for sector, names in data.get("sectors", {}).items():
        for name in names:
            mapping[name] = sector
    return mapping


def load_screen_data(screen_path: str = None) -> list[dict]:
    """Load all names from the latest xover screen Excel."""
    if not screen_path:
        outputs = Path("outputs")
        candidates = sorted(
            outputs.glob("xover_screen_*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return []
        screen_path = str(candidates[0])

    sector_map = load_index_data()
    wb = load_workbook(screen_path, read_only=True, data_only=True)
    ws = wb.active
    names = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        entity = str(row[0]).strip()
        spread = float(row[4]) if row[4] is not None else 0.0
        if spread <= 0:
            continue

        names.append({
            "entity_name": entity,
            "sector": sector_map.get(entity, "Other"),
            "current_spread": spread,
            "fair_spread": float(row[5]) if row[5] is not None else spread,
            "direction": str(row[1] or "").strip(),
            "conviction": int(row[2]) if row[2] is not None else 3,
            "mispricing_bps": float(row[6]) if row[6] is not None else 0.0,
            "rel_mispricing_pct": float(row[7]) if row[7] is not None else 0.0,
            "thesis": str(row[8] or "").strip(),
            "catalyst": str(row[9] or "").strip(),
        })

    wb.close()
    return names


# ---------------------------------------------------------------------------
# Migration Analysis
# ---------------------------------------------------------------------------

def _spread_to_implied_rating(spread: float) -> str:
    """Map current spread to implied rating."""
    if spread < 80:
        return "BBB"
    elif spread < 150:
        return "BB+"
    elif spread < 300:
        return "BB"
    elif spread < 500:
        return "B"
    elif spread < 800:
        return "B-"
    else:
        return "CCC"


def _target_rating(spread: float, fair_spread: float) -> str:
    """Where the name is heading based on fair spread direction."""
    # Use fair spread as a proxy for fundamental trajectory
    # If fair < current, the analyst thinks it should be tighter = upgrading
    # If fair > current, the analyst thinks it should be wider = downgrading
    return _spread_to_implied_rating(fair_spread)


def _migration_probability(spread: float, fair_spread: float,
                           category: str) -> float:
    """Estimate probability of migration event (0-100%).

    Based on:
    - How far the spread is from the threshold
    - Agreement between current spread and analyst fair value
    - Historical base rates for Xover migrations (~5-10% per roll)
    """
    if category == "rising_star":
        # Closer to IG threshold and fair tighter = higher probability
        distance_pct = (RISING_STAR_THRESHOLD - spread) / RISING_STAR_THRESHOLD * 100
        fair_signal = 1.0 if fair_spread < spread else 0.5
        base = min(90, max(10, 30 + distance_pct * 0.6))
        return round(base * fair_signal, 1)

    elif category == "distressed_exit":
        # Wider = more likely to exit
        excess = spread - DISTRESSED_THRESHOLD
        fair_signal = 1.0 if fair_spread > spread else 0.7
        base = min(90, max(15, 30 + excess / 10))
        return round(base * fair_signal, 1)

    elif category == "fallen_angel":
        # Names drifting wider within BB
        excess = spread - FALLEN_ANGEL_DRIFT
        base = min(50, max(5, 10 + excess / 20))
        return round(base, 1)

    return 0.0


def analyse_migration(names_data: list[dict]) -> list[MigrationSignal]:
    """Analyse all names for migration signals."""
    all_spreads = [n["current_spread"] for n in names_data]
    universe_median = median(all_spreads) if all_spreads else 200

    signals = []

    for n in names_data:
        spread = n["current_spread"]
        fair = n["fair_spread"]
        implied = _spread_to_implied_rating(spread)
        target = _target_rating(spread, fair)

        # Determine migration direction
        if fair < spread:
            migration_dir = "tightening"
        elif fair > spread:
            migration_dir = "widening"
        else:
            migration_dir = "stable"

        # Categorise
        category = "stable"
        roll_impact = "No significant roll impact expected"

        if spread < RISING_STAR_THRESHOLD:
            category = "rising_star"
            strength = "Strong" if spread < RISING_STAR_STRONG else "Moderate"
            roll_impact = (
                f"{strength} upgrade candidate for {NEXT_ROLL_SERIES} roll ({NEXT_ROLL}). "
                f"If upgraded to IG, exits Xover -> iTraxx Main. "
                f"Technical: short squeeze as index protection sellers cover, "
                f"expect 10-20bp tightening into roll date."
            )

        elif spread > DISTRESSED_THRESHOLD:
            category = "distressed_exit"
            severity = "Severe" if spread > SEVERE_DISTRESS else "Elevated"
            roll_impact = (
                f"{severity} distress signal -- potential removal from {NEXT_ROLL_SERIES}. "
                f"If removed, existing index positions unwind creating basis volatility. "
                f"Single-name CDS may decouple from index, widening CDS-index basis."
            )

        elif spread > FALLEN_ANGEL_DRIFT and migration_dir == "widening":
            category = "fallen_angel"
            roll_impact = (
                f"Drifting wider within HY -- spread implies deteriorating credit. "
                f"No immediate index impact but increases probability of future "
                f"distressed exit if trajectory continues."
            )

        prob = _migration_probability(spread, fair, category)

        # Convergence: does analyst view agree with spread signal?
        if category == "rising_star":
            if n["direction"] == "SHORT_RISK":
                convergence = "DIVERGENT: Analyst sees widening risk despite IG-like spread"
            elif n["direction"] == "LONG_RISK":
                convergence = "CONVERGENT: Analyst agrees name is cheap, supports tightening"
            else:
                convergence = "NEUTRAL: Analyst sees no strong directional view"
        elif category == "distressed_exit":
            if n["direction"] == "LONG_RISK":
                convergence = "CONTRARIAN: Analyst sees recovery potential despite distress spread"
            elif n["direction"] == "SHORT_RISK":
                convergence = "CONVERGENT: Analyst confirms widening risk"
            else:
                convergence = "NEUTRAL"
        else:
            convergence = "N/A"

        signals.append(MigrationSignal(
            entity_name=n["entity_name"],
            sector=n["sector"],
            current_spread=spread,
            fair_spread=fair,
            direction=n["direction"],
            conviction=n["conviction"],
            mispricing_bps=n["mispricing_bps"],
            rel_mispricing_pct=n["rel_mispricing_pct"],
            category=category,
            migration_direction=migration_dir,
            implied_rating=implied,
            target_rating=target,
            migration_probability=prob,
            spread_vs_median=spread - universe_median,
            roll_impact=roll_impact,
            thesis=n.get("thesis", ""),
            catalyst=n.get("catalyst", ""),
            convergence=convergence,
        ))

    return signals


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def print_migration_screen(signals: list[MigrationSignal],
                           show_detail: bool = False,
                           entity_filter: str = None):
    """Print the full migration screen."""
    if entity_filter:
        signals = [s for s in signals
                   if entity_filter.lower() in s.entity_name.lower()]

    # Group by category
    rising = [s for s in signals if s.category == "rising_star"]
    fallen = [s for s in signals if s.category == "fallen_angel"]
    distressed = [s for s in signals if s.category == "distressed_exit"]
    stable = [s for s in signals if s.category == "stable"]

    # Sort each group
    rising.sort(key=lambda s: s.current_spread)
    distressed.sort(key=lambda s: -s.current_spread)
    fallen.sort(key=lambda s: -s.current_spread)

    all_spreads = [s.current_spread for s in signals]
    med = median(all_spreads) if all_spreads else 0

    print(f"\n{'='*110}")
    print(f"  FALLEN ANGEL / RISING STAR SCREENER")
    print(f"  iTraxx Xover S44  |  {len(signals)} names  |  "
          f"Median spread: {med:.0f}bp  |  Next roll: {NEXT_ROLL} ({NEXT_ROLL_SERIES})")
    print(f"{'='*110}")

    # Rising Stars
    print(f"\n  RISING STARS -- Potential Upgrade to IG / Index Exit  "
          f"(spread < {RISING_STAR_THRESHOLD}bp)")
    print(f"  {'-'*105}")
    if rising:
        print(f"  {'Entity':<35} {'Sector':<18} {'Spread':>7} {'Fair':>7} "
              f"{'Implied':>7} {'Target':>7} {'Prob':>6} {'Dir':<12} {'Conv':>4}")
        print(f"  {'-'*35} {'-'*18} {'-'*7} {'-'*7} {'-'*7} {'-'*7} "
              f"{'-'*6} {'-'*12} {'-'*4}")
        for s in rising:
            dir_short = s.direction.replace("_RISK", "")
            print(f"  {s.entity_name[:35]:<35} {s.sector[:18]:<18} "
                  f"{s.current_spread:>7.1f} {s.fair_spread:>7.1f} "
                  f"{s.implied_rating:>7} {s.target_rating:>7} "
                  f"{s.migration_probability:>5.0f}% {dir_short:<12} {s.conviction:>4}")
            if show_detail:
                print(f"    Roll: {s.roll_impact}")
                print(f"    View: {s.convergence}")
                if s.thesis:
                    print(f"    Thesis: {s.thesis[:100]}")
                print()
    else:
        print(f"  (none)")

    # Distressed Exit
    print(f"\n  DISTRESSED EXIT -- Potential Removal from Index  "
          f"(spread > {DISTRESSED_THRESHOLD}bp)")
    print(f"  {'-'*105}")
    if distressed:
        print(f"  {'Entity':<35} {'Sector':<18} {'Spread':>7} {'Fair':>7} "
              f"{'Implied':>7} {'Target':>7} {'Prob':>6} {'Dir':<12} {'Conv':>4}")
        print(f"  {'-'*35} {'-'*18} {'-'*7} {'-'*7} {'-'*7} {'-'*7} "
              f"{'-'*6} {'-'*12} {'-'*4}")
        for s in distressed:
            dir_short = s.direction.replace("_RISK", "")
            print(f"  {s.entity_name[:35]:<35} {s.sector[:18]:<18} "
                  f"{s.current_spread:>7.1f} {s.fair_spread:>7.1f} "
                  f"{s.implied_rating:>7} {s.target_rating:>7} "
                  f"{s.migration_probability:>5.0f}% {dir_short:<12} {s.conviction:>4}")
            if show_detail:
                print(f"    Roll: {s.roll_impact}")
                print(f"    View: {s.convergence}")
                if s.thesis:
                    print(f"    Thesis: {s.thesis[:100]}")
                print()
    else:
        print(f"  (none)")

    # Fallen Angel Drift
    print(f"\n  FALLEN ANGEL DRIFT -- Widening Within HY  "
          f"(spread > {FALLEN_ANGEL_DRIFT}bp + widening)")
    print(f"  {'-'*105}")
    if fallen:
        print(f"  {'Entity':<35} {'Sector':<18} {'Spread':>7} {'Fair':>7} "
              f"{'Implied':>7} {'Target':>7} {'Prob':>6} {'Dir':<12} {'Conv':>4}")
        print(f"  {'-'*35} {'-'*18} {'-'*7} {'-'*7} {'-'*7} {'-'*7} "
              f"{'-'*6} {'-'*12} {'-'*4}")
        for s in fallen:
            dir_short = s.direction.replace("_RISK", "")
            print(f"  {s.entity_name[:35]:<35} {s.sector[:18]:<18} "
                  f"{s.current_spread:>7.1f} {s.fair_spread:>7.1f} "
                  f"{s.implied_rating:>7} {s.target_rating:>7} "
                  f"{s.migration_probability:>5.0f}% {dir_short:<12} {s.conviction:>4}")
            if show_detail:
                print(f"    Roll: {s.roll_impact}")
                if s.thesis:
                    print(f"    Thesis: {s.thesis[:100]}")
                print()
    else:
        print(f"  (none)")

    # Summary
    print(f"\n  {'='*110}")
    print(f"  SUMMARY")
    print(f"  {'='*110}")
    print(f"  Rising stars (IG-like):     {len(rising):>3}  "
          f"({', '.join(s.entity_name[:20] for s in rising[:5])})")
    print(f"  Distressed exit risk:       {len(distressed):>3}  "
          f"({', '.join(s.entity_name[:20] for s in distressed[:5])})")
    print(f"  Fallen angel drift:         {len(fallen):>3}  "
          f"({', '.join(s.entity_name[:20] for s in fallen[:5])})")
    print(f"  Stable core:                {len(stable):>3}")
    print(f"  Total:                      {len(signals):>3}")

    # Trading implications
    print(f"\n  ROLL TRADING IMPLICATIONS ({NEXT_ROLL}):")
    if rising:
        print(f"  * {len(rising)} names trading <{RISING_STAR_THRESHOLD}bp -- "
              f"SELL protection ahead of roll (short squeeze on exit)")
        for s in rising[:3]:
            print(f"      {s.entity_name[:30]} @ {s.current_spread:.0f}bp "
                  f"(prob {s.migration_probability:.0f}%)")
    if distressed:
        print(f"  * {len(distressed)} names trading >{DISTRESSED_THRESHOLD}bp -- "
              f"monitor for basis trades (CDS-index basis widens on removal)")
        for s in distressed[:3]:
            print(f"      {s.entity_name[:30]} @ {s.current_spread:.0f}bp "
                  f"(prob {s.migration_probability:.0f}%)")

    print(f"\n{'='*110}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fallen Angel / Rising Star Screener -- iTraxx Xover Roll Dynamics"
    )
    parser.add_argument(
        "--screen-file", type=str, default=None,
        help="Path to specific screen Excel",
    )
    parser.add_argument(
        "--detail", action="store_true",
        help="Show detailed thesis and roll impact for each name",
    )
    parser.add_argument(
        "--entity", type=str, default=None,
        help="Filter by entity name (partial match)",
    )
    args = parser.parse_args()

    names_data = load_screen_data(args.screen_file)
    if not names_data:
        print("Error: No screen data found.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(names_data)} names from screen")
    signals = analyse_migration(names_data)

    print_migration_screen(signals, show_detail=args.detail,
                           entity_filter=args.entity)


if __name__ == "__main__":
    main()

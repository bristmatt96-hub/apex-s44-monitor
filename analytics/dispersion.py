"""
Dispersion Analytics -- Spread Dispersion & Correlation Regime Monitor

Measures how dispersed the iTraxx Xover universe is across 75 names,
sectors, and rating buckets. High dispersion = better for single-name
alpha and relative value; low dispersion = better for index/tranche trades.

Metrics:
    - Universe dispersion:      stdev(spreads) / mean(spreads)
    - Sector dispersion:        per-sector coefficient of variation
    - Rating bucket dispersion: per-rating-bucket CV
    - Dispersion regime:        HIGH / MODERATE / LOW classification
    - Pair trade opportunity:   sectors with highest internal dispersion

Regime Thresholds (coefficient of variation):
    CV > 1.0   = HIGH dispersion    -- single-name alpha regime
    0.5-1.0    = MODERATE           -- balanced opportunity set
    CV < 0.5   = LOW dispersion     -- index/tranche regime

Usage:
    python -m analytics.dispersion                # Full dispersion report
    python -m analytics.dispersion --sector TMT   # Single sector detail
    python -m analytics.dispersion --json          # JSON output
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev, quantiles

from openpyxl import load_workbook


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regime thresholds (coefficient of variation)
HIGH_DISPERSION_CV = 1.0    # CV > 1.0 = high dispersion
LOW_DISPERSION_CV = 0.5     # CV < 0.5 = low dispersion

# Rating buckets (spread-implied)
RATING_BUCKETS = [
    ("BB+", 0, 150),
    ("BB",  150, 300),
    ("B",   300, 500),
    ("B-",  500, 800),
    ("CCC", 800, 9999),
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class NameSpread:
    """Spread data for a single name."""
    entity_name: str
    sector: str
    current_spread: float
    fair_spread: float
    implied_rating: str
    direction: str
    conviction: int


@dataclass
class DispersionStats:
    """Dispersion statistics for a group of names."""
    group_name: str
    group_type: str          # "universe", "sector", "rating"
    count: int
    mean_spread: float
    median_spread: float
    stdev_spread: float
    min_spread: float
    max_spread: float
    range_spread: float
    cv: float                # Coefficient of variation (stdev/mean)
    iqr: float               # Interquartile range
    regime: str              # HIGH, MODERATE, LOW
    widest_name: str
    tightest_name: str
    pair_opportunity: float  # Spread range as % of mean


@dataclass
class DispersionReport:
    """Full dispersion report."""
    report_date: str
    universe_stats: DispersionStats
    sector_stats: list[DispersionStats]
    rating_stats: list[DispersionStats]
    regime: str
    regime_description: str
    top_dispersion_sectors: list[str]
    bottom_dispersion_sectors: list[str]
    pair_trade_sectors: list[str]    # Best sectors for pair trades
    names: list[NameSpread] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_index_data() -> dict[str, str]:
    """Load entity -> sector mapping from xover_s44.json."""
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


def spread_to_rating(spread: float) -> str:
    """Map spread to implied rating bucket."""
    for rating, low, high in RATING_BUCKETS:
        if low <= spread < high:
            return rating
    return "CCC"


def load_spread_data(screen_path: str = None) -> list[NameSpread]:
    """Load all 75 names with spreads from the latest xover screen."""
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

        fair = float(row[5]) if row[5] is not None else spread
        direction = str(row[1] or "").strip()
        conviction = int(row[2]) if row[2] is not None else 3

        names.append(NameSpread(
            entity_name=entity,
            sector=sector_map.get(entity, "Other"),
            current_spread=spread,
            fair_spread=fair,
            implied_rating=spread_to_rating(spread),
            direction=direction,
            conviction=conviction,
        ))

    wb.close()
    return names


# ---------------------------------------------------------------------------
# Dispersion calculations
# ---------------------------------------------------------------------------

def compute_dispersion(
    names: list[NameSpread],
    group_name: str,
    group_type: str,
) -> DispersionStats | None:
    """Compute dispersion statistics for a group of names."""
    if len(names) < 2:
        return None

    spreads = [n.current_spread for n in names]
    s_mean = mean(spreads)
    s_median = median(spreads)
    s_stdev = stdev(spreads)
    s_min = min(spreads)
    s_max = max(spreads)

    cv = s_stdev / s_mean if s_mean > 0 else 0

    # IQR
    if len(spreads) >= 4:
        q = quantiles(spreads, n=4)
        iqr = q[2] - q[0]  # Q3 - Q1
    else:
        iqr = s_max - s_min

    # Regime classification
    if cv > HIGH_DISPERSION_CV:
        regime = "HIGH"
    elif cv < LOW_DISPERSION_CV:
        regime = "LOW"
    else:
        regime = "MODERATE"

    widest = max(names, key=lambda n: n.current_spread)
    tightest = min(names, key=lambda n: n.current_spread)

    return DispersionStats(
        group_name=group_name,
        group_type=group_type,
        count=len(names),
        mean_spread=s_mean,
        median_spread=s_median,
        stdev_spread=s_stdev,
        min_spread=s_min,
        max_spread=s_max,
        range_spread=s_max - s_min,
        cv=cv,
        iqr=iqr,
        regime=regime,
        widest_name=widest.entity_name,
        tightest_name=tightest.entity_name,
        pair_opportunity=(s_max - s_min) / s_mean * 100 if s_mean > 0 else 0,
    )


def run_dispersion_analysis(
    names: list[NameSpread],
) -> DispersionReport:
    """Run full dispersion analysis across universe, sectors, and ratings."""

    # Universe-level
    universe_stats = compute_dispersion(names, "Xover Universe", "universe")

    # Sector-level
    sectors: dict[str, list[NameSpread]] = {}
    for n in names:
        sectors.setdefault(n.sector, []).append(n)

    sector_stats = []
    for sector_name in sorted(sectors.keys()):
        s = compute_dispersion(sectors[sector_name], sector_name, "sector")
        if s:
            sector_stats.append(s)

    # Rating-level
    ratings: dict[str, list[NameSpread]] = {}
    for n in names:
        ratings.setdefault(n.implied_rating, []).append(n)

    rating_stats = []
    for rating_label, _, _ in RATING_BUCKETS:
        if rating_label in ratings:
            s = compute_dispersion(ratings[rating_label], rating_label, "rating")
            if s:
                rating_stats.append(s)

    # Sort sectors by dispersion (highest first)
    sector_by_cv = sorted(sector_stats, key=lambda s: s.cv, reverse=True)
    top_sectors = [s.group_name for s in sector_by_cv[:3]]
    bottom_sectors = [s.group_name for s in sector_by_cv[-2:]]

    # Best pair trade sectors: high dispersion + enough names
    pair_sectors = [
        s.group_name for s in sector_by_cv
        if s.count >= 4 and s.cv >= 0.3
    ][:5]

    # Overall regime
    regime = universe_stats.regime if universe_stats else "MODERATE"
    regime_descriptions = {
        "HIGH": (
            "High spread dispersion across the Xover universe indicates a "
            "single-name alpha regime. Wide variation between names within "
            "sectors creates rich relative value opportunities. Favour "
            "single-name CDS positions and intra-sector pair trades over "
            "index/tranche strategies."
        ),
        "MODERATE": (
            "Moderate dispersion signals a balanced opportunity set. Both "
            "single-name relative value and index/tranche strategies can "
            "add value. Focus pair trades on the highest-dispersion sectors "
            "while maintaining index hedge positions."
        ),
        "LOW": (
            "Low dispersion indicates a correlation-driven market where "
            "names move together. Single-name alpha is harder to extract. "
            "Favour index and tranche strategies that benefit from "
            "correlation (e.g. selling mezzanine tranche protection). "
            "Pair trades are less attractive."
        ),
    }

    return DispersionReport(
        report_date=datetime.now().strftime("%Y-%m-%d"),
        universe_stats=universe_stats,
        sector_stats=sector_stats,
        rating_stats=rating_stats,
        regime=regime,
        regime_description=regime_descriptions.get(regime, ""),
        top_dispersion_sectors=top_sectors,
        bottom_dispersion_sectors=bottom_sectors,
        pair_trade_sectors=pair_sectors,
        names=names,
    )


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def print_report(report: DispersionReport, sector_filter: str | None = None):
    """Print formatted dispersion report."""
    u = report.universe_stats

    print(f"\n{'='*100}")
    print(f"  SPREAD DISPERSION ANALYTICS -- iTraxx Xover Universe")
    print(f"  {report.report_date} | {u.count} names")
    print(f"{'='*100}")

    # Universe summary
    print(f"\n  UNIVERSE SUMMARY")
    print(f"  {'-'*60}")
    print(f"  Mean spread:       {u.mean_spread:>8.1f}bp")
    print(f"  Median spread:     {u.median_spread:>8.1f}bp")
    print(f"  Std deviation:     {u.stdev_spread:>8.1f}bp")
    print(f"  Range:             {u.min_spread:.0f}bp - {u.max_spread:.0f}bp "
          f"({u.range_spread:.0f}bp)")
    print(f"  IQR:               {u.iqr:>8.1f}bp")
    print(f"  Coeff of Variation:{u.cv:>8.3f}")
    print(f"  Dispersion Regime: {u.regime}")
    print(f"  Tightest:          {u.tightest_name} ({u.min_spread:.0f}bp)")
    print(f"  Widest:            {u.widest_name} ({u.max_spread:.0f}bp)")

    # Regime box
    print(f"\n  {'='*60}")
    print(f"  REGIME: {report.regime}")
    print(f"  {'-'*60}")
    # Word wrap the description
    words = report.regime_description.split()
    line = "  "
    for w in words:
        if len(line) + len(w) + 1 > 62:
            print(line)
            line = "  " + w
        else:
            line += " " + w if line.strip() else "  " + w
    if line.strip():
        print(line)
    print(f"  {'='*60}")

    # Sector dispersion table
    stats_to_show = report.sector_stats
    if sector_filter:
        stats_to_show = [
            s for s in stats_to_show
            if sector_filter.lower() in s.group_name.lower()
        ]

    print(f"\n  SECTOR DISPERSION (sorted by CV -- highest dispersion first)")
    print(f"  {'-'*95}")
    print(f"  {'Sector':<25} {'#':>3} {'Mean':>7} {'Median':>7} {'Stdev':>7} "
          f"{'Range':>10} {'CV':>6} {'Regime':<10} {'Pair Opp':>8}")
    print(f"  {'-'*25} {'-'*3} {'-'*7} {'-'*7} {'-'*7} {'-'*10} "
          f"{'-'*6} {'-'*10} {'-'*8}")

    for s in sorted(stats_to_show, key=lambda x: x.cv, reverse=True):
        range_str = f"{s.min_spread:.0f}-{s.max_spread:.0f}"
        pair_opp = f"{s.pair_opportunity:.0f}%"
        print(f"  {s.group_name:<25} {s.count:>3} {s.mean_spread:>6.0f}bp "
              f"{s.median_spread:>6.0f}bp {s.stdev_spread:>6.0f}bp "
              f"{range_str:>10} {s.cv:>5.2f} {s.regime:<10} {pair_opp:>8}")

    # Show sector detail if filtered
    if sector_filter and stats_to_show:
        for s in stats_to_show:
            sector_names = [
                n for n in report.names
                if n.sector == s.group_name
            ]
            if sector_names:
                print(f"\n  {s.group_name} -- NAME DETAIL "
                      f"(sorted by spread)")
                print(f"  {'-'*75}")
                print(f"  {'Entity':<35} {'Spread':>7} {'Fair':>7} "
                      f"{'Rating':>6} {'Dir':<12} {'Conv':>4}")
                print(f"  {'-'*35} {'-'*7} {'-'*7} {'-'*6} {'-'*12} {'-'*4}")
                for n in sorted(sector_names,
                                key=lambda x: x.current_spread):
                    dir_short = {
                        "LONG_RISK": "LONG",
                        "SHORT_RISK": "SHORT",
                        "FLAT": "FLAT",
                    }.get(n.direction, n.direction[:8])
                    print(f"  {n.entity_name[:35]:<35} "
                          f"{n.current_spread:>6.0f}bp "
                          f"{n.fair_spread:>6.0f}bp "
                          f"{n.implied_rating:>6} "
                          f"{dir_short:<12} {n.conviction:>4}")

    # Rating bucket dispersion
    print(f"\n  RATING BUCKET DISPERSION")
    print(f"  {'-'*85}")
    print(f"  {'Rating':<8} {'#':>3} {'Mean':>7} {'Median':>7} {'Stdev':>7} "
          f"{'Range':>12} {'CV':>6} {'Regime':<10}")
    print(f"  {'-'*8} {'-'*3} {'-'*7} {'-'*7} {'-'*7} {'-'*12} "
          f"{'-'*6} {'-'*10}")

    for s in report.rating_stats:
        range_str = f"{s.min_spread:.0f}-{s.max_spread:.0f}"
        print(f"  {s.group_name:<8} {s.count:>3} {s.mean_spread:>6.0f}bp "
              f"{s.median_spread:>6.0f}bp {s.stdev_spread:>6.0f}bp "
              f"{range_str:>12} {s.cv:>5.2f} {s.regime:<10}")

    # Strategy implications
    print(f"\n  STRATEGY IMPLICATIONS")
    print(f"  {'-'*60}")
    print(f"  Best sectors for pair trades (high dispersion):")
    for s_name in report.pair_trade_sectors:
        s_data = next(
            (s for s in report.sector_stats if s.group_name == s_name),
            None,
        )
        if s_data:
            print(f"    - {s_name}: CV={s_data.cv:.2f}, "
                  f"range={s_data.range_spread:.0f}bp "
                  f"({s_data.tightest_name[:20]} to "
                  f"{s_data.widest_name[:20]})")

    if report.bottom_dispersion_sectors:
        print(f"\n  Lowest dispersion sectors (favour index exposure):")
        for s_name in report.bottom_dispersion_sectors:
            s_data = next(
                (s for s in report.sector_stats if s.group_name == s_name),
                None,
            )
            if s_data:
                print(f"    - {s_name}: CV={s_data.cv:.2f}, "
                      f"names move more in tandem")

    # Spread distribution histogram (text-based)
    print(f"\n  SPREAD DISTRIBUTION")
    print(f"  {'-'*60}")
    buckets = [
        ("0-100bp",    0, 100),
        ("100-200bp",  100, 200),
        ("200-300bp",  200, 300),
        ("300-500bp",  300, 500),
        ("500-800bp",  500, 800),
        ("800bp+",     800, 99999),
    ]
    for label, low, high in buckets:
        count = sum(
            1 for n in report.names
            if low <= n.current_spread < high
        )
        bar = "#" * count
        pct = count / len(report.names) * 100 if report.names else 0
        print(f"  {label:<12} {count:>3} ({pct:>4.0f}%) {bar}")

    print(f"\n{'='*100}")


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def report_to_json(report: DispersionReport) -> str:
    """Convert report to JSON."""
    def stats_to_dict(s: DispersionStats) -> dict:
        return {
            "group_name": s.group_name,
            "group_type": s.group_type,
            "count": s.count,
            "mean_spread": round(s.mean_spread, 1),
            "median_spread": round(s.median_spread, 1),
            "stdev_spread": round(s.stdev_spread, 1),
            "min_spread": round(s.min_spread, 1),
            "max_spread": round(s.max_spread, 1),
            "range_spread": round(s.range_spread, 1),
            "cv": round(s.cv, 3),
            "iqr": round(s.iqr, 1),
            "regime": s.regime,
            "widest_name": s.widest_name,
            "tightest_name": s.tightest_name,
            "pair_opportunity": round(s.pair_opportunity, 1),
        }

    output = {
        "report_date": report.report_date,
        "regime": report.regime,
        "regime_description": report.regime_description,
        "universe": stats_to_dict(report.universe_stats),
        "sectors": [stats_to_dict(s) for s in report.sector_stats],
        "rating_buckets": [stats_to_dict(s) for s in report.rating_stats],
        "top_dispersion_sectors": report.top_dispersion_sectors,
        "pair_trade_sectors": report.pair_trade_sectors,
        "names": [
            {
                "entity_name": n.entity_name,
                "sector": n.sector,
                "spread": n.current_spread,
                "fair_spread": n.fair_spread,
                "implied_rating": n.implied_rating,
            }
            for n in sorted(report.names,
                            key=lambda x: x.current_spread, reverse=True)
        ],
    }
    return json.dumps(output, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Spread Dispersion Analytics -- iTraxx Xover"
    )
    parser.add_argument(
        "--screen-file", type=str, default=None,
        help="Specific xover screen Excel file",
    )
    parser.add_argument(
        "--sector", type=str, default=None,
        help="Filter by sector (partial match)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    # Load data
    names = load_spread_data(args.screen_file)
    if not names:
        print("Error: No spread data found. Run scripts/run_universe.py first.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(names)} names from xover screen")

    # Run analysis
    report = run_dispersion_analysis(names)

    if args.json:
        print(report_to_json(report))
        return

    print_report(report, sector_filter=args.sector)


if __name__ == "__main__":
    main()

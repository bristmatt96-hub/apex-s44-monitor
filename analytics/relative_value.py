"""
Rich/Cheap Relative Value Screener -- iTraxx Xover Universe

Compares each name's current spread to where it "should" trade based on
comparable peers, producing a composite rich/cheap score.

Dimensions:
    1. Sector RV     -- z-score vs sector median/mean
    2. Rating RV     -- z-score vs implied rating bucket
    3. Momentum RV   -- current spread vs analyst fair spread (mispricing %)
    4. Composite      -- weighted blend of all dimensions
    5. Pair ideas     -- top sector-neutral pair trades from composite

Rating buckets (from spread levels):
    <150bp  =  BB+     150-300bp  =  BB     300-500bp  =  B
    500-800bp = B-     >800bp     =  CCC

Usage:
    python -m analytics.relative_value                    # Full screen
    python -m analytics.relative_value --top 10           # Top 10 rich + cheap
    python -m analytics.relative_value --sector TMT       # Single sector
    python -m analytics.relative_value --pairs            # Best pair trades
    python -m analytics.relative_value --entity INEOS     # Search specific name
    python -m analytics.relative_value --excel            # Export to Excel
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path("outputs/analytics")

# Rating buckets from spread levels (bps)
RATING_BUCKETS = [
    ("BB+",  0,    150),
    ("BB",   150,  300),
    ("B",    300,  500),
    ("B-",   500,  800),
    ("CCC",  800,  9999),
]

# Composite weights
WEIGHT_SECTOR = 0.35
WEIGHT_RATING = 0.35
WEIGHT_MOMENTUM = 0.30


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class NameData:
    """Market data for a single name."""
    entity_name: str
    sector: str
    current_spread: float
    fair_spread: float
    direction: str
    conviction: int
    raw_conviction: int
    mispricing_bps: float
    rel_mispricing_pct: float
    implied_rating: str = ""

    # RV scores (set by analysis)
    sector_z: float = 0.0
    rating_z: float = 0.0
    momentum_score: float = 0.0
    composite_score: float = 0.0
    rv_signal: str = ""   # CHEAP, RICH, FAIR


@dataclass
class PairTrade:
    """A rich/cheap pair trade idea."""
    cheap_name: str
    rich_name: str
    sector: str
    spread_diff: float
    composite_diff: float
    cheap_spread: float
    rich_spread: float
    cheap_score: float
    rich_score: float
    rationale: str = ""


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


def load_market_data(screen_path: str = None) -> list[NameData]:
    """Load market data from the latest xover screen Excel."""
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
        mispricing = float(row[6]) if row[6] is not None else 0.0
        rel_misp = float(row[7]) if row[7] is not None else 0.0

        nd = NameData(
            entity_name=entity,
            sector=sector_map.get(entity, "Other"),
            current_spread=spread,
            fair_spread=fair,
            direction=str(row[1] or "").strip(),
            conviction=int(row[2]) if row[2] is not None else 3,
            raw_conviction=int(row[3]) if row[3] is not None else 3,
            mispricing_bps=mispricing,
            rel_mispricing_pct=rel_misp,
        )
        # Assign implied rating
        nd.implied_rating = _spread_to_rating(spread)
        names.append(nd)

    wb.close()
    return names


def _spread_to_rating(spread: float) -> str:
    """Map spread level to implied rating bucket."""
    for rating, low, high in RATING_BUCKETS:
        if low <= spread < high:
            return rating
    return "CCC"


# ---------------------------------------------------------------------------
# RV Analysis Functions
# ---------------------------------------------------------------------------

def sector_relative_value(names: list[NameData]) -> list[NameData]:
    """Compute sector-relative z-scores.

    For each name, compare its spread to the sector median and average.
    z-score = (spread - sector_median) / sector_stdev

    Positive z = cheap (wide of peers), negative z = rich (tight of peers).
    """
    # Group by sector
    sectors: dict[str, list[NameData]] = {}
    for n in names:
        sectors.setdefault(n.sector, []).append(n)

    for sector, sector_names in sectors.items():
        spreads = [n.current_spread for n in sector_names]
        if len(spreads) < 2:
            for n in sector_names:
                n.sector_z = 0.0
            continue

        med = median(spreads)
        sd = stdev(spreads)

        for n in sector_names:
            if sd > 0:
                n.sector_z = (n.current_spread - med) / sd
            else:
                n.sector_z = 0.0

    return names


def rating_relative_value(names: list[NameData]) -> list[NameData]:
    """Compute rating-bucket relative z-scores.

    Groups names by implied rating bucket and calculates z-score
    within the rating peer group.

    Positive z = cheap (wide of rating peers), negative = rich.
    """
    # Group by implied rating
    buckets: dict[str, list[NameData]] = {}
    for n in names:
        buckets.setdefault(n.implied_rating, []).append(n)

    for rating, bucket_names in buckets.items():
        spreads = [n.current_spread for n in bucket_names]
        if len(spreads) < 2:
            for n in bucket_names:
                n.rating_z = 0.0
            continue

        med = median(spreads)
        sd = stdev(spreads)

        for n in bucket_names:
            if sd > 0:
                n.rating_z = (n.current_spread - med) / sd
            else:
                n.rating_z = 0.0

    return names


def momentum_relative_value(names: list[NameData]) -> list[NameData]:
    """Compute momentum/mispricing score.

    Uses the analyst fair spread vs current spread to derive a
    normalised mispricing signal.

    Score = (current - fair) / fair * 100

    Positive = cheap (trading wider than fair), negative = rich.
    Normalised to z-score scale across the universe.
    """
    raw_scores = []
    for n in names:
        if n.fair_spread > 0:
            raw = (n.current_spread - n.fair_spread) / n.fair_spread * 100
        else:
            raw = 0.0
        raw_scores.append(raw)

    # Normalise to z-score
    if len(raw_scores) >= 2:
        avg = mean(raw_scores)
        sd = stdev(raw_scores)
    else:
        avg = 0.0
        sd = 1.0

    for i, n in enumerate(names):
        if sd > 0:
            n.momentum_score = (raw_scores[i] - avg) / sd
        else:
            n.momentum_score = 0.0

    return names


def composite_score(names: list[NameData]) -> list[NameData]:
    """Compute weighted composite rich/cheap score.

    Composite = w_sector * sector_z + w_rating * rating_z + w_momentum * momentum_z

    Positive composite = CHEAP, negative = RICH, near-zero = FAIR.
    Signal thresholds: |score| > 1.0 = strong signal, 0.5-1.0 = moderate.
    """
    for n in names:
        n.composite_score = (
            WEIGHT_SECTOR * n.sector_z
            + WEIGHT_RATING * n.rating_z
            + WEIGHT_MOMENTUM * n.momentum_score
        )

        if n.composite_score > 1.0:
            n.rv_signal = "CHEAP"
        elif n.composite_score > 0.5:
            n.rv_signal = "cheap"
        elif n.composite_score < -1.0:
            n.rv_signal = "RICH"
        elif n.composite_score < -0.5:
            n.rv_signal = "rich"
        else:
            n.rv_signal = "FAIR"

    return names


def find_pair_trades(names: list[NameData], max_pairs: int = 10) -> list[PairTrade]:
    """Find best sector-neutral rich/cheap pair trades.

    Within each sector, pair the cheapest name (buy protection)
    with the richest name (sell protection) for a spread-neutral trade.

    Also searches cross-sector pairs within the same rating bucket.
    """
    pairs = []

    # --- Intra-sector pairs ---
    sectors: dict[str, list[NameData]] = {}
    for n in names:
        sectors.setdefault(n.sector, []).append(n)

    for sector, sector_names in sectors.items():
        if len(sector_names) < 2:
            continue

        sorted_by_score = sorted(sector_names, key=lambda x: x.composite_score)
        richest = sorted_by_score[:3]   # Most negative scores (rich)
        cheapest = sorted_by_score[-3:]  # Most positive scores (cheap)

        for cheap in cheapest:
            for rich in richest:
                if cheap.entity_name == rich.entity_name:
                    continue
                if cheap.composite_score <= rich.composite_score:
                    continue

                diff = cheap.composite_score - rich.composite_score
                if diff < 0.5:
                    continue

                pairs.append(PairTrade(
                    cheap_name=cheap.entity_name,
                    rich_name=rich.entity_name,
                    sector=sector,
                    spread_diff=cheap.current_spread - rich.current_spread,
                    composite_diff=diff,
                    cheap_spread=cheap.current_spread,
                    rich_spread=rich.current_spread,
                    cheap_score=cheap.composite_score,
                    rich_score=rich.composite_score,
                    rationale=f"Intra-{sector}: buy protection on {cheap.entity_name[:20]} "
                              f"({cheap.current_spread:.0f}bp, {cheap.rv_signal}) "
                              f"vs sell protection on {rich.entity_name[:20]} "
                              f"({rich.current_spread:.0f}bp, {rich.rv_signal})",
                ))

    # --- Cross-sector same-rating pairs ---
    ratings: dict[str, list[NameData]] = {}
    for n in names:
        ratings.setdefault(n.implied_rating, []).append(n)

    for rating, rating_names in ratings.items():
        if len(rating_names) < 2:
            continue

        sorted_by_score = sorted(rating_names, key=lambda x: x.composite_score)
        richest = sorted_by_score[:2]
        cheapest = sorted_by_score[-2:]

        for cheap in cheapest:
            for rich in richest:
                if cheap.entity_name == rich.entity_name:
                    continue
                if cheap.sector == rich.sector:
                    continue  # Already captured in intra-sector
                if cheap.composite_score <= rich.composite_score:
                    continue

                diff = cheap.composite_score - rich.composite_score
                if diff < 0.8:
                    continue

                pairs.append(PairTrade(
                    cheap_name=cheap.entity_name,
                    rich_name=rich.entity_name,
                    sector=f"x-sector ({rating})",
                    spread_diff=cheap.current_spread - rich.current_spread,
                    composite_diff=diff,
                    cheap_spread=cheap.current_spread,
                    rich_spread=rich.current_spread,
                    cheap_score=cheap.composite_score,
                    rich_score=rich.composite_score,
                    rationale=f"Cross-sector {rating}: {cheap.sector} vs {rich.sector}",
                ))

    # Sort by composite difference (strongest signal first)
    pairs.sort(key=lambda p: p.composite_diff, reverse=True)
    return pairs[:max_pairs]


# ---------------------------------------------------------------------------
# Full analysis pipeline
# ---------------------------------------------------------------------------

def run_full_analysis(screen_path: str = None) -> tuple[list[NameData], list[PairTrade]]:
    """Run all RV analysis dimensions and return scored names + pairs."""
    names = load_market_data(screen_path)
    if not names:
        print("Error: No market data found.", file=sys.stderr)
        return [], []

    names = sector_relative_value(names)
    names = rating_relative_value(names)
    names = momentum_relative_value(names)
    names = composite_score(names)
    pairs = find_pair_trades(names)

    return names, pairs


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

def export_to_excel(names: list[NameData], pairs: list[PairTrade]) -> str:
    """Export rich/cheap analysis to Excel workbook."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filepath = str(OUTPUT_DIR / f"relative_value_{date_str}.xlsx")

    HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
    HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    CHEAP_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    RICH_FILL = PatternFill(start_color="FCE4EC", end_color="FCE4EC", fill_type="solid")
    GREEN_FONT = Font(bold=True, color="28A745")
    RED_FONT = Font(bold=True, color="DC3545")

    wb = Workbook()

    # Sheet 1: Full universe
    ws1 = wb.active
    ws1.title = "Relative Value Screen"

    headers = ["Entity", "Sector", "Rating", "Spread", "Fair", "Misprice",
               "Sector Z", "Rating Z", "Momentum Z", "Composite", "Signal",
               "Direction", "Conv"]
    for c, h in enumerate(headers, 1):
        cell = ws1.cell(row=1, column=c, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")

    sorted_names = sorted(names, key=lambda n: n.composite_score, reverse=True)
    for i, n in enumerate(sorted_names):
        r = i + 2
        ws1.cell(row=r, column=1, value=n.entity_name)
        ws1.cell(row=r, column=2, value=n.sector)
        ws1.cell(row=r, column=3, value=n.implied_rating)
        ws1.cell(row=r, column=4, value=round(n.current_spread, 1))
        ws1.cell(row=r, column=5, value=round(n.fair_spread, 1))
        ws1.cell(row=r, column=6, value=round(n.mispricing_bps, 0))
        ws1.cell(row=r, column=7, value=round(n.sector_z, 2))
        ws1.cell(row=r, column=8, value=round(n.rating_z, 2))
        ws1.cell(row=r, column=9, value=round(n.momentum_score, 2))
        score_cell = ws1.cell(row=r, column=10, value=round(n.composite_score, 2))
        signal_cell = ws1.cell(row=r, column=11, value=n.rv_signal)
        ws1.cell(row=r, column=12, value=n.direction)
        ws1.cell(row=r, column=13, value=n.conviction)

        if "CHEAP" in n.rv_signal.upper():
            score_cell.font = GREEN_FONT
            signal_cell.font = GREEN_FONT
            signal_cell.fill = CHEAP_FILL
        elif "RICH" in n.rv_signal.upper():
            score_cell.font = RED_FONT
            signal_cell.font = RED_FONT
            signal_cell.fill = RICH_FILL

    for col, w in zip(range(1, 14), [35, 18, 6, 8, 8, 8, 9, 9, 10, 10, 8, 12, 5]):
        ws1.column_dimensions[chr(64 + col) if col < 27 else ""].width = w
    # Fix column widths properly
    from openpyxl.utils import get_column_letter
    for col, w in enumerate([35, 18, 6, 8, 8, 8, 9, 9, 10, 10, 8, 12, 5], 1):
        ws1.column_dimensions[get_column_letter(col)].width = w

    ws1.freeze_panes = "A2"

    # Sheet 2: Pair trades
    ws2 = wb.create_sheet("Pair Trades")
    pair_headers = ["Rank", "Cheap (Buy Prot)", "Spread", "Score",
                    "Rich (Sell Prot)", "Spread", "Score",
                    "Sector", "Composite Diff", "Rationale"]
    for c, h in enumerate(pair_headers, 1):
        cell = ws2.cell(row=1, column=c, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    for i, p in enumerate(pairs):
        r = i + 2
        ws2.cell(row=r, column=1, value=i + 1)
        ws2.cell(row=r, column=2, value=p.cheap_name)
        ws2.cell(row=r, column=3, value=round(p.cheap_spread, 0))
        ws2.cell(row=r, column=4, value=round(p.cheap_score, 2))
        ws2.cell(row=r, column=5, value=p.rich_name)
        ws2.cell(row=r, column=6, value=round(p.rich_spread, 0))
        ws2.cell(row=r, column=7, value=round(p.rich_score, 2))
        ws2.cell(row=r, column=8, value=p.sector)
        ws2.cell(row=r, column=9, value=round(p.composite_diff, 2))
        ws2.cell(row=r, column=10, value=p.rationale)

    for col, w in enumerate([5, 32, 8, 7, 32, 8, 7, 18, 12, 55], 1):
        ws2.column_dimensions[get_column_letter(col)].width = w

    # Sheet 3: Sector summary
    ws3 = wb.create_sheet("Sector Summary")
    sec_headers = ["Sector", "Names", "Median Spread", "Mean Spread", "Stdev",
                   "Cheapest", "Richest", "Spread Range"]
    for c, h in enumerate(sec_headers, 1):
        cell = ws3.cell(row=1, column=c, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    sectors: dict[str, list[NameData]] = {}
    for n in names:
        sectors.setdefault(n.sector, []).append(n)

    r = 2
    for sector in sorted(sectors.keys()):
        sn = sectors[sector]
        spreads = [n.current_spread for n in sn]
        cheapest = max(sn, key=lambda n: n.composite_score)
        richest = min(sn, key=lambda n: n.composite_score)

        ws3.cell(row=r, column=1, value=sector)
        ws3.cell(row=r, column=2, value=len(sn))
        ws3.cell(row=r, column=3, value=round(median(spreads), 0))
        ws3.cell(row=r, column=4, value=round(mean(spreads), 0))
        ws3.cell(row=r, column=5, value=round(stdev(spreads), 0) if len(spreads) > 1 else 0)
        ws3.cell(row=r, column=6, value=f"{cheapest.entity_name[:25]} ({cheapest.composite_score:+.2f})")
        ws3.cell(row=r, column=7, value=f"{richest.entity_name[:25]} ({richest.composite_score:+.2f})")
        ws3.cell(row=r, column=8, value=f"{min(spreads):.0f} - {max(spreads):.0f}")
        r += 1

    for col, w in enumerate([20, 7, 14, 12, 8, 35, 35, 14], 1):
        ws3.column_dimensions[get_column_letter(col)].width = w

    wb.save(filepath)
    return filepath


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def print_universe(names: list[NameData], top_n: int = 0,
                   sector_filter: str = None, entity_filter: str = None):
    """Print the full RV screen to terminal."""
    filtered = names

    if sector_filter:
        filtered = [n for n in filtered if sector_filter.lower() in n.sector.lower()]
    if entity_filter:
        filtered = [n for n in filtered
                    if entity_filter.lower() in n.entity_name.lower()]

    sorted_names = sorted(filtered, key=lambda n: n.composite_score, reverse=True)

    if top_n > 0:
        cheapest = sorted_names[:top_n]
        richest = sorted_names[-top_n:]
        display_names = cheapest + [None] + richest  # None = separator
    else:
        display_names = sorted_names

    # Stats
    scores = [n.composite_score for n in filtered]
    cheap_count = sum(1 for n in filtered if "CHEAP" in n.rv_signal.upper())
    rich_count = sum(1 for n in filtered if "RICH" in n.rv_signal.upper())
    fair_count = sum(1 for n in filtered if n.rv_signal == "FAIR")

    label = f"Sector: {sector_filter}" if sector_filter else "Full Universe"
    print(f"\n{'='*110}")
    print(f"  RELATIVE VALUE SCREEN -- {label}")
    print(f"  {len(filtered)} names  |  {cheap_count} CHEAP  |  "
          f"{rich_count} RICH  |  {fair_count} FAIR")
    print(f"{'='*110}")

    print(f"\n  {'Entity':<32} {'Sector':<18} {'Rtg':<4} {'Spread':>7} "
          f"{'Fair':>7} {'SectZ':>6} {'RtgZ':>6} {'MomZ':>6} "
          f"{'Comp':>6}  {'Signal':<6}")
    print(f"  {'-'*32} {'-'*18} {'-'*4} {'-'*7} {'-'*7} {'-'*6} {'-'*6} "
          f"{'-'*6} {'-'*6}  {'-'*6}")

    for n in display_names:
        if n is None:
            print(f"  {'...':<32}")
            continue

        comp_str = f"{n.composite_score:>+5.2f}"
        print(f"  {n.entity_name[:32]:<32} {n.sector[:18]:<18} "
              f"{n.implied_rating:<4} {n.current_spread:>7.1f} "
              f"{n.fair_spread:>7.1f} {n.sector_z:>+6.2f} "
              f"{n.rating_z:>+6.2f} {n.momentum_score:>+6.2f} "
              f"{comp_str}  {n.rv_signal:<6}")

    print(f"\n{'='*110}")


def print_pairs(pairs: list[PairTrade]):
    """Print pair trade ideas to terminal."""
    if not pairs:
        print("\n  No pair trades found.")
        return

    print(f"\n{'='*110}")
    print(f"  RELATIVE VALUE PAIR TRADES -- Top {len(pairs)}")
    print(f"{'='*110}")

    for i, p in enumerate(pairs, 1):
        print(f"\n  Pair #{i}  (composite diff: {p.composite_diff:+.2f})")
        print(f"    CHEAP (buy prot): {p.cheap_name[:35]:<37} "
              f"{p.cheap_spread:>7.0f}bp  score={p.cheap_score:+.2f}")
        print(f"    RICH (sell prot): {p.rich_name[:35]:<37} "
              f"{p.rich_spread:>7.0f}bp  score={p.rich_score:+.2f}")
        print(f"    Sector: {p.sector}  |  Spread diff: {p.spread_diff:+.0f}bp")
        print(f"    {p.rationale}")

    print(f"\n{'='*110}")


def print_sector_summary(names: list[NameData]):
    """Print sector-level summary statistics."""
    sectors: dict[str, list[NameData]] = {}
    for n in names:
        sectors.setdefault(n.sector, []).append(n)

    print(f"\n{'='*90}")
    print(f"  SECTOR RELATIVE VALUE SUMMARY")
    print(f"{'='*90}")
    print(f"\n  {'Sector':<22} {'#':>3} {'Median':>8} {'Mean':>8} {'Stdev':>8} "
          f"{'Cheapest':<25} {'Richest':<25}")
    print(f"  {'-'*22} {'-'*3} {'-'*8} {'-'*8} {'-'*8} {'-'*25} {'-'*25}")

    for sector in sorted(sectors.keys()):
        sn = sectors[sector]
        spreads = [n.current_spread for n in sn]
        cheapest = max(sn, key=lambda n: n.composite_score)
        richest = min(sn, key=lambda n: n.composite_score)
        sd = stdev(spreads) if len(spreads) > 1 else 0

        print(f"  {sector:<22} {len(sn):>3} {median(spreads):>8.0f} "
              f"{mean(spreads):>8.0f} {sd:>8.0f} "
              f"{cheapest.entity_name[:23]:<25} "
              f"{richest.entity_name[:23]:<25}")

    print(f"\n{'='*90}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Rich/Cheap Relative Value Screener -- iTraxx Xover"
    )
    parser.add_argument(
        "--screen-file", type=str, default=None,
        help="Path to specific xover screen Excel",
    )
    parser.add_argument(
        "--top", type=int, default=0,
        help="Show only top N cheapest + richest (default: all)",
    )
    parser.add_argument(
        "--sector", type=str, default=None,
        help="Filter by sector name (partial match)",
    )
    parser.add_argument(
        "--entity", type=str, default=None,
        help="Filter by entity name (partial match)",
    )
    parser.add_argument(
        "--pairs", action="store_true",
        help="Show pair trade ideas",
    )
    parser.add_argument(
        "--excel", action="store_true",
        help="Export to Excel workbook",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Show sector summary only",
    )
    args = parser.parse_args()

    names, pairs = run_full_analysis(args.screen_file)
    if not names:
        sys.exit(1)

    print(f"Loaded {len(names)} names from screen")

    if args.summary:
        print_sector_summary(names)
        return

    if args.pairs:
        print_pairs(pairs)
        return

    if args.excel:
        filepath = export_to_excel(names, pairs)
        print(f"Excel exported: {filepath}")

    print_universe(names, top_n=args.top, sector_filter=args.sector,
                   entity_filter=args.entity)
    print_sector_summary(names)

    if not args.top and not args.sector and not args.entity:
        print_pairs(pairs[:5])


if __name__ == "__main__":
    main()

"""
Macro Scenario Stress Tester -- 8 Scenarios for iTraxx Xover Portfolio

Calculates portfolio P&L under 8 differentiated macro stress scenarios,
each with sector/rating/name-specific spread moves (not just parallel bumps).

Scenarios:
    1. ECB cuts 50bp         -- Risk-on rally, spreads tighten 30-50bp
    2. ECB hikes 25bp        -- Hawkish surprise, spreads widen 20-40bp
    3. European recession    -- Deep widening 100-200bp, CCC names gap wider
    4. China credit crisis   -- Contagion, all widen 50-100bp
    5. Sovereign stress      -- Italy/France turmoil, periphery names wider
    6. LME wave              -- Weakest covenants restructure, gap 300-500bp
    7. Fallen angel cascade  -- BBB downgrades flood HY, Xover +50bp
    8. Risk-on squeeze       -- Short squeeze, tight names rally 40-60bp

Each scenario applies non-uniform spread shocks by rating bucket, sector,
and individual name characteristics. The CDS pricer computes exact P&L
(not DV01 approximations) by re-pricing each position at stressed spreads.

Usage:
    python -m analytics.scenario_analysis                # All 8 scenarios
    python -m analytics.scenario_analysis --scenario 3   # Single scenario
    python -m analytics.scenario_analysis --detail        # Position-level detail
    python -m analytics.scenario_analysis --excel         # Export to Excel
    python -m analytics.scenario_analysis --json          # JSON output
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from analytics.cds_pricer import (
    cds_dv01,
    spread_to_upfront,
    _risky_annuity,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("outputs/analytics")

# Rating bucket boundaries (spread-implied)
RATING_THRESHOLDS = {
    "IG":  (0, 150),
    "BB":  (150, 300),
    "B":   (300, 500),
    "B-":  (500, 800),
    "CCC": (800, 5000),
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SpreadShock:
    """Spread move for a single position under a scenario."""
    entity_name: str
    direction: str
    notional_m: float
    current_spread: float
    shocked_spread: float
    spread_move_bps: float
    pnl_dollars: float
    pnl_pct_nav: float
    sector: str
    rating: str


@dataclass
class ScenarioResult:
    """Full result for one scenario."""
    scenario_id: int
    name: str
    description: str
    narrative: str
    total_pnl: float
    total_pnl_pct_nav: float
    pnl_by_direction: dict
    pnl_by_sector: dict
    pnl_by_rating: dict
    worst_position: str
    best_position: str
    position_details: list[SpreadShock] = field(default_factory=list)
    hedge_pnl: float = 0.0
    combined_pnl: float = 0.0


# ---------------------------------------------------------------------------
# Data loading (same patterns as risk_report.py)
# ---------------------------------------------------------------------------

def find_latest_portfolio() -> str | None:
    """Find the most recent portfolio JSON."""
    portfolio_dir = Path("outputs/portfolio")
    if not portfolio_dir.exists():
        return None
    candidates = sorted(
        portfolio_dir.glob("portfolio_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def load_portfolio(path: str) -> dict:
    """Load portfolio JSON."""
    with open(path) as f:
        return json.load(f)


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
    """Classify a name into a rating bucket by its spread."""
    if spread < 150:
        return "IG"
    elif spread < 300:
        return "BB"
    elif spread < 500:
        return "B"
    elif spread < 800:
        return "B-"
    else:
        return "CCC"


# ---------------------------------------------------------------------------
# P&L engine -- exact re-pricing, not DV01 approximation
# ---------------------------------------------------------------------------

def compute_position_pnl(
    spread_current: float,
    spread_stressed: float,
    notional: float,
    direction: str,
    recovery: float = 0.40,
    maturity: float = 5.0,
) -> float:
    """Compute exact P&L by re-pricing the CDS at stressed spread.

    P&L = Change in mark-to-market of the CDS position.

    For protection BUYER (SHORT_RISK):
        MtM = (market_spread - contract_spread) * RPV01 * Notional
        If spreads widen, protection becomes more valuable -> profit.

    For protection SELLER (LONG_RISK):
        Opposite sign -- widen = loss.

    We use the change in upfront value as the P&L measure:
        P&L = (upfront_stressed - upfront_current) * notional / 100
    Sign convention: SHORT_RISK profits on widening.
    """
    # Compute upfront PV at current and stressed spreads
    # Using 500bp running coupon (HY convention)
    rpv01_current = _risky_annuity(spread_current, recovery, maturity)
    rpv01_stressed = _risky_annuity(spread_stressed, recovery, maturity)

    # Upfront as % of notional
    coupon = 500.0  # HY standard
    uf_current = (spread_current - coupon) / 10_000 * rpv01_current * 100
    uf_stressed = (spread_stressed - coupon) / 10_000 * rpv01_stressed * 100

    # Change in upfront (in % of notional)
    delta_uf_pct = uf_stressed - uf_current

    # Convert to dollars
    delta_dollars = delta_uf_pct / 100 * notional

    # Sign: protection buyer gains when upfront increases (spreads widen)
    is_prot_buyer = direction == "SHORT_RISK"
    if is_prot_buyer:
        return delta_dollars
    else:
        return -delta_dollars


def compute_index_hedge_pnl(
    hedge: dict,
    index_spread_current: float,
    index_spread_stressed: float,
) -> float:
    """Compute P&L on index hedge position."""
    notional = abs(hedge.get("notional_millions", 0)) * 1_000_000
    direction = hedge.get("direction", "LONG_RISK")

    return compute_position_pnl(
        index_spread_current, index_spread_stressed,
        notional, direction,
    )


# ---------------------------------------------------------------------------
# 8 Macro Scenarios -- spread shock functions
# ---------------------------------------------------------------------------

def _shock_ecb_cuts(spread: float, sector: str, rating: str) -> float:
    """Scenario 1: ECB cuts 50bp -- risk-on rally.

    - IG-like names tighten 30bp
    - BB names tighten 40bp
    - B names tighten 35bp
    - CCC names tighten 50bp (distressed relief rally)
    - Consumers/TMT slightly more (beneficiaries)
    """
    base = {
        "IG": -30, "BB": -40, "B": -35, "B-": -45, "CCC": -50,
    }.get(rating, -35)

    # Sector overlay
    if sector in ("Consumers", "TMT"):
        base -= 5  # More rate-sensitive
    elif sector == "Energy":
        base += 5  # Less benefit

    return max(spread + base, 5)  # Floor at 5bp


def _shock_ecb_hikes(spread: float, sector: str, rating: str) -> float:
    """Scenario 2: ECB hikes 25bp -- hawkish surprise.

    - IG-like names widen 20bp (modest)
    - BB names widen 25bp
    - B names widen 30bp
    - CCC names widen 40bp (funding cost pressure)
    - Leveraged sectors (Autos) wider
    """
    base = {
        "IG": 20, "BB": 25, "B": 30, "B-": 35, "CCC": 40,
    }.get(rating, 25)

    if sector == "Autos & Industrials":
        base += 10
    elif sector == "Financials":
        base += 5

    return spread + base


def _shock_european_recession(spread: float, sector: str, rating: str) -> float:
    """Scenario 3: European recession -- deep widening.

    - IG names widen 100bp
    - BB names widen 150bp
    - B names widen 175bp
    - CCC names widen 250bp+ (gap wider)
    - Consumer discretionary and Autos hardest hit
    """
    base = {
        "IG": 100, "BB": 150, "B": 175, "B-": 225, "CCC": 250,
    }.get(rating, 150)

    if sector == "Consumers":
        base = int(base * 1.20)  # 20% extra widening
    elif sector == "Autos & Industrials":
        base = int(base * 1.15)
    elif sector == "Energy":
        base = int(base * 0.90)  # Slightly defensive

    return spread + base


def _shock_china_crisis(spread: float, sector: str, rating: str) -> float:
    """Scenario 4: China credit crisis -- contagion.

    - Uniform 50-100bp widening based on China exposure
    - Autos & Industrials widest (supply chain)
    - Consumers moderate
    - TMT/Financials least affected
    """
    base = {
        "IG": 50, "BB": 60, "B": 75, "B-": 85, "CCC": 100,
    }.get(rating, 60)

    if sector == "Autos & Industrials":
        base = int(base * 1.40)  # Heavy China exposure
    elif sector == "Consumers":
        base = int(base * 1.10)
    elif sector == "TMT":
        base = int(base * 0.85)

    return spread + base


def _shock_sovereign_stress(spread: float, sector: str, rating: str, entity: str) -> float:
    """Scenario 5: Sovereign stress (Italy/France) -- periphery names wider.

    - Base widening 75bp across all European credits
    - Financials widest (sovereign-bank nexus)
    - Names with Italy/France exposure extra +30bp
    - CCC names catch bid as flight-to-quality reverses
    """
    base = {
        "IG": 50, "BB": 75, "B": 85, "B-": 100, "CCC": 75,
    }.get(rating, 75)

    if sector == "Financials":
        base = int(base * 1.50)

    # Periphery-exposed names get extra widening
    periphery_names = {
        "Eutelsat SA", "Worldline SA/France", "Cirsa Finance International Sarl",
    }
    if entity in periphery_names:
        base += 30

    return spread + base


def _shock_lme_wave(spread: float, sector: str, rating: str, entity: str) -> float:
    """Scenario 6: LME wave -- 5 weakest covenant names restructure.

    - Distressed names (CCC) gap 300-500bp
    - B names widen 50bp on contagion fear
    - BB names widen 25bp
    - IG-like names tighten (flight to quality within HY)
    - Specific names identified as LME candidates
    """
    # Names most likely to undergo distressed exchange
    lme_candidates = {
        "INEOS Quattro Finance 2 Plc": 400,
        "Worldline SA/France": 350,
        "INEOS Finance PLC": 300,
        "Sherwood Financing PLC": 250,
    }

    if entity in lme_candidates:
        return spread + lme_candidates[entity]

    base = {
        "IG": -10,  # Flight to quality within HY
        "BB": 25,
        "B": 50,
        "B-": 75,
        "CCC": 200,
    }.get(rating, 30)

    return max(spread + base, 5)


def _shock_fallen_angel_cascade(spread: float, sector: str, rating: str) -> float:
    """Scenario 7: Fallen angel cascade -- 3 BBB names downgraded to HY.

    - New supply crushes Xover spreads +50bp base
    - BB names widen 60bp (most impacted by new entrants)
    - B names widen 45bp
    - CCC names widen 30bp (less impacted)
    - IG-like names widen 40bp (potential next to fall)
    """
    base = {
        "IG": 40, "BB": 60, "B": 45, "B-": 40, "CCC": 30,
    }.get(rating, 50)

    return spread + base


def _shock_risk_on_squeeze(spread: float, sector: str, rating: str) -> float:
    """Scenario 8: Risk-on squeeze -- shorts get squeezed.

    - Tight names rally 40-60bp (SHORT_RISK pain)
    - BB names tighten 50bp (most liquid, most shorted)
    - B names tighten 40bp
    - CCC names tighten 60bp (distressed rally)
    - TMT and Consumers tightest (highest short interest)
    """
    base = {
        "IG": -40, "BB": -50, "B": -40, "B-": -50, "CCC": -60,
    }.get(rating, -45)

    if sector in ("TMT", "Consumers"):
        base -= 10  # Extra squeeze
    elif sector == "Energy":
        base += 5  # Less short interest

    return max(spread + base, 5)  # Floor at 5bp


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS = {
    1: {
        "name": "ECB Cuts 50bp",
        "description": "Risk-on rally, spreads tighten 30-50bp across the board",
        "narrative": (
            "Unexpected 50bp ECB rate cut triggers a broad credit rally. "
            "Investment-grade proxies tighten 30bp, BB names 40bp, while "
            "CCC distressed names rally hardest at 50bp as refinancing "
            "costs fall and default risk recedes. Consumer and TMT sectors "
            "benefit most from lower rates."
        ),
        "shock_fn": _shock_ecb_cuts,
        "index_move": -40,  # Index tightens ~40bp
        "named": False,
    },
    2: {
        "name": "ECB Hikes 25bp",
        "description": "Hawkish surprise, spreads widen 20-40bp",
        "narrative": (
            "Surprise 25bp ECB hike on persistent inflation. Leveraged "
            "names widen 30-40bp on higher funding costs. CCC names hit "
            "hardest as debt service burden increases. Autos & Industrials "
            "sector widest due to capex sensitivity."
        ),
        "shock_fn": _shock_ecb_hikes,
        "index_move": 25,
        "named": False,
    },
    3: {
        "name": "European Recession",
        "description": "Deep widening 100-200bp, CCC names gap wider",
        "narrative": (
            "Two consecutive quarters of negative GDP trigger a full "
            "credit selloff. BB names widen 150bp, CCC names gap 250bp "
            "as default expectations spike. Consumer discretionary and "
            "Autos & Industrials hardest hit. Distressed names approach "
            "recovery value floors."
        ),
        "shock_fn": _shock_european_recession,
        "index_move": 150,
        "named": False,
    },
    4: {
        "name": "China Credit Crisis",
        "description": "Contagion, all spreads widen 50-100bp",
        "narrative": (
            "Major Chinese property developer default cascades through "
            "global credit markets. European HY widens 50-100bp on risk "
            "aversion and supply chain disruption fears. Autos & Industrials "
            "sector widest due to China revenue exposure (40% extra widening)."
        ),
        "shock_fn": _shock_china_crisis,
        "index_move": 65,
        "named": False,
    },
    5: {
        "name": "Sovereign Stress (Italy/France)",
        "description": "European spreads widen 75bp, periphery names wider",
        "narrative": (
            "Fiscal crisis in Italy and political instability in France "
            "widen all European credit 50-100bp. Financial sector widest "
            "(50% extra) on sovereign-bank nexus. France/periphery-exposed "
            "corporates (Eutelsat, Worldline, Cirsa) get additional +30bp. "
            "Flight-to-quality within HY limits CCC widening."
        ),
        "shock_fn": _shock_sovereign_stress,
        "index_move": 75,
        "named": True,
    },
    6: {
        "name": "LME Wave",
        "description": "5 weakest covenant names restructure, spreads gap 300-500bp",
        "narrative": (
            "Wave of liability management exercises (LMEs) hits weakest "
            "covenant names. INEOS Quattro gaps +400bp, Worldline +350bp, "
            "INEOS Finance +300bp, Sherwood +250bp as distressed exchanges "
            "announced. Contagion lifts B names 50bp and BB names 25bp, "
            "but IG-like names tighten 10bp on flight to quality."
        ),
        "shock_fn": _shock_lme_wave,
        "index_move": 35,  # Moderate impact on index avg
        "named": True,
    },
    7: {
        "name": "Fallen Angel Cascade",
        "description": "3 BBB names downgraded to HY, new supply crushes Xover +50bp",
        "narrative": (
            "Three large BBB issuers (auto, telecom, utility) downgraded "
            "to HY simultaneously. Massive new supply floods Xover index, "
            "widening BB names 60bp (most impacted by new entrants). "
            "IG-like names widen 40bp as market fears they are next. "
            "CCC names relatively sheltered at +30bp."
        ),
        "shock_fn": _shock_fallen_angel_cascade,
        "index_move": 50,
        "named": False,
    },
    8: {
        "name": "Risk-On Squeeze",
        "description": "Short squeeze, tight names rally 40-60bp",
        "narrative": (
            "Macro catalyst (peace deal, trade resolution) triggers forced "
            "short covering. BB names tighten 50bp as most-shorted credits "
            "rally. CCC distressed names tighten 60bp on recovery hopes. "
            "TMT and Consumer sectors tightest due to crowded short positioning. "
            "Net short portfolios suffer mark-to-market losses."
        ),
        "shock_fn": _shock_risk_on_squeeze,
        "index_move": -50,
        "named": False,
    },
}


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

def run_scenario(
    scenario_id: int,
    positions_raw: list[dict],
    hedges: list[dict],
    nav_millions: float,
    sector_mapping: dict[str, str],
) -> ScenarioResult:
    """Run a single scenario across the portfolio.

    Returns a ScenarioResult with position-level detail.
    """
    scenario = SCENARIOS[scenario_id]
    shock_fn = scenario["shock_fn"]
    index_move = scenario["index_move"]
    is_named = scenario["named"]

    # Compute current portfolio-weighted avg spread for index proxy
    total_notional = sum(abs(p.get("notional_millions", 0)) for p in positions_raw)
    weighted_spread = sum(
        abs(p.get("notional_millions", 0)) * p.get("current_spread", 0)
        for p in positions_raw
    )
    avg_spread = weighted_spread / total_notional if total_notional > 0 else 350.0

    # Estimate current index spread from avg (or use ~253bp from screen)
    index_spread_current = avg_spread * 0.65  # Index avg < portfolio avg
    index_spread_current = max(index_spread_current, 200)  # Floor
    index_spread_stressed = index_spread_current + index_move

    nav = nav_millions * 1_000_000
    details = []
    total_pnl = 0.0
    pnl_by_direction = {"LONG_RISK": 0.0, "SHORT_RISK": 0.0}
    pnl_by_sector = {}
    pnl_by_rating = {}

    for p in positions_raw:
        entity = p.get("entity_name", "Unknown")
        direction = p.get("direction", "LONG_RISK")
        notional_m = abs(p.get("notional_millions", 0))
        notional = notional_m * 1_000_000
        spread = p.get("current_spread", 0)
        sector = p.get("sector") or sector_mapping.get(entity, "Other")
        rating_raw = p.get("estimated_rating", "")
        rating = classify_rating(spread)

        if spread <= 0 or notional <= 0:
            continue

        # Apply scenario shock
        if is_named:
            shocked = shock_fn(spread, sector, rating, entity)
        else:
            shocked = shock_fn(spread, sector, rating)

        move = shocked - spread

        # Exact re-pricing P&L
        pnl = compute_position_pnl(
            spread, shocked, notional, direction,
        )

        pnl_pct = pnl / nav * 100 if nav > 0 else 0

        details.append(SpreadShock(
            entity_name=entity,
            direction=direction,
            notional_m=notional_m,
            current_spread=spread,
            shocked_spread=shocked,
            spread_move_bps=move,
            pnl_dollars=pnl,
            pnl_pct_nav=pnl_pct,
            sector=sector,
            rating=rating_raw or rating,
        ))

        total_pnl += pnl
        pnl_by_direction[direction] = pnl_by_direction.get(direction, 0) + pnl

        sec_key = sector or "Other"
        pnl_by_sector[sec_key] = pnl_by_sector.get(sec_key, 0) + pnl

        rat_key = rating_raw or rating
        pnl_by_rating[rat_key] = pnl_by_rating.get(rat_key, 0) + pnl

    # Hedge P&L
    hedge_pnl = 0.0
    for h in hedges:
        instrument = h.get("instrument", "")
        if "index" in instrument.lower() or "xover" in instrument.lower():
            hp = compute_index_hedge_pnl(
                h, index_spread_current, index_spread_stressed,
            )
            hedge_pnl += hp
        elif "tranche" in instrument.lower():
            # Tranche P&L: approximate using index move * tranche delta
            # Mezzanine tranche delta ~ 3-5x for 3-7% tranche
            tranche_notional = abs(h.get("notional_millions", 0)) * 1_000_000
            tranche_direction = h.get("direction", "SHORT_RISK")
            # Approximate: use 3x leverage for mezzanine
            effective_move = index_move * 3.0
            approx_shocked = max(index_spread_current + effective_move, 5)
            hp = compute_position_pnl(
                index_spread_current, approx_shocked,
                tranche_notional, tranche_direction,
            )
            hedge_pnl += hp

    combined = total_pnl + hedge_pnl

    # Best and worst positions
    if details:
        worst = min(details, key=lambda d: d.pnl_dollars)
        best = max(details, key=lambda d: d.pnl_dollars)
    else:
        worst = best = None

    return ScenarioResult(
        scenario_id=scenario_id,
        name=scenario["name"],
        description=scenario["description"],
        narrative=scenario["narrative"],
        total_pnl=total_pnl,
        total_pnl_pct_nav=total_pnl / nav * 100 if nav > 0 else 0,
        pnl_by_direction=pnl_by_direction,
        pnl_by_sector=pnl_by_sector,
        pnl_by_rating=pnl_by_rating,
        worst_position=f"{worst.entity_name} (${worst.pnl_dollars/1000:+,.0f}k)" if worst else "N/A",
        best_position=f"{best.entity_name} (${best.pnl_dollars/1000:+,.0f}k)" if best else "N/A",
        position_details=details,
        hedge_pnl=hedge_pnl,
        combined_pnl=combined,
    )


def run_all_scenarios(
    portfolio: dict,
    sector_mapping: dict[str, str],
    scenario_ids: list[int] | None = None,
) -> list[ScenarioResult]:
    """Run all (or selected) scenarios."""
    nav_m = portfolio.get("nav_millions", 500.0)
    positions = portfolio.get("top_positions", [])
    hedges = portfolio.get("hedges", [])

    # Enrich sectors
    for p in positions:
        if not p.get("sector"):
            p["sector"] = sector_mapping.get(p.get("entity_name", ""), "Other")

    ids = scenario_ids or list(SCENARIOS.keys())
    results = []
    for sid in ids:
        if sid in SCENARIOS:
            result = run_scenario(sid, positions, hedges, nav_m, sector_mapping)
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def print_summary(results: list[ScenarioResult], nav_millions: float):
    """Print scenario summary table."""
    print(f"\n{'='*100}")
    print(f"  MACRO SCENARIO STRESS TEST -- iTraxx Xover Portfolio")
    print(f"  NAV: ${nav_millions:.0f}M | {len(results)} scenarios | {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*100}")

    # Summary table
    print(f"\n  {'#':>2}  {'Scenario':<28} {'Portfolio':>12} {'Hedges':>12} "
          f"{'Combined':>12} {'% NAV':>8}  {'Worst Position':<30}")
    print(f"  {'-'*2}  {'-'*28} {'-'*12} {'-'*12} {'-'*12} {'-'*8}  {'-'*30}")

    for r in results:
        combined_pct = r.combined_pnl / (nav_millions * 1_000_000) * 100 if nav_millions > 0 else 0
        print(f"  {r.scenario_id:>2}  {r.name:<28} "
              f"${r.total_pnl/1000:>+10,.0f}k "
              f"${r.hedge_pnl/1000:>+10,.0f}k "
              f"${r.combined_pnl/1000:>+10,.0f}k "
              f"{combined_pct:>+7.2f}%  "
              f"{r.worst_position[:30]}")

    # Directional breakdown
    print(f"\n  {'-'*100}")
    print(f"  DIRECTION BREAKDOWN:")
    print(f"  {'#':>2}  {'Scenario':<28} {'Long P&L':>14} {'Short P&L':>14} {'Net':>14}")
    print(f"  {'-'*2}  {'-'*28} {'-'*14} {'-'*14} {'-'*14}")

    for r in results:
        long_pnl = r.pnl_by_direction.get("LONG_RISK", 0)
        short_pnl = r.pnl_by_direction.get("SHORT_RISK", 0)
        print(f"  {r.scenario_id:>2}  {r.name:<28} "
              f"${long_pnl/1000:>+12,.0f}k "
              f"${short_pnl/1000:>+12,.0f}k "
              f"${r.total_pnl/1000:>+12,.0f}k")

    # Sector breakdown
    all_sectors = set()
    for r in results:
        all_sectors.update(r.pnl_by_sector.keys())
    sectors = sorted(all_sectors)

    if sectors:
        print(f"\n  {'-'*100}")
        print(f"  SECTOR P&L HEATMAP:")
        header = f"  {'Scenario':<28}"
        for s in sectors:
            header += f"  {s[:12]:>12}"
        print(header)
        print(f"  {'-'*28}  " + "  ".join(["-" * 12] * len(sectors)))

        for r in results:
            row = f"  {r.name:<28}"
            for s in sectors:
                val = r.pnl_by_sector.get(s, 0)
                row += f"  ${val/1000:>+10,.0f}k"
            print(row)

    # Risk metrics
    print(f"\n  {'-'*100}")
    print(f"  RISK METRICS:")
    worst_scenario = min(results, key=lambda r: r.combined_pnl)
    best_scenario = max(results, key=lambda r: r.combined_pnl)
    avg_pnl = sum(r.combined_pnl for r in results) / len(results) if results else 0

    nav = nav_millions * 1_000_000
    print(f"  Worst scenario:    #{worst_scenario.scenario_id} {worst_scenario.name} "
          f"(${worst_scenario.combined_pnl/1000:+,.0f}k / "
          f"{worst_scenario.combined_pnl/nav*100:+.2f}% NAV)")
    print(f"  Best scenario:     #{best_scenario.scenario_id} {best_scenario.name} "
          f"(${best_scenario.combined_pnl/1000:+,.0f}k / "
          f"{best_scenario.combined_pnl/nav*100:+.2f}% NAV)")
    print(f"  Average P&L:       ${avg_pnl/1000:+,.0f}k ({avg_pnl/nav*100:+.2f}% NAV)")
    print(f"  Max drawdown:      ${worst_scenario.combined_pnl/1000:+,.0f}k "
          f"({worst_scenario.combined_pnl/nav*100:+.2f}% NAV)")

    # Hedge effectiveness
    total_hedge_contribution = sum(r.hedge_pnl for r in results if r.total_pnl < 0)
    total_loss_scenarios = sum(r.total_pnl for r in results if r.total_pnl < 0)
    if total_loss_scenarios != 0:
        hedge_eff = abs(total_hedge_contribution / total_loss_scenarios) * 100
        print(f"  Hedge effectiveness: {hedge_eff:.0f}% of losses offset")

    print(f"\n{'='*100}")


def print_detail(results: list[ScenarioResult]):
    """Print position-level detail for each scenario."""
    for r in results:
        print(f"\n{'='*100}")
        print(f"  SCENARIO {r.scenario_id}: {r.name}")
        print(f"  {r.narrative}")
        print(f"{'='*100}")

        print(f"\n  {'Entity':<32} {'Dir':<12} {'Notl':>6} {'Curr':>7} "
              f"{'Shock':>7} {'Move':>7} {'P&L':>12} {'% NAV':>7}")
        print(f"  {'-'*32} {'-'*12} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*7}")

        for d in sorted(r.position_details, key=lambda x: x.pnl_dollars):
            dir_short = {
                "LONG_RISK": "LONG", "SHORT_RISK": "SHORT",
            }.get(d.direction, d.direction[:8])
            print(f"  {d.entity_name[:32]:<32} {dir_short:<12} "
                  f"{d.notional_m:>5.1f}M "
                  f"{d.current_spread:>6.0f}bp "
                  f"{d.shocked_spread:>6.0f}bp "
                  f"{d.spread_move_bps:>+6.0f}bp "
                  f"${d.pnl_dollars/1000:>+10,.1f}k "
                  f"{d.pnl_pct_nav:>+6.2f}%")

        print(f"\n  Portfolio P&L: ${r.total_pnl/1000:>+,.0f}k | "
              f"Hedge P&L: ${r.hedge_pnl/1000:>+,.0f}k | "
              f"Combined: ${r.combined_pnl/1000:>+,.0f}k")


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

# Styles
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
_HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
_SECTION_FONT = Font(bold=True, size=12, color="1F4E79")
_GREEN_FILL = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")
_RED_FILL = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
_AMBER_FILL = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
_THIN_BORDER = Border(bottom=Side(style="thin", color="CCCCCC"))


def _apply_header(ws, row, headers, col_start=1):
    """Apply styled headers."""
    for col, h in enumerate(headers, col_start):
        cell = ws.cell(row=row, column=col, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def export_to_excel(results: list[ScenarioResult], nav_millions: float) -> str:
    """Export scenario results to styled Excel workbook."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    filepath = OUTPUT_DIR / f"scenario_analysis_{today}.xlsx"

    wb = Workbook()
    nav = nav_millions * 1_000_000

    # Sheet 1: Scenario Summary
    ws1 = wb.active
    ws1.title = "Scenario Summary"

    ws1.cell(row=1, column=1, value="Macro Scenario Stress Test").font = _SECTION_FONT
    ws1.cell(row=2, column=1, value=f"NAV: ${nav_millions:.0f}M | Date: {datetime.now().strftime('%Y-%m-%d')}")

    headers = [
        "#", "Scenario", "Description", "Portfolio P&L", "Hedge P&L",
        "Combined P&L", "% NAV", "Worst Position", "Best Position",
    ]
    _apply_header(ws1, 4, headers)

    for i, r in enumerate(results, 5):
        combined_pct = r.combined_pnl / nav * 100 if nav > 0 else 0
        row_data = [
            r.scenario_id, r.name, r.description,
            r.total_pnl, r.hedge_pnl, r.combined_pnl,
            combined_pct / 100,  # As decimal for % format
            r.worst_position, r.best_position,
        ]
        for col, val in enumerate(row_data, 1):
            cell = ws1.cell(row=i, column=col, value=val)
            cell.border = _THIN_BORDER
            if col in (4, 5, 6):
                cell.number_format = '#,##0'
                if isinstance(val, (int, float)):
                    cell.fill = _GREEN_FILL if val > 0 else _RED_FILL if val < 0 else _AMBER_FILL
            elif col == 7:
                cell.number_format = '0.00%'
                if isinstance(val, (int, float)):
                    cell.fill = _GREEN_FILL if val > 0 else _RED_FILL if val < 0 else _AMBER_FILL

    # Column widths
    widths = [4, 28, 50, 14, 14, 14, 10, 35, 35]
    for idx, w in enumerate(widths, 1):
        ws1.column_dimensions[get_column_letter(idx)].width = w

    # Sheet 2: Position Detail (one section per scenario)
    ws2 = wb.create_sheet("Position Detail")
    current_row = 1

    for r in results:
        ws2.cell(row=current_row, column=1,
                 value=f"Scenario {r.scenario_id}: {r.name}").font = _SECTION_FONT
        current_row += 1

        headers = [
            "Entity", "Direction", "Notional ($M)", "Current (bp)",
            "Shocked (bp)", "Move (bp)", "P&L ($)", "% NAV",
        ]
        _apply_header(ws2, current_row, headers)
        current_row += 1

        for d in sorted(r.position_details, key=lambda x: x.pnl_dollars):
            ws2.cell(row=current_row, column=1, value=d.entity_name)
            ws2.cell(row=current_row, column=2, value=d.direction)
            ws2.cell(row=current_row, column=3, value=d.notional_m).number_format = '#,##0.0'
            ws2.cell(row=current_row, column=4, value=d.current_spread).number_format = '#,##0'
            ws2.cell(row=current_row, column=5, value=d.shocked_spread).number_format = '#,##0'
            ws2.cell(row=current_row, column=6, value=d.spread_move_bps).number_format = '+#,##0;-#,##0'
            pnl_cell = ws2.cell(row=current_row, column=7, value=d.pnl_dollars)
            pnl_cell.number_format = '#,##0'
            pnl_cell.fill = _GREEN_FILL if d.pnl_dollars > 0 else _RED_FILL
            ws2.cell(row=current_row, column=8, value=d.pnl_pct_nav / 100).number_format = '0.00%'
            current_row += 1

        # Totals row
        ws2.cell(row=current_row, column=1, value="TOTAL").font = Font(bold=True)
        ws2.cell(row=current_row, column=7, value=r.total_pnl).font = Font(bold=True)
        ws2.cell(row=current_row, column=7).number_format = '#,##0'
        current_row += 2

    ws2_widths = [35, 12, 12, 10, 10, 10, 14, 10]
    for idx, w in enumerate(ws2_widths, 1):
        ws2.column_dimensions[get_column_letter(idx)].width = w

    # Sheet 3: Sector Heatmap
    ws3 = wb.create_sheet("Sector Heatmap")

    all_sectors = sorted(set(
        s for r in results for s in r.pnl_by_sector.keys()
    ))

    ws3.cell(row=1, column=1, value="Sector P&L Heatmap ($)").font = _SECTION_FONT
    headers = ["Scenario"] + all_sectors
    _apply_header(ws3, 3, headers)

    for i, r in enumerate(results, 4):
        ws3.cell(row=i, column=1, value=r.name)
        for j, s in enumerate(all_sectors, 2):
            val = r.pnl_by_sector.get(s, 0)
            cell = ws3.cell(row=i, column=j, value=val)
            cell.number_format = '#,##0'
            if val > 0:
                cell.fill = _GREEN_FILL
            elif val < 0:
                cell.fill = _RED_FILL

    ws3_widths = [28] + [14] * len(all_sectors)
    for idx, w in enumerate(ws3_widths, 1):
        ws3.column_dimensions[get_column_letter(idx)].width = w

    wb.save(str(filepath))
    return str(filepath)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def results_to_json(results: list[ScenarioResult]) -> str:
    """Convert results to JSON string."""
    output = []
    for r in results:
        d = {
            "scenario_id": r.scenario_id,
            "name": r.name,
            "description": r.description,
            "narrative": r.narrative,
            "total_pnl": round(r.total_pnl, 2),
            "total_pnl_pct_nav": round(r.total_pnl_pct_nav, 4),
            "hedge_pnl": round(r.hedge_pnl, 2),
            "combined_pnl": round(r.combined_pnl, 2),
            "pnl_by_direction": {
                k: round(v, 2) for k, v in r.pnl_by_direction.items()
            },
            "pnl_by_sector": {
                k: round(v, 2) for k, v in r.pnl_by_sector.items()
            },
            "pnl_by_rating": {
                k: round(v, 2) for k, v in r.pnl_by_rating.items()
            },
            "worst_position": r.worst_position,
            "best_position": r.best_position,
            "positions": [
                {
                    "entity": d.entity_name,
                    "direction": d.direction,
                    "current_spread": d.current_spread,
                    "shocked_spread": round(d.shocked_spread, 1),
                    "move_bps": round(d.spread_move_bps, 1),
                    "pnl": round(d.pnl_dollars, 2),
                    "pnl_pct_nav": round(d.pnl_pct_nav, 4),
                }
                for d in r.position_details
            ],
        }
        output.append(d)
    return json.dumps(output, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Macro Scenario Stress Tester -- 8 Scenarios"
    )
    parser.add_argument(
        "--portfolio", type=str, default=None,
        help="Specific portfolio JSON file",
    )
    parser.add_argument(
        "--scenario", type=int, default=None,
        help="Run a specific scenario (1-8)",
    )
    parser.add_argument(
        "--detail", action="store_true",
        help="Show position-level detail",
    )
    parser.add_argument(
        "--excel", action="store_true",
        help="Export to Excel workbook",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available scenarios",
    )
    args = parser.parse_args()

    # List scenarios
    if args.list:
        print(f"\n{'='*70}")
        print(f"  AVAILABLE SCENARIOS")
        print(f"{'='*70}")
        for sid, s in SCENARIOS.items():
            print(f"  {sid}. {s['name']:<28} {s['description']}")
        print(f"{'='*70}")
        return

    # Load portfolio
    portfolio_path = args.portfolio or find_latest_portfolio()
    if not portfolio_path or not os.path.exists(portfolio_path):
        print("Error: No portfolio file found. Run the strategist first.",
              file=sys.stderr)
        sys.exit(1)

    portfolio = load_portfolio(portfolio_path)
    nav_m = portfolio.get("nav_millions", 500.0)
    sector_mapping = load_sector_mapping()

    print(f"Portfolio: {portfolio_path}")
    print(f"NAV: ${nav_m:.0f}M | Positions: {len(portfolio.get('top_positions', []))}")

    # Select scenarios
    scenario_ids = [args.scenario] if args.scenario else None

    # Run
    results = run_all_scenarios(portfolio, sector_mapping, scenario_ids)

    if args.json:
        print(results_to_json(results))
        return

    # Print results
    print_summary(results, nav_m)

    if args.detail:
        print_detail(results)

    if args.excel:
        path = export_to_excel(results, nav_m)
        print(f"\nExcel report saved: {path}")


if __name__ == "__main__":
    main()

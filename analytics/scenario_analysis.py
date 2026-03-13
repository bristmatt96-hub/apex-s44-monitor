"""
Scenario Analysis Engine

Runs portfolio through multiple macro scenarios to assess P&L impact.
Supports 8+ predefined scenarios plus custom scenarios.

Each scenario defines:
- Spread shocks per rating bucket
- Recovery rate assumptions
- Correlation changes
- Index level changes
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class Scenario:
    """A macro scenario definition."""
    name: str
    description: str
    spread_shocks_bps: Dict[str, float]  # rating → spread change
    recovery_change: float = 0.0         # Change to recovery rate
    correlation_change: float = 0.0      # Change to correlation
    probability: float = 0.0            # Subjective scenario probability


@dataclass
class ScenarioResult:
    """P&L result for a single position under a scenario."""
    entity_name: str
    scenario_name: str
    spread_shock_bps: float
    pnl: float
    pnl_pct: float
    new_spread_bps: float


@dataclass
class PortfolioScenarioResult:
    """Portfolio-level scenario result."""
    scenario_name: str
    total_pnl: float
    worst_position: str
    best_position: str
    position_results: List[ScenarioResult] = field(default_factory=list)


# Predefined scenarios
SCENARIOS = [
    Scenario(
        name="Base Case",
        description="No change - current market conditions persist",
        spread_shocks_bps={"IG": 0, "HY": 0, "BB": 0, "B": 0, "CCC": 0},
        probability=0.30,
    ),
    Scenario(
        name="Mild Widening",
        description="Gradual risk-off, EM stress, mild recession fears",
        spread_shocks_bps={"IG": 10, "HY": 30, "BB": 25, "B": 50, "CCC": 100},
        probability=0.20,
    ),
    Scenario(
        name="Sharp Widening",
        description="Credit crisis - sudden repricing of risk",
        spread_shocks_bps={"IG": 40, "HY": 150, "BB": 100, "B": 250, "CCC": 500},
        recovery_change=-0.10,
        correlation_change=0.15,
        probability=0.05,
    ),
    Scenario(
        name="Rally",
        description="Risk-on - ECB easing, improving fundamentals",
        spread_shocks_bps={"IG": -10, "HY": -30, "BB": -25, "B": -40, "CCC": -60},
        probability=0.15,
    ),
    Scenario(
        name="Strong Rally",
        description="Aggressive ECB cuts, fiscal stimulus, M&A wave",
        spread_shocks_bps={"IG": -20, "HY": -60, "BB": -50, "B": -80, "CCC": -100},
        correlation_change=-0.05,
        probability=0.05,
    ),
    Scenario(
        name="Idiosyncratic Stress",
        description="Single-name blowup in HY, contagion to sector",
        spread_shocks_bps={"IG": 5, "HY": 50, "BB": 40, "B": 100, "CCC": 200},
        correlation_change=0.05,
        probability=0.10,
    ),
    Scenario(
        name="Rate Shock",
        description="Unexpected inflation → ECB hike → credit sells off",
        spread_shocks_bps={"IG": 25, "HY": 75, "BB": 60, "B": 120, "CCC": 200},
        probability=0.05,
    ),
    Scenario(
        name="Fallen Angel Wave",
        description="Multiple IG→HY downgrades force selling",
        spread_shocks_bps={"IG": 15, "HY": 100, "BB": 80, "B": 60, "CCC": 40},
        correlation_change=0.10,
        probability=0.05,
    ),
    Scenario(
        name="Geopolitical Shock",
        description="Major geopolitical event disrupts European markets",
        spread_shocks_bps={"IG": 30, "HY": 100, "BB": 80, "B": 150, "CCC": 300},
        recovery_change=-0.05,
        correlation_change=0.10,
        probability=0.05,
    ),
]


def get_rating_bucket(rating: str) -> str:
    """Map a specific rating to a bucket."""
    rating = rating.upper().replace("+", "").replace("-", "")
    if rating in ("AAA", "AA", "A", "BBB"):
        return "IG"
    elif rating in ("BB",):
        return "BB"
    elif rating in ("B",):
        return "B"
    elif rating in ("CCC", "CC", "C", "D"):
        return "CCC"
    else:
        return "HY"


def run_scenario(
    scenario: Scenario,
    positions: List[Dict],
    dv01_per_position: Dict[str, float] = None,
) -> PortfolioScenarioResult:
    """
    Run a scenario on the portfolio.

    Args:
        scenario: Scenario definition
        positions: List of dicts with keys: entity_name, rating, spread_bps, notional, direction
        dv01_per_position: Optional pre-computed DV01s

    Returns:
        PortfolioScenarioResult
    """
    results = []
    total_pnl = 0.0

    for pos in positions:
        entity = pos["entity_name"]
        rating = pos.get("rating", "HY")
        spread = pos.get("spread_bps", 100.0)
        notional = pos.get("notional", 10_000_000.0)
        direction = pos.get("direction", "flat")

        bucket = get_rating_bucket(rating)
        shock = scenario.spread_shocks_bps.get(bucket, 0.0)

        # Use DV01 if available, otherwise approximate
        if dv01_per_position and entity in dv01_per_position:
            dv01 = dv01_per_position[entity]
        else:
            # Rough approximation: DV01 ≈ notional * 0.0001 * duration
            dv01 = notional * 0.0001 * 4.5  # ~4.5 year duration

        # P&L = shock * DV01 * direction_sign
        if direction == "short":
            # Short protection → lose if spreads widen
            pnl = -shock * dv01
        elif direction == "long":
            # Long protection → gain if spreads widen
            pnl = shock * dv01
        else:
            pnl = 0.0

        pnl_pct = (pnl / notional * 100) if notional > 0 else 0.0

        results.append(ScenarioResult(
            entity_name=entity,
            scenario_name=scenario.name,
            spread_shock_bps=shock,
            pnl=pnl,
            pnl_pct=pnl_pct,
            new_spread_bps=spread + shock,
        ))
        total_pnl += pnl

    # Find best/worst
    if results:
        worst = min(results, key=lambda r: r.pnl)
        best = max(results, key=lambda r: r.pnl)
    else:
        worst = best = None

    return PortfolioScenarioResult(
        scenario_name=scenario.name,
        total_pnl=total_pnl,
        worst_position=worst.entity_name if worst else "",
        best_position=best.entity_name if best else "",
        position_results=results,
    )


def run_all_scenarios(
    positions: List[Dict],
    scenarios: List[Scenario] = None,
    dv01_per_position: Dict[str, float] = None,
) -> List[PortfolioScenarioResult]:
    """Run all predefined scenarios on the portfolio."""
    if scenarios is None:
        scenarios = SCENARIOS

    return [
        run_scenario(s, positions, dv01_per_position)
        for s in scenarios
    ]

"""
Analytics endpoints: relative value, scenarios, risk, fundamentals
"""
import json
from pathlib import Path
from fastapi import APIRouter
from typing import List

from app.api.schemas.models import (
    RVScoreResponse, RVScreenResponse,
    ScenarioResultResponse, ScenarioAnalysisResponse,
    RiskMetricsResponse, FundamentalResponse,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

SNAPSHOTS_DIR = Path("snapshots")


def _load_positions(limit: int = 50) -> list:
    """Load positions from snapshots."""
    positions = []
    for f in sorted(SNAPSHOTS_DIR.glob("*.json"))[:limit]:
        try:
            with open(f) as fh:
                data = json.load(fh)
            spread = data.get("cds_spread_bps", data.get("spread_bps", 0.0))
            if spread > 0:
                positions.append({
                    "entity_name": data.get("company_name", f.stem),
                    "rating": data.get("ratings", {}).get("composite", "B"),
                    "spread_bps": spread,
                    "notional": 10_000_000.0,
                    "direction": data.get("direction", "flat"),
                    "sector": data.get("sector", ""),
                    "fair_spread_bps": data.get("fair_spread_bps", spread * 0.95),
                })
        except Exception:
            continue
    return positions


# ── Relative Value ───────────────────────────────────────────────

@router.get("/rv", response_model=RVScreenResponse)
async def relative_value_screen():
    """Run relative value screen across the universe."""
    from analytics.relative_value import compute_rv_score, rank_universe

    positions = _load_positions()
    scores = []
    for p in positions:
        score = compute_rv_score(
            current_spread_bps=p["spread_bps"],
            fair_spread_bps=p["fair_spread_bps"],
            sector=p.get("sector", ""),
            entity_name=p["entity_name"],
        )
        scores.append(score)

    ranked = rank_universe(scores) if scores else []

    return RVScreenResponse(
        count=len(ranked),
        scores=[
            RVScoreResponse(
                entity_name=s.entity_name,
                current_spread_bps=s.current_spread_bps,
                fair_spread_bps=s.fair_spread_bps,
                rv_score=s.rv_score,
                signal=s.signal,
                sector=s.sector,
            )
            for s in ranked
        ],
    )


# ── Scenario Analysis ────────────────────────────────────────────

@router.get("/scenarios", response_model=ScenarioAnalysisResponse)
async def scenario_analysis():
    """Run all predefined scenarios on the current portfolio."""
    from analytics.scenario_analysis import SCENARIOS, run_all_scenarios

    positions = _load_positions(limit=30)
    if not positions:
        return ScenarioAnalysisResponse(
            position_count=0, scenarios=[], weighted_expected_pnl=0.0
        )

    results = run_all_scenarios(positions)

    scenario_responses = []
    for r in results:
        scenario = next((s for s in SCENARIOS if s.name == r.scenario_name), None)
        prob = scenario.probability if scenario else 0.0
        scenario_responses.append(ScenarioResultResponse(
            scenario_name=r.scenario_name,
            probability=prob,
            total_pnl=r.total_pnl,
            worst_position=r.worst_position,
            position_pnls=r.position_pnls if hasattr(r, "position_pnls") else {},
        ))

    weighted = sum(
        r.total_pnl * next((s.probability for s in SCENARIOS if s.name == r.scenario_name), 0)
        for r in results
    )

    return ScenarioAnalysisResponse(
        position_count=len(positions),
        scenarios=scenario_responses,
        weighted_expected_pnl=weighted,
    )


# ── Fundamental ──────────────────────────────────────────────────

@router.get("/fundamental/{name}", response_model=FundamentalResponse)
async def fundamental_analysis(name: str):
    """Run fundamental analysis for a single credit."""
    from analytics.fundamental import CreditFundamentalAnalyzer

    analyzer = CreditFundamentalAnalyzer()
    assessment = analyzer.assess(name)

    return FundamentalResponse(
        entity_name=assessment.entity_name,
        fundamental_score=assessment.fundamental_score,
        playbook=assessment.playbook,
        sponsor=assessment.sponsor,
        sponsor_aggression=assessment.sponsor_aggression,
        maturity_risk=assessment.maturity_risk,
        leverage=assessment.leverage,
        interest_coverage=assessment.interest_coverage,
        reasoning=assessment.reasoning,
        risk_factors=assessment.risk_factors,
    )


@router.get("/fundamental", response_model=List[FundamentalResponse])
async def fundamental_universe():
    """Run fundamental analysis across the full universe."""
    from analytics.fundamental import CreditFundamentalAnalyzer

    analyzer = CreditFundamentalAnalyzer()
    results = analyzer.assess_universe()

    return [
        FundamentalResponse(
            entity_name=a.entity_name,
            fundamental_score=a.fundamental_score,
            playbook=a.playbook,
            sponsor=a.sponsor,
            sponsor_aggression=a.sponsor_aggression,
            maturity_risk=a.maturity_risk,
            leverage=a.leverage,
            interest_coverage=a.interest_coverage,
            reasoning=a.reasoning,
            risk_factors=a.risk_factors,
        )
        for a in results
    ]

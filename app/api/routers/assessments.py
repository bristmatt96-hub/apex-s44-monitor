"""
Credit assessment endpoints
"""
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from typing import List

from app.api.schemas.models import CreditAssessmentResponse, UniverseOverviewResponse

router = APIRouter(prefix="/api/assessments", tags=["assessments"])

SNAPSHOTS_DIR = Path("snapshots")


def _load_snapshot(name: str) -> dict:
    """Find and load a snapshot by company name."""
    name_lower = name.lower()
    for f in SNAPSHOTS_DIR.glob("*.json"):
        if name_lower in f.stem.lower():
            with open(f) as fh:
                return json.load(fh)
    return {}


@router.get("/{name}", response_model=CreditAssessmentResponse)
async def get_assessment(name: str):
    """
    Get credit assessment for a single name.
    Runs the analyst agent synchronously and returns the result.
    """
    from agents.analyst import CreditAnalyst

    analyst = CreditAnalyst()
    analyst.load_knowledge(max_chunks=30)

    try:
        assessment = await analyst.assess_credit(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Assessment failed: {e}")

    return CreditAssessmentResponse(
        entity_name=assessment.entity_name,
        assessment_date=assessment.assessment_date,
        credit_score=assessment.credit_score,
        fair_spread_bps=assessment.fair_spread_bps,
        direction=assessment.direction,
        conviction=assessment.conviction,
        rating=assessment.rating,
        sector=assessment.sector,
        summary=assessment.summary,
        risk_factors=assessment.risk_factors or [],
        catalysts=assessment.catalysts or [],
    )


@router.get("", response_model=UniverseOverviewResponse)
async def get_universe_overview():
    """
    Get overview of all assessed credits.
    Reads from cached snapshots rather than running full assessment.
    """
    assessments = []
    for f in sorted(SNAPSHOTS_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            assessments.append(CreditAssessmentResponse(
                entity_name=data.get("company_name", f.stem),
                assessment_date=data.get("assessment_date", ""),
                credit_score=data.get("credit_score", 50),
                fair_spread_bps=data.get("fair_spread_bps", 0),
                direction=data.get("direction", "flat"),
                conviction=data.get("conviction", 0),
                rating=data.get("ratings", {}).get("composite"),
                sector=data.get("sector"),
                summary=data.get("summary", ""),
                risk_factors=data.get("risk_factors", []),
                catalysts=data.get("catalysts", []),
            ))
        except Exception:
            continue

    longs = sum(1 for a in assessments if a.direction == "long")
    shorts = sum(1 for a in assessments if a.direction == "short")
    flats = len(assessments) - longs - shorts
    avg_score = sum(a.credit_score for a in assessments) / max(len(assessments), 1)

    return UniverseOverviewResponse(
        total_names=len(list(SNAPSHOTS_DIR.glob("*.json"))),
        assessed=len(assessments),
        longs=longs,
        shorts=shorts,
        flats=flats,
        avg_score=avg_score,
        assessments=assessments,
    )

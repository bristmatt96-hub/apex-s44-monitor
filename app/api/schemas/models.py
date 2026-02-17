"""
Pydantic schemas for Credit Catalyst API
"""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class Conviction(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ── Credit Assessment ────────────────────────────────────────────

class CreditAssessmentResponse(BaseModel):
    entity_name: str
    assessment_date: str
    credit_score: float
    fair_spread_bps: float
    direction: str
    conviction: int
    rating: Optional[str] = None
    sector: Optional[str] = None
    summary: str = ""
    risk_factors: List[str] = []
    catalysts: List[str] = []


class UniverseOverviewResponse(BaseModel):
    total_names: int
    assessed: int
    longs: int
    shorts: int
    flats: int
    avg_score: float
    assessments: List[CreditAssessmentResponse] = []


# ── Relative Value ───────────────────────────────────────────────

class RVScoreResponse(BaseModel):
    entity_name: str
    current_spread_bps: float
    fair_spread_bps: float
    rv_score: float
    signal: str   # "RICH", "CHEAP", "FAIR"
    sector: str = ""
    z_score: Optional[float] = None


class RVScreenResponse(BaseModel):
    count: int
    scores: List[RVScoreResponse]


# ── Scenario Analysis ────────────────────────────────────────────

class ScenarioResultResponse(BaseModel):
    scenario_name: str
    probability: float
    total_pnl: float
    worst_position: str
    position_pnls: Dict[str, float] = {}


class ScenarioAnalysisResponse(BaseModel):
    position_count: int
    scenarios: List[ScenarioResultResponse]
    weighted_expected_pnl: float


# ── Risk Metrics ─────────────────────────────────────────────────

class RiskMetricsResponse(BaseModel):
    total_dv01: float
    total_cs01: float
    spread_var_95: float
    spread_var_99: float
    expected_shortfall: float
    jump_to_default_worst: float
    position_count: int


# ── Fundamental ──────────────────────────────────────────────────

class FundamentalResponse(BaseModel):
    entity_name: str
    fundamental_score: float
    playbook: str
    sponsor: Optional[str] = None
    sponsor_aggression: int = 0
    maturity_risk: Optional[str] = None
    leverage: Optional[float] = None
    interest_coverage: Optional[float] = None
    reasoning: str = ""
    risk_factors: List[str] = []


# ── System ───────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str
    components: Dict[str, bool] = {}


class WebSocketMessage(BaseModel):
    event: str
    data: Dict[str, Any]
    timestamp: datetime = None

    def __init__(self, **data):
        if "timestamp" not in data:
            data["timestamp"] = datetime.now()
        super().__init__(**data)

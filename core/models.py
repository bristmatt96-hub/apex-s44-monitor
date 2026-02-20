"""
Core Data Models for Strategies in Credit

These models are consumed by every downstream component:
dashboard, Excel reports, pitch decks, idea sheets, Telegram alerts.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Direction(str, Enum):
    LONG_RISK = "LONG_RISK"
    SHORT_RISK = "SHORT_RISK"
    FLAT = "FLAT"


class ItraxxIndex(str, Enum):
    MAIN = "Main"
    XOVER = "Xover"


class StrategyType(str, Enum):
    RELATIVE_VALUE = "relative_value"
    CATALYST = "catalyst"
    REGIME = "regime"


class TradeOutcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    OPEN = "open"


class CreditAssessment(BaseModel):
    """Output of the Analyst agent for a single name."""

    entity_name: str
    itraxx_index: ItraxxIndex
    current_spread: float
    fair_spread: float
    direction: Direction
    conviction: int = Field(ge=1, le=5)
    raw_conviction: Optional[int] = Field(default=None, ge=1, le=5)
    signal_sources: list[str]
    thesis: str
    catalyst: str
    key_risks: list[str]
    fundamental_metrics: dict
    updated_at: datetime


class TradeIdea(BaseModel):
    """A specific actionable trade recommendation."""

    assessment: CreditAssessment
    instrument: str
    entry_spread: float
    stop_loss_spread: float
    notional: float
    position_size_pct: float
    hedge: Optional[str] = None
    scenario_pnl: dict
    risk_metrics: dict


class RiskSnapshot(BaseModel):
    """Portfolio-level risk at a point in time."""

    timestamp: datetime
    gross_exposure: float
    net_exposure: float
    sector_concentration: dict
    rating_buckets: dict
    spread_duration: float
    top_5_positions: list[dict]
    stress_tests: dict
    current_drawdown: float
    max_drawdown_30d: float
    correlation_matrix: dict


class TradeJournalEntry(BaseModel):
    """Captures every trade for track record and case studies."""

    trade_id: str
    idea: TradeIdea
    entry_date: datetime
    entry_spread: float
    exit_date: Optional[datetime] = None
    exit_spread: Optional[float] = None
    pnl_bps: Optional[float] = None
    pnl_usd: Optional[float] = None
    signal_source: str
    strategy_type: StrategyType
    outcome: Optional[TradeOutcome] = None
    post_mortem: Optional[str] = None

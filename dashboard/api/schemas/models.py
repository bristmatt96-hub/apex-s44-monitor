"""
Pydantic schemas for Dashboard API
"""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class MarketType(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FOREX = "forex"
    OPTIONS = "options"


class PositionResponse(BaseModel):
    """Position data for dashboard"""
    symbol: str
    market_type: str
    quantity: float
    entry_price: float
    current_price: float
    entry_time: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    unrealized_pnl: float
    unrealized_pnl_pct: float
    market_value: float
    reasoning: List[str] = []
    composite_score: Optional[float] = None
    strategy: Optional[str] = None

    class Config:
        from_attributes = True


class PositionDetailResponse(PositionResponse):
    """Position with thesis history for drill-down"""
    thesis_history: List["ThesisEvent"] = []


class ThesisEvent(BaseModel):
    """A point in the thesis evolution timeline"""
    timestamp: datetime
    event_type: str  # 'entry', 'score_update', 'confluence_added', 'stop_adjusted'
    reasoning: List[str]
    composite_score: float
    confidence: float
    notes: Optional[str] = None


class PnLSummary(BaseModel):
    """P&L summary for dashboard"""
    daily_pnl: float
    daily_pnl_pct: float
    ytd_pnl: float
    ytd_pnl_pct: float
    realized_today: float
    unrealized_today: float
    total_positions: int
    winning_positions: int
    losing_positions: int


class OpportunityResponse(BaseModel):
    """Ranked opportunity for dashboard"""
    symbol: str
    market_type: str
    signal_type: str
    composite_score: float
    risk_reward: float
    confidence: float
    entry_price: float
    target_price: float
    stop_loss: float
    rank: int
    reasoning: List[str] = []
    strategy: Optional[str] = None


class SystemStatus(BaseModel):
    """System health status"""
    state: str
    trading_enabled: bool
    auto_execute: bool
    agents_active: int
    signals_raw: int
    signals_analyzed: int
    signals_ranked: int
    positions_count: int
    pending_trades: int


class WebSocketMessage(BaseModel):
    """WebSocket message format"""
    event: str
    data: Dict[str, Any]
    timestamp: datetime = None

    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = datetime.now()
        super().__init__(**data)


# Update forward references
PositionDetailResponse.model_rebuild()

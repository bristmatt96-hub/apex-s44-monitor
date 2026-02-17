"""
P&L endpoints for Dashboard API
"""
from fastapi import APIRouter
from typing import List

from dashboard.api.schemas.models import PnLSummary, OpportunityResponse, SystemStatus
from dashboard.api.services.coordinator_bridge import get_bridge

router = APIRouter(prefix="/api", tags=["pnl"])


@router.get("/pnl", response_model=PnLSummary)
async def get_pnl_summary():
    """
    Get P&L summary.

    Returns:
    - Daily P&L (realized + unrealized)
    - YTD P&L from trade history
    - Position counts (winning/losing)
    """
    bridge = get_bridge()
    return bridge.get_pnl_summary()


@router.get("/opportunities", response_model=List[OpportunityResponse])
async def get_opportunities(limit: int = 10):
    """
    Get top ranked opportunities.

    Returns top N opportunities with:
    - Symbol and market type
    - Composite score and rank
    - Entry, target, stop prices
    - Risk/reward ratio
    - Reasoning
    """
    bridge = get_bridge()
    return bridge.get_opportunities(limit)


@router.get("/status", response_model=SystemStatus)
async def get_system_status():
    """
    Get system health status.

    Returns:
    - System state (running/paused/stopped)
    - Trading enabled flag
    - Agent count
    - Signal pipeline stats
    """
    bridge = get_bridge()
    return bridge.get_system_status()

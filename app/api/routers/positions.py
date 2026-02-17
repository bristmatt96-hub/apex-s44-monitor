"""
Position endpoints for Dashboard API
"""
from fastapi import APIRouter, HTTPException
from typing import List

from dashboard.api.schemas.models import PositionResponse, PositionDetailResponse
from dashboard.api.services.coordinator_bridge import get_bridge

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("", response_model=List[PositionResponse])
async def get_positions():
    """
    Get all open positions with P&L.

    Returns list of positions with:
    - Symbol, quantity, entry/current price
    - Unrealized P&L ($ and %)
    - Stop loss and take profit levels
    - Entry reasoning summary
    """
    bridge = get_bridge()
    return bridge.get_positions()


@router.get("/{symbol}", response_model=PositionDetailResponse)
async def get_position_detail(symbol: str):
    """
    Get detailed position info with thesis evolution.

    Returns position details including:
    - Full position data
    - Thesis timeline showing how reasoning evolved
    - Score changes over time
    """
    bridge = get_bridge()
    position = bridge.get_position_detail(symbol.upper())

    if not position:
        raise HTTPException(status_code=404, detail=f"Position {symbol} not found")

    return position

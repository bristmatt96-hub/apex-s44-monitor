"""
Bridge between Dashboard API and Trading System Coordinator
"""
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from loguru import logger

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from dashboard.api.schemas.models import (
    PositionResponse, PositionDetailResponse, PnLSummary,
    OpportunityResponse, SystemStatus, ThesisEvent
)


class CoordinatorBridge:
    """
    Bridge to access trading system data from the dashboard.

    Can run in two modes:
    1. Connected mode: Links to live Coordinator instance
    2. Standalone mode: Reads from data files (for when trading system isn't running)
    """

    def __init__(self, coordinator=None):
        self.coordinator = coordinator
        self._thesis_cache: Dict[str, List[ThesisEvent]] = {}

        # Try to load trade history for YTD calculations
        self.trade_history_path = project_root / "data" / "trade_history.json"

    def is_connected(self) -> bool:
        """Check if connected to live coordinator"""
        return self.coordinator is not None

    def get_positions(self) -> List[PositionResponse]:
        """Get all open positions with P&L"""
        if not self.coordinator:
            return self._get_mock_positions()

        positions = []
        for symbol, pos in self.coordinator.positions.items():
            # Try to get entry reasoning from the signal that opened this position
            reasoning = []
            score = None
            strategy = None

            # Check if we have thesis data cached
            if symbol in self._thesis_cache and self._thesis_cache[symbol]:
                entry_thesis = self._thesis_cache[symbol][0]
                reasoning = entry_thesis.reasoning
                score = entry_thesis.composite_score

            positions.append(PositionResponse(
                symbol=pos.symbol,
                market_type=pos.market_type.value if hasattr(pos.market_type, 'value') else str(pos.market_type),
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=pos.current_price,
                entry_time=pos.entry_time,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                unrealized_pnl=pos.unrealized_pnl,
                unrealized_pnl_pct=pos.pnl_pct,
                market_value=pos.market_value,
                reasoning=reasoning,
                composite_score=score,
                strategy=strategy
            ))

        return positions

    def get_position_detail(self, symbol: str) -> Optional[PositionDetailResponse]:
        """Get detailed position with thesis history"""
        if not self.coordinator:
            return self._get_mock_position_detail(symbol)

        if symbol not in self.coordinator.positions:
            return None

        pos = self.coordinator.positions[symbol]
        thesis_history = self._thesis_cache.get(symbol, [])

        return PositionDetailResponse(
            symbol=pos.symbol,
            market_type=pos.market_type.value if hasattr(pos.market_type, 'value') else str(pos.market_type),
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            current_price=pos.current_price,
            entry_time=pos.entry_time,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            unrealized_pnl=pos.unrealized_pnl,
            unrealized_pnl_pct=pos.pnl_pct,
            market_value=pos.market_value,
            reasoning=thesis_history[0].reasoning if thesis_history else [],
            composite_score=thesis_history[0].composite_score if thesis_history else None,
            thesis_history=thesis_history
        )

    def get_pnl_summary(self) -> PnLSummary:
        """Get daily and YTD P&L summary"""
        if not self.coordinator:
            return self._get_mock_pnl()

        # Calculate unrealized P&L from open positions
        unrealized = sum(pos.unrealized_pnl for pos in self.coordinator.positions.values())

        # Get realized P&L from today's closed trades
        realized_today = self.coordinator.daily_pnl if hasattr(self.coordinator, 'daily_pnl') else 0.0

        daily_pnl = unrealized + realized_today

        # Calculate YTD from trade history
        ytd_pnl = self._calculate_ytd_pnl()

        # Starting capital for percentage calculations
        starting_capital = 3000.0  # From config

        # Count winning/losing positions
        winning = sum(1 for pos in self.coordinator.positions.values() if pos.unrealized_pnl > 0)
        losing = sum(1 for pos in self.coordinator.positions.values() if pos.unrealized_pnl < 0)

        return PnLSummary(
            daily_pnl=daily_pnl,
            daily_pnl_pct=(daily_pnl / starting_capital) * 100 if starting_capital else 0,
            ytd_pnl=ytd_pnl,
            ytd_pnl_pct=(ytd_pnl / starting_capital) * 100 if starting_capital else 0,
            realized_today=realized_today,
            unrealized_today=unrealized,
            total_positions=len(self.coordinator.positions),
            winning_positions=winning,
            losing_positions=losing
        )

    def get_opportunities(self, limit: int = 10) -> List[OpportunityResponse]:
        """Get top ranked opportunities"""
        if not self.coordinator:
            return self._get_mock_opportunities()

        opportunities = []
        for i, opp in enumerate(self.coordinator.get_top_opportunities(limit)):
            opportunities.append(OpportunityResponse(
                symbol=opp.get('symbol', ''),
                market_type=opp.get('market_type', 'equity'),
                signal_type=opp.get('signal_type', 'buy'),
                composite_score=opp.get('composite_score', 0),
                risk_reward=opp.get('risk_reward', 0),
                confidence=opp.get('confidence', 0),
                entry_price=opp.get('entry_price', 0),
                target_price=opp.get('target_price', 0),
                stop_loss=opp.get('stop_loss', 0),
                rank=i + 1,
                reasoning=opp.get('reasoning', []),
                strategy=opp.get('metadata', {}).get('strategy')
            ))

        return opportunities

    def get_system_status(self) -> SystemStatus:
        """Get system health status"""
        if not self.coordinator:
            return self._get_mock_status()

        status = self.coordinator.get_status()

        return SystemStatus(
            state=status['coordinator']['state'],
            trading_enabled=status['coordinator']['trading_enabled'],
            auto_execute=status['coordinator']['auto_execute'],
            agents_active=len(status['agents']),
            signals_raw=status['signals']['raw'],
            signals_analyzed=status['signals']['analyzed'],
            signals_ranked=status['signals']['ranked'],
            positions_count=status['trading']['positions'],
            pending_trades=status['trading']['pending_executions']
        )

    def record_thesis_entry(self, symbol: str, opportunity: Dict):
        """Record thesis at position entry"""
        event = ThesisEvent(
            timestamp=datetime.now(),
            event_type='entry',
            reasoning=opportunity.get('reasoning', []),
            composite_score=opportunity.get('composite_score', 0),
            confidence=opportunity.get('confidence', 0),
            notes=f"Entry at ${opportunity.get('entry_price', 0):.2f}"
        )

        if symbol not in self._thesis_cache:
            self._thesis_cache[symbol] = []
        self._thesis_cache[symbol].append(event)

        logger.info(f"[ThesisTracker] Recorded entry thesis for {symbol}")

    def record_thesis_update(self, symbol: str, new_score: float, new_reasoning: List[str]):
        """Record thesis update for open position"""
        if symbol not in self._thesis_cache:
            return

        # Only record if score changed significantly
        if self._thesis_cache[symbol]:
            last_score = self._thesis_cache[symbol][-1].composite_score
            if abs(new_score - last_score) < 0.1:
                return

        event = ThesisEvent(
            timestamp=datetime.now(),
            event_type='score_update',
            reasoning=new_reasoning,
            composite_score=new_score,
            confidence=0,
            notes=f"Score changed from {last_score:.2f} to {new_score:.2f}"
        )

        self._thesis_cache[symbol].append(event)
        logger.info(f"[ThesisTracker] Recorded score update for {symbol}: {new_score:.2f}")

    def _calculate_ytd_pnl(self) -> float:
        """Calculate YTD P&L from trade history"""
        import json

        try:
            if self.trade_history_path.exists():
                with open(self.trade_history_path) as f:
                    history = json.load(f)

                current_year = date.today().year
                ytd_pnl = 0.0

                for trade in history:
                    trade_date = datetime.fromisoformat(trade.get('exit_time', trade.get('timestamp', '')))
                    if trade_date.year == current_year:
                        ytd_pnl += trade.get('pnl', 0)

                return ytd_pnl
        except Exception as e:
            logger.warning(f"Could not calculate YTD P&L: {e}")

        return 0.0

    # Mock data methods for standalone/testing
    def _get_mock_positions(self) -> List[PositionResponse]:
        """Return mock positions for testing"""
        return [
            PositionResponse(
                symbol="AAPL",
                market_type="equity",
                quantity=10,
                entry_price=178.25,
                current_price=180.50,
                entry_time=datetime.now(),
                stop_loss=175.00,
                take_profit=190.00,
                unrealized_pnl=22.50,
                unrealized_pnl_pct=1.26,
                market_value=1805.00,
                reasoning=["RSI oversold bounce", "Volume confirmation", "Sector momentum"],
                composite_score=8.2
            ),
            PositionResponse(
                symbol="MSFT",
                market_type="equity",
                quantity=5,
                entry_price=425.00,
                current_price=422.50,
                entry_time=datetime.now(),
                stop_loss=415.00,
                unrealized_pnl=-12.50,
                unrealized_pnl_pct=-0.59,
                market_value=2112.50,
                reasoning=["Breakout pattern", "Strong earnings"],
                composite_score=7.5
            )
        ]

    def _get_mock_position_detail(self, symbol: str) -> Optional[PositionDetailResponse]:
        """Return mock position detail for testing"""
        mock_positions = {p.symbol: p for p in self._get_mock_positions()}
        if symbol not in mock_positions:
            return None

        pos = mock_positions[symbol]
        return PositionDetailResponse(
            **pos.model_dump(),
            thesis_history=[
                ThesisEvent(
                    timestamp=datetime.now(),
                    event_type="entry",
                    reasoning=pos.reasoning,
                    composite_score=pos.composite_score or 8.0,
                    confidence=0.75,
                    notes=f"Entry at ${pos.entry_price:.2f}"
                )
            ]
        )

    def _get_mock_pnl(self) -> PnLSummary:
        """Return mock P&L for testing"""
        return PnLSummary(
            daily_pnl=245.50,
            daily_pnl_pct=2.45,
            ytd_pnl=1832.00,
            ytd_pnl_pct=18.32,
            realized_today=150.00,
            unrealized_today=95.50,
            total_positions=3,
            winning_positions=2,
            losing_positions=1
        )

    def _get_mock_opportunities(self) -> List[OpportunityResponse]:
        """Return mock opportunities for testing"""
        return [
            OpportunityResponse(
                symbol="NVDA",
                market_type="equity",
                signal_type="buy",
                composite_score=8.7,
                risk_reward=3.2,
                confidence=0.82,
                entry_price=875.00,
                target_price=950.00,
                stop_loss=850.00,
                rank=1,
                reasoning=["AI momentum", "Earnings beat", "Institutional buying"],
                strategy="momentum_breakout"
            )
        ]

    def _get_mock_status(self) -> SystemStatus:
        """Return mock status for testing"""
        return SystemStatus(
            state="running",
            trading_enabled=True,
            auto_execute=False,
            agents_active=12,
            signals_raw=42,
            signals_analyzed=38,
            signals_ranked=12,
            positions_count=3,
            pending_trades=1
        )


# Singleton instance
_bridge_instance: Optional[CoordinatorBridge] = None


def get_bridge(coordinator=None) -> CoordinatorBridge:
    """Get or create the coordinator bridge instance"""
    global _bridge_instance

    if _bridge_instance is None:
        _bridge_instance = CoordinatorBridge(coordinator)
    elif coordinator and not _bridge_instance.coordinator:
        _bridge_instance.coordinator = coordinator

    return _bridge_instance

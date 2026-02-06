"""Tests for agents/coordinator.py — message handling & learning fan-out."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from core.base_agent import AgentMessage


def _make_coordinator():
    """Build a Coordinator with all heavy deps mocked out."""
    mock_config = MagicMock()
    mock_config.risk.max_daily_loss_pct = 0.05
    mock_config.risk.starting_capital = 10_000
    mock_config.risk.max_positions = 10

    with patch("agents.coordinator.config", mock_config), \
         patch("agents.coordinator.get_notifier", return_value=None), \
         patch("agents.coordinator.get_adaptive_weights") as mock_aw, \
         patch("agents.coordinator.get_edge_learner") as mock_el, \
         patch("agents.coordinator.get_pattern_learner") as mock_pl, \
         patch("agents.coordinator.get_model_manager") as mock_mm, \
         patch("agents.coordinator.get_retriever") as mock_ret:

        mock_aw.return_value = MagicMock()
        mock_el.return_value = MagicMock()
        mock_pl.return_value = MagicMock()
        mock_mm.return_value = MagicMock()
        mock_ret.return_value = MagicMock()

        from agents.coordinator import Coordinator
        coord = Coordinator()

    return coord


def _msg(msg_type, payload, source="TradeExecutor"):
    return AgentMessage(
        source=source,
        target="coordinator",
        msg_type=msg_type,
        payload=payload,
    )


# =========================================================================
# trade_executed handler
# =========================================================================

class TestTradeExecutedHandler:
    async def test_appends_to_executed_trades(self):
        coord = _make_coordinator()
        payload = {
            "trade_id": "SIM-001",
            "symbol": "AAPL",
            "market_type": "equity",
            "side": "buy",
            "quantity": 10,
            "fill_price": 150.0,
            "status": "filled",
        }
        await coord.handle_message(_msg("trade_executed", payload))
        assert len(coord.executed_trades) == 1
        assert coord.executed_trades[0]["symbol"] == "AAPL"

    async def test_side_resolution_in_notification(self):
        """When payload has no explicit side, signal_type='sell' → side='sell'."""
        coord = _make_coordinator()
        coord.notifier = AsyncMock()
        payload = {
            "trade_id": "SIM-002",
            "symbol": "SPY",
            "market_type": "equity",
            "signal_type": "sell",
            "quantity": 5,
            "fill_price": 400.0,
            "status": "filled",
        }
        await coord.handle_message(_msg("trade_executed", payload))
        # The notifier.notify_trade_entry should have been called with side='sell'
        coord.notifier.notify_trade_entry.assert_awaited_once()
        call_kwargs = coord.notifier.notify_trade_entry.call_args
        assert call_kwargs.kwargs.get("side") or call_kwargs[1].get("side") or \
               (call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None) == "sell"


# =========================================================================
# trade_closed handler
# =========================================================================

class TestTradeClosedHandler:
    def _closed_payload(self, **overrides):
        base = {
            "symbol": "AAPL",
            "company": "Apple",
            "market_type": "equity",
            "side": "long",
            "quantity": 10,
            "entry_price": 150.0,
            "exit_price": 160.0,
            "pnl": 100.0,
            "pnl_pct": 6.67,
            "risk_reward_achieved": 2.0,
            "hold_time_hours": 24.0,
            "hold_time": "24h 0m",
            "strategy": "mean_reversion",
            "exit_reason": "target_hit",
            "edge_score": None,
            "timestamp": datetime.now().isoformat(),
        }
        base.update(overrides)
        return base

    async def test_calls_all_four_learning_systems(self):
        coord = _make_coordinator()
        payload = self._closed_payload()
        await coord.handle_message(_msg("trade_closed", payload))

        coord.adaptive_weights.record_trade.assert_called_once()
        coord.edge_learner.record_outcome.assert_called_once()
        coord.pattern_learner.record_trade_pattern.assert_called_once()
        coord.model_manager.record_outcome.assert_called_once()

    async def test_notify_trade_exit_called_with_correct_side(self):
        coord = _make_coordinator()
        coord.notifier = AsyncMock()
        payload = self._closed_payload(side="short")
        await coord.handle_message(_msg("trade_closed", payload))

        coord.notifier.notify_trade_exit.assert_awaited_once()
        kwargs = coord.notifier.notify_trade_exit.call_args.kwargs
        assert kwargs["side"] == "short"

    async def test_side_resolution_signal_type_short(self):
        """signal_type='short' with no explicit side → 'sell' in notification."""
        coord = _make_coordinator()
        coord.notifier = AsyncMock()
        # No 'side' key — falls back to signal_type resolution
        payload = self._closed_payload(signal_type="short")
        del payload["side"]
        await coord.handle_message(_msg("trade_closed", payload))

        coord.notifier.notify_trade_exit.assert_awaited_once()
        kwargs = coord.notifier.notify_trade_exit.call_args.kwargs
        assert kwargs["side"] == "sell"


# =========================================================================
# positions_update handler
# =========================================================================

class TestPositionsUpdateHandler:
    async def test_updates_positions(self):
        coord = _make_coordinator()
        positions = [
            {"symbol": "AAPL", "side": "long", "pnl_pct": 5.0},
            {"symbol": "SPY", "side": "short", "pnl_pct": -2.0},
        ]
        await coord.handle_message(
            _msg("positions_update", {"positions": positions})
        )
        assert len(coord.positions) == 2
        assert coord.positions[0]["symbol"] == "AAPL"

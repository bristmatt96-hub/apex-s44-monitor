"""Tests for agents/execution/trade_executor.py

Side resolution, validation, sizing, and sim-mode execution.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime


# ---------------------------------------------------------------------------
# Patch heavy imports BEFORE importing TradeExecutor so __init__ never
# touches the real broker, notifier, config, or state file.
# ---------------------------------------------------------------------------

def _make_executor(
    capital=10_000,
    max_position_pct=0.05,
    max_positions=10,
    pdt_restricted=False,
    positions=None,
    day_trades_today=0,
):
    """Build a TradeExecutor with all externals mocked out."""
    mock_config = MagicMock()
    mock_config.risk.starting_capital = capital
    mock_config.risk.max_position_pct = max_position_pct
    mock_config.risk.max_positions = max_positions
    mock_config.pdt_restricted = pdt_restricted

    with patch("agents.execution.trade_executor.IBBroker") as MockBroker, \
         patch("agents.execution.trade_executor.get_notifier", return_value=None), \
         patch("agents.execution.trade_executor.config", mock_config):
        MockBroker.return_value.connect = AsyncMock(return_value=False)
        # Prevent _load_state from hitting disk
        with patch.object(
            __import__("agents.execution.trade_executor", fromlist=["TradeExecutor"]).TradeExecutor,
            "_load_state",
        ):
            from agents.execution.trade_executor import TradeExecutor
            executor = TradeExecutor()

    # Override any fields the caller needs
    executor.positions = list(positions or [])
    executor.day_trades_today = day_trades_today
    executor.connected = False  # always sim mode for tests
    executor.notifier = None
    return executor


# =========================================================================
# _resolve_side
# =========================================================================

class TestResolveSide:
    def _resolve(self, order):
        executor = _make_executor()
        return executor._resolve_side(order)

    def test_explicit_buy(self):
        assert self._resolve({"side": "buy"}) == "buy"

    def test_explicit_sell(self):
        assert self._resolve({"side": "sell"}) == "sell"

    def test_signal_type_sell(self):
        assert self._resolve({"signal_type": "sell"}) == "sell"

    def test_signal_type_short(self):
        assert self._resolve({"signal_type": "short"}) == "sell"

    def test_signal_type_short_put(self):
        assert self._resolve({"signal_type": "short_put"}) == "sell"

    def test_signal_type_short_call(self):
        assert self._resolve({"signal_type": "short_call"}) == "sell"

    def test_signal_type_buy(self):
        assert self._resolve({"signal_type": "buy"}) == "buy"

    def test_empty_dict_defaults_buy(self):
        assert self._resolve({}) == "buy"

    def test_explicit_side_takes_precedence(self):
        assert self._resolve({"side": "buy", "signal_type": "sell"}) == "buy"


# =========================================================================
# _validate_order (async)
# =========================================================================

class TestValidateOrder:
    async def test_valid_order_passes(self, sample_order):
        executor = _make_executor()
        assert await executor._validate_order(sample_order) is True

    async def test_max_positions_reached(self, sample_order):
        executor = _make_executor(max_positions=2)
        # Fill up to limit with dummy positions
        from core.models import Position, MarketType
        for sym in ("A", "B"):
            executor.positions.append(
                Position(sym, MarketType.EQUITY, 10, 100, 100, datetime.now())
            )
        assert await executor._validate_order(sample_order) is False

    async def test_duplicate_symbol_rejected(self, sample_order):
        executor = _make_executor()
        from core.models import Position, MarketType
        executor.positions.append(
            Position("AAPL", MarketType.EQUITY, 10, 150, 150, datetime.now())
        )
        assert await executor._validate_order(sample_order) is False

    async def test_pdt_limit_reached(self):
        executor = _make_executor(pdt_restricted=True, day_trades_today=3)
        # Stub send_message so it doesn't blow up
        executor.send_message = AsyncMock()
        order = {
            "symbol": "TSLA",
            "market_type": "equity",
            "entry_price": 200,
            "signal_type": "buy",
        }
        assert await executor._validate_order(order) is False


# =========================================================================
# _calculate_position_size
# =========================================================================

class TestCalculatePositionSize:
    def test_risk_based_sizing_with_stop(self):
        executor = _make_executor(capital=10_000, max_position_pct=0.05)
        order = {"entry_price": 100.0, "stop_loss": 95.0, "market_type": "equity"}
        # Risk per share = 5.  1% of 10k = 100.  100/5 = 20 shares (risk-based)
        # Value cap = 10k * 0.05 / 100 = 5 shares
        # min(20, 5) = 5  → int(5) = 5
        assert executor._calculate_position_size(order) == 5

    def test_value_cap_limits_quantity(self):
        executor = _make_executor(capital=10_000, max_position_pct=0.05)
        order = {"entry_price": 50.0, "stop_loss": 49.0, "market_type": "equity"}
        # risk-based: 100/1 = 100 shares
        # value-based: 500/50 = 10 shares
        # min(100, 10) = 10
        assert executor._calculate_position_size(order) == 10

    def test_no_stop_loss_value_based(self):
        executor = _make_executor(capital=10_000, max_position_pct=0.05)
        order = {"entry_price": 100.0, "market_type": "equity"}
        # 500 / 100 = 5
        assert executor._calculate_position_size(order) == 5

    def test_crypto_fractional(self):
        executor = _make_executor(capital=10_000, max_position_pct=0.05)
        order = {"entry_price": 60_000.0, "market_type": "crypto"}
        # 500 / 60000 ≈ 0.0083  → round to 4 decimal = 0.0083
        qty = executor._calculate_position_size(order)
        assert isinstance(qty, float)
        # Ensure 4 decimal places
        assert qty == round(qty, 4)
        assert qty > 0

    def test_zero_entry_returns_zero(self):
        executor = _make_executor()
        order = {"entry_price": 0, "market_type": "equity"}
        assert executor._calculate_position_size(order) == 0


# =========================================================================
# _execute_order (async, sim mode)
# =========================================================================

class TestExecuteOrder:
    async def test_creates_trade_with_correct_side_from_signal_type(self):
        executor = _make_executor()
        executor._save_state = MagicMock()
        order = {
            "symbol": "SPY",
            "market_type": "equity",
            "entry_price": 400.0,
            "stop_loss": 390.0,
            "target_price": 420.0,
            "signal_type": "sell",
        }
        trade = await executor._execute_order(order)
        assert trade is not None
        assert trade.side == "sell"

    async def test_creates_position_with_correct_side(self):
        executor = _make_executor()
        executor._save_state = MagicMock()
        order = {
            "symbol": "SPY",
            "market_type": "equity",
            "entry_price": 400.0,
            "stop_loss": 390.0,
            "target_price": 420.0,
            "signal_type": "short",
        }
        trade = await executor._execute_order(order)
        assert trade is not None
        # Position should be 'short' since side='sell'
        pos = executor.positions[-1]
        assert pos.side == "short"

    async def test_returns_none_for_zero_quantity(self):
        executor = _make_executor()
        order = {
            "symbol": "SPY",
            "market_type": "equity",
            "entry_price": 0,
            "signal_type": "buy",
        }
        trade = await executor._execute_order(order)
        assert trade is None

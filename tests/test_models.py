"""
Unit tests for core data models
"""
import pytest
from datetime import datetime

from core.models import (
    MarketType,
    SignalType,
    OrderType,
    OrderStatus,
    Signal,
    Trade,
    Position,
    MarketData,
    Opportunity,
)


class TestMarketType:
    """Tests for MarketType enum"""

    def test_market_type_values(self):
        """Test all market types exist"""
        assert MarketType.EQUITY.value == "equity"
        assert MarketType.CRYPTO.value == "crypto"
        assert MarketType.FOREX.value == "forex"
        assert MarketType.OPTIONS.value == "options"
        assert MarketType.SPAC.value == "spac"
        assert MarketType.FUTURES.value == "futures"


class TestSignal:
    """Tests for Signal dataclass"""

    def test_signal_creation(self):
        """Test basic signal creation"""
        signal = Signal(
            symbol="AAPL",
            market_type=MarketType.EQUITY,
            signal_type=SignalType.BUY,
            confidence=0.85,
            entry_price=150.0,
            target_price=165.0,
            stop_loss=145.0,
            risk_reward_ratio=3.0,
            source="TechnicalAnalyzer"
        )

        assert signal.symbol == "AAPL"
        assert signal.market_type == MarketType.EQUITY
        assert signal.signal_type == SignalType.BUY
        assert signal.confidence == 0.85
        assert isinstance(signal.timestamp, datetime)

    def test_signal_expected_gain_pct(self):
        """Test expected gain calculation"""
        signal = Signal(
            symbol="BTC",
            market_type=MarketType.CRYPTO,
            signal_type=SignalType.BUY,
            confidence=0.9,
            entry_price=50000.0,
            target_price=55000.0,
            stop_loss=48000.0,
            risk_reward_ratio=2.5,
            source="CryptoScanner"
        )

        # Expected gain: (55000 - 50000) / 50000 * 100 = 10%
        assert signal.expected_gain_pct == 10.0

    def test_signal_expected_loss_pct(self):
        """Test expected loss calculation"""
        signal = Signal(
            symbol="EUR/USD",
            market_type=MarketType.FOREX,
            signal_type=SignalType.BUY,
            confidence=0.75,
            entry_price=1.1000,
            target_price=1.1100,
            stop_loss=1.0950,
            risk_reward_ratio=2.0,
            source="ForexScanner"
        )

        # Expected loss: (1.1000 - 1.0950) / 1.1000 * 100 ≈ 0.4545%
        assert abs(signal.expected_loss_pct - 0.4545) < 0.01

    def test_signal_with_metadata(self):
        """Test signal with metadata"""
        signal = Signal(
            symbol="SPY",
            market_type=MarketType.EQUITY,
            signal_type=SignalType.BUY,
            confidence=0.8,
            entry_price=450.0,
            target_price=460.0,
            stop_loss=445.0,
            risk_reward_ratio=2.0,
            source="MomentumScanner",
            metadata={"strategy": "breakout", "volume_spike": True}
        )

        assert signal.metadata["strategy"] == "breakout"
        assert signal.metadata["volume_spike"] is True


class TestTrade:
    """Tests for Trade dataclass"""

    def test_trade_creation(self):
        """Test basic trade creation"""
        trade = Trade(
            id="trade_001",
            symbol="TSLA",
            market_type=MarketType.EQUITY,
            side="buy",
            quantity=10,
            order_type=OrderType.LIMIT,
            limit_price=200.0
        )

        assert trade.id == "trade_001"
        assert trade.symbol == "TSLA"
        assert trade.side == "buy"
        assert trade.quantity == 10
        assert trade.status == OrderStatus.PENDING  # default
        assert trade.commission == 0.0  # default

    def test_trade_with_stop(self):
        """Test trade with stop price"""
        trade = Trade(
            id="trade_002",
            symbol="AMZN",
            market_type=MarketType.EQUITY,
            side="buy",
            quantity=5,
            order_type=OrderType.STOP_LIMIT,
            limit_price=150.0,
            stop_price=148.0
        )

        assert trade.order_type == OrderType.STOP_LIMIT
        assert trade.stop_price == 148.0

    def test_trade_filled(self):
        """Test filled trade"""
        trade = Trade(
            id="trade_003",
            symbol="NVDA",
            market_type=MarketType.EQUITY,
            side="sell",
            quantity=20,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            fill_price=450.5,
            fill_quantity=20,
            commission=1.0,
            filled_at=datetime.now()
        )

        assert trade.status == OrderStatus.FILLED
        assert trade.fill_price == 450.5
        assert trade.fill_quantity == 20


class TestPosition:
    """Tests for Position dataclass"""

    def test_position_creation(self):
        """Test basic position creation"""
        position = Position(
            symbol="GOOGL",
            market_type=MarketType.EQUITY,
            quantity=15,
            entry_price=140.0,
            current_price=145.0,
            entry_time=datetime.now()
        )

        assert position.symbol == "GOOGL"
        assert position.quantity == 15
        assert position.entry_price == 140.0
        assert position.current_price == 145.0

    def test_position_pnl_pct_profit(self):
        """Test P&L percentage for winning position"""
        position = Position(
            symbol="MSFT",
            market_type=MarketType.EQUITY,
            quantity=10,
            entry_price=300.0,
            current_price=330.0,
            entry_time=datetime.now()
        )

        # P&L: (330 - 300) / 300 * 100 = 10%
        assert position.pnl_pct == 10.0

    def test_position_pnl_pct_loss(self):
        """Test P&L percentage for losing position"""
        position = Position(
            symbol="META",
            market_type=MarketType.EQUITY,
            quantity=20,
            entry_price=400.0,
            current_price=380.0,
            entry_time=datetime.now()
        )

        # P&L: (380 - 400) / 400 * 100 = -5%
        assert position.pnl_pct == -5.0

    def test_position_market_value(self):
        """Test market value calculation"""
        position = Position(
            symbol="BTC",
            market_type=MarketType.CRYPTO,
            quantity=0.5,
            entry_price=50000.0,
            current_price=52000.0,
            entry_time=datetime.now()
        )

        # Market value: 0.5 * 52000 = 26000
        assert position.market_value == 26000.0

    def test_position_with_stops(self):
        """Test position with stop loss and take profit"""
        position = Position(
            symbol="ETH",
            market_type=MarketType.CRYPTO,
            quantity=2.0,
            entry_price=3000.0,
            current_price=3100.0,
            entry_time=datetime.now(),
            stop_loss=2800.0,
            take_profit=3500.0
        )

        assert position.stop_loss == 2800.0
        assert position.take_profit == 3500.0


class TestMarketData:
    """Tests for MarketData dataclass"""

    def test_market_data_creation(self):
        """Test basic market data creation"""
        data = MarketData(
            symbol="SPY",
            market_type=MarketType.EQUITY,
            timestamp=datetime.now(),
            open=450.0,
            high=455.0,
            low=448.0,
            close=453.0,
            volume=50000000
        )

        assert data.symbol == "SPY"
        assert data.high == 455.0
        assert data.low == 448.0
        assert data.volume == 50000000

    def test_market_data_with_bid_ask(self):
        """Test market data with bid/ask"""
        data = MarketData(
            symbol="AAPL",
            market_type=MarketType.EQUITY,
            timestamp=datetime.now(),
            open=150.0,
            high=152.0,
            low=149.0,
            close=151.0,
            volume=30000000,
            bid=150.95,
            ask=151.05
        )

        assert data.bid == 150.95
        assert data.ask == 151.05
        # Spread
        assert data.ask - data.bid == pytest.approx(0.10)


class TestOpportunity:
    """Tests for Opportunity dataclass"""

    def test_opportunity_creation(self):
        """Test opportunity creation with signal"""
        signal = Signal(
            symbol="NVDA",
            market_type=MarketType.EQUITY,
            signal_type=SignalType.BUY,
            confidence=0.9,
            entry_price=450.0,
            target_price=500.0,
            stop_loss=430.0,
            risk_reward_ratio=2.5,
            source="MLPredictor"
        )

        opportunity = Opportunity(
            signal=signal,
            score=0.85,
            rank=1,
            reasoning=["Strong momentum", "High volume", "Above 50 MA"]
        )

        assert opportunity.signal.symbol == "NVDA"
        assert opportunity.score == 0.85
        assert opportunity.rank == 1
        assert len(opportunity.reasoning) == 3
        assert "Strong momentum" in opportunity.reasoning

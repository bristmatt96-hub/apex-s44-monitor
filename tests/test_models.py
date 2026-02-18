"""Tests for core/models.py — Signal & Position properties.

Pure dataclass math, no mocking needed.
"""
from datetime import datetime
from core.models import Signal, Position, MarketType, SignalType


def _make_signal(signal_type, entry, target, stop):
    return Signal(
        symbol="TEST",
        market_type=MarketType.EQUITY,
        signal_type=signal_type,
        confidence=0.8,
        entry_price=entry,
        target_price=target,
        stop_loss=stop,
        risk_reward_ratio=2.0,
        source="test",
    )


def _make_position(side, entry, current, quantity=100):
    return Position(
        symbol="TEST",
        market_type=MarketType.EQUITY,
        quantity=quantity,
        entry_price=entry,
        current_price=current,
        entry_time=datetime.now(),
        side=side,
    )


# --- Signal expected_gain_pct / expected_loss_pct ---

def test_signal_buy_expected_gain():
    sig = _make_signal(SignalType.BUY, entry=100, target=110, stop=95)
    assert sig.expected_gain_pct == pytest.approx(10.0)


def test_signal_buy_expected_loss():
    sig = _make_signal(SignalType.BUY, entry=100, target=110, stop=95)
    assert sig.expected_loss_pct == pytest.approx(5.0)


def test_signal_sell_expected_gain():
    sig = _make_signal(SignalType.SELL, entry=100, target=90, stop=105)
    assert sig.expected_gain_pct == pytest.approx(10.0)


def test_signal_sell_expected_loss():
    sig = _make_signal(SignalType.SELL, entry=100, target=90, stop=105)
    assert sig.expected_loss_pct == pytest.approx(5.0)


# --- Position pnl_pct ---

def test_position_long_profit():
    pos = _make_position("long", entry=100, current=110)
    assert pos.pnl_pct == pytest.approx(10.0)


def test_position_long_loss():
    pos = _make_position("long", entry=100, current=95)
    assert pos.pnl_pct == pytest.approx(-5.0)


def test_position_short_profit():
    pos = _make_position("short", entry=100, current=90)
    assert pos.pnl_pct == pytest.approx(10.0)


def test_position_short_loss():
    pos = _make_position("short", entry=100, current=105)
    assert pos.pnl_pct == pytest.approx(-5.0)


# --- Position market_value ---

def test_position_market_value():
    pos = _make_position("long", entry=100, current=120, quantity=50)
    assert pos.market_value == pytest.approx(6000.0)


# import pytest at module level for approx
import pytest

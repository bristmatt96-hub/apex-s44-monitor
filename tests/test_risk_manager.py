"""Tests for agents/risk_manager.py — all 7 guardrails.

RiskManager is self-contained; no external mocking needed.
"""
import pytest
from datetime import datetime, timedelta

from agents.risk_manager import (
    RiskManager,
    PortfolioState,
    Position,
    RiskCheck,
    RiskViolation,
)


def _make_portfolio(
    account_value=10_000,
    cash=10_000,
    positions=None,
    daily_pnl=0.0,
    weekly_pnl=0.0,
):
    return PortfolioState(
        account_value=account_value,
        cash=cash,
        positions=positions or [],
        daily_pnl=daily_pnl,
        weekly_pnl=weekly_pnl,
    )


def _make_position(ticker="TEST", sector="Tech", quantity=1, entry_price=5.0):
    return Position(
        ticker=ticker,
        company=ticker,
        sector=sector,
        direction="LONG_PUT",
        entry_date=datetime.now() - timedelta(days=1),
        entry_price=entry_price,
        quantity=quantity,
        current_price=entry_price,
        unrealized_pnl=0,
        max_loss=entry_price * 0.5,
        edge_score=6.0,
    )


# =========================================================================
# Individual checks
# =========================================================================

class TestCheckEdgeScore:
    def test_pass_at_5(self):
        rm = RiskManager()
        assert rm.check_edge_score(5.0).passed is True

    def test_fail_at_4_9(self):
        rm = RiskManager()
        check = rm.check_edge_score(4.9)
        assert check.passed is False
        assert check.violation == RiskViolation.MIN_EDGE_SCORE


class TestCheckDailyLoss:
    def test_pass_at_negative_499(self):
        rm = RiskManager(_make_portfolio(daily_pnl=-499))
        assert rm.check_daily_loss().passed is True

    def test_fail_at_negative_500(self):
        rm = RiskManager(_make_portfolio(daily_pnl=-500))
        check = rm.check_daily_loss()
        assert check.passed is False
        assert check.violation == RiskViolation.MAX_DAILY_LOSS


class TestCheckWeeklyLoss:
    def test_pass_at_negative_999(self):
        rm = RiskManager(_make_portfolio(weekly_pnl=-999))
        assert rm.check_weekly_loss().passed is True

    def test_fail_at_negative_1000(self):
        rm = RiskManager(_make_portfolio(weekly_pnl=-1000))
        check = rm.check_weekly_loss()
        assert check.passed is False
        assert check.violation == RiskViolation.MAX_WEEKLY_LOSS


class TestCheckSectorConcentration:
    def test_pass_at_2_positions(self):
        positions = [_make_position(f"T{i}", "Tech") for i in range(2)]
        rm = RiskManager(_make_portfolio(positions=positions))
        assert rm.check_sector_concentration("Tech").passed is True

    def test_fail_at_3_positions(self):
        positions = [_make_position(f"T{i}", "Tech") for i in range(3)]
        rm = RiskManager(_make_portfolio(positions=positions))
        check = rm.check_sector_concentration("Tech")
        assert check.passed is False
        assert check.violation == RiskViolation.MAX_SECTOR_CONCENTRATION


class TestCheckPositionSize:
    def test_pass_at_500(self):
        rm = RiskManager(_make_portfolio(account_value=10_000))
        assert rm.check_position_size(500).passed is True

    def test_fail_at_501(self):
        rm = RiskManager(_make_portfolio(account_value=10_000))
        check = rm.check_position_size(501)
        assert check.passed is False
        assert check.violation == RiskViolation.MAX_POSITION_SIZE
        # Returns a suggested max
        assert check.suggested_adjustment == pytest.approx(500.0)


class TestCheckPortfolioExposure:
    def test_pass_below_30pct(self):
        rm = RiskManager(_make_portfolio(account_value=10_000))
        assert rm.check_portfolio_exposure(2999).passed is True

    def test_fail_above_30pct(self):
        rm = RiskManager(_make_portfolio(account_value=10_000))
        check = rm.check_portfolio_exposure(3001)
        assert check.passed is False
        assert check.violation == RiskViolation.MAX_PORTFOLIO_EXPOSURE


class TestCheckCashAvailable:
    def test_pass_with_enough_cash(self):
        # cash=10k, reserve=20%=2k, available=8k
        rm = RiskManager(_make_portfolio(cash=10_000))
        assert rm.check_cash_available(7999).passed is True

    def test_fail_with_insufficient_cash(self):
        rm = RiskManager(_make_portfolio(cash=10_000))
        check = rm.check_cash_available(8001)
        assert check.passed is False
        assert check.violation == RiskViolation.INSUFFICIENT_CAPITAL


# =========================================================================
# validate_trade integration
# =========================================================================

class TestValidateTrade:
    def test_all_checks_pass(self):
        rm = RiskManager(_make_portfolio(account_value=10_000, cash=10_000))
        approved, checks, size = rm.validate_trade(
            ticker="TEST", sector="Tech", proposed_cost=400, edge_score=7.0
        )
        assert approved is True
        # 7 checks: edge, daily, weekly, sector, position size, exposure, cash
        assert len(checks) == 7

    def test_low_edge_early_exit(self):
        rm = RiskManager()
        approved, checks, size = rm.validate_trade(
            ticker="TEST", sector="Tech", proposed_cost=400, edge_score=4.0
        )
        assert approved is False
        assert len(checks) == 1  # Only edge check performed

    def test_oversized_position_adjusted(self):
        rm = RiskManager(_make_portfolio(account_value=10_000, cash=10_000))
        approved, checks, size = rm.validate_trade(
            ticker="TEST", sector="Tech", proposed_cost=800, edge_score=6.0
        )
        # Should be approved with reduced size (capped at 500 = 5% of 10k)
        assert approved is True
        assert size == pytest.approx(500.0)

    def test_daily_loss_breached_rejects(self):
        rm = RiskManager(_make_portfolio(daily_pnl=-500))
        approved, checks, size = rm.validate_trade(
            ticker="TEST", sector="Tech", proposed_cost=400, edge_score=7.0
        )
        assert approved is False
        # edge check passed, daily check failed → 2 checks
        assert len(checks) == 2

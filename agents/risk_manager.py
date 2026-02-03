"""
Risk Manager for Credit Catalyst

Enforces hard guardrails that CANNOT be overridden:
- Max single position: 5% of account
- Max portfolio exposure: 30% of account
- Max loss per trade: 50% of position value
- Max daily loss: 5% of account
- Max weekly loss: 10% of account
- Max correlation: 3 positions in same sector
- Min edge score: 5.0

These limits protect the account from catastrophic losses.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json
from pathlib import Path


class RiskViolation(Enum):
    """Types of risk violations."""
    MAX_POSITION_SIZE = "max_position_size"
    MAX_PORTFOLIO_EXPOSURE = "max_portfolio_exposure"
    MAX_SECTOR_CONCENTRATION = "max_sector_concentration"
    MAX_DAILY_LOSS = "max_daily_loss"
    MAX_WEEKLY_LOSS = "max_weekly_loss"
    MIN_EDGE_SCORE = "min_edge_score"
    INSUFFICIENT_CAPITAL = "insufficient_capital"


@dataclass
class RiskCheck:
    """Result of a risk check."""
    passed: bool
    violation: Optional[RiskViolation] = None
    message: str = ""
    current_value: Optional[float] = None
    limit_value: Optional[float] = None
    suggested_adjustment: Optional[float] = None


@dataclass
class Position:
    """Represents an open position."""
    ticker: str
    company: str
    sector: str
    direction: str  # LONG_PUT, LONG_CALL, STRADDLE
    entry_date: datetime
    entry_price: float
    quantity: int
    current_price: float
    unrealized_pnl: float
    max_loss: float  # Stop-loss level
    edge_score: float


@dataclass
class PortfolioState:
    """Current portfolio state for risk calculations."""
    account_value: float
    cash: float
    positions: List[Position] = field(default_factory=list)
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    daily_trades: int = 0

    def get_position_value(self, position: Position) -> float:
        """Calculate position value (premium paid)."""
        return position.entry_price * position.quantity * 100  # Options multiplier

    def get_total_exposure(self) -> float:
        """Calculate total portfolio exposure."""
        return sum(self.get_position_value(p) for p in self.positions)

    def get_sector_exposure(self, sector: str) -> Tuple[int, float]:
        """Get number of positions and value in a sector."""
        sector_positions = [p for p in self.positions if p.sector == sector]
        count = len(sector_positions)
        value = sum(self.get_position_value(p) for p in sector_positions)
        return count, value


class RiskManager:
    """
    Enforces hard risk limits for the autonomous trading agent.

    All limits are HARD - they cannot be overridden by edge score or conviction.
    """

    # Hard limits (cannot be changed)
    MAX_SINGLE_POSITION_PCT = 0.05  # 5% of account
    MAX_PORTFOLIO_EXPOSURE_PCT = 0.30  # 30% of account
    MAX_LOSS_PER_TRADE_PCT = 0.50  # 50% of position value
    MAX_DAILY_LOSS_PCT = 0.05  # 5% of account
    MAX_WEEKLY_LOSS_PCT = 0.10  # 10% of account
    MAX_SECTOR_POSITIONS = 3  # Max positions in same sector
    MIN_EDGE_SCORE = 5.0  # Minimum edge score to trade
    MIN_CASH_RESERVE_PCT = 0.20  # Keep 20% cash minimum

    def __init__(self, portfolio: PortfolioState = None):
        self.portfolio = portfolio or PortfolioState(account_value=10000, cash=10000)
        self.trade_log: List[Dict] = []

    def update_portfolio(self, portfolio: PortfolioState):
        """Update current portfolio state."""
        self.portfolio = portfolio

    def check_position_size(
        self,
        proposed_cost: float,
        aggression_multiplier: float = 1.0
    ) -> RiskCheck:
        """
        Check if proposed position size is within limits.

        Returns adjusted size if necessary.
        """
        # Calculate maximum allowed position size
        max_position = self.portfolio.account_value * self.MAX_SINGLE_POSITION_PCT

        # Apply aggression multiplier (but still capped at hard limit)
        desired_size = proposed_cost * aggression_multiplier
        actual_size = min(desired_size, max_position)

        if proposed_cost > max_position:
            return RiskCheck(
                passed=False,
                violation=RiskViolation.MAX_POSITION_SIZE,
                message=f"Position size ${proposed_cost:.2f} exceeds max ${max_position:.2f} (5% of account)",
                current_value=proposed_cost,
                limit_value=max_position,
                suggested_adjustment=max_position
            )

        return RiskCheck(
            passed=True,
            message=f"Position size ${actual_size:.2f} within limits",
            current_value=actual_size,
            limit_value=max_position
        )

    def check_portfolio_exposure(self, proposed_cost: float) -> RiskCheck:
        """Check if adding position would exceed portfolio exposure limit."""
        current_exposure = self.portfolio.get_total_exposure()
        max_exposure = self.portfolio.account_value * self.MAX_PORTFOLIO_EXPOSURE_PCT
        new_exposure = current_exposure + proposed_cost

        if new_exposure > max_exposure:
            available = max_exposure - current_exposure
            return RiskCheck(
                passed=False,
                violation=RiskViolation.MAX_PORTFOLIO_EXPOSURE,
                message=f"Portfolio exposure would be ${new_exposure:.2f}, exceeds max ${max_exposure:.2f} (30%)",
                current_value=new_exposure,
                limit_value=max_exposure,
                suggested_adjustment=max(0, available)
            )

        return RiskCheck(
            passed=True,
            message=f"Portfolio exposure ${new_exposure:.2f} within limit ${max_exposure:.2f}",
            current_value=new_exposure,
            limit_value=max_exposure
        )

    def check_sector_concentration(self, sector: str) -> RiskCheck:
        """Check if adding to sector would exceed concentration limit."""
        count, value = self.portfolio.get_sector_exposure(sector)

        if count >= self.MAX_SECTOR_POSITIONS:
            return RiskCheck(
                passed=False,
                violation=RiskViolation.MAX_SECTOR_CONCENTRATION,
                message=f"Already {count} positions in {sector} (max {self.MAX_SECTOR_POSITIONS})",
                current_value=count,
                limit_value=self.MAX_SECTOR_POSITIONS
            )

        return RiskCheck(
            passed=True,
            message=f"{count} positions in {sector}, can add more",
            current_value=count,
            limit_value=self.MAX_SECTOR_POSITIONS
        )

    def check_daily_loss(self) -> RiskCheck:
        """Check if daily loss limit has been breached."""
        max_daily_loss = self.portfolio.account_value * self.MAX_DAILY_LOSS_PCT

        if self.portfolio.daily_pnl <= -max_daily_loss:
            return RiskCheck(
                passed=False,
                violation=RiskViolation.MAX_DAILY_LOSS,
                message=f"Daily loss ${abs(self.portfolio.daily_pnl):.2f} exceeds max ${max_daily_loss:.2f} (5%)",
                current_value=self.portfolio.daily_pnl,
                limit_value=-max_daily_loss
            )

        return RiskCheck(
            passed=True,
            message=f"Daily P&L ${self.portfolio.daily_pnl:.2f} within limits",
            current_value=self.portfolio.daily_pnl,
            limit_value=-max_daily_loss
        )

    def check_weekly_loss(self) -> RiskCheck:
        """Check if weekly loss limit has been breached."""
        max_weekly_loss = self.portfolio.account_value * self.MAX_WEEKLY_LOSS_PCT

        if self.portfolio.weekly_pnl <= -max_weekly_loss:
            return RiskCheck(
                passed=False,
                violation=RiskViolation.MAX_WEEKLY_LOSS,
                message=f"Weekly loss ${abs(self.portfolio.weekly_pnl):.2f} exceeds max ${max_weekly_loss:.2f} (10%)",
                current_value=self.portfolio.weekly_pnl,
                limit_value=-max_weekly_loss
            )

        return RiskCheck(
            passed=True,
            message=f"Weekly P&L ${self.portfolio.weekly_pnl:.2f} within limits",
            current_value=self.portfolio.weekly_pnl,
            limit_value=-max_weekly_loss
        )

    def check_edge_score(self, edge_score: float) -> RiskCheck:
        """Check if edge score meets minimum threshold."""
        if edge_score < self.MIN_EDGE_SCORE:
            return RiskCheck(
                passed=False,
                violation=RiskViolation.MIN_EDGE_SCORE,
                message=f"Edge score {edge_score:.1f} below minimum {self.MIN_EDGE_SCORE}",
                current_value=edge_score,
                limit_value=self.MIN_EDGE_SCORE
            )

        return RiskCheck(
            passed=True,
            message=f"Edge score {edge_score:.1f} meets minimum {self.MIN_EDGE_SCORE}",
            current_value=edge_score,
            limit_value=self.MIN_EDGE_SCORE
        )

    def check_cash_available(self, proposed_cost: float) -> RiskCheck:
        """Check if sufficient cash is available."""
        min_cash = self.portfolio.account_value * self.MIN_CASH_RESERVE_PCT
        available_cash = self.portfolio.cash - min_cash

        if proposed_cost > available_cash:
            return RiskCheck(
                passed=False,
                violation=RiskViolation.INSUFFICIENT_CAPITAL,
                message=f"Need ${proposed_cost:.2f} but only ${available_cash:.2f} available (keeping 20% reserve)",
                current_value=available_cash,
                limit_value=proposed_cost,
                suggested_adjustment=available_cash
            )

        return RiskCheck(
            passed=True,
            message=f"${proposed_cost:.2f} available from ${available_cash:.2f} cash",
            current_value=available_cash,
            limit_value=proposed_cost
        )

    def validate_trade(
        self,
        ticker: str,
        sector: str,
        proposed_cost: float,
        edge_score: float,
        aggression_multiplier: float = 1.0
    ) -> Tuple[bool, List[RiskCheck], float]:
        """
        Run all risk checks for a proposed trade.

        Returns:
            - approved: bool
            - checks: List of all risk checks performed
            - adjusted_size: float (may be reduced from proposed)
        """
        checks = []
        approved = True
        adjusted_size = proposed_cost

        # 1. Check edge score first (no point continuing if too low)
        edge_check = self.check_edge_score(edge_score)
        checks.append(edge_check)
        if not edge_check.passed:
            return False, checks, 0

        # 2. Check daily/weekly circuit breakers
        daily_check = self.check_daily_loss()
        checks.append(daily_check)
        if not daily_check.passed:
            return False, checks, 0

        weekly_check = self.check_weekly_loss()
        checks.append(weekly_check)
        if not weekly_check.passed:
            return False, checks, 0

        # 3. Check sector concentration
        sector_check = self.check_sector_concentration(sector)
        checks.append(sector_check)
        if not sector_check.passed:
            return False, checks, 0

        # 4. Check position size
        size_check = self.check_position_size(proposed_cost, aggression_multiplier)
        checks.append(size_check)
        if not size_check.passed:
            # Adjust size down if possible
            if size_check.suggested_adjustment and size_check.suggested_adjustment > 0:
                adjusted_size = size_check.suggested_adjustment
            else:
                approved = False

        # 5. Check portfolio exposure with adjusted size
        exposure_check = self.check_portfolio_exposure(adjusted_size)
        checks.append(exposure_check)
        if not exposure_check.passed:
            if exposure_check.suggested_adjustment and exposure_check.suggested_adjustment > 0:
                adjusted_size = min(adjusted_size, exposure_check.suggested_adjustment)
            else:
                approved = False

        # 6. Check cash available for adjusted size
        cash_check = self.check_cash_available(adjusted_size)
        checks.append(cash_check)
        if not cash_check.passed:
            if cash_check.suggested_adjustment and cash_check.suggested_adjustment > 0:
                adjusted_size = min(adjusted_size, cash_check.suggested_adjustment)
            else:
                approved = False

        # Final check: is adjusted size still meaningful?
        min_viable_size = 100  # Minimum $100 position
        if adjusted_size < min_viable_size:
            approved = False
            checks.append(RiskCheck(
                passed=False,
                message=f"Adjusted size ${adjusted_size:.2f} below minimum viable ${min_viable_size}",
                current_value=adjusted_size,
                limit_value=min_viable_size
            ))

        return approved, checks, adjusted_size

    def calculate_position_size(
        self,
        edge_score: float,
        base_size: float,
        aggression_multiplier: float
    ) -> float:
        """
        Calculate position size based on edge score and risk limits.

        Returns the actual position size to use.
        """
        # Start with base size * aggression
        desired_size = base_size * aggression_multiplier

        # Cap at max position size
        max_position = self.portfolio.account_value * self.MAX_SINGLE_POSITION_PCT
        size = min(desired_size, max_position)

        # Cap at available portfolio capacity
        current_exposure = self.portfolio.get_total_exposure()
        max_exposure = self.portfolio.account_value * self.MAX_PORTFOLIO_EXPOSURE_PCT
        available_capacity = max_exposure - current_exposure
        size = min(size, available_capacity)

        # Cap at available cash
        min_cash = self.portfolio.account_value * self.MIN_CASH_RESERVE_PCT
        available_cash = self.portfolio.cash - min_cash
        size = min(size, available_cash)

        return max(0, size)

    def calculate_stop_loss(
        self,
        entry_price: float,
        direction: str,
        max_loss_pct: float = None
    ) -> float:
        """
        Calculate stop-loss price.

        For options, max loss is typically the premium paid (100%).
        We use 50% as default to manage risk.
        """
        if max_loss_pct is None:
            max_loss_pct = self.MAX_LOSS_PER_TRADE_PCT

        if direction in ["LONG_PUT", "LONG_CALL"]:
            # For long options, stop at 50% of premium loss
            return entry_price * (1 - max_loss_pct)
        elif direction == "STRADDLE":
            # For straddles, stop at 50% total premium loss
            return entry_price * (1 - max_loss_pct)
        else:
            return entry_price * (1 - max_loss_pct)

    def format_risk_report(self) -> str:
        """Generate risk report for current portfolio."""
        current_exposure = self.portfolio.get_total_exposure()
        max_exposure = self.portfolio.account_value * self.MAX_PORTFOLIO_EXPOSURE_PCT
        exposure_pct = (current_exposure / self.portfolio.account_value) * 100

        # Sector breakdown
        sectors = {}
        for pos in self.portfolio.positions:
            if pos.sector not in sectors:
                sectors[pos.sector] = {"count": 0, "value": 0}
            sectors[pos.sector]["count"] += 1
            sectors[pos.sector]["value"] += self.portfolio.get_position_value(pos)

        lines = [
            "=" * 50,
            "RISK REPORT",
            "=" * 50,
            "",
            f"Account Value: ${self.portfolio.account_value:,.2f}",
            f"Cash: ${self.portfolio.cash:,.2f}",
            f"",
            f"EXPOSURE:",
            f"  Current: ${current_exposure:,.2f} ({exposure_pct:.1f}%)",
            f"  Maximum: ${max_exposure:,.2f} (30%)",
            f"  Available: ${max_exposure - current_exposure:,.2f}",
            f"",
            f"P&L:",
            f"  Daily: ${self.portfolio.daily_pnl:,.2f}",
            f"  Weekly: ${self.portfolio.weekly_pnl:,.2f}",
            f"",
            f"POSITIONS: {len(self.portfolio.positions)}",
        ]

        if sectors:
            lines.append("")
            lines.append("SECTOR CONCENTRATION:")
            for sector, data in sectors.items():
                lines.append(f"  {sector}: {data['count']} positions (${data['value']:,.2f})")

        lines.extend([
            "",
            "LIMITS:",
            f"  Max position: ${self.portfolio.account_value * self.MAX_SINGLE_POSITION_PCT:,.2f}",
            f"  Max daily loss: ${self.portfolio.account_value * self.MAX_DAILY_LOSS_PCT:,.2f}",
            f"  Max weekly loss: ${self.portfolio.account_value * self.MAX_WEEKLY_LOSS_PCT:,.2f}",
            f"  Min edge score: {self.MIN_EDGE_SCORE}",
        ])

        return "\n".join(lines)


def main():
    """Test the risk manager."""
    print("=" * 60)
    print("RISK MANAGER - TEST")
    print("=" * 60)

    # Create portfolio state
    portfolio = PortfolioState(
        account_value=50000,
        cash=40000,
        positions=[
            Position(
                ticker="GRFS",
                company="Grifols",
                sector="Consumers",
                direction="LONG_PUT",
                entry_date=datetime.now() - timedelta(days=5),
                entry_price=2.50,
                quantity=10,
                current_price=2.80,
                unrealized_pnl=300,
                max_loss=1.25,
                edge_score=6.8
            )
        ],
        daily_pnl=150,
        weekly_pnl=-200
    )

    rm = RiskManager(portfolio)

    # Print current risk report
    print(rm.format_risk_report())

    # Test trade validation
    print("\n--- Trade Validation Tests ---")

    # Test 1: Good trade
    print("\nTest 1: Valid trade (edge 7.2, $1000)")
    approved, checks, size = rm.validate_trade(
        ticker="SBB-B.ST",
        sector="Financials",
        proposed_cost=1000,
        edge_score=7.2,
        aggression_multiplier=1.5
    )
    print(f"  Approved: {approved}")
    print(f"  Adjusted size: ${size:.2f}")
    for check in checks:
        status = "✓" if check.passed else "✗"
        print(f"  {status} {check.message}")

    # Test 2: Low edge score
    print("\nTest 2: Low edge score (4.5)")
    approved, checks, size = rm.validate_trade(
        ticker="TEST",
        sector="TMT",
        proposed_cost=500,
        edge_score=4.5
    )
    print(f"  Approved: {approved}")
    for check in checks:
        status = "✓" if check.passed else "✗"
        print(f"  {status} {check.message}")

    # Test 3: Position too large
    print("\nTest 3: Oversized position ($5000)")
    approved, checks, size = rm.validate_trade(
        ticker="BIG",
        sector="Energy",
        proposed_cost=5000,
        edge_score=8.0,
        aggression_multiplier=2.0
    )
    print(f"  Approved: {approved}")
    print(f"  Adjusted size: ${size:.2f}")
    for check in checks:
        status = "✓" if check.passed else "✗"
        print(f"  {status} {check.message}")

    # Test 4: Sector concentration
    print("\nTest 4: Sector concentration (Consumers - already has 1)")
    approved, checks, size = rm.validate_trade(
        ticker="CONS2",
        sector="Consumers",
        proposed_cost=800,
        edge_score=6.5
    )
    print(f"  Approved: {approved}")
    for check in checks:
        status = "✓" if check.passed else "✗"
        print(f"  {status} {check.message}")


if __name__ == "__main__":
    main()

"""
Panic Risk Manager

Special risk controls for trading during market panic/exogenous shocks.

THE PROBLEM:
- During panic, moves are 2-5x normal
- "Catching a falling knife" can wipe out capital
- VIX at 30 means daily moves of 3-4% are NORMAL
- You can be right on direction but wrong on timing

THE SOLUTION:
1. SMALLER POSITIONS during panic (50% of normal)
2. STAGED ENTRIES (don't go all-in, scale in)
3. WIDER STOPS (account for volatility)
4. MAX EXPOSURE LIMITS (no more than X% in recovery plays)
5. TIME-BASED RULES (don't buy day 1 of panic)

PHILOSOPHY:
"The market can stay irrational longer than you can stay solvent"
- Wait for panic to mature (2-3 days)
- Don't try to catch the exact bottom
- Accept missing the first 10% of the bounce
- Preserve capital to BUY MORE if it drops further
"""
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime, timedelta
from loguru import logger


@dataclass
class PanicRiskParams:
    """Risk parameters adjusted for panic conditions"""
    # Position sizing
    max_position_pct: float      # Max position size as % of capital
    position_size_multiplier: float  # Reduce normal size by this factor

    # Entry rules
    min_panic_days: int          # Wait X days before buying
    entry_tranches: int          # Split entry into X parts
    tranche_spacing_hours: int   # Hours between tranches

    # Stop loss
    stop_loss_atr_multiplier: float  # Wider stops during panic
    max_loss_per_trade_pct: float    # Max loss as % of capital

    # Portfolio limits
    max_panic_exposure_pct: float    # Max % of capital in panic plays
    max_correlated_positions: int    # Max positions in same sector


class PanicRiskManager:
    """
    Manages risk specifically for panic/recovery trades.

    Key principle: SURVIVE FIRST, PROFIT SECOND

    During panic:
    - Positions are HALF normal size
    - Stops are TWICE as wide (volatility adjusted)
    - Entry is STAGED over 2-3 tranches
    - Total exposure capped at 30% of capital
    """

    def __init__(self, total_capital: float = 3000.0):
        self.total_capital = total_capital

        # Normal risk params
        self.normal_params = PanicRiskParams(
            max_position_pct=0.10,        # 10% per position normally
            position_size_multiplier=1.0,
            min_panic_days=0,
            entry_tranches=1,
            tranche_spacing_hours=0,
            stop_loss_atr_multiplier=2.0,
            max_loss_per_trade_pct=0.02,  # 2% max loss
            max_panic_exposure_pct=1.0,   # No limit normally
            max_correlated_positions=5
        )

        # Panic risk params (much more conservative)
        self.panic_params = PanicRiskParams(
            max_position_pct=0.05,        # 5% per position in panic (HALF)
            position_size_multiplier=0.5, # 50% of normal size
            min_panic_days=2,             # Wait 2 days before buying
            entry_tranches=3,             # Split into 3 parts
            tranche_spacing_hours=24,     # 24 hours between tranches
            stop_loss_atr_multiplier=3.0, # 3x ATR stops (wider)
            max_loss_per_trade_pct=0.015, # 1.5% max loss (tighter)
            max_panic_exposure_pct=0.30,  # Max 30% in panic plays
            max_correlated_positions=2    # Max 2 in same sector
        )

        # Track current panic exposure
        self.panic_positions = {}  # symbol -> {entry_date, tranches_filled, total_invested}
        self.panic_start_date: Optional[datetime] = None

    def register_panic_start(self, timestamp: Optional[datetime] = None) -> None:
        """Mark the start of a panic event"""
        self.panic_start_date = timestamp or datetime.now()
        logger.info(f"Panic registered at {self.panic_start_date}")

    def can_enter_panic_trade(
        self,
        symbol: str,
        sector: str,
        current_panic_exposure: float
    ) -> Tuple[bool, str]:
        """
        Check if we can enter a new panic recovery trade.

        Returns (allowed, reason)
        """
        params = self.panic_params

        # Check 1: Panic maturity (don't buy day 1)
        if self.panic_start_date:
            days_since_panic = (datetime.now() - self.panic_start_date).days
            if days_since_panic < params.min_panic_days:
                return False, f"Panic too fresh ({days_since_panic}d < {params.min_panic_days}d minimum)"

        # Check 2: Total panic exposure limit
        if current_panic_exposure >= params.max_panic_exposure_pct * self.total_capital:
            return False, f"Max panic exposure reached ({params.max_panic_exposure_pct:.0%} of capital)"

        # Check 3: Already have position in this symbol
        if symbol in self.panic_positions:
            pos = self.panic_positions[symbol]
            if pos['tranches_filled'] >= params.entry_tranches:
                return False, f"All {params.entry_tranches} tranches already filled for {symbol}"

            # Check tranche timing
            last_entry = pos.get('last_entry_time')
            if last_entry:
                hours_since = (datetime.now() - last_entry).total_seconds() / 3600
                if hours_since < params.tranche_spacing_hours:
                    return False, f"Too soon for next tranche ({hours_since:.1f}h < {params.tranche_spacing_hours}h)"

        # Check 4: Sector concentration
        sector_count = sum(
            1 for s, p in self.panic_positions.items()
            if p.get('sector') == sector
        )
        if sector_count >= params.max_correlated_positions:
            return False, f"Max {params.max_correlated_positions} positions in {sector} sector"

        return True, "OK"

    def calculate_panic_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
        atr: float
    ) -> dict:
        """
        Calculate position size for a panic trade.

        Returns dict with:
        - shares: number of shares for this tranche
        - tranche_value: dollar value of this tranche
        - total_tranches: how many tranches total
        - stop_loss: adjusted stop loss
        - max_loss: max dollar loss on this tranche
        """
        params = self.panic_params

        # Widen stop for volatility
        adjusted_stop = entry_price - (atr * params.stop_loss_atr_multiplier)
        adjusted_stop = min(adjusted_stop, stop_price)  # Use wider of the two

        # Risk per share
        risk_per_share = entry_price - adjusted_stop

        # Max loss per tranche
        max_loss_per_tranche = (
            self.total_capital *
            params.max_loss_per_trade_pct /
            params.entry_tranches
        )

        # Position size based on risk
        if risk_per_share > 0:
            shares_by_risk = int(max_loss_per_tranche / risk_per_share)
        else:
            shares_by_risk = 0

        # Position size based on capital allocation
        tranche_capital = (
            self.total_capital *
            params.max_position_pct *
            params.position_size_multiplier /
            params.entry_tranches
        )
        shares_by_capital = int(tranche_capital / entry_price)

        # Use smaller of the two
        shares = min(shares_by_risk, shares_by_capital)
        shares = max(1, shares)  # At least 1 share

        tranche_value = shares * entry_price
        max_loss = shares * risk_per_share

        return {
            'shares': shares,
            'tranche_value': tranche_value,
            'total_tranches': params.entry_tranches,
            'current_tranche': self._get_current_tranche(symbol),
            'adjusted_stop': adjusted_stop,
            'max_loss': max_loss,
            'risk_per_share': risk_per_share,
            'next_tranche_in': f"{params.tranche_spacing_hours}h"
        }

    def _get_current_tranche(self, symbol: str) -> int:
        """Get current tranche number for symbol"""
        if symbol not in self.panic_positions:
            return 1
        return self.panic_positions[symbol].get('tranches_filled', 0) + 1

    def record_panic_entry(
        self,
        symbol: str,
        sector: str,
        shares: int,
        price: float
    ) -> None:
        """Record a panic trade entry"""
        if symbol not in self.panic_positions:
            self.panic_positions[symbol] = {
                'sector': sector,
                'tranches_filled': 0,
                'total_invested': 0,
                'total_shares': 0,
                'avg_price': 0,
                'entries': []
            }

        pos = self.panic_positions[symbol]
        pos['tranches_filled'] += 1
        pos['total_shares'] += shares
        pos['total_invested'] += shares * price
        pos['avg_price'] = pos['total_invested'] / pos['total_shares']
        pos['last_entry_time'] = datetime.now()
        pos['entries'].append({
            'time': datetime.now().isoformat(),
            'shares': shares,
            'price': price
        })

        logger.info(
            f"Panic entry recorded: {symbol} tranche {pos['tranches_filled']}/{self.panic_params.entry_tranches} "
            f"({shares} @ ${price:.2f})"
        )

    def get_panic_exposure(self) -> dict:
        """Get current panic trade exposure"""
        total_invested = sum(
            p['total_invested'] for p in self.panic_positions.values()
        )

        return {
            'total_invested': total_invested,
            'pct_of_capital': total_invested / self.total_capital if self.total_capital > 0 else 0,
            'max_allowed_pct': self.panic_params.max_panic_exposure_pct,
            'positions': len(self.panic_positions),
            'symbols': list(self.panic_positions.keys())
        }

    def format_risk_rules(self) -> str:
        """Format current panic risk rules for display"""
        p = self.panic_params

        return f"""
╔══════════════════════════════════════════════════════════════╗
║                 PANIC RISK RULES (ACTIVE)                    ║
╠══════════════════════════════════════════════════════════════╣
║  Position Size:    {p.position_size_multiplier:.0%} of normal ({p.max_position_pct:.0%} max)           ║
║  Entry Tranches:   {p.entry_tranches} parts, {p.tranche_spacing_hours}h apart                      ║
║  Wait Period:      {p.min_panic_days} days before first buy                   ║
║  Stop Width:       {p.stop_loss_atr_multiplier:.0f}x ATR (volatility adjusted)              ║
║  Max Loss/Trade:   {p.max_loss_per_trade_pct:.1%} of capital                         ║
║  Max Panic Exposure: {p.max_panic_exposure_pct:.0%} of capital                       ║
║  Max/Sector:       {p.max_correlated_positions} positions                             ║
╠══════════════════════════════════════════════════════════════╣
║  PHILOSOPHY: Survive first, profit second                    ║
║  - Don't catch falling knives                                ║
║  - Scale in slowly                                           ║
║  - Preserve capital to buy more if it drops                  ║
╚══════════════════════════════════════════════════════════════╝
"""


# Singleton
_panic_risk_manager: Optional[PanicRiskManager] = None


def get_panic_risk_manager(capital: float = 3000.0) -> PanicRiskManager:
    """Get or create panic risk manager"""
    global _panic_risk_manager
    if _panic_risk_manager is None:
        _panic_risk_manager = PanicRiskManager(capital)
    return _panic_risk_manager

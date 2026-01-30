"""
Capital Tracker - Tracks account balance and P&L over time

This is the agent's "bank account" - it knows exactly how much capital
it has at any moment, including all realized gains/losses.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, date
from dataclasses import dataclass, asdict
from loguru import logger

from config.settings import config


@dataclass
class DailySnapshot:
    """Daily account snapshot"""
    date: str
    starting_balance: float
    ending_balance: float
    realized_pnl: float
    trades_count: int
    winners: int
    losers: int


@dataclass
class TradeRecord:
    """Record of a completed trade for capital tracking"""
    timestamp: str
    symbol: str
    market_type: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    pnl_pct: float
    fees: float = 0.0


class CapitalTracker:
    """
    Tracks the agent's capital balance in real-time.

    Features:
    - Persists balance to disk (survives restarts)
    - Updates after every closed trade
    - Daily snapshots for performance review
    - Tracks win/loss streaks
    - Calculates drawdown from peak

    Usage:
        tracker = get_capital_tracker()
        tracker.record_trade_close(symbol, entry, exit, quantity, ...)
        current_balance = tracker.get_balance()
    """

    def __init__(self, data_path: str = "data"):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.state_file = self.data_path / "capital_state.json"
        self.history_file = self.data_path / "capital_history.json"

        # Load or initialize state
        self._load_state()

    def _load_state(self) -> None:
        """Load capital state from disk"""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                self.starting_capital = state.get('starting_capital', config.risk.starting_capital)
                self.current_balance = state.get('current_balance', self.starting_capital)
                self.peak_balance = state.get('peak_balance', self.current_balance)
                self.total_realized_pnl = state.get('total_realized_pnl', 0.0)
                self.total_trades = state.get('total_trades', 0)
                self.total_winners = state.get('total_winners', 0)
                self.total_losers = state.get('total_losers', 0)
                self.current_streak = state.get('current_streak', 0)  # + for wins, - for losses
                self.best_streak = state.get('best_streak', 0)
                self.worst_streak = state.get('worst_streak', 0)
                self.last_updated = state.get('last_updated')
        else:
            # Initialize with config starting capital
            self.starting_capital = config.risk.starting_capital
            self.current_balance = self.starting_capital
            self.peak_balance = self.starting_capital
            self.total_realized_pnl = 0.0
            self.total_trades = 0
            self.total_winners = 0
            self.total_losers = 0
            self.current_streak = 0
            self.best_streak = 0
            self.worst_streak = 0
            self.last_updated = None
            self._save_state()

        # Load trade history
        if self.history_file.exists():
            with open(self.history_file, 'r') as f:
                self.trade_history: List[Dict] = json.load(f)
        else:
            self.trade_history = []

        logger.info(
            f"Capital Tracker initialized: "
            f"Balance ${self.current_balance:,.2f} | "
            f"P&L ${self.total_realized_pnl:+,.2f} | "
            f"Trades: {self.total_trades}"
        )

    def _save_state(self) -> None:
        """Save capital state to disk"""
        state = {
            'starting_capital': self.starting_capital,
            'current_balance': self.current_balance,
            'peak_balance': self.peak_balance,
            'total_realized_pnl': self.total_realized_pnl,
            'total_trades': self.total_trades,
            'total_winners': self.total_winners,
            'total_losers': self.total_losers,
            'current_streak': self.current_streak,
            'best_streak': self.best_streak,
            'worst_streak': self.worst_streak,
            'last_updated': datetime.now().isoformat()
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def _save_history(self) -> None:
        """Save trade history"""
        with open(self.history_file, 'w') as f:
            json.dump(self.trade_history, f, indent=2, default=str)

    def record_trade_close(
        self,
        symbol: str,
        market_type: str,
        side: str,
        quantity: float,
        entry_price: float,
        exit_price: float,
        fees: float = 0.0
    ) -> float:
        """
        Record a completed trade and update capital.

        Returns the realized P&L.
        """
        # Calculate P&L
        if side.lower() == 'buy':
            # Long position: profit when exit > entry
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            # Short position: profit when entry > exit
            gross_pnl = (entry_price - exit_price) * quantity

        realized_pnl = gross_pnl - fees
        pnl_pct = ((exit_price / entry_price) - 1) * 100 if side.lower() == 'buy' else ((entry_price / exit_price) - 1) * 100

        # Update balance
        self.current_balance += realized_pnl
        self.total_realized_pnl += realized_pnl
        self.total_trades += 1

        # Update peak (for drawdown calculation)
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        # Update win/loss tracking
        if realized_pnl > 0:
            self.total_winners += 1
            if self.current_streak >= 0:
                self.current_streak += 1
            else:
                self.current_streak = 1
            self.best_streak = max(self.best_streak, self.current_streak)
        else:
            self.total_losers += 1
            if self.current_streak <= 0:
                self.current_streak -= 1
            else:
                self.current_streak = -1
            self.worst_streak = min(self.worst_streak, self.current_streak)

        # Record in history
        record = TradeRecord(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            market_type=market_type,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
            pnl_pct=pnl_pct,
            fees=fees
        )
        self.trade_history.append(asdict(record))

        # Save state
        self._save_state()
        self._save_history()

        # Log the update
        emoji = "+" if realized_pnl >= 0 else ""
        logger.info(
            f"CAPITAL UPDATE: {symbol} closed | "
            f"P&L: ${realized_pnl:+,.2f} ({pnl_pct:+.1f}%) | "
            f"Balance: ${self.current_balance:,.2f} | "
            f"Streak: {self.current_streak:+d}"
        )

        return realized_pnl

    def get_balance(self) -> float:
        """Get current account balance"""
        return self.current_balance

    def get_available_capital(self, positions_value: float = 0) -> float:
        """Get capital available for new trades (balance - positions)"""
        return self.current_balance - positions_value

    def get_total_return(self) -> float:
        """Get total return percentage"""
        if self.starting_capital <= 0:
            return 0.0
        return ((self.current_balance / self.starting_capital) - 1) * 100

    def get_drawdown(self) -> float:
        """Get current drawdown from peak (as percentage)"""
        if self.peak_balance <= 0:
            return 0.0
        return ((self.peak_balance - self.current_balance) / self.peak_balance) * 100

    def get_win_rate(self) -> float:
        """Get overall win rate"""
        if self.total_trades == 0:
            return 0.0
        return self.total_winners / self.total_trades

    def get_summary(self) -> Dict:
        """Get full capital summary"""
        return {
            'starting_capital': self.starting_capital,
            'current_balance': self.current_balance,
            'total_return': self.get_total_return(),
            'total_realized_pnl': self.total_realized_pnl,
            'peak_balance': self.peak_balance,
            'drawdown': self.get_drawdown(),
            'total_trades': self.total_trades,
            'winners': self.total_winners,
            'losers': self.total_losers,
            'win_rate': self.get_win_rate(),
            'current_streak': self.current_streak,
            'best_streak': self.best_streak,
            'worst_streak': self.worst_streak
        }

    def get_today_pnl(self) -> float:
        """Get today's realized P&L"""
        today = date.today().isoformat()
        today_trades = [
            t for t in self.trade_history
            if t.get('timestamp', '').startswith(today)
        ]
        return sum(t.get('realized_pnl', 0) for t in today_trades)

    def get_daily_snapshots(self, days: int = 30) -> List[DailySnapshot]:
        """Get daily performance snapshots"""
        # Group trades by day
        daily = {}
        for trade in self.trade_history:
            trade_date = trade.get('timestamp', '')[:10]
            if trade_date not in daily:
                daily[trade_date] = {
                    'pnl': 0,
                    'trades': 0,
                    'winners': 0,
                    'losers': 0
                }
            daily[trade_date]['pnl'] += trade.get('realized_pnl', 0)
            daily[trade_date]['trades'] += 1
            if trade.get('realized_pnl', 0) > 0:
                daily[trade_date]['winners'] += 1
            else:
                daily[trade_date]['losers'] += 1

        # Build snapshots
        snapshots = []
        running_balance = self.starting_capital

        for day_str in sorted(daily.keys())[-days:]:
            day_data = daily[day_str]
            starting = running_balance
            ending = starting + day_data['pnl']

            snapshots.append(DailySnapshot(
                date=day_str,
                starting_balance=starting,
                ending_balance=ending,
                realized_pnl=day_data['pnl'],
                trades_count=day_data['trades'],
                winners=day_data['winners'],
                losers=day_data['losers']
            ))

            running_balance = ending

        return snapshots

    def reset(self, new_starting_capital: Optional[float] = None) -> None:
        """Reset the tracker (use with caution!)"""
        self.starting_capital = new_starting_capital or config.risk.starting_capital
        self.current_balance = self.starting_capital
        self.peak_balance = self.starting_capital
        self.total_realized_pnl = 0.0
        self.total_trades = 0
        self.total_winners = 0
        self.total_losers = 0
        self.current_streak = 0
        self.best_streak = 0
        self.worst_streak = 0
        self.trade_history = []

        self._save_state()
        self._save_history()

        logger.warning(f"Capital tracker RESET to ${self.starting_capital:,.2f}")


# Singleton instance
_tracker_instance: Optional[CapitalTracker] = None


def get_capital_tracker() -> CapitalTracker:
    """Get or create the capital tracker instance"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = CapitalTracker()
    return _tracker_instance

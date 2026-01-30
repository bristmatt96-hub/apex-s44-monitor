"""
Trade Journal

Log every trade with context, rationale, and outcomes.
Learn from patterns - what works, what doesn't.

"A trade is not just a P&L number - it's a decision to learn from."
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
from enum import Enum
from loguru import logger


class TradeOutcome(Enum):
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    OPEN = "open"


class EmotionalState(Enum):
    CALM = "calm"
    CONFIDENT = "confident"
    ANXIOUS = "anxious"
    FOMO = "fomo"
    REVENGE = "revenge"
    GREEDY = "greedy"
    FEARFUL = "fearful"
    NEUTRAL = "neutral"


class ExitReason(Enum):
    TARGET_HIT = "target_hit"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    TIME_STOP = "time_stop"
    THESIS_BROKEN = "thesis_broken"
    TAKE_PROFIT_PARTIAL = "take_profit_partial"
    MARKET_CLOSE = "market_close"
    MANUAL = "manual"
    EUPHORIA_EXIT = "euphoria_exit"  # Exited because market was greedy
    PANIC_EXIT = "panic_exit"  # Exited due to fear (usually a mistake)


@dataclass
class TradeEntry:
    """A single trade record"""
    id: str
    symbol: str
    side: str  # "long" or "short"
    market_type: str  # "stock", "options", "etf"

    # Entry
    entry_date: str
    entry_price: float
    quantity: float
    entry_rationale: str
    strategy: str

    # Risk management
    initial_stop: Optional[float] = None
    initial_target: Optional[float] = None
    risk_reward_planned: Optional[float] = None

    # Options-specific
    strike: Optional[float] = None
    expiry: Optional[str] = None
    option_type: Optional[str] = None

    # Exit (filled when closed)
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    # Outcome
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    r_multiple: Optional[float] = None
    outcome: str = "open"

    # Self-reflection
    emotional_state_entry: str = "neutral"
    emotional_state_exit: Optional[str] = None
    lessons_learned: str = ""
    what_worked: str = ""
    what_didnt_work: str = ""
    would_take_again: Optional[bool] = None

    # Context
    market_condition: str = ""  # bull/bear/chop
    vix_at_entry: Optional[float] = None
    news_context: str = ""

    # Tags for filtering
    tags: List[str] = field(default_factory=list)


class TradeJournal:
    """
    Comprehensive trade journal for learning and improvement.

    Features:
    - Log trades with full context
    - Track emotional state (identify tilt patterns)
    - Calculate statistics by strategy/setup
    - Identify what works and what doesn't
    """

    def __init__(self, data_path: str = "portfolio/data"):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.journal_file = self.data_path / "trade_journal.json"
        self.trades: Dict[str, TradeEntry] = {}
        self._trade_counter = 0

        self._load_journal()

    def _load_journal(self) -> None:
        """Load journal from file"""
        if self.journal_file.exists():
            try:
                with open(self.journal_file, 'r') as f:
                    data = json.load(f)
                    self._trade_counter = data.get('counter', 0)
                    for trade_data in data.get('trades', []):
                        trade = TradeEntry(**trade_data)
                        self.trades[trade.id] = trade
                logger.info(f"Loaded {len(self.trades)} trades from journal")
            except Exception as e:
                logger.error(f"Error loading journal: {e}")

    def _save_journal(self) -> None:
        """Save journal to file"""
        try:
            data = {
                'counter': self._trade_counter,
                'last_updated': datetime.now().isoformat(),
                'trades': [asdict(t) for t in self.trades.values()]
            }
            with open(self.journal_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving journal: {e}")

    def _generate_id(self) -> str:
        """Generate unique trade ID"""
        self._trade_counter += 1
        return f"T{self._trade_counter:05d}"

    def log_entry(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        strategy: str,
        entry_rationale: str,
        market_type: str = "stock",
        initial_stop: Optional[float] = None,
        initial_target: Optional[float] = None,
        emotional_state: str = "neutral",
        market_condition: str = "",
        vix: Optional[float] = None,
        news_context: str = "",
        tags: List[str] = None,
        # Options
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        option_type: Optional[str] = None
    ) -> TradeEntry:
        """Log a new trade entry"""

        # Calculate planned R:R
        risk_reward = None
        if initial_stop and initial_target:
            risk = abs(entry_price - initial_stop)
            reward = abs(initial_target - entry_price)
            if risk > 0:
                risk_reward = reward / risk

        trade = TradeEntry(
            id=self._generate_id(),
            symbol=symbol.upper(),
            side=side.lower(),
            market_type=market_type.lower(),
            entry_date=datetime.now().isoformat(),
            entry_price=entry_price,
            quantity=quantity,
            entry_rationale=entry_rationale,
            strategy=strategy,
            initial_stop=initial_stop,
            initial_target=initial_target,
            risk_reward_planned=risk_reward,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            emotional_state_entry=emotional_state,
            market_condition=market_condition,
            vix_at_entry=vix,
            news_context=news_context,
            tags=tags or []
        )

        self.trades[trade.id] = trade
        self._save_journal()

        logger.info(f"Logged trade entry: {trade.id} - {symbol} {side}")
        return trade

    def log_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        emotional_state: str = "neutral",
        lessons_learned: str = "",
        what_worked: str = "",
        what_didnt_work: str = "",
        would_take_again: Optional[bool] = None
    ) -> Optional[TradeEntry]:
        """Log trade exit and calculate outcome"""

        if trade_id not in self.trades:
            logger.warning(f"Trade {trade_id} not found")
            return None

        trade = self.trades[trade_id]

        # Calculate P&L
        if trade.side == "long":
            pnl_per_unit = exit_price - trade.entry_price
        else:
            pnl_per_unit = trade.entry_price - exit_price

        if trade.market_type == "options":
            pnl = pnl_per_unit * trade.quantity * 100
        else:
            pnl = pnl_per_unit * trade.quantity

        pnl_pct = (pnl_per_unit / trade.entry_price) * 100

        # Calculate R-multiple
        r_multiple = None
        if trade.initial_stop:
            risk_per_unit = abs(trade.entry_price - trade.initial_stop)
            if risk_per_unit > 0:
                r_multiple = pnl_per_unit / risk_per_unit

        # Determine outcome
        if pnl > 0:
            outcome = TradeOutcome.WIN.value
        elif pnl < 0:
            outcome = TradeOutcome.LOSS.value
        else:
            outcome = TradeOutcome.BREAKEVEN.value

        # Update trade
        trade.exit_date = datetime.now().isoformat()
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct
        trade.r_multiple = r_multiple
        trade.outcome = outcome
        trade.emotional_state_exit = emotional_state
        trade.lessons_learned = lessons_learned
        trade.what_worked = what_worked
        trade.what_didnt_work = what_didnt_work
        trade.would_take_again = would_take_again

        self._save_journal()

        logger.info(f"Logged trade exit: {trade_id} - {outcome} ${pnl:+.2f}")
        return trade

    def get_trade(self, trade_id: str) -> Optional[TradeEntry]:
        """Get a specific trade"""
        return self.trades.get(trade_id)

    def get_open_trades(self) -> List[TradeEntry]:
        """Get all open trades"""
        return [t for t in self.trades.values() if t.outcome == "open"]

    def get_closed_trades(self, days: Optional[int] = None) -> List[TradeEntry]:
        """Get closed trades, optionally filtered by days"""
        closed = [t for t in self.trades.values() if t.outcome != "open"]

        if days:
            cutoff = datetime.now() - timedelta(days=days)
            closed = [t for t in closed if t.exit_date and
                     datetime.fromisoformat(t.exit_date) > cutoff]

        return sorted(closed, key=lambda t: t.exit_date or "", reverse=True)

    def get_trades_by_strategy(self, strategy: str) -> List[TradeEntry]:
        """Get all trades for a specific strategy"""
        return [t for t in self.trades.values()
                if t.strategy.lower() == strategy.lower()]

    def get_trades_by_symbol(self, symbol: str) -> List[TradeEntry]:
        """Get all trades for a specific symbol"""
        return [t for t in self.trades.values()
                if t.symbol.upper() == symbol.upper()]

    def get_emotional_analysis(self) -> Dict:
        """Analyze trading by emotional state"""
        closed = self.get_closed_trades()

        by_emotion = {}
        for trade in closed:
            emotion = trade.emotional_state_entry
            if emotion not in by_emotion:
                by_emotion[emotion] = {'trades': 0, 'wins': 0, 'total_pnl': 0}

            by_emotion[emotion]['trades'] += 1
            if trade.outcome == 'win':
                by_emotion[emotion]['wins'] += 1
            by_emotion[emotion]['total_pnl'] += trade.pnl or 0

        # Calculate win rates
        for emotion in by_emotion:
            total = by_emotion[emotion]['trades']
            wins = by_emotion[emotion]['wins']
            by_emotion[emotion]['win_rate'] = (wins / total * 100) if total > 0 else 0

        return by_emotion

    def get_strategy_analysis(self) -> Dict:
        """Analyze performance by strategy"""
        closed = self.get_closed_trades()

        by_strategy = {}
        for trade in closed:
            strat = trade.strategy or "unknown"
            if strat not in by_strategy:
                by_strategy[strat] = {
                    'trades': 0, 'wins': 0, 'losses': 0,
                    'total_pnl': 0, 'total_r': 0
                }

            by_strategy[strat]['trades'] += 1
            if trade.outcome == 'win':
                by_strategy[strat]['wins'] += 1
            elif trade.outcome == 'loss':
                by_strategy[strat]['losses'] += 1
            by_strategy[strat]['total_pnl'] += trade.pnl or 0
            by_strategy[strat]['total_r'] += trade.r_multiple or 0

        # Calculate metrics
        for strat in by_strategy:
            total = by_strategy[strat]['trades']
            wins = by_strategy[strat]['wins']
            by_strategy[strat]['win_rate'] = (wins / total * 100) if total > 0 else 0
            by_strategy[strat]['avg_r'] = by_strategy[strat]['total_r'] / total if total > 0 else 0

        return by_strategy

    def get_recent_lessons(self, limit: int = 5) -> List[str]:
        """Get recent lessons learned"""
        closed = self.get_closed_trades()
        lessons = []

        for trade in closed:
            if trade.lessons_learned:
                lessons.append(f"{trade.symbol}: {trade.lessons_learned}")
            if len(lessons) >= limit:
                break

        return lessons

    def format_trade_detail(self, trade: TradeEntry) -> str:
        """Format detailed view of a single trade"""
        lines = []
        lines.append(f"Trade {trade.id}: {trade.symbol} ({trade.side.upper()})")
        lines.append("-" * 40)

        lines.append(f"Strategy: {trade.strategy}")
        lines.append(f"Entry: ${trade.entry_price:.2f} x {trade.quantity}")
        lines.append(f"Date: {trade.entry_date[:10]}")

        if trade.initial_stop:
            lines.append(f"Stop: ${trade.initial_stop:.2f}")
        if trade.initial_target:
            lines.append(f"Target: ${trade.initial_target:.2f}")
        if trade.risk_reward_planned:
            lines.append(f"Planned R:R: {trade.risk_reward_planned:.1f}:1")

        lines.append(f"\nRationale: {trade.entry_rationale}")
        lines.append(f"Emotional State: {trade.emotional_state_entry}")

        if trade.outcome != "open":
            lines.append(f"\n--- EXIT ---")
            lines.append(f"Exit: ${trade.exit_price:.2f}")
            lines.append(f"Reason: {trade.exit_reason}")
            lines.append(f"P&L: ${trade.pnl:+.2f} ({trade.pnl_pct:+.1f}%)")
            if trade.r_multiple:
                lines.append(f"R-Multiple: {trade.r_multiple:+.2f}R")
            lines.append(f"Outcome: {trade.outcome.upper()}")

            if trade.lessons_learned:
                lines.append(f"\nLessons: {trade.lessons_learned}")

        return "\n".join(lines)

    def format_journal_summary(self, days: int = 30) -> str:
        """Format journal summary for display"""
        lines = []
        lines.append("=" * 60)
        lines.append("              TRADE JOURNAL SUMMARY")
        lines.append("=" * 60)

        closed = self.get_closed_trades(days)
        open_trades = self.get_open_trades()

        lines.append(f"\n  Period: Last {days} days")
        lines.append(f"  Closed Trades: {len(closed)}")
        lines.append(f"  Open Trades: {len(open_trades)}")

        if closed:
            wins = len([t for t in closed if t.outcome == 'win'])
            losses = len([t for t in closed if t.outcome == 'loss'])
            total_pnl = sum(t.pnl or 0 for t in closed)
            avg_r = sum(t.r_multiple or 0 for t in closed) / len(closed)

            lines.append(f"\n  Win Rate: {wins}/{len(closed)} ({wins/len(closed)*100:.0f}%)")
            lines.append(f"  Total P&L: ${total_pnl:+,.2f}")
            lines.append(f"  Average R: {avg_r:+.2f}R")

        # Strategy breakdown
        strat_analysis = self.get_strategy_analysis()
        if strat_analysis:
            lines.append("\n  BY STRATEGY:")
            for strat, stats in sorted(strat_analysis.items(),
                                       key=lambda x: x[1]['total_pnl'], reverse=True):
                lines.append(f"    {strat}: {stats['win_rate']:.0f}% WR, ${stats['total_pnl']:+,.0f}")

        # Emotional analysis
        emotion_analysis = self.get_emotional_analysis()
        problem_emotions = [e for e, stats in emotion_analysis.items()
                          if stats['win_rate'] < 40 and stats['trades'] >= 3]
        if problem_emotions:
            lines.append(f"\n  WARNING - Low win rate when: {', '.join(problem_emotions)}")

        # Recent lessons
        lessons = self.get_recent_lessons(3)
        if lessons:
            lines.append("\n  RECENT LESSONS:")
            for lesson in lessons:
                lines.append(f"    - {lesson[:50]}...")

        lines.append("")
        return "\n".join(lines)


# Singleton
_journal_instance: Optional[TradeJournal] = None

def get_trade_journal() -> TradeJournal:
    """Get or create trade journal instance"""
    global _journal_instance
    if _journal_instance is None:
        _journal_instance = TradeJournal()
    return _journal_instance

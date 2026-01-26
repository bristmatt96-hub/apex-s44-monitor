"""
Adaptive Weight System
Learns from trading performance and adjusts market weightings automatically
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from loguru import logger

from config.settings import config


@dataclass
class MarketPerformance:
    """Performance metrics for a market type"""
    market_type: str
    total_trades: int = 0
    winners: int = 0
    losers: int = 0
    total_pnl: float = 0.0
    avg_pnl_pct: float = 0.0
    avg_risk_reward_achieved: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0  # gross profit / gross loss
    avg_hold_time_hours: float = 0.0
    current_weight: float = 0.0
    recommended_weight: float = 0.0


class AdaptiveWeights:
    """
    Dynamically adjusts market weights based on actual trading performance.

    How it works:
    1. Tracks every trade's outcome by market type
    2. Every 24 hours, recalculates performance metrics
    3. Markets that perform better get higher weights
    4. Markets that underperform get lower weights
    5. Changes are gradual (max 15% shift per day)

    Metrics used for scoring:
    - Win rate (30%)
    - Profit factor (30%)
    - Average R:R achieved (20%)
    - Trade frequency / opportunity count (20%)
    """

    def __init__(self, data_path: str = "data"):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.history_file = self.data_path / "trade_history.json"
        self.weights_file = self.data_path / "adaptive_weights.json"

        # Load state
        self.trade_history: List[Dict] = self._load_history()
        self.current_weights: Dict[str, float] = self._load_weights()
        self.last_adaptation: Optional[datetime] = None

        # Scoring weights for the adaptation algorithm
        self.scoring = {
            'win_rate': 0.30,
            'profit_factor': 0.30,
            'avg_rr_achieved': 0.20,
            'opportunity_count': 0.20
        }

    def _load_history(self) -> List[Dict]:
        """Load trade history"""
        if self.history_file.exists():
            with open(self.history_file, 'r') as f:
                return json.load(f)
        return []

    def _save_history(self) -> None:
        """Save trade history"""
        with open(self.history_file, 'w') as f:
            json.dump(self.trade_history, f, indent=2, default=str)

    def _load_weights(self) -> Dict[str, float]:
        """Load current adaptive weights"""
        if self.weights_file.exists():
            with open(self.weights_file, 'r') as f:
                return json.load(f)

        # Start with config defaults
        return {
            'options': config.market_weights.options,
            'crypto': config.market_weights.crypto,
            'equity': config.market_weights.equities,
            'forex': config.market_weights.forex,
            'spac': config.market_weights.spacs
        }

    def _save_weights(self) -> None:
        """Save current weights"""
        with open(self.weights_file, 'w') as f:
            json.dump(self.current_weights, f, indent=2)

    def record_trade(self, trade: Dict) -> None:
        """
        Record a completed trade for performance tracking.

        Args:
            trade: Dict with keys:
                - market_type: str
                - symbol: str
                - side: str
                - entry_price: float
                - exit_price: float
                - pnl: float
                - pnl_pct: float
                - risk_reward_achieved: float
                - hold_time_hours: float
                - strategy: str
                - timestamp: str
        """
        self.trade_history.append(trade)
        self._save_history()

        logger.info(
            f"Trade recorded: {trade.get('symbol')} "
            f"({trade.get('market_type')}) "
            f"P&L: {trade.get('pnl_pct', 0):+.2f}%"
        )

    def get_market_performance(self, market_type: str, lookback_days: int = 30) -> MarketPerformance:
        """Get performance metrics for a specific market"""
        cutoff = datetime.now() - timedelta(days=lookback_days)

        trades = [
            t for t in self.trade_history
            if t.get('market_type') == market_type
            and datetime.fromisoformat(t.get('timestamp', '2000-01-01')) > cutoff
        ]

        if not trades:
            return MarketPerformance(
                market_type=market_type,
                current_weight=self.current_weights.get(market_type, 0.5)
            )

        winners = [t for t in trades if t.get('pnl', 0) > 0]
        losers = [t for t in trades if t.get('pnl', 0) <= 0]

        gross_profit = sum(t.get('pnl', 0) for t in winners)
        gross_loss = abs(sum(t.get('pnl', 0) for t in losers))

        total_pnl = sum(t.get('pnl', 0) for t in trades)
        avg_pnl_pct = sum(t.get('pnl_pct', 0) for t in trades) / len(trades)
        avg_rr = sum(t.get('risk_reward_achieved', 0) for t in trades) / len(trades)
        avg_hold = sum(t.get('hold_time_hours', 0) for t in trades) / len(trades)
        win_rate = len(winners) / len(trades) if trades else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        return MarketPerformance(
            market_type=market_type,
            total_trades=len(trades),
            winners=len(winners),
            losers=len(losers),
            total_pnl=total_pnl,
            avg_pnl_pct=avg_pnl_pct,
            avg_risk_reward_achieved=avg_rr,
            win_rate=win_rate,
            profit_factor=min(profit_factor, 10.0),  # Cap at 10
            avg_hold_time_hours=avg_hold,
            current_weight=self.current_weights.get(market_type, 0.5)
        )

    def should_adapt(self) -> bool:
        """Check if it's time to adapt weights"""
        if not config.market_weights.adaptive_enabled:
            return False

        if len(self.trade_history) < config.market_weights.min_trades_to_adapt:
            return False

        if self.last_adaptation is None:
            return True

        hours_since = (datetime.now() - self.last_adaptation).total_seconds() / 3600
        return hours_since >= config.market_weights.adapt_interval_hours

    def adapt(self) -> Dict[str, float]:
        """
        Recalculate market weights based on performance.
        Returns the new weights.
        """
        markets = ['options', 'crypto', 'equity', 'forex']
        performances = {}
        scores = {}

        # Calculate performance for each market
        for market in markets:
            perf = self.get_market_performance(market)
            performances[market] = perf

            if perf.total_trades == 0:
                # No trades yet - keep current weight
                scores[market] = self.current_weights.get(market, 0.5)
                continue

            # Score each metric (0-1 scale)
            wr_score = min(perf.win_rate, 1.0)

            pf_score = min(perf.profit_factor / 3.0, 1.0)  # 3.0 PF = perfect score

            rr_score = min(perf.avg_risk_reward_achieved / 3.0, 1.0)  # 3:1 = perfect

            # Opportunity score based on trade count relative to others
            max_trades = max(p.total_trades for p in performances.values()) or 1
            opp_score = perf.total_trades / max_trades

            # Composite score
            composite = (
                wr_score * self.scoring['win_rate'] +
                pf_score * self.scoring['profit_factor'] +
                rr_score * self.scoring['avg_rr_achieved'] +
                opp_score * self.scoring['opportunity_count']
            )

            scores[market] = composite

        # Normalize scores to weights (0.1 - 1.0 range)
        max_score = max(scores.values()) or 1
        min_score = min(scores.values())

        new_weights = {}
        for market in markets:
            if max_score == min_score:
                normalized = 0.5
            else:
                normalized = (scores[market] - min_score) / (max_score - min_score)

            # Scale to 0.2 - 1.0 range (never fully disable a market)
            target_weight = 0.2 + (normalized * 0.8)

            # Apply max shift limit
            current = self.current_weights.get(market, 0.5)
            max_shift = config.market_weights.max_weight_shift
            clamped = max(current - max_shift, min(current + max_shift, target_weight))

            new_weights[market] = round(clamped, 3)

        # Keep SPACs at 0
        new_weights['spac'] = 0.0

        # Update weights
        old_weights = self.current_weights.copy()
        self.current_weights = new_weights
        self._save_weights()
        self.last_adaptation = datetime.now()

        # Log changes
        logger.info("=" * 50)
        logger.info("ADAPTIVE WEIGHT ADJUSTMENT")
        logger.info("=" * 50)
        for market in markets:
            old = old_weights.get(market, 0.5)
            new = new_weights[market]
            perf = performances[market]
            direction = "↑" if new > old else "↓" if new < old else "="
            logger.info(
                f"  {market:10s}: {old:.3f} → {new:.3f} {direction} "
                f"(trades: {perf.total_trades}, "
                f"win: {perf.win_rate:.0%}, "
                f"PF: {perf.profit_factor:.1f})"
            )
        logger.info("=" * 50)

        # Recalculate capital allocation based on new weights
        self._update_capital_allocation(new_weights)

        return new_weights

    def _update_capital_allocation(self, weights: Dict[str, float]) -> None:
        """Recalculate capital allocation from weights"""
        # Active markets only (weight > 0)
        active = {k: v for k, v in weights.items() if v > 0}
        total_weight = sum(active.values())

        if total_weight == 0:
            return

        # Reserve stays fixed
        reserve = config.market_weights.reserve_pct
        allocatable = 1.0 - reserve

        allocations = {}
        for market, weight in active.items():
            allocations[market] = round((weight / total_weight) * allocatable, 3)

        logger.info("Capital Allocation Updated:")
        capital = config.risk.starting_capital
        for market, pct in allocations.items():
            logger.info(f"  {market:10s}: {pct:.1%} (${capital * pct:.0f})")

    def get_weight(self, market_type: str) -> float:
        """Get current weight for a market (used by ranker)"""
        return self.current_weights.get(market_type, 0.5)

    def get_all_weights(self) -> Dict[str, float]:
        """Get all current weights"""
        return self.current_weights.copy()

    def get_performance_summary(self) -> Dict[str, Dict]:
        """Get performance summary for all markets"""
        markets = ['options', 'crypto', 'equity', 'forex']
        summary = {}

        for market in markets:
            perf = self.get_market_performance(market)
            summary[market] = asdict(perf)

        return summary

    def reset_weights(self) -> None:
        """Reset to default config weights"""
        self.current_weights = {
            'options': config.market_weights.options,
            'crypto': config.market_weights.crypto,
            'equity': config.market_weights.equities,
            'forex': config.market_weights.forex,
            'spac': config.market_weights.spacs
        }
        self._save_weights()
        logger.info("Weights reset to defaults")


# Singleton
_adaptive_instance: Optional[AdaptiveWeights] = None


def get_adaptive_weights() -> AdaptiveWeights:
    """Get or create the adaptive weights instance"""
    global _adaptive_instance
    if _adaptive_instance is None:
        _adaptive_instance = AdaptiveWeights()
    return _adaptive_instance

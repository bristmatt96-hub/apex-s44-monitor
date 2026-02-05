"""
Edge Component Learner
Learns which edge score components (credit_signal, psychology, options, catalyst, pattern)
actually predict profitable trades, and adjusts their weights accordingly.

Follows the same pattern as adaptive_weights.py:
- JSON persistence
- Gradual weight shifts (max 15%/day)
- Singleton access
- 24-hour adaptation cycle with minimum trade threshold
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from loguru import logger


# Default weights matching the hardcoded values in edge_scorer.py
DEFAULT_WEIGHTS = {
    "credit_signal": 0.25,
    "psychology_alignment": 0.25,
    "options_mispricing": 0.20,
    "catalyst_clarity": 0.15,
    "pattern_match": 0.15
}

COMPONENTS = list(DEFAULT_WEIGHTS.keys())


class EdgeComponentLearner:
    """
    Learns optimal edge score component weights from trade outcomes.

    Process:
    1. Each closed trade records its edge score component breakdown + P&L
    2. Every 24 hours (if 20+ trades), recalculates component weights
    3. Components that better predict winners get higher weights
    4. Changes are gradual with safety guardrails

    Adaptation scoring (per component):
    - Win rate when component scored high (30%)
    - Average P&L contribution (30%)
    - Signal accuracy - did high score predict right direction (20%)
    - Consistency - low variance in outcomes (20%)
    """

    def __init__(self, data_path: str = "data"):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.outcomes_file = self.data_path / "edge_outcomes.json"
        self.weights_file = self.data_path / "edge_weights.json"

        # Load state
        self.outcomes: List[Dict] = self._load_outcomes()
        self.learned_weights: Dict[str, float] = self._load_weights()
        self.last_adaptation: Optional[datetime] = None

        # Load config (import here to avoid circular imports)
        self._config = None

    @property
    def config(self):
        if self._config is None:
            from config.settings import config
            self._config = config
        return self._config

    def _load_outcomes(self) -> List[Dict]:
        """Load recorded trade outcomes."""
        if self.outcomes_file.exists():
            with open(self.outcomes_file, 'r') as f:
                return json.load(f)
        return []

    def _save_outcomes(self) -> None:
        """Save trade outcomes (keep last 500)."""
        self.outcomes = self.outcomes[-500:]
        with open(self.outcomes_file, 'w') as f:
            json.dump(self.outcomes, f, indent=2, default=str)

    def _load_weights(self) -> Dict[str, float]:
        """Load learned weights, or return defaults."""
        if self.weights_file.exists():
            with open(self.weights_file, 'r') as f:
                return json.load(f)
        return DEFAULT_WEIGHTS.copy()

    def _save_weights(self) -> None:
        """Save learned weights."""
        with open(self.weights_file, 'w') as f:
            json.dump(self.learned_weights, f, indent=2)

    def record_outcome(self, trade_outcome: Dict) -> None:
        """
        Record a trade outcome with edge score component breakdown.

        Args:
            trade_outcome: Dict with keys:
                - symbol: str
                - company: str (optional)
                - pnl: float
                - pnl_pct: float
                - side: str
                - strategy: str
                - edge_score: dict with 'total_score' and 'components' keys
                - timestamp: str
        """
        edge_score = trade_outcome.get('edge_score', {})
        components = edge_score.get('components', {})

        if not components:
            logger.warning("No edge score components in trade outcome, skipping")
            return

        # Dedup check - don't record same trade twice
        trade_id = f"{trade_outcome.get('symbol')}_{trade_outcome.get('timestamp', '')}"
        for existing in self.outcomes[-50:]:
            existing_id = f"{existing.get('symbol')}_{existing.get('timestamp', '')}"
            if existing_id == trade_id:
                logger.debug(f"Duplicate trade outcome skipped: {trade_id}")
                return

        record = {
            "symbol": trade_outcome.get('symbol'),
            "company": trade_outcome.get('company', ''),
            "pnl": trade_outcome.get('pnl', 0),
            "pnl_pct": trade_outcome.get('pnl_pct', 0),
            "won": trade_outcome.get('pnl', 0) > 0,
            "side": trade_outcome.get('side', ''),
            "strategy": trade_outcome.get('strategy', ''),
            "total_score": edge_score.get('total_score', 0),
            "components": {
                comp: {
                    "score": components.get(comp, {}).get('score', 0),
                    "weight": components.get(comp, {}).get('weight', 0)
                }
                for comp in COMPONENTS
                if comp in components
            },
            "timestamp": trade_outcome.get('timestamp', datetime.now().isoformat()),
            "recorded_at": datetime.now().isoformat()
        }

        self.outcomes.append(record)
        self._save_outcomes()
        logger.info(f"Edge outcome recorded: {record['symbol']} P&L: {record['pnl_pct']:+.2f}%")

    def get_component_performance(
        self,
        component: str,
        lookback_days: int = 90
    ) -> Dict:
        """
        Get performance stats for a component over the lookback period.

        Returns dict with:
        - win_rate_when_high: win rate when this component scored >= 7
        - avg_pnl_when_high: average P&L% when this component scored high
        - signal_accuracy: correlation between score and positive outcome
        - consistency: 1 - normalized std dev of outcomes when high
        - sample_count: number of trades with this component scored high
        """
        cutoff = datetime.now() - timedelta(days=lookback_days)

        recent = [
            o for o in self.outcomes
            if datetime.fromisoformat(o.get('recorded_at', '2000-01-01')) > cutoff
            and component in o.get('components', {})
        ]

        if not recent:
            return {
                "win_rate_when_high": 0.5,
                "avg_pnl_when_high": 0.0,
                "signal_accuracy": 0.5,
                "consistency": 0.5,
                "sample_count": 0
            }

        # Trades where this component scored high (>= 7)
        high_score_trades = [
            o for o in recent
            if o['components'].get(component, {}).get('score', 0) >= 7
        ]

        if not high_score_trades:
            return {
                "win_rate_when_high": 0.5,
                "avg_pnl_when_high": 0.0,
                "signal_accuracy": 0.5,
                "consistency": 0.5,
                "sample_count": 0
            }

        # Win rate when high
        wins_when_high = sum(1 for t in high_score_trades if t.get('won', False))
        win_rate_when_high = wins_when_high / len(high_score_trades)

        # Average P&L when high
        pnls = [t.get('pnl_pct', 0) for t in high_score_trades]
        avg_pnl = sum(pnls) / len(pnls)

        # Signal accuracy: proportion of trades where high score -> positive P&L
        accurate = sum(1 for t in recent if (
            t['components'].get(component, {}).get('score', 0) >= 7
            and t.get('won', False)
        ) or (
            t['components'].get(component, {}).get('score', 0) < 5
            and not t.get('won', False)
        ))
        signal_accuracy = accurate / len(recent) if recent else 0.5

        # Consistency: 1 - normalized standard deviation
        if len(pnls) > 1:
            mean_pnl = sum(pnls) / len(pnls)
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
            std_dev = variance ** 0.5
            # Normalize: std of 10% = inconsistent, 0% = perfectly consistent
            consistency = max(0, 1 - (std_dev / 10.0))
        else:
            consistency = 0.5

        return {
            "win_rate_when_high": win_rate_when_high,
            "avg_pnl_when_high": avg_pnl,
            "signal_accuracy": signal_accuracy,
            "consistency": consistency,
            "sample_count": len(high_score_trades)
        }

    def should_adapt(self) -> bool:
        """Check if it's time to adapt edge component weights."""
        edge_config = getattr(self.config, 'edge_learning', None)
        if edge_config and not edge_config.enabled:
            return False

        min_trades = 20
        adapt_interval = 24
        if edge_config:
            min_trades = edge_config.min_trades_to_adapt
            adapt_interval = edge_config.adapt_interval_hours

        if len(self.outcomes) < min_trades:
            return False

        if self.last_adaptation is None:
            return True

        hours_since = (datetime.now() - self.last_adaptation).total_seconds() / 3600
        return hours_since >= adapt_interval

    def adapt(self) -> Dict[str, float]:
        """
        Recalculate component weights based on trade outcome data.

        Scoring per component:
        - win_rate_when_high:   30%
        - avg_pnl_contribution: 30%
        - signal_accuracy:      20%
        - consistency:          20%

        Guardrails:
        - Min weight: 5%
        - Max weight: 40%
        - Max shift: 15% per adaptation cycle
        - Weights must sum to 1.0

        Returns the new weights dict.
        """
        edge_config = getattr(self.config, 'edge_learning', None)
        lookback = 90
        max_shift = 0.15
        min_weight = 0.05
        max_weight = 0.40
        if edge_config:
            lookback = edge_config.lookback_days
            max_shift = edge_config.max_weight_shift
            min_weight = edge_config.min_component_weight
            max_weight = edge_config.max_component_weight

        raw_scores = {}

        for component in COMPONENTS:
            perf = self.get_component_performance(component, lookback_days=lookback)

            if perf['sample_count'] == 0:
                # No data - use current weight as score
                raw_scores[component] = self.learned_weights.get(
                    component, DEFAULT_WEIGHTS[component]
                )
                continue

            # Normalize metrics to 0-1
            wr = min(perf['win_rate_when_high'], 1.0)

            # Normalize avg_pnl: +5% = 1.0, -5% = 0.0
            pnl_normalized = max(0, min(1, (perf['avg_pnl_when_high'] + 5) / 10))

            sa = min(perf['signal_accuracy'], 1.0)
            con = min(perf['consistency'], 1.0)

            composite = (
                wr * 0.30 +
                pnl_normalized * 0.30 +
                sa * 0.20 +
                con * 0.20
            )

            raw_scores[component] = composite

        # Normalize raw scores to sum to 1.0
        total_raw = sum(raw_scores.values())
        if total_raw == 0:
            return self.learned_weights.copy()

        target_weights = {
            comp: score / total_raw
            for comp, score in raw_scores.items()
        }

        # Apply guardrails: clamp, max shift, re-normalize
        old_weights = self.learned_weights.copy()
        new_weights = {}

        for comp in COMPONENTS:
            target = target_weights[comp]
            current = old_weights.get(comp, DEFAULT_WEIGHTS[comp])

            # Max shift per cycle
            clamped = max(current - max_shift, min(current + max_shift, target))

            # Floor and ceiling
            clamped = max(min_weight, min(max_weight, clamped))

            new_weights[comp] = clamped

        # Re-normalize to sum to 1.0
        weight_sum = sum(new_weights.values())
        if weight_sum > 0:
            new_weights = {
                comp: round(w / weight_sum, 4)
                for comp, w in new_weights.items()
            }

        # Update state
        self.learned_weights = new_weights
        self._save_weights()
        self.last_adaptation = datetime.now()

        # Log changes
        logger.info("=" * 50)
        logger.info("EDGE COMPONENT WEIGHT ADAPTATION")
        logger.info("=" * 50)
        for comp in COMPONENTS:
            old = old_weights.get(comp, DEFAULT_WEIGHTS[comp])
            new = new_weights[comp]
            direction = "↑" if new > old else "↓" if new < old else "="
            perf = self.get_component_performance(comp)
            logger.info(
                f"  {comp:25s}: {old:.4f} → {new:.4f} {direction} "
                f"(samples: {perf['sample_count']}, "
                f"win_high: {perf['win_rate_when_high']:.0%})"
            )
        logger.info("=" * 50)

        return new_weights

    def get_current_weights(self) -> Dict[str, float]:
        """
        Get current component weights.

        Returns learned weights if enough trades have been recorded,
        otherwise returns defaults.
        """
        edge_config = getattr(self.config, 'edge_learning', None)
        min_trades = 20
        if edge_config:
            min_trades = edge_config.min_trades_to_adapt

        if len(self.outcomes) < min_trades:
            return DEFAULT_WEIGHTS.copy()

        return self.learned_weights.copy()

    def get_status(self) -> Dict:
        """Get learner status for monitoring."""
        return {
            "total_outcomes": len(self.outcomes),
            "current_weights": self.learned_weights,
            "using_learned": len(self.outcomes) >= 20,
            "last_adaptation": self.last_adaptation.isoformat() if self.last_adaptation else None,
            "should_adapt": self.should_adapt()
        }


# Singleton
_learner_instance: Optional[EdgeComponentLearner] = None


def get_edge_learner() -> EdgeComponentLearner:
    """Get or create the edge component learner instance."""
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = EdgeComponentLearner()
    return _learner_instance

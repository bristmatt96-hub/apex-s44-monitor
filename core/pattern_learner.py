"""
Pattern Learner
Grows the pattern database from trade outcomes and provides enhanced pattern matching.

Instead of relying on 4 hardcoded patterns, this module:
1. Records new patterns from every closed trade
2. Auto-detects characteristics from edge score component data
3. Provides weighted pattern matching using playbook, sector, component similarity, and track record
"""
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger


class PatternLearner:
    """
    Learns and matches trading patterns from historical outcomes.

    Pattern matching scoring:
    - Playbook match:             40%
    - Sector match:               20%
    - Component similarity:       30%
    - Outcome track record:       10%
    """

    def __init__(self, data_path: str = "data"):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.patterns_file = self.data_path / "patterns.json"
        self.patterns: List[Dict] = self._load_patterns()

    def _load_patterns(self) -> List[Dict]:
        """Load pattern database."""
        if self.patterns_file.exists():
            with open(self.patterns_file, 'r') as f:
                return json.load(f)
        return []

    def _save_patterns(self) -> None:
        """Save pattern database."""
        with open(self.patterns_file, 'w') as f:
            json.dump(self.patterns, f, indent=2, default=str)

    def record_trade_pattern(self, trade_outcome: Dict) -> None:
        """
        Extract and record a pattern from a closed trade.

        Args:
            trade_outcome: Dict with keys:
                - symbol: str
                - company: str
                - playbook: str (optional, from edge_score)
                - sector: str (optional, from edge_score)
                - pnl: float
                - pnl_pct: float
                - edge_score: dict with 'components', 'total_score'
                - strategy: str
                - exit_reason: str
                - hold_time_hours: float
        """
        edge_score = trade_outcome.get('edge_score', {})
        components = edge_score.get('components', {})

        if not components:
            logger.debug("No edge score components, skipping pattern recording")
            return

        # Dedup check
        symbol = trade_outcome.get('symbol', '')
        timestamp = trade_outcome.get('timestamp', '')
        pattern_id = f"trade_{symbol}_{timestamp}".replace(' ', '_').replace(':', '')
        for existing in self.patterns:
            if existing.get('id') == pattern_id:
                logger.debug(f"Duplicate pattern skipped: {pattern_id}")
                return

        # Determine outcome
        pnl = trade_outcome.get('pnl', 0)
        pnl_pct = trade_outcome.get('pnl_pct', 0)
        if pnl > 0:
            outcome = "success"
        elif pnl < 0:
            outcome = "failure"
        else:
            outcome = "breakeven"

        # Extract component scores
        component_scores = {
            comp: data.get('score', 0)
            for comp, data in components.items()
        }

        # Auto-detect characteristics
        characteristics = self._detect_characteristics(components)

        pattern = {
            "id": pattern_id,
            "name": f"{trade_outcome.get('company', symbol)} {datetime.now().strftime('%Y-%m')}",
            "company": trade_outcome.get('company', symbol),
            "playbook": edge_score.get('playbook', ''),
            "sector": edge_score.get('sector', 'Unknown'),
            "characteristics": characteristics,
            "outcome": outcome,
            "component_scores": component_scores,
            "pnl_pct": pnl_pct,
            "strategy": trade_outcome.get('strategy', ''),
            "exit_reason": trade_outcome.get('exit_reason', ''),
            "hold_time_hours": trade_outcome.get('hold_time_hours', 0),
            "total_score": edge_score.get('total_score', 0),
            "source": "learned",
            "recorded_at": datetime.now().isoformat()
        }

        self.patterns.append(pattern)
        self._save_patterns()
        logger.info(
            f"Pattern recorded: {pattern['name']} "
            f"({outcome}, P&L: {pnl_pct:+.2f}%)"
        )

    def _detect_characteristics(self, components: Dict) -> List[str]:
        """
        Auto-generate characteristic tags from edge score component data.

        Maps high component scores to descriptive characteristics.
        """
        tags = []

        credit = components.get('credit_signal', {})
        credit_score = credit.get('score', 0)
        if credit_score >= 8:
            tags.append("severe_credit_deterioration")
        elif credit_score >= 7:
            tags.append("strong_credit_deterioration")
        elif credit_score >= 5:
            tags.append("moderate_credit_concern")

        psych = components.get('psychology_alignment', {})
        psych_score = psych.get('score', 0)
        if psych_score >= 8:
            tags.append("extreme_market_complacency")
        elif psych_score >= 7:
            tags.append("market_complacency")
        elif psych_score >= 5:
            tags.append("partial_market_awareness")

        options = components.get('options_mispricing', {})
        options_score = options.get('score', 0)
        if options_score >= 8:
            tags.append("significant_options_mispricing")
        elif options_score >= 7:
            tags.append("options_mispricing")
        elif options_score >= 5:
            tags.append("slight_options_mispricing")

        catalyst = components.get('catalyst_clarity', {})
        catalyst_score = catalyst.get('score', 0)
        if catalyst_score >= 8:
            tags.append("imminent_catalyst")
        elif catalyst_score >= 6:
            tags.append("known_catalyst")

        pattern = components.get('pattern_match', {})
        pattern_score = pattern.get('score', 0)
        if pattern_score >= 7:
            tags.append("strong_historical_precedent")

        return tags

    def get_pattern_match_score(
        self,
        company: str,
        playbook: str,
        sector: str,
        component_scores: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Enhanced pattern matching against the full pattern database.

        Scoring breakdown:
        - Playbook match:         40%
        - Sector match:           20%
        - Component similarity:   30% (cosine-like similarity to winning patterns)
        - Outcome track record:   10%

        Returns a score 0-10.
        """
        if not self.patterns:
            return 3.0  # Default: no patterns to match

        best_match_score = 0.0
        total_weighted_score = 0.0
        match_count = 0

        for pattern in self.patterns:
            match_score = 0.0

            # Playbook match (40%)
            if pattern.get('playbook') == playbook and playbook:
                match_score += 4.0

            # Sector match (20%)
            pattern_sector = (pattern.get('sector') or '').lower()
            query_sector = (sector or '').lower()
            if pattern_sector and query_sector:
                if pattern_sector == query_sector:
                    match_score += 2.0
                elif pattern_sector in query_sector or query_sector in pattern_sector:
                    match_score += 1.0

            # Component similarity (30%)
            if component_scores and pattern.get('component_scores'):
                similarity = self._component_similarity(
                    component_scores,
                    pattern['component_scores']
                )
                match_score += similarity * 3.0

            # Outcome track record (10%)
            if pattern.get('outcome') == 'success':
                match_score += 1.0
            elif pattern.get('outcome') == 'ongoing':
                match_score += 0.5
            # failure = 0 bonus

            if match_score >= 3.0:
                total_weighted_score += match_score
                match_count += 1
                best_match_score = max(best_match_score, match_score)

        if match_count == 0:
            return 3.0

        # Blend: 60% best match, 40% average of qualifying matches
        avg_score = total_weighted_score / match_count
        blended = (best_match_score * 0.6) + (avg_score * 0.4)

        return min(10.0, round(blended, 1))

    def _component_similarity(
        self,
        scores_a: Dict[str, float],
        scores_b: Dict[str, float]
    ) -> float:
        """
        Calculate similarity between two component score profiles.
        Returns 0-1 (1 = identical).
        """
        components = [
            "credit_signal", "psychology_alignment",
            "options_mispricing", "catalyst_clarity", "pattern_match"
        ]

        diffs = []
        for comp in components:
            a = scores_a.get(comp, 5.0)
            b = scores_b.get(comp, 5.0)
            # Normalize diff to 0-1 (max possible diff is 10)
            diffs.append(abs(a - b) / 10.0)

        if not diffs:
            return 0.5

        avg_diff = sum(diffs) / len(diffs)
        return 1.0 - avg_diff

    def get_stats(self) -> Dict:
        """Get pattern database stats."""
        seed_count = sum(1 for p in self.patterns if p.get('source') == 'seed')
        learned_count = sum(1 for p in self.patterns if p.get('source') == 'learned')
        success_count = sum(1 for p in self.patterns if p.get('outcome') == 'success')
        failure_count = sum(1 for p in self.patterns if p.get('outcome') == 'failure')

        return {
            "total_patterns": len(self.patterns),
            "seed_patterns": seed_count,
            "learned_patterns": learned_count,
            "success_patterns": success_count,
            "failure_patterns": failure_count,
        }


# Singleton
_pattern_instance: Optional[PatternLearner] = None


def get_pattern_learner() -> PatternLearner:
    """Get or create the pattern learner instance."""
    global _pattern_instance
    if _pattern_instance is None:
        _pattern_instance = PatternLearner()
    return _pattern_instance

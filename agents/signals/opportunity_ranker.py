"""
Opportunity Ranker Agent
Ranks and prioritizes trading opportunities based on multiple factors
"""
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

from core.base_agent import BaseAgent, AgentMessage
from core.models import Signal, Opportunity, MarketType
from core.adaptive_weights import get_adaptive_weights
from config.settings import config


@dataclass
class ScoredOpportunity:
    """An opportunity with detailed scoring"""
    signal: Dict
    composite_score: float
    risk_reward_score: float
    confidence_score: float
    timing_score: float
    liquidity_score: float
    diversification_score: float
    reasoning: List[str] = field(default_factory=list)
    rank: int = 0


class OpportunityRanker(BaseAgent):
    """
    Ranks trading opportunities based on:
    - Risk/Reward ratio
    - Signal confidence
    - Technical analysis scores
    - ML predictions
    - Market timing
    - Portfolio diversification
    - PDT considerations (for equities)
    """

    def __init__(self, agent_config: Optional[Dict] = None):
        super().__init__("OpportunityRanker", agent_config)

        self.pending_opportunities: List[Dict] = []
        self.ranked_opportunities: List[ScoredOpportunity] = []
        self.current_positions: List[Dict] = []
        self.day_trades_used = 0
        self.recent_insider_buys: Dict[str, Dict] = {}  # symbol -> insider data
        self.recent_options_flow: Dict[str, Dict] = {}  # symbol -> unusual flow data

        # Scoring weights
        self.weights = {
            'risk_reward': 0.30,
            'confidence': 0.25,
            'timing': 0.20,
            'liquidity': 0.15,
            'diversification': 0.10
        }

        # Minimum thresholds
        self.min_risk_reward = config.signals.min_risk_reward
        self.min_confidence = config.signals.min_confidence

        # Adaptive market weights
        self.adaptive_weights = get_adaptive_weights()

    async def process(self) -> None:
        """Process and rank opportunities"""
        # Check if adaptive weights need recalculation
        if self.adaptive_weights.should_adapt():
            new_weights = self.adaptive_weights.adapt()
            logger.info(f"Weights adapted: {new_weights}")

        if not self.pending_opportunities:
            await asyncio.sleep(1)
            return

        # Score all pending opportunities
        scored = []
        for opp in self.pending_opportunities:
            scored_opp = await self._score_opportunity(opp)
            if scored_opp:
                scored.append(scored_opp)

        self.pending_opportunities.clear()

        if not scored:
            return

        # Sort by composite score
        scored.sort(key=lambda x: x.composite_score, reverse=True)

        # Assign ranks
        for i, opp in enumerate(scored):
            opp.rank = i + 1

        # Keep top opportunities
        self.ranked_opportunities = scored[:10]

        # Send top opportunities to coordinator
        await self._broadcast_rankings()

        logger.info(f"Ranked {len(scored)} opportunities. Top: {scored[0].signal.get('symbol')} ({scored[0].composite_score:.2f})")

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming messages"""
        if message.msg_type == 'rank_opportunity':
            self.pending_opportunities.append(message.payload)

        elif message.msg_type == 'update_positions':
            self.current_positions = message.payload.get('positions', [])

        elif message.msg_type == 'update_day_trades':
            self.day_trades_used = message.payload.get('count', 0)

        elif message.msg_type == 'get_top_opportunities':
            await self._send_top_opportunities(message.payload.get('count', 5))

    async def _score_opportunity(self, opportunity: Dict) -> Optional[ScoredOpportunity]:
        """Score an individual opportunity"""
        # Extract key data
        rr_ratio = opportunity.get('risk_reward_ratio', 0)
        confidence = opportunity.get('adjusted_confidence', opportunity.get('confidence', 0))
        market_type = opportunity.get('market_type', 'equity')
        symbol = opportunity.get('symbol', '')

        # Check minimum thresholds
        if rr_ratio < self.min_risk_reward:
            return None
        if confidence < self.min_confidence:
            return None

        reasoning = []

        # 1. Risk/Reward Score (0-1)
        rr_score = min(rr_ratio / 5.0, 1.0)  # Max score at 5:1
        if rr_ratio >= 3.0:
            reasoning.append(f"Excellent R:R of {rr_ratio:.1f}:1")
        elif rr_ratio >= 2.0:
            reasoning.append(f"Good R:R of {rr_ratio:.1f}:1")

        # 2. Confidence Score (0-1)
        conf_score = confidence
        if confidence >= 0.75:
            reasoning.append(f"High confidence signal ({confidence:.0%})")
        elif confidence >= 0.65:
            reasoning.append(f"Moderate confidence ({confidence:.0%})")

        # 3. Timing Score (0-1)
        timing_score = await self._calculate_timing_score(opportunity)
        if timing_score >= 0.7:
            reasoning.append("Good market timing")

        # 4. Liquidity Score (0-1)
        liquidity_score = self._calculate_liquidity_score(opportunity)
        if liquidity_score >= 0.8:
            reasoning.append("High liquidity")

        # 5. Diversification Score (0-1)
        diversification_score = self._calculate_diversification_score(opportunity)
        if diversification_score >= 0.7:
            reasoning.append("Adds diversification")

        # PDT consideration for equities
        pdt_penalty = 0
        if market_type == 'equity' and config.pdt_restricted:
            if self.day_trades_used >= 3:
                reasoning.append("PDT limit reached - swing trade only")
                pdt_penalty = 0.1  # Slight penalty for less flexibility

        # Calculate composite score
        composite = (
            rr_score * self.weights['risk_reward'] +
            conf_score * self.weights['confidence'] +
            timing_score * self.weights['timing'] +
            liquidity_score * self.weights['liquidity'] +
            diversification_score * self.weights['diversification']
        ) - pdt_penalty

        # Apply adaptive market weight
        market_weight = self.adaptive_weights.get_weight(market_type)
        composite *= (0.7 + (market_weight * 0.6))  # Range: 0.7x to 1.3x multiplier
        if market_weight >= 0.8:
            reasoning.append(f"High priority market (weight: {market_weight:.2f})")
        elif market_weight <= 0.3:
            reasoning.append(f"Low priority market (weight: {market_weight:.2f})")

        # Bonus for crypto/forex (no PDT)
        if market_type in ['crypto', 'forex']:
            composite *= 1.05
            reasoning.append("No PDT restrictions")

        # Strategy bonus (from backtest results)
        strategy_name = opportunity.get('metadata', {}).get('strategy', '')
        strategy_cfg = config.strategies
        if strategy_name:
            if strategy_cfg.is_strategy_enabled(strategy_name):
                bonus = strategy_cfg.get_strategy_bonus(strategy_name)
                composite *= bonus
                strat_data = strategy_cfg.proven_strategies.get(strategy_name, {})
                pf = strat_data.get('avg_profit_factor', 0)
                reasoning.append(f"Proven strategy: {strategy_name} (avg PF: {pf:.1f})")
            elif strategy_name in strategy_cfg.disabled_strategies:
                composite *= 0.5  # Heavy penalty for disproven strategies
                reasoning.append(f"Unproven strategy: {strategy_name} (disabled)")

        # TA bonus
        ta_scores = opportunity.get('ta_scores', {})
        if ta_scores.get('composite', 0) > 0.7:
            composite *= 1.1
            reasoning.append("Strong TA confirmation")

        # ML bonus
        ml_predictions = opportunity.get('ml_predictions', {})
        if ml_predictions.get('up_probability', 0.5) > 0.65:
            composite *= 1.08
            reasoning.append("ML predicts upside")

        # Insider buying confluence bonus
        # If insiders are buying AND we have a technical signal, that's very strong
        source = opportunity.get('source', '')
        if source == 'edgar_insider_buying':
            # Track this insider signal for confluence detection
            self.recent_insider_buys[symbol] = {
                'metadata': opportunity.get('metadata', {}),
                'timestamp': datetime.now()
            }
        elif symbol in self.recent_insider_buys:
            # Technical signal + insider buying = confluence
            insider_data = self.recent_insider_buys[symbol]
            age_hours = (datetime.now() - insider_data['timestamp']).total_seconds() / 3600
            if age_hours < 168:  # Within 7 days
                composite *= 1.15  # 15% confluence bonus
                insider_meta = insider_data.get('metadata', {})
                value = insider_meta.get('total_purchase_value', 0)
                reasoning.append(
                    f"Insider buying confluence: ${value:,.0f} purchased in last 7 days"
                )

        # Unusual options flow confluence bonus
        # If unusual bullish flow AND we have a technical buy signal, that's strong
        if source == 'unusual_options_flow':
            # Track flow signal for confluence detection
            self.recent_options_flow[symbol] = {
                'metadata': opportunity.get('metadata', {}),
                'timestamp': datetime.now()
            }
        elif symbol in self.recent_options_flow:
            # Technical signal + unusual options flow = confluence
            flow_data = self.recent_options_flow[symbol]
            age_hours = (datetime.now() - flow_data['timestamp']).total_seconds() / 3600
            if age_hours < 72:  # Within 3 days (flow is more time-sensitive)
                flow_meta = flow_data.get('metadata', {})
                flow_dir = flow_meta.get('flow_direction', '')
                # Only boost if flow direction matches signal direction
                signal_type = opportunity.get('signal_type', '')
                if (flow_dir == 'bullish' and signal_type == 'buy') or \
                   (flow_dir == 'bearish' and signal_type == 'sell'):
                    composite *= 1.12  # 12% confluence bonus
                    premium = flow_meta.get('directional_premium', 0)
                    has_sweep = flow_meta.get('has_sweep', False)
                    sweep_note = " (includes sweeps)" if has_sweep else ""
                    reasoning.append(
                        f"Options flow confluence: ${premium:,.0f} {flow_dir} premium{sweep_note}"
                    )

        return ScoredOpportunity(
            signal=opportunity,
            composite_score=min(composite, 1.0),
            risk_reward_score=rr_score,
            confidence_score=conf_score,
            timing_score=timing_score,
            liquidity_score=liquidity_score,
            diversification_score=diversification_score,
            reasoning=reasoning
        )

    async def _calculate_timing_score(self, opportunity: Dict) -> float:
        """Calculate timing score based on market conditions"""
        market_type = opportunity.get('market_type', 'equity')
        score = 0.5  # Base score

        # Time-based adjustments
        now = datetime.now()
        hour = now.hour

        if market_type == 'equity':
            # Best equity trading: 9:30-11:30 AM, 3:00-4:00 PM ET
            if 9 <= hour <= 11 or 15 <= hour <= 16:
                score += 0.2
            elif 12 <= hour <= 14:  # Lunch lull
                score -= 0.1

        elif market_type == 'crypto':
            # Crypto trades 24/7, higher volume during US hours
            if 8 <= hour <= 17:
                score += 0.1

        elif market_type == 'forex':
            # London/NY overlap: 8 AM - 12 PM ET
            if 8 <= hour <= 12:
                score += 0.2
            # Asian session overlap
            elif 0 <= hour <= 3:
                score += 0.1

        # Strategy timing
        strategy = opportunity.get('metadata', {}).get('strategy', '')
        if 'breakout' in strategy and hour in [9, 10, 15]:
            score += 0.1
        if 'mean_reversion' in strategy and 11 <= hour <= 14:
            score += 0.1

        return min(max(score, 0), 1.0)

    def _calculate_liquidity_score(self, opportunity: Dict) -> float:
        """Calculate liquidity score"""
        metadata = opportunity.get('metadata', {})

        # Volume ratio
        volume_ratio = metadata.get('volume_ratio', 1.0)

        if volume_ratio >= 2.0:
            return 0.9
        elif volume_ratio >= 1.5:
            return 0.75
        elif volume_ratio >= 1.0:
            return 0.6
        else:
            return 0.4

    def _calculate_diversification_score(self, opportunity: Dict) -> float:
        """Calculate how much this adds to portfolio diversification"""
        if not self.current_positions:
            return 0.8  # Good to open first position

        symbol = opportunity.get('symbol', '')
        market_type = opportunity.get('market_type', '')

        # Check if we already have this symbol
        for pos in self.current_positions:
            if pos.get('symbol') == symbol:
                return 0.2  # Already have position

        # Check market type concentration
        market_count = sum(1 for p in self.current_positions if p.get('market_type') == market_type)
        total_positions = len(self.current_positions)

        if total_positions == 0:
            return 0.8

        concentration = market_count / total_positions

        if concentration > 0.6:
            return 0.4  # Too concentrated
        elif concentration > 0.4:
            return 0.6
        else:
            return 0.8

    async def _broadcast_rankings(self) -> None:
        """Send rankings to coordinator"""
        rankings = []
        for opp in self.ranked_opportunities:
            rankings.append({
                'rank': opp.rank,
                'symbol': opp.signal.get('symbol'),
                'market_type': opp.signal.get('market_type'),
                'composite_score': opp.composite_score,
                'risk_reward': opp.signal.get('risk_reward_ratio'),
                'confidence': opp.confidence_score,
                'reasoning': opp.reasoning,
                'signal': opp.signal
            })

        await self.send_message(
            target='coordinator',
            msg_type='opportunity_rankings',
            payload={'rankings': rankings},
            priority=2
        )

    async def _send_top_opportunities(self, count: int) -> None:
        """Send top N opportunities"""
        top = self.ranked_opportunities[:count]

        await self.send_message(
            target='coordinator',
            msg_type='top_opportunities',
            payload={
                'opportunities': [
                    {
                        'rank': o.rank,
                        'symbol': o.signal.get('symbol'),
                        'market_type': o.signal.get('market_type'),
                        'score': o.composite_score,
                        'signal': o.signal,
                        'reasoning': o.reasoning
                    }
                    for o in top
                ]
            },
            priority=1
        )

    def get_best_opportunity(self) -> Optional[Dict]:
        """Get the current best opportunity"""
        if not self.ranked_opportunities:
            return None

        best = self.ranked_opportunities[0]
        return {
            'signal': best.signal,
            'score': best.composite_score,
            'reasoning': best.reasoning
        }

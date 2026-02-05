"""
Coordinator Agent
Orchestrates all trading agents and manages the overall trading system
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from loguru import logger

from core.base_agent import BaseAgent, AgentMessage, AgentState
from core.adaptive_weights import get_adaptive_weights
from core.edge_component_learner import get_edge_learner
from core.pattern_learner import get_pattern_learner
from core.model_manager import get_model_manager
from config.settings import config
from utils.telegram_notifier import get_notifier
from knowledge.retriever import get_retriever


class Coordinator(BaseAgent):
    """
    Master coordinator that:
    - Manages all trading agents
    - Routes messages between agents
    - Makes final trading decisions
    - Monitors system health
    - Enforces risk limits
    - Logs all activity
    """

    def __init__(self, agent_config: Optional[Dict] = None):
        super().__init__("Coordinator", agent_config)

        # Agent registry
        self.agents: Dict[str, BaseAgent] = {}

        # Signal pipeline
        self.raw_signals: List[Dict] = []
        self.analyzed_signals: List[Dict] = []
        self.ranked_opportunities: List[Dict] = []
        self.pending_executions: List[Dict] = []

        # Trade tracking
        self.executed_trades: List[Dict] = []
        self.positions: List[Dict] = []

        # System state
        self.trading_enabled = True
        self.auto_execute = False  # Manual approval by default
        self.day_trades_used = 0

        # Risk limits
        self.max_daily_loss = config.risk.max_daily_loss_pct * config.risk.starting_capital
        self.daily_pnl = 0

        # Adaptive market weights
        self.adaptive_weights = get_adaptive_weights()

        # Learning systems
        self.edge_learner = get_edge_learner()
        self.pattern_learner = get_pattern_learner()
        self.model_manager = get_model_manager()

        # Telegram notifications
        self.notifier = get_notifier()

        # Knowledge retriever (loaded once into memory)
        self.retriever = get_retriever()

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent with the coordinator"""
        self.agents[agent.name] = agent
        agent.subscribe(self._route_message)
        logger.info(f"Registered agent: {agent.name}")

    async def _route_message(self, message: AgentMessage) -> None:
        """Route message to target agent"""
        target = message.target

        if target == 'coordinator':
            await self.receive_message(message)
        elif target in self.agents:
            await self.agents[target].receive_message(message)
        elif target == 'all':
            for agent in self.agents.values():
                await agent.receive_message(message)
        else:
            logger.warning(f"Unknown target agent: {target}")

    async def process(self) -> None:
        """Main coordinator loop"""
        # Process the signal pipeline
        await self._process_signals()

        # Check for execution opportunities
        if self.trading_enabled and self.ranked_opportunities:
            await self._evaluate_executions()

        # Monitor risk limits
        await self._check_risk_limits()

        # Check if edge component weights need adaptation
        if self.edge_learner.should_adapt():
            new_weights = self.edge_learner.adapt()
            logger.info(f"Edge component weights adapted: {new_weights}")
            if self.notifier:
                weight_lines = "\n".join(
                    f"  {comp}: {w:.1%}" for comp, w in new_weights.items()
                )
                await self.notifier.notify_alert(
                    "EDGE WEIGHTS ADAPTED",
                    f"Edge component weights recalculated:\n\n"
                    f"<pre>{weight_lines}</pre>\n\n"
                    f"Based on {len(self.edge_learner.outcomes)} trade outcomes",
                    severity="info"
                )

        await asyncio.sleep(1)

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle messages from agents"""
        msg_type = message.msg_type
        payload = message.payload
        source = message.source

        logger.debug(f"Coordinator received {msg_type} from {source}")

        if msg_type == 'new_signal':
            self.raw_signals.append(payload)
            # Forward to technical analyzer
            await self._forward_for_analysis(payload)

        elif msg_type == 'signal_analyzed':
            if payload.get('validated'):
                self.analyzed_signals.append(payload)
                # Forward to ML predictor
                await self._forward_for_prediction(payload)

        elif msg_type == 'ml_prediction':
            # Forward to ranker
            await self._forward_for_ranking(payload)

        elif msg_type == 'opportunity_rankings':
            self.ranked_opportunities = payload.get('rankings', [])
            logger.info(f"Received {len(self.ranked_opportunities)} ranked opportunities")

        elif msg_type == 'trade_executed':
            self.executed_trades.append(payload)
            logger.info(f"Trade executed: {payload.get('symbol')} - {payload.get('side')}")

            # Telegram notification for executed trade
            if self.notifier:
                await self.notifier.notify_trade_entry(
                    symbol=payload.get('symbol', ''),
                    side=payload.get('side', 'buy'),
                    quantity=payload.get('quantity', 0),
                    entry_price=payload.get('entry_price', 0),
                    market_type=payload.get('market_type', 'unknown'),
                    strategy=payload.get('strategy', 'unknown'),
                    risk_reward=payload.get('risk_reward', 0),
                    confidence=payload.get('confidence', 0),
                    rationale=payload.get('rationale', 'Signal-based entry'),
                    stop_loss=payload.get('stop_loss'),
                    target=payload.get('target_price')
                )

        elif msg_type == 'trade_closed':
            # 1. Record for adaptive market weight learning
            self.adaptive_weights.record_trade({
                'market_type': payload.get('market_type'),
                'symbol': payload.get('symbol'),
                'side': payload.get('side'),
                'entry_price': payload.get('entry_price'),
                'exit_price': payload.get('exit_price'),
                'pnl': payload.get('pnl'),
                'pnl_pct': payload.get('pnl_pct'),
                'risk_reward_achieved': payload.get('risk_reward_achieved', 0),
                'hold_time_hours': payload.get('hold_time_hours', 0),
                'strategy': payload.get('strategy', 'unknown'),
                'timestamp': datetime.now().isoformat()
            })

            # 2. Record for edge component weight learning
            self.edge_learner.record_outcome(payload)

            # 3. Record for pattern database growth
            self.pattern_learner.record_trade_pattern(payload)

            # 4. Record for ML model accuracy tracking
            pnl = payload.get('pnl', 0)
            actual_direction = 'up' if pnl > 0 else 'down'
            self.model_manager.record_outcome(
                symbol=payload.get('symbol', ''),
                actual_direction=actual_direction
            )

            logger.info(
                f"Trade recorded for all learning systems: {payload.get('symbol')} "
                f"(P&L: {payload.get('pnl_pct', 0):+.2f}%)"
            )

            # Telegram notification for closed trade
            if self.notifier:
                await self.notifier.notify_trade_exit(
                    symbol=payload.get('symbol', ''),
                    side=payload.get('side', 'buy'),
                    quantity=payload.get('quantity', 0),
                    entry_price=payload.get('entry_price', 0),
                    exit_price=payload.get('exit_price', 0),
                    market_type=payload.get('market_type', 'unknown'),
                    pnl=payload.get('pnl', 0),
                    pnl_pct=payload.get('pnl_pct', 0),
                    hold_time=payload.get('hold_time', 'unknown'),
                    exit_reason=payload.get('exit_reason', 'unknown')
                )

        elif msg_type == 'positions_update':
            self.positions = payload.get('positions', [])

        elif msg_type == 'order_rejected':
            logger.warning(f"Order rejected: {payload.get('symbol')} - {payload.get('reason')}")

            if self.notifier:
                await self.notifier.notify_alert(
                    "ORDER REJECTED",
                    f"<b>{payload.get('symbol')}</b>\n"
                    f"Reason: {payload.get('reason', 'unknown')}",
                    severity="warning"
                )

    async def _forward_for_analysis(self, signal: Dict) -> None:
        """Forward signal to technical analyzer"""
        if 'TechnicalAnalyzer' in self.agents:
            await self.agents['TechnicalAnalyzer'].receive_message(
                AgentMessage(
                    source='coordinator',
                    target='TechnicalAnalyzer',
                    msg_type='analyze_signal',
                    payload=signal
                )
            )

    async def _forward_for_prediction(self, signal: Dict) -> None:
        """Forward signal to ML predictor"""
        if 'MLPredictor' in self.agents:
            await self.agents['MLPredictor'].receive_message(
                AgentMessage(
                    source='coordinator',
                    target='MLPredictor',
                    msg_type='predict',
                    payload=signal
                )
            )
        else:
            # Skip ML, go directly to ranker
            await self._forward_for_ranking(signal)

    async def _forward_for_ranking(self, signal: Dict) -> None:
        """Forward signal to opportunity ranker"""
        if 'OpportunityRanker' in self.agents:
            await self.agents['OpportunityRanker'].receive_message(
                AgentMessage(
                    source='coordinator',
                    target='OpportunityRanker',
                    msg_type='rank_opportunity',
                    payload=signal
                )
            )

    async def _process_signals(self) -> None:
        """Process signal pipeline"""
        # Clear old signals (keep last 100)
        if len(self.raw_signals) > 100:
            self.raw_signals = self.raw_signals[-50:]
        if len(self.analyzed_signals) > 100:
            self.analyzed_signals = self.analyzed_signals[-50:]

    async def _evaluate_executions(self) -> None:
        """Evaluate top opportunities for execution"""
        if not self.ranked_opportunities:
            return

        # Get top opportunity
        top = self.ranked_opportunities[0]
        score = top.get('composite_score', 0)
        symbol = top.get('symbol')
        signal = top.get('signal', {})

        # Check if already in position
        if any(p.get('symbol') == symbol for p in self.positions):
            return

        # Check if meets execution threshold
        if score < 0.6:
            return

        # Check daily loss limit
        if self.daily_pnl < -self.max_daily_loss:
            logger.warning("Daily loss limit reached - trading paused")
            self.trading_enabled = False
            return

        if self.auto_execute:
            # Auto-execute
            await self._execute_trade(signal)
        else:
            # Queue for manual review
            if signal not in self.pending_executions:
                self.pending_executions.append(signal)
                logger.info(f"Opportunity queued for review: {symbol} (score: {score:.2f})")

                # Send Telegram alert for manual approval
                if self.notifier:
                    market = signal.get('market_type', 'unknown')
                    strategy = signal.get('metadata', {}).get('strategy', signal.get('source', 'unknown'))
                    confidence = signal.get('confidence', 0)
                    entry = signal.get('entry_price', 0)
                    target_px = signal.get('target_price', 0)
                    stop = signal.get('stop_loss', 0)
                    rr = signal.get('risk_reward_ratio', 0)

                    # Get knowledge insight for this trade
                    kb_insight = ""
                    try:
                        kb_results = self.retriever.get_context_for_trade(
                            symbol=symbol,
                            signal_type=strategy,
                            market_type=market
                        )
                        if kb_results:
                            kb_insight = f"\n<b>Book Insight:</b> <i>{kb_results[0].content[:150]}...</i>\n"
                    except Exception:
                        pass

                    await self.notifier.notify_alert(
                        "TRADE OPPORTUNITY",
                        f"<b>{symbol}</b> ({market.upper()})\n\n"
                        f"<b>Score:</b> {score:.2f}/1.00\n"
                        f"<b>Strategy:</b> {strategy}\n"
                        f"<b>Confidence:</b> {confidence:.0%}\n"
                        f"<b>Entry:</b> ${entry:.2f}\n"
                        f"<b>Target:</b> ${target_px:.2f}\n"
                        f"<b>Stop:</b> ${stop:.2f}\n"
                        f"<b>Risk/Reward:</b> {rr:.1f}:1\n"
                        f"{kb_insight}\n"
                        f"Awaiting manual approval.",
                        severity="info"
                    )

    async def _execute_trade(self, signal: Dict) -> None:
        """Execute a trade"""
        if 'TradeExecutor' not in self.agents:
            logger.error("TradeExecutor not registered")
            return

        await self.agents['TradeExecutor'].receive_message(
            AgentMessage(
                source='coordinator',
                target='TradeExecutor',
                msg_type='execute_trade',
                payload=signal
            )
        )

    async def _check_risk_limits(self) -> None:
        """Monitor and enforce risk limits"""
        # Calculate current P&L
        total_pnl = sum(p.get('pnl_pct', 0) for p in self.positions)

        # Check max daily loss
        if total_pnl < -config.risk.max_daily_loss_pct * 100:
            if self.trading_enabled:
                logger.warning("Max daily loss reached - disabling trading")
                self.trading_enabled = False

                if self.notifier:
                    await self.notifier.notify_alert(
                        "RISK LIMIT HIT",
                        f"Daily loss limit reached ({config.risk.max_daily_loss_pct:.0%})\n"
                        f"Current P&L: {total_pnl:+.2f}%\n\n"
                        f"Trading has been DISABLED.\n"
                        f"Positions: {len(self.positions)}",
                        severity="error"
                    )

        # Check position count
        if len(self.positions) >= config.risk.max_positions:
            logger.info(f"Max positions ({config.risk.max_positions}) reached")

    async def approve_trade(self, signal: Dict) -> None:
        """Manually approve a trade for execution"""
        await self._execute_trade(signal)
        if signal in self.pending_executions:
            self.pending_executions.remove(signal)

    async def reject_trade(self, signal: Dict) -> None:
        """Reject a pending trade"""
        if signal in self.pending_executions:
            self.pending_executions.remove(signal)
            logger.info(f"Trade rejected: {signal.get('symbol')}")

    def set_auto_execute(self, enabled: bool) -> None:
        """Enable/disable auto-execution"""
        self.auto_execute = enabled
        logger.info(f"Auto-execute {'enabled' if enabled else 'disabled'}")

    def enable_trading(self) -> None:
        """Enable trading"""
        self.trading_enabled = True
        logger.info("Trading enabled")

    def disable_trading(self) -> None:
        """Disable trading"""
        self.trading_enabled = False
        logger.info("Trading disabled")

    async def start_all_agents(self) -> None:
        """Start all registered agents"""
        for name, agent in self.agents.items():
            await agent.start()
            logger.info(f"Started agent: {name}")

        # Start coordinator
        await self.start()

        # Notify via Telegram
        if self.notifier:
            kb_stats = self.retriever.get_stats()
            kb_line = f"<b>Knowledge:</b> {kb_stats['total_chunks']} chunks loaded" if kb_stats['total_chunks'] > 0 else "<b>Knowledge:</b> No books ingested"
            await self.notifier.notify_alert(
                "SYSTEM STARTED",
                f"APEX Trading System is LIVE\n\n"
                f"<b>Agents:</b> {len(self.agents)} registered\n"
                f"<b>Capital:</b> ${config.risk.starting_capital:,.2f}\n"
                f"<b>Auto-Execute:</b> {'ON' if self.auto_execute else 'OFF (manual approval)'}\n"
                f"<b>Trading:</b> {'ENABLED' if self.trading_enabled else 'DISABLED'}\n"
                f"{kb_line}",
                severity="success"
            )

    async def stop_all_agents(self) -> None:
        """Stop all agents"""
        # Notify via Telegram before shutdown
        if self.notifier:
            await self.notifier.notify_alert(
                "SYSTEM SHUTDOWN",
                f"APEX Trading System shutting down\n\n"
                f"<b>Trades today:</b> {len(self.executed_trades)}\n"
                f"<b>Open positions:</b> {len(self.positions)}",
                severity="warning"
            )

        # Stop coordinator first
        await self.stop()

        for name, agent in self.agents.items():
            await agent.stop()
            logger.info(f"Stopped agent: {name}")

    def get_status(self) -> Dict[str, Any]:
        """Get system status"""
        return {
            'coordinator': {
                'state': self.state.value,
                'trading_enabled': self.trading_enabled,
                'auto_execute': self.auto_execute
            },
            'agents': {
                name: agent.get_status()
                for name, agent in self.agents.items()
            },
            'signals': {
                'raw': len(self.raw_signals),
                'analyzed': len(self.analyzed_signals),
                'ranked': len(self.ranked_opportunities)
            },
            'trading': {
                'positions': len(self.positions),
                'pending_executions': len(self.pending_executions),
                'executed_today': len(self.executed_trades),
                'daily_pnl': self.daily_pnl
            }
        }

    def get_pending_trades(self) -> List[Dict]:
        """Get trades pending manual approval"""
        return self.pending_executions.copy()

    def get_top_opportunities(self, n: int = 5) -> List[Dict]:
        """Get top N opportunities"""
        return self.ranked_opportunities[:n]

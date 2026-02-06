"""
Trade Execution Agent
Handles order execution, position management, and trade tracking
"""
import asyncio
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from loguru import logger

from core.base_agent import BaseAgent, AgentMessage
from core.broker import IBBroker
from core.models import Trade, Position, OrderType, OrderStatus, MarketType
from config.settings import config
from utils.telegram_notifier import get_notifier


class TradeExecutor(BaseAgent):
    """
    Executes trades based on approved opportunities.

    Responsibilities:
    - Order execution through IB
    - Position sizing based on risk
    - Stop loss / take profit orders
    - Trade tracking and logging
    - PDT compliance for equities
    """

    def __init__(self, agent_config: Optional[Dict] = None):
        super().__init__("TradeExecutor", agent_config)

        self.broker = IBBroker()
        self.pending_orders: List[Dict] = []
        self.active_trades: List[Trade] = []
        self.positions: List[Position] = []
        self.trade_history: List[Trade] = []

        # Position sizing
        self.capital = config.risk.starting_capital
        self.max_position_pct = config.risk.max_position_pct
        self.max_positions = config.risk.max_positions

        # PDT tracking
        self.day_trades_today = 0
        self.pdt_restricted = config.pdt_restricted

        # Connection state
        self.connected = False

        # Telegram notifications
        self.notifier = get_notifier()

        # Load persisted state from previous run
        self._load_state()

    async def start(self) -> None:
        """Start executor and connect to broker"""
        await super().start()

        # Connect to Interactive Brokers
        self.connected = await self.broker.connect()

        if self.connected:
            logger.info("TradeExecutor connected to IB")
            await self._sync_positions()
        else:
            logger.warning("TradeExecutor running in simulation mode (IB not connected)")

    async def stop(self) -> None:
        """Stop executor and disconnect"""
        if self.connected:
            await self.broker.disconnect()
        await super().stop()

    async def process(self) -> None:
        """Process pending orders"""
        if not self.pending_orders:
            await asyncio.sleep(0.5)
            return

        while self.pending_orders:
            order = self.pending_orders.pop(0)

            # Validate order
            if not await self._validate_order(order):
                continue

            # Execute
            trade = await self._execute_order(order)

            if trade:
                self.active_trades.append(trade)
                self._save_state()
                await self._notify_trade_status(trade)

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming messages"""
        if message.msg_type == 'execute_trade':
            self.pending_orders.append(message.payload)
            logger.info(f"Order queued: {message.payload.get('symbol')}")

        elif message.msg_type == 'cancel_order':
            order_id = message.payload.get('order_id')
            await self._cancel_order(order_id)

        elif message.msg_type == 'close_position':
            symbol = message.payload.get('symbol')
            await self._close_position(symbol)

        elif message.msg_type == 'get_positions':
            await self._send_positions()

        elif message.msg_type == 'sync_positions':
            await self._sync_positions()

    def _resolve_side(self, order: Dict) -> str:
        """Derive trade side from order dict, falling back to signal_type"""
        if side := order.get('side'):
            return side
        signal_type = order.get('signal_type', 'buy').lower()
        if signal_type in ('sell', 'short', 'short_put', 'short_call'):
            return 'sell'
        return 'buy'

    async def _validate_order(self, order: Dict) -> bool:
        """Validate order before execution"""
        symbol = order.get('symbol')
        market_type = order.get('market_type')
        side = self._resolve_side(order)

        # Check position limits
        if len(self.positions) >= self.max_positions:
            logger.warning(f"Max positions ({self.max_positions}) reached")
            return False

        # Check if already have position in same symbol
        for pos in self.positions:
            if pos.symbol == symbol:
                logger.warning(f"Already have position in {symbol}")
                return False

        # PDT check for equity day trades
        if market_type == 'equity' and self.pdt_restricted:
            if self._is_day_trade(order) and self.day_trades_today >= 3:
                logger.warning("PDT limit reached - order rejected")
                await self.send_message(
                    target='coordinator',
                    msg_type='order_rejected',
                    payload={'symbol': symbol, 'reason': 'PDT limit'},
                    priority=2
                )
                return False

        return True

    def _is_day_trade(self, order: Dict) -> bool:
        """Check if order would be a day trade"""
        # Would need to check if we opened position today
        # Simplified: treat all equity trades as potential day trades
        return order.get('market_type') == 'equity'

    async def _execute_order(self, order: Dict) -> Optional[Trade]:
        """Execute a trade order"""
        symbol = order.get('symbol')
        market_type = MarketType(order.get('market_type', 'equity'))
        side = self._resolve_side(order)
        entry_price = order.get('entry_price', 0)
        stop_loss = order.get('stop_loss')
        target_price = order.get('target_price')

        # Calculate position size
        quantity = self._calculate_position_size(order)

        if quantity <= 0:
            logger.warning(f"Invalid position size for {symbol}")
            return None

        logger.info(f"Executing: {side.upper()} {quantity} {symbol} @ ~{entry_price:.2f}")

        if self.connected:
            # Live execution through IB
            trade = await self.broker.place_order(
                symbol=symbol,
                market_type=market_type,
                side=side,
                quantity=quantity,
                order_type=OrderType.MARKET
            )

            if trade:
                trade.metadata['stop_loss'] = stop_loss
                trade.metadata['target_price'] = target_price
                trade.metadata['signal'] = order
                trade.metadata['edge_score'] = order.get('edge_score')
                trade.metadata['entry_time'] = datetime.now().isoformat()

                # Place stop loss order
                position_side = 'short' if side == 'sell' else 'long'
                if stop_loss:
                    await self._place_stop_order(symbol, market_type, quantity, stop_loss, position_side)

                # Track day trades
                if market_type == MarketType.EQUITY:
                    self.day_trades_today += 1

                # Send Telegram notification
                await self._send_entry_notification(trade, order)

                return trade

        else:
            # Simulation mode
            trade = Trade(
                id=f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                symbol=symbol,
                market_type=market_type,
                side=side,
                quantity=quantity,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
                fill_price=entry_price,
                fill_quantity=quantity,
                filled_at=datetime.now(),
                metadata={
                    'stop_loss': stop_loss,
                    'target_price': target_price,
                    'simulated': True,
                    'signal': order,
                    'edge_score': order.get('edge_score'),
                    'entry_time': datetime.now().isoformat()
                }
            )

            # Create simulated position
            position_side = 'short' if side == 'sell' else 'long'
            position = Position(
                symbol=symbol,
                market_type=market_type,
                quantity=quantity,
                entry_price=entry_price,
                current_price=entry_price,
                entry_time=datetime.now(),
                side=position_side,
                stop_loss=stop_loss,
                take_profit=target_price
            )
            self.positions.append(position)
            self._save_state()

            logger.info(f"SIMULATED: {side.upper()} {quantity} {symbol} @ {entry_price:.2f}")

            # Send Telegram notification
            await self._send_entry_notification(trade, order)

            return trade

        return None

    async def _send_entry_notification(self, trade: Trade, order: Dict) -> None:
        """Send Telegram notification for trade entry"""
        if not self.notifier:
            return

        try:
            # Build rationale from signal data
            signal = order.get('signal', order)
            reasoning = signal.get('reasoning', [])
            if isinstance(reasoning, list):
                rationale = ' '.join(reasoning[:3]) if reasoning else "Signal matched entry criteria"
            else:
                rationale = str(reasoning) if reasoning else "Signal matched entry criteria"

            metadata = signal.get('metadata', {})
            strategy = metadata.get('strategy', signal.get('source', 'unknown'))

            await self.notifier.notify_trade_entry(
                symbol=trade.symbol,
                side=trade.side,
                quantity=trade.quantity,
                entry_price=trade.fill_price or order.get('entry_price', 0),
                market_type=trade.market_type.value,
                strategy=strategy,
                risk_reward=signal.get('risk_reward_ratio', 0),
                confidence=signal.get('confidence', 0),
                rationale=rationale,
                stop_loss=order.get('stop_loss'),
                target=order.get('target_price')
            )
        except (ValueError, TypeError, OSError) as e:
            logger.error(f"Failed to send entry notification: {e}")

    async def _send_exit_notification(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        exit_price: float,
        market_type: str,
        entry_time: datetime,
        exit_reason: str
    ) -> None:
        """Send Telegram notification for trade exit"""
        if not self.notifier:
            return

        try:
            # Calculate P&L
            if side.lower() in ('buy', 'long'):
                pnl = (exit_price - entry_price) * quantity
                pnl_pct = ((exit_price / entry_price) - 1) * 100
            else:
                pnl = (entry_price - exit_price) * quantity
                pnl_pct = ((entry_price / exit_price) - 1) * 100

            # Calculate hold time
            hold_duration = datetime.now() - entry_time
            days = hold_duration.days
            hours = hold_duration.seconds // 3600
            if days > 0:
                hold_time = f"{days}d {hours}h"
            else:
                minutes = (hold_duration.seconds % 3600) // 60
                hold_time = f"{hours}h {minutes}m"

            await self.notifier.notify_trade_exit(
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                exit_price=exit_price,
                market_type=market_type,
                pnl=pnl,
                pnl_pct=pnl_pct,
                hold_time=hold_time,
                exit_reason=exit_reason
            )
        except (ValueError, TypeError, OSError) as e:
            logger.error(f"Failed to send exit notification: {e}")

    def _calculate_position_size(self, order: Dict) -> float:
        """Calculate position size based on risk parameters"""
        entry_price = order.get('entry_price', 0)
        stop_loss = order.get('stop_loss', 0)
        market_type = order.get('market_type', 'equity')

        if entry_price <= 0:
            return 0

        # Max position value
        max_position_value = self.capital * self.max_position_pct

        # Risk-based sizing (if stop loss provided)
        if stop_loss and stop_loss < entry_price:
            risk_per_share = entry_price - stop_loss
            # Risk 1% of capital per trade
            max_risk = self.capital * 0.01
            risk_based_quantity = max_risk / risk_per_share

            # Position value constraint
            value_based_quantity = max_position_value / entry_price

            quantity = min(risk_based_quantity, value_based_quantity)
        else:
            # Simple position sizing
            quantity = max_position_value / entry_price

        # Round appropriately
        if market_type == 'crypto':
            # Crypto can have fractional quantities
            return round(quantity, 4)
        elif market_type == 'forex':
            # Forex in lots (1 lot = 100,000 units)
            # For small account, use micro lots
            return round(quantity, 2)
        else:
            # Equities - whole shares
            return int(quantity)

    async def _place_stop_order(
        self,
        symbol: str,
        market_type: MarketType,
        quantity: float,
        stop_price: float,
        position_side: str = 'long'
    ) -> None:
        """Place a stop loss order"""
        if not self.connected:
            return

        # Stop order closes the position: sell to close long, buy to close short
        stop_side = 'sell' if position_side == 'long' else 'buy'

        await self.broker.place_order(
            symbol=symbol,
            market_type=market_type,
            side=stop_side,
            quantity=quantity,
            order_type=OrderType.STOP,
            stop_price=stop_price
        )
        logger.info(f"Stop loss placed for {symbol} @ {stop_price:.2f} ({stop_side} to close {position_side})")

    async def _cancel_order(self, order_id: str) -> None:
        """Cancel an order"""
        if self.connected:
            success = await self.broker.cancel_order(order_id)
            if success:
                logger.info(f"Order {order_id} cancelled")
        else:
            # Remove from active trades in sim mode
            self.active_trades = [t for t in self.active_trades if t.id != order_id]
            self._save_state()

    async def _close_position(self, symbol: str, exit_reason: str = "Manual close") -> None:
        """Close a position and emit trade_closed for learning systems."""
        position = next((p for p in self.positions if p.symbol == symbol), None)

        if not position:
            logger.warning(f"No position found for {symbol}")
            return

        exit_price = position.current_price

        # Determine closing side from position side
        close_side = 'sell' if position.side == 'long' else 'buy'

        if self.connected:
            trade = await self.broker.place_order(
                symbol=symbol,
                market_type=position.market_type,
                side=close_side,
                quantity=position.quantity,
                order_type=OrderType.MARKET
            )
            if trade and trade.fill_price:
                exit_price = trade.fill_price
            # Remove position in live mode
            self.positions = [p for p in self.positions if p.symbol != symbol]
        else:
            # Simulation
            self.positions = [p for p in self.positions if p.symbol != symbol]
            logger.info(f"SIMULATED: Closed {position.side} position in {symbol}")

        # Send exit notification
        await self._send_exit_notification(
            symbol=symbol,
            side=position.side,
            quantity=position.quantity,
            entry_price=position.entry_price,
            exit_price=exit_price,
            market_type=position.market_type.value,
            entry_time=position.entry_time,
            exit_reason=exit_reason
        )

        # Find the matching active trade and move to history
        closed_trade = None
        for t in self.active_trades:
            if t.symbol == symbol:
                closed_trade = t
                break

        if closed_trade:
            self.active_trades.remove(closed_trade)
            self.trade_history.append(closed_trade)
            self._save_state()

        # Calculate P&L using actual position side
        if position.side == 'long':
            pnl = (exit_price - position.entry_price) * position.quantity
            pnl_pct = ((exit_price / position.entry_price) - 1) * 100 if position.entry_price > 0 else 0
        else:
            pnl = (position.entry_price - exit_price) * position.quantity
            pnl_pct = ((position.entry_price / exit_price) - 1) * 100 if exit_price > 0 else 0

        # Calculate hold time
        hold_duration = datetime.now() - position.entry_time
        hold_time_hours = hold_duration.total_seconds() / 3600

        # Calculate risk/reward achieved
        stop_loss = None
        edge_score_data = None
        strategy = 'unknown'
        company = symbol

        if closed_trade and closed_trade.metadata:
            stop_loss = closed_trade.metadata.get('stop_loss')
            edge_score_data = closed_trade.metadata.get('edge_score')
            signal = closed_trade.metadata.get('signal', {})
            strategy = signal.get('metadata', {}).get('strategy', signal.get('source', 'unknown'))
            if edge_score_data:
                company = edge_score_data.get('company', symbol)

        risk_reward_achieved = 0
        if stop_loss and position.entry_price != stop_loss:
            risk = abs(position.entry_price - stop_loss)
            reward = abs(exit_price - position.entry_price)
            risk_reward_achieved = round(reward / risk, 2) if risk > 0 else 0

        # Emit trade_closed message to coordinator for all learning systems
        await self.send_message(
            target='coordinator',
            msg_type='trade_closed',
            payload={
                'symbol': symbol,
                'company': company,
                'market_type': position.market_type.value,
                'side': position.side,
                'quantity': position.quantity,
                'entry_price': position.entry_price,
                'exit_price': exit_price,
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'risk_reward_achieved': risk_reward_achieved,
                'hold_time_hours': round(hold_time_hours, 2),
                'hold_time': f"{int(hold_time_hours)}h {int((hold_time_hours % 1) * 60)}m",
                'strategy': strategy,
                'exit_reason': exit_reason,
                'edge_score': edge_score_data,
                'timestamp': datetime.now().isoformat()
            },
            priority=1
        )
        logger.info(f"trade_closed emitted for {symbol} (P&L: {pnl_pct:+.2f}%)")

    async def _sync_positions(self) -> None:
        """Sync positions from broker"""
        if self.connected:
            self.positions = await self.broker.get_positions()
            self._save_state()
            logger.info(f"Synced {len(self.positions)} positions from IB")

    async def _send_positions(self) -> None:
        """Send current positions to coordinator"""
        await self.send_message(
            target='coordinator',
            msg_type='positions_update',
            payload={
                'positions': [
                    {
                        'symbol': p.symbol,
                        'market_type': p.market_type.value,
                        'quantity': p.quantity,
                        'entry_price': p.entry_price,
                        'current_price': p.current_price,
                        'side': p.side,
                        'pnl_pct': p.pnl_pct,
                        'stop_loss': p.stop_loss,
                        'take_profit': p.take_profit
                    }
                    for p in self.positions
                ],
                'count': len(self.positions)
            },
            priority=3
        )

    async def _notify_trade_status(self, trade: Trade) -> None:
        """Notify coordinator of trade execution"""
        await self.send_message(
            target='coordinator',
            msg_type='trade_executed',
            payload={
                'trade_id': trade.id,
                'symbol': trade.symbol,
                'market_type': trade.market_type.value,
                'side': trade.side,
                'quantity': trade.quantity,
                'fill_price': trade.fill_price,
                'status': trade.status.value,
                'timestamp': trade.filled_at.isoformat() if trade.filled_at else None
            },
            priority=1
        )

    # --- State persistence ---

    def _state_file(self) -> Path:
        """Path to state persistence file"""
        path = Path("data")
        path.mkdir(parents=True, exist_ok=True)
        return path / "executor_state.json"

    def _serialize_trade(self, trade: Trade) -> Dict:
        """Serialize a Trade to dict for JSON storage"""
        return {
            'id': trade.id,
            'symbol': trade.symbol,
            'market_type': trade.market_type.value,
            'side': trade.side,
            'quantity': trade.quantity,
            'order_type': trade.order_type.value,
            'limit_price': trade.limit_price,
            'stop_price': trade.stop_price,
            'status': trade.status.value,
            'fill_price': trade.fill_price,
            'fill_quantity': trade.fill_quantity,
            'commission': trade.commission,
            'created_at': trade.created_at.isoformat(),
            'filled_at': trade.filled_at.isoformat() if trade.filled_at else None,
            'signal_id': trade.signal_id,
            'metadata': trade.metadata
        }

    def _deserialize_trade(self, data: Dict) -> Trade:
        """Deserialize a dict back to Trade"""
        return Trade(
            id=data['id'],
            symbol=data['symbol'],
            market_type=MarketType(data['market_type']),
            side=data['side'],
            quantity=data['quantity'],
            order_type=OrderType(data['order_type']),
            limit_price=data.get('limit_price'),
            stop_price=data.get('stop_price'),
            status=OrderStatus(data['status']),
            fill_price=data.get('fill_price'),
            fill_quantity=data.get('fill_quantity'),
            commission=data.get('commission', 0.0),
            created_at=datetime.fromisoformat(data['created_at']),
            filled_at=datetime.fromisoformat(data['filled_at']) if data.get('filled_at') else None,
            signal_id=data.get('signal_id'),
            metadata=data.get('metadata', {})
        )

    def _serialize_position(self, pos: Position) -> Dict:
        """Serialize a Position to dict for JSON storage"""
        return {
            'symbol': pos.symbol,
            'market_type': pos.market_type.value,
            'quantity': pos.quantity,
            'entry_price': pos.entry_price,
            'current_price': pos.current_price,
            'entry_time': pos.entry_time.isoformat(),
            'side': pos.side,
            'stop_loss': pos.stop_loss,
            'take_profit': pos.take_profit,
            'unrealized_pnl': pos.unrealized_pnl,
            'realized_pnl': pos.realized_pnl
        }

    def _deserialize_position(self, data: Dict) -> Position:
        """Deserialize a dict back to Position"""
        return Position(
            symbol=data['symbol'],
            market_type=MarketType(data['market_type']),
            quantity=data['quantity'],
            entry_price=data['entry_price'],
            current_price=data['current_price'],
            entry_time=datetime.fromisoformat(data['entry_time']),
            side=data.get('side', 'long'),
            stop_loss=data.get('stop_loss'),
            take_profit=data.get('take_profit'),
            unrealized_pnl=data.get('unrealized_pnl', 0.0),
            realized_pnl=data.get('realized_pnl', 0.0)
        )

    def _load_state(self) -> None:
        """Load persisted state from disk"""
        state_file = self._state_file()
        if not state_file.exists():
            return

        try:
            with open(state_file, 'r') as f:
                state = json.load(f)

            self.active_trades = [self._deserialize_trade(t) for t in state.get('active_trades', [])]
            self.positions = [self._deserialize_position(p) for p in state.get('positions', [])]
            self.trade_history = [self._deserialize_trade(t) for t in state.get('trade_history', [])]

            logger.info(
                f"State restored: {len(self.active_trades)} active trades, "
                f"{len(self.positions)} positions, {len(self.trade_history)} history"
            )
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            logger.error(f"Failed to load executor state: {e}")

    def _save_state(self) -> None:
        """Save current state to disk"""
        state = {
            'active_trades': [self._serialize_trade(t) for t in self.active_trades],
            'positions': [self._serialize_position(p) for p in self.positions],
            'trade_history': [self._serialize_trade(t) for t in self.trade_history[-100:]],
            'saved_at': datetime.now().isoformat()
        }

        try:
            with open(self._state_file(), 'w') as f:
                json.dump(state, f, indent=2, default=str)
        except OSError as e:
            logger.error(f"Failed to save executor state: {e}")

    def get_portfolio_value(self) -> float:
        """Get total portfolio value"""
        positions_value = sum(p.market_value for p in self.positions)
        return self.capital + positions_value

    def get_unrealized_pnl(self) -> float:
        """Get total unrealized P&L"""
        return sum(p.unrealized_pnl for p in self.positions)

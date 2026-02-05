# Layer 5: Decision & Execution

## Overview

The Decision & Execution layer handles the final steps of the signal pipeline: deciding whether to execute a trade and interfacing with the broker to place orders. It consists of two main components:

1. **Coordinator** — The central orchestrator that makes execution decisions
2. **TradeExecutor** — The broker interface that places and manages orders

**Locations**:
- `agents/coordinator.py`
- `agents/execution/trade_executor.py`

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ OpportunityRanker│────▶│   Coordinator   │────▶│  TradeExecutor  │
│    (Scored      │     │   (Decision)    │     │   (Broker)      │
│    Signals)     │     │                 │     │                 │
└─────────────────┘     └────────┬────────┘     └────────┬────────┘
                                 │                       │
                    ┌────────────┴────────────┐          │
                    ▼                         ▼          ▼
            ┌───────────┐            ┌───────────┐  ┌─────────┐
            │   Auto    │            │  Manual   │  │   IB    │
            │  Execute  │            │  Approval │  │ Gateway │
            └───────────┘            │ (Telegram)│  └─────────┘
                                     └───────────┘
```

---

## Coordinator

The Coordinator is the central hub of the APEX system. It:
- Routes signals between agents
- Makes execution decisions
- Manages the main event loop
- Coordinates learning system updates

### Initialization

```python
class Coordinator(BaseAgent):
    def __init__(self, config: Optional[Dict] = None):
        super().__init__("Coordinator", config)

        # Agent references
        self.scanners: List[BaseScanner] = []
        self.technical_analyzer = None
        self.ml_predictor = None
        self.opportunity_ranker = None
        self.trade_executor = None

        # Signal storage
        self.raw_signals: List[Dict] = []
        self.validated_signals: List[Dict] = []
        self.ranked_opportunities: List[Dict] = []

        # Learning systems
        self.adaptive_weights = AdaptiveWeights()
        self.edge_learner = EdgeComponentLearner()
        self.pattern_learner = PatternLearner()

        # Execution mode
        self.auto_execute = config.get('auto_execute', False)

        # Learning check throttle (Fix #4 from recommendations)
        self._last_learning_check: Optional[datetime] = None
        self._learning_check_interval = 300  # 5 minutes
```

### Main Process Loop

```python
async def process(self) -> None:
    while self.running:
        # 1. Check for new signals from scanners
        await self._process_incoming_signals()

        # 2. Process validated signals
        await self._process_validated_signals()

        # 3. Process ranked opportunities
        await self._process_ranked_opportunities()

        # 4. Check learning systems (throttled)
        await self._check_learning_systems()

        # 5. Brief sleep to prevent busy loop
        await asyncio.sleep(1)
```

### Signal Routing

```python
async def _process_incoming_signals(self) -> None:
    while self.raw_signals:
        signal = self.raw_signals.pop(0)

        # Send to technical analyzer
        await self.send_message(
            target='TechnicalAnalyzer',
            msg_type='analyze_signal',
            payload=signal,
            priority=2
        )

async def _process_validated_signals(self) -> None:
    while self.validated_signals:
        signal = self.validated_signals.pop(0)

        # Send to ML predictor
        await self.send_message(
            target='MLPredictor',
            msg_type='predict',
            payload=signal,
            priority=2
        )

async def _process_ml_predictions(self, prediction: Dict) -> None:
    # Score with opportunity ranker
    score = self.opportunity_ranker.rank(prediction, self.positions)
    prediction['opportunity_score'] = score

    if self.opportunity_ranker.is_tradeable(prediction):
        self.ranked_opportunities.append(prediction)
```

### Execution Decision

```python
async def _process_ranked_opportunities(self) -> None:
    if not self.ranked_opportunities:
        return

    # Sort by opportunity score
    self.ranked_opportunities.sort(
        key=lambda x: x.get('opportunity_score', 0),
        reverse=True
    )

    for opportunity in self.ranked_opportunities:
        if self.auto_execute:
            # Direct execution
            await self._execute_opportunity(opportunity)
        else:
            # Queue for manual approval
            await self._queue_for_approval(opportunity)

    self.ranked_opportunities.clear()

async def _execute_opportunity(self, opportunity: Dict) -> None:
    await self.send_message(
        target='TradeExecutor',
        msg_type='execute',
        payload=opportunity,
        priority=1  # High priority
    )

async def _queue_for_approval(self, opportunity: Dict) -> None:
    # Send Telegram notification
    await self.send_message(
        target='TelegramNotifier',
        msg_type='opportunity_notification',
        payload={
            'opportunity': opportunity,
            'approval_required': True
        },
        priority=2
    )
```

### Learning System Checks (Throttled)

```python
async def _check_learning_systems(self) -> None:
    now = datetime.now()

    # Throttle: check every 5 minutes, not every 1 second
    if (self._last_learning_check is None or
            (now - self._last_learning_check).total_seconds() >= self._learning_check_interval):

        self._last_learning_check = now

        if self.edge_learner.should_adapt():
            adaptations = self.edge_learner.adapt()

            if adaptations:
                # Notify about weight changes
                await self.send_message(
                    target='TelegramNotifier',
                    msg_type='weight_adaptation',
                    payload=adaptations,
                    priority=3
                )
```

---

## TradeExecutor

The TradeExecutor interfaces with Interactive Brokers to place and manage orders.

### Initialization

```python
class TradeExecutor(BaseAgent):
    def __init__(self, config: Optional[Dict] = None):
        super().__init__("TradeExecutor", config)

        # Broker connection
        self.broker = IBBroker(config)
        self.simulation_mode = config.get('simulation_mode', True)

        # Position tracking
        self.active_trades: List[Trade] = []
        self.positions: List[Position] = []
        self.pending_orders: List[Dict] = []
        self.trade_history: List[Trade] = []

        # Risk parameters
        self.capital = config.get('capital', 3000)
        self.max_position_pct = config.get('max_position_pct', 0.05)
        self.max_risk_pct = config.get('max_risk_pct', 0.01)
        self.max_positions = config.get('max_positions', 10)

        # PDT tracking
        self.day_trades_count = 0
        self.day_trade_limit = 3

        # Load persisted state (Fix #3 from recommendations)
        self._load_state()
```

### Position Sizing

The executor sizes positions based on two constraints:

```python
def _calculate_position_size(self, signal: Dict) -> int:
    entry = signal.get('entry_price')
    stop = signal.get('stop_loss')
    risk_per_share = abs(entry - stop)

    # Constraint 1: Risk-based sizing
    # Risk no more than 1% of capital per trade
    max_risk_amount = self.capital * self.max_risk_pct
    shares_by_risk = int(max_risk_amount / risk_per_share)

    # Constraint 2: Capital-based sizing
    # No more than 5% of capital per position
    max_position_value = self.capital * self.max_position_pct
    shares_by_capital = int(max_position_value / entry)

    # Take the smaller of the two
    shares = min(shares_by_risk, shares_by_capital)

    # Minimum 1 share
    return max(shares, 1)
```

**Example**:
- Capital: $3,000
- Entry: $50, Stop: $48 (risk = $2/share)
- Risk sizing: $30 max risk / $2 = 15 shares
- Capital sizing: $150 max / $50 = 3 shares
- **Result**: 3 shares

### Order Execution

```python
async def _execute_order(self, signal: Dict) -> Optional[Trade]:
    symbol = signal.get('symbol')
    side = 'buy' if signal.get('signal_type') in ['BUY', 'LONG_CALL'] else 'sell'
    quantity = self._calculate_position_size(signal)

    # Determine position side (Fix #2 from recommendations)
    position_side = 'short' if side == 'sell' else 'long'

    if self.simulation_mode:
        # Simulated execution
        fill_price = signal.get('entry_price')
        order_id = f"SIM-{datetime.now().timestamp()}"

        trade = Trade(
            symbol=symbol,
            market_type=signal.get('market_type'),
            side=side,
            quantity=quantity,
            entry_price=fill_price,
            order_id=order_id,
            status=OrderStatus.FILLED
        )

        position = Position(
            symbol=symbol,
            quantity=quantity,
            entry_price=fill_price,
            side=position_side,  # Now tracks long/short
            current_price=fill_price
        )

        self.positions.append(position)
        self.active_trades.append(trade)
        self._save_state()

        return trade

    else:
        # Live execution via IB
        order_result = await self.broker.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type='MARKET'
        )

        if order_result.get('filled'):
            # Place stop loss order
            await self._place_stop_order(
                symbol=symbol,
                stop_price=signal.get('stop_loss'),
                quantity=quantity,
                position_side=position_side
            )

            # ... create Trade and Position objects ...

        return trade
```

### Stop Loss Management

```python
async def _place_stop_order(
    self,
    symbol: str,
    stop_price: float,
    quantity: int,
    position_side: str = 'long'
) -> None:
    # Determine stop order side (opposite of position)
    stop_side = 'sell' if position_side == 'long' else 'buy'

    if self.simulation_mode:
        self.pending_orders.append({
            'symbol': symbol,
            'type': 'STOP',
            'side': stop_side,
            'quantity': quantity,
            'stop_price': stop_price
        })
    else:
        await self.broker.place_order(
            symbol=symbol,
            side=stop_side,
            quantity=quantity,
            order_type='STOP',
            stop_price=stop_price
        )
```

### Position Closing

```python
async def _close_position(self, position: Position, reason: str = 'manual') -> None:
    # Determine close side based on position side (Fix #2)
    close_side = 'sell' if position.side == 'long' else 'buy'

    if self.simulation_mode:
        # Get current price (would be from data feed in live)
        current_price = position.current_price

        # Calculate P&L using position side
        if position.side == 'short':
            pnl = (position.entry_price - current_price) * position.quantity
        else:
            pnl = (current_price - position.entry_price) * position.quantity

        pnl_pct = pnl / (position.entry_price * position.quantity) * 100

    else:
        # Live close via broker
        result = await self.broker.place_order(
            symbol=position.symbol,
            side=close_side,
            quantity=position.quantity,
            order_type='MARKET'
        )
        current_price = result.get('fill_price')
        pnl = result.get('realized_pnl')
        pnl_pct = position.pnl_pct

    # Remove from positions
    self.positions.remove(position)

    # Record in history
    trade = self._find_matching_trade(position.symbol)
    if trade:
        trade.exit_price = current_price
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct
        trade.exit_reason = reason
        trade.status = OrderStatus.CLOSED
        self.trade_history.append(trade)
        self.active_trades.remove(trade)

    # Send exit notification
    await self._send_exit_notification(position, pnl, pnl_pct, reason)

    # Notify learning systems
    await self._notify_trade_closed(trade)

    # Persist state
    self._save_state()
```

### PDT Compliance

```python
def _check_pdt_compliance(self, symbol: str) -> bool:
    """Check if trade would violate PDT rule"""
    if self.capital >= 25000:
        return True  # No PDT restrictions

    # Check if this would be a day trade
    for position in self.positions:
        if position.symbol == symbol:
            # Already have a position - selling would be day trade
            entry_date = position.entry_time.date()
            if entry_date == datetime.now().date():
                # Would be same-day round trip
                if self.day_trades_count >= self.day_trade_limit:
                    logger.warning(f"PDT limit reached ({self.day_trade_limit})")
                    return False

    return True

async def _execute_order(self, signal: Dict) -> Optional[Trade]:
    # Check PDT before executing
    if not self._check_pdt_compliance(signal.get('symbol')):
        await self._send_pdt_warning(signal)
        return None

    # ... rest of execution logic ...
```

---

## State Persistence

Added in Fix #3 to survive restarts:

### Serialization

```python
def _serialize_trade(self, trade: Trade) -> Dict:
    return {
        'symbol': trade.symbol,
        'market_type': trade.market_type.value if isinstance(trade.market_type, Enum) else trade.market_type,
        'side': trade.side,
        'quantity': trade.quantity,
        'entry_price': trade.entry_price,
        'exit_price': trade.exit_price,
        'stop_loss': trade.stop_loss,
        'target_price': trade.target_price,
        'order_id': trade.order_id,
        'status': trade.status.value if isinstance(trade.status, Enum) else trade.status,
        'entry_time': trade.entry_time.isoformat() if trade.entry_time else None,
        'exit_time': trade.exit_time.isoformat() if trade.exit_time else None,
        'pnl': trade.pnl,
        'pnl_pct': trade.pnl_pct,
        'exit_reason': trade.exit_reason
    }

def _serialize_position(self, pos: Position) -> Dict:
    return {
        'symbol': pos.symbol,
        'quantity': pos.quantity,
        'entry_price': pos.entry_price,
        'current_price': pos.current_price,
        'side': pos.side,  # Now includes side
        'entry_time': pos.entry_time.isoformat() if pos.entry_time else None
    }
```

### Load/Save State

```python
def _load_state(self) -> None:
    state_file = Path('data/executor_state.json')
    if not state_file.exists():
        return

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)

        self.active_trades = [self._deserialize_trade(t) for t in state.get('active_trades', [])]
        self.positions = [self._deserialize_position(p) for p in state.get('positions', [])]
        self.trade_history = [self._deserialize_trade(t) for t in state.get('trade_history', [])]

        logger.info(f"Loaded state: {len(self.positions)} positions, {len(self.active_trades)} active trades")

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error loading state: {e}")

def _save_state(self) -> None:
    state_file = Path('data/executor_state.json')
    state_file.parent.mkdir(parents=True, exist_ok=True)

    state = {
        'active_trades': [self._serialize_trade(t) for t in self.active_trades],
        'positions': [self._serialize_position(p) for p in self.positions],
        'trade_history': [self._serialize_trade(t) for t in self.trade_history[-100:]],  # Keep last 100
        'saved_at': datetime.now().isoformat()
    }

    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
```

### Save Triggers

State is saved after every mutation:
- After adding a trade to `active_trades`
- After adding a position to `positions`
- After closing a position
- After adding to `trade_history`
- After syncing with broker
- After canceling an order

---

## Position Model

Updated in Fix #2 to track long/short:

```python
@dataclass
class Position:
    symbol: str
    quantity: int
    entry_price: float
    current_price: float
    side: str = 'long'  # 'long' or 'short'
    entry_time: Optional[datetime] = None

    @property
    def pnl(self) -> float:
        if self.side == 'short':
            return (self.entry_price - self.current_price) * self.quantity
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def pnl_pct(self) -> float:
        if self.side == 'short':
            return ((self.entry_price - self.current_price) / self.entry_price) * 100
        return ((self.current_price - self.entry_price) / self.entry_price) * 100
```

---

## Broker Integration

### IBBroker Class

```python
class IBBroker:
    def __init__(self, config: Dict):
        self.host = config.get('ib_host', '127.0.0.1')
        self.port = config.get('ib_port', 7497)  # TWS paper: 7497, live: 7496
        self.client_id = config.get('ib_client_id', 1)
        self.connected = False

    async def connect(self) -> bool:
        try:
            # Connect to IB Gateway/TWS
            self.ib = IB()
            await self.ib.connectAsync(self.host, self.port, self.client_id)
            self.connected = True
            return True
        except (ConnectionError, OSError, TimeoutError) as e:
            logger.error(f"IB connection failed: {e}")
            return False

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = 'MARKET',
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> Dict:
        contract = Stock(symbol, 'SMART', 'USD')

        if order_type == 'MARKET':
            order = MarketOrder(side.upper(), quantity)
        elif order_type == 'LIMIT':
            order = LimitOrder(side.upper(), quantity, limit_price)
        elif order_type == 'STOP':
            order = StopOrder(side.upper(), quantity, stop_price)

        trade = self.ib.placeOrder(contract, order)
        await asyncio.sleep(0.5)  # Allow time for fill

        return {
            'order_id': trade.order.orderId,
            'filled': trade.orderStatus.status == 'Filled',
            'fill_price': trade.orderStatus.avgFillPrice,
            'quantity': trade.orderStatus.filled
        }

    async def get_positions(self) -> List[Position]:
        positions = []
        for pos in self.ib.positions():
            # Infer side from position sign
            position_side = 'short' if pos.position < 0 else 'long'
            qty = abs(pos.position)

            positions.append(Position(
                symbol=pos.contract.symbol,
                quantity=qty,
                entry_price=pos.avgCost,
                current_price=pos.avgCost,  # Would update from market data
                side=position_side
            ))
        return positions
```

---

## Notifications

### Entry Notification

```python
async def _send_entry_notification(self, trade: Trade, position: Position) -> None:
    await self.send_message(
        target='TelegramNotifier',
        msg_type='trade_entry',
        payload={
            'symbol': trade.symbol,
            'side': position.side,
            'quantity': position.quantity,
            'entry_price': trade.entry_price,
            'stop_loss': trade.stop_loss,
            'target_price': trade.target_price,
            'risk_reward': trade.metadata.get('risk_reward_ratio'),
            'strategy': trade.metadata.get('strategy')
        },
        priority=1
    )
```

### Exit Notification

```python
async def _send_exit_notification(
    self,
    position: Position,
    pnl: float,
    pnl_pct: float,
    reason: str
) -> None:
    emoji = "💰" if pnl > 0 else "📉"

    await self.send_message(
        target='TelegramNotifier',
        msg_type='trade_exit',
        payload={
            'symbol': position.symbol,
            'side': position.side,
            'quantity': position.quantity,
            'entry_price': position.entry_price,
            'exit_price': position.current_price,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'reason': reason,
            'emoji': emoji
        },
        priority=1
    )
```

---

## Error Handling

```python
async def _execute_order(self, signal: Dict) -> Optional[Trade]:
    try:
        # ... execution logic ...
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"Broker connection error: {e}")
        await self._send_error_notification(f"Execution failed: {e}")
        return None
    except (ValueError, TypeError) as e:
        logger.error(f"Order validation error: {e}")
        return None
```

---

## Future Improvements

1. **Bracket Orders**: Place entry, stop, and target as a single OCO order

2. **Trailing Stops**: Implement trailing stop logic for locking in profits

3. **Partial Exits**: Scale out of positions at multiple targets

4. **Order Types**: Add limit orders for better fills during volatility

5. **Retry Logic**: Automatic retry on transient broker failures

6. **Position Reconciliation**: Regular check that local state matches broker

7. **Risk Dashboard**: Real-time P&L and exposure monitoring

"""
Position Monitor - Manages open positions with smart exits

Features:
- Partial profit taking (sell portion at first target)
- Move stop to breakeven after first take profit
- Trailing stops on remaining position
- Time-based alerts (optional)
"""
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from loguru import logger

from core.models import Position, MarketType
from config.settings import config


@dataclass
class ManagedPosition:
    """A position with smart exit management"""
    position: Position

    # Exit configuration
    partial_take_profit_pct: float = 0.50      # Sell 50% at first target
    first_target_rr: float = 1.0              # First target at 1:1 R:R
    trailing_stop_pct: float = 0.02           # 2% trailing stop
    trailing_start_rr: float = 1.5            # Start trailing after 1.5:1 R:R

    # State tracking
    initial_quantity: float = 0.0
    remaining_quantity: float = 0.0
    first_target_hit: bool = False
    trailing_active: bool = False
    current_trail_stop: Optional[float] = None
    highest_price: float = 0.0

    # Calculated targets
    first_target_price: float = 0.0
    original_stop: float = 0.0
    breakeven_stop: float = 0.0

    # Tracking
    partial_exits: List[Dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Calculate targets after initialization"""
        self.initial_quantity = self.position.quantity
        self.remaining_quantity = self.position.quantity
        self.highest_price = self.position.entry_price
        self.original_stop = self.position.stop_loss or 0

        # Calculate first target (1:1 R:R from entry)
        if self.position.stop_loss and self.position.entry_price:
            risk = self.position.entry_price - self.position.stop_loss
            self.first_target_price = self.position.entry_price + (risk * self.first_target_rr)
            self.breakeven_stop = self.position.entry_price * 1.001  # Tiny profit to cover fees


class PositionMonitor:
    """
    Monitors open positions and manages smart exits.

    Exit Strategy:
    1. FIRST TARGET (1:1 R:R):
       - Sell 50% of position
       - Move stop to breakeven on remainder

    2. TRAILING STOP (after 1.5:1 R:R):
       - Trail 2% below highest price
       - Locks in profits while letting winners run

    3. ORIGINAL STOP:
       - Full position exits if price hits original stop before first target

    Usage:
        monitor = PositionMonitor()
        await monitor.start()
        monitor.add_position(position, stop_loss=100.0, take_profit=120.0)
    """

    def __init__(self, check_interval: float = 5.0):
        self.managed_positions: Dict[str, ManagedPosition] = {}
        self.check_interval = check_interval
        self.running = False
        self.broker = None  # Set externally
        self.notifier = None  # Set externally

        # Configuration
        self.partial_take_profit_pct = 0.50  # Sell 50% at first target
        self.trailing_stop_pct = 0.02  # 2% trailing

    async def start(self):
        """Start the position monitor loop"""
        self.running = True
        logger.info("PositionMonitor started")

        while self.running:
            try:
                await self._check_all_positions()
            except Exception as e:
                logger.error(f"Position monitor error: {e}")

            await asyncio.sleep(self.check_interval)

    async def stop(self):
        """Stop the monitor"""
        self.running = False
        logger.info("PositionMonitor stopped")

    def add_position(
        self,
        position: Position,
        partial_pct: float = 0.50,
        first_target_rr: float = 1.0,
        trailing_pct: float = 0.02
    ) -> ManagedPosition:
        """
        Add a position to be monitored with smart exits.

        Args:
            position: The Position object
            partial_pct: Percentage to sell at first target (default 50%)
            first_target_rr: Risk:reward for first target (default 1:1)
            trailing_pct: Trailing stop percentage (default 2%)
        """
        managed = ManagedPosition(
            position=position,
            partial_take_profit_pct=partial_pct,
            first_target_rr=first_target_rr,
            trailing_stop_pct=trailing_pct
        )

        self.managed_positions[position.symbol] = managed

        logger.info(
            f"Position monitored: {position.symbol} | "
            f"Entry: ${position.entry_price:.2f} | "
            f"Stop: ${managed.original_stop:.2f} | "
            f"1st Target: ${managed.first_target_price:.2f} (sell {partial_pct:.0%}) | "
            f"Then trail {trailing_pct:.0%}"
        )

        return managed

    def remove_position(self, symbol: str):
        """Remove a position from monitoring"""
        if symbol in self.managed_positions:
            del self.managed_positions[symbol]
            logger.info(f"Position removed from monitor: {symbol}")

    async def _check_all_positions(self):
        """Check all managed positions for exit conditions"""
        for symbol, managed in list(self.managed_positions.items()):
            try:
                await self._check_position(managed)
            except Exception as e:
                logger.error(f"Error checking {symbol}: {e}")

    async def _check_position(self, managed: ManagedPosition):
        """Check a single position for exit conditions"""
        pos = managed.position
        current_price = pos.current_price

        # Update highest price for trailing
        if current_price > managed.highest_price:
            managed.highest_price = current_price

        # === CHECK EXIT CONDITIONS ===

        # 1. ORIGINAL STOP HIT (before first target)
        if not managed.first_target_hit and current_price <= managed.original_stop:
            await self._exit_full_position(managed, "Stop Loss Hit")
            return

        # 2. FIRST TARGET HIT - Partial exit
        if not managed.first_target_hit and current_price >= managed.first_target_price:
            await self._partial_exit(managed)
            return

        # 3. BREAKEVEN STOP HIT (after first target)
        if managed.first_target_hit and not managed.trailing_active:
            if current_price <= managed.breakeven_stop:
                await self._exit_remaining(managed, "Breakeven Stop Hit")
                return

        # 4. Check if we should START trailing
        if managed.first_target_hit and not managed.trailing_active:
            entry = pos.entry_price
            risk = entry - managed.original_stop
            current_rr = (current_price - entry) / risk if risk > 0 else 0

            if current_rr >= managed.trailing_start_rr:
                managed.trailing_active = True
                managed.current_trail_stop = current_price * (1 - managed.trailing_stop_pct)
                logger.info(
                    f"{pos.symbol}: Trailing stop activated at ${managed.current_trail_stop:.2f} "
                    f"({managed.trailing_stop_pct:.0%} below ${current_price:.2f})"
                )

        # 5. UPDATE TRAILING STOP
        if managed.trailing_active:
            new_trail = managed.highest_price * (1 - managed.trailing_stop_pct)

            # Only move stop UP, never down
            if new_trail > (managed.current_trail_stop or 0):
                managed.current_trail_stop = new_trail
                logger.debug(f"{pos.symbol}: Trail stop updated to ${new_trail:.2f}")

            # Check if trailing stop hit
            if current_price <= managed.current_trail_stop:
                await self._exit_remaining(managed, f"Trailing Stop Hit (${managed.current_trail_stop:.2f})")
                return

    async def _partial_exit(self, managed: ManagedPosition):
        """Execute partial profit taking at first target"""
        pos = managed.position

        # Calculate quantity to sell
        sell_qty = managed.initial_quantity * managed.partial_take_profit_pct

        # Round appropriately
        if pos.market_type in [MarketType.EQUITY, MarketType.OPTIONS]:
            sell_qty = int(sell_qty)
        else:
            sell_qty = round(sell_qty, 4)

        if sell_qty <= 0:
            return

        logger.info(
            f"PARTIAL EXIT: {pos.symbol} | "
            f"Selling {sell_qty} of {managed.remaining_quantity} @ ${pos.current_price:.2f} | "
            f"First target hit (1:1 R:R)"
        )

        # Execute sell (if broker connected)
        if self.broker and hasattr(self.broker, 'place_order'):
            try:
                await self.broker.place_order(
                    symbol=pos.symbol,
                    market_type=pos.market_type,
                    side='sell',
                    quantity=sell_qty,
                    order_type='market'
                )
            except Exception as e:
                logger.error(f"Partial exit order failed: {e}")
                return

        # Update managed position state
        managed.first_target_hit = True
        managed.remaining_quantity -= sell_qty
        managed.partial_exits.append({
            'quantity': sell_qty,
            'price': pos.current_price,
            'reason': 'First Target (1:1 R:R)',
            'timestamp': datetime.now().isoformat()
        })

        # Move stop to breakeven
        pos.stop_loss = managed.breakeven_stop

        # Notify
        if self.notifier:
            try:
                pnl = (pos.current_price - pos.entry_price) * sell_qty
                pnl_pct = ((pos.current_price / pos.entry_price) - 1) * 100

                await self.notifier.send_message(
                    f"💰 PARTIAL PROFIT: {pos.symbol}\n"
                    f"Sold {sell_qty} @ ${pos.current_price:.2f}\n"
                    f"P&L: ${pnl:.2f} ({pnl_pct:+.1f}%)\n"
                    f"Remaining: {managed.remaining_quantity}\n"
                    f"Stop moved to breakeven: ${managed.breakeven_stop:.2f}\n"
                    f"Now trailing for more gains..."
                )
            except:
                pass

        logger.info(
            f"{pos.symbol}: Stop moved to breakeven ${managed.breakeven_stop:.2f} | "
            f"Remaining: {managed.remaining_quantity} | "
            f"Trailing will start at {managed.trailing_start_rr}:1 R:R"
        )

    async def _exit_remaining(self, managed: ManagedPosition, reason: str):
        """Exit the remaining position"""
        pos = managed.position

        if managed.remaining_quantity <= 0:
            self.remove_position(pos.symbol)
            return

        logger.info(
            f"EXIT REMAINING: {pos.symbol} | "
            f"Selling {managed.remaining_quantity} @ ${pos.current_price:.2f} | "
            f"Reason: {reason}"
        )

        # Execute sell
        if self.broker and hasattr(self.broker, 'place_order'):
            try:
                await self.broker.place_order(
                    symbol=pos.symbol,
                    market_type=pos.market_type,
                    side='sell',
                    quantity=managed.remaining_quantity,
                    order_type='market'
                )
            except Exception as e:
                logger.error(f"Exit order failed: {e}")
                return

        # Notify
        if self.notifier:
            try:
                total_pnl = 0
                # Calculate P&L from all exits
                for exit in managed.partial_exits:
                    total_pnl += (exit['price'] - pos.entry_price) * exit['quantity']
                total_pnl += (pos.current_price - pos.entry_price) * managed.remaining_quantity

                total_qty = managed.initial_quantity
                avg_exit = total_pnl / total_qty + pos.entry_price if total_qty > 0 else pos.current_price
                pnl_pct = ((avg_exit / pos.entry_price) - 1) * 100

                await self.notifier.send_message(
                    f"🏁 POSITION CLOSED: {pos.symbol}\n"
                    f"Reason: {reason}\n"
                    f"Final exit @ ${pos.current_price:.2f}\n"
                    f"Total P&L: ${total_pnl:.2f} ({pnl_pct:+.1f}%)\n"
                    f"Entry: ${pos.entry_price:.2f}"
                )
            except:
                pass

        self.remove_position(pos.symbol)

    async def _exit_full_position(self, managed: ManagedPosition, reason: str):
        """Exit the full position (stop loss before first target)"""
        managed.remaining_quantity = managed.initial_quantity
        await self._exit_remaining(managed, reason)

    def get_position_status(self, symbol: str) -> Optional[Dict]:
        """Get current status of a managed position"""
        managed = self.managed_positions.get(symbol)
        if not managed:
            return None

        pos = managed.position
        entry = pos.entry_price
        current = pos.current_price
        risk = entry - managed.original_stop if managed.original_stop else 0
        current_rr = (current - entry) / risk if risk > 0 else 0

        return {
            'symbol': symbol,
            'entry': entry,
            'current': current,
            'pnl_pct': pos.pnl_pct,
            'current_rr': current_rr,
            'initial_qty': managed.initial_quantity,
            'remaining_qty': managed.remaining_quantity,
            'first_target_hit': managed.first_target_hit,
            'first_target_price': managed.first_target_price,
            'trailing_active': managed.trailing_active,
            'trail_stop': managed.current_trail_stop,
            'highest_price': managed.highest_price,
            'original_stop': managed.original_stop,
            'current_stop': managed.current_trail_stop or managed.breakeven_stop if managed.first_target_hit else managed.original_stop
        }

    def get_all_status(self) -> List[Dict]:
        """Get status of all managed positions"""
        return [
            self.get_position_status(symbol)
            for symbol in self.managed_positions
        ]


# Singleton instance
_monitor_instance: Optional[PositionMonitor] = None


def get_position_monitor() -> PositionMonitor:
    """Get or create the position monitor instance"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = PositionMonitor()
    return _monitor_instance

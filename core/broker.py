"""
Interactive Brokers Integration
Handles all broker communication and order execution
"""
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from loguru import logger

try:
    from ib_insync import IB, Stock, Forex, Crypto, Option, Contract, Order, Trade as IBTrade
    from ib_insync import MarketOrder, LimitOrder, StopOrder, StopLimitOrder
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    logger.warning("ib_insync not installed - IB functionality disabled")

from .models import (
    Trade, Position, MarketData, MarketType,
    OrderType, OrderStatus, PortfolioSnapshot
)
from config.settings import config


class IBBroker:
    """
    Interactive Brokers connection and trading interface.

    Supports:
    - Equities (stocks, ETFs)
    - Forex
    - Crypto
    - Options
    """

    def __init__(self):
        self.ib: Optional[IB] = None
        self.connected = False
        self.account_id: Optional[str] = None
        self._callbacks: Dict[str, List[Callable]] = {
            'order_filled': [],
            'order_cancelled': [],
            'position_changed': [],
            'error': []
        }

    async def connect(self) -> bool:
        """Connect to Interactive Brokers TWS/Gateway"""
        if not IB_AVAILABLE:
            logger.error("ib_insync not installed")
            return False

        try:
            self.ib = IB()
            await self.ib.connectAsync(
                host=config.ib.host,
                port=config.ib.port,
                clientId=config.ib.client_id
            )

            self.connected = True
            self.account_id = self.ib.managedAccounts()[0] if self.ib.managedAccounts() else None

            # Set up event handlers
            self.ib.orderStatusEvent += self._on_order_status
            self.ib.errorEvent += self._on_error

            logger.info(f"Connected to IB - Account: {self.account_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to IB: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from IB"""
        if self.ib and self.connected:
            self.ib.disconnect()
            self.connected = False
            logger.info("Disconnected from IB")

    def _create_contract(self, symbol: str, market_type: MarketType) -> Optional[Contract]:
        """Create IB contract based on market type"""
        if not IB_AVAILABLE:
            return None

        if market_type == MarketType.EQUITY or market_type == MarketType.SPAC:
            return Stock(symbol, 'SMART', 'USD')
        elif market_type == MarketType.FOREX:
            # Forex symbols like EURUSD
            base = symbol[:3]
            quote = symbol[3:]
            return Forex(base + quote)
        elif market_type == MarketType.CRYPTO:
            return Crypto(symbol, 'PAXOS', 'USD')
        elif market_type == MarketType.OPTIONS:
            # Options need more details - handled separately
            return None
        else:
            return Stock(symbol, 'SMART', 'USD')

    async def get_quote(self, symbol: str, market_type: MarketType) -> Optional[MarketData]:
        """Get current quote for a symbol"""
        if not self.connected:
            return None

        contract = self._create_contract(symbol, market_type)
        if not contract:
            return None

        try:
            self.ib.qualifyContracts(contract)
            ticker = self.ib.reqMktData(contract)
            await asyncio.sleep(1)  # Wait for data

            return MarketData(
                symbol=symbol,
                market_type=market_type,
                timestamp=datetime.now(),
                open=ticker.open or 0,
                high=ticker.high or 0,
                low=ticker.low or 0,
                close=ticker.close or ticker.last or 0,
                volume=ticker.volume or 0,
                bid=ticker.bid,
                ask=ticker.ask
            )
        except Exception as e:
            logger.error(f"Error getting quote for {symbol}: {e}")
            return None

    async def get_historical_data(
        self,
        symbol: str,
        market_type: MarketType,
        duration: str = "1 M",
        bar_size: str = "1 day"
    ) -> List[Dict[str, Any]]:
        """Get historical bars"""
        if not self.connected:
            return []

        contract = self._create_contract(symbol, market_type)
        if not contract:
            return []

        try:
            self.ib.qualifyContracts(contract)
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True
            )

            return [
                {
                    'date': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                }
                for bar in bars
            ]
        except Exception as e:
            logger.error(f"Error getting historical data for {symbol}: {e}")
            return []

    async def place_order(
        self,
        symbol: str,
        market_type: MarketType,
        side: str,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> Optional[Trade]:
        """Place an order"""
        if not self.connected:
            logger.error("Not connected to broker")
            return None

        contract = self._create_contract(symbol, market_type)
        if not contract:
            return None

        try:
            self.ib.qualifyContracts(contract)

            # Create order based on type
            action = 'BUY' if side.lower() == 'buy' else 'SELL'

            if order_type == OrderType.MARKET:
                order = MarketOrder(action, quantity)
            elif order_type == OrderType.LIMIT:
                order = LimitOrder(action, quantity, limit_price)
            elif order_type == OrderType.STOP:
                order = StopOrder(action, quantity, stop_price)
            elif order_type == OrderType.STOP_LIMIT:
                order = StopLimitOrder(action, quantity, stop_price, limit_price)
            else:
                order = MarketOrder(action, quantity)

            # Submit order
            ib_trade = self.ib.placeOrder(contract, order)

            trade = Trade(
                id=str(ib_trade.order.orderId),
                symbol=symbol,
                market_type=market_type,
                side=side,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                status=OrderStatus.SUBMITTED
            )

            logger.info(f"Order placed: {side} {quantity} {symbol} @ {order_type.value}")
            return trade

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        if not self.connected:
            return False

        try:
            for trade in self.ib.trades():
                if str(trade.order.orderId) == order_id:
                    self.ib.cancelOrder(trade.order)
                    logger.info(f"Order {order_id} cancelled")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        if not self.connected:
            return []

        positions = []
        for pos in self.ib.positions():
            if pos.position != 0:
                # Determine market type from contract
                if hasattr(pos.contract, 'secType'):
                    if pos.contract.secType == 'STK':
                        market_type = MarketType.EQUITY
                    elif pos.contract.secType == 'CASH':
                        market_type = MarketType.FOREX
                    elif pos.contract.secType == 'CRYPTO':
                        market_type = MarketType.CRYPTO
                    else:
                        market_type = MarketType.EQUITY
                else:
                    market_type = MarketType.EQUITY

                positions.append(Position(
                    symbol=pos.contract.symbol,
                    market_type=market_type,
                    quantity=pos.position,
                    entry_price=pos.avgCost,
                    current_price=pos.avgCost,  # Will be updated with market data
                    entry_time=datetime.now()
                ))

        return positions

    async def get_account_summary(self) -> Dict[str, Any]:
        """Get account summary"""
        if not self.connected:
            return {}

        summary = {}
        for item in self.ib.accountSummary():
            summary[item.tag] = {
                'value': item.value,
                'currency': item.currency
            }
        return summary

    async def get_portfolio(self) -> PortfolioSnapshot:
        """Get complete portfolio snapshot"""
        if not self.connected:
            return PortfolioSnapshot(
                timestamp=datetime.now(),
                cash=0,
                positions=[],
                total_value=0,
                daily_pnl=0,
                total_pnl=0
            )

        summary = await self.get_account_summary()
        positions = await self.get_positions()

        cash = float(summary.get('TotalCashValue', {}).get('value', 0))
        total_value = float(summary.get('NetLiquidation', {}).get('value', 0))
        daily_pnl = float(summary.get('DailyPnL', {}).get('value', 0))
        total_pnl = float(summary.get('RealizedPnL', {}).get('value', 0))

        return PortfolioSnapshot(
            timestamp=datetime.now(),
            cash=cash,
            positions=positions,
            total_value=total_value,
            daily_pnl=daily_pnl,
            total_pnl=total_pnl
        )

    def _on_order_status(self, trade: IBTrade) -> None:
        """Handle order status updates"""
        if trade.orderStatus.status == 'Filled':
            for callback in self._callbacks['order_filled']:
                callback(trade)
        elif trade.orderStatus.status == 'Cancelled':
            for callback in self._callbacks['order_cancelled']:
                callback(trade)

    def _on_error(self, reqId: int, errorCode: int, errorString: str, contract: Contract) -> None:
        """Handle errors"""
        logger.error(f"IB Error {errorCode}: {errorString}")
        for callback in self._callbacks['error']:
            callback(reqId, errorCode, errorString)

    def on(self, event: str, callback: Callable) -> None:
        """Register event callback"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

"""
Base Scanner Agent
Foundation for all market scanning agents
"""
import asyncio
from abc import abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd
from loguru import logger

from core.base_agent import BaseAgent, AgentMessage
from core.models import Signal, MarketType, SignalType, MarketData


class BaseScanner(BaseAgent):
    """
    Base class for market scanners.
    Scans markets for potential trading opportunities.
    """

    def __init__(self, name: str, market_type: MarketType, config: Optional[Dict] = None):
        super().__init__(name, config)
        self.market_type = market_type
        self.watchlist: List[str] = []
        self.scan_interval = config.get('scan_interval', 60) if config else 60
        self.signals_generated: List[Signal] = []
        self.last_scan: Optional[datetime] = None

    @abstractmethod
    async def get_universe(self) -> List[str]:
        """Get list of symbols to scan"""
        pass

    @abstractmethod
    async def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch market data for a symbol"""
        pass

    @abstractmethod
    async def analyze(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Analyze data and generate signal if opportunity found"""
        pass

    async def process(self) -> None:
        """Main scanning loop"""
        # Check if it's time to scan
        if self.last_scan:
            elapsed = (datetime.now() - self.last_scan).seconds
            if elapsed < self.scan_interval:
                await asyncio.sleep(1)
                return

        logger.info(f"[{self.name}] Starting market scan...")

        # Get universe of symbols to scan
        if not self.watchlist:
            self.watchlist = await self.get_universe()
            logger.info(f"[{self.name}] Scanning {len(self.watchlist)} symbols")

        # Scan each symbol
        for symbol in self.watchlist:
            try:
                data = await self.fetch_data(symbol)
                if data is not None and not data.empty:
                    signal = await self.analyze(symbol, data)
                    if signal:
                        self.signals_generated.append(signal)
                        await self._broadcast_signal(signal)

            except Exception as e:
                logger.error(f"[{self.name}] Error scanning {symbol}: {e}")
                continue

        self.last_scan = datetime.now()
        logger.info(f"[{self.name}] Scan complete. Signals: {len(self.signals_generated)}")

    async def _broadcast_signal(self, signal: Signal) -> None:
        """Send signal to coordinator/ranker"""
        await self.send_message(
            target='coordinator',
            msg_type='new_signal',
            payload={
                'symbol': signal.symbol,
                'market_type': signal.market_type.value,
                'signal_type': signal.signal_type.value,
                'confidence': signal.confidence,
                'entry_price': signal.entry_price,
                'target_price': signal.target_price,
                'stop_loss': signal.stop_loss,
                'risk_reward_ratio': signal.risk_reward_ratio,
                'source': signal.source,
                'timestamp': signal.timestamp.isoformat(),
                'metadata': signal.metadata
            },
            priority=2 if signal.confidence > 0.8 else 5
        )

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming messages"""
        if message.msg_type == 'update_watchlist':
            self.watchlist = message.payload.get('symbols', [])
            logger.info(f"[{self.name}] Watchlist updated: {len(self.watchlist)} symbols")

        elif message.msg_type == 'force_scan':
            self.last_scan = None  # Reset to trigger immediate scan

        elif message.msg_type == 'pause_scanning':
            await self.pause()

        elif message.msg_type == 'resume_scanning':
            await self.resume()

    def calculate_risk_reward(
        self,
        entry: float,
        target: float,
        stop: float,
        is_long: bool = True
    ) -> float:
        """Calculate risk/reward ratio"""
        if is_long:
            risk = entry - stop
            reward = target - entry
        else:
            risk = stop - entry
            reward = entry - target

        if risk <= 0:
            return 0

        return reward / risk

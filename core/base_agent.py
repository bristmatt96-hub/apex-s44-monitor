"""
Base Agent Framework
All trading agents inherit from this base class
"""
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from loguru import logger
import json


class AgentState(Enum):
    """Agent lifecycle states"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentMessage:
    """Message passed between agents"""
    source: str
    target: str
    msg_type: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    priority: int = 5  # 1-10, 1 being highest priority

    def to_json(self) -> str:
        return json.dumps({
            'source': self.source,
            'target': self.target,
            'msg_type': self.msg_type,
            'payload': self.payload,
            'timestamp': self.timestamp.isoformat(),
            'priority': self.priority
        })

    @classmethod
    def from_json(cls, data: str) -> 'AgentMessage':
        d = json.loads(data)
        d['timestamp'] = datetime.fromisoformat(d['timestamp'])
        return cls(**d)


class BaseAgent(ABC):
    """
    Base class for all trading agents.

    Agents are autonomous units that:
    - Scan markets for opportunities
    - Generate trading signals
    - Execute trades
    - Communicate with other agents
    """

    def __init__(self, name: str, config: Optional[Dict] = None):
        self.name = name
        self.config = config or {}
        self.state = AgentState.IDLE
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.subscribers: List[Callable] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.metrics = {
            'messages_sent': 0,
            'messages_received': 0,
            'errors': 0,
            'last_active': None
        }
        logger.info(f"Agent [{self.name}] initialized")

    @abstractmethod
    async def process(self) -> None:
        """
        Main processing loop - implement in subclasses.
        This is called continuously while the agent is running.
        """
        pass

    @abstractmethod
    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming messages from other agents"""
        pass

    async def start(self) -> None:
        """Start the agent"""
        if self._running:
            logger.warning(f"Agent [{self.name}] already running")
            return

        self._running = True
        self.state = AgentState.RUNNING
        logger.info(f"Agent [{self.name}] started")

        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the agent"""
        self._running = False
        self.state = AgentState.STOPPED
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Agent [{self.name}] stopped")

    async def pause(self) -> None:
        """Pause the agent"""
        self.state = AgentState.PAUSED
        logger.info(f"Agent [{self.name}] paused")

    async def resume(self) -> None:
        """Resume the agent"""
        if self.state == AgentState.PAUSED:
            self.state = AgentState.RUNNING
            logger.info(f"Agent [{self.name}] resumed")

    async def _run_loop(self) -> None:
        """Main run loop"""
        while self._running:
            try:
                if self.state == AgentState.RUNNING:
                    # Process incoming messages
                    while not self.message_queue.empty():
                        msg = await self.message_queue.get()
                        await self.handle_message(msg)
                        self.metrics['messages_received'] += 1

                    # Run main processing
                    await self.process()
                    self.metrics['last_active'] = datetime.now()

                elif self.state == AgentState.PAUSED:
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Agent [{self.name}] error: {e}")
                self.metrics['errors'] += 1
                self.state = AgentState.ERROR
                await asyncio.sleep(5)  # Back off on error
                self.state = AgentState.RUNNING  # Try to recover

            await asyncio.sleep(0.1)  # Prevent tight loop

    async def send_message(self, target: str, msg_type: str, payload: Dict[str, Any], priority: int = 5) -> None:
        """Send a message to another agent"""
        message = AgentMessage(
            source=self.name,
            target=target,
            msg_type=msg_type,
            payload=payload,
            priority=priority
        )

        # Notify subscribers (coordinator will route)
        for subscriber in self.subscribers:
            await subscriber(message)

        self.metrics['messages_sent'] += 1
        logger.debug(f"Agent [{self.name}] sent {msg_type} to {target}")

    async def receive_message(self, message: AgentMessage) -> None:
        """Receive a message from another agent"""
        await self.message_queue.put(message)

    def subscribe(self, callback: Callable) -> None:
        """Subscribe to messages from this agent"""
        self.subscribers.append(callback)

    def get_status(self) -> Dict[str, Any]:
        """Get agent status"""
        return {
            'name': self.name,
            'state': self.state.value,
            'metrics': self.metrics
        }

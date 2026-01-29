"""
Unit tests for Coordinator agent
"""
import asyncio
import pytest

from core.base_agent import BaseAgent, AgentMessage, AgentState


class MockScanner(BaseAgent):
    """Mock scanner for testing"""

    def __init__(self, name: str):
        super().__init__(name)

    async def process(self) -> None:
        await asyncio.sleep(0.01)

    async def handle_message(self, message: AgentMessage) -> None:
        pass


class MockCoordinator(BaseAgent):
    """Simplified coordinator for testing message routing"""

    def __init__(self):
        super().__init__("Coordinator")
        self.agents = {}
        self.raw_signals = []
        self.trading_enabled = True

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent"""
        self.agents[agent.name] = agent
        agent.subscribe(self._route_message)

    async def _route_message(self, message: AgentMessage) -> None:
        """Route message to target"""
        target = message.target
        if target == 'coordinator':
            await self.receive_message(message)
        elif target in self.agents:
            await self.agents[target].receive_message(message)
        elif target == 'all':
            for agent in self.agents.values():
                await agent.receive_message(message)

    async def process(self) -> None:
        await asyncio.sleep(0.01)

    async def handle_message(self, message: AgentMessage) -> None:
        if message.msg_type == 'new_signal':
            self.raw_signals.append(message.payload)

    def get_status(self):
        return {
            'coordinator': {
                'state': self.state.value,
                'trading_enabled': self.trading_enabled
            },
            'agents': {
                name: agent.get_status()
                for name, agent in self.agents.items()
            },
            'signals': {
                'raw': len(self.raw_signals)
            }
        }


@pytest.mark.asyncio
class TestCoordinator:
    """Tests for Coordinator functionality"""

    async def test_coordinator_initialization(self):
        """Test coordinator initializes correctly"""
        coordinator = MockCoordinator()

        assert coordinator.name == "Coordinator"
        assert coordinator.agents == {}
        assert coordinator.raw_signals == []
        assert coordinator.trading_enabled is True

    async def test_register_agent(self):
        """Test agent registration"""
        coordinator = MockCoordinator()
        scanner = MockScanner("EquityScanner")

        coordinator.register_agent(scanner)

        assert "EquityScanner" in coordinator.agents
        assert len(scanner.subscribers) == 1

    async def test_register_multiple_agents(self):
        """Test registering multiple agents"""
        coordinator = MockCoordinator()
        equity = MockScanner("EquityScanner")
        crypto = MockScanner("CryptoScanner")
        forex = MockScanner("ForexScanner")

        coordinator.register_agent(equity)
        coordinator.register_agent(crypto)
        coordinator.register_agent(forex)

        assert len(coordinator.agents) == 3
        assert "EquityScanner" in coordinator.agents
        assert "CryptoScanner" in coordinator.agents
        assert "ForexScanner" in coordinator.agents

    async def test_message_routing_to_coordinator(self):
        """Test messages route to coordinator"""
        coordinator = MockCoordinator()
        scanner = MockScanner("TestScanner")
        coordinator.register_agent(scanner)

        await coordinator.start()
        await scanner.start()

        # Scanner sends signal to coordinator
        await scanner.send_message(
            target="coordinator",
            msg_type="new_signal",
            payload={"symbol": "AAPL", "price": 150.0}
        )

        await asyncio.sleep(0.1)  # Wait for message processing

        await scanner.stop()
        await coordinator.stop()

        assert len(coordinator.raw_signals) == 1
        assert coordinator.raw_signals[0]["symbol"] == "AAPL"

    async def test_message_routing_between_agents(self):
        """Test messages route between agents"""
        coordinator = MockCoordinator()

        class ReceiverAgent(MockScanner):
            def __init__(self):
                super().__init__("Receiver")
                self.received = []

            async def handle_message(self, message):
                self.received.append(message)

        sender = MockScanner("Sender")
        receiver = ReceiverAgent()

        coordinator.register_agent(sender)
        coordinator.register_agent(receiver)

        await coordinator.start()
        await sender.start()
        await receiver.start()

        # Sender sends to receiver
        await sender.send_message(
            target="Receiver",
            msg_type="test_message",
            payload={"data": "hello"}
        )

        await asyncio.sleep(0.15)

        await sender.stop()
        await receiver.stop()
        await coordinator.stop()

        assert len(receiver.received) == 1
        assert receiver.received[0].payload["data"] == "hello"

    async def test_broadcast_to_all(self):
        """Test broadcast to all agents"""
        coordinator = MockCoordinator()

        class CountingAgent(MockScanner):
            def __init__(self, name):
                super().__init__(name)
                self.message_count = 0

            async def handle_message(self, message):
                self.message_count += 1

        agent1 = CountingAgent("Agent1")
        agent2 = CountingAgent("Agent2")
        agent3 = CountingAgent("Agent3")

        coordinator.register_agent(agent1)
        coordinator.register_agent(agent2)
        coordinator.register_agent(agent3)

        # Coordinator needs to subscribe to itself for routing outgoing messages
        coordinator.subscribe(coordinator._route_message)

        await coordinator.start()
        await agent1.start()
        await agent2.start()
        await agent3.start()

        # Broadcast to all
        await coordinator.send_message(
            target="all",
            msg_type="system_announcement",
            payload={"message": "Trading paused"}
        )

        await asyncio.sleep(0.15)

        await agent1.stop()
        await agent2.stop()
        await agent3.stop()
        await coordinator.stop()

        assert agent1.message_count == 1
        assert agent2.message_count == 1
        assert agent3.message_count == 1

    async def test_coordinator_status(self):
        """Test coordinator status reporting"""
        coordinator = MockCoordinator()
        scanner = MockScanner("TestScanner")
        coordinator.register_agent(scanner)

        await coordinator.start()
        await scanner.start()

        status = coordinator.get_status()

        assert status['coordinator']['state'] == 'running'
        assert status['coordinator']['trading_enabled'] is True
        assert 'TestScanner' in status['agents']
        assert status['signals']['raw'] == 0

        await scanner.stop()
        await coordinator.stop()

    async def test_disable_trading(self):
        """Test trading can be disabled"""
        coordinator = MockCoordinator()
        coordinator.trading_enabled = False

        assert coordinator.trading_enabled is False
        status = coordinator.get_status()
        assert status['coordinator']['trading_enabled'] is False

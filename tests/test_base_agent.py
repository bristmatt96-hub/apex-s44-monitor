"""
Unit tests for BaseAgent and AgentMessage
"""
import asyncio
import pytest
from datetime import datetime

from core.base_agent import BaseAgent, AgentMessage, AgentState


class MockAgent(BaseAgent):
    """Concrete implementation for testing"""

    def __init__(self, name: str):
        super().__init__(name)
        self.processed_count = 0
        self.handled_messages = []

    async def process(self) -> None:
        self.processed_count += 1
        await asyncio.sleep(0.01)

    async def handle_message(self, message: AgentMessage) -> None:
        self.handled_messages.append(message)


class TestAgentMessage:
    """Tests for AgentMessage dataclass"""

    def test_message_creation(self):
        """Test basic message creation"""
        msg = AgentMessage(
            source="scanner",
            target="coordinator",
            msg_type="new_signal",
            payload={"symbol": "AAPL", "price": 150.0}
        )

        assert msg.source == "scanner"
        assert msg.target == "coordinator"
        assert msg.msg_type == "new_signal"
        assert msg.payload["symbol"] == "AAPL"
        assert msg.priority == 5  # default
        assert isinstance(msg.timestamp, datetime)

    def test_message_priority(self):
        """Test message with custom priority"""
        msg = AgentMessage(
            source="risk_manager",
            target="executor",
            msg_type="stop_trading",
            payload={},
            priority=1  # highest priority
        )

        assert msg.priority == 1

    def test_message_json_serialization(self):
        """Test message serialization to JSON"""
        msg = AgentMessage(
            source="scanner",
            target="coordinator",
            msg_type="new_signal",
            payload={"symbol": "BTC", "price": 50000}
        )

        json_str = msg.to_json()
        assert '"source": "scanner"' in json_str
        assert '"target": "coordinator"' in json_str
        assert '"symbol": "BTC"' in json_str

    def test_message_json_deserialization(self):
        """Test message deserialization from JSON"""
        original = AgentMessage(
            source="analyzer",
            target="ranker",
            msg_type="analysis_complete",
            payload={"score": 0.85}
        )

        json_str = original.to_json()
        restored = AgentMessage.from_json(json_str)

        assert restored.source == original.source
        assert restored.target == original.target
        assert restored.msg_type == original.msg_type
        assert restored.payload == original.payload
        assert restored.priority == original.priority


@pytest.mark.asyncio
class TestBaseAgent:
    """Tests for BaseAgent lifecycle and functionality"""

    async def test_agent_initialization(self):
        """Test agent initializes correctly"""
        agent = MockAgent("TestAgent")

        assert agent.name == "TestAgent"
        assert agent.state == AgentState.IDLE
        assert agent._running is False
        assert agent.metrics['messages_sent'] == 0
        assert agent.metrics['messages_received'] == 0
        assert agent.metrics['errors'] == 0

    async def test_agent_start(self):
        """Test agent starts correctly"""
        agent = MockAgent("TestAgent")

        await agent.start()

        assert agent._running is True
        assert agent.state == AgentState.RUNNING
        assert agent._task is not None

        await agent.stop()

    async def test_agent_stop(self):
        """Test agent stops correctly"""
        agent = MockAgent("TestAgent")

        await agent.start()
        await asyncio.sleep(0.05)
        await agent.stop()

        assert agent._running is False
        assert agent.state == AgentState.STOPPED

    async def test_agent_pause_resume(self):
        """Test agent pause and resume"""
        agent = MockAgent("TestAgent")

        await agent.start()
        await agent.pause()
        assert agent.state == AgentState.PAUSED

        await agent.resume()
        assert agent.state == AgentState.RUNNING

        await agent.stop()

    async def test_agent_processes_while_running(self):
        """Test that process() is called while running"""
        agent = MockAgent("TestAgent")

        await agent.start()
        await asyncio.sleep(0.1)  # Let it process a few times
        await agent.stop()

        assert agent.processed_count > 0

    async def test_agent_receive_message(self):
        """Test agent receives messages in queue"""
        agent = MockAgent("TestAgent")
        msg = AgentMessage(
            source="other",
            target="TestAgent",
            msg_type="test",
            payload={"data": "value"}
        )

        await agent.receive_message(msg)

        assert agent.message_queue.qsize() == 1

    async def test_agent_handles_messages(self):
        """Test agent processes messages from queue"""
        agent = MockAgent("TestAgent")
        msg = AgentMessage(
            source="other",
            target="TestAgent",
            msg_type="test",
            payload={"key": "value"}
        )

        await agent.start()
        await agent.receive_message(msg)
        await asyncio.sleep(0.15)  # Wait for message processing
        await agent.stop()

        assert len(agent.handled_messages) == 1
        assert agent.handled_messages[0].payload["key"] == "value"
        assert agent.metrics['messages_received'] >= 1

    async def test_agent_subscribe(self):
        """Test agent subscription mechanism"""
        agent = MockAgent("TestAgent")
        received_messages = []

        async def callback(msg):
            received_messages.append(msg)

        agent.subscribe(callback)
        await agent.start()
        await agent.send_message("other", "test_type", {"hello": "world"})
        await asyncio.sleep(0.05)
        await agent.stop()

        assert len(received_messages) == 1
        assert received_messages[0].target == "other"
        assert agent.metrics['messages_sent'] == 1

    async def test_agent_status(self):
        """Test get_status returns correct info"""
        agent = MockAgent("StatusAgent")

        await agent.start()
        await asyncio.sleep(0.05)

        status = agent.get_status()

        assert status['name'] == "StatusAgent"
        assert status['state'] == "running"
        assert 'metrics' in status
        assert status['metrics']['errors'] == 0

        await agent.stop()

    async def test_double_start_warning(self):
        """Test that starting an already running agent is handled"""
        agent = MockAgent("TestAgent")

        await agent.start()
        await agent.start()  # Should not error, just warn

        assert agent._running is True

        await agent.stop()

    async def test_resume_only_from_paused(self):
        """Test resume only works from paused state"""
        agent = MockAgent("TestAgent")

        await agent.start()
        initial_state = agent.state

        await agent.resume()  # Should have no effect since not paused
        assert agent.state == initial_state

        await agent.stop()

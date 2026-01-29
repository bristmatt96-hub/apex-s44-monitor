"""
Pytest configuration and fixtures for APEX Trading System tests
"""
import pytest
import asyncio
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_signal_payload():
    """Sample signal payload for testing"""
    return {
        "symbol": "AAPL",
        "market_type": "equity",
        "signal_type": "buy",
        "confidence": 0.85,
        "entry_price": 150.0,
        "target_price": 165.0,
        "stop_loss": 145.0,
        "risk_reward_ratio": 3.0,
        "source": "TestScanner"
    }


@pytest.fixture
def sample_trade_payload():
    """Sample trade payload for testing"""
    return {
        "symbol": "TSLA",
        "side": "buy",
        "quantity": 10,
        "entry_price": 200.0,
        "market_type": "equity",
        "strategy": "momentum_breakout",
        "confidence": 0.9,
        "risk_reward": 2.5
    }

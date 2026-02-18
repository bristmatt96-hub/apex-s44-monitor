"""Shared fixtures & mocks for Credit Catalyst tests.

The conftest must pre-patch heavy transitive imports (ib_insync, pandas, etc.)
so that test collection never fails due to missing optional dependencies.
"""
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out optional packages that the production code guards behind try/except
# but __init__.py re-exports trigger before we can patch.  We insert harmless
# stubs into sys.modules ONLY when the real package is missing.
# ---------------------------------------------------------------------------
_OPTIONAL_STUBS = [
    "ib_insync",
    "pandas", "pandas.core", "pandas.core.frame",
    "numpy",
    "ta", "ta.trend", "ta.momentum", "ta.volatility",
    "yfinance",
    "ccxt",
    "sklearn", "sklearn.ensemble",
    "xgboost",
    "joblib",
    "httpx",
    "aiohttp",
]

for _mod_name in _OPTIONAL_STUBS:
    if _mod_name not in sys.modules:
        try:
            __import__(_mod_name)
        except (ImportError, ModuleNotFoundError):
            stub = ModuleType(_mod_name)
            # Some modules need attributes the import chain touches
            if _mod_name == "ib_insync":
                for _cls in (
                    "IB", "Stock", "Forex", "Crypto", "Option", "Contract",
                    "Order", "Trade", "MarketOrder", "LimitOrder",
                    "StopOrder", "StopLimitOrder",
                ):
                    setattr(stub, _cls, MagicMock())
            if _mod_name == "pandas":
                stub.DataFrame = MagicMock()
                stub.Series = MagicMock()
                stub.Timestamp = MagicMock()
                stub.to_datetime = MagicMock()
                stub.read_csv = MagicMock()
                stub.read_json = MagicMock()
                stub.concat = MagicMock()
            if _mod_name == "numpy":
                stub.array = MagicMock()
                stub.mean = MagicMock()
                stub.std = MagicMock()
                stub.float64 = float
                stub.int64 = int
                stub.nan = float('nan')
                stub.isscalar = lambda obj: isinstance(obj, (int, float, complex, str, bytes))
                stub.ndarray = type('ndarray', (), {})
                stub.bool_ = type('bool_', (), {})  # pytest.approx checks this
            sys.modules[_mod_name] = stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_broker():
    """IBBroker mock — connect() always returns False (sim mode)."""
    broker = AsyncMock()
    broker.connect = AsyncMock(return_value=False)
    broker.disconnect = AsyncMock()
    return broker


@pytest.fixture
def mock_notifier():
    """Patch get_notifier() to return None globally."""
    with patch("utils.telegram_notifier.get_notifier", return_value=None):
        yield None


@pytest.fixture
def sample_order():
    return {
        "symbol": "AAPL",
        "market_type": "equity",
        "entry_price": 150.0,
        "stop_loss": 145.0,
        "target_price": 165.0,
        "signal_type": "buy",
    }


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temp directory for JSON state files."""
    return tmp_path

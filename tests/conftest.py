"""
Shared test fixtures and mock setup for Apex S44 Monitor tests.

Mocks Streamlit, tweepy, and feedparser before any production code is imported,
since those modules execute UI/API code at import time.
"""

import sys
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest

# ============================================================
# Pre-import mocks for modules that have side effects on import
# ============================================================

# --- Streamlit mock ---
_st_mock = MagicMock()
_st_mock.secrets.get = MagicMock(return_value="")
_st_mock.stop = MagicMock()

# UI inputs must return real values (not MagicMock) so downstream JSON
# serialization and arithmetic don't crash during module-level UI execution.
def _selectbox_side_effect(*args, **kwargs):
    """Return the first option from the options list (mimics default selection)."""
    options = args[1] if len(args) >= 2 else kwargs.get("options", [])
    if options and len(options) > 0:
        return options[0]
    return ""


_st_mock.button.return_value = False
_st_mock.checkbox.return_value = False
_st_mock.selectbox.side_effect = _selectbox_side_effect
_st_mock.multiselect.return_value = []
_st_mock.radio.side_effect = _selectbox_side_effect
_st_mock.text_input.return_value = ""
_st_mock.text_area.return_value = ""
_st_mock.number_input.return_value = 0.0
_st_mock.slider.return_value = 0.0
_st_mock.date_input.return_value = None
_st_mock.file_uploader.return_value = None
_st_mock.sidebar.selectbox.side_effect = _selectbox_side_effect
_st_mock.sidebar.button.return_value = False
_st_mock.sidebar.checkbox.return_value = False
_st_mock.sidebar.slider.return_value = 0.0
_st_mock.sidebar.number_input.return_value = 0.0
_st_mock.sidebar.radio.return_value = ""
_st_mock.sidebar.text_input.return_value = ""


def _tabs_side_effect(labels):
    """Return exactly as many mock context-managers as tab labels requested."""
    return [MagicMock() for _ in labels]


def _columns_side_effect(spec):
    """Return as many mock columns as requested (int or list)."""
    if isinstance(spec, (list, tuple)):
        return [MagicMock() for _ in spec]
    return [MagicMock() for _ in range(int(spec))]


_st_mock.tabs.side_effect = _tabs_side_effect
_st_mock.columns.side_effect = _columns_side_effect
_st_mock.sidebar.columns.side_effect = _columns_side_effect


class _CacheDecorator:
    """Mimics st.cache_resource / st.cache_data — works as decorator and has .clear()."""

    def __call__(self, func=None, **kwargs):
        if func is not None:
            return func
        return lambda f: f

    def clear(self):
        pass


_st_mock.cache_resource = _CacheDecorator()
_st_mock.cache_data = _CacheDecorator()

sys.modules["streamlit"] = _st_mock

# --- Pandas compatibility (applymap → map in pandas 3.0) ---
try:
    from pandas.io.formats.style import Styler as _Styler

    if not hasattr(_Styler, "applymap") and hasattr(_Styler, "map"):
        _Styler.applymap = _Styler.map
except Exception:
    pass

# --- SQLAlchemy ARRAY → Text shim for SQLite testing ---
# Company model uses ARRAY(Text) which is PostgreSQL-only.
# Replace ARRAY with Text-compatible shim so tables create in SQLite.
try:
    import sqlalchemy as _sa

    class _TextShim(_sa.Text):
        """Drop-in for ARRAY(item_type) that degrades to Text on SQLite."""
        def __init__(self, *args, **kwargs):
            super().__init__()

    _sa.ARRAY = _TextShim
except Exception:
    pass

# --- Tweepy mock ---
sys.modules["tweepy"] = MagicMock()

# --- Feedparser mock ---
_feedparser_mock = MagicMock()
_feedparser_mock.parse.return_value = MagicMock(
    entries=[],
    feed=MagicMock(title="Mock Feed"),
)
sys.modules["feedparser"] = _feedparser_mock

# --- Optional heavy libs ---
for mod in ("openai", "anthropic", "yfinance", "pypdf", "pyaudio",
            "deepgram", "assemblyai", "whisper", "openpyxl"):
    sys.modules.setdefault(mod, MagicMock())


# ============================================================
# Project root fixture
# ============================================================

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def project_root():
    return PROJECT_ROOT


# ============================================================
# Sample snapshot fixtures
# ============================================================

@pytest.fixture
def sample_snapshot():
    """A realistic credit snapshot with all fields populated."""
    return {
        "company_name": "Acme Corp",
        "sector": "TMT",
        "last_updated": "2025-01-15",
        "overview": {
            "business_description": "European telecom operator",
            "business_positives": ["Strong subscriber base", "Fiber rollout"],
            "fatal_flaw": "High leverage from LBO",
            "ownership": "Private equity",
            "public_private": "Private",
            "recent_news": "Refinanced TLB in Q4",
        },
        "ratings": {
            "moodys": {"rating": "B2", "outlook": "Stable"},
            "sp": {"rating": "B", "outlook": "Negative"},
            "fitch": {"rating": "B+", "outlook": "Stable"},
        },
        "quick_assessment": {
            "total_debt": 5000,
            "cash_on_hand": 400,
            "cffo": 600,
            "interest_expense": 350,
            "revolver_available": 200,
            "debt_due_one_year": 250,
        },
        "key_ratios": {
            "debt_to_ebitda": 5.5,
            "net_debt_to_ebitda": 5.1,
            "ebitda_minus_capex_to_interest": 2.0,
            "fcf_to_debt": 0.05,
        },
        "debt_capitalization": [
            {
                "instrument": "Senior Secured TLB",
                "amount": 3000,
                "maturity": "2028-06-15",
                "coupon": "E+400",
                "price": 98.5,
                "ytw": 6.2,
                "stw": 420,
                "rating": "B2/B",
            }
        ],
        "maturity_schedule": {
            "year_1": 250,
            "year_2": 0,
            "year_3": 1500,
            "year_4": 0,
            "year_5": 3250,
            "thereafter": 0,
        },
        "credit_opinion": {
            "summary": "Adequate credit with elevated leverage.",
            "recommendation": "NEUTRAL",
            "key_risks": ["High leverage", "Competition"],
            "key_catalysts": ["Deleveraging", "EBITDA growth"],
        },
        "trend_analysis": {
            "years": ["2022", "2023", "2024"],
            "revenue": [2000, 2100, 2200],
            "ebitda": [800, 850, 900],
            "ebitda_margin": [40.0, 40.5, 40.9],
            "total_debt": [5200, 5100, 5000],
        },
        "equity_market_value": {},
    }


@pytest.fixture
def strong_credit_snapshot():
    """Snapshot that should produce a LONG signal."""
    return {
        "company_name": "StrongCo",
        "sector": "Consumer",
        "key_ratios": {
            "debt_to_ebitda": 3.0,
            "ebitda_minus_capex_to_interest": 4.0,
            "fcf_to_debt": 0.15,
        },
        "quick_assessment": {
            "cash_on_hand": 500,
            "revolver_available": 300,
            "debt_due_one_year": 200,
        },
        "credit_opinion": {
            "recommendation": "OVERWEIGHT",
        },
    }


@pytest.fixture
def weak_credit_snapshot():
    """Snapshot that should produce a SHORT signal."""
    return {
        "company_name": "WeakCo",
        "sector": "Retail",
        "key_ratios": {
            "debt_to_ebitda": 7.0,
            "ebitda_minus_capex_to_interest": 1.0,
            "fcf_to_debt": -0.05,
        },
        "quick_assessment": {
            "cash_on_hand": 50,
            "revolver_available": 20,
            "debt_due_one_year": 200,
        },
        "credit_opinion": {
            "recommendation": "UNDERWEIGHT",
        },
    }


@pytest.fixture
def empty_snapshot():
    """Minimal snapshot with missing data."""
    return {
        "company_name": "EmptyCo",
        "sector": "Unknown",
    }


# ============================================================
# Temporary file-system fixtures
# ============================================================

@pytest.fixture
def tmp_snapshots_dir(tmp_path):
    """Create a temporary snapshots directory with sample JSON files."""
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()

    # Template (should be skipped)
    (snapshots_dir / "template.json").write_text(
        json.dumps({"company_name": "Template"}), encoding="utf-8"
    )

    # Company snapshot
    (snapshots_dir / "acme.json").write_text(
        json.dumps({"company_name": "Acme Corp", "sector": "TMT"}),
        encoding="utf-8",
    )

    # Another snapshot
    (snapshots_dir / "betaco.json").write_text(
        json.dumps({"company_name": "BetaCo", "sector": "Retail"}),
        encoding="utf-8",
    )

    return snapshots_dir


@pytest.fixture
def tmp_indices_dir(tmp_path):
    """Create a temporary indices directory with sample index JSON."""
    indices_dir = tmp_path / "indices"
    indices_dir.mkdir()

    index_data = {
        "name": "Test Index",
        "total_names": 3,
        "sectors": {
            "TMT": ["Acme Corp", "TeleCo"],
            "Retail": ["BetaCo"],
        },
        "search_aliases": {
            "Acme Corp": ["Acme", "ACME"],
            "BetaCo": ["Beta"],
        },
    }
    (indices_dir / "test_index.json").write_text(
        json.dumps(index_data), encoding="utf-8"
    )
    return indices_dir


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temporary config directory with news_sources.json."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    news_sources = {
        "rss_feeds": {
            "general_credit": [
                {"name": "Test Feed", "url": "https://example.com/rss", "region": "EU"}
            ],
            "european": [],
        },
        "newsapi_keywords": {},
    }
    (config_dir / "news_sources.json").write_text(
        json.dumps(news_sources), encoding="utf-8"
    )
    return config_dir


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir

"""Tests for equity movers social buzz and alert functions."""
import sys
from types import ModuleType
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field

# Stub heavy dependencies before importing equity_movers
for mod in ["yfinance", "feedparser", "dotenv"]:
    if mod not in sys.modules:
        stub = ModuleType(mod)
        if mod == "dotenv":
            stub.load_dotenv = lambda **kw: None
        sys.modules[mod] = stub

# Stub social_sentiment module to avoid macrocosmos/anthropic imports.
# Save any existing entry so we can restore it after import.
_ss_orig = sys.modules.get("monitors.social_sentiment")
_ss_stub = ModuleType("monitors.social_sentiment")

@dataclass
class _FakeSocialPost:
    post_id: str
    source: str
    author: str
    content: str
    posted_at: str
    url: str
    entity_name: str
    keywords_matched: list = field(default_factory=list)

_ss_stub.SocialPost = _FakeSocialPost
_ss_stub.query_gopher = MagicMock(return_value=[])
_ss_stub.query_desearch = MagicMock(return_value=[])
sys.modules["monitors.social_sentiment"] = _ss_stub

from monitors.equity_movers import fetch_social_buzz

# Restore original social_sentiment module entry so other tests are not affected
if _ss_orig is not None:
    sys.modules["monitors.social_sentiment"] = _ss_orig
else:
    del sys.modules["monitors.social_sentiment"]


def test_fetch_social_buzz_returns_dict_with_counts():
    """fetch_social_buzz returns a dict with total, bullish, bearish, neutral, top_post."""
    result = fetch_social_buzz("Grifols SA", ["Grifols"])
    assert isinstance(result, dict)
    assert "total" in result
    assert "bullish" in result
    assert "bearish" in result
    assert "neutral" in result
    assert "top_post" in result


def test_fetch_social_buzz_counts_posts_correctly():
    """Posts from both sources are counted and deduped by post_id."""
    gopher_posts = [
        _FakeSocialPost("p1", "X", "user1", "Grifols downgrade risk high", "2026-02-24T10:00:00Z",
                         "https://x.com/1", "Grifols SA", ["downgrade"]),
        _FakeSocialPost("p2", "X", "user2", "Grifols new drug approval great news", "2026-02-24T11:00:00Z",
                         "https://x.com/2", "Grifols SA", []),
    ]
    desearch_posts = [
        _FakeSocialPost("p1", "X", "user1", "Grifols downgrade risk high", "2026-02-24T10:00:00Z",
                         "https://x.com/1", "Grifols SA", ["downgrade"]),  # duplicate
        _FakeSocialPost("p3", "X", "user3", "Grifols restructuring rumours", "2026-02-24T12:00:00Z",
                         "https://x.com/3", "Grifols SA", ["restructuring"]),
    ]

    with patch("monitors.equity_movers.query_gopher", return_value=gopher_posts), \
         patch("monitors.equity_movers.query_desearch", return_value=desearch_posts):
        result = fetch_social_buzz("Grifols SA", ["Grifols"])

    assert result["total"] == 3  # p1, p2, p3 (p1 deduped)


def test_fetch_social_buzz_sentiment_bucketing():
    """Bearish keywords bucket posts correctly."""
    posts = [
        _FakeSocialPost("p1", "X", "u1", "Grifols default risk rising", "2026-02-24T10:00:00Z",
                         "https://x.com/1", "Grifols SA", ["default"]),
        _FakeSocialPost("p2", "X", "u2", "Grifols upgrade expected", "2026-02-24T11:00:00Z",
                         "https://x.com/2", "Grifols SA", ["upgrade"]),
        _FakeSocialPost("p3", "X", "u3", "Grifols earnings coming up", "2026-02-24T12:00:00Z",
                         "https://x.com/3", "Grifols SA", []),
    ]

    with patch("monitors.equity_movers.query_gopher", return_value=posts), \
         patch("monitors.equity_movers.query_desearch", return_value=[]):
        result = fetch_social_buzz("Grifols SA", ["Grifols"])

    assert result["bearish"] >= 1  # "default" is bearish
    assert result["bullish"] >= 1  # "upgrade" is bullish
    assert result["total"] == 3

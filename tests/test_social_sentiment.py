"""Tests for social sentiment pre-filter."""
import pytest
import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub macrocosmos + anthropic before import
for mod in ["macrocosmos", "anthropic", "dotenv"]:
    if mod not in sys.modules:
        stub = ModuleType(mod)
        if mod == "dotenv":
            stub.load_dotenv = lambda **kw: None
        sys.modules[mod] = stub

from monitors.social_sentiment import NOISE_BLOCKLIST, ENTITY_NOISE


def test_noise_blocklist_exists_and_has_sports_terms():
    assert isinstance(NOISE_BLOCKLIST, list)
    assert len(NOISE_BLOCKLIST) >= 10
    # Must contain key sports terms
    blocklist_lower = [t.lower() for t in NOISE_BLOCKLIST]
    for term in ["grenadiers", "premier league", "cycling"]:
        assert term in blocklist_lower, f"Missing '{term}' from NOISE_BLOCKLIST"


def test_entity_noise_has_ineos():
    assert "INEOS" in ENTITY_NOISE
    ineos_lower = [t.lower() for t in ENTITY_NOISE["INEOS"]]
    assert "manchester united" in ineos_lower
    assert "grenadiers" in ineos_lower


from monitors.social_sentiment import is_credit_noise, SocialPost


def _make_post(content: str, entity_name: str = "INEOS Finance PLC") -> SocialPost:
    """Helper to create test posts."""
    return SocialPost(
        post_id="test_001",
        source="X",
        author="testuser",
        content=content,
        posted_at="2026-02-23T10:00:00Z",
        url="https://x.com/test/1",
        entity_name=entity_name,
        keywords_matched=[],
    )


class TestIsCreditNoise:
    """Test the pre-filter logic."""

    def test_football_post_is_noise(self):
        post = _make_post("INEOS signing better players for Manchester United this window")
        assert is_credit_noise(post) is True

    def test_cycling_post_is_noise(self):
        post = _make_post("Great debut for INEOS Grenadiers at Tour de France stage 3")
        assert is_credit_noise(post) is True

    def test_credit_post_passes_through(self):
        post = _make_post("INEOS Rosignano plant crisis, 600 jobs at risk, regional government intervening")
        assert is_credit_noise(post) is False

    def test_credit_keyword_always_passes(self):
        """Even if noise terms present, credit keywords = pass through."""
        post = _make_post(
            "Manchester United owner INEOS faces restructuring of debt facilities"
        )
        assert is_credit_noise(post) is False

    def test_neutral_post_without_noise_passes(self):
        post = _make_post("INEOS reported Q4 earnings above consensus")
        assert is_credit_noise(post) is False

    def test_entity_specific_noise_only_applies_to_that_entity(self):
        post = _make_post("Nokia Manchester United sponsorship deal", entity_name="Nokia Oyj")
        assert is_credit_noise(post) is True

    def test_non_noisy_entity_passes(self):
        post = _make_post("Worldline SA covenant test approaching", entity_name="Worldline SA/France")
        assert is_credit_noise(post) is False

    def test_empty_content_passes(self):
        """Don't crash on empty posts."""
        post = _make_post("")
        assert is_credit_noise(post) is False

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


from monitors.social_sentiment import is_credit_noise, is_noisy_entity, has_credit_keyword, SocialPost


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


from unittest.mock import patch, MagicMock


def test_run_scan_filters_noise_before_classify(tmp_path):
    """Noise posts should never reach classify_post()."""
    with patch("monitors.social_sentiment.DB_PATH", tmp_path / "test.db"), \
         patch("monitors.social_sentiment.get_demo_posts") as mock_demo, \
         patch("monitors.social_sentiment.classify_post") as mock_classify:

        # 3 posts: 1 noise, 1 credit, 1 borderline-passes
        mock_demo.return_value = [
            _make_post("INEOS Grenadiers cycling at Tour de France"),      # noise
            _make_post("INEOS restructuring debt facilities at holdco"),   # credit keyword
            _make_post("INEOS Rosignano plant facing 600 job losses"),    # no keyword, no noise
        ]
        mock_classify.return_value = MagicMock(
            alert_worthy=False, severity=1, entity_name="test",
            sentiment="neutral", is_new_info=False, claim_summary="",
            post_id="x", credit_relevance="", source_credibility="low",
            raw_post="", author="test", posted_at="", classified_at="",
        )

        from monitors.social_sentiment import run_scan
        run_scan(entity_filter="INEOS", demo_mode=True)

        # classify_post should only be called for the 2 non-noise posts
        assert mock_classify.call_count == 2


def test_dry_run_does_not_classify(tmp_path):
    """--dry-run should show filter results without calling Claude."""
    with patch("monitors.social_sentiment.DB_PATH", tmp_path / "test.db"), \
         patch("monitors.social_sentiment.get_demo_posts") as mock_demo, \
         patch("monitors.social_sentiment.classify_post") as mock_classify:

        mock_demo.return_value = [
            _make_post("INEOS Grenadiers cycling at Algarve"),
            _make_post("INEOS restructuring debt at holdco"),
        ]

        from monitors.social_sentiment import run_scan
        result = run_scan(entity_filter="INEOS", demo_mode=True, dry_run=True)

        # classify_post should never be called in dry-run mode
        assert mock_classify.call_count == 0
        assert result == []


class TestHelperFunctions:
    """Test is_noisy_entity and has_credit_keyword helpers."""

    def test_ineos_is_noisy_entity(self):
        assert is_noisy_entity("INEOS Finance PLC") is True

    def test_nokia_is_noisy_entity(self):
        assert is_noisy_entity("Nokia Oyj") is True

    def test_worldline_is_not_noisy(self):
        assert is_noisy_entity("Worldline SA/France") is False

    def test_has_credit_keyword_restructuring(self):
        assert has_credit_keyword("company faces restructuring of debt") is True

    def test_has_credit_keyword_none(self):
        assert has_credit_keyword("vague commentary about management") is False


class TestHaikuTriage:
    """Test Haiku triage integration (mocked)."""

    def test_haiku_triage_credit_passes(self):
        """Mock Haiku returning CREDIT — post should pass."""
        from monitors.social_sentiment import haiku_triage

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="CREDIT")]

        with patch("monitors.social_sentiment.os.getenv", return_value="test-key"), \
             patch("monitors.social_sentiment.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            post = _make_post("INEOS Rosignano plant crisis affecting 600 jobs")
            assert haiku_triage(post) is True

    def test_haiku_triage_noise_blocked(self):
        """Mock Haiku returning NOISE — post should be blocked."""
        from monitors.social_sentiment import haiku_triage

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="NOISE")]

        with patch("monitors.social_sentiment.os.getenv", return_value="test-key"), \
             patch("monitors.social_sentiment.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            post = _make_post("Generic vague comment about INEOS with no substance")
            assert haiku_triage(post) is False

    def test_haiku_triage_no_api_key_passes_through(self):
        """No API key = pass through (fail open)."""
        from monitors.social_sentiment import haiku_triage

        with patch("monitors.social_sentiment.os.getenv", return_value=None):
            post = _make_post("Some vague INEOS post")
            assert haiku_triage(post) is True


def test_run_scan_uses_haiku_for_ambiguous(tmp_path):
    """Ambiguous posts from noisy entities should go through Haiku triage."""
    with patch("monitors.social_sentiment.DB_PATH", tmp_path / "test.db"), \
         patch("monitors.social_sentiment.get_demo_posts") as mock_demo, \
         patch("monitors.social_sentiment.classify_post") as mock_classify, \
         patch("monitors.social_sentiment.haiku_triage") as mock_haiku:

        mock_demo.return_value = [
            _make_post("INEOS Grenadiers cycling at Tour de France"),      # obvious noise
            _make_post("INEOS restructuring debt facilities at holdco"),   # credit keyword
            _make_post("Generic vague INEOS management commentary"),       # ambiguous -> haiku
        ]
        mock_haiku.return_value = False  # Haiku says noise
        mock_classify.return_value = MagicMock(
            alert_worthy=False, severity=1, entity_name="test",
            sentiment="neutral", is_new_info=False, claim_summary="",
            post_id="x", credit_relevance="", source_credibility="low",
            raw_post="", author="test", posted_at="", classified_at="",
        )

        from monitors.social_sentiment import run_scan
        run_scan(entity_filter="INEOS", demo_mode=True)

        # Haiku should be called once (for the ambiguous post)
        assert mock_haiku.call_count == 1
        # Sonnet should only be called once (the credit keyword post)
        assert mock_classify.call_count == 1

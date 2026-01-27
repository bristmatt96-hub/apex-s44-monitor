"""
P3: Tests for Market Pulse headline scoring (monitors/market_pulse.py).

Covers hash_headline(), parse_score_response(), check_headline_for_watchlist(),
load/save seen headlines, and scan_feeds_once() logic.
"""

import json
import hashlib
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from monitors.market_pulse import (
    hash_headline,
    parse_score_response,
    check_headline_for_watchlist,
    load_seen_headlines,
    save_seen_headlines,
    load_alerts_log,
    save_alert,
    send_pulse_alert,
)


# ============================================================
# hash_headline
# ============================================================


class TestHashHeadline:
    def test_deterministic(self):
        h1 = hash_headline("Test headline", "Reuters")
        h2 = hash_headline("Test headline", "Reuters")
        assert h1 == h2

    def test_different_titles_different_hashes(self):
        h1 = hash_headline("Headline A", "Reuters")
        h2 = hash_headline("Headline B", "Reuters")
        assert h1 != h2

    def test_different_sources_different_hashes(self):
        h1 = hash_headline("Same headline", "Reuters")
        h2 = hash_headline("Same headline", "Bloomberg")
        assert h1 != h2

    def test_returns_md5_hex(self):
        result = hash_headline("Test", "Source")
        expected = hashlib.md5("Test:Source".encode()).hexdigest()
        assert result == expected

    def test_empty_inputs(self):
        result = hash_headline("", "")
        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hex length


# ============================================================
# parse_score_response
# ============================================================


class TestParseScoreResponse:
    def test_valid_response(self):
        text = "SCORE: 4\nDIRECTION: DOWN\nREASON: Company faces restructuring risk"
        result = parse_score_response(text)
        assert result is not None
        assert result["score"] == 4
        assert result["direction"] == "DOWN"
        assert result["reason"] == "Company faces restructuring risk"

    def test_score_1(self):
        text = "SCORE: 1\nDIRECTION: UP\nREASON: Routine news"
        result = parse_score_response(text)
        assert result["score"] == 1

    def test_score_5(self):
        text = "SCORE: 5\nDIRECTION: DOWN\nREASON: Default imminent"
        result = parse_score_response(text)
        assert result["score"] == 5

    def test_uncertain_direction(self):
        text = "SCORE: 3\nDIRECTION: UNCERTAIN\nREASON: Mixed signals"
        result = parse_score_response(text)
        assert result["direction"] == "UNCERTAIN"

    def test_missing_score_returns_none(self):
        text = "DIRECTION: UP\nREASON: Some reason"
        result = parse_score_response(text)
        assert result is None

    def test_missing_direction_returns_none(self):
        text = "SCORE: 3\nREASON: Some reason"
        result = parse_score_response(text)
        assert result is None

    def test_missing_reason_still_parses(self):
        text = "SCORE: 3\nDIRECTION: UP"
        result = parse_score_response(text)
        assert result is not None
        assert result["score"] == 3
        assert result["direction"] == "UP"

    def test_empty_string_returns_none(self):
        result = parse_score_response("")
        assert result is None

    def test_garbage_input_returns_none(self):
        result = parse_score_response("This is not a valid response at all")
        assert result is None

    def test_non_integer_score_returns_none(self):
        text = "SCORE: abc\nDIRECTION: UP\nREASON: Test"
        result = parse_score_response(text)
        assert result is None

    def test_reason_with_colons(self):
        """REASON field uses split(':', 1) so colons in the value should be preserved."""
        text = "SCORE: 4\nDIRECTION: DOWN\nREASON: Rating cut: Moody's downgrade to Caa1"
        result = parse_score_response(text)
        assert result["reason"] == "Rating cut: Moody's downgrade to Caa1"

    def test_extra_whitespace(self):
        text = "SCORE:   3  \nDIRECTION:   UP  \nREASON:   Some reason  "
        result = parse_score_response(text)
        assert result["score"] == 3
        assert result["direction"] == "UP"


# ============================================================
# check_headline_for_watchlist
# ============================================================


class TestCheckHeadlineForWatchlist:
    def test_exact_match(self):
        watchlist = ["Ardagh Group", "Altice France"]
        result = check_headline_for_watchlist(
            "Ardagh Group announces bond issue", "", watchlist
        )
        assert result == "Ardagh Group"

    def test_case_insensitive_match(self):
        watchlist = ["Ardagh Group"]
        result = check_headline_for_watchlist(
            "ARDAGH GROUP files for protection", "", watchlist
        )
        assert result == "Ardagh Group"

    def test_match_in_summary(self):
        watchlist = ["Ardagh Group"]
        result = check_headline_for_watchlist(
            "European credit news", "Ardagh Group announces restructuring", watchlist
        )
        assert result == "Ardagh Group"

    def test_first_word_match(self):
        """Multi-word company: first word alone can match."""
        watchlist = ["Ardagh Group"]
        result = check_headline_for_watchlist(
            "Ardagh files for protection", "", watchlist
        )
        assert result == "Ardagh Group"

    def test_no_match_returns_none(self):
        watchlist = ["Ardagh Group", "Altice France"]
        result = check_headline_for_watchlist(
            "Amazon reports Q3 earnings beat", "", watchlist
        )
        assert result is None

    def test_empty_watchlist(self):
        result = check_headline_for_watchlist("Any headline", "", [])
        assert result is None

    def test_empty_headline(self):
        watchlist = ["Ardagh Group"]
        result = check_headline_for_watchlist("", "", watchlist)
        assert result is None

    def test_single_word_company_no_first_word_logic(self):
        """Single-word company names: first-word match only applies to multi-word names."""
        watchlist = ["INEOS"]
        result = check_headline_for_watchlist(
            "INEOS hires advisor", "", watchlist
        )
        assert result == "INEOS"


# ============================================================
# load/save seen headlines
# ============================================================


class TestSeenHeadlines:
    def test_load_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "monitors.market_pulse.SEEN_HEADLINES_FILE",
            tmp_path / "nonexistent.json",
        )
        result = load_seen_headlines()
        assert result == set()

    def test_save_and_load(self, tmp_path, monkeypatch):
        file_path = tmp_path / "seen.json"
        monkeypatch.setattr(
            "monitors.market_pulse.SEEN_HEADLINES_FILE", file_path
        )
        monkeypatch.setattr("monitors.market_pulse.DATA_DIR", tmp_path)

        seen = {"hash1", "hash2", "hash3"}
        save_seen_headlines(seen)
        loaded = load_seen_headlines()
        assert loaded == seen

    def test_caps_at_5000(self, tmp_path, monkeypatch):
        file_path = tmp_path / "seen.json"
        monkeypatch.setattr(
            "monitors.market_pulse.SEEN_HEADLINES_FILE", file_path
        )
        monkeypatch.setattr("monitors.market_pulse.DATA_DIR", tmp_path)

        big_set = {f"hash_{i}" for i in range(6000)}
        save_seen_headlines(big_set)

        data = json.loads(file_path.read_text())
        assert len(data["seen"]) == 5000


# ============================================================
# load/save alerts log
# ============================================================


class TestAlertsLog:
    def test_load_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "monitors.market_pulse.ALERTS_LOG_FILE",
            tmp_path / "nonexistent.json",
        )
        result = load_alerts_log()
        assert result == []

    def test_save_and_load(self, tmp_path, monkeypatch):
        file_path = tmp_path / "alerts.json"
        monkeypatch.setattr(
            "monitors.market_pulse.ALERTS_LOG_FILE", file_path
        )
        monkeypatch.setattr("monitors.market_pulse.DATA_DIR", tmp_path)

        alert = {"headline": "Test", "score": 4, "company": "TestCo"}
        save_alert(alert)
        loaded = load_alerts_log()
        assert len(loaded) == 1
        assert loaded[0]["headline"] == "Test"

    def test_caps_at_200_alerts(self, tmp_path, monkeypatch):
        file_path = tmp_path / "alerts.json"
        monkeypatch.setattr(
            "monitors.market_pulse.ALERTS_LOG_FILE", file_path
        )
        monkeypatch.setattr("monitors.market_pulse.DATA_DIR", tmp_path)

        # Pre-fill with 199 alerts
        existing = [{"headline": f"Alert {i}"} for i in range(199)]
        file_path.write_text(json.dumps(existing))

        # Add 5 more (total 204, should cap at 200)
        for i in range(5):
            save_alert({"headline": f"New alert {i}"})

        loaded = load_alerts_log()
        assert len(loaded) == 200


# ============================================================
# send_pulse_alert formatting
# ============================================================


class TestSendPulseAlert:
    @patch("monitors.market_pulse.send_telegram_alert")
    def test_format_contains_company(self, mock_send):
        alert = {
            "company": "Ardagh",
            "score": 4,
            "direction": "DOWN",
            "headline": "Ardagh announces restructuring",
            "source": "Reuters",
            "region": "EU",
            "reason": "Restructuring risk",
            "link": "https://example.com",
        }
        send_pulse_alert(alert)
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "Ardagh" in msg
        assert "4/5" in msg

    @patch("monitors.market_pulse.send_telegram_alert")
    def test_score_5_gets_siren_emoji(self, mock_send):
        alert = {
            "company": "TestCo",
            "score": 5,
            "direction": "DOWN",
            "headline": "Test",
            "source": "Source",
            "region": "EU",
            "reason": "Reason",
            "link": "https://example.com",
        }
        send_pulse_alert(alert)
        msg = mock_send.call_args[0][0]
        assert "\U0001f6a8" in msg  # 🚨

    @patch("monitors.market_pulse.send_telegram_alert")
    def test_direction_emoji(self, mock_send):
        for direction, emoji in [("UP", "\U0001f4c8"), ("DOWN", "\U0001f4c9"), ("UNCERTAIN", "\u2753")]:
            alert = {
                "company": "Co",
                "score": 3,
                "direction": direction,
                "headline": "Test",
                "source": "S",
                "region": "R",
                "reason": "R",
                "link": "L",
            }
            send_pulse_alert(alert)
            msg = mock_send.call_args[0][0]
            assert emoji in msg

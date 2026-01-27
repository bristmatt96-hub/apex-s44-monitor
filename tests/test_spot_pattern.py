"""
P7: Tests for news pattern detection (NewsHound.spot_pattern from apex_monitor.py).

Tests the classification of tweet text into credit impact categories,
including sector-specific logic.
"""

import pytest
from apex_monitor import NewsHound


@pytest.fixture
def hound():
    """Create a NewsHound instance with minimal index data."""
    index_data = {
        "name": "Test Index",
        "total_names": 2,
        "sectors": {
            "Autos & Industrials": ["ThyssenKrupp"],
            "TMT": ["Altice France"],
        },
        "search_aliases": {},
    }
    return NewsHound(index_data)


# ============================================================
# Rating-related patterns
# ============================================================


class TestRatingPatterns:
    def test_downgrade(self, hound):
        result = hound.spot_pattern("TestCo", "Moody's downgrade to Caa1", "TMT")
        assert "NEGATIVE" in result
        assert "Rating pressure" in result

    def test_negative_outlook(self, hound):
        result = hound.spot_pattern("TestCo", "S&P revises to negative outlook", "TMT")
        assert "NEGATIVE" in result

    def test_rating_cut(self, hound):
        result = hound.spot_pattern("TestCo", "Fitch announces rating cut", "TMT")
        assert "NEGATIVE" in result

    def test_upgrade(self, hound):
        result = hound.spot_pattern("TestCo", "Company receives rating upgrade", "TMT")
        assert "POSITIVE" in result

    def test_positive_outlook(self, hound):
        result = hound.spot_pattern("TestCo", "Positive outlook from Moody's", "TMT")
        assert "POSITIVE" in result


# ============================================================
# Restructuring/default patterns
# ============================================================


class TestRestructuringPatterns:
    def test_restructuring(self, hound):
        result = hound.spot_pattern(
            "TestCo", "Company announces restructuring plan", "TMT"
        )
        assert "HIGH RISK" in result
        assert "Restructuring" in result

    def test_bankruptcy(self, hound):
        result = hound.spot_pattern(
            "TestCo", "Company files for bankruptcy protection", "TMT"
        )
        assert "HIGH RISK" in result

    def test_default(self, hound):
        result = hound.spot_pattern(
            "TestCo", "Company enters default on senior bonds", "TMT"
        )
        assert "HIGH RISK" in result


# ============================================================
# M&A patterns
# ============================================================


class TestMandAPatterns:
    def test_acquisition(self, hound):
        result = hound.spot_pattern(
            "TestCo", "Company announces acquisition of rival", "TMT"
        )
        assert "EVENT" in result
        assert "M&A" in result

    def test_takeover(self, hound):
        result = hound.spot_pattern("TestCo", "Hostile takeover bid launched", "TMT")
        assert "EVENT" in result

    def test_buyout(self, hound):
        result = hound.spot_pattern(
            "TestCo", "PE firm launches buyout offer for company", "TMT"
        )
        assert "EVENT" in result

    def test_m_and_a(self, hound):
        result = hound.spot_pattern("TestCo", "m&a deal announced", "TMT")
        assert "EVENT" in result


# ============================================================
# Refinancing patterns
# ============================================================


class TestRefinancingPatterns:
    def test_refinancing(self, hound):
        result = hound.spot_pattern(
            "TestCo", "Company completes refinancing of TLB", "TMT"
        )
        assert "NEUTRAL" in result
        assert "Refinancing" in result

    def test_bond_issue(self, hound):
        result = hound.spot_pattern(
            "TestCo", "New bond issue announced at 8% coupon", "TMT"
        )
        assert "NEUTRAL" in result

    def test_new_debt(self, hound):
        result = hound.spot_pattern(
            "TestCo", "Company raises new debt facility", "TMT"
        )
        assert "NEUTRAL" in result


# ============================================================
# Regulatory patterns
# ============================================================


class TestRegulatoryPatterns:
    def test_antitrust(self, hound):
        result = hound.spot_pattern(
            "TestCo", "EU antitrust probe into company", "TMT"
        )
        assert "RISK" in result
        assert "Regulatory" in result

    def test_investigation(self, hound):
        result = hound.spot_pattern(
            "TestCo", "Regulatory investigation announced", "TMT"
        )
        assert "RISK" in result


# ============================================================
# Sector-specific patterns — Autos & Industrials
# ============================================================


class TestAutosSectorPatterns:
    def test_tariff_in_autos(self, hound):
        result = hound.spot_pattern(
            "ThyssenKrupp", "New tariff on steel imports", "Autos & Industrials"
        )
        assert "SECTOR" in result
        assert "Auto/Industrial" in result

    def test_ev_in_autos(self, hound):
        result = hound.spot_pattern(
            "ThyssenKrupp", "EV transition accelerating", "Autos & Industrials"
        )
        assert "SECTOR" in result

    def test_supply_chain_in_autos(self, hound):
        result = hound.spot_pattern(
            "ThyssenKrupp",
            "Global supply chain disruptions worsen",
            "Autos & Industrials",
        )
        assert "SECTOR" in result

    def test_tariff_in_non_autos(self, hound):
        """Tariff keyword should NOT trigger sector-specific for TMT."""
        result = hound.spot_pattern("Altice", "New tariff imposed", "TMT")
        assert "Auto/Industrial" not in result


# ============================================================
# Sector-specific patterns — TMT
# ============================================================


class TestTMTSectorPatterns:
    def test_spectrum_in_tmt(self, hound):
        result = hound.spot_pattern(
            "Altice", "Company acquires new spectrum band", "TMT"
        )
        assert "SECTOR" in result
        assert "TMT" in result

    def test_fiber_in_tmt(self, hound):
        result = hound.spot_pattern(
            "Altice", "Fiber rollout reaches 10M homes", "TMT"
        )
        assert "SECTOR" in result

    def test_5g_in_tmt(self, hound):
        result = hound.spot_pattern("Altice", "5g deployment on track", "TMT")
        assert "SECTOR" in result

    def test_subscriber_in_tmt(self, hound):
        result = hound.spot_pattern(
            "Altice", "Subscriber growth slows in Q3", "TMT"
        )
        assert "SECTOR" in result

    def test_spectrum_in_non_tmt(self, hound):
        """Spectrum keyword should NOT trigger sector-specific for Autos."""
        result = hound.spot_pattern(
            "ThyssenKrupp", "Spectrum allocation news", "Autos & Industrials"
        )
        assert "TMT" not in result


# ============================================================
# Default fallback
# ============================================================


class TestDefaultPattern:
    def test_no_specific_match_returns_monitor(self, hound):
        result = hound.spot_pattern(
            "TestCo", "Company announces new marketing campaign", "TMT"
        )
        assert "MONITOR" in result

    def test_empty_text_returns_monitor(self, hound):
        result = hound.spot_pattern("TestCo", "", "TMT")
        assert "MONITOR" in result

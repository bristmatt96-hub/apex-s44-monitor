"""
P1: Tests for the trading signal scoring engine.

Covers calculate_signal_score() and get_search_terms() from apex_monitor.py.
These are the core decision-making functions that generate LONG/SHORT/NEUTRAL signals.
"""

import pytest
from apex_monitor import calculate_signal_score, get_search_terms


# ============================================================
# calculate_signal_score — basic signal classification
# ============================================================


class TestSignalClassification:
    """Score thresholds: >= 30 → LONG, <= -30 → SHORT, else NEUTRAL."""

    def test_no_snapshot_returns_no_data(self):
        score, signal, rationale = calculate_signal_score(None)
        assert score == 0
        assert signal == "NO DATA"
        assert "Insufficient data" in rationale[0]

    def test_empty_snapshot_returns_no_data(self):
        """Empty dict is falsy in Python, so treated same as None."""
        score, signal, rationale = calculate_signal_score({})
        assert score == 0
        assert signal == "NO DATA"

    def test_strong_credit_returns_long(self, strong_credit_snapshot):
        score, signal, rationale = calculate_signal_score(strong_credit_snapshot)
        assert signal == "LONG"
        assert score >= 30

    def test_weak_credit_returns_short(self, weak_credit_snapshot):
        score, signal, rationale = calculate_signal_score(weak_credit_snapshot)
        assert signal == "SHORT"
        assert score <= -30

    def test_neutral_snapshot_returns_neutral(self, empty_snapshot):
        score, signal, rationale = calculate_signal_score(empty_snapshot)
        assert signal == "NEUTRAL"


# ============================================================
# calculate_signal_score — leverage component
# ============================================================


class TestLeverageScoring:
    def test_low_leverage_adds_positive_score(self):
        snapshot = {"key_ratios": {"debt_to_ebitda": 3.5}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert score > 0
        assert any("Low leverage" in r for r in rationale)

    def test_high_leverage_subtracts_score(self):
        snapshot = {"key_ratios": {"debt_to_ebitda": 6.5}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert score < 0
        assert any("High leverage" in r for r in rationale)

    def test_moderate_leverage_subtracts_less(self):
        snapshot = {"key_ratios": {"debt_to_ebitda": 5.5}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert score < 0
        assert any("Moderate leverage" in r for r in rationale)

    def test_leverage_at_boundary_4(self):
        """Exactly 4.0 should NOT get the low-leverage bonus (< 4.0 required)."""
        snapshot = {"key_ratios": {"debt_to_ebitda": 4.0}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert not any("Low leverage" in r for r in rationale)

    def test_leverage_none_is_skipped(self):
        snapshot = {"key_ratios": {"debt_to_ebitda": None}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert not any("leverage" in r.lower() for r in rationale)

    def test_leverage_non_numeric_string(self):
        snapshot = {"key_ratios": {"debt_to_ebitda": "N/A"}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        # Should handle gracefully without crashing
        assert isinstance(score, (int, float))

    def test_leverage_string_number(self):
        """Leverage passed as string should be converted to float."""
        snapshot = {"key_ratios": {"debt_to_ebitda": "3.5"}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert any("Low leverage" in r for r in rationale)


# ============================================================
# calculate_signal_score — interest coverage component
# ============================================================


class TestCoverageScoring:
    def test_strong_coverage_adds_score(self):
        snapshot = {
            "key_ratios": {"ebitda_minus_capex_to_interest": 4.0},
            "quick_assessment": {},
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert score > 0
        assert any("Strong interest coverage" in r for r in rationale)

    def test_weak_coverage_subtracts_score(self):
        snapshot = {
            "key_ratios": {"ebitda_minus_capex_to_interest": 1.0},
            "quick_assessment": {},
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert score < 0
        assert any("Weak interest coverage" in r for r in rationale)

    def test_coverage_none_is_skipped(self):
        snapshot = {
            "key_ratios": {"ebitda_minus_capex_to_interest": None},
            "quick_assessment": {},
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert not any("coverage" in r.lower() for r in rationale)


# ============================================================
# calculate_signal_score — FCF component
# ============================================================


class TestFCFScoring:
    def test_strong_fcf_adds_score(self):
        snapshot = {"key_ratios": {"fcf_to_debt": 0.15}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert score > 0
        assert any("Strong FCF" in r for r in rationale)

    def test_negative_fcf_subtracts_score(self):
        snapshot = {"key_ratios": {"fcf_to_debt": -0.05}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert score < 0
        assert any("Negative FCF" in r for r in rationale)

    def test_fcf_zero_no_contribution(self):
        """Zero FCF is falsy, so the branch is skipped entirely."""
        snapshot = {"key_ratios": {"fcf_to_debt": 0}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert not any("FCF" in r for r in rationale)


# ============================================================
# calculate_signal_score — liquidity component
# ============================================================


class TestLiquidityScoring:
    def test_adequate_liquidity_adds_score(self):
        snapshot = {
            "key_ratios": {},
            "quick_assessment": {
                "cash_on_hand": 500,
                "revolver_available": 300,
                "debt_due_one_year": 200,
            },
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert any("Adequate liquidity" in r for r in rationale)

    def test_liquidity_concern_subtracts_score(self):
        snapshot = {
            "key_ratios": {},
            "quick_assessment": {
                "cash_on_hand": 50,
                "revolver_available": 20,
                "debt_due_one_year": 200,
            },
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert any("Liquidity concern" in r for r in rationale)

    def test_zero_debt_due_skips_liquidity(self):
        """No near-term maturities means no liquidity assessment."""
        snapshot = {
            "key_ratios": {},
            "quick_assessment": {
                "cash_on_hand": 100,
                "revolver_available": 0,
                "debt_due_one_year": 0,
            },
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert not any("liquidity" in r.lower() for r in rationale)

    def test_missing_liquidity_fields_no_crash(self):
        snapshot = {"key_ratios": {}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot)
        assert isinstance(score, (int, float))

    def test_non_numeric_liquidity_fields(self):
        snapshot = {
            "key_ratios": {},
            "quick_assessment": {
                "cash_on_hand": "N/A",
                "revolver_available": None,
                "debt_due_one_year": "unknown",
            },
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert isinstance(score, (int, float))


# ============================================================
# calculate_signal_score — credit opinion component
# ============================================================


class TestOpinionScoring:
    def test_overweight_adds_score(self):
        snapshot = {
            "key_ratios": {},
            "quick_assessment": {},
            "credit_opinion": {"recommendation": "OVERWEIGHT"},
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert score > 0
        assert any("Overweight" in r for r in rationale)

    def test_underweight_subtracts_score(self):
        snapshot = {
            "key_ratios": {},
            "quick_assessment": {},
            "credit_opinion": {"recommendation": "UNDERWEIGHT"},
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert score < 0
        assert any("Underweight" in r for r in rationale)

    def test_neutral_recommendation_no_adjustment(self):
        snapshot = {
            "key_ratios": {},
            "quick_assessment": {},
            "credit_opinion": {"recommendation": "NEUTRAL"},
        }
        score, _, rationale = calculate_signal_score(snapshot)
        assert not any("Overweight" in r or "Underweight" in r for r in rationale)


# ============================================================
# calculate_signal_score — news sentiment component
# ============================================================


class TestNewsSentiment:
    def test_positive_sentiment_adds_score(self):
        snapshot = {"key_ratios": {}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot, news_sentiment=2)
        assert score > 0
        assert any("Positive news" in r for r in rationale)

    def test_negative_sentiment_subtracts_score(self):
        snapshot = {"key_ratios": {}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot, news_sentiment=-2)
        assert score < 0
        assert any("Negative news" in r for r in rationale)

    def test_zero_sentiment_no_adjustment(self):
        snapshot = {"key_ratios": {}, "quick_assessment": {}}
        score, _, rationale = calculate_signal_score(snapshot, news_sentiment=0)
        assert not any("news" in r.lower() for r in rationale)


# ============================================================
# calculate_signal_score — combined scoring
# ============================================================


class TestCombinedScoring:
    def test_all_positive_factors(self, strong_credit_snapshot):
        score, signal, rationale = calculate_signal_score(
            strong_credit_snapshot, news_sentiment=1
        )
        assert signal == "LONG"
        assert len(rationale) >= 4  # leverage + coverage + FCF + liquidity + opinion

    def test_all_negative_factors(self, weak_credit_snapshot):
        score, signal, rationale = calculate_signal_score(
            weak_credit_snapshot, news_sentiment=-1
        )
        assert signal == "SHORT"
        assert len(rationale) >= 4

    def test_score_is_numeric(self, sample_snapshot):
        score, _, _ = calculate_signal_score(sample_snapshot)
        assert isinstance(score, (int, float))

    def test_rationale_is_list_of_strings(self, sample_snapshot):
        _, _, rationale = calculate_signal_score(sample_snapshot)
        assert isinstance(rationale, list)
        for r in rationale:
            assert isinstance(r, str)


# ============================================================
# get_search_terms
# ============================================================


class TestGetSearchTerms:
    def test_name_only_when_no_aliases(self):
        result = get_search_terms("Acme Corp", {})
        assert result == ["Acme Corp"]

    def test_name_plus_aliases(self):
        aliases = {"Acme Corp": ["Acme", "ACME"]}
        result = get_search_terms("Acme Corp", aliases)
        assert result == ["Acme Corp", "Acme", "ACME"]

    def test_name_not_in_aliases(self):
        aliases = {"OtherCo": ["Other"]}
        result = get_search_terms("Acme Corp", aliases)
        assert result == ["Acme Corp"]

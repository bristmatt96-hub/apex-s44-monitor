"""
P2a: Tests for the ISDA Credit Event Analyzer (monitors/isda_analyzer.py).

Covers analyze_text_for_isda(), format_isda_alert(), and get_full_isda_analysis().
"""

import pytest
from monitors.isda_analyzer import (
    analyze_text_for_isda,
    format_isda_alert,
    get_full_isda_analysis,
    CreditEventType,
    ISDAAnalysis,
    ISDA_DEFINITIONS,
    HIGH_PRIORITY_TRIGGERS,
)


# ============================================================
# analyze_text_for_isda — event type detection
# ============================================================


class TestEventTypeDetection:
    def test_bankruptcy_detected(self):
        result = analyze_text_for_isda(
            "Company X files for Chapter 11 bankruptcy protection"
        )
        assert result.event_type == CreditEventType.BANKRUPTCY

    def test_failure_to_pay_detected(self):
        result = analyze_text_for_isda(
            "Company Y has missed payment on senior notes due today"
        )
        assert result.event_type == CreditEventType.FAILURE_TO_PAY

    def test_restructuring_detected(self):
        result = analyze_text_for_isda(
            "Company Z announces debt exchange offer with maturity extension and coupon reduction"
        )
        assert result.event_type == CreditEventType.RESTRUCTURING

    def test_succession_event_detected(self):
        result = analyze_text_for_isda(
            "Company A acquires Company B in merger deal"
        )
        assert result.event_type == CreditEventType.SUCCESSION_EVENT

    def test_not_a_credit_event_detected(self):
        result = analyze_text_for_isda(
            "Company receives rating downgrade from Moody's, negative outlook"
        )
        assert result.event_type == CreditEventType.NOT_A_CREDIT_EVENT

    def test_no_triggers_returns_watch(self):
        result = analyze_text_for_isda(
            "Company reports quarterly revenue in line with expectations"
        )
        assert result.event_type == CreditEventType.WATCH
        assert result.confidence == "Low"
        assert result.triggers_found == []

    def test_empty_text(self):
        result = analyze_text_for_isda("")
        assert result.event_type == CreditEventType.WATCH


# ============================================================
# analyze_text_for_isda — priority ordering
# ============================================================


class TestEventPriority:
    """Bankruptcy > Failure to Pay > Restructuring > Succession > Not CE."""

    def test_bankruptcy_takes_priority_over_restructuring(self):
        result = analyze_text_for_isda(
            "Company files for bankruptcy amid restructuring talks"
        )
        assert result.event_type == CreditEventType.BANKRUPTCY

    def test_failure_to_pay_takes_priority_over_succession(self):
        result = analyze_text_for_isda(
            "Company failed to pay following merger announcement"
        )
        assert result.event_type == CreditEventType.FAILURE_TO_PAY

    def test_restructuring_takes_priority_over_succession(self):
        result = analyze_text_for_isda(
            "Company announces restructuring and asset sale"
        )
        assert result.event_type == CreditEventType.RESTRUCTURING


# ============================================================
# analyze_text_for_isda — confidence levels
# ============================================================


class TestConfidenceLevels:
    def test_high_confidence_with_three_plus_matches(self):
        text = (
            "Company files for Chapter 11 bankruptcy, enters administration, "
            "insolvency proceedings under creditor protection"
        )
        result = analyze_text_for_isda(text)
        assert result.confidence == "High"

    def test_medium_confidence_with_two_matches(self):
        text = "Company missed payment, coupon missed on senior notes"
        result = analyze_text_for_isda(text)
        assert result.confidence == "Medium"

    def test_low_confidence_with_one_match(self):
        text = "Company files for chapter 11"
        result = analyze_text_for_isda(text)
        assert result.confidence == "Low"


# ============================================================
# analyze_text_for_isda — high priority flag
# ============================================================


class TestHighPriority:
    def test_bankruptcy_is_high_priority(self):
        result = analyze_text_for_isda("Company files for bankruptcy")
        assert result.is_high_priority is True

    def test_missed_payment_is_high_priority(self):
        result = analyze_text_for_isda("Company missed payment on bonds")
        assert result.is_high_priority is True

    def test_restructuring_is_high_priority(self):
        result = analyze_text_for_isda("Company announces restructuring of debt")
        assert result.is_high_priority is True

    def test_routine_news_is_not_high_priority(self):
        result = analyze_text_for_isda("Company reports solid quarterly earnings")
        assert result.is_high_priority is False


# ============================================================
# analyze_text_for_isda — result structure
# ============================================================


class TestAnalysisResultStructure:
    def test_result_is_isda_analysis(self):
        result = analyze_text_for_isda("Company files for bankruptcy")
        assert isinstance(result, ISDAAnalysis)

    def test_result_has_all_fields(self):
        result = analyze_text_for_isda("Company files for bankruptcy")
        assert hasattr(result, "event_type")
        assert hasattr(result, "confidence")
        assert hasattr(result, "triggers_found")
        assert hasattr(result, "isda_notes")
        assert hasattr(result, "what_to_watch")
        assert hasattr(result, "summary")
        assert hasattr(result, "is_high_priority")

    def test_triggers_found_are_strings(self):
        result = analyze_text_for_isda("Company files for bankruptcy")
        for trigger in result.triggers_found:
            assert isinstance(trigger, str)

    def test_isda_notes_populated_for_known_event(self):
        result = analyze_text_for_isda("Company files for bankruptcy")
        assert len(result.isda_notes) > 0

    def test_what_to_watch_populated_for_known_event(self):
        result = analyze_text_for_isda("Company files for bankruptcy")
        assert len(result.what_to_watch) > 0


# ============================================================
# analyze_text_for_isda — summary text
# ============================================================


class TestSummaryText:
    def test_not_ce_summary_mentions_escalation(self):
        result = analyze_text_for_isda("Company faces rating downgrade")
        assert "Not a Credit Event" in result.summary or "escalation" in result.summary

    def test_succession_summary_mentions_dc(self):
        result = analyze_text_for_isda("Company acquires target in merger")
        assert "Succession" in result.summary

    def test_bankruptcy_summary_mentions_verify(self):
        result = analyze_text_for_isda("Company files for bankruptcy")
        assert "Bankruptcy" in result.summary

    def test_watch_summary_for_no_matches(self):
        result = analyze_text_for_isda("Nothing notable happened today")
        assert "No clear ISDA" in result.summary


# ============================================================
# analyze_text_for_isda — case insensitivity
# ============================================================


class TestCaseInsensitivity:
    def test_uppercase_triggers_detected(self):
        result = analyze_text_for_isda("COMPANY FILES FOR BANKRUPTCY")
        assert result.event_type == CreditEventType.BANKRUPTCY

    def test_mixed_case_triggers_detected(self):
        result = analyze_text_for_isda("Company Files For Chapter 11")
        assert result.event_type == CreditEventType.BANKRUPTCY


# ============================================================
# format_isda_alert
# ============================================================


class TestFormatISDAAlert:
    def test_format_contains_event_type(self):
        analysis = analyze_text_for_isda("Company files for bankruptcy")
        result = format_isda_alert("Test tweet", analysis)
        assert "Bankruptcy" in result

    def test_format_contains_confidence(self):
        analysis = analyze_text_for_isda("Company files for bankruptcy")
        result = format_isda_alert("Test tweet", analysis)
        assert analysis.confidence in result

    def test_format_contains_triggers(self):
        analysis = analyze_text_for_isda("Company files for bankruptcy")
        result = format_isda_alert("Test tweet", analysis)
        assert "Triggers:" in result

    def test_format_contains_watch_item(self):
        analysis = analyze_text_for_isda("Company files for bankruptcy")
        result = format_isda_alert("Test tweet", analysis)
        assert "Watch:" in result

    def test_format_bankruptcy_has_siren_emoji(self):
        analysis = analyze_text_for_isda("Company files for bankruptcy")
        result = format_isda_alert("Test tweet", analysis)
        # The emoji for BANKRUPTCY is the siren
        assert "\U0001f6a8" in result  # 🚨

    def test_format_watch_has_no_triggers_section(self):
        analysis = analyze_text_for_isda("Routine quarterly results")
        result = format_isda_alert("Test tweet", analysis)
        # WATCH type with no triggers should not have "Triggers:" line
        assert "Triggers:" not in result or analysis.triggers_found


# ============================================================
# get_full_isda_analysis
# ============================================================


class TestGetFullISDAAnalysis:
    def test_returns_string(self):
        result = get_full_isda_analysis("Company files for bankruptcy")
        assert isinstance(result, str)

    def test_contains_section_headers(self):
        result = get_full_isda_analysis("Company files for bankruptcy")
        assert "## ISDA Analysis" in result
        assert "### Triggers Detected" in result
        assert "### ISDA Notes" in result
        assert "### What to Watch" in result

    def test_restructuring_includes_subtypes(self):
        result = get_full_isda_analysis(
            "Company announces exchange offer with maturity extension and coupon reduction"
        )
        assert "### Restructuring Types" in result
        assert "Mod-R" in result

    def test_non_restructuring_has_no_subtypes(self):
        result = get_full_isda_analysis("Company files for bankruptcy")
        assert "### Restructuring Types" not in result


# ============================================================
# ISDA_DEFINITIONS structure
# ============================================================


class TestISDADefinitions:
    def test_all_event_types_have_definitions(self):
        expected_types = [
            CreditEventType.BANKRUPTCY,
            CreditEventType.FAILURE_TO_PAY,
            CreditEventType.RESTRUCTURING,
            CreditEventType.SUCCESSION_EVENT,
            CreditEventType.NOT_A_CREDIT_EVENT,
        ]
        for et in expected_types:
            assert et in ISDA_DEFINITIONS

    def test_each_definition_has_triggers(self):
        for event_type, defn in ISDA_DEFINITIONS.items():
            assert "triggers" in defn
            assert len(defn["triggers"]) > 0

    def test_each_definition_has_isda_notes(self):
        for event_type, defn in ISDA_DEFINITIONS.items():
            assert "isda_notes" in defn

    def test_each_definition_has_what_to_watch(self):
        for event_type, defn in ISDA_DEFINITIONS.items():
            assert "what_to_watch" in defn

    def test_high_priority_triggers_exist(self):
        assert len(HIGH_PRIORITY_TRIGGERS) > 0
        for trigger in HIGH_PRIORITY_TRIGGERS:
            assert isinstance(trigger, str)

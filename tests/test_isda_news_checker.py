"""
P2b: Tests for the ISDA News-to-Credit-Event Checker (monitors/isda_news_checker.py).

Covers scan_headline(), scan_headlines_batch(), generate_credit_event_checklist(),
rapid_response_analysis(), GracePeriodTracker, and analyze_news_for_isda().
"""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from monitors.isda_news_checker import (
    scan_headline,
    scan_headlines_batch,
    generate_credit_event_checklist,
    rapid_response_analysis,
    analyze_news_for_isda,
    GracePeriodTracker,
    ISDA_KEYWORDS,
    ISDA_SECTIONS,
)


# ============================================================
# scan_headline — keyword matching
# ============================================================


class TestScanHeadline:
    def test_bankruptcy_keyword_detected(self):
        matches = scan_headline("Company files for chapter 11", "TestCo")
        assert len(matches) >= 1
        assert matches[0]["category"] == "bankruptcy"
        assert matches[0]["urgency"] == "CRITICAL"

    def test_failure_to_pay_detected(self):
        matches = scan_headline("Company missed payment on senior notes", "TestCo")
        assert any(m["category"] == "failure_to_pay" for m in matches)

    def test_restructuring_detected(self):
        matches = scan_headline("Company announces exchange offer", "TestCo")
        assert any(m["category"] == "restructuring" for m in matches)

    def test_binding_mechanisms_detected(self):
        matches = scan_headline(
            "Company proposes scheme of arrangement for creditors", "TestCo"
        )
        assert any(m["category"] == "binding_mechanisms" for m in matches)

    def test_advisor_engagement_detected(self):
        matches = scan_headline(
            "Company hires Houlihan Lokey as restructuring advisor", "TestCo"
        )
        assert any(m["category"] == "advisor_engagement" for m in matches)

    def test_cds_specific_detected(self):
        matches = scan_headline(
            "ISDA determinations committee to review credit event referral", "TestCo"
        )
        assert any(m["category"] == "cds_specific" for m in matches)

    def test_no_match_returns_empty(self):
        matches = scan_headline("Company reports Q3 results in line", "TestCo")
        assert matches == []

    def test_case_insensitive(self):
        matches = scan_headline("COMPANY FILES FOR BANKRUPTCY", "TestCo")
        assert len(matches) >= 1

    def test_company_included_in_match(self):
        matches = scan_headline("Company files for bankruptcy", "AcmeCo")
        assert matches[0]["company"] == "AcmeCo"

    def test_headline_included_in_match(self):
        headline = "Company files for bankruptcy"
        matches = scan_headline(headline, "TestCo")
        assert matches[0]["headline"] == headline

    def test_one_match_per_category(self):
        """Multiple triggers from the same category should only produce one match."""
        matches = scan_headline(
            "Company files chapter 11 bankruptcy insolvency", "TestCo"
        )
        bankruptcy_matches = [m for m in matches if m["category"] == "bankruptcy"]
        assert len(bankruptcy_matches) == 1

    def test_multiple_categories_matched(self):
        """A headline can match multiple categories."""
        matches = scan_headline(
            "Company files for bankruptcy, houlihan lokey hired", "TestCo"
        )
        categories = {m["category"] for m in matches}
        assert "bankruptcy" in categories
        assert "advisor_engagement" in categories

    def test_match_has_isda_section(self):
        matches = scan_headline("Company files for bankruptcy", "TestCo")
        assert matches[0]["isda_section"] == "4.2"


# ============================================================
# scan_headlines_batch
# ============================================================


class TestScanHeadlinesBatch:
    def test_groups_by_urgency(self):
        headlines = [
            {"headline": "Company files for bankruptcy", "company": "A"},
            {"headline": "Company hires Lazard", "company": "B"},
            {"headline": "Normal earnings report", "company": "C"},
        ]
        results = scan_headlines_batch(headlines)
        assert results["total_scanned"] == 3
        assert len(results["CRITICAL"]) >= 1
        assert "WATCH" in results

    def test_empty_input(self):
        results = scan_headlines_batch([])
        assert results["total_scanned"] == 0
        assert results["total_flagged"] == 0

    def test_all_clean_headlines(self):
        headlines = [
            {"headline": "Revenue in line with expectations", "company": "A"},
            {"headline": "New product launch announced", "company": "B"},
        ]
        results = scan_headlines_batch(headlines)
        assert results["total_flagged"] == 0

    def test_total_flagged_counts_all_matches(self):
        headlines = [
            {"headline": "Company files for bankruptcy, hires Kirkland", "company": "A"},
        ]
        results = scan_headlines_batch(headlines)
        # bankruptcy + advisor_engagement
        assert results["total_flagged"] >= 2


# ============================================================
# generate_credit_event_checklist
# ============================================================


class TestGenerateCreditEventChecklist:
    def test_bankruptcy_checklist(self):
        result = generate_credit_event_checklist(
            "bankruptcy", "Company files Chapter 11"
        )
        assert result["event_type"] == "bankruptcy"
        assert result["status"] == "PENDING_ANALYSIS"
        assert "questions" in result["checklist"]
        assert len(result["checklist"]["questions"]) > 4

    def test_failure_to_pay_checklist(self):
        result = generate_credit_event_checklist(
            "failure_to_pay", "Company missed payment"
        )
        assert "grace period" in " ".join(result["checklist"]["questions"]).lower()

    def test_restructuring_checklist(self):
        result = generate_credit_event_checklist(
            "restructuring", "Company announces exchange offer"
        )
        assert any(
            "voluntary" in q.lower() or "binding" in q.lower()
            for q in result["checklist"]["questions"]
        )

    def test_cds_specific_checklist(self):
        result = generate_credit_event_checklist(
            "cds_specific", "DC referral on Company X"
        )
        assert any("DC" in q for q in result["checklist"]["questions"])

    def test_unknown_event_type_fallback(self):
        result = generate_credit_event_checklist(
            "unknown_type", "Something happened"
        )
        assert result["checklist"]["isda_reference"] == "TBD"
        assert len(result["checklist"]["questions"]) >= 4  # Base questions

    def test_checklist_contains_base_questions(self):
        result = generate_credit_event_checklist(
            "bankruptcy", "Company files Chapter 11"
        )
        questions = result["checklist"]["questions"]
        assert any("Reference Entity" in q for q in questions)

    def test_headline_preserved_in_result(self):
        headline = "Company files for Chapter 11"
        result = generate_credit_event_checklist("bankruptcy", headline)
        assert result["headline"] == headline

    def test_generated_at_is_iso_format(self):
        result = generate_credit_event_checklist(
            "bankruptcy", "Company files Chapter 11"
        )
        # Should not raise
        datetime.fromisoformat(result["generated_at"])


# ============================================================
# rapid_response_analysis
# ============================================================


class TestRapidResponseAnalysis:
    def test_critical_headline(self):
        result = rapid_response_analysis(
            "Ardagh Group files Chapter 15 for ARD Finance SA", "Ardagh"
        )
        assert result["isda_relevance"] in ("CRITICAL", "HIGH")
        assert "primary_event_type" in result
        assert "immediate_actions" in result

    def test_no_isda_keywords(self):
        result = rapid_response_analysis(
            "Company reports solid Q3 results", "TestCo"
        )
        assert result["isda_relevance"] == "LOW"
        assert result["analysis"] is None

    def test_returns_checklist(self):
        result = rapid_response_analysis(
            "Company files for bankruptcy", "TestCo"
        )
        assert "checklist" in result
        assert result["checklist"]["event_type"] == "bankruptcy"

    def test_returns_isda_section(self):
        result = rapid_response_analysis(
            "Company missed payment on bonds", "TestCo"
        )
        assert "isda_section" in result

    def test_human_review_required(self):
        result = rapid_response_analysis(
            "Company announces restructuring", "TestCo"
        )
        assert result["human_review_required"] is True

    def test_disclaimer_present(self):
        result = rapid_response_analysis(
            "Company files for bankruptcy", "TestCo"
        )
        assert "disclaimer" in result


# ============================================================
# analyze_news_for_isda (main interface)
# ============================================================


class TestAnalyzeNewsForISDA:
    def test_basic_analysis(self):
        headlines = [
            "Company files for bankruptcy",
            "Normal earnings report",
        ]
        result = analyze_news_for_isda(headlines)
        assert result["summary"]["total_headlines"] == 2
        assert result["summary"]["critical_flags"] >= 1

    def test_with_companies(self):
        headlines = ["Company files for bankruptcy"]
        companies = ["TestCo"]
        result = analyze_news_for_isda(headlines, companies)
        assert result["summary"]["total_headlines"] == 1

    def test_no_companies_defaults_to_none(self):
        result = analyze_news_for_isda(["Normal news"])
        assert result["summary"]["total_headlines"] == 1
        assert result["summary"]["critical_flags"] == 0

    def test_detailed_analysis_for_critical(self):
        headlines = ["Company files for bankruptcy"]
        result = analyze_news_for_isda(headlines, ["TestCo"])
        assert len(result["detailed_analysis"]) >= 1


# ============================================================
# GracePeriodTracker
# ============================================================


class TestGracePeriodTracker:
    def test_add_grace_period(self, tmp_path):
        storage = tmp_path / "grace_periods.json"
        tracker = GracePeriodTracker(str(storage))
        entry = tracker.add_grace_period(
            company="TestCo",
            payment_type="interest",
            missed_date="2025-01-15",
            grace_days=30,
            notes="Senior note coupon",
        )
        assert entry["company"] == "TestCo"
        assert entry["status"] == "RUNNING"
        assert entry["expiry_date"] == "2025-02-14"

    def test_persistence(self, tmp_path):
        storage = tmp_path / "grace_periods.json"
        tracker1 = GracePeriodTracker(str(storage))
        tracker1.add_grace_period("Co", "interest", "2025-01-01", 30)

        tracker2 = GracePeriodTracker(str(storage))
        assert len(tracker2.periods) == 1

    def test_get_expiring_soon(self, tmp_path):
        storage = tmp_path / "grace_periods.json"
        tracker = GracePeriodTracker(str(storage))

        # Expiring tomorrow
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tracker.add_grace_period("ExpiringSoon", "interest", yesterday, 2)

        # Expiring in 30 days
        tracker.add_grace_period("NotExpiring", "interest", datetime.now().strftime("%Y-%m-%d"), 60)

        expiring = tracker.get_expiring_soon(days=7)
        companies = [e["company"] for e in expiring]
        assert "ExpiringSoon" in companies

    def test_mark_cured(self, tmp_path):
        storage = tmp_path / "grace_periods.json"
        tracker = GracePeriodTracker(str(storage))
        tracker.add_grace_period("CuredCo", "interest", "2025-01-01", 30)
        tracker.mark_cured("CuredCo")
        assert tracker.periods[0]["status"] == "CURED"

    def test_mark_cured_case_insensitive(self, tmp_path):
        storage = tmp_path / "grace_periods.json"
        tracker = GracePeriodTracker(str(storage))
        tracker.add_grace_period("CuredCo", "interest", "2025-01-01", 30)
        tracker.mark_cured("curedco")
        assert tracker.periods[0]["status"] == "CURED"

    def test_mark_expired(self, tmp_path):
        storage = tmp_path / "grace_periods.json"
        tracker = GracePeriodTracker(str(storage))
        tracker.add_grace_period("ExpiredCo", "interest", "2025-01-01", 30)
        tracker.mark_expired("ExpiredCo")
        assert tracker.periods[0]["status"] == "EXPIRED_CREDIT_EVENT"

    def test_empty_storage_file(self, tmp_path):
        storage = tmp_path / "grace_periods.json"
        tracker = GracePeriodTracker(str(storage))
        assert tracker.periods == []


# ============================================================
# ISDA_KEYWORDS structure
# ============================================================


class TestISDAKeywords:
    def test_all_categories_have_terms(self):
        for category, data in ISDA_KEYWORDS.items():
            assert "terms" in data
            assert len(data["terms"]) > 0

    def test_all_categories_have_urgency(self):
        for category, data in ISDA_KEYWORDS.items():
            assert data["urgency"] in ("CRITICAL", "HIGH", "WATCH")

    def test_all_categories_have_isda_section(self):
        for category, data in ISDA_KEYWORDS.items():
            assert "isda_section" in data


# ============================================================
# ISDA_SECTIONS structure
# ============================================================


class TestISDASections:
    def test_bankruptcy_section_exists(self):
        assert "4.2" in ISDA_SECTIONS

    def test_failure_to_pay_section_exists(self):
        assert "4.5" in ISDA_SECTIONS

    def test_restructuring_section_exists(self):
        assert "4.7" in ISDA_SECTIONS

    def test_sections_have_titles(self):
        for section_id, data in ISDA_SECTIONS.items():
            assert "title" in data
            assert "summary" in data

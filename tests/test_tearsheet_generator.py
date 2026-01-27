"""
P4: Tests for the tear sheet generator (generators/tearsheet_generator.py).

Covers generate_tearsheet_html() and all internal formatting helpers.
This module has no Streamlit dependency — all functions are pure.
"""

import pytest
from generators.tearsheet_generator import (
    generate_tearsheet_html,
    _format_number,
    _format_ratio,
    _format_percent,
    _generate_debt_rows,
    _generate_credit_opinion_section,
)


# ============================================================
# _format_number
# ============================================================


class TestFormatNumber:
    def test_integer(self):
        assert _format_number(5000) == "5,000"

    def test_float(self):
        assert _format_number(5000.7) == "5,001"

    def test_none(self):
        assert _format_number(None) == "-"

    def test_string_number(self):
        assert _format_number("3500") == "3,500"

    def test_non_numeric_string(self):
        assert _format_number("N/A") == "N/A"

    def test_zero(self):
        assert _format_number(0) == "0"

    def test_negative(self):
        assert _format_number(-100) == "-100"


# ============================================================
# _format_ratio
# ============================================================


class TestFormatRatio:
    def test_normal_ratio(self):
        assert _format_ratio(5.5) == "5.5"

    def test_integer_ratio(self):
        assert _format_ratio(4) == "4.0"

    def test_none(self):
        assert _format_ratio(None) == "-"

    def test_string_number(self):
        assert _format_ratio("3.2") == "3.2"

    def test_non_numeric_string(self):
        assert _format_ratio("N/A") == "N/A"

    def test_zero(self):
        assert _format_ratio(0) == "0.0"


# ============================================================
# _format_percent
# ============================================================


class TestFormatPercent:
    def test_positive_fraction(self):
        assert _format_percent(0.15) == "15.0%"

    def test_negative_fraction(self):
        assert _format_percent(-0.05) == "-5.0%"

    def test_none(self):
        assert _format_percent(None) == "-"

    def test_zero(self):
        assert _format_percent(0) == "0.0%"

    def test_string_number(self):
        assert _format_percent("0.10") == "10.0%"

    def test_non_numeric_string(self):
        assert _format_percent("N/A") == "N/A"

    def test_one(self):
        assert _format_percent(1.0) == "100.0%"


# ============================================================
# _generate_debt_rows
# ============================================================


class TestGenerateDebtRows:
    def test_empty_list(self):
        result = _generate_debt_rows([])
        assert "No debt instruments available" in result

    def test_none_input(self):
        result = _generate_debt_rows(None)
        assert "No debt instruments available" in result

    def test_single_instrument(self):
        instruments = [
            {
                "instrument": "Senior Secured TLB",
                "amount": 3000,
                "maturity": "2028-06-15",
                "coupon": "E+400",
                "price": 98.5,
                "ytw": 6.2,
                "stw": 420,
            }
        ]
        result = _generate_debt_rows(instruments)
        assert "Senior Secured TLB" in result
        assert "3,000" in result
        assert "2028-06-15" in result

    def test_missing_fields(self):
        instruments = [{"instrument": "Bond"}]
        result = _generate_debt_rows(instruments)
        assert "Bond" in result
        assert "-" in result  # Missing fields should show "-"

    def test_multiple_instruments(self):
        instruments = [
            {"instrument": "TLB", "amount": 1000},
            {"instrument": "SSN", "amount": 2000},
        ]
        result = _generate_debt_rows(instruments)
        assert "TLB" in result
        assert "SSN" in result


# ============================================================
# _generate_credit_opinion_section
# ============================================================


class TestGenerateCreditOpinionSection:
    def test_empty_opinion(self):
        result = _generate_credit_opinion_section({})
        assert result == ""

    def test_none_opinion(self):
        result = _generate_credit_opinion_section(None)
        assert result == ""

    def test_opinion_without_summary(self):
        result = _generate_credit_opinion_section({"recommendation": "OVERWEIGHT"})
        assert result == ""

    def test_full_opinion(self):
        opinion = {
            "summary": "Solid credit fundamentals.",
            "recommendation": "OVERWEIGHT",
            "key_risks": ["High leverage", "Competition"],
            "key_catalysts": ["Deleveraging", "Margin expansion"],
        }
        result = _generate_credit_opinion_section(opinion)
        assert "Solid credit fundamentals" in result
        assert "OVERWEIGHT" in result
        assert "High leverage" in result
        assert "Deleveraging" in result

    def test_opinion_no_risks(self):
        opinion = {
            "summary": "Some summary.",
            "key_risks": [],
            "key_catalysts": ["Growth"],
        }
        result = _generate_credit_opinion_section(opinion)
        assert "Some summary" in result

    def test_opinion_no_catalysts(self):
        opinion = {
            "summary": "Some summary.",
            "key_risks": ["Risk A"],
            "key_catalysts": [],
        }
        result = _generate_credit_opinion_section(opinion)
        assert "Risk A" in result


# ============================================================
# generate_tearsheet_html — full output
# ============================================================


class TestGenerateTearsheetHTML:
    def test_returns_valid_html(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert html.strip().startswith("<!DOCTYPE html>") or html.strip().startswith("<")
        assert "</html>" in html

    def test_contains_company_name(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert "Acme Corp" in html

    def test_contains_sector(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert "TMT" in html

    def test_contains_ratings(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert "B2" in html  # Moody's rating
        assert "B+" in html  # Fitch rating

    def test_contains_key_metrics(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert "5,000" in html  # total_debt
        assert "5.5" in html    # debt_to_ebitda

    def test_contains_debt_instruments(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert "Senior Secured TLB" in html

    def test_contains_credit_opinion(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert "Adequate credit" in html

    def test_minimal_snapshot(self):
        data = {"company_name": "MinimalCo"}
        html = generate_tearsheet_html(data)
        assert "MinimalCo" in html
        assert "</html>" in html

    def test_empty_snapshot(self):
        html = generate_tearsheet_html({})
        assert "Unknown Company" in html
        assert "</html>" in html

    def test_contains_css_styling(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert "<style>" in html
        assert "tearsheet" in html

    def test_print_media_query(self, sample_snapshot):
        html = generate_tearsheet_html(sample_snapshot)
        assert "@media print" in html

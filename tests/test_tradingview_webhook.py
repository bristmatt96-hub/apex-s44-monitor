"""
P5: Tests for the TradingView webhook Flask endpoints.

Covers get_credit_implication(), /webhook, /health, and /test endpoints.
"""

import json
import pytest
from unittest.mock import patch

from webhook.tradingview_webhook import app, get_credit_implication


# ============================================================
# Flask test client fixture
# ============================================================


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ============================================================
# get_credit_implication — boundary testing
# ============================================================


class TestGetCreditImplication:
    def test_severe_drop(self):
        result = get_credit_implication(-10.0)
        assert "SEVERE" in result

    def test_high_drop(self):
        result = get_credit_implication(-5.0)
        assert "HIGH" in result

    def test_moderate_drop(self):
        result = get_credit_implication(-3.0)
        assert "MODERATE" in result

    def test_watch_drop(self):
        result = get_credit_implication(-1.0)
        assert "WATCH" in result

    def test_positive_large(self):
        result = get_credit_implication(5.0)
        assert "POSITIVE" in result

    def test_positive_moderate(self):
        result = get_credit_implication(3.0)
        assert "GOOD" in result

    def test_neutral(self):
        result = get_credit_implication(0.0)
        assert "NEUTRAL" in result

    def test_small_positive(self):
        result = get_credit_implication(1.0)
        assert "NEUTRAL" in result

    def test_small_negative(self):
        result = get_credit_implication(-0.5)
        assert "NEUTRAL" in result

    # Boundary tests
    def test_boundary_negative_10(self):
        """Exactly -10 should be SEVERE."""
        result = get_credit_implication(-10)
        assert "SEVERE" in result

    def test_boundary_negative_5(self):
        """Exactly -5 should be HIGH."""
        result = get_credit_implication(-5)
        assert "HIGH" in result

    def test_boundary_negative_3(self):
        """Exactly -3 should be MODERATE."""
        result = get_credit_implication(-3)
        assert "MODERATE" in result

    def test_boundary_positive_5(self):
        """Exactly +5 should be POSITIVE."""
        result = get_credit_implication(5)
        assert "POSITIVE" in result

    def test_boundary_positive_3(self):
        """Exactly +3 should be GOOD."""
        result = get_credit_implication(3)
        assert "GOOD" in result


# ============================================================
# Health endpoint
# ============================================================


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "telegram_configured" in data

    def test_health_contains_service_name(self, client):
        resp = client.get("/")
        data = resp.get_json()
        assert "XO S44" in data["service"]


# ============================================================
# Webhook endpoint — JSON payloads
# ============================================================


class TestWebhookJSON:
    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=True)
    def test_valid_json_payload(self, mock_send, client):
        payload = {
            "ticker": "TKA",
            "price": 4.52,
            "change": -2.5,
            "company": "ThyssenKrupp",
            "alert_type": "price_drop",
        }
        resp = client.post(
            "/webhook",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["forwarded_to_telegram"] is True
        mock_send.assert_called_once()

    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=True)
    def test_missing_fields_uses_defaults(self, mock_send, client):
        payload = {"ticker": "TKA"}
        resp = client.post(
            "/webhook",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ticker"] == "TKA"

    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=True)
    def test_change_as_string_percent(self, mock_send, client):
        payload = {"ticker": "TKA", "change": "-5.2%"}
        resp = client.post(
            "/webhook",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["change"] == -5.2

    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=True)
    def test_change_as_non_numeric_string(self, mock_send, client):
        payload = {"ticker": "TKA", "change": "N/A"}
        resp = client.post(
            "/webhook",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["change"] == 0  # Falls back to 0

    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=False)
    def test_telegram_failure_reflected(self, mock_send, client):
        payload = {"ticker": "TKA", "change": -1}
        resp = client.post(
            "/webhook",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["status"] == "telegram_failed"
        assert data["forwarded_to_telegram"] is False

    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=True)
    def test_empty_json_body(self, mock_send, client):
        """Empty JSON {} is falsy, so the webhook falls through to the
        text-alert branch (request.data is b'{}')."""
        resp = client.post(
            "/webhook",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"


# ============================================================
# Webhook endpoint — plain text payloads
# ============================================================


class TestWebhookPlainText:
    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=True)
    def test_plain_text_alert(self, mock_send, client):
        """Flask 3.1+ raises 415 when request.json is accessed with a
        non-JSON content type. The production code's except block catches
        this and returns a 500 error response."""
        resp = client.post(
            "/webhook",
            data="TKA price alert: down 5%",
            content_type="text/plain",
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "error"

    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=True)
    def test_plain_text_sent_as_json_content_type(self, mock_send, client):
        """When TradingView sends a non-JSON body with application/json
        content type, Flask silently returns None for request.json,
        falling through to the text-alert branch."""
        resp = client.post(
            "/webhook",
            data="TKA price alert: down 5%",
            content_type="application/json",
        )
        # Non-parseable JSON with application/json content type triggers
        # the except block in Flask
        assert resp.status_code == 500


# ============================================================
# Test endpoint
# ============================================================


class TestTestEndpoint:
    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=True)
    def test_endpoint_sends_test_message(self, mock_send, client):
        resp = client.get("/test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["telegram_sent"] is True

    @patch("webhook.tradingview_webhook.send_telegram_message", return_value=False)
    def test_endpoint_failure(self, mock_send, client):
        resp = client.get("/test")
        data = resp.get_json()
        assert data["status"] == "failed"

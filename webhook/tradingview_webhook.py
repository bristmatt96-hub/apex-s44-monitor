"""
TradingView Webhook Receiver → Telegram Alerts
Deploy this on Vercel, Railway, or Render (all have free tiers)

Receives TradingView alerts and forwards to your Telegram bot
"""

from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime

app = Flask(__name__)

# Get these from environment variables (set in your deployment platform)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Credit implications based on price move
def get_credit_implication(change_pct: float) -> str:
    if change_pct <= -10:
        return "🔴 SEVERE: Expect significant spread widening (20-50bps+)"
    elif change_pct <= -5:
        return "🔴 HIGH: Expect spread widening (10-20bps)"
    elif change_pct <= -3:
        return "🟠 MODERATE: Monitor for spread pressure"
    elif change_pct <= -1:
        return "🟡 WATCH: Minor move, stay alert"
    elif change_pct >= 5:
        return "🟢 POSITIVE: Potential spread tightening"
    elif change_pct >= 3:
        return "🟢 GOOD: Supportive for credit"
    else:
        return "⚪ NEUTRAL: Limited credit impact"


def send_telegram_message(message: str) -> bool:
    """Send message to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.ok
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


@app.route("/", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "service": "Apex Credit Monitor - TradingView Webhook",
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    })


@app.route("/webhook", methods=["POST"])
def tradingview_webhook():
    """
    Receive TradingView webhook and forward to Telegram

    Expected payload from TradingView:
    {
        "ticker": "TKA",
        "price": 4.52,
        "change": -2.5,
        "company": "ThyssenKrupp",
        "alert_type": "price_drop"
    }
    """
    try:
        # Parse incoming data
        data = request.json or {}

        # Handle plain text alerts (TradingView sometimes sends just text)
        if not data and request.data:
            text_alert = request.data.decode('utf-8')
            message = f"📊 *TradingView Alert*\n\n{text_alert}\n\n_{datetime.now().strftime('%H:%M:%S')}_"
            send_telegram_message(message)
            return jsonify({"status": "ok", "message": "Text alert forwarded"})

        # Extract fields
        ticker = data.get("ticker", "Unknown")
        price = data.get("price", data.get("close", "N/A"))
        change = data.get("change", data.get("change_pct", 0))
        company = data.get("company", ticker)
        alert_type = data.get("alert_type", "price_alert")

        # Convert change to float if string
        try:
            change = float(str(change).replace("%", ""))
        except:
            change = 0

        # Get credit implication
        implication = get_credit_implication(change)

        # Format direction
        direction = "📉" if change < 0 else "📈"
        change_str = f"{change:+.2f}%" if change else "N/A"

        # Build message
        message = f"""
{direction} *PRICE ALERT: {company}*

*Ticker:* {ticker}
*Price:* {price}
*Change:* {change_str}

*Credit Implication:*
{implication}

_TradingView Alert • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_
"""

        # Send to Telegram
        success = send_telegram_message(message.strip())

        return jsonify({
            "status": "ok" if success else "telegram_failed",
            "ticker": ticker,
            "change": change,
            "forwarded_to_telegram": success
        })

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/test", methods=["GET"])
def test_telegram():
    """Test endpoint to verify Telegram is working"""
    message = "🧪 *Test Alert*\n\nYour TradingView → Telegram webhook is working!\n\n_Apex Credit Monitor_"
    success = send_telegram_message(message)

    return jsonify({
        "status": "ok" if success else "failed",
        "telegram_sent": success
    })


# For local testing
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

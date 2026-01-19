import streamlit as st
import tweepy
from threading import Thread
import time
import requests
import os

# Load secrets from Streamlit Cloud or environment variables (for local dev)
TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))
TWITTER_BEARER_TOKEN = st.secrets.get("TWITTER_BEARER_TOKEN", os.environ.get("TWITTER_BEARER_TOKEN", ""))

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            print(f"[Telegram Error] {resp.status_code}: {resp.text}")
        return resp.ok
    except Exception as e:
        print(f"[Telegram Exception] {e}")
        return False

def test_telegram():
    """Manual test - call this to verify Telegram is working"""
    print("Sending test message to Telegram...")
    success = send_telegram_message("🔔 *Apex Monitor Test*\nIf you see this, Telegram alerts are working!")
    if success:
        print("✓ Test message sent successfully!")
    else:
        print("✗ Failed to send test message - check bot token and chat ID")
    return success

# Twitter/X API Bearer Token loaded from secrets above

S44_AUTOS = [
    'Renault',
    'Valeo',
    'Forvia',
    'Jaguar Land Rover Automotive PLC',
    'Volvo Car AB',
    'Schaeffler AG'
]

S44_TELECOMS = [
    'Telecom Italia Spa',
    'Virgin Media Finance PLC',
    'Iliad Holding',
    'Nokia Oyj',
    'Eutelsat S.A.',
    'Matterhorn Telecom S.A.',
    'Sunrise HoldCo IV B.V.',
    'Ziggo Bond Company B.V.',
    'United Group B.V.',
    'Kaixo Bondco Telecom S.A.U.',
    'FiberCop S.p.A.',
    'SES',
    'Telefonaktiebolaget L M Ericsson'
]

class NewsHound:
    def __init__(self):
        self.client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
        self.alerts = {}
        print("=== Apex Credit Monitor Started (Bearer Token mode) ===")
        print("Pro tip: Set a $50/month spend cap in X Portal > Billing")
        print("Queries optimised: lang:en, since:2026-01-01, min_faves:1, no noise")

    def scour(self, name, is_telecom=False):
        query = (
            f'"{name}" (CDS OR downgrade OR leverage OR restructuring OR tariff OR EV OR supply OR debt OR earnings) '
            f'lang:en since:2026-01-01 min_faves:1 -filter:replies -is:retweet'
        )
        if is_telecom:
            query = (
                f'("{name}" OR "Telecom Italia" OR TI) (antitrust OR KKR OR accordo OR chiusura OR deleveraging OR debito OR ristrutturazione OR clearance OR review) '
                f'since:2026-01-01 min_faves:0 -filter:replies -is:retweet'
            )
        try:
            tweets = self.client.search_recent_tweets(
                query=query,
                max_results=5,
                tweet_fields=['created_at', 'public_metrics', 'lang']
            )
            new_alerts = []
            if tweets.data:
                for tweet in tweets.data:
                    impact = self.spot_pattern(name, tweet.text, tweet.lang)
                    likes = tweet.public_metrics.get('like_count', 0)
                    lang_note = f" ({tweet.lang.upper()})" if tweet.lang != 'en' else ""
                    new_alerts.append(
                        f"X Hit ({tweet.created_at.date()} | {likes} likes{lang_note}): "
                        f"{tweet.text[:140]}... – {impact}"
                    )
                    if "antitrust" in tweet.text.lower() or "kkr" in tweet.text.lower() or "clearance" in tweet.text.lower():
                        alert_text = f"**HIGH PRIORITY ALERT**\n{name}: {tweet.text[:200]}...\nImpact: {impact}\nLink: https://x.com/status/{tweet.id}"
                        send_telegram_message(alert_text)
            else:
                new_alerts.append("Quiet on X / Italian sources (Il Sole 24 Ore etc.)")
            self.alerts[name] = new_alerts
        except Exception as e:
            self.alerts[name] = [f"API error: {str(e)} (check token / $50 balance)"]

    def spot_pattern(self, name, text, lang='en'):
        txt = text.lower()
        if lang != 'en' or 'antitrust' in txt or 'kkr' in txt or 'chiusura' in txt:
            if 'antitrust' in txt or 'kkr' in txt or 'accordo' in txt or 'chiusura' in txt:
                return "Italian antitrust clearance signal – e.g., KKR deal for Telecom Italia; potential close Q1 2026, CDS tighten 15-20bps; RV long Telecom Italia / short Virgin Media (UK lag)"
        if any(w in txt for w in ['ev', 'tariff', 'supply', 'china', 'hybrid']):
            return f"EV/tariff/supply risk → potential widen vs peers. RV idea: short {name} CDS / long Volvo Car AB"
        if any(w in txt for w in ['debt', 'leverage', 'restructuring', 'deleveraging']):
            return "Leverage/debt signal – monitor for 10-20 bps CDS move; check correlations to peers like Telecom Italia"
        if 'reg' in txt or 'antitrust' in txt or 'ofcom' in txt:
            return "Reg risk – e.g., EU/Ofcom fiber deal delay; ripple to Virgin Media leverage; RV short Virgin Media / long Telecom Italia"
        return "Watch item – volume building"

    def constant_scour(self):
        while True:
            for name in S44_AUTOS:
                self.scour(name)
            for name in S44_TELECOMS:
                self.scour(name, is_telecom=True)
            time.sleep(600)  # 10 minutes

# Dashboard
st.title("Apex Credit Monitor – iTraxx XO S44")
hound = NewsHound()
Thread(target=hound.constant_scour, daemon=True).start()

sector = st.selectbox("Select Sector", ["Autos", "Telecoms"])

if sector == "Autos":
    names = S44_AUTOS
elif sector == "Telecoms":
    names = S44_TELECOMS

selected = st.selectbox("Select Name", names)
st.subheader(f"Latest on {selected}")
alerts = hound.alerts.get(selected, ["Scanning..."])
for alert in alerts[-3:]:
    st.info(alert)
import streamlit as st
import tweepy
from threading import Thread
import time
import requests
import os
import json
from pathlib import Path

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
    success = send_telegram_message("*Apex Monitor Test*\nIf you see this, Telegram alerts are working!")
    if success:
        print("Test message sent successfully!")
    else:
        print("Failed to send test message - check bot token and chat ID")
    return success

def load_index(index_file):
    """Load index constituents from JSON config file"""
    indices_dir = Path(__file__).parent / "indices"
    with open(indices_dir / index_file, "r", encoding="utf-8") as f:
        return json.load(f)

def get_available_indices():
    """Get list of available index config files"""
    indices_dir = Path(__file__).parent / "indices"
    if not indices_dir.exists():
        return []
    return [f.stem for f in indices_dir.glob("*.json")]

def get_search_terms(name, aliases):
    """Get search terms for a company including aliases"""
    terms = [name]
    if name in aliases:
        terms.extend(aliases[name])
    return terms

# Credit-relevant keywords by category
CREDIT_KEYWORDS = {
    "spread_moving": ["CDS", "downgrade", "upgrade", "outlook", "rating", "leverage", "debt", "default"],
    "corporate_events": ["restructuring", "refinancing", "M&A", "acquisition", "merger", "takeover", "buyout"],
    "regulatory": ["antitrust", "regulatory", "clearance", "approval", "investigation"],
    "earnings": ["earnings", "EBITDA", "revenue", "profit", "loss", "guidance"],
    "sector_specific": ["tariff", "EV", "supply chain", "strike", "bankruptcy"]
}

class NewsHound:
    def __init__(self, index_data):
        self.client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
        self.alerts = {}
        self.index_data = index_data
        self.aliases = index_data.get("search_aliases", {})
        print(f"=== Apex Credit Monitor Started ===")
        print(f"Monitoring: {index_data['name']} ({index_data['total_names']} names)")

    def scour(self, name, sector):
        """Search for credit-relevant news on X/Twitter"""
        search_terms = get_search_terms(name, self.aliases)
        # Use the first/primary term for the query
        primary_term = search_terms[0]
        short_name = search_terms[1] if len(search_terms) > 1 else primary_term.split()[0]

        # Build query with credit-relevant keywords
        keywords = " OR ".join(CREDIT_KEYWORDS["spread_moving"][:4] + CREDIT_KEYWORDS["corporate_events"][:3])
        query = (
            f'("{short_name}" OR "{primary_term}") ({keywords}) '
            f'lang:en -filter:replies -is:retweet'
        )

        # Truncate query if too long (Twitter limit is 512 chars)
        if len(query) > 500:
            query = f'"{short_name}" (CDS OR debt OR rating OR restructuring) lang:en -filter:replies -is:retweet'

        try:
            tweets = self.client.search_recent_tweets(
                query=query,
                max_results=10,
                tweet_fields=['created_at', 'public_metrics', 'lang']
            )
            new_alerts = []
            if tweets.data:
                for tweet in tweets.data:
                    impact = self.spot_pattern(name, tweet.text, sector)
                    likes = tweet.public_metrics.get('like_count', 0)
                    new_alerts.append(
                        f"X ({tweet.created_at.date()} | {likes} likes): "
                        f"{tweet.text[:140]}... | {impact}"
                    )
                    # High-priority alert triggers
                    txt_lower = tweet.text.lower()
                    if any(kw in txt_lower for kw in ["downgrade", "default", "restructuring", "antitrust", "takeover"]):
                        alert_text = (
                            f"*HIGH PRIORITY ALERT*\n"
                            f"*{name}* ({sector})\n"
                            f"{tweet.text[:200]}...\n"
                            f"Impact: {impact}\n"
                            f"Link: https://x.com/i/status/{tweet.id}"
                        )
                        send_telegram_message(alert_text)
            else:
                new_alerts.append("No recent X activity matching credit keywords")
            self.alerts[name] = new_alerts
        except Exception as e:
            self.alerts[name] = [f"API error: {str(e)}"]

    def spot_pattern(self, name, text, sector):
        """Analyze tweet for credit impact"""
        txt = text.lower()

        # Rating/spread signals
        if any(w in txt for w in ['downgrade', 'negative outlook', 'rating cut']):
            return "NEGATIVE: Rating pressure - expect CDS widening 10-30bps"
        if any(w in txt for w in ['upgrade', 'positive outlook', 'rating raise']):
            return "POSITIVE: Rating improvement - expect CDS tightening"

        # Corporate events
        if any(w in txt for w in ['restructuring', 'bankruptcy', 'default']):
            return "HIGH RISK: Restructuring signal - significant spread impact likely"
        if any(w in txt for w in ['acquisition', 'takeover', 'buyout', 'm&a']):
            return "EVENT: M&A activity - monitor for leverage impact"
        if any(w in txt for w in ['refinancing', 'bond issue', 'new debt']):
            return "NEUTRAL: Refinancing activity - monitor terms"

        # Regulatory
        if any(w in txt for w in ['antitrust', 'regulatory', 'investigation']):
            return "RISK: Regulatory scrutiny - potential headline risk"

        # Sector-specific (Autos & Industrials)
        if sector == "Autos & Industrials":
            if any(w in txt for w in ['tariff', 'ev', 'supply chain', 'chip shortage']):
                return f"SECTOR: Auto/Industrial headwind - compare to sector peers"

        # TMT specific
        if sector == "TMT":
            if any(w in txt for w in ['spectrum', 'fiber', '5g', 'subscriber']):
                return "SECTOR: TMT operational signal"

        return "MONITOR: Potential credit signal - requires analysis"

    def constant_scour(self):
        """Background thread for continuous monitoring"""
        while True:
            for sector, names in self.index_data["sectors"].items():
                for name in names:
                    self.scour(name, sector)
                    time.sleep(2)  # Rate limiting between API calls
            time.sleep(600)  # 10 minutes between full scans

# ============== STREAMLIT DASHBOARD ==============

st.set_page_config(page_title="Apex Credit Monitor", layout="wide")
st.title("Apex Credit Monitor")

# Get available indices
available_indices = get_available_indices()

if not available_indices:
    st.error("No index configuration files found in /indices folder")
    st.stop()

# Index selector
selected_index = st.sidebar.selectbox(
    "Select Index",
    available_indices,
    format_func=lambda x: x.replace("_", " ").upper()
)

# Load selected index
index_data = load_index(f"{selected_index}.json")
st.sidebar.markdown(f"**{index_data['name']}**")
st.sidebar.markdown(f"Names: {index_data['total_names']}")

# Initialize NewsHound with selected index
@st.cache_resource
def get_hound(index_name):
    index_data = load_index(f"{index_name}.json")
    hound = NewsHound(index_data)
    Thread(target=hound.constant_scour, daemon=True).start()
    return hound

hound = get_hound(selected_index)

# Sector selector
sectors = list(index_data["sectors"].keys())
selected_sector = st.selectbox("Select Sector", sectors)

# Company selector
companies = index_data["sectors"][selected_sector]
selected_company = st.selectbox("Select Company", companies)

# Display alerts
st.subheader(f"{selected_company}")
st.caption(f"Sector: {selected_sector}")

alerts = hound.alerts.get(selected_company, ["Scanning... (may take a few minutes on first load)"])
for alert in alerts[-5:]:
    if "HIGH PRIORITY" in alert or "NEGATIVE" in alert or "HIGH RISK" in alert:
        st.error(alert)
    elif "POSITIVE" in alert:
        st.success(alert)
    else:
        st.info(alert)

# Sidebar stats
st.sidebar.markdown("---")
st.sidebar.markdown("### Sector Breakdown")
for sector, names in index_data["sectors"].items():
    st.sidebar.markdown(f"- {sector}: {len(names)} names")

"""
XO S44 Morning Brief Generator
Sends daily Telegram summary at 7am UK time
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
import requests
import threading
import time
import feedparser

# Telegram config - loaded from environment or secrets
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Try to load from Streamlit secrets
try:
    import streamlit as st
    TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
except Exception:
    pass

# Paths
SNAPSHOTS_DIR = Path(__file__).parent.parent / "snapshots"

# RSS feeds for credit news
RSS_FEEDS = [
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("FT Markets", "https://www.ft.com/markets?format=rss"),
]


def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    """Send message via Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Morning Brief] Telegram not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        return resp.ok
    except Exception as e:
        print(f"[Morning Brief] Telegram error: {e}")
        return False


def load_all_snapshots() -> list:
    """Load all snapshot JSON files"""
    snapshots = []
    if not SNAPSHOTS_DIR.exists():
        return snapshots

    for f in SNAPSHOTS_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                data["_filename"] = f.name
                snapshots.append(data)
        except Exception as e:
            print(f"[Morning Brief] Error loading {f}: {e}")

    return snapshots


def get_distressed_names(snapshots: list) -> list:
    """Find names flagged as distressed or underweight"""
    distressed = []

    for snap in snapshots:
        name = snap.get("company_name", "Unknown")
        sector = snap.get("sector", "")
        recommendation = snap.get("credit_opinion", {}).get("recommendation", "")

        # Check if distressed
        is_distressed = (
            "DISTRESSED" in sector.upper() or
            "DISTRESSED" in recommendation.upper() or
            "UNDERWEIGHT" in recommendation.upper()
        )

        if is_distressed:
            distressed.append({
                "name": name,
                "sector": sector,
                "recommendation": recommendation,
                "ratings": snap.get("ratings", {})
            })

    return distressed


def get_near_term_maturities(snapshots: list, days: int = 180) -> list:
    """Find bonds/loans maturing within X days"""
    maturities = []
    today = datetime.now()
    cutoff = today + timedelta(days=days)

    for snap in snapshots:
        name = snap.get("company_name", "Unknown")
        debt = snap.get("debt_capitalization", [])

        for instrument in debt:
            maturity_str = instrument.get("maturity", "")
            amount = instrument.get("amount", 0)

            if not maturity_str or not amount:
                continue

            # Try to parse maturity date
            maturity_date = None
            for fmt in ["%b %Y", "%B %Y", "%Y", "%d %b %Y", "%Y-%m-%d"]:
                try:
                    maturity_date = datetime.strptime(maturity_str, fmt)
                    break
                except Exception:
                    continue

            # Handle year-only (e.g., "2026")
            if maturity_date is None and maturity_str.isdigit() and len(maturity_str) == 4:
                maturity_date = datetime(int(maturity_str), 12, 31)

            if maturity_date and maturity_date <= cutoff:
                maturities.append({
                    "company": name,
                    "instrument": instrument.get("instrument", "Unknown"),
                    "amount": amount,
                    "maturity": maturity_str,
                    "maturity_date": maturity_date
                })

    # Sort by maturity date
    maturities.sort(key=lambda x: x["maturity_date"])
    return maturities


def get_watchlist_names(snapshots: list) -> list:
    """Get names with concerning metrics"""
    watchlist = []

    for snap in snapshots:
        name = snap.get("company_name", "Unknown")
        ratios = snap.get("key_ratios", {})
        ratings = snap.get("ratings", {})

        # Check for concerning metrics
        leverage = ratios.get("net_debt_to_ebitda") or ratios.get("debt_to_ebitda")

        concerns = []

        # High leverage
        if leverage and leverage > 6:
            concerns.append(f"Leverage: {leverage:.1f}x")

        # Low ratings
        moodys = ratings.get("moodys", {}).get("rating", "")
        sp = ratings.get("sp", {}).get("rating", "")

        if any(r in moodys for r in ["Caa", "Ca", "C"]):
            concerns.append(f"Moody's: {moodys}")
        if any(r in sp for r in ["CCC", "CC", "C", "D"]):
            concerns.append(f"S&P: {sp}")

        # Negative outlook
        if ratings.get("moodys", {}).get("outlook", "").lower() == "negative":
            concerns.append("Moody's outlook: Negative")
        if ratings.get("sp", {}).get("outlook", "").lower() == "negative":
            concerns.append("S&P outlook: Negative")

        if concerns:
            watchlist.append({
                "name": name,
                "concerns": concerns
            })

    return watchlist


def fetch_credit_news() -> list:
    """Fetch recent news from RSS feeds"""
    news = []
    keywords = ["credit", "bond", "debt", "rating", "downgrade", "upgrade",
                "default", "restructur", "high yield", "junk", "leverage"]

    # XO S44 company names to watch
    company_keywords = ["worldline", "ses ", "telefonica", "vodafone", "orange",
                       "casino", "altice", "tui ", "lufthansa", "renault",
                       "ford", "jaguar", "telecom", "iliad", "masmovil"]

    for feed_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "").lower()
                summary = entry.get("summary", "").lower()
                content = title + " " + summary

                # Check if relevant
                is_relevant = (
                    any(kw in content for kw in keywords) or
                    any(co in content for co in company_keywords)
                )

                if is_relevant:
                    news.append({
                        "source": feed_name,
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "date": entry.get("published", "")
                    })
        except Exception as e:
            print(f"[Morning Brief] RSS error {feed_name}: {e}")

    return news[:10]  # Top 10


def generate_morning_brief() -> str:
    """Generate the full morning brief message"""

    snapshots = load_all_snapshots()

    # Get data
    distressed = get_distressed_names(snapshots)
    maturities_90d = get_near_term_maturities(snapshots, days=90)
    maturities_180d = get_near_term_maturities(snapshots, days=180)
    watchlist = get_watchlist_names(snapshots)
    news = fetch_credit_news()

    # Build message
    now = datetime.now()
    date_str = now.strftime("%d %b %Y")

    msg = f"☀️ <b>XO S44 Morning Brief</b>\n"
    msg += f"📅 {date_str}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"

    # Distressed names
    if distressed:
        msg += "🚨 <b>DISTRESSED / UNDERWEIGHT</b>\n"
        for d in distressed[:5]:
            msg += f"• {d['name']}\n"
        msg += "\n"

    # Near-term maturities
    if maturities_90d:
        msg += "⏰ <b>MATURITIES &lt;90 DAYS</b>\n"
        for m in maturities_90d[:5]:
            msg += f"• {m['company']}: ${m['amount']}m ({m['maturity']})\n"
        msg += "\n"
    elif maturities_180d:
        msg += "📆 <b>MATURITIES &lt;6 MONTHS</b>\n"
        for m in maturities_180d[:5]:
            msg += f"• {m['company']}: ${m['amount']}m ({m['maturity']})\n"
        msg += "\n"

    # Watchlist
    if watchlist:
        msg += "⚠️ <b>WATCHLIST</b>\n"
        for w in watchlist[:5]:
            concerns_str = ", ".join(w["concerns"][:2])
            msg += f"• {w['name']}: {concerns_str}\n"
        msg += "\n"

    # News
    if news:
        msg += "📰 <b>CREDIT NEWS</b>\n"
        for n in news[:5]:
            msg += f"• {n['title'][:60]}...\n"
        msg += "\n"

    # Summary stats
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 Snapshots: {len(snapshots)} | "
    msg += f"Distressed: {len(distressed)} | "
    msg += f"Mat &lt;6m: {len(maturities_180d)}\n"

    return msg


def send_morning_brief() -> bool:
    """Generate and send the morning brief"""
    print(f"[Morning Brief] Generating brief at {datetime.now()}")

    try:
        brief = generate_morning_brief()
        success = send_telegram(brief)

        if success:
            print("[Morning Brief] Sent successfully")
        else:
            print("[Morning Brief] Failed to send")

        return success
    except Exception as e:
        print(f"[Morning Brief] Error: {e}")
        return False


def schedule_daily_brief(hour: int = 7, minute: int = 0):
    """
    Run scheduler that sends brief at specified UK time daily.
    Call this in a background thread.
    """
    import pytz
    uk_tz = pytz.timezone("Europe/London")

    while True:
        now_uk = datetime.now(uk_tz)
        target = now_uk.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If we've passed today's target, schedule for tomorrow
        if now_uk >= target:
            target += timedelta(days=1)

        wait_seconds = (target - now_uk).total_seconds()
        print(f"[Morning Brief] Next brief at {target}, waiting {wait_seconds/3600:.1f} hours")

        time.sleep(wait_seconds)
        send_morning_brief()

        # Wait a minute to avoid double-sending
        time.sleep(60)


def start_scheduler():
    """Start the morning brief scheduler in a background thread"""
    thread = threading.Thread(target=schedule_daily_brief, daemon=True)
    thread.start()
    print("[Morning Brief] Scheduler started for 7am UK daily")
    return thread


# CLI testing
if __name__ == "__main__":
    print("Testing Morning Brief Generator...")
    brief = generate_morning_brief()
    print(brief)
    print("\n--- Sending to Telegram ---")
    send_morning_brief()

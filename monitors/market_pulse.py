"""
Market Pulse - Real-time Bond-Moving News Monitor
Scans RSS feeds and scores headlines for potential price impact
Sends Telegram alerts for high-impact news
"""

import streamlit as st
import os
import json
import requests
import feedparser
import time
from threading import Thread
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set
import hashlib

# Import multi-agent utilities
try:
    from utils.agent_utils import (
        safe_json_read, safe_json_write, safe_json_update,
        thread_monitor, setup_logger, retry_with_backoff, ThreadSafeSet
    )
    UTILS_AVAILABLE = True
    pulse_logger = setup_logger("market_pulse", "market_pulse.log")
except ImportError:
    UTILS_AVAILABLE = False
    pulse_logger = None

# Helper function to safely get secrets
def get_secret(key, default=""):
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except Exception:
        return os.environ.get(key, default)

# Load secrets
TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = get_secret("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY = get_secret("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY", "")

# Try to import LLM libraries
OPENAI_AVAILABLE = False
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    pass

ANTHROPIC_AVAILABLE = False
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    pass

# Paths
CONFIG_DIR = Path(__file__).parent.parent / "config"
DATA_DIR = Path(__file__).parent.parent / "data"
SEEN_HEADLINES_FILE = DATA_DIR / "seen_headlines.json"
ALERTS_LOG_FILE = DATA_DIR / "market_pulse_alerts.json"

# ============== WATCHLIST ==============

def load_watchlist() -> List[str]:
    """Load company watchlist from XO S44 index"""
    indices_dir = Path(__file__).parent.parent / "indices"
    watchlist = []

    # Try to load XO S44 index
    xo_file = indices_dir / "xover_s44.json"
    if xo_file.exists():
        try:
            with open(xo_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for sector, names in data.get("sectors", {}).items():
                    watchlist.extend(names)
                # Also add aliases
                aliases = data.get("search_aliases", {})
                for name, alias_list in aliases.items():
                    watchlist.extend(alias_list)
        except:
            pass

    return list(set(watchlist))

def load_news_sources() -> Dict:
    """Load RSS feed configurations"""
    config_path = CONFIG_DIR / "news_sources.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"rss_feeds": {}}

# ============== HEADLINE TRACKING ==============

def load_seen_headlines() -> Set[str]:
    """Load set of already-seen headline hashes (thread-safe)"""
    if UTILS_AVAILABLE:
        data = safe_json_read(SEEN_HEADLINES_FILE, default={"seen": []})
        return set(data.get("seen", []))
    else:
        # Fallback to original implementation
        if SEEN_HEADLINES_FILE.exists():
            try:
                with open(SEEN_HEADLINES_FILE, "r") as f:
                    data = json.load(f)
                    return set(data.get("seen", []))
            except:
                pass
        return set()

def save_seen_headlines(seen: Set[str]):
    """Save seen headline hashes with file locking (keep last 5000)"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    recent = list(seen)[-5000:]
    data = {"seen": recent, "updated": datetime.now().isoformat()}

    if UTILS_AVAILABLE:
        if not safe_json_write(SEEN_HEADLINES_FILE, data):
            if pulse_logger:
                pulse_logger.error("Failed to save seen headlines")
    else:
        # Fallback to original implementation
        with open(SEEN_HEADLINES_FILE, "w") as f:
            json.dump(data, f)

def hash_headline(title: str, source: str) -> str:
    """Create unique hash for a headline"""
    return hashlib.md5(f"{title}:{source}".encode()).hexdigest()

# ============== ALERTS LOG ==============

def load_alerts_log() -> List[Dict]:
    """Load recent alerts (thread-safe)"""
    if UTILS_AVAILABLE:
        return safe_json_read(ALERTS_LOG_FILE, default=[])
    else:
        # Fallback to original implementation
        if ALERTS_LOG_FILE.exists():
            try:
                with open(ALERTS_LOG_FILE, "r") as f:
                    return json.load(f)
            except:
                pass
        return []

def save_alert(alert: Dict):
    """Save an alert to the log (thread-safe with file locking)"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if UTILS_AVAILABLE:
        def update_alerts(alerts):
            if not isinstance(alerts, list):
                alerts = []
            alerts.append(alert)
            return alerts[-200:]  # Keep last 200 alerts

        if not safe_json_update(ALERTS_LOG_FILE, update_alerts, default=[]):
            if pulse_logger:
                pulse_logger.error("Failed to save alert")
    else:
        # Fallback to original implementation
        alerts = load_alerts_log()
        alerts.append(alert)
        alerts = alerts[-200:]
        with open(ALERTS_LOG_FILE, "w") as f:
            json.dump(alerts, f, indent=2)

# ============== TELEGRAM ==============

def send_telegram_alert(message: str) -> bool:
    """Send alert to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.ok
    except:
        return False

# ============== LLM SCORING ==============

SCORING_PROMPT = """You are a EUR High Yield credit analyst. Score this headline for potential bond price impact.

Headline: {headline}
Source: {source}
Company mentioned: {company}

Score from 1-5:
1 = No impact (routine news, no price move expected)
2 = Minor (might move bonds 0.25-0.5 pts)
3 = Moderate (could move bonds 0.5-1 pt)
4 = Significant (likely to move bonds 1-2 pts)
5 = Major (could move bonds 2+ pts, restructuring/M&A/default risk)

Also indicate direction: UP, DOWN, or UNCERTAIN

Consider:
- Earnings surprises (beat/miss)
- M&A rumours or announcements
- Management changes
- Refinancing news
- Asset sales/disposals
- Covenant amendments
- Rating actions
- Restructuring signals
- Litigation/regulatory issues

Respond ONLY in this exact format:
SCORE: [1-5]
DIRECTION: [UP/DOWN/UNCERTAIN]
REASON: [One sentence explanation]"""

def score_headline_openai(headline: str, source: str, company: str) -> Optional[Dict]:
    """Score headline using OpenAI"""
    if not OPENAI_AVAILABLE or not OPENAI_API_KEY:
        return None

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Fast and cheap
            messages=[
                {"role": "user", "content": SCORING_PROMPT.format(
                    headline=headline, source=source, company=company
                )}
            ],
            temperature=0.1,
            max_tokens=100
        )

        text = response.choices[0].message.content
        return parse_score_response(text)
    except Exception as e:
        return None

def score_headline_anthropic(headline: str, source: str, company: str) -> Optional[Dict]:
    """Score headline using Anthropic"""
    if not ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
        return None

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-3-haiku-20240307",  # Fast and cheap
            max_tokens=100,
            messages=[
                {"role": "user", "content": SCORING_PROMPT.format(
                    headline=headline, source=source, company=company
                )}
            ]
        )

        text = response.content[0].text
        return parse_score_response(text)
    except Exception as e:
        return None

def parse_score_response(text: str) -> Optional[Dict]:
    """Parse LLM response into structured data"""
    try:
        lines = text.strip().split("\n")
        result = {}

        for line in lines:
            if line.startswith("SCORE:"):
                result["score"] = int(line.split(":")[1].strip())
            elif line.startswith("DIRECTION:"):
                result["direction"] = line.split(":")[1].strip()
            elif line.startswith("REASON:"):
                result["reason"] = line.split(":", 1)[1].strip()

        if "score" in result and "direction" in result:
            return result
    except:
        pass
    return None

def score_headline(headline: str, source: str, company: str) -> Optional[Dict]:
    """Score headline using available LLM"""
    # Try Anthropic first (cheaper), then OpenAI
    result = score_headline_anthropic(headline, source, company)
    if result:
        result["provider"] = "anthropic"
        return result

    result = score_headline_openai(headline, source, company)
    if result:
        result["provider"] = "openai"
        return result

    return None

# ============== RSS SCANNING ==============

def fetch_rss_feed(feed_url: str, max_items: int = 20) -> List[Dict]:
    """Fetch and parse RSS feed"""
    try:
        feed = feedparser.parse(feed_url)
        articles = []

        for entry in feed.entries[:max_items]:
            pub_date = entry.get('published_parsed') or entry.get('updated_parsed')
            if pub_date:
                pub_date = datetime(*pub_date[:6])
            else:
                pub_date = datetime.now()

            articles.append({
                'title': entry.get('title', ''),
                'link': entry.get('link', ''),
                'summary': entry.get('summary', '')[:300] if entry.get('summary') else '',
                'published': pub_date,
                'source': feed.feed.get('title', 'Unknown')
            })
        return articles
    except:
        return []

def check_headline_for_watchlist(headline: str, summary: str, watchlist: List[str]) -> Optional[str]:
    """Check if headline mentions any watchlist company"""
    text = (headline + " " + summary).lower()

    for company in watchlist:
        # Check for company name (case insensitive)
        if company.lower() in text:
            return company

        # Check for common abbreviations/variations
        words = company.lower().split()
        if len(words) > 1 and words[0] in text:
            # First word match (e.g., "Ardagh" for "Ardagh Group")
            return company

    return None

def scan_feeds_once(watchlist: List[str], news_sources: Dict, seen: Set[str],
                    min_score: int = 3) -> List[Dict]:
    """Scan all feeds once and return high-impact alerts"""
    alerts = []

    # Get all feed categories
    all_feeds = []
    for category, feeds in news_sources.get("rss_feeds", {}).items():
        for feed in feeds:
            feed["category"] = category
            all_feeds.append(feed)

    # Prioritize high-priority feeds
    priority_feeds = [f for f in all_feeds if f.get("priority") == "high"]
    other_feeds = [f for f in all_feeds if f.get("priority") != "high"]

    # Scan priority feeds first
    for feed in priority_feeds + other_feeds[:20]:  # Limit to avoid rate limits
        articles = fetch_rss_feed(feed["url"], max_items=10)

        for article in articles:
            headline_hash = hash_headline(article["title"], feed["name"])

            # Skip if already seen
            if headline_hash in seen:
                continue

            # Check if mentions watchlist company
            company = check_headline_for_watchlist(
                article["title"],
                article.get("summary", ""),
                watchlist
            )

            if company:
                # Score the headline
                score_result = score_headline(
                    article["title"],
                    feed["name"],
                    company
                )

                if score_result and score_result.get("score", 0) >= min_score:
                    alert = {
                        "headline": article["title"],
                        "source": feed["name"],
                        "category": feed.get("category", ""),
                        "region": feed.get("region", "Global"),
                        "company": company,
                        "link": article["link"],
                        "published": article["published"].isoformat() if hasattr(article["published"], "isoformat") else str(article["published"]),
                        "score": score_result["score"],
                        "direction": score_result["direction"],
                        "reason": score_result.get("reason", ""),
                        "timestamp": datetime.now().isoformat()
                    }
                    alerts.append(alert)

                    # Save alert
                    save_alert(alert)

                    # Send Telegram
                    send_pulse_alert(alert)

            # Mark as seen
            seen.add(headline_hash)

    return alerts

def send_pulse_alert(alert: Dict):
    """Format and send a Market Pulse alert to Telegram"""
    direction_emoji = {
        "UP": "📈",
        "DOWN": "📉",
        "UNCERTAIN": "❓"
    }

    score_emoji = {
        3: "⚠️",
        4: "🔔",
        5: "🚨"
    }

    emoji = score_emoji.get(alert["score"], "⚠️")
    dir_emoji = direction_emoji.get(alert["direction"], "❓")

    msg = (
        f"{emoji} *Market Pulse Alert*\n\n"
        f"*{alert['company']}* {dir_emoji} (Score: {alert['score']}/5)\n\n"
        f"_{alert['headline']}_\n\n"
        f"📰 {alert['source']} ({alert['region']})\n"
        f"💡 {alert['reason']}\n\n"
        f"[Read more]({alert['link']})"
    )

    send_telegram_alert(msg)

# ============== BACKGROUND SCANNER ==============

_scanner_running = False
_scanner_thread = None

def start_background_scanner(interval_minutes: int = 5, min_score: int = 3):
    """Start background RSS scanner with health monitoring"""
    global _scanner_running, _scanner_thread

    if _scanner_running:
        return

    _scanner_running = True

    def scanner_loop():
        global _scanner_running
        watchlist = load_watchlist()
        news_sources = load_news_sources()
        seen = load_seen_headlines()

        if pulse_logger:
            pulse_logger.info(f"Scanner started - interval={interval_minutes}min, min_score={min_score}")

        while _scanner_running:
            try:
                # Send heartbeat if thread monitoring is available
                if UTILS_AVAILABLE:
                    thread_monitor.heartbeat("market_pulse_scanner")

                # Scan feeds
                alerts = scan_feeds_once(watchlist, news_sources, seen, min_score)

                if pulse_logger and alerts:
                    pulse_logger.info(f"Scan complete - {len(alerts)} new alerts")

                # Save seen headlines
                save_seen_headlines(seen)

                # Wait before next scan (in smaller intervals for responsive shutdown)
                wait_time = interval_minutes * 60
                while wait_time > 0 and _scanner_running:
                    time.sleep(min(30, wait_time))
                    wait_time -= 30
                    # Send heartbeat during wait
                    if UTILS_AVAILABLE:
                        thread_monitor.heartbeat("market_pulse_scanner")

            except Exception as e:
                if pulse_logger:
                    pulse_logger.error(f"Scanner error: {e}")
                else:
                    print(f"Scanner error: {e}")
                time.sleep(60)  # Wait 1 min on error

    # Use thread monitor if available for auto-restart capability
    if UTILS_AVAILABLE:
        _scanner_thread = thread_monitor.register_thread(
            name="market_pulse_scanner",
            target=scanner_loop,
            heartbeat_timeout=interval_minutes * 60 + 120,  # Allow extra time
            auto_restart=True,
            daemon=True
        )
        if pulse_logger:
            pulse_logger.info("Scanner registered with health monitor")
    else:
        _scanner_thread = Thread(target=scanner_loop, daemon=True)
        _scanner_thread.start()

def stop_background_scanner():
    """Stop background scanner"""
    global _scanner_running
    _scanner_running = False
    if pulse_logger:
        pulse_logger.info("Scanner stop requested")

def get_scanner_health() -> Dict:
    """Get health status of the scanner thread"""
    if UTILS_AVAILABLE:
        status = thread_monitor.get_health_status()
        return status.get("market_pulse_scanner", {"healthy": False, "status": "not_registered"})
    return {"healthy": _scanner_running, "status": "running" if _scanner_running else "stopped"}

# ============== STREAMLIT UI ==============

def render_market_pulse():
    """Render the Market Pulse dashboard"""

    st.subheader("Market Pulse")
    st.caption("Real-time bond-moving news monitor")

    # Check for LLM availability
    has_llm = (OPENAI_AVAILABLE and OPENAI_API_KEY) or (ANTHROPIC_AVAILABLE and ANTHROPIC_API_KEY)

    if not has_llm:
        st.error("No LLM configured. Add OPENAI_API_KEY or ANTHROPIC_API_KEY to enable headline scoring.")
        return

    # Scanner controls
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        min_score = st.selectbox(
            "Min Alert Score",
            [3, 4, 5],
            index=0,
            help="Only alert on headlines with this score or higher"
        )

    with col2:
        interval = st.selectbox(
            "Scan Interval",
            [5, 10, 15, 30],
            index=0,
            help="Minutes between scans"
        )

    with col3:
        if st.button("Start Background Scanner", type="primary"):
            start_background_scanner(interval_minutes=interval, min_score=min_score)
            st.success(f"Scanner started! Checking every {interval} mins for score ≥{min_score}")

    st.markdown("---")

    # Manual scan
    st.markdown("### Manual Scan")

    if st.button("Scan Now"):
        with st.spinner("Scanning feeds for bond-moving news..."):
            watchlist = load_watchlist()
            news_sources = load_news_sources()
            seen = load_seen_headlines()

            alerts = scan_feeds_once(watchlist, news_sources, seen, min_score=min_score)
            save_seen_headlines(seen)

            if alerts:
                st.success(f"Found {len(alerts)} high-impact headlines!")
            else:
                st.info("No new high-impact headlines found")

    st.markdown("---")

    # Recent alerts
    st.markdown("### Recent Alerts")

    alerts = load_alerts_log()

    if alerts:
        # Sort by timestamp descending
        alerts = sorted(alerts, key=lambda x: x.get("timestamp", ""), reverse=True)

        for alert in alerts[:20]:
            score = alert.get("score", 0)
            direction = alert.get("direction", "UNCERTAIN")

            # Color based on direction
            if direction == "UP":
                color = "🟢"
            elif direction == "DOWN":
                color = "🔴"
            else:
                color = "🟡"

            with st.expander(f"{color} **{alert.get('company', 'Unknown')}** - Score {score}/5 - {alert.get('headline', '')[:60]}..."):
                st.markdown(f"**Headline:** {alert.get('headline', '')}")
                st.markdown(f"**Source:** {alert.get('source', '')} ({alert.get('region', '')})")
                st.markdown(f"**Direction:** {direction}")
                st.markdown(f"**Reason:** {alert.get('reason', '')}")
                st.markdown(f"**Time:** {alert.get('timestamp', '')[:19]}")
                if alert.get("link"):
                    st.markdown(f"[Read article]({alert.get('link')})")
    else:
        st.info("No alerts yet. Start the scanner or run a manual scan.")

    st.markdown("---")

    # Watchlist info
    st.markdown("### Watchlist")
    watchlist = load_watchlist()
    st.caption(f"Monitoring {len(watchlist)} companies from XO S44 index")

    with st.expander("View watchlist"):
        st.write(sorted(watchlist)[:50])
        if len(watchlist) > 50:
            st.caption(f"... and {len(watchlist) - 50} more")

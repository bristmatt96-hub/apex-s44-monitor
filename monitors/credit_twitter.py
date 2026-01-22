"""
Credit Twitter - Curated X/Twitter Feed for Credit Professionals
Monitors trusted accounts for credit-relevant signals
Sends Telegram alerts for high-priority credit tweets
"""

import streamlit as st
import tweepy
import os
import json
import requests
import time
from threading import Thread
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set

# Load secrets
TWITTER_BEARER_TOKEN = st.secrets.get("TWITTER_BEARER_TOKEN", st.secrets.get("Bearer token", os.environ.get("TWITTER_BEARER_TOKEN", "")))
TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))

# Config directory
CONFIG_DIR = Path(__file__).parent.parent / "config"
SEEN_TWEETS_FILE = CONFIG_DIR / "seen_tweets.json"
CUSTOM_ACCOUNTS_FILE = CONFIG_DIR / "credit_twitter_accounts.json"

# ============== TELEGRAM ALERTS ==============

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


def load_seen_tweets() -> Set[str]:
    """Load set of already-seen tweet IDs"""
    if SEEN_TWEETS_FILE.exists():
        try:
            with open(SEEN_TWEETS_FILE, "r") as f:
                data = json.load(f)
                return set(data.get("seen_ids", []))
        except:
            pass
    return set()


def save_seen_tweets(seen_ids: Set[str]):
    """Save seen tweet IDs (keep only last 1000)"""
    CONFIG_DIR.mkdir(exist_ok=True)
    # Keep only most recent 1000 to avoid file bloat
    recent = list(seen_ids)[-1000:]
    with open(SEEN_TWEETS_FILE, "w") as f:
        json.dump({"seen_ids": recent, "updated": datetime.now().isoformat()}, f)


def format_tweet_alert(tweet: Dict) -> str:
    """Format a tweet as a Telegram alert message"""
    keywords = tweet.get('keywords', [])
    keywords_str = ", ".join(keywords[:5]) if keywords else "credit"

    msg = (
        f"*Credit Alert* ({keywords_str})\n\n"
        f"@{tweet.get('username', 'unknown')} ({tweet.get('category', '')})\n\n"
        f"{tweet.get('text', '')[:500]}\n\n"
        f"[View on X]({tweet.get('link', '')})"
    )
    return msg


# ============== BACKGROUND MONITOR ==============

_monitor_running = False

def monitor_curated_accounts(interval_minutes: int = 5):
    """
    Background thread that monitors curated accounts for new credit-relevant tweets.
    Sends Telegram alerts for new tweets.
    """
    global _monitor_running

    if not TWITTER_BEARER_TOKEN:
        print("[CreditTwitter] No Twitter token - monitor disabled")
        return

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[CreditTwitter] No Telegram config - monitor disabled")
        return

    print(f"[CreditTwitter] Starting monitor (checking every {interval_minutes} min)")
    _monitor_running = True

    client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
    seen_ids = load_seen_tweets()

    while _monitor_running:
        try:
            accounts = get_all_accounts()
            new_alerts = 0

            for account in accounts:
                handle = account.get('handle', '')
                if not handle:
                    continue

                try:
                    tweets = get_account_tweets(client, handle, max_results=5)

                    for tweet in tweets:
                        if 'error' in tweet:
                            continue

                        tweet_id = str(tweet.get('id', ''))

                        # Skip if already seen
                        if tweet_id in seen_ids:
                            continue

                        # Mark as seen
                        seen_ids.add(tweet_id)

                        # Only alert for credit-relevant tweets
                        if tweet.get('is_credit_relevant'):
                            tweet['category'] = account.get('category', 'Unknown')
                            msg = format_tweet_alert(tweet)
                            if send_telegram_alert(msg):
                                new_alerts += 1
                                print(f"[CreditTwitter] Alert sent: @{handle}")

                    time.sleep(1)  # Rate limiting between accounts

                except Exception as e:
                    print(f"[CreditTwitter] Error checking @{handle}: {e}")
                    continue

            # Save seen IDs periodically
            save_seen_tweets(seen_ids)

            if new_alerts > 0:
                print(f"[CreditTwitter] Sent {new_alerts} alerts")

        except Exception as e:
            print(f"[CreditTwitter] Monitor error: {e}")

        # Wait before next check
        time.sleep(interval_minutes * 60)


def start_credit_twitter_monitor():
    """Start the background monitor thread"""
    global _monitor_running

    if _monitor_running:
        return  # Already running

    thread = Thread(target=monitor_curated_accounts, daemon=True)
    thread.start()
    return thread


# ============== CURATED ACCOUNT LISTS ==============

# Pre-built lists of trusted credit accounts by category
DEFAULT_ACCOUNTS = {
    "rating_agencies": [
        {"handle": "MoodysCorp", "name": "Moody's Corporation", "category": "Rating Agency"},
        {"handle": "SPGlobal", "name": "S&P Global", "category": "Rating Agency"},
        {"handle": "FitchRatings", "name": "Fitch Ratings", "category": "Rating Agency"},
    ],
    "credit_news": [
        {"handle": "Aborosglobal", "name": "Aboros Global", "category": "Credit News"},
        {"handle": "9aborosglobal", "name": "9Aboros", "category": "Credit News"},
        {"handle": "FinancialJuice", "name": "Financial Juice", "category": "News"},
        {"handle": "Newsquawk", "name": "Newsquawk", "category": "News"},
        {"handle": "DeItaone", "name": "Walter Bloomberg", "category": "News"},
    ],
    "analysts_traders": [
        {"handle": "CreditSights", "name": "CreditSights", "category": "Research"},
        {"handle": "bondaborosglobal", "name": "Bond News", "category": "Fixed Income"},
    ],
    "restructuring": [
        # Add restructuring lawyers/advisors as you find good ones
    ],
    "sector_specific": [
        # TMT, Autos, etc specialists
    ]
}

# Credit-specific keywords for filtering
CREDIT_KEYWORDS = [
    # Rating actions
    "downgrade", "upgrade", "outlook negative", "outlook positive",
    "rating watch", "creditwatch", "review for downgrade",

    # Distress signals
    "covenant breach", "covenant waiver", "liquidity concerns",
    "going concern", "default", "missed payment", "forbearance",

    # Restructuring
    "restructuring", "liability management", "exchange offer",
    "maturity extension", "amend and extend", "debt-for-equity",
    "chapter 11", "scheme of arrangement", "standstill",

    # Refinancing
    "refinancing", "repricing", "new issue", "bond issue",
    "term loan", "revolver", "high yield", "leveraged loan",

    # M&A / LBO
    "lbo", "leveraged buyout", "acquisition financing",
    "take-private", "sponsor-backed",

    # Spread movements
    "cds", "spread", "basis points", "bps wider", "bps tighter",
    "trading at", "bid wanted", "distressed",
]

def load_custom_accounts() -> List[Dict]:
    """Load user's custom account list"""
    if CUSTOM_ACCOUNTS_FILE.exists():
        try:
            with open(CUSTOM_ACCOUNTS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return []


def save_custom_accounts(accounts: List[Dict]):
    """Save user's custom account list"""
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(CUSTOM_ACCOUNTS_FILE, "w") as f:
        json.dump(accounts, f, indent=2)


def get_all_accounts() -> List[Dict]:
    """Get combined list of default + custom accounts"""
    all_accounts = []

    # Add defaults
    for category, accounts in DEFAULT_ACCOUNTS.items():
        for acc in accounts:
            acc["source"] = "default"
            all_accounts.append(acc)

    # Add custom
    custom = load_custom_accounts()
    for acc in custom:
        acc["source"] = "custom"
        all_accounts.append(acc)

    return all_accounts


def is_credit_relevant(text: str) -> tuple[bool, List[str]]:
    """Check if tweet contains credit-relevant keywords"""
    text_lower = text.lower()
    matches = []

    for keyword in CREDIT_KEYWORDS:
        if keyword.lower() in text_lower:
            matches.append(keyword)

    return len(matches) > 0, matches


def get_account_tweets(client: tweepy.Client, username: str, max_results: int = 10) -> List[Dict]:
    """Fetch recent tweets from a specific account"""
    try:
        # First get user ID
        user = client.get_user(username=username)
        if not user.data:
            return []

        user_id = user.data.id

        # Get recent tweets
        tweets = client.get_users_tweets(
            id=user_id,
            max_results=max_results,
            tweet_fields=['created_at', 'public_metrics', 'text'],
            exclude=['retweets', 'replies']
        )

        if not tweets.data:
            return []

        results = []
        for tweet in tweets.data:
            is_relevant, keywords = is_credit_relevant(tweet.text)
            results.append({
                'id': tweet.id,
                'text': tweet.text,
                'created_at': tweet.created_at,
                'likes': tweet.public_metrics.get('like_count', 0) if tweet.public_metrics else 0,
                'retweets': tweet.public_metrics.get('retweet_count', 0) if tweet.public_metrics else 0,
                'username': username,
                'is_credit_relevant': is_relevant,
                'keywords': keywords,
                'link': f"https://x.com/{username}/status/{tweet.id}"
            })

        return results

    except Exception as e:
        return [{'error': str(e), 'username': username}]


def fetch_curated_feed(accounts: List[Dict], filter_relevant_only: bool = False, max_per_account: int = 5) -> List[Dict]:
    """Fetch tweets from all curated accounts"""
    if not TWITTER_BEARER_TOKEN:
        return []

    client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
    all_tweets = []

    for account in accounts:
        handle = account.get('handle', '')
        if not handle:
            continue

        tweets = get_account_tweets(client, handle, max_results=max_per_account)

        for tweet in tweets:
            if 'error' not in tweet:
                tweet['account_name'] = account.get('name', handle)
                tweet['category'] = account.get('category', 'Unknown')

                if filter_relevant_only and not tweet.get('is_credit_relevant'):
                    continue

                all_tweets.append(tweet)

    # Sort by created_at descending
    all_tweets.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)

    return all_tweets


# ============== STREAMLIT UI ==============

def render_credit_twitter():
    """Main render function for Credit Twitter tab"""

    st.subheader("Credit Twitter Feed")
    st.caption("Curated feed from trusted credit accounts")

    if not TWITTER_BEARER_TOKEN:
        st.error("Twitter/X API not configured. Add TWITTER_BEARER_TOKEN to secrets.")
        return

    # Sidebar controls
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        filter_relevant = st.checkbox("Credit keywords only", value=True,
                                       help="Only show tweets containing credit-relevant keywords")

    with col2:
        show_categories = st.multiselect(
            "Categories",
            ["Rating Agency", "Credit News", "Research", "News", "Fixed Income", "Custom"],
            default=["Rating Agency", "Credit News", "Research", "News"]
        )

    with col3:
        tweets_per_account = st.slider("Tweets per account", 3, 10, 5)

    # Get accounts
    all_accounts = get_all_accounts()

    # Filter by category
    if show_categories:
        filtered_accounts = [a for a in all_accounts if a.get('category') in show_categories or
                           (a.get('source') == 'custom' and 'Custom' in show_categories)]
    else:
        filtered_accounts = all_accounts

    st.markdown("---")

    # Main feed
    tab1, tab2 = st.tabs(["Feed", "Manage Accounts"])

    with tab1:
        if st.button("Refresh Feed", type="primary"):
            st.cache_data.clear()

        if not filtered_accounts:
            st.info("No accounts selected. Adjust category filters or add custom accounts.")
            return

        with st.spinner(f"Fetching from {len(filtered_accounts)} accounts..."):
            tweets = fetch_curated_feed(
                filtered_accounts,
                filter_relevant_only=filter_relevant,
                max_per_account=tweets_per_account
            )

        if not tweets:
            st.info("No tweets found. Try adjusting filters or check API connection.")
            return

        st.markdown(f"**{len(tweets)} tweets** from {len(filtered_accounts)} accounts")
        st.markdown("---")

        # Display tweets
        for tweet in tweets[:50]:  # Limit display
            render_tweet(tweet)

    with tab2:
        render_account_manager()


def render_tweet(tweet: Dict):
    """Render a single tweet"""

    # Color code by relevance
    if tweet.get('is_credit_relevant'):
        border_color = "#4CAF50"  # Green for credit-relevant
    else:
        border_color = "#666"

    # Format timestamp
    created = tweet.get('created_at')
    if created:
        time_str = created.strftime("%b %d, %H:%M")
    else:
        time_str = ""

    # Build card
    with st.container():
        # Header
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.markdown(f"**@{tweet.get('username')}** ({tweet.get('category', '')})")
        with col2:
            st.caption(time_str)
        with col3:
            likes = tweet.get('likes', 0)
            rts = tweet.get('retweets', 0)
            st.caption(f"{likes} likes | {rts} RTs")

        # Tweet text
        text = tweet.get('text', '')

        # Highlight keywords if present
        keywords = tweet.get('keywords', [])
        if keywords:
            st.markdown(f"**Keywords:** {', '.join(keywords)}")

        st.markdown(text)

        # Link
        st.markdown(f"[View on X]({tweet.get('link', '')})")

        st.markdown("---")


def render_account_manager():
    """UI for managing custom accounts"""

    st.markdown("### Default Accounts")
    st.caption("Pre-configured trusted credit accounts")

    # Show defaults by category
    for category, accounts in DEFAULT_ACCOUNTS.items():
        if accounts:
            with st.expander(f"{category.replace('_', ' ').title()} ({len(accounts)})"):
                for acc in accounts:
                    st.markdown(f"- **@{acc['handle']}** - {acc['name']}")

    st.markdown("---")
    st.markdown("### Custom Accounts")
    st.caption("Add your own trusted accounts to monitor")

    # Load custom accounts
    custom_accounts = load_custom_accounts()

    # Add new account form
    with st.form("add_account"):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            new_handle = st.text_input("X Handle (without @)", placeholder="username")
        with col2:
            new_name = st.text_input("Display Name", placeholder="Account Name")
        with col3:
            new_category = st.selectbox("Category",
                ["Custom", "Rating Agency", "Credit News", "Research", "Restructuring", "Analyst"])

        if st.form_submit_button("Add Account"):
            if new_handle:
                # Remove @ if included
                new_handle = new_handle.replace("@", "").strip()

                # Check if already exists
                existing = [a for a in custom_accounts if a['handle'].lower() == new_handle.lower()]
                if existing:
                    st.warning(f"@{new_handle} already in list")
                else:
                    custom_accounts.append({
                        "handle": new_handle,
                        "name": new_name or new_handle,
                        "category": new_category
                    })
                    save_custom_accounts(custom_accounts)
                    st.success(f"Added @{new_handle}")
                    st.rerun()

    # Display and manage custom accounts
    if custom_accounts:
        st.markdown("**Your Custom Accounts:**")
        for i, acc in enumerate(custom_accounts):
            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                st.markdown(f"@{acc['handle']}")
            with col2:
                st.caption(acc.get('category', 'Custom'))
            with col3:
                if st.button("Remove", key=f"remove_{i}"):
                    custom_accounts.pop(i)
                    save_custom_accounts(custom_accounts)
                    st.rerun()
    else:
        st.info("No custom accounts added yet. Add trusted credit accounts above.")

    # Suggested accounts to add
    st.markdown("---")
    st.markdown("### Suggested Accounts")
    st.caption("Accounts commonly followed in credit markets")

    suggestions = [
        ("Debtwire", "debaborosglobal", "Debtwire news"),
        ("9Fin", "9aborosglobal", "European credit news"),
        ("LCD News", "LeveragedLoan", "Leveraged loan news"),
        ("IFR", "IFaborosglobal", "Bond/loan market news"),
        ("Reorg Research", "reaborosglobal", "Restructuring research"),
    ]

    for name, handle, desc in suggestions:
        # Check if already added
        all_handles = [a['handle'].lower() for a in get_all_accounts()]
        if handle.lower() not in all_handles:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**@{handle}** - {desc}")
            with col2:
                if st.button(f"Add", key=f"suggest_{handle}"):
                    custom_accounts.append({
                        "handle": handle,
                        "name": name,
                        "category": "Credit News"
                    })
                    save_custom_accounts(custom_accounts)
                    st.success(f"Added @{handle}")
                    st.rerun()

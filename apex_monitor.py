import streamlit as st
import tweepy
from threading import Thread
import time
import requests
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
import feedparser

# ============== CONFIGURATION ==============

# Load secrets from Streamlit Cloud or environment variables
TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))
TWITTER_BEARER_TOKEN = st.secrets.get("TWITTER_BEARER_TOKEN", st.secrets.get("Bearer token", os.environ.get("TWITTER_BEARER_TOKEN", "")))
NEWSAPI_KEY = st.secrets.get("NEWSAPI_KEY", os.environ.get("NEWSAPI_KEY", ""))
DATABASE_URL = st.secrets.get("DATABASE_URL", os.environ.get("DATABASE_URL", ""))

# Try to import database module (optional - falls back to JSON if unavailable)
DB_AVAILABLE = False
try:
    if DATABASE_URL:
        from database import get_session, get_all_companies, get_latest_financials, get_debt_instruments
        DB_AVAILABLE = True
except ImportError:
    pass

# Try to import tear sheet generator
TEARSHEET_AVAILABLE = False
try:
    from generators import generate_tearsheet_html
    TEARSHEET_AVAILABLE = True
except ImportError:
    pass

# Try to import equity monitor
EQUITY_MONITOR_AVAILABLE = False
try:
    from monitors import render_equity_dashboard, YFINANCE_AVAILABLE
    EQUITY_MONITOR_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# Try to import knowledge base
KNOWLEDGE_BASE_AVAILABLE = False
try:
    from knowledge.pdf_processor import KnowledgeBase, render_knowledge_base_ui
    KNOWLEDGE_BASE_AVAILABLE = True
except ImportError:
    pass

# Try to import credit events monitor
CREDIT_EVENTS_AVAILABLE = False
try:
    from monitors.credit_events_monitor import render_credit_events_dashboard
    CREDIT_EVENTS_AVAILABLE = True
except ImportError:
    pass

# Try to import morning brief
MORNING_BRIEF_AVAILABLE = False
try:
    from monitors.morning_brief import send_morning_brief, start_scheduler
    MORNING_BRIEF_AVAILABLE = True
except ImportError:
    pass

# Try to import trading tools
TRADING_TOOLS_AVAILABLE = False
try:
    from monitors.trading_tools import render_trading_tools
    TRADING_TOOLS_AVAILABLE = True
except ImportError:
    pass

# Try to import credit twitter
CREDIT_TWITTER_AVAILABLE = False
try:
    from monitors.credit_twitter import render_credit_twitter
    CREDIT_TWITTER_AVAILABLE = True
except ImportError:
    pass

# ============== TELEGRAM FUNCTIONS ==============

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
    success = send_telegram_message("*XO S44 Monitor Test*\nIf you see this, Telegram alerts are working!")
    if success:
        print("Test message sent successfully!")
    else:
        print("Failed to send test message - check bot token and chat ID")
    return success

# ============== DATA LOADING FUNCTIONS ==============

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

def load_news_sources():
    """Load RSS feed configurations"""
    config_path = Path(__file__).parent / "config" / "news_sources.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"rss_feeds": {}, "newsapi_keywords": {}}

def load_snapshot(company_name):
    """Load credit snapshot for a company - tries database first, then JSON"""
    # Try database first if available
    if DB_AVAILABLE:
        try:
            session = get_session()
            # Database lookup logic would go here
            session.close()
        except:
            pass

    # Fall back to JSON files
    snapshots_dir = Path(__file__).parent / "snapshots"
    if not snapshots_dir.exists():
        return None
    for f in snapshots_dir.glob("*.json"):
        if f.stem == "template":
            continue
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
                if data.get("company_name") == company_name:
                    return data
        except:
            continue
    return None

def get_available_snapshots():
    """Get list of companies with snapshots"""
    snapshots_dir = Path(__file__).parent / "snapshots"
    if not snapshots_dir.exists():
        return []
    snapshots = []
    for f in snapshots_dir.glob("*.json"):
        if f.stem == "template":
            continue
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
                snapshots.append(data.get("company_name", f.stem))
        except:
            continue
    return snapshots

def get_search_terms(name, aliases):
    """Get search terms for a company including aliases"""
    terms = [name]
    if name in aliases:
        terms.extend(aliases[name])
    return terms

# ============== TRADING SIGNALS ==============

# Signal definitions for long/short decisions
SIGNAL_CRITERIA = {
    "fundamental_positive": [
        "improving_leverage",      # Debt/EBITDA declining
        "positive_fcf",            # Generating free cash flow
        "deleveraging",            # Active debt paydown
        "margin_expansion",        # EBITDA margins improving
        "rating_upgrade_watch",    # Potential upgrade
    ],
    "fundamental_negative": [
        "deteriorating_leverage",  # Debt/EBITDA increasing
        "negative_fcf",            # Burning cash
        "maturity_wall",           # Near-term refinancing risk
        "margin_compression",      # EBITDA margins declining
        "rating_downgrade_watch",  # Potential downgrade
    ],
    "event_driven": [
        "m_and_a_target",          # Potential acquisition target
        "activist_involved",       # Activist investor
        "management_change",       # New CEO/CFO
        "asset_sale",              # Divesting assets
        "restructuring",           # Debt restructuring
    ],
    "technical": [
        "spread_dislocation",      # Trading wide vs fundamentals
        "new_issue_concession",    # New bond at attractive levels
        "index_inclusion",         # Entering major index
        "short_squeeze",           # Technical buying pressure
    ]
}

def calculate_signal_score(snapshot, news_sentiment=0):
    """
    Calculate a trading signal score for a credit
    Returns: (score, signal, rationale)
    - score: -100 (strong short) to +100 (strong long)
    - signal: "LONG", "SHORT", "NEUTRAL"
    - rationale: list of reasons
    """
    if not snapshot:
        return (0, "NO DATA", ["Insufficient data for analysis"])

    score = 0
    rationale = []

    # Fundamental analysis
    key_ratios = snapshot.get('key_ratios', {})
    qa = snapshot.get('quick_assessment', {})

    # Leverage assessment
    leverage = key_ratios.get('debt_to_ebitda')
    if leverage:
        if leverage < 4.0:
            score += 20
            rationale.append(f"Low leverage ({leverage}x) - defensive")
        elif leverage > 6.0:
            score -= 20
            rationale.append(f"High leverage ({leverage}x) - elevated risk")
        elif leverage > 5.0:
            score -= 10
            rationale.append(f"Moderate leverage ({leverage}x)")

    # Interest coverage
    coverage = key_ratios.get('ebitda_minus_capex_to_interest')
    if coverage:
        if coverage > 3.0:
            score += 15
            rationale.append(f"Strong interest coverage ({coverage}x)")
        elif coverage < 1.5:
            score -= 25
            rationale.append(f"Weak interest coverage ({coverage}x) - stress signal")

    # FCF generation
    fcf_to_debt = key_ratios.get('fcf_to_debt')
    if fcf_to_debt:
        if fcf_to_debt > 0.10:
            score += 15
            rationale.append(f"Strong FCF/Debt ({fcf_to_debt:.1%}) - deleveraging capacity")
        elif fcf_to_debt < 0:
            score -= 20
            rationale.append(f"Negative FCF - cash burn concern")

    # Liquidity assessment
    cash = qa.get('cash_on_hand', 0) or 0
    revolver = qa.get('revolver_available', 0) or 0
    debt_due = qa.get('debt_due_one_year', 0) or 0

    if debt_due > 0:
        liquidity_ratio = (cash + revolver) / debt_due
        if liquidity_ratio > 2.0:
            score += 10
            rationale.append("Adequate liquidity vs near-term maturities")
        elif liquidity_ratio < 1.0:
            score -= 25
            rationale.append("Liquidity concern - maturities exceed cash + revolver")

    # Credit opinion
    opinion = snapshot.get('credit_opinion', {})
    rec = opinion.get('recommendation', '').upper()
    if 'OVER' in rec:
        score += 20
        rationale.append("Analyst recommendation: Overweight")
    elif 'UNDER' in rec:
        score -= 20
        rationale.append("Analyst recommendation: Underweight")

    # News sentiment adjustment
    score += news_sentiment * 10
    if news_sentiment > 0:
        rationale.append("Positive news flow")
    elif news_sentiment < 0:
        rationale.append("Negative news flow")

    # Determine signal
    if score >= 30:
        signal = "LONG"
    elif score <= -30:
        signal = "SHORT"
    else:
        signal = "NEUTRAL"

    return (score, signal, rationale)


def get_all_signals(index_data):
    """Calculate signals for all companies in the index"""
    signals = []
    for sector, names in index_data["sectors"].items():
        for name in names:
            snapshot = load_snapshot(name)
            score, signal, rationale = calculate_signal_score(snapshot)
            signals.append({
                'company': name,
                'sector': sector,
                'score': score,
                'signal': signal,
                'rationale': rationale,
                'has_snapshot': snapshot is not None
            })
    return sorted(signals, key=lambda x: x['score'], reverse=True)


# Credit-relevant keywords by category
CREDIT_KEYWORDS = {
    "spread_moving": ["CDS", "downgrade", "upgrade", "outlook", "rating", "leverage", "debt", "default"],
    "corporate_events": ["restructuring", "refinancing", "M&A", "acquisition", "merger", "takeover", "buyout"],
    "regulatory": ["antitrust", "regulatory", "clearance", "approval", "investigation"],
    "earnings": ["earnings", "EBITDA", "revenue", "profit", "loss", "guidance"],
    "sector_specific": ["tariff", "EV", "supply chain", "strike", "bankruptcy"]
}

# ============== RSS FEED FUNCTIONS ==============

def fetch_rss_feed(feed_url, max_items=10):
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
                'summary': entry.get('summary', '')[:200] if entry.get('summary') else '',
                'published': pub_date,
                'source': feed.feed.get('title', 'Unknown')
            })
        return articles
    except Exception as e:
        print(f"RSS Error: {e}")
        return []

def search_rss_for_company(company_name, aliases, feeds):
    """Search RSS feeds for mentions of a company"""
    search_terms = [company_name.lower()] + [a.lower() for a in aliases]
    matches = []

    for feed_info in feeds:
        articles = fetch_rss_feed(feed_info['url'], max_items=20)
        for article in articles:
            text = (article['title'] + ' ' + article['summary']).lower()
            if any(term in text for term in search_terms):
                article['feed_name'] = feed_info['name']
                article['region'] = feed_info.get('region', 'Global')
                matches.append(article)

    # Sort by date, most recent first
    matches.sort(key=lambda x: x['published'], reverse=True)
    return matches[:10]

# ============== NEWSAPI FUNCTIONS ==============

def search_newsapi(query, days_back=7):
    """Search NewsAPI for articles"""
    if not NEWSAPI_KEY:
        return []

    try:
        from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        url = "https://newsapi.org/v2/everything"
        params = {
            'q': query,
            'from': from_date,
            'sortBy': 'relevancy',
            'language': 'en',
            'pageSize': 10,
            'apiKey': NEWSAPI_KEY
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.ok:
            data = resp.json()
            articles = []
            for item in data.get('articles', []):
                articles.append({
                    'title': item.get('title', ''),
                    'link': item.get('url', ''),
                    'summary': item.get('description', '')[:200] if item.get('description') else '',
                    'published': datetime.fromisoformat(item['publishedAt'].replace('Z', '+00:00')) if item.get('publishedAt') else datetime.now(),
                    'source': item.get('source', {}).get('name', 'Unknown'),
                    'feed_name': 'NewsAPI',
                    'region': 'Global'
                })
            return articles
        return []
    except Exception as e:
        print(f"NewsAPI Error: {e}")
        return []

# ============== NEWS HOUND CLASS ==============

class NewsHound:
    def __init__(self, index_data):
        self.client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
        self.alerts = {}
        self.rss_alerts = {}
        self.sentiment_scores = {}  # Track news sentiment per company
        self.index_data = index_data
        self.aliases = index_data.get("search_aliases", {})
        self.news_sources = load_news_sources()
        print(f"=== XO S44 Credit Monitor Started ===")
        print(f"Monitoring: {index_data['name']} ({index_data['total_names']} names)")

    def scour(self, name, sector):
        """Search for credit-relevant news on X/Twitter"""
        search_terms = get_search_terms(name, self.aliases)
        primary_term = search_terms[0]
        short_name = search_terms[1] if len(search_terms) > 1 else primary_term.split()[0]

        keywords = " OR ".join(CREDIT_KEYWORDS["spread_moving"][:4] + CREDIT_KEYWORDS["corporate_events"][:3])
        query = (
            f'("{short_name}" OR "{primary_term}") ({keywords}) '
            f'lang:en -filter:replies -is:retweet'
        )

        if len(query) > 500:
            query = f'"{short_name}" (CDS OR debt OR rating OR restructuring) lang:en -filter:replies -is:retweet'

        try:
            tweets = self.client.search_recent_tweets(
                query=query,
                max_results=10,
                tweet_fields=['created_at', 'public_metrics', 'lang']
            )
            new_alerts = []
            sentiment = 0

            if tweets.data:
                for tweet in tweets.data:
                    impact = self.spot_pattern(name, tweet.text, sector)
                    likes = tweet.public_metrics.get('like_count', 0)

                    # Update sentiment score
                    if "NEGATIVE" in impact or "HIGH RISK" in impact:
                        sentiment -= 1
                    elif "POSITIVE" in impact:
                        sentiment += 1

                    new_alerts.append({
                        'source': 'X/Twitter',
                        'date': tweet.created_at.date(),
                        'text': tweet.text[:140] + '...',
                        'impact': impact,
                        'likes': likes,
                        'link': f"https://x.com/i/status/{tweet.id}"
                    })
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
                new_alerts.append({
                    'source': 'X/Twitter',
                    'date': datetime.now().date(),
                    'text': 'No recent activity matching credit keywords',
                    'impact': 'N/A',
                    'likes': 0,
                    'link': ''
                })

            self.alerts[name] = new_alerts
            self.sentiment_scores[name] = sentiment

        except Exception as e:
            self.alerts[name] = [{
                'source': 'X/Twitter',
                'date': datetime.now().date(),
                'text': f'API error: {str(e)}',
                'impact': 'ERROR',
                'likes': 0,
                'link': ''
            }]

    def scour_rss(self, name, sector):
        """Search RSS feeds for company mentions"""
        aliases = self.aliases.get(name, [])

        # Get relevant feeds based on sector
        feeds = self.news_sources.get('rss_feeds', {}).get('general_credit', [])
        feeds += self.news_sources.get('rss_feeds', {}).get('european', [])

        if 'Auto' in sector or 'Industrial' in sector:
            feeds += self.news_sources.get('rss_feeds', {}).get('sector_autos', [])
        elif 'TMT' in sector:
            feeds += self.news_sources.get('rss_feeds', {}).get('sector_tmt', [])
        elif 'Consumer' in sector or 'Retail' in sector:
            feeds += self.news_sources.get('rss_feeds', {}).get('sector_retail', [])

        matches = search_rss_for_company(name, aliases, feeds)

        # Also search NewsAPI if key is available
        if NEWSAPI_KEY:
            short_name = aliases[0] if aliases else name.split()[0]
            newsapi_results = search_newsapi(f'"{short_name}" AND (debt OR bond OR rating)')
            matches.extend(newsapi_results)

        self.rss_alerts[name] = matches[:10]

    def spot_pattern(self, name, text, sector):
        """Analyze tweet for credit impact"""
        txt = text.lower()

        if any(w in txt for w in ['downgrade', 'negative outlook', 'rating cut']):
            return "NEGATIVE: Rating pressure - expect CDS widening 10-30bps"
        if any(w in txt for w in ['upgrade', 'positive outlook', 'rating raise']):
            return "POSITIVE: Rating improvement - expect CDS tightening"
        if any(w in txt for w in ['restructuring', 'bankruptcy', 'default']):
            return "HIGH RISK: Restructuring signal - significant spread impact likely"
        if any(w in txt for w in ['acquisition', 'takeover', 'buyout', 'm&a']):
            return "EVENT: M&A activity - monitor for leverage impact"
        if any(w in txt for w in ['refinancing', 'bond issue', 'new debt']):
            return "NEUTRAL: Refinancing activity - monitor terms"
        if any(w in txt for w in ['antitrust', 'regulatory', 'investigation']):
            return "RISK: Regulatory scrutiny - potential headline risk"
        if sector == "Autos & Industrials":
            if any(w in txt for w in ['tariff', 'ev', 'supply chain', 'chip shortage']):
                return f"SECTOR: Auto/Industrial headwind - compare to sector peers"
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
                    self.scour_rss(name, sector)
                    time.sleep(2)
            time.sleep(600)


# ============== STREAMLIT RENDERING ==============

def render_snapshot(snapshot):
    """Render credit snapshot in Streamlit"""
    if not snapshot:
        st.warning("No credit snapshot available for this company. Use the template in /snapshots to create one.")
        return

    # Header
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown(f"## {snapshot['company_name']}")
        st.caption(f"Sector: {snapshot['sector']} | Last Updated: {snapshot['last_updated']}")
    with col2:
        ratings = snapshot.get('ratings', {})
        if ratings:
            rating_str = " | ".join([
                f"**{agency.upper()}**: {r['rating']} ({r['outlook']})"
                for agency, r in ratings.items() if r.get('rating')
            ])
            st.markdown(rating_str)
    with col3:
        opinion = snapshot.get('credit_opinion', {})
        if opinion.get('recommendation'):
            rec = opinion['recommendation']
            if 'OVER' in rec.upper():
                st.success(f"**{rec}**")
            elif 'UNDER' in rec.upper():
                st.error(f"**{rec}**")
            else:
                st.info(f"**{rec}**")

    # Overview Section
    st.markdown("### Overview")
    overview = snapshot.get('overview', {})
    st.markdown(f"**Business:** {overview.get('business_description', 'N/A')}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Positives:**")
        for pos in overview.get('business_positives', []):
            st.markdown(f"- {pos}")
    with col2:
        st.markdown(f"**Fatal Flaw:** {overview.get('fatal_flaw', 'N/A')}")
        st.markdown(f"**Ownership:** {overview.get('ownership', 'N/A')}")

    if overview.get('recent_news'):
        st.info(f"**Recent News:** {overview['recent_news']}")

    # Quick Assessment
    st.markdown("### Quick Credit Assessment")
    qa = snapshot.get('quick_assessment', {})
    ratios = snapshot.get('key_ratios', {})

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Debt", f"${qa.get('total_debt', 'N/A')}m")
        st.metric("Cash", f"${qa.get('cash_on_hand', 'N/A')}m")
    with col2:
        st.metric("CFFO (LTM)", f"${qa.get('cffo', 'N/A')}m")
        st.metric("Interest Expense", f"${qa.get('interest_expense', 'N/A')}m")
    with col3:
        st.metric("Debt/EBITDA", f"{ratios.get('debt_to_ebitda', 'N/A')}x")
        st.metric("Net Debt/EBITDA", f"{ratios.get('net_debt_to_ebitda', 'N/A')}x")
    with col4:
        st.metric("Interest Coverage", f"{ratios.get('ebitda_minus_capex_to_interest', 'N/A')}x")
        fcf = ratios.get('fcf_to_debt')
        st.metric("FCF/Debt", f"{fcf:.1%}" if fcf else "N/A")

    # Trend Analysis
    st.markdown("### Trend Analysis")
    trend = snapshot.get('trend_analysis', {})
    if trend.get('years'):
        import pandas as pd
        trend_data = {
            'Period': trend['years'],
            'Revenue': trend.get('revenue', []),
            'EBITDA': trend.get('ebitda', []),
            'Margin %': trend.get('ebitda_margin', []),
            'Total Debt': trend.get('total_debt', []),
            'Debt/EBITDA': [
                round(d/e, 1) if d and e else None
                for d, e in zip(trend.get('total_debt', []), trend.get('ebitda', []))
            ]
        }
        df = pd.DataFrame(trend_data)
        st.dataframe(df, hide_index=True, use_container_width=True)

    # Debt Capitalization
    st.markdown("### Debt Capitalization")
    debt_cap = snapshot.get('debt_capitalization', [])
    if debt_cap:
        import pandas as pd
        debt_df = pd.DataFrame(debt_cap)
        debt_df = debt_df.rename(columns={
            'instrument': 'Instrument',
            'amount': 'Amount ($m)',
            'maturity': 'Maturity',
            'coupon': 'Coupon',
            'price': 'Price',
            'ytw': 'YTW %',
            'stw': 'STW (bps)',
            'rating': 'Rating'
        })
        st.dataframe(debt_df, hide_index=True, use_container_width=True)

    # Maturity Schedule
    st.markdown("### Maturity Schedule")
    maturities = snapshot.get('maturity_schedule', {})
    if maturities:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        cols = [col1, col2, col3, col4, col5, col6]
        labels = ['Year 1', 'Year 2', 'Year 3', 'Year 4', 'Year 5', 'Thereafter']
        keys = ['year_1', 'year_2', 'year_3', 'year_4', 'year_5', 'thereafter']
        for col, label, key in zip(cols, labels, keys):
            val = maturities.get(key)
            col.metric(label, f"${val}m" if val else "—")

    # Equity Market Value (if public)
    equity = snapshot.get('equity_market_value', {})
    if equity.get('equity_market_value'):
        st.markdown("### Equity Market Value")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Market Cap", f"${equity.get('equity_market_value', 'N/A')}m")
        with col2:
            st.metric("Stock Price (3m avg)", f"${equity.get('avg_stock_price_3m', 'N/A')}")
        with col3:
            st.metric("TEV", f"${equity.get('total_enterprise_value', 'N/A')}m")
        with col4:
            st.metric("TEV/EBITDA", f"{equity.get('tev_to_ebitda', 'N/A')}x")

    # Credit Opinion
    st.markdown("### Credit Opinion")
    opinion = snapshot.get('credit_opinion', {})
    if opinion.get('summary'):
        st.markdown(opinion['summary'])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Key Risks:**")
        for risk in opinion.get('key_risks', []):
            st.markdown(f"- {risk}")
    with col2:
        st.markdown("**Key Catalysts:**")
        for cat in opinion.get('key_catalysts', []):
            st.markdown(f"- {cat}")

    # Tear sheet export button
    if TEARSHEET_AVAILABLE:
        st.markdown("---")
        if st.button("Export Tear Sheet", key="export_tearsheet"):
            html = generate_tearsheet_html(snapshot)
            st.download_button(
                label="Download HTML Tear Sheet",
                data=html,
                file_name=f"{snapshot['company_name'].replace(' ', '_')}_tearsheet.html",
                mime="text/html"
            )


def render_trading_signals(signals, hound=None):
    """Render the trading signals dashboard"""
    import pandas as pd

    st.markdown("### Trading Signal Summary")
    st.caption("Signals based on fundamental analysis, news sentiment, and credit metrics")

    # Summary stats
    longs = [s for s in signals if s['signal'] == 'LONG']
    shorts = [s for s in signals if s['signal'] == 'SHORT']
    neutrals = [s for s in signals if s['signal'] == 'NEUTRAL']
    no_data = [s for s in signals if s['signal'] == 'NO DATA']

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("LONG", len(longs), help="Credits with positive signals")
    with col2:
        st.metric("SHORT", len(shorts), help="Credits with negative signals")
    with col3:
        st.metric("NEUTRAL", len(neutrals), help="Credits with mixed signals")
    with col4:
        st.metric("NO DATA", len(no_data), help="Credits without snapshot data")

    st.markdown("---")

    # Top Longs
    st.markdown("#### Top Long Ideas")
    if longs:
        for sig in longs[:5]:
            with st.expander(f"**{sig['company']}** ({sig['sector']}) - Score: {sig['score']}"):
                for reason in sig['rationale']:
                    st.markdown(f"- {reason}")
    else:
        st.info("No strong long signals currently")

    # Top Shorts
    st.markdown("#### Top Short Ideas")
    if shorts:
        for sig in shorts[:5]:
            with st.expander(f"**{sig['company']}** ({sig['sector']}) - Score: {sig['score']}"):
                for reason in sig['rationale']:
                    st.markdown(f"- {reason}")
    else:
        st.info("No strong short signals currently")

    # Full signal table
    st.markdown("---")
    st.markdown("#### All Signals")

    df_signals = pd.DataFrame([
        {
            'Company': s['company'],
            'Sector': s['sector'],
            'Signal': s['signal'],
            'Score': s['score'],
            'Data': 'Yes' if s['has_snapshot'] else 'No'
        }
        for s in signals
    ])

    # Color code by signal
    def color_signal(val):
        if val == 'LONG':
            return 'background-color: #c6efce; color: #006100'
        elif val == 'SHORT':
            return 'background-color: #ffc7ce; color: #9c0006'
        elif val == 'NO DATA':
            return 'background-color: #ffeb9c; color: #9c5700'
        return ''

    st.dataframe(
        df_signals.style.applymap(color_signal, subset=['Signal']),
        hide_index=True,
        use_container_width=True
    )


# ============== STREAMLIT DASHBOARD ==============

st.set_page_config(page_title="Trading Analysis Tool", layout="wide")
st.title("Trading Analysis Tool")

# Get available indices
available_indices = get_available_indices()

if not available_indices:
    st.error("No index configuration files found in /indices folder")
    st.stop()

# Sidebar - Index selector
selected_index = st.sidebar.selectbox(
    "Select Index",
    available_indices,
    format_func=lambda x: x.replace("_", " ").upper()
)

# Load selected index
index_data = load_index(f"{selected_index}.json")
st.sidebar.markdown(f"**{index_data['name']}**")
st.sidebar.markdown(f"Names: {index_data['total_names']}")

# Sidebar stats
st.sidebar.markdown("---")
st.sidebar.markdown("### Sector Breakdown")
for sector, names in index_data["sectors"].items():
    st.sidebar.markdown(f"- {sector}: {len(names)} names")

# Available snapshots
available_snapshots = get_available_snapshots()
if available_snapshots:
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"### Credit Snapshots: {len(available_snapshots)}")

# System status
st.sidebar.markdown("---")
st.sidebar.markdown("### System Status")
st.sidebar.markdown("**Data Sources:**")
st.sidebar.markdown("- X/Twitter API")
st.sidebar.markdown("- RSS Feeds (10+ sources)")
if NEWSAPI_KEY:
    st.sidebar.markdown("- NewsAPI")
if DB_AVAILABLE:
    st.sidebar.markdown("- PostgreSQL Database")
if TEARSHEET_AVAILABLE:
    st.sidebar.markdown("- Tear Sheet Generator")
if EQUITY_MONITOR_AVAILABLE:
    st.sidebar.markdown("- Equity Monitor (yfinance)" if YFINANCE_AVAILABLE else "- Equity Monitor (no yfinance)")
if KNOWLEDGE_BASE_AVAILABLE:
    st.sidebar.markdown("- PDF Knowledge Base")
if CREDIT_EVENTS_AVAILABLE:
    st.sidebar.markdown("- Credit Events Monitor")
if CREDIT_TWITTER_AVAILABLE:
    st.sidebar.markdown("- Credit Twitter Feed")

# Telegram test button
st.sidebar.markdown("---")
st.sidebar.markdown("### Telegram Alerts")
if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    st.sidebar.markdown("✅ Configured")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🔔 Test", key="test_tg"):
            if send_telegram_message("✅ *XO S44 Monitor Connected!*\n\nTelegram alerts are working."):
                st.sidebar.success("Sent!")
            else:
                st.sidebar.error("Failed")
    with col2:
        if MORNING_BRIEF_AVAILABLE:
            if st.button("☀️ Brief", key="send_brief"):
                if send_morning_brief():
                    st.sidebar.success("Sent!")
                else:
                    st.sidebar.error("Failed")
else:
    st.sidebar.markdown("❌ Not configured")

# Start morning brief scheduler (7am UK daily)
if MORNING_BRIEF_AVAILABLE and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    @st.cache_resource
    def init_morning_scheduler():
        start_scheduler()
        return True
    init_morning_scheduler()

# Main content tabs
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs(["Trading Signals", "Equity Monitor", "Credit Events", "News Monitor", "RSS & News", "Credit Snapshot", "Knowledge Base", "Trading Tools", "Credit Twitter"])

# Initialize NewsHound with selected index
@st.cache_resource
def get_hound(index_name):
    index_data = load_index(f"{index_name}.json")
    hound = NewsHound(index_data)
    Thread(target=hound.constant_scour, daemon=True).start()
    return hound

hound = get_hound(selected_index)

with tab1:
    st.markdown("### Trading Signals Dashboard")
    st.caption("Long/Short signal generation based on fundamentals + news")

    if st.button("Refresh Signals"):
        st.cache_data.clear()

    # Calculate signals for all companies
    with st.spinner("Analyzing all credits..."):
        signals = get_all_signals(index_data)

    render_trading_signals(signals, hound)

with tab2:
    if EQUITY_MONITOR_AVAILABLE:
        render_equity_dashboard(st)
    else:
        st.warning("Equity Monitor not available. Check monitors/ module.")
        st.info("Install yfinance for live prices: `pip install yfinance`")

with tab3:
    if CREDIT_EVENTS_AVAILABLE:
        render_credit_events_dashboard(st)
    else:
        st.warning("Credit Events Monitor not available.")
        st.info("Check monitors/credit_events_monitor.py")

with tab4:
    st.markdown("### X/Twitter Monitor (News)")

    # Sector selector
    sectors = list(index_data["sectors"].keys())
    selected_sector = st.selectbox("Select Sector", sectors, key="news_sector")

    # Company selector
    companies = index_data["sectors"][selected_sector]
    selected_company = st.selectbox("Select Company", companies, key="news_company")

    # Display alerts
    st.subheader(f"{selected_company}")
    st.caption(f"Sector: {selected_sector}")

    alerts = hound.alerts.get(selected_company, [])
    if not alerts:
        st.info("Scanning... (may take a few minutes on first load)")
    else:
        for alert in alerts[-5:]:
            if isinstance(alert, dict):
                impact = alert.get('impact', '')
                text = f"**{alert.get('source')}** ({alert.get('date')}) | {alert.get('likes', 0)} likes\n\n{alert.get('text')}\n\n*{impact}*"
                if alert.get('link'):
                    text += f"\n\n[Link]({alert.get('link')})"

                if "NEGATIVE" in impact or "HIGH RISK" in impact:
                    st.error(text)
                elif "POSITIVE" in impact:
                    st.success(text)
                else:
                    st.info(text)
            else:
                st.info(str(alert))

with tab5:
    st.markdown("### RSS Feeds & NewsAPI")
    st.caption("Trade journals, local newspapers, and news aggregators")

    # Sector selector
    sectors2 = list(index_data["sectors"].keys())
    selected_sector2 = st.selectbox("Select Sector", sectors2, key="rss_sector")

    # Company selector
    companies2 = index_data["sectors"][selected_sector2]
    selected_company2 = st.selectbox("Select Company", companies2, key="rss_company")

    st.subheader(f"{selected_company2}")

    # Manual refresh button
    if st.button("Refresh News"):
        with st.spinner("Fetching news from RSS feeds and NewsAPI..."):
            hound.scour_rss(selected_company2, selected_sector2)

    # Display RSS alerts
    rss_alerts = hound.rss_alerts.get(selected_company2, [])

    if not rss_alerts:
        st.info("No recent news found. Click 'Refresh News' to search, or news will load automatically during background scan.")
    else:
        for article in rss_alerts:
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**[{article['title']}]({article['link']})**")
                    st.caption(f"{article.get('feed_name', 'Unknown')} | {article.get('region', 'Global')} | {article['published'].strftime('%Y-%m-%d %H:%M') if hasattr(article['published'], 'strftime') else article['published']}")
                    if article.get('summary'):
                        st.markdown(article['summary'] + "...")
                st.markdown("---")

with tab6:
    st.markdown("### Credit Snapshot")

    # Get all companies across sectors
    all_companies = []
    for sector, names in index_data["sectors"].items():
        all_companies.extend(names)
    all_companies = sorted(all_companies)

    selected_snapshot_company = st.selectbox(
        "Select Company",
        all_companies,
        key="snapshot_company"
    )

    # Load and display snapshot
    snapshot = load_snapshot(selected_snapshot_company)
    render_snapshot(snapshot)

with tab7:
    if KNOWLEDGE_BASE_AVAILABLE:
        # Initialize knowledge base
        @st.cache_resource
        def get_knowledge_base():
            return KnowledgeBase()

        kb = get_knowledge_base()
        render_knowledge_base_ui(st, kb)
    else:
        st.warning("Knowledge Base not available.")
        st.info("Install pypdf to enable: `pip install pypdf`")

with tab8:
    if TRADING_TOOLS_AVAILABLE:
        render_trading_tools()
    else:
        st.warning("Trading Tools not available.")
        st.info("Check monitors/trading_tools.py")

with tab9:
    if CREDIT_TWITTER_AVAILABLE:
        render_credit_twitter()
    else:
        st.warning("Credit Twitter not available.")
        st.info("Check monitors/credit_twitter.py")

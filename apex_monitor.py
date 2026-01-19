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

# Load secrets from Streamlit Cloud or environment variables (for local dev)
TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))
TWITTER_BEARER_TOKEN = st.secrets.get("TWITTER_BEARER_TOKEN", os.environ.get("TWITTER_BEARER_TOKEN", ""))
NEWSAPI_KEY = st.secrets.get("NEWSAPI_KEY", os.environ.get("NEWSAPI_KEY", ""))

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

def load_news_sources():
    """Load RSS feed configurations"""
    config_path = Path(__file__).parent / "config" / "news_sources.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"rss_feeds": {}, "newsapi_keywords": {}}

def load_snapshot(company_name):
    """Load credit snapshot for a company if available"""
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
        self.index_data = index_data
        self.aliases = index_data.get("search_aliases", {})
        self.news_sources = load_news_sources()
        print(f"=== Apex Credit Monitor Started ===")
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
            if tweets.data:
                for tweet in tweets.data:
                    impact = self.spot_pattern(name, tweet.text, sector)
                    likes = tweet.public_metrics.get('like_count', 0)
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
        st.metric("FCF/Debt", f"{ratios.get('fcf_to_debt', 'N/A'):.1%}" if ratios.get('fcf_to_debt') else "N/A")

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


# ============== STREAMLIT DASHBOARD ==============

st.set_page_config(page_title="Apex Credit Monitor", layout="wide")
st.title("Apex Credit Monitor")

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

# News sources status
st.sidebar.markdown("---")
st.sidebar.markdown("### News Sources")
st.sidebar.markdown("- X/Twitter API")
st.sidebar.markdown("- RSS Feeds (10+ sources)")
if NEWSAPI_KEY:
    st.sidebar.markdown("- NewsAPI")
else:
    st.sidebar.caption("Add NEWSAPI_KEY for more coverage")

# Main content tabs
tab1, tab2, tab3 = st.tabs(["News Monitor", "RSS & News", "Credit Snapshot"])

# Initialize NewsHound with selected index
@st.cache_resource
def get_hound(index_name):
    index_data = load_index(f"{index_name}.json")
    hound = NewsHound(index_data)
    Thread(target=hound.constant_scour, daemon=True).start()
    return hound

hound = get_hound(selected_index)

with tab1:
    st.markdown("### X/Twitter Monitor")

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

with tab2:
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

with tab3:
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

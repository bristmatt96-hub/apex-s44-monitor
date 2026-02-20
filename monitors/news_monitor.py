"""
News Monitor — Credit Catalyst Continuous Learning

Scrapes Google News RSS for each iTraxx Crossover S44 name, classifies
articles via Claude API (credit impact, severity 1-5, novelty), and stores
results in data/news_history.db (SQLite).

When severity >= 3 is detected the signal change is logged to
outputs/signal_changes.txt.  With --auto-assess, a full analyst
re-assessment is triggered for that name.

Usage:
    python -m monitors.news_monitor                              # Scan all 75 names
    python -m monitors.news_monitor --entity "INEOS Finance PLC" # Single name
    python -m monitors.news_monitor --check-changes              # Recent signal changes
    python -m monitors.news_monitor --status                     # Recent news from DB
    python -m monitors.news_monitor --stats                      # Summary statistics
    python -m monitors.news_monitor --demo                       # Mock data (no scrape)
    python -m monitors.news_monitor --auto-assess                # Re-assess on sev >= 3
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

import requests
import feedparser

from dotenv import load_dotenv

load_dotenv(override=True)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path("data/news_history.db")
UNIVERSE_PATH = Path("indices/xover_s44.json")
SIGNAL_CHANGES_PATH = Path("outputs/signal_changes.txt")
MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1024

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?"
    "q={query}+credit+debt&hl=en&gl=GB&ceid=GB:en"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Legal suffixes stripped for search-query building
LEGAL_SUFFIXES = [
    "plc", "ltd", "limited", "gmbh", "ag", "s.a.", "sa", "b.v.", "bv",
    "s.p.a.", "spa", "ab", "se", "nv", "oyj", "sarl", "sas", "saca",
    "dac", "co", "corp", "inc", "finance", "financing", "holdco",
    "holdings", "holding", "group", "international", "europe", "european",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class NewsArticle:
    """A classified news article."""
    article_id: str          # SHA256(source|entity|date|title)[:16]
    entity_name: str
    title: str
    source: str              # Publisher
    url: str
    published_date: str      # ISO date
    summary: str
    credit_impact: str       # positive, negative, neutral
    severity: int            # 1-5
    is_new_info: bool
    claim_summary: str
    credit_relevance: str
    sector: str = ""
    classified_at: str = ""


# ---------------------------------------------------------------------------
# Universe loading & name helpers
# (same pattern as rating_actions.py)
# ---------------------------------------------------------------------------

def load_universe() -> dict:
    """Load xover_s44.json."""
    if not UNIVERSE_PATH.exists():
        return {}
    with open(UNIVERSE_PATH) as f:
        return json.load(f)


def all_entity_names(universe: dict) -> list[str]:
    """Flat list of all 75 entity names."""
    names: list[str] = []
    for sector_names in universe.get("sectors", {}).values():
        names.extend(sector_names)
    return names


def get_sector(entity: str, universe: dict) -> str:
    for sector, names in universe.get("sectors", {}).items():
        if entity in names:
            return sector
    return ""


def build_search_query(entity_name: str, universe: dict) -> str:
    """Pick the best short search term for Google News RSS.

    Prefers search_aliases from xover_s44.json, then falls back to the
    first meaningful word of the legal name.
    """
    aliases = universe.get("search_aliases", {}).get(entity_name, [])
    if aliases:
        return aliases[0]

    noise = set(LEGAL_SUFFIXES)
    for word in entity_name.split():
        clean = word.strip(".,()").lower()
        if len(clean) >= 4 and clean not in noise:
            return word
    return entity_name.split()[0]


# ---------------------------------------------------------------------------
# Google News RSS
# ---------------------------------------------------------------------------

def fetch_news_rss(entity_name: str, query: str) -> list[dict]:
    """Fetch Google News RSS for *query* and return raw entries."""
    url = GOOGLE_NEWS_RSS.format(query=query.replace(" ", "+"))
    entries: list[dict] = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"    WARNING: Google News returned {resp.status_code} "
                  f"for {entity_name}")
            return []

        feed = feedparser.parse(resp.text)
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            link = entry.get("link", "")
            published = entry.get("published", "")
            source_name = ""
            if hasattr(entry, "source") and isinstance(entry.source, dict):
                source_name = entry.source.get("title", "")
            elif hasattr(entry, "source"):
                source_name = getattr(entry.source, "title", "")

            # Parse date (same pattern as rating_actions.py)
            date_str = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                date_str = time.strftime("%Y-%m-%d", entry.published_parsed)
            elif published:
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%a, %d %b %Y %H:%M:%S"):
                    try:
                        dt = datetime.strptime(published[:19], fmt)
                        date_str = dt.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
                if not date_str:
                    date_str = datetime.now().strftime("%Y-%m-%d")

            entries.append({
                "title": title,
                "summary": summary,
                "link": link,
                "date": date_str,
                "source": source_name or "Unknown",
                "entity_name": entity_name,
            })

    except requests.RequestException as e:
        print(f"    WARNING: News fetch failed for {entity_name}: {e}")
    except Exception as e:
        print(f"    WARNING: News parse error for {entity_name}: {e}")

    return entries


# ---------------------------------------------------------------------------
# Claude classification
# ---------------------------------------------------------------------------

CLASSIFICATION_SYSTEM = """You are a credit analyst classifying news articles about European high-yield corporate credits.
You focus on the iTraxx Crossover (Xover) universe of 75 names.

For each article, assess:
1. CREDIT IMPACT: Is this positive (spread tightening), negative (spread widening), or neutral for the company's CDS?
2. SEVERITY (1-5):
   1 = noise/generic corporate news with no credit relevance
   2 = minor colour, confirms known narrative
   3 = meaningful data point, could move spreads 5-10bp
   4 = material information, likely to move spreads 10-25bp
   5 = critical/breaking, could move spreads 25bp+ (restructuring, default, major M&A)
3. NOVELTY: Is this genuinely new information or rehashing known facts?
4. CLAIM SUMMARY: One-sentence summary of the key development
5. CREDIT RELEVANCE: Why does this matter for CDS spreads specifically?

Respond in strict JSON format:
{
    "credit_impact": "positive" | "negative" | "neutral",
    "severity": 1-5,
    "is_new_info": true | false,
    "claim_summary": "...",
    "credit_relevance": "..."
}"""


def classify_article(
    entity_name: str,
    title: str,
    summary: str,
) -> dict | None:
    """Classify a news article via Claude.  Returns dict or None on failure."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("  Warning: ANTHROPIC_API_KEY not set, skipping classification",
              file=sys.stderr)
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        user_msg = (
            f"Entity: {entity_name}\n"
            f"Headline: {title}\n"
            f"\nArticle snippet:\n{summary[:500]}"
        )

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=CLASSIFICATION_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        print(f"  JSON parse error classifying article: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Classification error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Demo mode — mock data for testing
# ---------------------------------------------------------------------------

DEMO_ARTICLES = [
    {
        "title": "INEOS Group explores sale of composites division to reduce debt pile",
        "summary": (
            "INEOS Group, controlled by billionaire Jim Ratcliffe, is in "
            "advanced talks to sell its composites division for up to EUR "
            "500m. Proceeds would be used to pay down senior secured debt."
        ),
        "link": "https://news.google.com/articles/demo001",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "Financial Times",
        "entity_name": "INEOS Finance PLC",
    },
    {
        "title": "Worldline revenue misses estimates as payment volumes decline",
        "summary": (
            "Worldline SA reported Q4 revenue 4% below consensus as "
            "merchant acquiring volumes fell across Southern Europe. "
            "Management cut 2026 guidance, sending bonds lower."
        ),
        "link": "https://news.google.com/articles/demo002",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "Bloomberg",
        "entity_name": "Worldline SA/France",
    },
    {
        "title": "SBB secures EUR 800m refinancing with consortium of Nordic banks",
        "summary": (
            "Samhallsbyggnadsbolaget i Norden AB has closed an EUR 800m "
            "secured refinancing, extending its maturity wall to 2029. "
            "The deal removes near-term liquidity concerns."
        ),
        "link": "https://news.google.com/articles/demo003",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "Reuters",
        "entity_name": "Samhallsbyggnadsbolaget i Norden AB",
    },
    {
        "title": "CMA CGM reports record container shipping profits in Q4",
        "summary": (
            "CMA CGM SA posted record EBITDA of EUR 4.2bn for Q4 2025, "
            "benefiting from Red Sea diversions and strong trans-Pacific "
            "rates. Net leverage fell to 0.8x."
        ),
        "link": "https://news.google.com/articles/demo004",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "Financial Times",
        "entity_name": "CMA CGM SA",
    },
    {
        "title": "Spanish regulator proposes new online gambling tax hitting Cirsa margins",
        "summary": (
            "Spain's gambling regulator has proposed a 15% gross gaming "
            "revenue tax on online operations. Analysts estimate this "
            "could reduce Cirsa's EBITDA by 8-12% from 2027."
        ),
        "link": "https://news.google.com/articles/demo005",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "Expansion",
        "entity_name": "Cirsa Finance International Sarl",
    },
    {
        "title": "Kaixo Bondco (MasMovil) accelerates deleveraging, targets sub-4x by mid-2026",
        "summary": (
            "MasMovil parent Kaixo Bondco has reported strong Q4 subscriber "
            "growth and raised its deleveraging target to below 4x net "
            "debt/EBITDA by mid-2026, up from end-2026 previously."
        ),
        "link": "https://news.google.com/articles/demo006",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "CincoDias",
        "entity_name": "Kaixo Bondco Telecom SA",
    },
    {
        "title": "Jaguar Land Rover sees strong Range Rover demand lift Q3 margins",
        "summary": (
            "JLR reported Q3 EBIT margins of 9.2%, ahead of consensus, "
            "driven by Range Rover mix and cost savings. Free cash flow "
            "of GBP 600m enables further debt reduction."
        ),
        "link": "https://news.google.com/articles/demo007",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "Reuters",
        "entity_name": "Jaguar Land Rover Automotive PLC",
    },
    {
        "title": "Syngenta faces headwinds as Chinese ownership scrutiny intensifies",
        "summary": (
            "US and EU regulators have stepped up scrutiny of Syngenta AG's "
            "Chinese state ownership, potentially restricting some product "
            "approvals. Leverage remains above 5x."
        ),
        "link": "https://news.google.com/articles/demo008",
        "date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "source": "Bloomberg",
        "entity_name": "Syngenta AG",
    },
    {
        "title": "INEOS Quattro maturity wall looms as EUR 1.8bn term loans near 2027 deadline",
        "summary": (
            "Credit analysts flag growing refinancing risk for INEOS "
            "Quattro Finance 2 Plc with EUR 1.8bn of term loans due 2027 "
            "still unaddressed. CDS spreads widen to multi-year highs."
        ),
        "link": "https://news.google.com/articles/demo009",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "Debtwire",
        "entity_name": "INEOS Quattro Finance 2 Plc",
    },
    {
        "title": "TUI AG summer bookings up 12% year-on-year, upgrades outlook",
        "summary": (
            "TUI AG reported summer 2026 bookings 12% ahead of prior year "
            "with average selling prices up 5%. Management upgraded full-year "
            "EBITDA guidance by EUR 100m."
        ),
        "link": "https://news.google.com/articles/demo010",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "Handelsblatt",
        "entity_name": "TUI AG",
    },
]

# Pre-classified demo results (so demo mode works without ANTHROPIC_API_KEY)
DEMO_CLASSIFICATIONS = {
    "INEOS Finance PLC": {
        "credit_impact": "positive", "severity": 4, "is_new_info": True,
        "claim_summary": "INEOS exploring composites division sale for EUR 500m to reduce debt",
        "credit_relevance": "Asset disposal proceeds for debt paydown would reduce leverage and improve credit metrics",
    },
    "Worldline SA/France": {
        "credit_impact": "negative", "severity": 4, "is_new_info": True,
        "claim_summary": "Worldline Q4 revenue 4% below consensus, guidance cut",
        "credit_relevance": "Revenue miss and guidance cut increase leverage risk and reduce deleveraging capacity",
    },
    "Samhallsbyggnadsbolaget i Norden AB": {
        "credit_impact": "positive", "severity": 5, "is_new_info": True,
        "claim_summary": "SBB closes EUR 800m secured refinancing extending maturities to 2029",
        "credit_relevance": "Removes near-term liquidity overhang that was key driver of wide CDS spreads",
    },
    "CMA CGM SA": {
        "credit_impact": "positive", "severity": 3, "is_new_info": True,
        "claim_summary": "CMA CGM Q4 EBITDA record of EUR 4.2bn, leverage at 0.8x",
        "credit_relevance": "Sub-1x leverage is exceptional for BB-rated; supports further spread tightening",
    },
    "Cirsa Finance International Sarl": {
        "credit_impact": "negative", "severity": 3, "is_new_info": True,
        "claim_summary": "Spanish regulator proposes new online gambling tax reducing Cirsa EBITDA by 8-12%",
        "credit_relevance": "Margin compression from regulatory tax change would increase leverage and weaken coverage ratios",
    },
    "Kaixo Bondco Telecom SA": {
        "credit_impact": "positive", "severity": 3, "is_new_info": True,
        "claim_summary": "MasMovil accelerates deleveraging target to sub-4x by mid-2026",
        "credit_relevance": "Faster deleveraging supports rising star potential and spread compression",
    },
    "Jaguar Land Rover Automotive PLC": {
        "credit_impact": "positive", "severity": 3, "is_new_info": True,
        "claim_summary": "JLR Q3 EBIT margins beat at 9.2% with GBP 600m FCF enabling debt reduction",
        "credit_relevance": "Strong FCF generation and margin improvement support deleveraging trajectory",
    },
    "Syngenta AG": {
        "credit_impact": "negative", "severity": 3, "is_new_info": True,
        "claim_summary": "Increased regulatory scrutiny of Syngenta's Chinese ownership could restrict product approvals",
        "credit_relevance": "Ownership uncertainty adds tail risk; leverage above 5x provides limited cushion",
    },
    "INEOS Quattro Finance 2 Plc": {
        "credit_impact": "negative", "severity": 4, "is_new_info": False,
        "claim_summary": "INEOS Quattro EUR 1.8bn 2027 maturity wall still unaddressed, CDS at multi-year wides",
        "credit_relevance": "Unresolved refinancing risk for near-term maturities is the primary spread driver",
    },
    "TUI AG": {
        "credit_impact": "positive", "severity": 3, "is_new_info": True,
        "claim_summary": "TUI summer bookings up 12% YoY with upgraded EBITDA guidance",
        "credit_relevance": "Demand strength and guidance upgrade support credit improvement trajectory",
    },
}


# ---------------------------------------------------------------------------
# SQLite database
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    """Initialise the news history database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_articles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id      TEXT UNIQUE NOT NULL,
            entity_name     TEXT NOT NULL,
            title           TEXT NOT NULL,
            source          TEXT DEFAULT '',
            url             TEXT DEFAULT '',
            published_date  TEXT,
            summary         TEXT DEFAULT '',
            credit_impact   TEXT DEFAULT 'neutral',
            severity        INTEGER DEFAULT 0,
            is_new_info     INTEGER DEFAULT 0,
            claim_summary   TEXT DEFAULT '',
            credit_relevance TEXT DEFAULT '',
            sector          TEXT DEFAULT '',
            classified_at   TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_entity "
                 "ON news_articles(entity_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_date "
                 "ON news_articles(published_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_severity "
                 "ON news_articles(severity)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_impact "
                 "ON news_articles(credit_impact)")
    conn.commit()
    return conn


def article_exists(conn: sqlite3.Connection, article_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM news_articles WHERE article_id = ?", (article_id,)
    )
    return cur.fetchone() is not None


def store_article(conn: sqlite3.Connection, article: NewsArticle) -> bool:
    """Store a news article.  Returns True if new (not duplicate)."""
    if article_exists(conn, article.article_id):
        return False
    conn.execute("""
        INSERT INTO news_articles
            (article_id, entity_name, title, source, url, published_date,
             summary, credit_impact, severity, is_new_info,
             claim_summary, credit_relevance, sector, classified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        article.article_id, article.entity_name, article.title,
        article.source, article.url, article.published_date,
        article.summary, article.credit_impact, article.severity,
        int(article.is_new_info), article.claim_summary,
        article.credit_relevance, article.sector, article.classified_at,
    ))
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Signal changes & auto-reassessment
# ---------------------------------------------------------------------------

def log_signal_change(article: NewsArticle) -> None:
    """Append a signal change to outputs/signal_changes.txt."""
    SIGNAL_CHANGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"[{timestamp}] {article.entity_name} | "
        f"impact={article.credit_impact} | sev={article.severity}/5 | "
        f"source={article.source} | "
        f"{article.claim_summary}\n"
    )
    with open(SIGNAL_CHANGES_PATH, "a") as f:
        f.write(line)


def trigger_reassessment(entity_name: str) -> None:
    """Auto-trigger analyst re-assessment for a high-severity entity."""
    try:
        from agents.analyst import assess_credit

        print(f"\n  AUTO-REASSESS: Triggering analyst for {entity_name}...")
        assessment = assess_credit(entity_name, "Xover")
        print(f"  -> {assessment.direction.value} | "
              f"conviction={assessment.conviction}/5 | "
              f"spread={assessment.current_spread:.0f} -> "
              f"fair={assessment.fair_spread:.0f}")

        # Log the reassessment
        SIGNAL_CHANGES_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(SIGNAL_CHANGES_PATH, "a") as f:
            f.write(
                f"[{timestamp}] REASSESSMENT: {entity_name} | "
                f"direction={assessment.direction.value} | "
                f"conviction={assessment.conviction}/5 | "
                f"fair_spread={assessment.fair_spread:.0f}bps\n"
            )

    except Exception as e:
        print(f"  Warning: Auto-reassessment failed for {entity_name}: {e}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_scan(
    entity_filter: str | None = None,
    demo: bool = False,
    auto_assess: bool = False,
) -> list[NewsArticle]:
    """Run the full news monitoring scan.

    Args:
        entity_filter: Partial entity name to filter (case-insensitive).
        demo: Use mock data instead of live scraping.
        auto_assess: Trigger analyst re-assessment for severity >= 3.
    """
    universe = load_universe()
    conn = init_db()

    # Determine entities to scan
    names = all_entity_names(universe)
    if entity_filter:
        entities = [n for n in names if entity_filter.lower() in n.lower()]
        if not entities:
            print(f"  No entity matching '{entity_filter}' in universe")
            conn.close()
            return []
    else:
        entities = names

    print(f"  Scanning news for {len(entities)} entities...")

    all_entries: list[dict] = []

    if demo:
        print("  Running in DEMO mode (mock news articles)...")
        if entity_filter:
            fl = entity_filter.lower()
            all_entries = [a for a in DEMO_ARTICLES
                          if fl in a["entity_name"].lower()]
        else:
            all_entries = list(DEMO_ARTICLES)
    else:
        for entity in entities:
            query = build_search_query(entity, universe)
            entries = fetch_news_rss(entity, query)
            all_entries.extend(entries)
            if entries:
                print(f"    {entity[:35]:<35} {len(entries):>3} articles")
            time.sleep(0.5)  # Rate-limit Google News

    print(f"\n  Processing {len(all_entries)} articles...")

    new_articles: list[NewsArticle] = []
    reassessed: set[str] = set()

    for entry in all_entries:
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        entity_name = entry["entity_name"]

        # Dedup ID
        id_str = (f"{entry.get('source', '')}|{entity_name}"
                  f"|{entry['date']}|{title}")
        article_id = sha256(id_str.encode()).hexdigest()[:16]

        if article_exists(conn, article_id):
            continue

        # Classify — use pre-computed results in demo mode
        if demo:
            result = DEMO_CLASSIFICATIONS.get(entity_name)
            if not result:
                continue
        else:
            result = classify_article(entity_name, title, summary)
            if not result:
                continue

        sector = get_sector(entity_name, universe)

        article = NewsArticle(
            article_id=article_id,
            entity_name=entity_name,
            title=title,
            source=entry.get("source", ""),
            url=entry.get("link", ""),
            published_date=entry["date"],
            summary=summary[:500],
            credit_impact=result.get("credit_impact", "neutral"),
            severity=int(result.get("severity", 1)),
            is_new_info=bool(result.get("is_new_info", False)),
            claim_summary=result.get("claim_summary", ""),
            credit_relevance=result.get("credit_relevance", ""),
            sector=sector,
            classified_at=datetime.now().isoformat(),
        )

        is_new = store_article(conn, article)
        if is_new:
            new_articles.append(article)

            # Update entity profile
            try:
                from data.entity_profile_manager import update_profile
                update_profile(entity_name, "news", {
                    "article_id": article.article_id,
                    "title": article.title,
                    "source": article.source,
                    "published_date": article.published_date,
                    "credit_impact": article.credit_impact,
                    "severity": article.severity,
                    "is_new_info": article.is_new_info,
                    "claim_summary": article.claim_summary,
                    "credit_relevance": article.credit_relevance,
                })
            except Exception:
                pass

            # Log signal change for severity >= 3
            if article.severity >= 3:
                log_signal_change(article)

            # Auto-reassess (once per entity per scan)
            if (article.severity >= 3
                    and auto_assess
                    and entity_name not in reassessed):
                trigger_reassessment(entity_name)
                reassessed.add(entity_name)

        # Rate-limit between Claude calls (skip in demo)
        if not demo:
            time.sleep(0.3)

    conn.close()
    return new_articles


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def print_articles(articles: list[NewsArticle]) -> None:
    """Print new articles to terminal."""
    if not articles:
        print("  No new news articles found.")
        return

    W = 72
    print()
    print("  NEW NEWS ARTICLES")
    print("  " + "=" * (W - 2))

    for a in sorted(articles, key=lambda x: -x.severity):
        sev_stars = "*" * a.severity
        impact_tag = {
            "negative": "\033[91m[-]\033[0m",
            "positive": "\033[92m[+]\033[0m",
            "neutral": "[=]",
        }.get(a.credit_impact, "[?]")

        print()
        print(f"  {impact_tag} {a.entity_name}")
        print(f"     {a.source}  |  sev={a.severity}/5 {sev_stars}"
              f"  |  new_info={'Y' if a.is_new_info else 'N'}")
        print(f"     {a.title[:68]}")
        print(f"     {a.claim_summary[:68]}")
        print(f"     Date: {a.published_date}  |  Sector: {a.sector}")

    print()
    print(f"  Total: {len(articles)} new articles")
    neg = sum(1 for a in articles if a.credit_impact == "negative")
    pos = sum(1 for a in articles if a.credit_impact == "positive")
    high = sum(1 for a in articles if a.severity >= 3)
    print(f"  Negative: {neg}  |  Positive: {pos}  |  Severity >= 3: {high}")
    print("  " + "=" * (W - 2))


def show_recent(days: int = 7, entity_filter: str | None = None) -> None:
    """Show recent news from the database."""
    if not DB_PATH.exists():
        print("  No news history database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    if entity_filter:
        rows = conn.execute(
            """SELECT * FROM news_articles
               WHERE published_date >= ? AND entity_name LIKE ?
               ORDER BY published_date DESC, severity DESC""",
            (cutoff, f"%{entity_filter}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM news_articles
               WHERE published_date >= ?
               ORDER BY published_date DESC, severity DESC""",
            (cutoff,),
        ).fetchall()

    conn.close()

    if not rows:
        print(f"  No news in the last {days} days.")
        return

    W = 72
    print()
    print(f"  NEWS HISTORY — Last {days} Days ({len(rows)} total)")
    print("  " + "=" * (W - 2))

    for r in rows:
        impact = {"negative": "[-]", "positive": "[+]",
                  "neutral": "[=]"}.get(r["credit_impact"], "[?]")
        print(f"\n  {impact} {r['entity_name']}  ({r['source']})")
        print(f"     sev={r['severity']}/5  |  {r['published_date']}")
        print(f"     {r['title'][:65]}")
        if r["claim_summary"]:
            print(f"     {r['claim_summary'][:65]}")

    print()


def show_stats() -> None:
    """Show summary statistics from the database."""
    if not DB_PATH.exists():
        print("  No news history database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM news_articles"
    ).fetchone()["cnt"]

    by_impact = conn.execute(
        "SELECT credit_impact, COUNT(*) as cnt "
        "FROM news_articles GROUP BY credit_impact ORDER BY cnt DESC"
    ).fetchall()

    by_severity = conn.execute(
        "SELECT severity, COUNT(*) as cnt "
        "FROM news_articles GROUP BY severity ORDER BY severity DESC"
    ).fetchall()

    top_entities = conn.execute(
        "SELECT entity_name, COUNT(*) as cnt "
        "FROM news_articles GROUP BY entity_name "
        "ORDER BY cnt DESC LIMIT 10"
    ).fetchall()

    recent_high = conn.execute(
        """SELECT entity_name, credit_impact, severity, published_date,
                  claim_summary
           FROM news_articles
           WHERE severity >= 3
           ORDER BY published_date DESC LIMIT 5"""
    ).fetchall()

    conn.close()

    W = 60
    print()
    print(f"  NEWS MONITOR — Summary ({total} total articles)")
    print("  " + "=" * W)

    print(f"\n  BY CREDIT IMPACT:")
    for r in by_impact:
        print(f"    {r['credit_impact']:<25} {r['cnt']:>4}")

    print(f"\n  BY SEVERITY:")
    for r in by_severity:
        stars = "*" * r["severity"]
        print(f"    sev={r['severity']} {stars:<6}  {r['cnt']:>4}")

    print(f"\n  TOP ENTITIES:")
    for r in top_entities:
        print(f"    {r['entity_name']:<40} {r['cnt']:>4}")

    if recent_high:
        print(f"\n  RECENT HIGH-SEVERITY:")
        for r in recent_high:
            impact = {"negative": "[-]", "positive": "[+]",
                      "neutral": "[=]"}.get(r["credit_impact"], "[?]")
            print(f"    {impact} {r['entity_name']:<30} "
                  f"sev={r['severity']}  {r['published_date']}")
            if r["claim_summary"]:
                print(f"        {r['claim_summary'][:55]}")

    print()


def show_signal_changes() -> None:
    """Show recent signal changes from the log file."""
    if not SIGNAL_CHANGES_PATH.exists():
        print("  No signal changes logged yet.")
        return

    with open(SIGNAL_CHANGES_PATH) as f:
        lines = f.readlines()

    if not lines:
        print("  Signal changes log is empty.")
        return

    W = 72
    print()
    print(f"  SIGNAL CHANGES LOG ({len(lines)} entries)")
    print("  " + "=" * (W - 2))

    # Show last 20 entries
    for line in lines[-20:]:
        print(f"  {line.rstrip()}")

    if len(lines) > 20:
        print(f"\n  ... showing last 20 of {len(lines)} entries")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Credit Catalyst — News Monitor (Google News RSS)"
    )
    parser.add_argument("--entity", type=str, default=None,
                        help="Scan a specific entity (partial match)")
    parser.add_argument("--status", action="store_true",
                        help="Show recent news from database")
    parser.add_argument("--stats", action="store_true",
                        help="Show news statistics")
    parser.add_argument("--check-changes", action="store_true",
                        help="Show signal changes log")
    parser.add_argument("--days", type=int, default=7,
                        help="Lookback days for --status (default: 7)")
    parser.add_argument("--demo", action="store_true",
                        help="Demo mode with mock data (no scraping)")
    parser.add_argument("--auto-assess", action="store_true",
                        help="Trigger analyst re-assessment for sev >= 3")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.status:
        show_recent(days=args.days, entity_filter=args.entity)
        return

    if args.check_changes:
        show_signal_changes()
        return

    # Run scan
    print()
    print("  CREDIT CATALYST — News Monitor")
    print("  " + "=" * 50)

    new_articles = run_scan(
        entity_filter=args.entity,
        demo=args.demo,
        auto_assess=args.auto_assess,
    )

    print_articles(new_articles)


if __name__ == "__main__":
    main()

"""
RSS Feed Monitor — Comprehensive Financial News Scraper
========================================================
Scrapes 85+ RSS feeds from config/news_sources.json and matches articles
to all 200 iTraxx entities (75 Crossover + 125 Main).

Unlike news_monitor.py (one Google News query per entity), this monitor
flips the model: scrape all feeds once, then match articles to entities
via keyword matching. Far more efficient for 200 names.

Classification uses Chutes (SN64, ~$0.08/scan) by default, with
Anthropic Claude as fallback.

Data sources:
  - 85 RSS feeds across 14 categories (general, sector, local, regulatory)
  - Entity matching via name + search_aliases from universe files
  - Credit-focused keyword boosting for relevance

Database: data/rss_news.db (SQLite)

Usage:
    python -m monitors.rss_monitor                      # Full scan (all feeds, all 200 names)
    python -m monitors.rss_monitor --entity "INEOS"     # Filter to one entity
    python -m monitors.rss_monitor --feeds general_credit,sector_autos  # Specific feed categories
    python -m monitors.rss_monitor --universe xover     # Only Crossover names
    python -m monitors.rss_monitor --universe main      # Only Main names
    python -m monitors.rss_monitor --status             # Recent articles from DB
    python -m monitors.rss_monitor --stats              # Aggregate statistics
    python -m monitors.rss_monitor --dry-run            # Scrape only, no classification

Author: Built with Claude for macro credit trading
"""

import argparse
import io
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Optional

import requests
import feedparser
from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# UTF-8 stdout safety (Windows cp1252 fix)
# ---------------------------------------------------------------------------
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path("data/rss_news.db")
XOVER_PATH = Path("indices/xover_s44.json")
MAIN_PATH = Path("indices/main_s44.json")
FEEDS_PATH = Path("config/news_sources.json")
SIGNAL_CHANGES_PATH = Path("outputs/signal_changes.txt")

# LLM config
CHUTES_BASE_URL = "https://llm.chutes.ai/v1"
CHUTES_CLASSIFY_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507-TEE"
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 512

# RSS scraping
REQUEST_TIMEOUT = 15
FEED_DELAY_SEC = 0.3  # Delay between feeds to be polite
CLASSIFY_DELAY_SEC = 0.2  # Delay between LLM calls

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Credit-relevant keywords that boost matching confidence
CREDIT_KEYWORDS = {
    "bond", "debt", "leverage", "refinancing", "default", "restructuring",
    "downgrade", "upgrade", "covenant", "maturity", "credit", "cds",
    "spread", "yield", "coupon", "rating", "moodys", "moody's", "fitch",
    "s&p", "ebitda", "cashflow", "cash flow", "liquidity", "solvency",
    "bankruptcy", "insolvency", "distressed", "liability management",
    "lme", "tender offer", "exchange offer", "rights issue",
    "profit warning", "guidance cut", "writedown", "impairment",
    "dividend cut", "dividend suspension", "capex", "free cash flow",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RssArticle:
    """A matched and optionally classified RSS article."""
    article_id: str          # SHA256(feed|title|date)[:16]
    entity_name: str         # Matched entity
    index: str               # "xover" or "main"
    title: str
    summary: str
    source_feed: str         # Feed name
    feed_category: str       # e.g. "sector_autos"
    url: str
    published_date: str      # ISO date
    credit_impact: str = "unclassified"  # positive/negative/neutral
    severity: int = 0        # 1-5
    is_new_info: bool = False
    claim_summary: str = ""
    credit_relevance: str = ""
    match_score: float = 0.0  # Keyword match confidence
    sector: str = ""
    classified_at: str = ""


@dataclass
class EntityInfo:
    """Entity with all searchable names."""
    name: str               # Canonical name
    index: str              # "xover" or "main"
    sector: str
    search_terms: list = field(default_factory=list)  # All searchable terms


# ---------------------------------------------------------------------------
# Universe loading
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def load_entities(universe_filter: str = "all") -> list[EntityInfo]:
    """Load all entities from both universes.

    Args:
        universe_filter: "all", "xover", or "main"
    """
    entities = []

    if universe_filter in ("all", "xover"):
        xover = _load_json(XOVER_PATH)
        aliases = xover.get("search_aliases", {})
        for sector, names in xover.get("sectors", {}).items():
            for name in names:
                terms = _build_search_terms(name, aliases.get(name, []))
                entities.append(EntityInfo(
                    name=name, index="xover", sector=sector,
                    search_terms=terms,
                ))

    if universe_filter in ("all", "main"):
        main = _load_json(MAIN_PATH)
        aliases = main.get("search_aliases", {})
        for sector, names in main.get("sectors", {}).items():
            for name in names:
                terms = _build_search_terms(name, aliases.get(name, []))
                entities.append(EntityInfo(
                    name=name, index="main", sector=sector,
                    search_terms=terms,
                ))

    return entities


# Legal suffixes to strip for matching
_LEGAL_SUFFIXES = {
    "plc", "ltd", "limited", "gmbh", "ag", "sa", "bv", "spa", "ab", "se",
    "nv", "oyj", "sarl", "sas", "saca", "dac", "co", "corp", "inc",
    "finance", "financing", "holdco", "holdings", "holding", "group",
    "international", "europe", "european", "global", "midholding",
}

# Common words that cause false positives when used as single-word search terms
_AMBIGUOUS_SINGLE_WORDS = {
    "credit", "national", "standard", "general", "public", "united",
    "royal", "british", "deutsche", "banco", "swiss", "new", "total",
    "imperial", "premier", "atlas", "crown", "motion", "global",
    "land", "power", "orange", "shell", "continental", "virgin",
    "smiths", "smith", "aviva", "sse", "edp", "rwe", "eni", "bp",
    "abb", "skf", "sap", "crh", "wpp", "abf",
}


def _build_search_terms(name: str, aliases: list[str]) -> list[str]:
    """Build list of searchable terms for an entity.

    Returns lowercase terms sorted by length (longest first) to
    prefer more specific matches. Avoids single common words that
    would cause excessive false positives.
    """
    terms = set()

    # Full name
    terms.add(name.lower())

    # Aliases (trusted — manually curated)
    for alias in aliases:
        terms.add(alias.lower())

    # Strip legal suffixes for a short form
    words = name.split()
    meaningful = []
    for w in words:
        clean = w.strip(".,()").lower()
        if clean not in _LEGAL_SUFFIXES and len(clean) >= 2:
            meaningful.append(w)
    if meaningful:
        short = " ".join(meaningful).lower()
        if short != name.lower() and len(short) >= 3:
            terms.add(short)

    # First meaningful word — but ONLY if it's distinctive enough
    # Skip single words that are too common in financial news
    for w in words:
        clean = w.strip(".,()").lower()
        if (len(clean) >= 5
                and clean not in _LEGAL_SUFFIXES
                and clean not in _AMBIGUOUS_SINGLE_WORDS):
            terms.add(clean)
            break

    return sorted(terms, key=len, reverse=True)


# ---------------------------------------------------------------------------
# RSS feed loading
# ---------------------------------------------------------------------------

def load_feed_config() -> dict:
    """Load RSS feed configuration."""
    return _load_json(FEEDS_PATH)


def fetch_feed(feed_url: str, feed_name: str) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of raw entries."""
    entries = []
    try:
        resp = requests.get(feed_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []

        feed = feedparser.parse(resp.text)
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            if not title:
                continue

            summary = entry.get("summary", entry.get("description", "")).strip()
            link = entry.get("link", "")
            published = entry.get("published", "")

            # Parse date
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
                "summary": summary[:500],
                "url": link,
                "date": date_str,
                "feed_name": feed_name,
            })

    except requests.RequestException:
        pass
    except Exception:
        pass

    return entries


def scrape_all_feeds(
    feed_config: dict,
    category_filter: list[str] | None = None,
) -> list[dict]:
    """Scrape all RSS feeds (or filtered categories).

    Returns list of raw article dicts with feed metadata.
    """
    rss_feeds = feed_config.get("rss_feeds", {})
    all_entries = []
    feeds_scraped = 0
    feeds_failed = 0

    for category, feeds in rss_feeds.items():
        if category_filter and category not in category_filter:
            continue

        for feed_info in feeds:
            name = feed_info["name"]
            url = feed_info["url"]

            entries = fetch_feed(url, name)
            for e in entries:
                e["feed_category"] = category
                e["feed_priority"] = feed_info.get("priority", "normal")

            if entries:
                feeds_scraped += 1
                all_entries.extend(entries)
                safe_name = name.encode("ascii", "replace").decode()
                print(f"    {safe_name:<35} {len(entries):>3} articles")
            else:
                feeds_failed += 1

            time.sleep(FEED_DELAY_SEC)

    print(f"\n  Feeds: {feeds_scraped} OK, {feeds_failed} failed/empty")
    print(f"  Raw articles: {len(all_entries)}")
    return all_entries


# ---------------------------------------------------------------------------
# Entity matching
# ---------------------------------------------------------------------------

def match_article_to_entities(
    article: dict,
    entities: list[EntityInfo],
) -> list[tuple[EntityInfo, float]]:
    """Match a raw article to entities.

    Returns list of (entity, score) tuples, sorted by score descending.
    Score components:
      - 1.0: full legal name match in title
      - 0.8: multi-word stripped name match in title
      - 0.7: alias match in title
      - 0.5: full name match in summary
      - 0.4: multi-word stripped name in summary
      - 0.3: alias match in summary
      - +0.2: credit keyword present
    Short single-word terms (< 6 chars) require word-boundary matching
    to avoid false positives.
    """
    title_lower = article["title"].lower()
    summary_lower = article.get("summary", "").lower()
    text_lower = title_lower + " " + summary_lower

    # Check for credit keywords (bonus)
    has_credit_kw = any(kw in text_lower for kw in CREDIT_KEYWORDS)

    matches = []
    for entity in entities:
        best_score = 0.0

        for i, term in enumerate(entity.search_terms):
            # Skip very short terms — high false-positive risk
            if len(term) < 3:
                continue

            # Determine if this is the full name (i==0), a multi-word
            # stripped name, or a single-word/alias
            is_full_name = (i == 0)
            is_multiword = " " in term

            # Use word-boundary matching for short terms (< 6 chars)
            # to prevent "BP" matching "Gbps" or "DNB" matching "CDNB"
            if len(term) <= 5:
                pattern = r'\b' + re.escape(term) + r'\b'
                in_title = bool(re.search(pattern, title_lower))
                in_summary = bool(re.search(pattern, summary_lower))
            else:
                in_title = term in title_lower
                in_summary = term in summary_lower

            if in_title:
                if is_full_name:
                    score = 1.0
                elif is_multiword:
                    score = 0.8
                else:
                    score = 0.7
                best_score = max(best_score, score)
            elif in_summary:
                if is_full_name:
                    score = 0.5
                elif is_multiword:
                    score = 0.4
                else:
                    score = 0.3
                best_score = max(best_score, score)

        if best_score > 0:
            if has_credit_kw:
                best_score += 0.2
            matches.append((entity, best_score))

    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


# ---------------------------------------------------------------------------
# LLM Classification
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = """You are a credit analyst classifying news articles about European corporate credits.
You cover the iTraxx universe: Crossover (75 HY names) and Main (125 IG names).

For each article, assess:
1. CREDIT IMPACT: positive (spread tightening), negative (spread widening), or neutral
2. SEVERITY (1-5):
   1 = noise/generic corporate news
   2 = minor colour, confirms known narrative
   3 = meaningful, could move spreads 5-10bp
   4 = material, likely 10-25bp move
   5 = critical/breaking, 25bp+ (restructuring, default, major M&A)
3. NOVELTY: genuinely new information or rehashing known facts?
4. CLAIM SUMMARY: one-sentence key development
5. CREDIT RELEVANCE: why this matters for CDS spreads

Respond in strict JSON:
{"credit_impact":"positive"|"negative"|"neutral","severity":1-5,"is_new_info":true|false,"claim_summary":"...","credit_relevance":"..."}"""


def classify_article_chutes(
    entity_name: str,
    title: str,
    summary: str,
    index: str,
) -> dict | None:
    """Classify via Chutes (SN64) — cheap."""
    api_key = os.getenv("CHUTES_API_KEY")
    if not api_key:
        return None

    user_msg = (
        f"Entity: {entity_name} (iTraxx {index.capitalize()})\n"
        f"Headline: {title}\n"
        f"Snippet: {summary[:400]}"
    )

    try:
        resp = requests.post(
            f"{CHUTES_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": CHUTES_CLASSIFY_MODEL,
                "messages": [
                    {"role": "system", "content": CLASSIFY_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": MAX_TOKENS,
                "temperature": 0.1,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            return None

        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        # Strip <think> tags from reasoning models
        if "<think>" in raw:
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = raw.strip()

        return json.loads(raw)

    except Exception:
        return None


def classify_article_anthropic(
    entity_name: str,
    title: str,
    summary: str,
    index: str,
) -> dict | None:
    """Classify via Anthropic Claude — fallback."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        user_msg = (
            f"Entity: {entity_name} (iTraxx {index.capitalize()})\n"
            f"Headline: {title}\n"
            f"Snippet: {summary[:400]}"
        )

        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            system=CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        return json.loads(raw)

    except Exception:
        return None


def classify_article(
    entity_name: str,
    title: str,
    summary: str,
    index: str,
) -> dict | None:
    """Classify using configured LLM provider."""
    provider = os.getenv("LLM_PROVIDER", "chutes").lower()

    if provider == "chutes":
        result = classify_article_chutes(entity_name, title, summary, index)
        if result:
            return result
        # Fallback to Anthropic
        return classify_article_anthropic(entity_name, title, summary, index)
    else:
        result = classify_article_anthropic(entity_name, title, summary, index)
        if result:
            return result
        return classify_article_chutes(entity_name, title, summary, index)


# ---------------------------------------------------------------------------
# SQLite database
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    """Initialise the RSS news database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_articles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id      TEXT UNIQUE NOT NULL,
            entity_name     TEXT NOT NULL,
            idx             TEXT DEFAULT '',
            title           TEXT NOT NULL,
            summary         TEXT DEFAULT '',
            source_feed     TEXT DEFAULT '',
            feed_category   TEXT DEFAULT '',
            url             TEXT DEFAULT '',
            published_date  TEXT,
            credit_impact   TEXT DEFAULT 'unclassified',
            severity        INTEGER DEFAULT 0,
            is_new_info     INTEGER DEFAULT 0,
            claim_summary   TEXT DEFAULT '',
            credit_relevance TEXT DEFAULT '',
            match_score     REAL DEFAULT 0.0,
            sector          TEXT DEFAULT '',
            classified_at   TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_entity "
                 "ON rss_articles(entity_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_date "
                 "ON rss_articles(published_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_severity "
                 "ON rss_articles(severity)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_idx "
                 "ON rss_articles(idx)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_category "
                 "ON rss_articles(feed_category)")
    conn.commit()
    return conn


def article_exists(conn: sqlite3.Connection, article_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM rss_articles WHERE article_id = ?", (article_id,)
    )
    return cur.fetchone() is not None


def store_article(conn: sqlite3.Connection, article: RssArticle) -> bool:
    """Store an article. Returns True if new."""
    if article_exists(conn, article.article_id):
        return False
    conn.execute("""
        INSERT INTO rss_articles
            (article_id, entity_name, idx, title, summary, source_feed,
             feed_category, url, published_date, credit_impact, severity,
             is_new_info, claim_summary, credit_relevance, match_score,
             sector, classified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        article.article_id, article.entity_name, article.index,
        article.title, article.summary, article.source_feed,
        article.feed_category, article.url, article.published_date,
        article.credit_impact, article.severity, int(article.is_new_info),
        article.claim_summary, article.credit_relevance,
        article.match_score, article.sector, article.classified_at,
    ))
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Signal change logging
# ---------------------------------------------------------------------------

def log_signal_change(article: RssArticle) -> None:
    """Append a signal change to outputs/signal_changes.txt."""
    SIGNAL_CHANGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_name = article.entity_name.encode("ascii", "replace").decode()
    safe_summary = article.claim_summary.encode("ascii", "replace").decode()
    line = (
        f"[{timestamp}] [RSS] {safe_name} ({article.index}) | "
        f"impact={article.credit_impact} | sev={article.severity}/5 | "
        f"feed={article.source_feed} | "
        f"{safe_summary}\n"
    )
    with open(SIGNAL_CHANGES_PATH, "a") as f:
        f.write(line)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_scan(
    entity_filter: str | None = None,
    universe_filter: str = "all",
    category_filter: list[str] | None = None,
    dry_run: bool = False,
    min_match_score: float = 0.3,
) -> list[RssArticle]:
    """Run the full RSS monitoring scan.

    Args:
        entity_filter: Partial entity name to filter.
        universe_filter: "all", "xover", or "main".
        category_filter: List of feed categories to scrape.
        dry_run: If True, scrape and match but skip classification.
        min_match_score: Minimum score to consider a match.
    """
    # Load entities
    entities = load_entities(universe_filter)
    if entity_filter:
        entities = [e for e in entities
                    if entity_filter.lower() in e.name.lower()]
        if not entities:
            print(f"  No entity matching '{entity_filter}'")
            return []

    print()
    print("=" * 70)
    print("  RSS FEED MONITOR")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    n_xover = sum(1 for e in entities if e.index == "xover")
    n_main = sum(1 for e in entities if e.index == "main")
    print(f"  Universe: {len(entities)} entities "
          f"(Xover={n_xover}, Main={n_main})")

    provider = os.getenv("LLM_PROVIDER", "chutes").lower()
    print(f"  LLM: {'Chutes (SN64)' if provider == 'chutes' else 'Anthropic Claude'}")
    if dry_run:
        print("  Mode: DRY RUN (scrape + match only, no classification)")
    print()

    # Load feed config and scrape
    feed_config = load_feed_config()
    print(f"  Scraping RSS feeds...")
    raw_articles = scrape_all_feeds(feed_config, category_filter)

    if not raw_articles:
        print("  No articles scraped.")
        return []

    # Filter to recent articles (last 7 days)
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [a for a in raw_articles if a.get("date", "") >= cutoff]
    print(f"  Recent (7d): {len(recent)} of {len(raw_articles)}")

    # Match articles to entities
    print(f"\n  Matching articles to {len(entities)} entities...")
    conn = init_db()

    matched_articles: list[RssArticle] = []
    new_articles: list[RssArticle] = []
    duplicates = 0

    for raw in recent:
        matches = match_article_to_entities(raw, entities)
        if not matches:
            continue

        # Take best match (or all above threshold)
        for entity, score in matches:
            if score < min_match_score:
                continue

            # Generate dedup ID
            id_str = (f"{raw['feed_name']}|{entity.name}"
                      f"|{raw['date']}|{raw['title']}")
            article_id = sha256(id_str.encode()).hexdigest()[:16]

            article = RssArticle(
                article_id=article_id,
                entity_name=entity.name,
                index=entity.index,
                title=raw["title"],
                summary=raw.get("summary", ""),
                source_feed=raw["feed_name"],
                feed_category=raw.get("feed_category", ""),
                url=raw.get("url", ""),
                published_date=raw["date"],
                match_score=score,
                sector=entity.sector,
            )

            if article_exists(conn, article_id):
                duplicates += 1
                continue

            matched_articles.append(article)
            break  # Best match only per article

    print(f"  Matched: {len(matched_articles)} | Duplicates: {duplicates}")

    if not matched_articles:
        conn.close()
        return []

    # Classify matched articles
    if dry_run:
        print(f"\n  [DRY RUN] {len(matched_articles)} articles matched:")
        for a in matched_articles[:30]:
            safe_name = a.entity_name.encode("ascii", "replace").decode()
            safe_title = a.title[:60].encode("ascii", "replace").decode()
            print(f"    [{a.index:5}] {safe_name:<30} score={a.match_score:.1f} "
                  f"| {a.source_feed} | {safe_title}")
            # Store unclassified
            store_article(conn, a)
            new_articles.append(a)

        if len(matched_articles) > 30:
            print(f"    ... and {len(matched_articles) - 30} more")
    else:
        classified = 0
        failed = 0
        print(f"\n  Classifying {len(matched_articles)} articles...")

        for i, article in enumerate(matched_articles):
            safe_name = article.entity_name.encode("ascii", "replace").decode()

            result = classify_article(
                article.entity_name,
                article.title,
                article.summary,
                article.index,
            )

            if result:
                article.credit_impact = result.get("credit_impact", "neutral")
                article.severity = int(result.get("severity", 1))
                article.is_new_info = bool(result.get("is_new_info", False))
                article.claim_summary = result.get("claim_summary", "")
                article.credit_relevance = result.get("credit_relevance", "")
                article.classified_at = datetime.now().isoformat()
                classified += 1
            else:
                failed += 1

            is_new = store_article(conn, article)
            if is_new:
                new_articles.append(article)

                # Log signal change for severity >= 3
                if article.severity >= 3:
                    log_signal_change(article)

            # Progress
            if (i + 1) % 10 == 0:
                print(f"    [{i+1}/{len(matched_articles)}] classified={classified} "
                      f"failed={failed}")

            time.sleep(CLASSIFY_DELAY_SEC)

        print(f"\n  Classification: {classified} OK, {failed} failed")

    conn.close()

    # Print summary
    _print_scan_summary(new_articles)
    return new_articles


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def _print_scan_summary(articles: list[RssArticle]) -> None:
    """Print scan results summary."""
    if not articles:
        print("\n  No new articles found.")
        return

    W = 72
    print()
    print("  NEW RSS ARTICLES")
    print("  " + "=" * (W - 2))

    # Sort by severity desc, then match score desc
    sorted_arts = sorted(articles,
                         key=lambda a: (-a.severity, -a.match_score))

    for a in sorted_arts[:25]:
        safe_name = a.entity_name.encode("ascii", "replace").decode()
        safe_title = a.title[:65].encode("ascii", "replace").decode()

        impact_tag = {
            "negative": "[-]",
            "positive": "[+]",
            "neutral": "[=]",
            "unclassified": "[?]",
        }.get(a.credit_impact, "[?]")

        idx_tag = "XO" if a.index == "xover" else "IG"

        print()
        print(f"  {impact_tag} [{idx_tag}] {safe_name}")
        if a.severity > 0:
            sev_stars = "*" * a.severity
            print(f"     sev={a.severity}/5 {sev_stars}  |  "
                  f"new={'Y' if a.is_new_info else 'N'}  |  "
                  f"score={a.match_score:.1f}")
        else:
            print(f"     score={a.match_score:.1f}  |  {a.source_feed}")
        print(f"     {safe_title}")
        if a.claim_summary:
            safe_claim = a.claim_summary[:65].encode("ascii", "replace").decode()
            print(f"     {safe_claim}")
        print(f"     {a.published_date}  |  {a.source_feed}  |  {a.sector}")

    if len(articles) > 25:
        print(f"\n  ... showing 25 of {len(articles)} articles")

    print()
    total = len(articles)
    neg = sum(1 for a in articles if a.credit_impact == "negative")
    pos = sum(1 for a in articles if a.credit_impact == "positive")
    high = sum(1 for a in articles if a.severity >= 3)
    xover = sum(1 for a in articles if a.index == "xover")
    main = sum(1 for a in articles if a.index == "main")

    print(f"  Total: {total} new articles (Xover={xover}, Main={main})")
    print(f"  Negative: {neg}  |  Positive: {pos}  |  Severity >= 3: {high}")
    print("  " + "=" * (W - 2))


def show_recent(
    days: int = 7,
    entity_filter: str | None = None,
    universe_filter: str = "all",
) -> None:
    """Show recent articles from the database."""
    if not DB_PATH.exists():
        print("  No RSS news database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    query = "SELECT * FROM rss_articles WHERE published_date >= ?"
    params: list = [cutoff]

    if entity_filter:
        query += " AND entity_name LIKE ?"
        params.append(f"%{entity_filter}%")
    if universe_filter != "all":
        query += " AND idx = ?"
        params.append(universe_filter)

    query += " ORDER BY published_date DESC, severity DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print(f"  No RSS articles in the last {days} days.")
        return

    W = 72
    print()
    print(f"  RSS NEWS — Last {days} Days ({len(rows)} total)")
    print("  " + "=" * (W - 2))

    for r in rows[:30]:
        impact = {"negative": "[-]", "positive": "[+]",
                  "neutral": "[=]"}.get(r["credit_impact"], "[?]")
        idx_tag = "XO" if r["idx"] == "xover" else "IG"
        safe_name = r["entity_name"].encode("ascii", "replace").decode()
        safe_title = r["title"][:60].encode("ascii", "replace").decode()

        print(f"\n  {impact} [{idx_tag}] {safe_name}  ({r['source_feed']})")
        print(f"     sev={r['severity']}/5  |  {r['published_date']}")
        print(f"     {safe_title}")
        if r["claim_summary"]:
            safe_claim = r["claim_summary"][:60].encode("ascii", "replace").decode()
            print(f"     {safe_claim}")

    if len(rows) > 30:
        print(f"\n  ... showing 30 of {len(rows)} articles")
    print()


def show_stats(universe_filter: str = "all") -> None:
    """Show summary statistics."""
    if not DB_PATH.exists():
        print("  No RSS news database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    base_query = ""
    params = []
    if universe_filter != "all":
        base_query = " WHERE idx = ?"
        params = [universe_filter]

    total = conn.execute(
        f"SELECT COUNT(*) as cnt FROM rss_articles{base_query}", params
    ).fetchone()["cnt"]

    by_index = conn.execute(
        "SELECT idx, COUNT(*) as cnt FROM rss_articles "
        "GROUP BY idx ORDER BY cnt DESC"
    ).fetchall()

    by_impact = conn.execute(
        f"SELECT credit_impact, COUNT(*) as cnt "
        f"FROM rss_articles{base_query} GROUP BY credit_impact "
        f"ORDER BY cnt DESC", params
    ).fetchall()

    by_severity = conn.execute(
        f"SELECT severity, COUNT(*) as cnt "
        f"FROM rss_articles{base_query} GROUP BY severity "
        f"ORDER BY severity DESC", params
    ).fetchall()

    by_feed = conn.execute(
        f"SELECT feed_category, COUNT(*) as cnt "
        f"FROM rss_articles{base_query} GROUP BY feed_category "
        f"ORDER BY cnt DESC", params
    ).fetchall()

    top_entities = conn.execute(
        f"SELECT entity_name, idx, COUNT(*) as cnt "
        f"FROM rss_articles{base_query} GROUP BY entity_name "
        f"ORDER BY cnt DESC LIMIT 15", params
    ).fetchall()

    recent_high = conn.execute(
        f"SELECT entity_name, idx, credit_impact, severity, "
        f"published_date, claim_summary, source_feed "
        f"FROM rss_articles WHERE severity >= 3 "
        f"{'AND idx = ?' if universe_filter != 'all' else ''} "
        f"ORDER BY published_date DESC LIMIT 10",
        params if universe_filter != "all" else [],
    ).fetchall()

    conn.close()

    W = 65
    print()
    print(f"  RSS MONITOR — Summary ({total} total articles)")
    print("  " + "=" * W)

    print(f"\n  BY INDEX:")
    for r in by_index:
        label = "Xover" if r["idx"] == "xover" else "Main"
        print(f"    {label:<20} {r['cnt']:>5}")

    print(f"\n  BY CREDIT IMPACT:")
    for r in by_impact:
        print(f"    {r['credit_impact']:<20} {r['cnt']:>5}")

    print(f"\n  BY SEVERITY:")
    for r in by_severity:
        stars = "*" * r["severity"] if r["severity"] > 0 else "-"
        print(f"    sev={r['severity']} {stars:<6}  {r['cnt']:>5}")

    print(f"\n  BY FEED CATEGORY:")
    for r in by_feed:
        print(f"    {r['feed_category']:<30} {r['cnt']:>5}")

    print(f"\n  TOP ENTITIES:")
    for r in top_entities:
        idx_tag = "XO" if r["idx"] == "xover" else "IG"
        safe_name = r["entity_name"].encode("ascii", "replace").decode()
        print(f"    [{idx_tag}] {safe_name:<35} {r['cnt']:>5}")

    if recent_high:
        print(f"\n  RECENT HIGH-SEVERITY (sev >= 3):")
        for r in recent_high:
            impact = {"negative": "[-]", "positive": "[+]",
                      "neutral": "[=]"}.get(r["credit_impact"], "[?]")
            idx_tag = "XO" if r["idx"] == "xover" else "IG"
            safe_name = r["entity_name"].encode("ascii", "replace").decode()
            print(f"    {impact} [{idx_tag}] {safe_name:<30} "
                  f"sev={r['severity']}  {r['published_date']}")
            if r["claim_summary"]:
                safe_claim = r["claim_summary"][:55].encode("ascii", "replace").decode()
                print(f"        {safe_claim}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RSS Feed Monitor — 200-name iTraxx news scanner"
    )
    parser.add_argument("--entity", type=str, default=None,
                        help="Filter to entity (partial match)")
    parser.add_argument("--universe", type=str, default="all",
                        choices=["all", "xover", "main"],
                        help="Universe filter (default: all)")
    parser.add_argument("--feeds", type=str, default=None,
                        help="Comma-separated feed categories to scrape")
    parser.add_argument("--status", action="store_true",
                        help="Show recent articles from database")
    parser.add_argument("--stats", action="store_true",
                        help="Show aggregate statistics")
    parser.add_argument("--days", type=int, default=7,
                        help="Lookback days for --status (default: 7)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and match only, skip classification")
    parser.add_argument("--min-score", type=float, default=0.3,
                        help="Minimum match score (default: 0.3)")
    args = parser.parse_args()

    if args.stats:
        show_stats(universe_filter=args.universe)
        return

    if args.status:
        show_recent(
            days=args.days,
            entity_filter=args.entity,
            universe_filter=args.universe,
        )
        return

    # Parse feed categories
    category_filter = None
    if args.feeds:
        category_filter = [c.strip() for c in args.feeds.split(",")]

    # Run scan
    run_scan(
        entity_filter=args.entity,
        universe_filter=args.universe,
        category_filter=category_filter,
        dry_run=args.dry_run,
        min_match_score=args.min_score,
    )


if __name__ == "__main__":
    main()

"""
Rating Action Monitor — Credit Catalyst

Scrapes public rating agency pages for rating actions affecting our 75
iTraxx Crossover S44 names. Uses RSS feeds and public research pages
from S&P, Moody's, and Fitch, then classifies actions by type.

Action types:
    UPGRADE, DOWNGRADE, OUTLOOK_POSITIVE, OUTLOOK_NEGATIVE,
    OUTLOOK_STABLE, WATCH_POSITIVE, WATCH_NEGATIVE, WATCH_REMOVED,
    AFFIRMED, NEW_RATING, WITHDRAWN

Logs to SQLite: data/rating_actions.db

Usage:
    python -m monitors.rating_actions                 # Scan all agencies
    python -m monitors.rating_actions --agency sp     # S&P only
    python -m monitors.rating_actions --agency moodys # Moody's only
    python -m monitors.rating_actions --agency fitch  # Fitch only
    python -m monitors.rating_actions --entity INEOS  # Filter entity
    python -m monitors.rating_actions --status        # Show recent actions
    python -m monitors.rating_actions --stats         # Summary statistics
    python -m monitors.rating_actions --demo          # Demo mode (no scrape)
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from hashlib import sha256

import requests
import feedparser

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path("data/rating_actions.db")
UNIVERSE_PATH = Path("indices/xover_s44.json")

# Legal suffixes to strip for matching
LEGAL_SUFFIXES = [
    "plc", "ltd", "limited", "gmbh", "ag", "s.a.", "sa", "b.v.", "bv",
    "s.p.a.", "spa", "ab", "se", "nv", "oyj", "sarl", "sas", "saca",
    "dac", "co", "corp", "inc", "finance", "financing", "holdco",
    "holdings", "holding", "group", "international", "europe", "european",
]

# Action classification keywords
ACTION_KEYWORDS = {
    "UPGRADE": ["upgrade", "upgraded", "raises", "raised to"],
    "DOWNGRADE": ["downgrade", "downgraded", "lowers", "lowered to", "cuts"],
    "OUTLOOK_NEGATIVE": ["outlook negative", "negative outlook",
                          "outlook to negative", "outlook revised to negative",
                          "outlook changed to negative",
                          "changes outlook", "changed outlook"],
    "OUTLOOK_POSITIVE": ["outlook positive", "positive outlook",
                          "outlook to positive", "outlook revised to positive",
                          "outlook changed to positive"],
    "OUTLOOK_STABLE": ["outlook stable", "stable outlook",
                        "outlook to stable", "outlook revised to stable"],
    "WATCH_NEGATIVE": ["creditwatch negative", "watch negative",
                        "review for downgrade", "placed on review",
                        "on review for downgrade", "watchlist negative",
                        "rating watch negative"],
    "WATCH_POSITIVE": ["creditwatch positive", "watch positive",
                        "review for upgrade", "on review for upgrade",
                        "watchlist positive", "rating watch positive"],
    "WATCH_REMOVED": ["creditwatch removed", "watch removed",
                       "removed from review", "off watch",
                       "review concluded", "watch resolved"],
    "AFFIRMED": ["affirmed", "affirms", "confirms", "confirmed"],
    "WITHDRAWN": ["withdrawn", "withdraws", "withdrawal"],
    "NEW_RATING": ["new rating", "assigns", "assigned", "initial rating",
                    "first-time"],
}

# Rating agency RSS/research URLs
AGENCY_SOURCES = {
    "sp": {
        "name": "S&P Global Ratings",
        "rss": [
            "https://www.spglobal.com/ratings/en/feed/rss/ratingActions.xml",
        ],
        "research_url": "https://www.spglobal.com/ratings/en/research-insights/credit-research",
    },
    "moodys": {
        "name": "Moody's Investors Service",
        "rss": [
            "https://www.moodys.com/feed/rss/",
        ],
        "research_url": "https://www.moodys.com/research",
    },
    "fitch": {
        "name": "Fitch Ratings",
        "rss": [
            "https://www.fitchratings.com/rss/entity-research",
        ],
        "research_url": "https://www.fitchratings.com/research/corporate-finance",
    },
}

# HTTP headers to appear as browser
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-GB,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RatingAction:
    """A single rating action from any agency."""
    action_id: str               # SHA256 of agency+entity+date+headline
    entity_name: str             # Matched Xover entity
    agency: str                  # sp, moodys, fitch
    action_type: str             # UPGRADE, DOWNGRADE, etc.
    headline: str
    raw_text: str                # Full entry text
    rating_from: str = ""        # e.g., "BB-"
    rating_to: str = ""          # e.g., "B+"
    outlook: str = ""            # e.g., "Negative"
    date: str = ""               # ISO date
    url: str = ""
    sector: str = ""
    severity: int = 0            # 1-5 (5 = multi-notch downgrade)
    credit_impact: str = ""      # positive, negative, neutral


# ---------------------------------------------------------------------------
# Universe loading & fuzzy name matching
# (same pattern as european_monitor.py)
# ---------------------------------------------------------------------------

def load_universe() -> dict:
    """Load xover_s44.json."""
    if not UNIVERSE_PATH.exists():
        return {}
    with open(UNIVERSE_PATH) as f:
        return json.load(f)


def build_name_index(universe: dict) -> dict[str, str]:
    """Build keyword -> entity mapping for fuzzy matching.

    Extracts keywords from entity names plus search_aliases.
    Removes legal suffixes and noise words.
    Returns dict[lowercased_keyword -> full_entity_name].
    """
    index: dict[str, str] = {}

    noise = set(LEGAL_SUFFIXES + [
        "the", "company", "of", "and", "de", "du", "des", "i", "ii", "iii",
        "iv", "v", "1", "2", "3", "4", "5",
    ])

    # Extract from sector listings
    for sector, names in universe.get("sectors", {}).items():
        for name in names:
            # Full name as key
            index[name.lower()] = name

            # Individual words (>= 4 chars, not legal suffix)
            words = re.split(r'[\s/\-]+', name)
            for w in words:
                w_clean = w.strip(".,()").lower()
                if len(w_clean) >= 4 and w_clean not in noise:
                    # Only add if not already mapped to a different entity
                    if w_clean not in index:
                        index[w_clean] = name

    # Add search aliases (higher priority — overwrite)
    for entity, aliases in universe.get("search_aliases", {}).items():
        for alias in aliases:
            index[alias.lower()] = entity

    return index


def match_to_universe(text: str, name_index: dict[str, str]) -> str:
    """Match text to an Xover entity using word-boundary regex.

    Returns longest keyword match (highest specificity).
    """
    text_lower = text.lower()
    best_match = ""
    best_len = 0

    for keyword, entity in name_index.items():
        if len(keyword) < 4:
            continue
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower) and len(keyword) > best_len:
            best_match = entity
            best_len = len(keyword)

    return best_match


def get_sector(entity: str, universe: dict) -> str:
    """Look up sector for entity."""
    for sector, names in universe.get("sectors", {}).items():
        if entity in names:
            return sector
    return ""


# ---------------------------------------------------------------------------
# Action classification
# ---------------------------------------------------------------------------

def classify_action(headline: str, body: str = "") -> tuple[str, int, str]:
    """Classify a rating action from headline + body text.

    Returns (action_type, severity, credit_impact).
    """
    combined = (headline + " " + body).lower()

    # Try to match action type (most specific first)
    action_type = "UNKNOWN"
    for atype, keywords in ACTION_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                action_type = atype
                break
        if action_type != "UNKNOWN":
            break

    # Classify severity and credit impact
    if action_type in ("DOWNGRADE",):
        # Check for multi-notch
        if any(w in combined for w in ["two notch", "three notch", "multiple",
                                        "several notch"]):
            return action_type, 5, "negative"
        return action_type, 4, "negative"
    elif action_type in ("WATCH_NEGATIVE",):
        return action_type, 4, "negative"
    elif action_type in ("OUTLOOK_NEGATIVE",):
        return action_type, 3, "negative"
    elif action_type in ("UPGRADE",):
        if any(w in combined for w in ["investment grade", "bbb", "ig"]):
            return action_type, 5, "positive"
        return action_type, 4, "positive"
    elif action_type in ("WATCH_POSITIVE",):
        return action_type, 3, "positive"
    elif action_type in ("OUTLOOK_POSITIVE",):
        return action_type, 3, "positive"
    elif action_type in ("OUTLOOK_STABLE", "AFFIRMED", "WATCH_REMOVED"):
        return action_type, 2, "neutral"
    elif action_type in ("WITHDRAWN",):
        return action_type, 3, "neutral"
    elif action_type in ("NEW_RATING",):
        return action_type, 2, "neutral"
    else:
        return action_type, 1, "neutral"


def extract_ratings(text: str) -> tuple[str, str]:
    """Try to extract 'from' and 'to' ratings from text.

    Patterns:
        "upgraded to BB+ from BB"
        "downgraded to B from B+"
        "lowered to 'BB-' from 'BB'"
    """
    text_clean = text.replace("'", "").replace('"', '')

    # Pattern: "to X from Y"
    m = re.search(
        r'(?:to|at)\s+([A-D][a-d]*[\+\-]?\d?)\s+from\s+([A-D][a-d]*[\+\-]?\d?)',
        text_clean, re.IGNORECASE,
    )
    if m:
        return m.group(2).upper(), m.group(1).upper()

    # Pattern: "from X to Y"
    m = re.search(
        r'from\s+([A-D][a-d]*[\+\-]?\d?)\s+to\s+([A-D][a-d]*[\+\-]?\d?)',
        text_clean, re.IGNORECASE,
    )
    if m:
        return m.group(1).upper(), m.group(2).upper()

    return "", ""


# ---------------------------------------------------------------------------
# RSS / web scraping
# ---------------------------------------------------------------------------

def scrape_rss_feed(url: str, agency_key: str) -> list[dict]:
    """Parse an RSS feed and return list of entries."""
    entries = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"    WARNING: {agency_key} RSS returned {resp.status_code}")
            return []

        feed = feedparser.parse(resp.text)
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            link = entry.get("link", "")
            published = entry.get("published", entry.get("updated", ""))

            # Parse date
            date_str = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                date_str = time.strftime("%Y-%m-%d", entry.published_parsed)
            elif published:
                # Try ISO parse
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
                "agency": agency_key,
            })

    except requests.RequestException as e:
        print(f"    WARNING: {agency_key} RSS fetch failed: {e}")
    except Exception as e:
        print(f"    WARNING: {agency_key} RSS parse error: {e}")

    return entries


def scrape_agency(agency_key: str) -> list[dict]:
    """Scrape all feeds for a given agency."""
    config = AGENCY_SOURCES.get(agency_key, {})
    all_entries = []

    for url in config.get("rss", []):
        print(f"    Fetching {agency_key} RSS: {url[:60]}...")
        entries = scrape_rss_feed(url, agency_key)
        all_entries.extend(entries)
        time.sleep(0.5)  # Rate limiting

    print(f"    {agency_key}: {len(all_entries)} entries fetched")
    return all_entries


# ---------------------------------------------------------------------------
# Demo mode — realistic mock data
# ---------------------------------------------------------------------------

DEMO_ACTIONS = [
    {
        "title": "Moody's changes outlook on INEOS Quattro to negative from stable",
        "summary": "Moody's Investors Service has changed the outlook on INEOS Quattro Finance 2 Plc to negative from stable, affirming the B3 corporate family rating. The outlook change reflects weakening liquidity and elevated refinancing risk on EUR 2.5bn of maturities in 2027-2028.",
        "link": "https://www.moodys.com/research/INEOS-Quattro-Rating-Action",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "agency": "moodys",
    },
    {
        "title": "S&P downgrades Worldline to BB- from BB; outlook negative",
        "summary": "S&P Global Ratings lowered its long-term issuer credit rating on Worldline SA/France to 'BB-' from 'BB', with negative outlook. The downgrade reflects weaker-than-expected Q4 results, leverage above 4x, and uncertainty around the company's strategic repositioning.",
        "link": "https://www.spglobal.com/ratings/worldline-action",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "agency": "sp",
    },
    {
        "title": "Fitch places SBB on Rating Watch Negative",
        "summary": "Fitch Ratings has placed Samhallsbyggnadsbolaget i Norden AB (SBB) on Rating Watch Negative from 'BB-'. The RWN reflects the company's weakening liquidity position and EUR 1.2bn in near-term maturities with limited refinancing options.",
        "link": "https://www.fitchratings.com/research/sbb-watch",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "agency": "fitch",
    },
    {
        "title": "Moody's upgrades Jaguar Land Rover outlook to positive",
        "summary": "Moody's Investors Service has changed the outlook on Jaguar Land Rover Automotive PLC to positive from stable, affirming the Ba2 rating. Positive outlook reflects strong Range Rover demand, deleveraging below 2x, and improving free cash flow generation.",
        "link": "https://www.moodys.com/research/JLR-Rating-Action",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "agency": "moodys",
    },
    {
        "title": "S&P affirms CMA CGM at BB+; outlook stable",
        "summary": "S&P Global Ratings affirmed its 'BB+' long-term issuer credit rating on CMA CGM SA with a stable outlook. The affirmation reflects the company's strong market position, diversified revenue base, and adequate liquidity despite shipping market softening.",
        "link": "https://www.spglobal.com/ratings/cma-cgm-affirm",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "agency": "sp",
    },
    {
        "title": "Fitch downgrades Cirsa Finance to B from B+; outlook stable",
        "summary": "Fitch Ratings has downgraded Cirsa Finance International Sarl to 'B' from 'B+' with a stable outlook. The downgrade reflects the impact of new Spanish regional gaming taxes effective May 2026, which Fitch estimates will reduce EBITDA margins by 150-200bp.",
        "link": "https://www.fitchratings.com/research/cirsa-downgrade",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "agency": "fitch",
    },
    {
        "title": "Moody's places Kaixo Bondco on review for upgrade",
        "summary": "Moody's has placed Kaixo Bondco Telecom SA ratings on review for upgrade following MasMovil's announcement of accelerated deleveraging to below 4x by mid-2026 and improved free cash flow visibility.",
        "link": "https://www.moodys.com/research/Kaixo-Review",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "agency": "moodys",
    },
    {
        "title": "S&P lowers Syngenta AG to BB- from BB; CreditWatch negative",
        "summary": "S&P Global Ratings lowered its rating on Syngenta AG to 'BB-' from 'BB' and placed it on CreditWatch with negative implications. The actions reflect weaker-than-expected crop protection volumes, Chinese parent ownership uncertainty, and leverage above 5x.",
        "link": "https://www.spglobal.com/ratings/syngenta-downgrade",
        "date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "agency": "sp",
    },
]


# ---------------------------------------------------------------------------
# SQLite database
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    """Initialise the rating actions database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rating_actions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id       TEXT UNIQUE NOT NULL,
            entity_name     TEXT NOT NULL,
            agency          TEXT NOT NULL,
            action_type     TEXT NOT NULL,
            headline        TEXT,
            raw_text        TEXT,
            rating_from     TEXT DEFAULT '',
            rating_to       TEXT DEFAULT '',
            outlook         TEXT DEFAULT '',
            date            TEXT,
            url             TEXT,
            sector          TEXT DEFAULT '',
            severity        INTEGER DEFAULT 0,
            credit_impact   TEXT DEFAULT 'neutral',
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ra_entity ON rating_actions(entity_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ra_date ON rating_actions(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ra_agency ON rating_actions(agency)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ra_type ON rating_actions(action_type)")
    conn.commit()
    return conn


def action_exists(conn: sqlite3.Connection, action_id: str) -> bool:
    """Check if this action is already in the database."""
    cur = conn.execute(
        "SELECT 1 FROM rating_actions WHERE action_id = ?", (action_id,)
    )
    return cur.fetchone() is not None


def store_action(conn: sqlite3.Connection, action: RatingAction) -> bool:
    """Store a rating action, return True if new (not duplicate)."""
    if action_exists(conn, action.action_id):
        return False
    conn.execute("""
        INSERT INTO rating_actions
            (action_id, entity_name, agency, action_type, headline, raw_text,
             rating_from, rating_to, outlook, date, url, sector,
             severity, credit_impact)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        action.action_id, action.entity_name, action.agency,
        action.action_type, action.headline, action.raw_text,
        action.rating_from, action.rating_to, action.outlook,
        action.date, action.url, action.sector,
        action.severity, action.credit_impact,
    ))
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Main scanning pipeline
# ---------------------------------------------------------------------------

def process_entries(
    entries: list[dict],
    name_index: dict[str, str],
    universe: dict,
    conn: sqlite3.Connection,
) -> list[RatingAction]:
    """Process raw feed entries: match, classify, store."""
    new_actions = []

    for entry in entries:
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        combined = title + " " + summary

        # Match to universe
        entity = match_to_universe(combined, name_index)
        if not entity:
            continue

        # Classify
        action_type, severity, impact = classify_action(title, summary)
        rating_from, rating_to = extract_ratings(combined)

        # Extract outlook from text
        outlook = ""
        for ol in ["negative", "positive", "stable", "developing"]:
            if f"outlook {ol}" in combined.lower() or f"{ol} outlook" in combined.lower():
                outlook = ol.capitalize()
                break

        # Generate unique ID
        id_str = f"{entry['agency']}|{entity}|{entry['date']}|{title}"
        action_id = sha256(id_str.encode()).hexdigest()[:16]

        action = RatingAction(
            action_id=action_id,
            entity_name=entity,
            agency=entry["agency"],
            action_type=action_type,
            headline=title,
            raw_text=summary[:500],
            rating_from=rating_from,
            rating_to=rating_to,
            outlook=outlook,
            date=entry["date"],
            url=entry.get("link", ""),
            sector=get_sector(entity, universe),
            severity=severity,
            credit_impact=impact,
        )

        is_new = store_action(conn, action)
        if is_new:
            new_actions.append(action)
            try:
                from data.entity_profile_manager import update_profile
                update_profile(entity, "rating_actions", {
                    "action_id": action.action_id,
                    "agency": action.agency,
                    "action_type": action.action_type,
                    "headline": action.headline,
                    "date": action.date,
                    "severity": action.severity,
                    "credit_impact": action.credit_impact,
                    "rating_from": action.rating_from,
                    "rating_to": action.rating_to,
                })
            except Exception:
                pass  # Profile update is non-critical

    return new_actions


def run_scan(
    agencies: list[str] | None = None,
    demo: bool = False,
) -> list[RatingAction]:
    """Run the full rating action scan.

    Args:
        agencies: ["sp", "moodys", "fitch"] or None for all
        demo: Use mock data instead of live scraping
    """
    universe = load_universe()
    name_index = build_name_index(universe)
    conn = init_db()

    if agencies is None:
        agencies = list(AGENCY_SOURCES.keys())

    all_entries = []

    if demo:
        print("  Running in DEMO mode (mock rating actions)...")
        all_entries = DEMO_ACTIONS
    else:
        for agency in agencies:
            if agency not in AGENCY_SOURCES:
                print(f"  WARNING: Unknown agency '{agency}', skipping")
                continue
            name = AGENCY_SOURCES[agency]["name"]
            print(f"  Scanning {name}...")
            entries = scrape_agency(agency)
            all_entries.extend(entries)

    print(f"\n  Processing {len(all_entries)} entries against {len(name_index)} keywords...")

    new_actions = process_entries(all_entries, name_index, universe, conn)

    conn.close()
    return new_actions


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def print_actions(actions: list[RatingAction]) -> None:
    """Print rating actions to terminal."""
    if not actions:
        print("  No new rating actions found.")
        return

    W = 72
    print()
    print("  NEW RATING ACTIONS")
    print("  " + "=" * (W - 2))

    for a in sorted(actions, key=lambda x: -x.severity):
        sev_stars = "*" * a.severity
        impact_tag = {
            "negative": "\033[91m[-]\033[0m",
            "positive": "\033[92m[+]\033[0m",
            "neutral": "[=]",
        }.get(a.credit_impact, "[?]")

        agency_tag = {
            "sp": "S&P",
            "moodys": "Moody's",
            "fitch": "Fitch",
        }.get(a.agency, a.agency.upper())

        print()
        print(f"  {impact_tag} {a.entity_name}")
        print(f"     {agency_tag}  |  {a.action_type}  |  sev={a.severity}/5 {sev_stars}")
        print(f"     {a.headline[:68]}")
        if a.rating_from and a.rating_to:
            print(f"     Rating: {a.rating_from} -> {a.rating_to}"
                  + (f"  |  Outlook: {a.outlook}" if a.outlook else ""))
        elif a.outlook:
            print(f"     Outlook: {a.outlook}")
        print(f"     Date: {a.date}  |  Sector: {a.sector}")

    print()
    print(f"  Total: {len(actions)} new actions")
    print("  " + "=" * (W - 2))


def show_recent(days: int = 30, entity_filter: str | None = None) -> None:
    """Show recent rating actions from DB."""
    if not DB_PATH.exists():
        print("  No rating actions database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    if entity_filter:
        rows = conn.execute(
            """SELECT * FROM rating_actions
               WHERE date >= ? AND entity_name LIKE ?
               ORDER BY date DESC, severity DESC""",
            (cutoff, f"%{entity_filter}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM rating_actions
               WHERE date >= ?
               ORDER BY date DESC, severity DESC""",
            (cutoff,),
        ).fetchall()

    conn.close()

    if not rows:
        print(f"  No rating actions in the last {days} days.")
        return

    W = 72
    print()
    print(f"  RATING ACTIONS — Last {days} Days ({len(rows)} total)")
    print("  " + "=" * (W - 2))

    for r in rows:
        impact = {"negative": "[-]", "positive": "[+]", "neutral": "[=]"}.get(
            r["credit_impact"], "[?]"
        )
        agency = {"sp": "S&P", "moodys": "Moody's", "fitch": "Fitch"}.get(
            r["agency"], r["agency"]
        )
        print(f"\n  {impact} {r['entity_name']}  ({agency})")
        print(f"     {r['action_type']}  |  sev={r['severity']}/5  |  {r['date']}")
        print(f"     {r['headline'][:65]}")
        if r["rating_from"] and r["rating_to"]:
            print(f"     {r['rating_from']} -> {r['rating_to']}", end="")
            if r["outlook"]:
                print(f"  |  Outlook: {r['outlook']}")
            else:
                print()

    print()


def show_stats() -> None:
    """Show summary statistics from DB."""
    if not DB_PATH.exists():
        print("  No rating actions database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) as cnt FROM rating_actions").fetchone()["cnt"]

    by_type = conn.execute(
        "SELECT action_type, COUNT(*) as cnt FROM rating_actions GROUP BY action_type ORDER BY cnt DESC"
    ).fetchall()

    by_agency = conn.execute(
        "SELECT agency, COUNT(*) as cnt FROM rating_actions GROUP BY agency ORDER BY cnt DESC"
    ).fetchall()

    by_impact = conn.execute(
        "SELECT credit_impact, COUNT(*) as cnt FROM rating_actions GROUP BY credit_impact ORDER BY cnt DESC"
    ).fetchall()

    recent_negative = conn.execute(
        """SELECT entity_name, action_type, date, severity
           FROM rating_actions
           WHERE credit_impact = 'negative'
           ORDER BY date DESC LIMIT 5"""
    ).fetchall()

    conn.close()

    W = 60
    print()
    print(f"  RATING ACTIONS — Summary ({total} total)")
    print("  " + "=" * W)

    print(f"\n  BY ACTION TYPE:")
    for r in by_type:
        print(f"    {r['action_type']:<25} {r['cnt']:>4}")

    print(f"\n  BY AGENCY:")
    agency_names = {"sp": "S&P", "moodys": "Moody's", "fitch": "Fitch"}
    for r in by_agency:
        print(f"    {agency_names.get(r['agency'], r['agency']):<25} {r['cnt']:>4}")

    print(f"\n  BY IMPACT:")
    for r in by_impact:
        print(f"    {r['credit_impact']:<25} {r['cnt']:>4}")

    if recent_negative:
        print(f"\n  RECENT NEGATIVE ACTIONS:")
        for r in recent_negative:
            print(f"    {r['entity_name']:<30} {r['action_type']:<18} "
                  f"sev={r['severity']}  {r['date']}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Credit Catalyst — Rating Action Monitor"
    )
    parser.add_argument("--agency", type=str, default=None,
                        help="Scan specific agency: sp, moodys, fitch")
    parser.add_argument("--entity", type=str, default=None,
                        help="Filter by entity name")
    parser.add_argument("--status", action="store_true",
                        help="Show recent rating actions from DB")
    parser.add_argument("--stats", action="store_true",
                        help="Show summary statistics")
    parser.add_argument("--days", type=int, default=30,
                        help="Lookback days for --status (default: 30)")
    parser.add_argument("--demo", action="store_true",
                        help="Demo mode with mock data (no live scraping)")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.status:
        show_recent(days=args.days, entity_filter=args.entity)
        return

    # Run scan
    agencies = [args.agency] if args.agency else None

    print()
    print("  CREDIT CATALYST — Rating Action Monitor")
    print("  " + "=" * 50)

    new_actions = run_scan(agencies=agencies, demo=args.demo)

    # Filter by entity if specified
    if args.entity:
        target = args.entity.lower()
        new_actions = [a for a in new_actions
                       if target in a.entity_name.lower()]

    print_actions(new_actions)


if __name__ == "__main__":
    main()

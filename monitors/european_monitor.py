"""
European Regulatory Filing Monitor

Four working data sources:
1. Companies House (UK) — REST API for filing history
2. Investegate (UK RNS) — scrapes public announcements page
3. EQS News (Germany DGAP) — scrapes ad-hoc disclosures page
4. AMF (France) — scrapes Autorite des Marches Financiers disclosures

Each new filing is classified for credit impact via Claude API,
logged to SQLite, and optionally sent as a Telegram alert.

Usage:
    python -m monitors.european_monitor                     # Run all sources
    python -m monitors.european_monitor --source ch         # Companies House only
    python -m monitors.european_monitor --source investegate # Investegate only
    python -m monitors.european_monitor --source eqs        # EQS News only
    python -m monitors.european_monitor --source amf        # AMF only
    python -m monitors.european_monitor --days 3            # Look back 3 days
"""

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import anthropic
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Filing:
    """A regulatory filing or announcement from any source."""

    company_name: str
    source: str           # "companies_house" | "investegate" | "eqs_news"
    filing_type: str      # "accounts" | "charge" | "ad-hoc" | "rns" etc.
    headline: str
    date: str             # ISO date string
    url: str
    country: str          # "UK" | "DE" | "FR" etc.

    # Claude classification (filled after analysis)
    credit_impact: str = ""       # "positive" | "negative" | "neutral"
    severity: int = 0             # 1-5
    credit_summary: str = ""      # One-line summary from Claude
    classified: bool = False

    # Matching
    matched_entity: str = ""      # Which Xover entity this maps to


# ---------------------------------------------------------------------------
# Universe loader
# ---------------------------------------------------------------------------

def load_xover_universe() -> dict:
    """Load Xover S44 constituents with sector and alias info."""
    path = Path("indices/xover_s44.json")
    if not path.exists():
        logger.error(f"Index file not found: {path}")
        return {"names": [], "aliases": {}, "sectors": {}}

    with open(path) as f:
        data = json.load(f)

    names: list[str] = []
    name_to_sector: dict[str, str] = {}
    for sector, sector_names in data.get("sectors", {}).items():
        for name in sector_names:
            names.append(name)
            name_to_sector[name] = sector

    return {
        "names": names,
        "aliases": data.get("search_aliases", {}),
        "sectors": name_to_sector,
    }


# Build a search index: lowercased keyword -> full entity name
def _build_name_index(universe: dict) -> dict[str, str]:
    """Build keyword -> entity mapping for fuzzy matching announcements."""
    index: dict[str, str] = {}
    for name in universe["names"]:
        # Extract meaningful keywords from entity name
        # "Bellis Acquisition Company plc (Asda)" -> ["bellis", "asda"]
        clean = re.sub(r"\b(plc|ltd|gmbh|ag|s\.a\.|b\.v\.|s\.p\.a\.|ab|se|nv|oyj|s\.a\.u\.)\b", "",
                       name, flags=re.IGNORECASE)
        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", clean)
        words = [w.lower() for w in clean.split() if len(w) >= 4]
        for w in words:
            if w not in ("the", "company", "finance", "financing", "holdco",
                         "holding", "holdings", "group", "international",
                         "european", "designated", "activity", "bondco",
                         "midholding", "acquisition", "global", "trust",
                         "capital", "technology", "healthcare", "power",
                         "energy", "property", "general", "corp",
                         "standard", "premier", "public", "crown",
                         "motion", "summer", "real", "cruises"):
                index[w] = name

    # Add aliases
    for full_name, aliases in universe.get("aliases", {}).items():
        for alias in aliases:
            index[alias.lower()] = full_name

    return index


def match_to_universe(text: str, name_index: dict[str, str]) -> str:
    """Try to match a headline/company to a Xover entity. Returns '' if no match.
    Uses word-boundary matching to avoid partial matches (e.g. 'lloyd' in 'lloyds')."""
    text_lower = text.lower()
    best_match = ""
    best_len = 0
    for keyword, entity in name_index.items():
        # Word boundary match: keyword must appear as a whole word
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower) and len(keyword) > best_len:
            best_match = entity
            best_len = len(keyword)
    return best_match


# ---------------------------------------------------------------------------
# Source 1: Companies House API
# ---------------------------------------------------------------------------

# UK companies in Xover S44 with their Companies House numbers
UK_COMPANIES: dict[str, str] = {
    "INEOS Finance plc": "10040243",
    "INEOS Quattro Finance 2 plc": "12809822",
    "Jaguar Land Rover Automotive plc": "06477691",
    "Bellis Acquisition Company plc (Asda)": "13035608",
    "Stonegate Pub Company Financing plc": "11532037",
    "Iceland Bondco plc": "10314498",
    "Premier Foods Finance plc": "05765669",
    "EG Global Finance plc": "11043982",
    "Belron UK Finance plc": "10527314",
    "Boparan Finance plc": "08674498",
    "Virgin Media Finance plc": "08457551",
    "Allwyn Entertainment Financing (UK) plc": "14471498",
    "Zegona Finance plc": "14927996",
}


class CompaniesHouseSource:
    """Monitors UK Companies House for new filings."""

    BASE_URL = "https://api.company-information.service.gov.uk"

    def __init__(self):
        self.api_key = os.getenv("COMPANIES_HOUSE_API_KEY", "")
        self.session = requests.Session()
        if self.api_key:
            self.session.auth = (self.api_key, "")
        self.session.headers.update({"Accept": "application/json"})

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def get_filings(self, company_number: str, company_name: str,
                    since_days: int = 7) -> list[Filing]:
        """Fetch recent filings for a single company."""
        if not self.available:
            return []

        url = f"{self.BASE_URL}/company/{company_number}/filing-history"
        try:
            resp = self.session.get(url, params={"items_per_page": 25}, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"CH API error for {company_name}: {e}")
            return []

        cutoff = datetime.now() - timedelta(days=since_days)
        filings: list[Filing] = []

        for item in resp.json().get("items", []):
            try:
                filing_date = datetime.strptime(item.get("date", ""), "%Y-%m-%d")
            except ValueError:
                continue
            if filing_date < cutoff:
                continue

            filing_type = item.get("type", "unknown")
            description = item.get("description", "")
            # Build Companies House URL for this filing
            doc_url = f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/filing-history"

            filings.append(Filing(
                company_name=company_name,
                source="companies_house",
                filing_type=filing_type,
                headline=description or filing_type,
                date=item.get("date", ""),
                url=doc_url,
                country="UK",
                matched_entity=company_name,
            ))

        return filings

    def scan(self, since_days: int = 7) -> list[Filing]:
        """Scan all UK Xover companies for new filings."""
        if not self.available:
            logger.warning("Companies House: no API key — skipping (set COMPANIES_HOUSE_API_KEY)")
            return []

        all_filings: list[Filing] = []
        for name, number in UK_COMPANIES.items():
            logger.info(f"CH: checking {name} ({number})")
            filings = self.get_filings(number, name, since_days)
            all_filings.extend(filings)
            time.sleep(0.5)  # Rate limit: 600 req / 5 min

        logger.info(f"Companies House: found {len(all_filings)} filings in last {since_days} days")
        return all_filings


# ---------------------------------------------------------------------------
# Source 2: Investegate (UK RNS announcements)
# ---------------------------------------------------------------------------

class InvestegateSource:
    """Scrapes Investegate for UK regulatory news announcements."""

    BASE_URL = "https://www.investegate.co.uk"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })

    def scan(self, since_days: int = 1, name_index: dict = None) -> list[Filing]:
        """Scrape recent announcements and match to Xover universe."""
        if name_index is None:
            name_index = {}

        filings: list[Filing] = []
        try:
            resp = self.session.get(self.BASE_URL, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Investegate fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Investegate lists announcements in table rows
        for row in soup.select("tr"):
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            # Try to extract: time, company, headline
            time_text = cols[0].get_text(strip=True)
            company_text = cols[1].get_text(strip=True)
            headline_text = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            if not company_text or not headline_text:
                continue

            # Extract link
            link_tag = cols[2].find("a") if len(cols) > 2 else cols[1].find("a")
            url = ""
            if link_tag and link_tag.get("href"):
                href = link_tag["href"]
                url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            # Match to universe
            matched = match_to_universe(
                f"{company_text} {headline_text}", name_index
            )

            if matched:
                filings.append(Filing(
                    company_name=company_text,
                    source="investegate",
                    filing_type="rns",
                    headline=headline_text[:200],
                    date=datetime.now().strftime("%Y-%m-%d"),
                    url=url,
                    country="UK",
                    matched_entity=matched,
                ))

        logger.info(f"Investegate: found {len(filings)} matched announcements")
        return filings


# ---------------------------------------------------------------------------
# Source 3: EQS News (German DGAP ad-hoc disclosures)
# ---------------------------------------------------------------------------

class EQSNewsSource:
    """Scrapes EQS News (formerly DGAP) for German ad-hoc disclosures."""

    BASE_URL = "https://www.eqs-news.com"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })

    def scan(self, since_days: int = 1, name_index: dict = None) -> list[Filing]:
        """Scrape recent ad-hoc announcements and match to Xover universe."""
        if name_index is None:
            name_index = {}

        filings: list[Filing] = []

        try:
            resp = self.session.get(self.BASE_URL, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"EQS News fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # EQS News uses .news__row elements
        for item in soup.select("[class*='news__row'], [class*='news-item'], article, .news-list tr"):
            # Extract company and headline text
            company_el = item.select_one("[class*='company'], [class*='stock'], .company-name")
            headline_el = item.select_one("[class*='heading'], [class*='title'], a")

            company_text = company_el.get_text(strip=True) if company_el else ""
            headline_text = headline_el.get_text(strip=True) if headline_el else ""

            if not company_text and not headline_text:
                # Fallback: grab all text from the item
                all_text = item.get_text(strip=True)
                if len(all_text) > 10:
                    headline_text = all_text[:200]
                else:
                    continue

            # Extract link
            link_tag = item.find("a", href=True)
            url = ""
            if link_tag:
                href = link_tag["href"]
                url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            # Match to universe
            search_text = f"{company_text} {headline_text}"
            matched = match_to_universe(search_text, name_index)

            if matched:
                filings.append(Filing(
                    company_name=company_text or matched,
                    source="eqs_news",
                    filing_type="ad-hoc",
                    headline=headline_text[:200],
                    date=datetime.now().strftime("%Y-%m-%d"),
                    url=url,
                    country="DE",
                    matched_entity=matched,
                ))

        logger.info(f"EQS News: found {len(filings)} matched announcements")
        return filings


# ---------------------------------------------------------------------------
# Source 4: AMF (Autorite des Marches Financiers — France)
# ---------------------------------------------------------------------------

class AMFSource:
    """Scrapes AMF (French financial regulator) for corporate disclosures.

    Monitors the AMF decisions and disclosures feed for ad-hoc announcements
    from French-domiciled iTraxx constituents.
    """

    BASE_URL = "https://www.amf-france.org"
    DECISIONS_URL = f"{BASE_URL}/en/news-publications/news-releases/amf-news-releases"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })

    def scan(self, since_days: int = 1, name_index: dict = None) -> list[Filing]:
        """Scrape recent AMF disclosures and match to iTraxx universe."""
        if name_index is None:
            name_index = {}

        filings: list[Filing] = []

        try:
            resp = self.session.get(self.DECISIONS_URL, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"AMF fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # AMF uses article/card-style elements for news items
        for item in soup.select(
            "article, .views-row, .node--type-news, [class*='news'], .view-content .item-list li"
        ):
            # Extract headline and date
            headline_el = item.select_one("h2, h3, [class*='title'], a")
            date_el = item.select_one("time, [class*='date'], .field--name-created")

            headline_text = headline_el.get_text(strip=True) if headline_el else ""
            date_text = date_el.get_text(strip=True) if date_el else ""

            if not headline_text:
                all_text = item.get_text(strip=True)
                if len(all_text) > 10:
                    headline_text = all_text[:200]
                else:
                    continue

            # Extract link
            link_tag = item.find("a", href=True)
            url = ""
            if link_tag:
                href = link_tag["href"]
                url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            # Match to universe
            matched = match_to_universe(headline_text, name_index)

            if matched:
                filings.append(Filing(
                    company_name=matched,
                    source="amf",
                    filing_type="amf_disclosure",
                    headline=headline_text[:200],
                    date=date_text or datetime.now().strftime("%Y-%m-%d"),
                    url=url,
                    country="FR",
                    matched_entity=matched,
                ))

        logger.info(f"AMF: found {len(filings)} matched announcements")
        return filings


# ---------------------------------------------------------------------------
# Claude credit impact classifier
# ---------------------------------------------------------------------------

def classify_filing(filing: Filing) -> Filing:
    """Use Claude API to classify the credit impact of a filing."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY — skipping classification")
        filing.credit_impact = "unknown"
        filing.severity = 0
        filing.credit_summary = "Not classified (no API key)"
        filing.classified = False
        return filing

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""Classify this regulatory filing for credit impact on the issuer's CDS spread.

Company: {filing.company_name}
Matched Entity: {filing.matched_entity}
Source: {filing.source}
Filing Type: {filing.filing_type}
Headline: {filing.headline}
Country: {filing.country}

Respond with ONLY valid JSON:
{{
    "impact": "positive" or "negative" or "neutral",
    "severity": 1-5 (1=trivial, 5=material spread-moving),
    "summary": "One sentence credit impact summary"
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=256,
            system="You are a credit analyst. Classify regulatory filings for CDS spread impact. Be concise.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        data = json.loads(raw)
        filing.credit_impact = data.get("impact", "neutral")
        filing.severity = int(data.get("severity", 1))
        filing.credit_summary = data.get("summary", "")
        filing.classified = True

    except Exception as e:
        logger.error(f"Classification failed for {filing.company_name}: {e}")
        filing.credit_impact = "error"
        filing.severity = 0
        filing.credit_summary = f"Classification error: {str(e)[:80]}"
        filing.classified = False

    return filing


# ---------------------------------------------------------------------------
# SQLite logging
# ---------------------------------------------------------------------------

DB_PATH = Path("data/filings.db")


def init_db():
    """Create the filings table if it doesn't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS filings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            matched_entity TEXT,
            source TEXT NOT NULL,
            filing_type TEXT,
            headline TEXT,
            date TEXT,
            url TEXT,
            country TEXT,
            credit_impact TEXT,
            severity INTEGER,
            credit_summary TEXT,
            classified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_filings_entity ON filings(matched_entity)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_filings_date ON filings(date)
    """)
    conn.commit()
    conn.close()


def is_duplicate(filing: Filing) -> bool:
    """Check if this exact filing was already logged."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute(
        "SELECT COUNT(*) FROM filings WHERE source=? AND headline=? AND date=?",
        (filing.source, filing.headline, filing.date),
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def log_filing(filing: Filing):
    """Insert a filing into the database."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        INSERT INTO filings (company_name, matched_entity, source, filing_type,
                            headline, date, url, country, credit_impact,
                            severity, credit_summary, classified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        filing.company_name, filing.matched_entity, filing.source,
        filing.filing_type, filing.headline, filing.date, filing.url,
        filing.country, filing.credit_impact, filing.severity,
        filing.credit_summary, int(filing.classified),
    ))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Telegram alerting
# ---------------------------------------------------------------------------

async def send_telegram_alert(filing: Filing):
    """Send a Telegram alert for a classified filing."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return

    impact_emoji = {
        "positive": "\u2705",   # green check
        "negative": "\U0001F6A8",  # siren
        "neutral": "\u2139\ufe0f",  # info
    }.get(filing.credit_impact, "\u2753")  # question mark

    severity_bar = "\u2b1b" * filing.severity + "\u2b1c" * (5 - filing.severity)

    message = (
        f"{impact_emoji} <b>{filing.matched_entity}</b>\n\n"
        f"<b>Type:</b> {filing.filing_type}\n"
        f"<b>Source:</b> {filing.source}\n"
        f"<b>Impact:</b> {filing.credit_impact.upper()} {severity_bar}\n\n"
        f"<b>Headline:</b>\n{filing.headline}\n\n"
        f"<b>Assessment:</b>\n<i>{filing.credit_summary}</i>\n\n"
    )
    if filing.url:
        message += f'<a href="{filing.url}">View filing</a>\n'
    message += f"\n{filing.date}"

    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_scan(sources: list[str] | None = None, since_days: int = 7,
             classify: bool = True, alert: bool = True) -> list[Filing]:
    """Run the full European monitor scan.

    Args:
        sources: List of sources to scan. None = all.
                 Options: "ch", "investegate", "eqs"
        since_days: How many days back to look.
        classify: Whether to classify filings via Claude API.
        alert: Whether to send Telegram alerts.

    Returns:
        List of all filings found (classified if enabled).
    """
    init_db()

    # Load universe and build name index
    universe = load_xover_universe()
    name_index = _build_name_index(universe)
    logger.info(f"Loaded {len(universe['names'])} Xover names, {len(name_index)} search keywords")

    if sources is None:
        sources = ["ch", "investegate", "eqs", "amf"]

    all_filings: list[Filing] = []

    # --- Companies House ---
    if "ch" in sources:
        ch = CompaniesHouseSource()
        all_filings.extend(ch.scan(since_days=since_days))

    # --- Investegate ---
    if "investegate" in sources:
        inv = InvestegateSource()
        all_filings.extend(inv.scan(since_days=since_days, name_index=name_index))

    # --- EQS News ---
    if "eqs" in sources:
        eqs = EQSNewsSource()
        all_filings.extend(eqs.scan(since_days=since_days, name_index=name_index))

    # --- AMF (France) ---
    if "amf" in sources:
        amf = AMFSource()
        all_filings.extend(amf.scan(since_days=since_days, name_index=name_index))

    # Deduplicate against DB
    new_filings = [f for f in all_filings if not is_duplicate(f)]
    logger.info(f"Total: {len(all_filings)} filings, {len(new_filings)} new")

    # Classify and alert
    for filing in new_filings:
        if classify:
            classify_filing(filing)
            time.sleep(1)  # Rate limit Claude API

        log_filing(filing)

        if alert and filing.classified and filing.severity >= 2:
            asyncio.run(send_telegram_alert(filing))

    return new_filings


def print_results(filings: list[Filing]):
    """Pretty-print scan results to terminal."""
    if not filings:
        print("No new filings found.")
        return

    impact_symbols = {"positive": "+", "negative": "-", "neutral": "=", "error": "?", "unknown": "?"}

    print(f"\n{'='*80}")
    print(f"  EUROPEAN MONITOR — {len(filings)} new filings")
    print(f"{'='*80}\n")

    for f in sorted(filings, key=lambda x: x.severity, reverse=True):
        symbol = impact_symbols.get(f.credit_impact, "?")
        sev = f"[{f.severity}/5]" if f.classified else "[n/a]"
        print(f"  {symbol} {sev} {f.matched_entity or f.company_name}")
        print(f"    {f.source} | {f.filing_type} | {f.date}")
        print(f"    {f.headline[:100]}")
        if f.credit_summary:
            print(f"    >> {f.credit_summary}")
        print()


def main():
    parser = argparse.ArgumentParser(description="European Regulatory Filing Monitor")
    parser.add_argument(
        "--source",
        type=str,
        choices=["ch", "investegate", "eqs", "amf"],
        default=None,
        help="Scan specific source only (default: all)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Look back N days (default: 7)",
    )
    parser.add_argument(
        "--no-classify",
        action="store_true",
        help="Skip Claude API classification",
    )
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="Skip Telegram alerts",
    )
    args = parser.parse_args()

    sources = [args.source] if args.source else None

    filings = run_scan(
        sources=sources,
        since_days=args.days,
        classify=not args.no_classify,
        alert=not args.no_alert,
    )

    print_results(filings)


if __name__ == "__main__":
    main()

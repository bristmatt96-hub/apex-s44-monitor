"""
Equity Movers Monitor — Real-Time Price Alert Scanner
=====================================================
Fetches live equity prices for all 175+ public iTraxx names
(42 Crossover + 133 Main) and alerts when any name moves >2%.

For every mover, automatically fetches news via Google News RSS
to explain the move. Optionally classifies credit impact via
Chutes (SN64) or Anthropic Claude.

Equity moves lead CDS by 1-2 days (Merton structural model).
A >5% equity drop on an HY name almost always precedes spread
widening. This monitor catches those signals in real-time.

Data sources:
  - Yahoo Finance (via yfinance) — 15-20 min delayed intraday
  - Google News RSS — automatic news lookup for movers
  - Chutes / Anthropic — optional credit impact classification

Database: data/equity_movers.db (SQLite)

Usage:
    python -m monitors.equity_movers                     # Scan all 175 names
    python -m monitors.equity_movers --threshold 5       # Only >5% moves
    python -m monitors.equity_movers --universe xover    # Xover only
    python -m monitors.equity_movers --entity "Grifols"  # Single name
    python -m monitors.equity_movers --status             # Recent movers from DB
    python -m monitors.equity_movers --stats              # Aggregate statistics
    python -m monitors.equity_movers --no-news            # Skip news lookup
    python -m monitors.equity_movers --classify           # Also classify news via LLM

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
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Optional

import requests
import feedparser
from dotenv import load_dotenv

load_dotenv(override=True)

# Social buzz (Gopher SN42 + Desearch SN22)
try:
    from monitors.social_sentiment import query_gopher, query_desearch, SocialPost
    SOCIAL_AVAILABLE = True
except ImportError:
    SOCIAL_AVAILABLE = False

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

DB_PATH = Path("data/equity_movers.db")
XOVER_TICKERS_PATH = Path("config/equity_tickers.json")
MAIN_CONSTITUENTS_PATH = Path("analytics/itraxx_main_constituents.py")
MAIN_INDEX_PATH = Path("indices/main_s44.json")
XOVER_INDEX_PATH = Path("indices/xover_s44.json")
SIGNAL_CHANGES_PATH = Path("outputs/signal_changes.txt")

# Default move threshold
DEFAULT_THRESHOLD_PCT = 2.0

# yfinance batch size (avoid rate limits)
BATCH_SIZE = 20
BATCH_DELAY_SEC = 1.0

# News lookup
GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?"
    "q={query}&hl=en&gl=GB&ceid=GB:en"
)
NEWS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# LLM config
CHUTES_BASE_URL = "https://llm.chutes.ai/v1"
CHUTES_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507-TEE"

CLASSIFY_SYSTEM = """You are a credit analyst. An equity has moved significantly today.
Given the company name, the equity move, and recent news headlines,
assess the credit impact.

Respond in strict JSON:
{"credit_impact":"positive"|"negative"|"neutral","severity":1-5,"explanation":"one sentence on what this means for CDS spreads"}"""

# Sentiment keywords for quick bucketing (no LLM needed)
BEARISH_KEYWORDS = {
    "downgrade", "default", "restructuring", "distressed", "bankruptcy",
    "covenant breach", "widening", "sell", "short", "risk", "warning",
    "negative", "deteriorating", "junk", "fallen angel", "miss",
    "loss", "debt", "leverage", "investigation", "probe", "fraud",
}
BULLISH_KEYWORDS = {
    "upgrade", "tightening", "recovery", "refinanced", "improvement",
    "positive", "beat", "outperform", "buy", "strong",
    "growth", "profit", "deleveraging", "investment grade",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EquityMover:
    """A significant equity price move."""
    entity_name: str
    index: str               # "xover" or "main"
    ticker: str
    sector: str
    previous_close: float
    current_price: float
    change_pct: float
    volume: int = 0
    avg_volume: int = 0
    volume_ratio: float = 0.0  # today's vol / avg vol
    news_headlines: list = None
    credit_impact: str = ""
    severity: int = 0
    explanation: str = ""
    detected_at: str = ""

    def __post_init__(self):
        if self.news_headlines is None:
            self.news_headlines = []


@dataclass
class TickerInfo:
    """Ticker with entity mapping."""
    entity_name: str
    ticker: str
    index: str            # "xover" or "main"
    sector: str
    search_name: str      # Short name for news search


# ---------------------------------------------------------------------------
# Ticker loading
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _xover_name_to_index_name(config_name: str, xover_data: dict) -> str:
    """Try to match equity_tickers.json name to xover_s44.json name."""
    # Direct search in all sector lists
    for sector, names in xover_data.get("sectors", {}).items():
        for name in names:
            if config_name.lower() in name.lower() or name.lower() in config_name.lower():
                return name
    return config_name


def load_tickers(universe_filter: str = "all") -> list[TickerInfo]:
    """Load all public equity tickers from both universes."""
    tickers = []
    xover_data = _load_json(XOVER_INDEX_PATH)
    xover_aliases = xover_data.get("search_aliases", {})

    # --- Xover tickers from config/equity_tickers.json ---
    if universe_filter in ("all", "xover"):
        config = _load_json(XOVER_TICKERS_PATH)
        ticker_map = config.get("ticker_map", {})

        # Build sector lookup from xover index
        xover_sector_map = {}
        for sector, names in xover_data.get("sectors", {}).items():
            for name in names:
                xover_sector_map[name.lower()] = sector

        for config_name, info in ticker_map.items():
            ticker = info.get("ticker", "")
            if not ticker or ticker == "Private":
                continue

            # Map config name to canonical xover name
            entity_name = _xover_name_to_index_name(config_name, xover_data)

            # Determine sector
            sector = xover_sector_map.get(entity_name.lower(), "")

            # Build search name for news (prefer aliases)
            aliases = xover_aliases.get(entity_name, [])
            if aliases:
                search_name = aliases[0]
            else:
                # Use first meaningful word from config name
                search_name = config_name.split("(")[-1].rstrip(")").strip() \
                    if "(" in config_name else config_name.split()[0]

            tickers.append(TickerInfo(
                entity_name=entity_name,
                ticker=ticker,
                index="xover",
                sector=sector,
                search_name=search_name,
            ))

    # --- Main tickers from analytics/itraxx_main_constituents.py ---
    if universe_filter in ("all", "main"):
        # Import MAIN_CONSTITUENTS directly
        try:
            sys.path.insert(0, str(Path("analytics").resolve()))
            from itraxx_main_constituents import MAIN_CONSTITUENTS
            sys.path.pop(0)
        except ImportError:
            # Fallback: parse the file manually
            MAIN_CONSTITUENTS = _parse_main_constituents()

        main_data = _load_json(MAIN_INDEX_PATH)
        main_aliases = main_data.get("search_aliases", {})

        for name, info in MAIN_CONSTITUENTS.items():
            ticker = info.get("ticker", "")
            if not ticker:
                continue

            aliases = main_aliases.get(name, [])
            search_name = aliases[0] if aliases else name

            tickers.append(TickerInfo(
                entity_name=name,
                ticker=ticker,
                index="main",
                sector=info.get("sector", ""),
                search_name=search_name,
            ))

    return tickers


def _parse_main_constituents() -> dict:
    """Fallback: parse MAIN_CONSTITUENTS from Python file."""
    path = Path("analytics/itraxx_main_constituents.py")
    if not path.exists():
        return {}
    content = path.read_text()
    # Find the dict between MAIN_CONSTITUENTS = { ... }
    match = re.search(r'MAIN_CONSTITUENTS\s*=\s*\{(.+?)\n\}', content, re.DOTALL)
    if not match:
        return {}
    # This is a rough parse — just extract name: ticker pairs
    result = {}
    for line in match.group(1).split("\n"):
        line = line.strip()
        if line.startswith('"') and '"ticker"' in line:
            parts = line.split('"')
            if len(parts) >= 2:
                name = parts[1]
                ticker_match = re.search(r'"ticker":\s*"([^"]+)"', line)
                sector_match = re.search(r'"sector":\s*"([^"]+)"', line)
                if ticker_match:
                    result[name] = {
                        "ticker": ticker_match.group(1),
                        "sector": sector_match.group(1) if sector_match else "",
                    }
    return result


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------

def fetch_prices(tickers: list[TickerInfo]) -> list[EquityMover]:
    """Fetch current prices for all tickers, return significant movers."""
    try:
        import yfinance as yf
    except ImportError:
        print("  ERROR: pip install yfinance")
        return []

    all_movers = []
    ticker_symbols = [t.ticker for t in tickers]
    ticker_lookup = {t.ticker: t for t in tickers}

    # Fetch in batches
    for i in range(0, len(ticker_symbols), BATCH_SIZE):
        batch = ticker_symbols[i:i + BATCH_SIZE]
        batch_str = " ".join(batch)

        try:
            data = yf.download(
                batch_str,
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=True,
            )

            if data.empty:
                continue

            # Handle single vs multi-ticker DataFrame
            if len(batch) == 1:
                sym = batch[0]
                if "Close" in data.columns and len(data) >= 2:
                    closes = data["Close"].dropna()
                    volumes = data["Volume"].dropna() if "Volume" in data.columns else None

                    if len(closes) >= 2:
                        prev_close = float(closes.iloc[-2])
                        curr_price = float(closes.iloc[-1])

                        if prev_close > 0:
                            change_pct = ((curr_price - prev_close) / prev_close) * 100

                            vol = int(volumes.iloc[-1]) if volumes is not None and len(volumes) >= 1 else 0
                            avg_vol = int(volumes.mean()) if volumes is not None and len(volumes) >= 2 else 0
                            vol_ratio = vol / avg_vol if avg_vol > 0 else 0.0

                            info = ticker_lookup[sym]
                            all_movers.append(EquityMover(
                                entity_name=info.entity_name,
                                index=info.index,
                                ticker=sym,
                                sector=info.sector,
                                previous_close=prev_close,
                                current_price=curr_price,
                                change_pct=round(change_pct, 2),
                                volume=vol,
                                avg_volume=avg_vol,
                                volume_ratio=round(vol_ratio, 2),
                                detected_at=datetime.now().isoformat(),
                            ))
            else:
                for sym in batch:
                    try:
                        if sym not in data["Close"].columns:
                            continue

                        closes = data["Close"][sym].dropna()
                        volumes = data["Volume"][sym].dropna() if "Volume" in data.columns else None

                        if len(closes) < 2:
                            continue

                        prev_close = float(closes.iloc[-2])
                        curr_price = float(closes.iloc[-1])

                        if prev_close <= 0:
                            continue

                        change_pct = ((curr_price - prev_close) / prev_close) * 100

                        vol = int(volumes.iloc[-1]) if volumes is not None and len(volumes) >= 1 else 0
                        avg_vol = int(volumes.mean()) if volumes is not None and len(volumes) >= 2 else 0
                        vol_ratio = vol / avg_vol if avg_vol > 0 else 0.0

                        info = ticker_lookup[sym]
                        all_movers.append(EquityMover(
                            entity_name=info.entity_name,
                            index=info.index,
                            ticker=sym,
                            sector=info.sector,
                            previous_close=prev_close,
                            current_price=curr_price,
                            change_pct=round(change_pct, 2),
                            volume=vol,
                            avg_volume=avg_vol,
                            volume_ratio=round(vol_ratio, 2),
                            detected_at=datetime.now().isoformat(),
                        ))

                    except Exception:
                        continue

        except Exception as e:
            safe_msg = str(e)[:80].encode("ascii", "replace").decode()
            print(f"    Batch error: {safe_msg}")

        if i + BATCH_SIZE < len(ticker_symbols):
            time.sleep(BATCH_DELAY_SEC)

    return all_movers


# ---------------------------------------------------------------------------
# News lookup
# ---------------------------------------------------------------------------

def fetch_news_for_mover(search_name: str, max_articles: int = 5) -> list[dict]:
    """Fetch recent news for a mover via Google News RSS."""
    query = f"{search_name} stock".replace(" ", "+")
    url = GOOGLE_NEWS_RSS.format(query=query)

    try:
        resp = requests.get(url, headers=NEWS_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []

        feed = feedparser.parse(resp.text)
        articles = []
        for entry in feed.entries[:max_articles]:
            title = entry.get("title", "")
            source = ""
            if hasattr(entry, "source") and isinstance(entry.source, dict):
                source = entry.source.get("title", "")
            elif hasattr(entry, "source"):
                source = getattr(entry.source, "title", "")

            articles.append({
                "title": title,
                "source": source or "Unknown",
                "link": entry.get("link", ""),
            })

        return articles

    except Exception:
        return []


# ---------------------------------------------------------------------------
# LLM classification (optional)
# ---------------------------------------------------------------------------

def classify_mover(
    entity_name: str,
    change_pct: float,
    headlines: list[dict],
) -> dict | None:
    """Classify credit impact of an equity move via Chutes."""
    api_key = os.getenv("CHUTES_API_KEY")
    if not api_key:
        return None

    headline_text = "\n".join(
        f"- {h['title']} ({h['source']})" for h in headlines[:3]
    )

    user_msg = (
        f"Entity: {entity_name}\n"
        f"Equity move: {change_pct:+.1f}% today\n"
        f"Recent headlines:\n{headline_text}"
    )

    try:
        resp = requests.post(
            f"{CHUTES_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": CHUTES_MODEL,
                "messages": [
                    {"role": "system", "content": CLASSIFY_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 256,
                "temperature": 0.1,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            return None

        raw = resp.json()["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        if "<think>" in raw:
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = raw.strip()

        return json.loads(raw)

    except Exception:
        return None


def fetch_social_buzz(
    entity_name: str,
    search_terms: list[str],
) -> dict:
    """Quick social buzz scan via Gopher SN42 + Desearch SN22.

    Returns dict with post counts and sentiment bucketing.
    No per-post LLM classification — just keyword matching.
    """
    if not SOCIAL_AVAILABLE:
        return {"total": 0, "bullish": 0, "bearish": 0, "neutral": 0, "top_post": ""}

    # Query both sources
    gopher_posts = []
    desearch_posts = []
    try:
        gopher_posts = query_gopher(entity_name, search_terms)
    except Exception:
        pass
    try:
        desearch_posts = query_desearch(entity_name, search_terms, days_back=1, limit=20)
    except Exception:
        pass

    # Dedup by post_id
    seen_ids = set()
    all_posts = []
    for post in gopher_posts + desearch_posts:
        if post.post_id not in seen_ids:
            seen_ids.add(post.post_id)
            all_posts.append(post)

    # Bucket sentiment by keyword
    bullish = 0
    bearish = 0
    neutral = 0
    for post in all_posts:
        content_lower = post.content.lower()
        has_bear = any(kw in content_lower for kw in BEARISH_KEYWORDS)
        has_bull = any(kw in content_lower for kw in BULLISH_KEYWORDS)

        if has_bear and not has_bull:
            bearish += 1
        elif has_bull and not has_bear:
            bullish += 1
        else:
            neutral += 1

    # Pick top post (longest content as proxy for most informative)
    top_post = ""
    if all_posts:
        best = max(all_posts, key=lambda p: len(p.content))
        top_post = best.content[:120]

    return {
        "total": len(all_posts),
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "top_post": top_post,
    }


# ---------------------------------------------------------------------------
# SQLite database
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    """Initialise the equity movers database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equity_movers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_name     TEXT NOT NULL,
            idx             TEXT DEFAULT '',
            ticker          TEXT NOT NULL,
            sector          TEXT DEFAULT '',
            previous_close  REAL,
            current_price   REAL,
            change_pct      REAL,
            volume          INTEGER DEFAULT 0,
            avg_volume      INTEGER DEFAULT 0,
            volume_ratio    REAL DEFAULT 0,
            news_headlines  TEXT DEFAULT '[]',
            credit_impact   TEXT DEFAULT '',
            severity        INTEGER DEFAULT 0,
            explanation     TEXT DEFAULT '',
            detected_at     TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_movers_entity "
                 "ON equity_movers(entity_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_movers_date "
                 "ON equity_movers(detected_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_movers_change "
                 "ON equity_movers(change_pct)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_movers_idx "
                 "ON equity_movers(idx)")
    conn.commit()
    return conn


def store_mover(conn: sqlite3.Connection, mover: EquityMover) -> bool:
    """Store a mover. Returns True if new (not already recorded today)."""
    # Check if already recorded today for same entity
    today = datetime.now().strftime("%Y-%m-%d")
    existing = conn.execute(
        "SELECT 1 FROM equity_movers WHERE entity_name = ? "
        "AND detected_at LIKE ?",
        (mover.entity_name, f"{today}%"),
    ).fetchone()
    if existing:
        return False

    headlines_json = json.dumps(mover.news_headlines)
    conn.execute("""
        INSERT INTO equity_movers
            (entity_name, idx, ticker, sector, previous_close,
             current_price, change_pct, volume, avg_volume,
             volume_ratio, news_headlines, credit_impact,
             severity, explanation, detected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        mover.entity_name, mover.index, mover.ticker, mover.sector,
        mover.previous_close, mover.current_price, mover.change_pct,
        mover.volume, mover.avg_volume, mover.volume_ratio,
        headlines_json, mover.credit_impact, mover.severity,
        mover.explanation, mover.detected_at,
    ))
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Signal change logging
# ---------------------------------------------------------------------------

def log_signal_change(mover: EquityMover) -> None:
    """Append an equity mover signal to outputs/signal_changes.txt."""
    SIGNAL_CHANGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_name = mover.entity_name.encode("ascii", "replace").decode()
    idx_tag = "XO" if mover.index == "xover" else "IG"

    direction = "DOWN" if mover.change_pct < 0 else "UP"
    line = (
        f"[{timestamp}] [EQ] [{idx_tag}] {safe_name} | "
        f"{direction} {mover.change_pct:+.1f}% | "
        f"{mover.ticker} {mover.previous_close:.2f}->{mover.current_price:.2f}"
    )

    # Add top headline if available
    if mover.news_headlines:
        headline = mover.news_headlines[0].get("title", "")[:60]
        safe_headline = headline.encode("ascii", "replace").decode()
        line += f" | {safe_headline}"

    if mover.credit_impact:
        line += f" | impact={mover.credit_impact} sev={mover.severity}"

    line += "\n"

    with open(SIGNAL_CHANGES_PATH, "a") as f:
        f.write(line)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_scan(
    entity_filter: str | None = None,
    universe_filter: str = "all",
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    fetch_news: bool = True,
    classify: bool = False,
) -> list[EquityMover]:
    """Run the equity movers scan.

    Args:
        entity_filter: Partial entity name to filter.
        universe_filter: "all", "xover", or "main".
        threshold_pct: Minimum absolute % change to flag.
        fetch_news: Whether to fetch news for movers.
        classify: Whether to classify credit impact via LLM.
    """
    print()
    print("=" * 70)
    print("  EQUITY MOVERS MONITOR")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # Load tickers
    tickers = load_tickers(universe_filter)
    if entity_filter:
        tickers = [t for t in tickers
                   if entity_filter.lower() in t.entity_name.lower()
                   or entity_filter.lower() in t.search_name.lower()]
        if not tickers:
            print(f"  No entity matching '{entity_filter}'")
            return []

    n_xover = sum(1 for t in tickers if t.index == "xover")
    n_main = sum(1 for t in tickers if t.index == "main")
    print(f"  Tickers: {len(tickers)} (Xover={n_xover}, Main={n_main})")
    print(f"  Threshold: {threshold_pct:+.1f}%")
    print(f"  News lookup: {'ON' if fetch_news else 'OFF'}")
    print(f"  Classification: {'ON' if classify else 'OFF'}")
    print()

    # Fetch prices
    print(f"  Fetching prices from Yahoo Finance...")
    all_prices = fetch_prices(tickers)
    print(f"  Prices received: {len(all_prices)} of {len(tickers)}")

    # Filter to significant movers
    movers = [m for m in all_prices if abs(m.change_pct) >= threshold_pct]
    movers.sort(key=lambda m: abs(m.change_pct), reverse=True)

    if not movers:
        print(f"\n  No equity moves > {threshold_pct:.1f}% today.")
        # Still show top movers for context
        all_prices.sort(key=lambda m: abs(m.change_pct), reverse=True)
        if all_prices:
            print(f"\n  Top 10 moves (below threshold):")
            for m in all_prices[:10]:
                safe_name = m.entity_name[:25].encode("ascii", "replace").decode()
                idx_tag = "XO" if m.index == "xover" else "IG"
                arrow = "^" if m.change_pct > 0 else "v"
                print(f"    [{idx_tag}] {safe_name:<25} {m.ticker:<12} "
                      f"{m.change_pct:+5.1f}% {arrow} "
                      f"({m.previous_close:.2f}->{m.current_price:.2f})")
        return []

    print(f"\n  MOVERS DETECTED: {len(movers)} names > {threshold_pct:.1f}%")

    # Fetch news for each mover
    conn = init_db()

    if fetch_news:
        print(f"\n  Fetching news for {len(movers)} movers...")
        for mover in movers:
            # Use search_name from ticker info
            ticker_info = next(
                (t for t in tickers if t.ticker == mover.ticker), None
            )
            search_name = ticker_info.search_name if ticker_info else mover.entity_name

            news = fetch_news_for_mover(search_name)
            mover.news_headlines = news

            if news:
                safe_name = mover.entity_name[:25].encode("ascii", "replace").decode()
                print(f"    {safe_name}: {len(news)} headlines")

            time.sleep(0.5)

    # Optionally classify
    if classify:
        print(f"\n  Classifying credit impact for {len(movers)} movers...")
        for mover in movers:
            if not mover.news_headlines:
                continue

            result = classify_mover(
                mover.entity_name,
                mover.change_pct,
                mover.news_headlines,
            )

            if result:
                mover.credit_impact = result.get("credit_impact", "")
                mover.severity = int(result.get("severity", 0))
                mover.explanation = result.get("explanation", "")

            time.sleep(0.3)

    # Store and log
    new_count = 0
    for mover in movers:
        is_new = store_mover(conn, mover)
        if is_new:
            new_count += 1
            log_signal_change(mover)

    conn.close()

    # Print report
    _print_movers_report(movers, threshold_pct)

    print(f"\n  Stored: {new_count} new mover alerts")
    return movers


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def _print_movers_report(movers: list[EquityMover], threshold: float) -> None:
    """Print movers report to terminal."""
    W = 76
    print()
    print("  EQUITY MOVERS REPORT")
    print("  " + "=" * (W - 2))

    # Split into decliners and gainers
    decliners = sorted([m for m in movers if m.change_pct < 0],
                       key=lambda m: m.change_pct)
    gainers = sorted([m for m in movers if m.change_pct > 0],
                     key=lambda m: -m.change_pct)

    if decliners:
        print(f"\n  DECLINERS ({len(decliners)}):")
        print("  " + "-" * (W - 2))
        for m in decliners:
            safe_name = m.entity_name[:28].encode("ascii", "replace").decode()
            idx_tag = "XO" if m.index == "xover" else "IG"

            # Severity indicator
            if abs(m.change_pct) >= 10:
                sev = "!!!"
            elif abs(m.change_pct) >= 5:
                sev = "!! "
            else:
                sev = "!  "

            vol_str = f"vol={m.volume_ratio:.1f}x" if m.volume_ratio > 0 else ""

            print(f"\n  {sev} [{idx_tag}] {safe_name:<28} {m.ticker:<12} "
                  f"{m.change_pct:+6.1f}%  {vol_str}")
            print(f"       Price: {m.previous_close:.2f} -> {m.current_price:.2f}  "
                  f"| {m.sector}")

            if m.credit_impact:
                print(f"       Credit: {m.credit_impact} (sev={m.severity}/5) "
                      f"| {m.explanation[:50]}")

            for headline in m.news_headlines[:3]:
                safe_title = headline["title"][:65].encode("ascii", "replace").decode()
                print(f"       > {safe_title}")
                if headline.get("source"):
                    print(f"         ({headline['source']})")

    if gainers:
        print(f"\n  GAINERS ({len(gainers)}):")
        print("  " + "-" * (W - 2))
        for m in gainers:
            safe_name = m.entity_name[:28].encode("ascii", "replace").decode()
            idx_tag = "XO" if m.index == "xover" else "IG"

            vol_str = f"vol={m.volume_ratio:.1f}x" if m.volume_ratio > 0 else ""

            print(f"\n  [+] [{idx_tag}] {safe_name:<28} {m.ticker:<12} "
                  f"{m.change_pct:+6.1f}%  {vol_str}")
            print(f"       Price: {m.previous_close:.2f} -> {m.current_price:.2f}  "
                  f"| {m.sector}")

            if m.credit_impact:
                print(f"       Credit: {m.credit_impact} (sev={m.severity}/5) "
                      f"| {m.explanation[:50]}")

            for headline in m.news_headlines[:3]:
                safe_title = headline["title"][:65].encode("ascii", "replace").decode()
                print(f"       > {safe_title}")
                if headline.get("source"):
                    print(f"         ({headline['source']})")

    print()
    print("  " + "=" * (W - 2))
    print(f"  Total: {len(movers)} movers (threshold: {threshold:+.1f}%)")
    print(f"  Decliners: {len(decliners)} | Gainers: {len(gainers)}")

    # Flag HY decliners specifically (credit risk signal)
    hy_decliners = [m for m in decliners if m.index == "xover"]
    if hy_decliners:
        print(f"\n  *** {len(hy_decliners)} CROSSOVER (HY) DECLINERS — "
              f"WATCH FOR CDS WIDENING ***")
        for m in hy_decliners:
            safe_name = m.entity_name[:30].encode("ascii", "replace").decode()
            print(f"    -> {safe_name} {m.change_pct:+.1f}%")

    print()


def show_recent(
    days: int = 7,
    entity_filter: str | None = None,
    universe_filter: str = "all",
) -> None:
    """Show recent movers from the database."""
    if not DB_PATH.exists():
        print("  No equity movers database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    query = "SELECT * FROM equity_movers WHERE detected_at >= ?"
    params: list = [cutoff]

    if entity_filter:
        query += " AND entity_name LIKE ?"
        params.append(f"%{entity_filter}%")
    if universe_filter != "all":
        query += " AND idx = ?"
        params.append(universe_filter)

    query += " ORDER BY detected_at DESC, ABS(change_pct) DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print(f"  No equity movers in the last {days} days.")
        return

    W = 72
    print()
    print(f"  EQUITY MOVERS — Last {days} Days ({len(rows)} alerts)")
    print("  " + "=" * (W - 2))

    for r in rows[:30]:
        idx_tag = "XO" if r["idx"] == "xover" else "IG"
        safe_name = r["entity_name"][:28].encode("ascii", "replace").decode()
        direction = "DOWN" if r["change_pct"] < 0 else "UP  "

        print(f"\n  [{idx_tag}] {safe_name:<28} {r['ticker']:<12} "
              f"{direction} {r['change_pct']:+6.1f}%")
        print(f"       {r['previous_close']:.2f} -> {r['current_price']:.2f}  "
              f"| {r['detected_at'][:16]}")

        # Show headlines
        try:
            headlines = json.loads(r["news_headlines"] or "[]")
            for h in headlines[:2]:
                safe_title = h.get("title", "")[:60].encode("ascii", "replace").decode()
                print(f"       > {safe_title}")
        except json.JSONDecodeError:
            pass

    if len(rows) > 30:
        print(f"\n  ... showing 30 of {len(rows)} alerts")
    print()


def show_stats(universe_filter: str = "all") -> None:
    """Show aggregate statistics."""
    if not DB_PATH.exists():
        print("  No equity movers database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) as cnt FROM equity_movers").fetchone()["cnt"]

    by_index = conn.execute(
        "SELECT idx, COUNT(*) as cnt, AVG(change_pct) as avg_chg "
        "FROM equity_movers GROUP BY idx"
    ).fetchall()

    biggest_drops = conn.execute(
        "SELECT entity_name, idx, ticker, change_pct, detected_at "
        "FROM equity_movers ORDER BY change_pct ASC LIMIT 10"
    ).fetchall()

    biggest_gains = conn.execute(
        "SELECT entity_name, idx, ticker, change_pct, detected_at "
        "FROM equity_movers ORDER BY change_pct DESC LIMIT 10"
    ).fetchall()

    frequent = conn.execute(
        "SELECT entity_name, idx, COUNT(*) as cnt, "
        "AVG(change_pct) as avg_chg "
        "FROM equity_movers GROUP BY entity_name "
        "ORDER BY cnt DESC LIMIT 10"
    ).fetchall()

    conn.close()

    W = 65
    print()
    print(f"  EQUITY MOVERS — Statistics ({total} total alerts)")
    print("  " + "=" * W)

    print(f"\n  BY INDEX:")
    for r in by_index:
        label = "Xover (HY)" if r["idx"] == "xover" else "Main (IG)"
        print(f"    {label:<20} {r['cnt']:>5} alerts  avg={r['avg_chg']:+.1f}%")

    print(f"\n  BIGGEST DROPS:")
    for r in biggest_drops:
        idx_tag = "XO" if r["idx"] == "xover" else "IG"
        safe_name = r["entity_name"][:30].encode("ascii", "replace").decode()
        print(f"    [{idx_tag}] {safe_name:<30} {r['change_pct']:+6.1f}%  "
              f"{r['detected_at'][:10]}")

    print(f"\n  BIGGEST GAINS:")
    for r in biggest_gains:
        idx_tag = "XO" if r["idx"] == "xover" else "IG"
        safe_name = r["entity_name"][:30].encode("ascii", "replace").decode()
        print(f"    [{idx_tag}] {safe_name:<30} {r['change_pct']:+6.1f}%  "
              f"{r['detected_at'][:10]}")

    print(f"\n  MOST FREQUENT MOVERS:")
    for r in frequent:
        idx_tag = "XO" if r["idx"] == "xover" else "IG"
        safe_name = r["entity_name"][:30].encode("ascii", "replace").decode()
        print(f"    [{idx_tag}] {safe_name:<30} {r['cnt']:>3} alerts  "
              f"avg={r['avg_chg']:+.1f}%")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Equity Movers Monitor — real-time price alert scanner"
    )
    parser.add_argument("--entity", type=str, default=None,
                        help="Filter to entity (partial match)")
    parser.add_argument("--universe", type=str, default="all",
                        choices=["all", "xover", "main"],
                        help="Universe filter (default: all)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_PCT,
                        help=f"Min %% move to flag (default: {DEFAULT_THRESHOLD_PCT})")
    parser.add_argument("--status", action="store_true",
                        help="Show recent movers from database")
    parser.add_argument("--stats", action="store_true",
                        help="Show aggregate statistics")
    parser.add_argument("--days", type=int, default=7,
                        help="Lookback days for --status (default: 7)")
    parser.add_argument("--no-news", action="store_true",
                        help="Skip news lookup for movers")
    parser.add_argument("--classify", action="store_true",
                        help="Classify credit impact via LLM")
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

    # Run scan
    run_scan(
        entity_filter=args.entity,
        universe_filter=args.universe,
        threshold_pct=args.threshold,
        fetch_news=not args.no_news,
        classify=args.classify,
    )


if __name__ == "__main__":
    main()

"""
Social Sentiment Monitor -- Bittensor SN13 + Claude Credit Classifier

Monitors Twitter/X for credit-relevant social media posts about iTraxx
Xover names using the Macrocosmos SN13 on-demand data API, then classifies
each post through Claude with a credit-specific lens.

Pipeline:
    1. Query SN13 for recent X posts matching entity + credit keywords
    2. De-duplicate by post ID against SQLite history
    3. Classify each new post via Claude: sentiment, severity, novelty
    4. Log results to SQLite (data/social_sentiment.db)
    5. Flag high-severity items for alerting

Credit Keywords:
    restructuring, covenant, downgrade, default, LME, maturity,
    refinancing, distressed, bankruptcy, leverage, amendment, waiver,
    debt exchange, bondholder, credit event

Key Credit Twitter Accounts (configurable):
    @9aborad, @ResearchReorg, @debaborad, @CreditSights

Demo Mode:
    If MACROCOSMOS_API_KEY is not set in .env, runs with mock data
    so the full pipeline (de-dupe, classify, store) can be tested.

Usage:
    python -m monitors.social_sentiment                          # Full universe
    python -m monitors.social_sentiment --entity "INEOS Finance" # Single name
    python -m monitors.social_sentiment --watchlist              # Top conviction only
    python -m monitors.social_sentiment --status                 # Show recent alerts
    python -m monitors.social_sentiment --stats                  # Sentiment stats
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path("data/social_sentiment.db")
MODEL = "claude-sonnet-4-5-20250929"
TRIAGE_MODEL = "claude-3-5-haiku-20241022"
MAX_TOKENS = 1024

# Credit-specific search keywords
CREDIT_KEYWORDS = [
    "restructuring", "covenant", "downgrade", "default", "LME",
    "maturity", "refinancing", "distressed", "bankruptcy", "leverage",
    "amendment", "waiver", "debt exchange", "bondholder", "credit event",
    "CDS", "high yield", "junk bond", "fallen angel",
]

# Global noise terms -- never credit-relevant for any entity
NOISE_BLOCKLIST = [
    # Football / soccer
    "Manchester United", "Man Utd", "MUFC", "Premier League",
    "transfer window", "footballer", "signing players", "squad depth",
    "manager sacked", "Glazers", "Old Trafford", "OGC Nice", "Ligue 1",
    "Champions League goal", "Europa League",
    # Cycling
    "Grenadiers", "cycling", "Tour de France", "Giro d'Italia", "Vuelta",
    "Algarve", "peloton", "stage race", "GC contender", "domestique",
    "Vauquelin", "Vlasov",
    # Other sports / entertainment
    "Formula 1", "F1 team", "rugby", "sailing", "Americas Cup",
    "yacht race",
]

# Per-entity noise -- for names with big non-credit social footprints
ENTITY_NOISE = {
    "INEOS": [
        "Manchester United", "Man Utd", "MUFC", "Grenadiers", "cycling",
        "Ratcliffe football", "Old Trafford", "OGC Nice", "peloton",
        "Tour de France", "Algarve", "Americas Cup", "Vivell",
        "stage race", "Giro", "Vuelta",
        # Football-adjacent terms that rarely appear in credit context
        "transfer", "player", "footballer", "signing", "manager",
        "Tottenham", "Barcelona", "centre-back", "Maguire",
    ],
    "Nokia": ["phone", "smartphone", "Android", "mobile launch", "handset"],
    "TUI": [
        "holiday", "vacation", "flight delayed", "hotel review",
        "package deal", "all inclusive", "beach resort",
    ],
    "Air France": [
        "flight delayed", "lost luggage", "luggage", "boarding pass",
        "seat upgrade", "frequent flyer", "Flying Blue", "meal service",
        "cabin crew", "check-in", "baggage", "lounge access", "economy class",
        "business class", "turbulence", "runway", "departure gate",
    ],
    "Jaguar": [
        "car review", "test drive", "horsepower", "SUV", "Range Rover",
        "Defender", "F-Type", "electric vehicle launch", "showroom",
        "celebrity", "top speed", "MPG",
    ],
    "Renault": [
        "car review", "test drive", "Megane", "Clio", "Alpine F1",
        "Formula 1", "Grand Prix", "Dacia", "EV launch", "showroom",
        "horsepower", "hatchback",
    ],
    "Volvo": [
        "car review", "test drive", "safety rating", "XC90", "XC60",
        "EX90", "electric vehicle", "self-driving", "crash test",
        "family car", "SUV review",
    ],
    "Virgin Media": [
        "broadband speed", "wifi down", "router", "customer service",
        "TV package", "installation", "engineer visit", "buffering",
        "Branson", "Virgin Atlantic", "Virgin Galactic", "fibre optic",
    ],
    "Premier Foods": [
        "Mr Kipling", "Bisto", "Oxo", "recipe", "baking",
        "supermarket", "grocery", "cake", "pie", "cooking",
    ],
    "Ericsson": [
        "5G rollout", "network coverage", "cell tower", "antenna",
        "mobile network", "telecom infrastructure", "base station",
    ],
    "Telecom Italia": [
        "broadband speed", "wifi down", "customer service", "TIM mobile",
        "phone plan", "data plan", "coverage map", "roaming",
    ],
    "Lagardere": [
        "book launch", "publishing", "magazine", "airport lounge",
        "duty free", "travel retail", "bookstore", "Hachette",
    ],
    "SES": [
        "satellite TV", "signal lost", "dish alignment", "channel lineup",
        "set-top box", "Astra satellite", "TV reception",
    ],
    "Eutelsat": [
        "satellite TV", "OneWeb", "satellite broadband", "orbit",
        "space launch", "Starlink competitor", "dish installation",
    ],
}

# Key credit Twitter accounts to monitor
CREDIT_ACCOUNTS = [
    "9aborad",
    "ResearchReorg",
    "debaborad",
    "CreditSights",
    "RasijWadji",
    "JulienBittel",
    "AndreasSteno",
    "MikkelRosenvold",
    "jvisserlabs",
    "CrossBorderCap",
]

# Search aliases for entity names (short names for Twitter search)
ENTITY_ALIASES = {
    "INEOS Finance PLC": ["INEOS", "Ineos"],
    "INEOS Quattro Finance 2 Plc": ["INEOS Quattro", "Ineos Quattro"],
    "Kaixo Bondco Telecom SA": ["MasMovil", "Kaixo", "MasMóvil"],
    "Worldline SA/France": ["Worldline"],
    "Sunrise HoldCo IV BV": ["Sunrise", "Liberty Global"],
    "CECONOMY AG": ["CECONOMY", "MediaMarkt", "Saturn"],
    "Syngenta AG": ["Syngenta"],
    "Cirsa Finance International Sarl": ["Cirsa"],
    "Eutelsat SA": ["Eutelsat"],
    "Sherwood Financing PLC": ["Sherwood", "Camelot"],
    "SBB - Samhallsbyggnadsbolaget i Norden AB": ["SBB"],
    "TUI AG": ["TUI"],
    "Nokia Oyj": ["Nokia"],
    "Telecom Italia SpA/Milano": ["Telecom Italia", "TIM"],
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SocialPost:
    """A social media post with metadata."""
    post_id: str
    source: str           # "X", "Reddit", etc.
    author: str
    content: str
    posted_at: str        # ISO timestamp
    url: str
    entity_name: str      # Matched Xover entity
    keywords_matched: list[str] = field(default_factory=list)


@dataclass
class SentimentSignal:
    """Claude-classified sentiment signal."""
    post_id: str
    entity_name: str
    sentiment: str        # "bullish", "bearish", "neutral"
    severity: int         # 1-5 (1=noise, 5=material)
    is_new_info: bool     # Novel vs already known
    claim_summary: str    # Key claim/rumour
    credit_relevance: str # Why it matters for CDS spreads
    source_credibility: str  # "high", "medium", "low"
    raw_post: str
    author: str
    posted_at: str
    classified_at: str
    alert_worthy: bool    # severity >= 4


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS social_signals (
    signal_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         TEXT UNIQUE NOT NULL,
    entity_name     TEXT NOT NULL,
    sentiment       TEXT NOT NULL,
    severity        INTEGER NOT NULL,
    is_new_info     INTEGER NOT NULL DEFAULT 0,
    claim_summary   TEXT,
    credit_relevance TEXT,
    source_credibility TEXT,
    raw_post        TEXT,
    author          TEXT,
    source          TEXT DEFAULT 'X',
    posted_at       TEXT,
    classified_at   TEXT NOT NULL,
    alert_worthy    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_INDICES = """
CREATE INDEX IF NOT EXISTS idx_social_entity ON social_signals(entity_name);
CREATE INDEX IF NOT EXISTS idx_social_severity ON social_signals(severity);
CREATE INDEX IF NOT EXISTS idx_social_alert ON social_signals(alert_worthy);
CREATE INDEX IF NOT EXISTS idx_social_posted ON social_signals(posted_at);
CREATE INDEX IF NOT EXISTS idx_social_post_id ON social_signals(post_id);
"""


def get_connection() -> sqlite3.Connection:
    """Get SQLite connection, creating DB and tables if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(CREATE_TABLE)
    conn.executescript(CREATE_INDICES)
    return conn


def is_duplicate(conn: sqlite3.Connection, post_id: str) -> bool:
    """Check if we've already processed this post."""
    row = conn.execute(
        "SELECT 1 FROM social_signals WHERE post_id = ?", (post_id,)
    ).fetchone()
    return row is not None


def store_signal(conn: sqlite3.Connection, signal: SentimentSignal):
    """Store a classified signal to SQLite."""
    conn.execute("""
        INSERT OR IGNORE INTO social_signals (
            post_id, entity_name, sentiment, severity,
            is_new_info, claim_summary, credit_relevance,
            source_credibility, raw_post, author, source,
            posted_at, classified_at, alert_worthy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        signal.post_id, signal.entity_name, signal.sentiment,
        signal.severity, int(signal.is_new_info), signal.claim_summary,
        signal.credit_relevance, signal.source_credibility,
        signal.raw_post, signal.author, "X",
        signal.posted_at, signal.classified_at, int(signal.alert_worthy),
    ))
    conn.commit()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_watchlist() -> list[dict]:
    """Load top conviction names from latest portfolio."""
    portfolio_dir = Path("outputs/portfolio")
    if not portfolio_dir.exists():
        return []
    candidates = sorted(
        portfolio_dir.glob("portfolio_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return []
    with open(candidates[0]) as f:
        portfolio = json.load(f)
    # Top conviction names (conviction >= 4)
    return [
        p for p in portfolio.get("top_positions", [])
        if p.get("conviction", 0) >= 4
    ]


def load_universe_names() -> list[str]:
    """Load all 75 Xover entity names."""
    path = Path("indices/xover_s44.json")
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    names = []
    for sector, sector_names in data.get("sectors", {}).items():
        names.extend(sector_names)
    return names


def get_search_terms(entity_name: str) -> list[str]:
    """Get search terms for an entity (aliases + base name)."""
    terms = ENTITY_ALIASES.get(entity_name, [])
    if not terms:
        # Extract a short name from the full legal name
        short = entity_name.split(" ")[0]
        if len(short) > 2:
            terms = [short]
        else:
            terms = [entity_name]
    return terms


def is_credit_noise(post: SocialPost) -> bool:
    """Fast pre-filter to reject obviously non-credit posts.

    Returns True if the post should be SKIPPED (is noise).
    Safety valve: posts matching any CREDIT_KEYWORDS always pass through.
    """
    content_lower = post.content.lower()

    if not content_lower.strip():
        return False  # Don't filter empty posts, let Claude decide

    # Safety valve: any credit keyword present = always pass through
    for kw in CREDIT_KEYWORDS:
        if kw.lower() in content_lower:
            return False

    # Check global noise blocklist
    is_noisy = False
    for term in NOISE_BLOCKLIST:
        if term.lower() in content_lower:
            is_noisy = True
            break

    # Check per-entity noise (match against search aliases)
    if not is_noisy:
        for alias_key, noise_terms in ENTITY_NOISE.items():
            if alias_key.lower() in post.entity_name.lower():
                for term in noise_terms:
                    if term.lower() in content_lower:
                        is_noisy = True
                        break
                break  # Only check one entity match

    return is_noisy


def is_noisy_entity(entity_name: str) -> bool:
    """Check if an entity is in the ENTITY_NOISE map (has a big non-credit footprint)."""
    entity_lower = entity_name.lower()
    return any(alias.lower() in entity_lower for alias in ENTITY_NOISE)


def has_credit_keyword(content: str) -> bool:
    """Check if content contains any credit keyword."""
    content_lower = content.lower()
    return any(kw.lower() in content_lower for kw in CREDIT_KEYWORDS)


TRIAGE_PROMPT = """You are a credit analyst gatekeeper. Determine if this social media post is about the CORPORATE CREDIT entity or about something unrelated (sports team, consumer product, entertainment).

Entity: {entity_name}
Post: {content}

Reply with ONLY one word: CREDIT or NOISE"""


def haiku_triage(post: SocialPost) -> bool:
    """Cheap Haiku pre-screen for ambiguous posts from noisy entities.

    Returns True if the post should PASS through to full classification.
    Returns False if Haiku says it's noise.
    Cost: ~$0.0003 per call (30x cheaper than Sonnet classification).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return True  # If no API key, let it through

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=TRIAGE_MODEL,
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": TRIAGE_PROMPT.format(
                    entity_name=post.entity_name,
                    content=post.content[:300],  # Truncate to save tokens
                ),
            }],
        )
        answer = response.content[0].text.strip().upper()
        return "CREDIT" in answer
    except Exception as e:
        print(f"  Haiku triage error: {e}", file=sys.stderr)
        return True  # On error, let it through to Sonnet


# ---------------------------------------------------------------------------
# SN13 API queries
# ---------------------------------------------------------------------------

def query_sn13(
    entity_name: str,
    search_terms: list[str],
    days_back: int = 3,
    limit: int = 50,
) -> list[SocialPost]:
    """Query Macrocosmos SN13 for recent X posts about an entity.

    Returns list of SocialPost objects.
    """
    api_key = os.getenv("MACROCOSMOS_API_KEY")
    if not api_key:
        return []  # Will fall back to demo mode

    try:
        import macrocosmos as mc
        client = mc.Sn13Client(api_key=api_key, app_name="apex-s44-monitor")

        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        # Combine entity terms with credit keywords for targeted search
        keywords = []
        for term in search_terms[:2]:  # Limit to top 2 aliases
            for kw in CREDIT_KEYWORDS[:8]:  # Top 8 most relevant keywords
                keywords.append(f"{term} {kw}")

        # Also search by entity name alone
        keywords.extend(search_terms[:2])

        response = client.sn13.OnDemandData(
            source="X",
            keywords=keywords,
            start_date=start_date,
            limit=limit,
            keyword_mode="any",
        )

        posts = []
        items = response.get("data", []) if isinstance(response, dict) else []

        for item in items:
            # SDK v3.1.0 field mapping
            tweet_data = item.get("tweet", {})
            user_data = item.get("user", {})
            post_id = str(tweet_data.get("id", item.get("id", f"sn13_{hash(str(item))}")))
            content = item.get("text", item.get("content", ""))
            author = user_data.get("username", item.get("username", "unknown"))
            posted_at = item.get("datetime", item.get("created_at", ""))
            url = item.get("uri", item.get("url", ""))

            # Check which credit keywords are present
            content_lower = content.lower()
            matched = [
                kw for kw in CREDIT_KEYWORDS
                if kw.lower() in content_lower
            ]

            posts.append(SocialPost(
                post_id=post_id,
                source="X",
                author=author,
                content=content,
                posted_at=posted_at,
                url=url,
                entity_name=entity_name,
                keywords_matched=matched,
            ))

        return posts

    except Exception as e:
        print(f"  SN13 API error for {entity_name}: {e}", file=sys.stderr)
        return []


def query_sn13_accounts(
    days_back: int = 3,
    limit: int = 100,
) -> list[SocialPost]:
    """Query SN13 for posts from key credit Twitter accounts.

    Note: SDK v3.1.0 has intermittent gRPC stream failures.
    This function retries up to 2 times, using credit-relevant
    keyword combinations with account names to surface their posts.
    """
    api_key = os.getenv("MACROCOSMOS_API_KEY")
    if not api_key:
        return []

    import macrocosmos as mc

    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # Search for posts mentioning these accounts + credit keywords
    # Split into small batches to avoid overloading gRPC stream
    all_posts = []
    for batch_start in range(0, len(CREDIT_ACCOUNTS), 3):
        batch = CREDIT_ACCOUNTS[batch_start:batch_start + 3]
        keywords = batch  # Account names as keywords

        for attempt in range(2):
            try:
                client = mc.Sn13Client(api_key=api_key, app_name="apex-s44-monitor")
                response = client.sn13.OnDemandData(
                    source="X",
                    keywords=keywords,
                    start_date=start_date,
                    limit=limit // max(1, len(CREDIT_ACCOUNTS) // 3),
                    keyword_mode="any",
                )

                items = response.get("data", []) if isinstance(response, dict) else []

                for item in items:
                    tweet_data = item.get("tweet", {})
                    user_data = item.get("user", {})
                    post_id = str(tweet_data.get("id", item.get("id", f"sn13_{hash(str(item))}")))
                    content = item.get("text", item.get("content", ""))
                    author = user_data.get("username", item.get("username", "unknown"))
                    posted_at = item.get("datetime", item.get("created_at", ""))
                    url = item.get("uri", item.get("url", ""))

                    all_posts.append(SocialPost(
                        post_id=post_id,
                        source="X",
                        author=author,
                        content=content,
                        posted_at=posted_at,
                        url=url,
                        entity_name="",  # Will be matched by Claude
                        keywords_matched=[],
                    ))

                break  # Success, move to next batch

            except Exception as e:
                if attempt == 0:
                    time.sleep(1)  # Brief pause before retry
                else:
                    print(f"  SN13 accounts batch {batch}: {e}", file=sys.stderr)

        time.sleep(0.5)  # Rate limit between batches

    return all_posts


# ---------------------------------------------------------------------------
# Demo mode -- mock data for testing without API key
# ---------------------------------------------------------------------------

DEMO_POSTS = [
    SocialPost(
        post_id="demo_001",
        source="X",
        author="@ResearchReorg",
        content=(
            "INEOS Quattro - hearing the 2027 secured notes refinancing "
            "is being actively marketed to a club of 5 banks. Price talk "
            "suggests 300bp over, which would be a significant tightening "
            "from current CDS levels. Positive for recovery thesis."
        ),
        posted_at="2026-02-19T14:30:00Z",
        url="https://x.com/ResearchReorg/status/demo001",
        entity_name="INEOS Quattro Finance 2 Plc",
        keywords_matched=["refinancing"],
    ),
    SocialPost(
        post_id="demo_002",
        source="X",
        author="@9aborad",
        content=(
            "Worldline SA covenant review: Q4 numbers show adjusted "
            "leverage at 3.8x, just inside the 4.0x maintenance test. "
            "Headroom is razor thin. Any earnings miss in Q1 could "
            "trigger a waiver request. Watch the March board meeting."
        ),
        posted_at="2026-02-19T11:15:00Z",
        url="https://x.com/9aborad/status/demo002",
        entity_name="Worldline SA/France",
        keywords_matched=["covenant", "leverage", "waiver"],
    ),
    SocialPost(
        post_id="demo_003",
        source="X",
        author="@CreditSights",
        content=(
            "CECONOMY AG - we see limited downside risk to the credit "
            "at 64bp CDS. Strong free cash flow generation and net cash "
            "balance sheet make this name mispriced vs BB peers trading "
            "150-200bp. Potential upgrade candidate."
        ),
        posted_at="2026-02-18T16:45:00Z",
        url="https://x.com/CreditSights/status/demo003",
        entity_name="CECONOMY AG",
        keywords_matched=["downgrade"],
    ),
    SocialPost(
        post_id="demo_004",
        source="X",
        author="@debaborad",
        content=(
            "Cirsa Finance - Spanish gaming regulator proposing new "
            "online gambling tax that could hit EBITDA by 8-12%. "
            "Management on call said 'we are monitoring the situation'. "
            "CDS at 200bp doesn't price this in. Could see 250-280bp."
        ),
        posted_at="2026-02-19T09:20:00Z",
        url="https://x.com/debaborad/status/demo004",
        entity_name="Cirsa Finance International Sarl",
        keywords_matched=["leverage"],
    ),
    SocialPost(
        post_id="demo_005",
        source="X",
        author="@ResearchReorg",
        content=(
            "ALERT: SBB i Norden AB - Moody's has placed the corporate "
            "family rating on review for downgrade. Cited 'weakening "
            "liquidity profile and increasing refinancing risk for the "
            "EUR 1.2bn 2027 maturity wall'. CDS should gap wider."
        ),
        posted_at="2026-02-19T08:00:00Z",
        url="https://x.com/ResearchReorg/status/demo005",
        entity_name="SBB - Samhallsbyggnadsbolaget i Norden AB",
        keywords_matched=["downgrade", "refinancing", "maturity"],
    ),
    SocialPost(
        post_id="demo_006",
        source="X",
        author="@9aborad",
        content=(
            "Kaixo Bondco / MasMovil - remarkable credit improvement "
            "story. Organic deleveraging on track for sub-4x by mid-2026. "
            "At 50bp CDS this is trading through BB index. Rising star "
            "candidate for the next index roll in March."
        ),
        posted_at="2026-02-18T13:00:00Z",
        url="https://x.com/9aborad/status/demo006",
        entity_name="Kaixo Bondco Telecom SA",
        keywords_matched=["leverage", "fallen angel"],
    ),
    SocialPost(
        post_id="demo_007",
        source="X",
        author="@CreditSights",
        content=(
            "iTraxx Xover technicals: March roll approaching, 3 names "
            "likely to exit (risen to IG). New entrants from BBB "
            "downgrade pipeline include 2 auto sector names. Expect "
            "index to widen 10-15bp purely on composition changes."
        ),
        posted_at="2026-02-18T10:30:00Z",
        url="https://x.com/CreditSights/status/demo007",
        entity_name="iTraxx Xover Index",
        keywords_matched=["fallen angel", "downgrade"],
    ),
    SocialPost(
        post_id="demo_008",
        source="X",
        author="@ResearchReorg",
        content=(
            "INEOS Finance PLC - Jim Ratcliffe comments at Davos suggest "
            "the group is exploring asset disposals to reduce debt at the "
            "holdco level. Petrochemicals division being shopped. This "
            "would be credit positive for the senior secured."
        ),
        posted_at="2026-02-17T15:45:00Z",
        url="https://x.com/ResearchReorg/status/demo008",
        entity_name="INEOS Finance PLC",
        keywords_matched=["distressed", "leverage"],
    ),
]


def get_demo_posts(entity_filter: str | None = None) -> list[SocialPost]:
    """Return mock posts for demo mode testing."""
    if entity_filter:
        filter_lower = entity_filter.lower()
        return [
            p for p in DEMO_POSTS
            if filter_lower in p.entity_name.lower()
            or any(filter_lower in alias.lower()
                   for alias in ENTITY_ALIASES.get(p.entity_name, []))
        ]
    return list(DEMO_POSTS)


# ---------------------------------------------------------------------------
# Claude classification
# ---------------------------------------------------------------------------

CLASSIFICATION_SYSTEM = """You are a credit analyst classifying social media posts about European high-yield corporate credits. You focus on the iTraxx Crossover (Xover) universe of 75 names.

For each post, assess:
1. CREDIT SENTIMENT: Is this bullish (spread tightening), bearish (spread widening), or neutral for the company's CDS?
2. SEVERITY (1-5):
   1 = noise/opinion with no substance
   2 = minor colour, confirms known narrative
   3 = meaningful data point, could move spreads 5-10bp
   4 = material information, likely to move spreads 10-25bp
   5 = critical/breaking, could move spreads 25bp+ (rating action, default, restructuring)
3. NOVELTY: Is this genuinely new information or rehashing known facts?
4. CLAIM SUMMARY: One-sentence summary of the key claim or rumour
5. CREDIT RELEVANCE: Why does this matter for CDS spreads specifically?
6. SOURCE CREDIBILITY: Based on the author, is this high/medium/low credibility?

Known high-credibility credit accounts: @9aborad, @ResearchReorg, @debaborad, @CreditSights

Respond in strict JSON format:
{
    "sentiment": "bullish" | "bearish" | "neutral",
    "severity": 1-5,
    "is_new_info": true | false,
    "claim_summary": "...",
    "credit_relevance": "...",
    "source_credibility": "high" | "medium" | "low"
}"""


def classify_post(post: SocialPost) -> SentimentSignal | None:
    """Classify a social media post using Claude."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("  Warning: ANTHROPIC_API_KEY not set, skipping classification",
              file=sys.stderr)
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)

        user_msg = (
            f"Entity: {post.entity_name}\n"
            f"Author: {post.author}\n"
            f"Posted: {post.posted_at}\n"
            f"Credit keywords matched: {', '.join(post.keywords_matched) or 'none'}\n"
            f"\nPost content:\n{post.content}"
        )

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=CLASSIFICATION_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )

        raw = response.content[0].text.strip()

        # Strip code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        # Use raw_decode to extract first JSON object, ignoring trailing text
        decoder = json.JSONDecoder()
        json_start = raw.find("{")
        if json_start == -1:
            raise json.JSONDecodeError("No JSON object found", raw, 0)
        result, _ = decoder.raw_decode(raw, json_start)

        severity = int(result.get("severity", 1))
        sentiment = result.get("sentiment", "neutral")

        return SentimentSignal(
            post_id=post.post_id,
            entity_name=post.entity_name,
            sentiment=sentiment,
            severity=severity,
            is_new_info=bool(result.get("is_new_info", False)),
            claim_summary=result.get("claim_summary", ""),
            credit_relevance=result.get("credit_relevance", ""),
            source_credibility=result.get("source_credibility", "medium"),
            raw_post=post.content,
            author=post.author,
            posted_at=post.posted_at,
            classified_at=datetime.now().isoformat(),
            alert_worthy=severity >= 4,
        )

    except json.JSONDecodeError as e:
        print(f"  JSON parse error for {post.post_id}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Classification error for {post.post_id}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_scan(
    entity_filter: str | None = None,
    watchlist_only: bool = False,
    demo_mode: bool = False,
    dry_run: bool = False,
) -> list[SentimentSignal]:
    """Run the full social sentiment scan pipeline.

    1. Fetch posts from SN13 (or demo data)
    2. De-duplicate against SQLite
    3. Classify via Claude
    4. Store results
    5. Return signals
    """
    has_api_key = bool(os.getenv("MACROCOSMOS_API_KEY"))
    if not has_api_key:
        demo_mode = True
        print("  [DEMO MODE] MACROCOSMOS_API_KEY not set -- using mock data")

    conn = get_connection()

    # Determine which entities to scan
    if entity_filter:
        entities = [entity_filter]
    elif watchlist_only:
        watchlist = load_watchlist()
        entities = [p["entity_name"] for p in watchlist]
        print(f"  Watchlist: {len(entities)} names (conviction >= 4)")
    else:
        entities = load_universe_names()
        print(f"  Universe: {len(entities)} names")

    all_posts: list[SocialPost] = []

    if demo_mode:
        all_posts = get_demo_posts(entity_filter)
        print(f"  Demo posts: {len(all_posts)}")
    else:
        # Query SN13 per entity
        for entity in entities:
            search_terms = get_search_terms(entity)
            posts = query_sn13(entity, search_terms)
            all_posts.extend(posts)
            if posts:
                print(f"  {entity[:35]:<35} {len(posts):>3} posts")
            time.sleep(0.5)  # Rate limit

        # Also query key credit accounts
        account_posts = query_sn13_accounts()
        if account_posts:
            all_posts.extend(account_posts)
            print(f"  Credit accounts (@9aborad etc)   {len(account_posts):>3} posts")

    # De-duplicate
    new_posts = []
    skipped = 0
    for post in all_posts:
        if is_duplicate(conn, post.post_id):
            skipped += 1
        else:
            new_posts.append(post)

    # Pre-filter stage 1: drop obvious noise via keyword matching
    filtered_posts = []
    noise_count = 0
    ambiguous_posts = []
    for post in new_posts:
        if is_credit_noise(post):
            noise_count += 1
        elif is_noisy_entity(post.entity_name) and not has_credit_keyword(post.content):
            ambiguous_posts.append(post)  # Needs Haiku triage
        else:
            filtered_posts.append(post)

    # Pre-filter stage 2: Haiku triage for ambiguous posts from noisy entities
    haiku_passed = 0
    haiku_dropped = 0
    if ambiguous_posts and not dry_run:
        print(f"\n  Haiku triage: {len(ambiguous_posts)} ambiguous posts...")
        for post in ambiguous_posts:
            if haiku_triage(post):
                filtered_posts.append(post)
                haiku_passed += 1
                print(f"    CREDIT: [{post.entity_name[:25]}] {post.content[:60]}...")
            else:
                haiku_dropped += 1
                print(f"    NOISE:  [{post.entity_name[:25]}] {post.content[:60]}...")
            time.sleep(0.2)  # Rate limit

    print(f"\n  Total posts: {len(all_posts)} | New: {len(new_posts)} | "
          f"Duplicates skipped: {skipped} | Noise filtered: {noise_count} | "
          f"Haiku triaged: {len(ambiguous_posts)} (passed={haiku_passed}, dropped={haiku_dropped}) | "
          f"Sent to Sonnet: {len(filtered_posts)}")

    if dry_run:
        print(f"\n  [DRY RUN] Would send {len(filtered_posts)} posts to Sonnet:")
        for p in filtered_posts:
            print(f"    PASS: [{p.entity_name[:25]}] {p.content[:80]}...")
        print(f"\n  [DRY RUN] Would SKIP {noise_count} noise posts:")
        for post in new_posts:
            if is_credit_noise(post):
                print(f"    SKIP: [{post.entity_name[:25]}] {post.content[:80]}...")
        if ambiguous_posts:
            print(f"\n  [DRY RUN] Would Haiku-triage {len(ambiguous_posts)} ambiguous posts:")
            for post in ambiguous_posts:
                print(f"    TRIAGE: [{post.entity_name[:25]}] {post.content[:80]}...")
        conn.close()
        return []

    if not filtered_posts:
        print("  No posts to classify after noise filter.")
        conn.close()
        return []

    # Classify through Claude
    signals = []
    print(f"\n  Classifying {len(filtered_posts)} posts through Claude...")

    for i, post in enumerate(filtered_posts):
        signal = classify_post(post)
        if signal:
            store_signal(conn, signal)
            signals.append(signal)
            try:
                from data.entity_profile_manager import update_profile
                update_profile(signal.entity_name, "social_sentiment", {
                    "post_id": signal.post_id,
                    "sentiment": signal.sentiment,
                    "severity": signal.severity,
                    "is_new_info": signal.is_new_info,
                    "claim_summary": signal.claim_summary,
                    "credit_relevance": signal.credit_relevance,
                    "author": signal.author,
                    "posted_at": signal.posted_at,
                })
            except Exception:
                pass  # Profile update is non-critical
            # Progress indicator
            severity_icon = {
                1: ".", 2: "o", 3: "*", 4: "!", 5: "!!",
            }.get(signal.severity, "?")
            print(f"  [{i+1}/{len(filtered_posts)}] {severity_icon} "
                  f"{signal.entity_name[:30]:<30} "
                  f"{signal.sentiment:<8} sev={signal.severity} "
                  f"{'NEW' if signal.is_new_info else 'known'}")

        # Brief pause between API calls
        if i < len(filtered_posts) - 1:
            time.sleep(0.3)

    conn.close()

    # Summary
    alerts = [s for s in signals if s.alert_worthy]
    if alerts:
        print(f"\n  {'='*70}")
        print(f"  ALERT: {len(alerts)} high-severity signals detected!")
        print(f"  {'='*70}")
        for a in alerts:
            print(f"\n  [{a.severity}/5] {a.entity_name}")
            print(f"  {a.claim_summary}")
            print(f"  Sentiment: {a.sentiment} | Source: {a.author} | "
                  f"Credibility: {a.source_credibility}")
            if a.credit_relevance:
                print(f"  Relevance: {a.credit_relevance}")

    return signals


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def show_recent(days: int = 7, entity_filter: str | None = None):
    """Show recent signals from the database."""
    conn = get_connection()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    query = "SELECT * FROM social_signals WHERE classified_at > ?"
    params = [cutoff]

    if entity_filter:
        query += " AND entity_name LIKE ?"
        params.append(f"%{entity_filter}%")

    query += " ORDER BY severity DESC, classified_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print(f"\nNo signals in the last {days} days.")
        return

    alerts = [r for r in rows if r["alert_worthy"]]
    bearish = [r for r in rows if r["sentiment"] == "bearish"]
    bullish = [r for r in rows if r["sentiment"] == "bullish"]

    print(f"\n{'='*90}")
    print(f"  SOCIAL SENTIMENT -- RECENT SIGNALS ({len(rows)} total | "
          f"last {days} days)")
    print(f"  Alerts: {len(alerts)} | Bearish: {len(bearish)} | "
          f"Bullish: {len(bullish)}")
    print(f"{'='*90}")

    print(f"\n  {'Sev':>3}  {'Entity':<32} {'Sent':<8} {'New':>3} "
          f"{'Author':<18} {'Summary':<40}")
    print(f"  {'-'*3}  {'-'*32} {'-'*8} {'-'*3} {'-'*18} {'-'*40}")

    for r in rows:
        new_str = "NEW" if r["is_new_info"] else ""
        severity_marker = ">>>" if r["severity"] >= 4 else "   "
        print(f"  {severity_marker}{r['severity']}  "
              f"{r['entity_name'][:32]:<32} "
              f"{r['sentiment']:<8} {new_str:>3} "
              f"{r['author'][:18]:<18} "
              f"{(r['claim_summary'] or '')[:40]}")

    print(f"\n{'='*90}")


def show_stats():
    """Show aggregate sentiment statistics."""
    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) as n FROM social_signals").fetchone()["n"]
    if total == 0:
        print("\nNo signals in database. Run a scan first.")
        conn.close()
        return

    # By sentiment
    sentiments = conn.execute(
        "SELECT sentiment, COUNT(*) as n FROM social_signals GROUP BY sentiment"
    ).fetchall()

    # By severity
    severities = conn.execute(
        "SELECT severity, COUNT(*) as n FROM social_signals GROUP BY severity ORDER BY severity"
    ).fetchall()

    # By entity (top 10)
    entities = conn.execute("""
        SELECT entity_name, COUNT(*) as n,
            AVG(severity) as avg_sev,
            SUM(CASE WHEN sentiment='bearish' THEN 1 ELSE 0 END) as bearish,
            SUM(CASE WHEN sentiment='bullish' THEN 1 ELSE 0 END) as bullish
        FROM social_signals
        GROUP BY entity_name
        ORDER BY n DESC
        LIMIT 10
    """).fetchall()

    # Alerts
    alert_count = conn.execute(
        "SELECT COUNT(*) as n FROM social_signals WHERE alert_worthy = 1"
    ).fetchone()["n"]
    new_info = conn.execute(
        "SELECT COUNT(*) as n FROM social_signals WHERE is_new_info = 1"
    ).fetchone()["n"]

    conn.close()

    print(f"\n{'='*70}")
    print(f"  SOCIAL SENTIMENT -- STATISTICS")
    print(f"{'='*70}")
    print(f"  Total signals:     {total}")
    print(f"  Alerts (sev>=4):   {alert_count}")
    print(f"  New information:   {new_info} ({new_info/total*100:.0f}%)")

    print(f"\n  SENTIMENT BREAKDOWN:")
    for s in sentiments:
        pct = s["n"] / total * 100
        bar = "#" * int(pct / 2)
        print(f"    {s['sentiment']:<10} {s['n']:>4} ({pct:>4.0f}%) {bar}")

    print(f"\n  SEVERITY BREAKDOWN:")
    for s in severities:
        pct = s["n"] / total * 100
        bar = "#" * int(pct / 2)
        label = {1: "noise", 2: "colour", 3: "meaningful",
                 4: "material", 5: "critical"}.get(s["severity"], "?")
        print(f"    {s['severity']}/5 {label:<12} {s['n']:>4} ({pct:>4.0f}%) {bar}")

    print(f"\n  TOP ENTITIES:")
    print(f"  {'Entity':<35} {'Posts':>5} {'Avg Sev':>8} {'Bear':>5} {'Bull':>5}")
    print(f"  {'-'*35} {'-'*5} {'-'*8} {'-'*5} {'-'*5}")
    for e in entities:
        print(f"  {e['entity_name'][:35]:<35} {e['n']:>5} "
              f"{e['avg_sev']:>7.1f} {e['bearish']:>5} {e['bullish']:>5}")

    print(f"\n{'='*70}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Social Sentiment Monitor -- Bittensor SN13 + Claude"
    )
    parser.add_argument(
        "--entity", type=str, default=None,
        help="Scan a specific entity (partial match)",
    )
    parser.add_argument(
        "--watchlist", action="store_true",
        help="Scan top conviction names only (conviction >= 4)",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show recent signals from database",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show aggregate sentiment statistics",
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Days of history to show (for --status)",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Force demo mode (use mock data)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be filtered vs sent to Claude (no API calls)",
    )
    args = parser.parse_args()

    if args.status:
        show_recent(days=args.days, entity_filter=args.entity)
        return

    if args.stats:
        show_stats()
        return

    # Run scan
    print(f"\n{'='*70}")
    print(f"  SOCIAL SENTIMENT MONITOR")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    signals = run_scan(
        entity_filter=args.entity,
        watchlist_only=args.watchlist,
        demo_mode=args.demo,
        dry_run=args.dry_run,
    )

    print(f"\n  Scan complete: {len(signals)} signals classified")
    alerts = [s for s in signals if s.alert_worthy]
    if alerts:
        print(f"  {len(alerts)} ALERT-WORTHY signals flagged")
    print(f"\n  Use --status to view stored signals")
    print(f"  Use --stats for aggregate statistics")


if __name__ == "__main__":
    main()

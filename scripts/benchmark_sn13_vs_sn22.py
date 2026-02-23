"""
SN13 vs SN22 Benchmark -- Compare Bittensor data sources for credit social data

Compares Macrocosmos SN13 and Desearch SN22 across:
  - Coverage (total posts, unique posts per source)
  - Signal quality (credit keyword hit rate vs noise rate)
  - Freshness (median age, newest post)

Usage:
    python -m scripts.benchmark_sn13_vs_sn22 --entity "INEOS" --demo
    python -m scripts.benchmark_sn13_vs_sn22 --all-noisy
    python -m scripts.benchmark_sn13_vs_sn22 --entity "INEOS" --days 5 --limit 100
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from types import ModuleType

# ---------------------------------------------------------------------------
# Stub heavy optional deps so we can import monitors.social_sentiment
# without requiring macrocosmos / anthropic / dotenv to be installed.
# ---------------------------------------------------------------------------
for _mod in ["macrocosmos", "anthropic", "dotenv"]:
    if _mod not in sys.modules:
        _stub = ModuleType(_mod)
        if _mod == "dotenv":
            _stub.load_dotenv = lambda **kw: None
        sys.modules[_mod] = _stub

from monitors.social_sentiment import (
    SocialPost,
    is_credit_noise,
    has_credit_keyword,
    is_noisy_entity,
    ENTITY_ALIASES,
    CREDIT_KEYWORDS,
    ENTITY_NOISE,
    get_search_terms,
    get_demo_posts,
)


# ---------------------------------------------------------------------------
# SN22 (Desearch) query
# ---------------------------------------------------------------------------

def query_desearch(
    entity_name: str,
    aliases: list,
    keywords: list,
    days_back: int = 3,
    limit: int = 50,
) -> list[SocialPost]:
    """Query Desearch SN22 API for recent X posts about an entity.

    REST client for https://api.desearch.ai/twitter
    Auth via DESEARCH_API_KEY env var.
    Returns list of SocialPost objects, or empty list on error.
    """
    api_key = os.getenv("DESEARCH_API_KEY")
    if not api_key:
        return []

    try:
        import requests
    except ImportError:
        print("  Warning: requests library not installed, cannot query Desearch",
              file=sys.stderr)
        return []

    # Build query: top 2 aliases OR-joined with top 8 credit keywords
    query_parts = []
    for alias in aliases[:2]:
        for kw in keywords[:8]:
            query_parts.append(f"{alias} {kw}")
    # Also add bare aliases
    query_parts.extend(aliases[:2])
    query_string = " OR ".join(query_parts)

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days_back)

    params = {
        "query": query_string,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "count": limit,
        "sort": "Top",
        "lang": "en",
    }
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.get(
            "https://api.desearch.ai/twitter",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Warning: Desearch API error for {entity_name}: {e}",
              file=sys.stderr)
        return []

    # Normalize response to SocialPost objects
    items = data if isinstance(data, list) else data.get("data", data.get("results", []))
    posts = []
    for item in items:
        post_id = str(item.get("id", item.get("tweet_id", f"sn22_{hash(str(item))}")))
        content = item.get("text", item.get("content", item.get("full_text", "")))
        author = item.get("username", item.get("user", {}).get("screen_name", "unknown"))
        url = item.get("url", item.get("uri", f"https://x.com/{author}/status/{post_id}"))

        # Robust timestamp parsing
        raw_ts = item.get("created_at", item.get("datetime", item.get("timestamp", "")))
        posted_at = _parse_timestamp(raw_ts)

        content_lower = content.lower()
        matched = [kw for kw in CREDIT_KEYWORDS if kw.lower() in content_lower]

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


def _parse_timestamp(raw: str) -> str:
    """Parse various timestamp formats into ISO-8601 string."""
    if not raw:
        return datetime.utcnow().isoformat() + "Z"

    # Already ISO-like
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        # Twitter-style: "Mon Feb 17 15:45:00 +0000 2026"
        "%a %b %d %H:%M:%S %z %Y",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue

    # Fallback: return raw, let downstream handle it
    return raw


# ---------------------------------------------------------------------------
# Demo data for SN22
# ---------------------------------------------------------------------------

def get_demo_sn22_results(entity_name: str = "INEOS") -> list[SocialPost]:
    """Generate realistic mock SN22 data when DESEARCH_API_KEY is not set.

    Creates ~40 posts with a mix of:
      - Credit-relevant posts (some overlapping with SN13 demo by post_id)
      - Noise posts (sports, consumer products)
      - Ambiguous posts (neither clear signal nor clear noise)
    """
    now = datetime.utcnow()
    entity_lower = entity_name.lower()

    # --- Posts that overlap with SN13 demo data (same post_id) ---
    overlap_posts = [
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
            posted_at=(now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/ResearchReorg/status/demo001",
            entity_name=entity_name,
            keywords_matched=["refinancing"],
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
            posted_at=(now - timedelta(hours=38)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/ResearchReorg/status/demo008",
            entity_name=entity_name,
            keywords_matched=["distressed", "leverage"],
        ),
    ]

    # --- Credit-signal posts unique to SN22 ---
    credit_posts = [
        SocialPost(
            post_id="sn22_cr_001",
            source="X",
            author="@debaborad",
            content=(
                f"{entity_name} -- S&P placed the BB- rating on CreditWatch "
                "negative after Q4 leverage came in at 5.2x vs 4.5x covenant. "
                "Downgrade to B+ likely within 90 days."
            ),
            posted_at=(now - timedelta(hours=1, minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/debaborad/status/sn22_cr_001",
            entity_name=entity_name,
            keywords_matched=["downgrade", "leverage", "covenant"],
        ),
        SocialPost(
            post_id="sn22_cr_002",
            source="X",
            author="@CreditSights",
            content=(
                f"New report on {entity_name}: maturity wall analysis shows "
                "EUR 2.8bn coming due in 2027-2028. Refinancing risk is "
                "elevated given current market conditions. CDS at 350bp."
            ),
            posted_at=(now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/CreditSights/status/sn22_cr_002",
            entity_name=entity_name,
            keywords_matched=["maturity", "refinancing", "CDS"],
        ),
        SocialPost(
            post_id="sn22_cr_003",
            source="X",
            author="@9aborad",
            content=(
                f"{entity_name} bondholder group formed to negotiate amendment "
                "on the 2026 term loan B. This is the first sign of a "
                "potential liability management exercise (LME)."
            ),
            posted_at=(now - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/9aborad/status/sn22_cr_003",
            entity_name=entity_name,
            keywords_matched=["bondholder", "amendment", "LME"],
        ),
    ]

    # --- Noise posts ---
    noise_posts = [
        SocialPost(
            post_id="sn22_ns_001",
            source="X",
            author="@FootballDaily",
            content=(
                f"{entity_name} owner Sir Jim Ratcliffe reportedly unhappy "
                "with Manchester United transfer window. Fans calling for "
                "new manager after 5th straight Premier League loss."
            ),
            posted_at=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/FootballDaily/status/sn22_ns_001",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_002",
            source="X",
            author="@CyclingNews",
            content=(
                f"{entity_name} Grenadiers announce Tour de France squad. "
                "Vlasov and Vauquelin to lead GC challenge. Strong "
                "domestique lineup for the mountain stages."
            ),
            posted_at=(now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/CyclingNews/status/sn22_ns_002",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_003",
            source="X",
            author="@SkySports",
            content=(
                "BREAKING: Man Utd confirm Ratcliffe's INEOS to increase "
                "investment in Old Trafford renovation. Stadium capacity "
                "to expand by 15,000 seats."
            ),
            posted_at=(now - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/SkySports/status/sn22_ns_003",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_004",
            source="X",
            author="@ProCycling",
            content=(
                f"{entity_name} Grenadiers sign promising U23 rider from "
                "Belgian development team. Contract through 2028. Expected "
                "to debut at Giro d'Italia."
            ),
            posted_at=(now - timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/ProCycling/status/sn22_ns_004",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_005",
            source="X",
            author="@MUFC_Daily",
            content=(
                "INEOS executives spotted at Barcelona vs Man Utd match. "
                "Rumours of a centre-back transfer deal worth 60M euros."
            ),
            posted_at=(now - timedelta(hours=16)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/MUFC_Daily/status/sn22_ns_005",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_006",
            source="X",
            author="@SportUpdate",
            content=(
                f"{entity_name} Americas Cup yacht team unveils new boat "
                "design for 2027 campaign. Budget reportedly 120M USD."
            ),
            posted_at=(now - timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/SportUpdate/status/sn22_ns_006",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_007",
            source="X",
            author="@TransferWatch",
            content=(
                "Latest: INEOS-backed Man Utd closing in on Tottenham "
                "midfielder for 45M. Player eager for Champions League football."
            ),
            posted_at=(now - timedelta(hours=22)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/TransferWatch/status/sn22_ns_007",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_008",
            source="X",
            author="@PelotonWatch",
            content=(
                f"{entity_name} Grenadiers stage race strategy for Vuelta "
                "a Espana revealed. Three protected GC riders for the first "
                "time in team history."
            ),
            posted_at=(now - timedelta(hours=26)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/PelotonWatch/status/sn22_ns_008",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_009",
            source="X",
            author="@EPLZone",
            content=(
                "INEOS reportedly considering Ligue 1 expansion. OGC Nice "
                "to receive additional 30M for squad depth ahead of next "
                "transfer window."
            ),
            posted_at=(now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/EPLZone/status/sn22_ns_009",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_010",
            source="X",
            author="@F1_News",
            content=(
                f"{entity_name} rumoured to be evaluating F1 team investment. "
                "Sir Jim Ratcliffe said to be in talks with Mercedes."
            ),
            posted_at=(now - timedelta(hours=34)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/F1_News/status/sn22_ns_010",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_011",
            source="X",
            author="@SailingWeekly",
            content=(
                f"{entity_name} Team UK sets new sailing speed record during "
                "Americas Cup qualifying. Impressive yacht race performance."
            ),
            posted_at=(now - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/SailingWeekly/status/sn22_ns_011",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_012",
            source="X",
            author="@SportBiz",
            content=(
                "Ratcliffe's INEOS multi-sport empire expanding: cycling, "
                "football, sailing, rugby. Total sports spend estimated "
                "at 800M over 5 years."
            ),
            posted_at=(now - timedelta(hours=44)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/SportBiz/status/sn22_ns_012",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_013",
            source="X",
            author="@MatchDay",
            content=(
                "INEOS executive sacked after disagreement over Man Utd "
                "signing players policy. Old Trafford restructuring of "
                "football operations continues."
            ),
            posted_at=(now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/MatchDay/status/sn22_ns_013",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_ns_014",
            source="X",
            author="@EuroFootball",
            content=(
                f"Europa League draw: {entity_name}-owned OGC Nice vs "
                "Fenerbahce. Two legs in March. Fans excited for knockout "
                "stage return."
            ),
            posted_at=(now - timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/EuroFootball/status/sn22_ns_014",
            entity_name=entity_name,
            keywords_matched=[],
        ),
    ]

    # --- Ambiguous posts (neither clear signal nor clear noise) ---
    ambiguous_posts = [
        SocialPost(
            post_id="sn22_am_001",
            source="X",
            author="@ChemicalWeekly",
            content=(
                f"{entity_name} petrochemicals division reports mixed Q4. "
                "Revenue up 3% but margins compressed. Management guidance "
                "cautious for 2026 outlook."
            ),
            posted_at=(now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/ChemicalWeekly/status/sn22_am_001",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_am_002",
            source="X",
            author="@IndustrialNews",
            content=(
                f"{entity_name} announces new CFO appointment. Former "
                "Deutsche Bank restructuring head joins the team. Interesting "
                "choice for a company claiming to be stable."
            ),
            posted_at=(now - timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/IndustrialNews/status/sn22_am_002",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_am_003",
            source="X",
            author="@UKBizWatch",
            content=(
                f"{entity_name} Grangemouth refinery closure confirmed. "
                "700 jobs lost. Government providing transition support. "
                "Impact on group EBITDA unclear."
            ),
            posted_at=(now - timedelta(hours=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/UKBizWatch/status/sn22_am_003",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_am_004",
            source="X",
            author="@EURegulator",
            content=(
                f"EU antitrust review of {entity_name} acquisition of "
                "Belgian chemicals plant. Phase II investigation opened. "
                "Decision expected by June."
            ),
            posted_at=(now - timedelta(hours=19)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/EURegulator/status/sn22_am_004",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_am_005",
            source="X",
            author="@PetroAnalyst",
            content=(
                f"{entity_name} crude oil operations facing headwinds from "
                "OPEC+ production cuts. Analysts estimate 200M annual EBITDA "
                "impact if prices stay below 70 USD."
            ),
            posted_at=(now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/PetroAnalyst/status/sn22_am_005",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_am_006",
            source="X",
            author="@GreenWatch",
            content=(
                f"{entity_name} fined 15M by environment agency for chemical "
                "spill at Rosignano plant. Second incident in 18 months. "
                "ESG implications growing."
            ),
            posted_at=(now - timedelta(hours=28)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/GreenWatch/status/sn22_am_006",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_am_007",
            source="X",
            author="@EnergyTrader",
            content=(
                f"{entity_name} North Sea gas output declining faster than "
                "expected. Field life may end 2 years early. Decommissioning "
                "costs not yet provisioned."
            ),
            posted_at=(now - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/EnergyTrader/status/sn22_am_007",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_am_008",
            source="X",
            author="@ChemSector",
            content=(
                f"Interesting thread on {entity_name} group structure. "
                "Multiple holdco layers make it hard to assess true "
                "consolidated leverage. Anyone have the org chart?"
            ),
            posted_at=(now - timedelta(hours=42)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/ChemSector/status/sn22_am_008",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn22_am_009",
            source="X",
            author="@RatingWatch",
            content=(
                f"{entity_name} investor call next Thursday. Expected to "
                "address recent media speculation about asset sales and "
                "capital structure simplification."
            ),
            posted_at=(now - timedelta(hours=46)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/RatingWatch/status/sn22_am_009",
            entity_name=entity_name,
            keywords_matched=[],
        ),
    ]

    return overlap_posts + credit_posts + noise_posts + ambiguous_posts


def _get_demo_sn13_results(entity_name: str = "INEOS") -> list[SocialPost]:
    """Get SN13 demo data filtered by entity, supplemented with extra posts.

    Uses the existing get_demo_posts() plus additional noise/ambiguous posts
    so the comparison is more realistic.
    """
    now = datetime.utcnow()
    entity_lower = entity_name.lower()

    # Start with the existing demo posts (filtered to entity)
    base_posts = get_demo_posts(entity_filter=entity_name)

    # Add extra noise and ambiguous posts to make comparison richer
    extra_posts = [
        SocialPost(
            post_id="sn13_ns_001",
            source="X",
            author="@FootballInsider",
            content=(
                "INEOS set to overhaul Manchester United scouting department. "
                "Three new signing analysts hired from Brentford. Transfer "
                "strategy shifting to data-driven approach."
            ),
            posted_at=(now - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/FootballInsider/status/sn13_ns_001",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_002",
            source="X",
            author="@CyclingTips",
            content=(
                "INEOS Grenadiers Algarve training camp update: team looking "
                "strong ahead of spring classics. New time trial bikes "
                "expected at Tour de France."
            ),
            posted_at=(now - timedelta(hours=11)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/CyclingTips/status/sn13_ns_002",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_003",
            source="X",
            author="@PremLeagueNews",
            content=(
                "Manager sacked? Sources say INEOS ownership growing "
                "impatient with Man Utd results. Emergency board meeting "
                "called for Friday."
            ),
            posted_at=(now - timedelta(hours=13)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/PremLeagueNews/status/sn13_ns_003",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_004",
            source="X",
            author="@VeloNews",
            content=(
                "INEOS Grenadiers peloton positioning masterclass at "
                "stage race in Italy. GC contender Vlasov moves to 3rd "
                "overall. Domestique work superb."
            ),
            posted_at=(now - timedelta(hours=17)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/VeloNews/status/sn13_ns_004",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_005",
            source="X",
            author="@TransferNews",
            content=(
                "MUFC under INEOS: club confirms new footballer signing "
                "from Bundesliga for 38M. Squad depth strengthened ahead "
                "of Champions League campaign."
            ),
            posted_at=(now - timedelta(hours=21)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/TransferNews/status/sn13_ns_005",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_006",
            source="X",
            author="@GazetteSport",
            content=(
                "INEOS cycling team considering merger with another World "
                "Tour squad for 2027. Budget pressures cited as reason."
            ),
            posted_at=(now - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/GazetteSport/status/sn13_ns_006",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_007",
            source="X",
            author="@SoccerZone",
            content=(
                "Glazers vs INEOS: power struggle at Old Trafford as "
                "Ratcliffe pushes for more control over player transfers "
                "and commercial deals."
            ),
            posted_at=(now - timedelta(hours=29)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/SoccerZone/status/sn13_ns_007",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_008",
            source="X",
            author="@RugbyUpdate",
            content=(
                "INEOS rumoured to invest in French rugby club. Sports "
                "empire expanding beyond football and cycling."
            ),
            posted_at=(now - timedelta(hours=32)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/RugbyUpdate/status/sn13_ns_008",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_009",
            source="X",
            author="@FootieTransfers",
            content=(
                "INEOS-backed Nice confirm Ligue 1 star Maguire on loan "
                "from Man Utd. Player excited for Mediterranean move."
            ),
            posted_at=(now - timedelta(hours=35)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/FootieTransfers/status/sn13_ns_009",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_ns_010",
            source="X",
            author="@CycleWorld",
            content=(
                "INEOS Grenadiers Giro d'Italia preview: Vauquelin leads "
                "strong 8-rider squad. Mountain stages suit team well."
            ),
            posted_at=(now - timedelta(hours=39)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/CycleWorld/status/sn13_ns_010",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        # A few ambiguous SN13 posts
        SocialPost(
            post_id="sn13_am_001",
            source="X",
            author="@ChemIndustry",
            content=(
                f"{entity_name} Q4 production volumes flat. Ethylene "
                "margins remain under pressure from cheap Asian imports. "
                "No guidance change."
            ),
            posted_at=(now - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/ChemIndustry/status/sn13_am_001",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_am_002",
            source="X",
            author="@UKManufacturing",
            content=(
                f"{entity_name} Grangemouth site workers vote on new "
                "shift patterns. Union negotiations ongoing. No impact "
                "on production yet."
            ),
            posted_at=(now - timedelta(hours=23)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/UKManufacturing/status/sn13_am_002",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_am_003",
            source="X",
            author="@BizReporter",
            content=(
                f"{entity_name} considering IPO of consumer division in "
                "2027. Early stage discussions with banks. Valuation "
                "unclear."
            ),
            posted_at=(now - timedelta(hours=33)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/BizReporter/status/sn13_am_003",
            entity_name=entity_name,
            keywords_matched=[],
        ),
        SocialPost(
            post_id="sn13_am_004",
            source="X",
            author="@EUPolicy",
            content=(
                f"EU carbon border tax could impact {entity_name} "
                "petrochemicals margins by 5-8%. Implementation timeline "
                "still uncertain."
            ),
            posted_at=(now - timedelta(hours=41)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            url="https://x.com/EUPolicy/status/sn13_am_004",
            entity_name=entity_name,
            keywords_matched=[],
        ),
    ]

    return base_posts + extra_posts


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

def _hours_ago(posted_at: str) -> float:
    """Return how many hours ago a post was made."""
    now = datetime.utcnow()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(posted_at, fmt)
            # Strip tzinfo for comparison with utcnow
            dt = dt.replace(tzinfo=None)
            delta = now - dt
            return max(delta.total_seconds() / 3600, 0.0)
        except ValueError:
            continue
    return 48.0  # Fallback: assume 2 days old


def compare_sources(
    sn13_posts: list[SocialPost],
    sn22_posts: list[SocialPost],
    entity_name: str,
) -> dict:
    """Compare SN13 and SN22 results across coverage, signal, noise, freshness.

    Returns dict with 'sn13' and 'sn22' sub-dicts plus 'overlap_count' and 'verdict'.
    """
    sn13_ids = {p.post_id for p in sn13_posts}
    sn22_ids = {p.post_id for p in sn22_posts}
    overlap_ids = sn13_ids & sn22_ids

    def _metrics(posts: list[SocialPost], own_ids: set, other_ids: set) -> dict:
        total = len(posts)
        if total == 0:
            return {
                "total": 0, "unique": 0, "overlap": 0,
                "signal_count": 0, "signal_rate": 0.0,
                "noise_count": 0, "noise_rate": 0.0,
                "ambiguous_count": 0, "ambiguous_rate": 0.0,
                "median_freshness_hours": 0.0, "newest_hours": 0.0,
            }

        unique = len(own_ids - other_ids)
        overlap = len(own_ids & other_ids)

        signal_count = sum(1 for p in posts if has_credit_keyword(p.content))
        noise_count = sum(1 for p in posts if is_credit_noise(p))
        ambiguous_count = total - signal_count - noise_count

        ages = [_hours_ago(p.posted_at) for p in posts]
        med_fresh = median(ages) if ages else 0.0
        newest = min(ages) if ages else 0.0

        return {
            "total": total,
            "unique": unique,
            "overlap": overlap,
            "signal_count": signal_count,
            "signal_rate": round(signal_count / total * 100, 1),
            "noise_count": noise_count,
            "noise_rate": round(noise_count / total * 100, 1),
            "ambiguous_count": ambiguous_count,
            "ambiguous_rate": round(ambiguous_count / total * 100, 1),
            "median_freshness_hours": round(med_fresh, 1),
            "newest_hours": round(newest, 1),
        }

    sn13_m = _metrics(sn13_posts, sn13_ids, sn22_ids)
    sn22_m = _metrics(sn22_posts, sn22_ids, sn13_ids)

    # Build verdict
    verdict_parts = []

    # Coverage comparison
    if sn22_m["unique"] > sn13_m["unique"] and sn13_m["unique"] > 0:
        pct_more = round((sn22_m["unique"] - sn13_m["unique"]) / sn13_m["unique"] * 100)
        verdict_parts.append(f"SN22 finds {pct_more}% more unique posts")
    elif sn13_m["unique"] > sn22_m["unique"] and sn22_m["unique"] > 0:
        pct_more = round((sn13_m["unique"] - sn22_m["unique"]) / sn22_m["unique"] * 100)
        verdict_parts.append(f"SN13 finds {pct_more}% more unique posts")
    elif sn22_m["unique"] > 0 and sn13_m["unique"] == 0:
        verdict_parts.append(f"SN22 finds {sn22_m['unique']} unique posts vs 0 for SN13")
    elif sn13_m["unique"] > 0 and sn22_m["unique"] == 0:
        verdict_parts.append(f"SN13 finds {sn13_m['unique']} unique posts vs 0 for SN22")
    else:
        verdict_parts.append("Equal unique post counts")

    # Signal rate
    if sn22_m["signal_rate"] > sn13_m["signal_rate"]:
        verdict_parts.append("better signal rate")
    elif sn13_m["signal_rate"] > sn22_m["signal_rate"]:
        verdict_parts.append("SN13 has better signal rate")
    else:
        verdict_parts.append("equal signal rates")

    # Noise rate
    if sn22_m["noise_rate"] < sn13_m["noise_rate"]:
        verdict_parts.append("lower noise")
    elif sn13_m["noise_rate"] < sn22_m["noise_rate"]:
        verdict_parts.append("SN13 has lower noise")
    else:
        verdict_parts.append("equal noise levels")

    # Freshness
    if sn22_m["newest_hours"] < sn13_m["newest_hours"]:
        verdict_parts.append("fresher data")
    elif sn13_m["newest_hours"] < sn22_m["newest_hours"]:
        verdict_parts.append("SN13 has fresher data")
    else:
        verdict_parts.append("equal freshness")

    # Join first part with following parts
    if len(verdict_parts) > 1:
        verdict = verdict_parts[0] + ",\n           " + ", ".join(verdict_parts[1:])
    else:
        verdict = verdict_parts[0]

    return {
        "entity": entity_name,
        "sn13": sn13_m,
        "sn22": sn22_m,
        "overlap_count": len(overlap_ids),
        "verdict": verdict,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Pretty-print
# ---------------------------------------------------------------------------

def print_comparison(result: dict):
    """Pretty-print a comparison result table."""
    entity = result["entity"]
    sn13 = result["sn13"]
    sn22 = result["sn22"]
    verdict = result["verdict"]

    w = 55  # total width

    print()
    print("=" * w)
    print(f"  SN13 vs SN22 Benchmark: {entity}")
    print("=" * w)
    print(f"  {'':24s} {'SN13':>10s}    {'SN22':>10s}")
    print(f"  Total posts           {sn13['total']:>10d}    {sn22['total']:>10d}")
    print(f"  Unique to source      {sn13['unique']:>10d}    {sn22['unique']:>10d}")
    print(f"  Overlap               {sn13['overlap']:>10d}    {sn22['overlap']:>10d}")
    print(f"  " + "-" * (w - 4))
    print(f"  Credit signal         {sn13['signal_rate']:>9.1f}%    {sn22['signal_rate']:>9.1f}%")
    print(f"  Noise                 {sn13['noise_rate']:>9.1f}%    {sn22['noise_rate']:>9.1f}%")
    print(f"  Ambiguous             {sn13['ambiguous_rate']:>9.1f}%    {sn22['ambiguous_rate']:>9.1f}%")
    print(f"  " + "-" * (w - 4))
    print(f"  Median freshness      {sn13['median_freshness_hours']:>9.1f}h    {sn22['median_freshness_hours']:>9.1f}h")
    print(f"  Newest post           {sn13['newest_hours']:>9.1f}h    {sn22['newest_hours']:>9.1f}h")
    print(f"  " + "-" * (w - 4))
    print(f"  Verdict: {verdict}")
    print("=" * w)
    print()


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

def save_report(result: dict):
    """Save benchmark result to data/benchmarks/ as JSON."""
    entity_slug = result["entity"].replace(" ", "_").replace("/", "_")
    date_str = datetime.utcnow().strftime("%Y%m%d")
    out_dir = Path("data/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sn13_vs_sn22_{entity_slug}_{date_str}.json"

    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Report saved: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(
    entity_name: str,
    demo_mode: bool = False,
    days_back: int = 3,
    limit: int = 50,
) -> dict:
    """Run a full SN13 vs SN22 benchmark for a single entity.

    Returns the comparison dict.
    """
    aliases = get_search_terms(entity_name)
    keywords = list(CREDIT_KEYWORDS)

    has_sn13_key = bool(os.getenv("MACROCOSMOS_API_KEY"))
    has_sn22_key = bool(os.getenv("DESEARCH_API_KEY"))

    if demo_mode or (not has_sn13_key and not has_sn22_key):
        if not demo_mode:
            print("  [DEMO MODE] No API keys set -- using mock data")

        # Resolve short entity name to a display name for demo
        short_name = entity_name
        for full_name, alias_list in ENTITY_ALIASES.items():
            for alias in alias_list:
                if alias.lower() == entity_name.lower():
                    short_name = alias
                    break

        sn13_posts = _get_demo_sn13_results(short_name)
        sn22_posts = get_demo_sn22_results(short_name)
        print(f"  SN13 demo: {len(sn13_posts)} posts")
        print(f"  SN22 demo: {len(sn22_posts)} posts")
    else:
        # Live API calls
        sn13_posts = []
        sn22_posts = []

        if has_sn13_key:
            try:
                from monitors.social_sentiment import query_sn13
                sn13_posts = query_sn13(entity_name, aliases, days_back=days_back, limit=limit)
                print(f"  SN13 live: {len(sn13_posts)} posts")
            except Exception as e:
                print(f"  SN13 error: {e}", file=sys.stderr)
        else:
            sn13_posts = _get_demo_sn13_results(entity_name)
            print(f"  SN13 demo (no key): {len(sn13_posts)} posts")

        if has_sn22_key:
            sn22_posts = query_desearch(
                entity_name, aliases, keywords,
                days_back=days_back, limit=limit,
            )
            print(f"  SN22 live: {len(sn22_posts)} posts")
        else:
            sn22_posts = get_demo_sn22_results(entity_name)
            print(f"  SN22 demo (no key): {len(sn22_posts)} posts")

    result = compare_sources(sn13_posts, sn22_posts, entity_name)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark SN13 (Macrocosmos) vs SN22 (Desearch) for credit social data"
    )
    parser.add_argument(
        "--entity", type=str, default=None,
        help="Benchmark a single entity (e.g. 'INEOS')",
    )
    parser.add_argument(
        "--all-noisy", action="store_true",
        help="Benchmark all 14 noisy entities from ENTITY_NOISE",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Force demo mode even if API keys are set",
    )
    parser.add_argument(
        "--days", type=int, default=3,
        help="Lookback window in days (default: 3)",
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Max posts per source (default: 50)",
    )
    args = parser.parse_args()

    if not args.entity and not args.all_noisy:
        parser.error("Provide --entity NAME or --all-noisy")

    print()
    print("=" * 55)
    print("  SN13 vs SN22 Benchmark")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    if args.demo:
        print("  [DEMO MODE]")
    print("=" * 55)

    entities = []
    if args.all_noisy:
        entities = list(ENTITY_NOISE.keys())
        print(f"\n  Benchmarking {len(entities)} noisy entities...\n")
    else:
        entities = [args.entity]

    all_results = []
    for entity in entities:
        print(f"\n  --- {entity} ---")
        result = run_benchmark(
            entity_name=entity,
            demo_mode=args.demo,
            days_back=args.days,
            limit=args.limit,
        )
        print_comparison(result)
        report_path = save_report(result)
        all_results.append(result)

    # Summary across all entities
    if len(all_results) > 1:
        print("\n" + "=" * 55)
        print("  AGGREGATE SUMMARY")
        print("=" * 55)

        total_sn13_unique = sum(r["sn13"]["unique"] for r in all_results)
        total_sn22_unique = sum(r["sn22"]["unique"] for r in all_results)
        avg_sn13_signal = sum(r["sn13"]["signal_rate"] for r in all_results) / len(all_results)
        avg_sn22_signal = sum(r["sn22"]["signal_rate"] for r in all_results) / len(all_results)
        avg_sn13_noise = sum(r["sn13"]["noise_rate"] for r in all_results) / len(all_results)
        avg_sn22_noise = sum(r["sn22"]["noise_rate"] for r in all_results) / len(all_results)

        print(f"  Entities benchmarked: {len(all_results)}")
        print(f"  Total unique (SN13): {total_sn13_unique}")
        print(f"  Total unique (SN22): {total_sn22_unique}")
        print(f"  Avg signal rate:     SN13={avg_sn13_signal:.1f}%  SN22={avg_sn22_signal:.1f}%")
        print(f"  Avg noise rate:      SN13={avg_sn13_noise:.1f}%  SN22={avg_sn22_noise:.1f}%")
        print("=" * 55)
        print()


if __name__ == "__main__":
    main()

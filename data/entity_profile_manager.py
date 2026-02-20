"""
Entity Profile Manager — Continuous Learning System

Manages per-entity JSON profiles that accumulate intelligence from all monitors.
Each entity gets a JSON file in data/entity_profiles/ that aggregates:
    - Rating actions (from monitors/rating_actions.py)
    - Social sentiment signals (from monitors/social_sentiment.py)
    - News articles (from monitors/news_monitor.py)
    - Earnings signals (from data/earnings_signals/)
    - Analyst assessments (from agents/analyst.py)
    - Signal changes

Usage:
    from data.entity_profile_manager import load_profile, update_profile, get_profile_summary
"""

import json
import re
from datetime import datetime
from pathlib import Path


PROFILES_DIR = Path("data/entity_profiles")
MAX_ITEMS_PER_CATEGORY = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify_entity(name: str) -> str:
    """Convert entity name to a filesystem-safe slug.

    Examples:
        'INEOS Finance PLC'  ->  'ineos_finance_plc'
        'Worldline SA/France'  ->  'worldline_sa_france'
    """
    slug = name.lower()
    slug = slug.replace("/", "_").replace("-", "_").replace(".", "")
    slug = re.sub(r"[^a-z0-9_]", "_", slug)
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_")


def _profile_path(entity_name: str) -> Path:
    return PROFILES_DIR / f"{slugify_entity(entity_name)}.json"


def _empty_profile(entity_name: str) -> dict:
    return {
        "entity": entity_name,
        "last_updated": datetime.now().isoformat(),
        "filings": [],
        "news": [],
        "rating_actions": [],
        "earnings_signals": [],
        "social_sentiment": [],
        "analyst_assessments": [],
        "signal_changes": [],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_profile(entity_name: str) -> dict:
    """Load an entity profile from JSON.  Returns empty template if not found."""
    path = _profile_path(entity_name)
    if not path.exists():
        return _empty_profile(entity_name)
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_profile(entity_name)


def update_profile(entity_name: str, category: str, new_data: dict) -> None:
    """Append *new_data* to a profile category and save.

    Args:
        entity_name: Full entity name (e.g. "INEOS Finance PLC").
        category: One of filings, news, rating_actions, earnings_signals,
                  social_sentiment, analyst_assessments, signal_changes.
        new_data: Dict to append.
    """
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile = load_profile(entity_name)

    if category not in profile:
        profile[category] = []

    if "added_at" not in new_data:
        new_data["added_at"] = datetime.now().isoformat()

    profile[category].append(new_data)

    # Cap list size — keep most recent items
    if len(profile[category]) > MAX_ITEMS_PER_CATEGORY:
        profile[category] = profile[category][-MAX_ITEMS_PER_CATEGORY:]

    profile["last_updated"] = datetime.now().isoformat()

    path = _profile_path(entity_name)
    with open(path, "w") as f:
        json.dump(profile, f, indent=2, default=str)


def get_profile_summary(entity_name: str) -> str:
    """Generate a concise text summary for use as analyst context.

    Returns an empty string when no meaningful data exists.
    Targets ~300-500 words so it fits alongside knowledge_context and
    spread_context in the analyst prompt.
    """
    profile = load_profile(entity_name)
    parts: list[str] = []

    # Recent rating actions (last 3)
    if profile.get("rating_actions"):
        lines = []
        for ra in profile["rating_actions"][-3:][::-1]:
            agency = ra.get("agency", "")
            action = ra.get("action_type", "")
            date = ra.get("date", "")
            headline = ra.get("headline", "")[:80]
            lines.append(f"  - [{date}] {agency}: {action} — {headline}")
        if lines:
            parts.append("RECENT RATING ACTIONS:\n" + "\n".join(lines))

    # Recent news (last 5)
    if profile.get("news"):
        lines = []
        for n in profile["news"][-5:][::-1]:
            impact = n.get("credit_impact", "neutral")
            sev = n.get("severity", 1)
            summary = n.get("claim_summary", n.get("title", ""))[:80]
            lines.append(f"  - [sev={sev}] ({impact}) {summary}")
        if lines:
            parts.append("RECENT NEWS:\n" + "\n".join(lines))

    # Recent social sentiment (last 3, severity >= 3 only)
    if profile.get("social_sentiment"):
        material = [
            s for s in profile["social_sentiment"]
            if s.get("severity", 0) >= 3
        ][-3:]
        lines = []
        for s in material[::-1]:
            sentiment = s.get("sentiment", "neutral")
            sev = s.get("severity", 1)
            claim = s.get("claim_summary", "")[:80]
            lines.append(f"  - [sev={sev}] ({sentiment}) {claim}")
        if lines:
            parts.append("SOCIAL SENTIMENT (material only):\n" + "\n".join(lines))

    # Latest earnings signal
    if profile.get("earnings_signals"):
        latest = profile["earnings_signals"][-1]
        signal = latest.get("signal", "neutral")
        quarter = latest.get("quarter", "")
        summary = latest.get("summary", "")[:200]
        parts.append(f"LATEST EARNINGS ({quarter}): signal={signal}\n  {summary}")

    # Latest analyst assessment
    if profile.get("analyst_assessments"):
        latest = profile["analyst_assessments"][-1]
        direction = latest.get("direction", "FLAT")
        conviction = latest.get("conviction", 0)
        thesis = latest.get("thesis", "")[:150]
        parts.append(
            f"PRIOR ASSESSMENT: {direction} conviction={conviction}/5\n  {thesis}"
        )

    # Recent signal changes (last 3)
    if profile.get("signal_changes"):
        lines = []
        for sc in profile["signal_changes"][-3:][::-1]:
            desc = sc.get("description", str(sc))[:80]
            lines.append(f"  - {desc}")
        if lines:
            parts.append("SIGNAL CHANGES:\n" + "\n".join(lines))

    if not parts:
        return ""

    return (
        f"ENTITY PROFILE — {entity_name}\n"
        f"(Last updated: {profile.get('last_updated', 'unknown')})\n\n"
        + "\n\n".join(parts)
    )

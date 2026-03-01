"""
Closed-Loop Signal Pipeline
============================

The missing link between monitors and analytics. This module:

  1. INGESTS signals from all monitor SQLite databases
  2. ENRICHES each signal with spread context from snapshot store
  3. SCORES using signal_scorer (credit + equity repricing + gap)
  4. CHECKS risk via risk_metrics (position sizing, concentration)
  5. ALERTS via Telegram with full trade recommendation

Flow:
  monitors fire → signal_pipeline reads monitor DBs
    → loads current spread + spread history
    → runs signal_scorer.compute_credit_signal_score()
    → runs risk_metrics.compute_name_risk()
    → formats trade recommendation
    → sends Telegram alert (severity >= 3 or gap >= 30)
    → logs to data/pipeline_signals.db

This closes the loop: monitors → analytics → risk → alert.

Usage:
    python -m monitors.signal_pipeline                # Run once
    python -m monitors.signal_pipeline --watch         # Continuous (every 60s)
    python -m monitors.signal_pipeline --watch --interval 30
    python -m monitors.signal_pipeline --status        # Show recent pipeline signals
    python -m monitors.signal_pipeline --entity "INEOS Finance PLC"
    python -m monitors.signal_pipeline --dry-run       # No Telegram, just print

Programmatic:
    from monitors.signal_pipeline import run_pipeline, PipelineSignal
"""

import argparse
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests

from data.spread_snapshots import (
    get_latest_spreads,
    get_spread_change,
    capture_snapshot,
)
from data.market_data_loader import load_market_data
from analytics.signal_scorer import (
    compute_credit_signal_score,
)
from analytics.risk_metrics import compute_name_risk
from data.entity_profile_manager import load_profile, update_profile


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIPELINE_DB = Path("data/pipeline_signals.db")

# Monitor database paths (match existing monitor patterns)
MONITOR_DBS = {
    "social": Path("outputs/monitors/social_signals.db"),
    "equity": Path("outputs/monitors/equity_movers.db"),
    "news": Path("outputs/monitors/news_articles.db"),
    "rss": Path("outputs/monitors/rss_articles.db"),
    "rating": Path("outputs/monitors/rating_actions.db"),
    "filing": Path("outputs/monitors/filings.db"),
}

# Thresholds
ALERT_SEVERITY_MIN = 3          # Minimum severity to trigger alert
ALERT_CREDIT_SCORE_MIN = 55.0   # Minimum credit signal score for alert
ALERT_SPREAD_CHANGE_PCT = 5.0   # Alert on >5% spread move

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

try:
    import streamlit as st
    TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
except Exception:
    pass

# Default notional for risk sizing (millions)
DEFAULT_NOTIONAL_M = 10.0

# Index constituents by sector (loaded lazily)
_XOVER_SECTORS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MonitorSignal:
    """A raw signal from any monitor database."""
    source: str              # social, equity, news, rss, rating, filing
    entity_name: str
    signal_type: str         # e.g., "bearish_sentiment", "equity_drop", "downgrade"
    severity: int            # 1-5
    credit_impact: str       # positive, negative, neutral
    headline: str            # Summary/headline
    detail: str              # Additional context
    detected_at: str         # ISO datetime


@dataclass
class PipelineSignal:
    """An enriched, scored, risk-checked signal ready for alerting."""
    # Source signal
    entity_name: str
    source: str
    signal_type: str
    severity: int
    headline: str

    # Spread context
    current_spread: float
    spread_5d_change_bps: float
    spread_5d_change_pct: float

    # Credit signal score
    credit_score: float
    credit_components: dict

    # Risk metrics
    direction: str           # Recommended: LONG_RISK or SHORT_RISK
    suggested_notional_m: float
    dv01: float
    jtd: float

    # Alert decision
    alert_worthy: bool
    alert_reason: str

    # Metadata
    processed_at: str
    sector: str = ""


# ---------------------------------------------------------------------------
# Pipeline Database
# ---------------------------------------------------------------------------

PIPELINE_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pipeline_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_name     TEXT NOT NULL,
    source          TEXT NOT NULL,
    signal_type     TEXT NOT NULL,
    severity        INTEGER DEFAULT 0,
    headline        TEXT DEFAULT '',
    current_spread  REAL,
    spread_5d_chg   REAL,
    credit_score    REAL,
    direction       TEXT DEFAULT '',
    suggested_notional REAL DEFAULT 0,
    dv01            REAL DEFAULT 0,
    jtd             REAL DEFAULT 0,
    alert_worthy    INTEGER DEFAULT 0,
    alert_reason    TEXT DEFAULT '',
    alert_sent      INTEGER DEFAULT 0,
    sector          TEXT DEFAULT '',
    processed_at    TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""

PIPELINE_INDICES = """
CREATE INDEX IF NOT EXISTS idx_pipe_entity ON pipeline_signals(entity_name);
CREATE INDEX IF NOT EXISTS idx_pipe_date ON pipeline_signals(processed_at);
CREATE INDEX IF NOT EXISTS idx_pipe_alert ON pipeline_signals(alert_worthy);
CREATE INDEX IF NOT EXISTS idx_pipe_source ON pipeline_signals(source);
"""


def get_pipeline_db() -> sqlite3.Connection:
    """Get connection to the pipeline signals database."""
    PIPELINE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PIPELINE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(PIPELINE_CREATE_TABLE)
    conn.executescript(PIPELINE_INDICES)
    return conn


def store_pipeline_signal(conn: sqlite3.Connection, sig: PipelineSignal, alert_sent: bool = False):
    """Store a processed pipeline signal."""
    conn.execute("""
        INSERT INTO pipeline_signals
            (entity_name, source, signal_type, severity, headline,
             current_spread, spread_5d_chg, credit_score, direction,
             suggested_notional, dv01, jtd, alert_worthy, alert_reason,
             alert_sent, sector, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sig.entity_name, sig.source, sig.signal_type, sig.severity,
        sig.headline, sig.current_spread, sig.spread_5d_change_bps,
        sig.credit_score, sig.direction, sig.suggested_notional_m,
        sig.dv01, sig.jtd, int(sig.alert_worthy), sig.alert_reason,
        int(alert_sent), sig.sector, sig.processed_at,
    ))
    conn.commit()


# ---------------------------------------------------------------------------
# Monitor Signal Ingestion
# ---------------------------------------------------------------------------

def _load_sector_map() -> dict[str, str]:
    """Load entity → sector mapping from xover_s44.json."""
    global _XOVER_SECTORS
    if _XOVER_SECTORS:
        return _XOVER_SECTORS

    idx_file = Path("indices/xover_s44.json")
    if not idx_file.exists():
        return {}

    with open(idx_file) as f:
        data = json.load(f)

    for sector, names in data.get("sectors", {}).items():
        for name in names:
            _XOVER_SECTORS[name] = sector

    return _XOVER_SECTORS


def ingest_social_signals(since_hours: int = 4) -> list[MonitorSignal]:
    """Read recent signals from social_sentiment monitor."""
    db_path = MONITOR_DBS["social"]
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat()

    try:
        rows = conn.execute("""
            SELECT entity_name, sentiment, severity, claim_summary,
                   credit_relevance, classified_at
            FROM social_signals
            WHERE classified_at >= ? AND severity >= 2
            ORDER BY severity DESC, classified_at DESC
        """, (cutoff,)).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    conn.close()

    signals = []
    for r in rows:
        sentiment = r["sentiment"]
        impact = "negative" if sentiment == "bearish" else (
            "positive" if sentiment == "bullish" else "neutral"
        )
        signals.append(MonitorSignal(
            source="social",
            entity_name=r["entity_name"],
            signal_type=f"{sentiment}_sentiment",
            severity=r["severity"],
            credit_impact=impact,
            headline=r["claim_summary"] or "",
            detail=r["credit_relevance"] or "",
            detected_at=r["classified_at"],
        ))

    return signals


def ingest_equity_signals(since_hours: int = 4) -> list[MonitorSignal]:
    """Read recent signals from equity_movers monitor."""
    db_path = MONITOR_DBS["equity"]
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat()

    try:
        rows = conn.execute("""
            SELECT entity_name, change_pct, credit_impact, severity,
                   explanation, detected_at
            FROM equity_movers
            WHERE detected_at >= ? AND ABS(change_pct) >= 2.0
            ORDER BY ABS(change_pct) DESC
        """, (cutoff,)).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    conn.close()

    signals = []
    for r in rows:
        chg = r["change_pct"] or 0
        impact = r["credit_impact"] or ("negative" if chg < -3 else "neutral")
        signals.append(MonitorSignal(
            source="equity",
            entity_name=r["entity_name"],
            signal_type=f"equity_{'drop' if chg < 0 else 'rally'}_{abs(chg):.0f}pct",
            severity=r["severity"] or (4 if abs(chg) > 5 else 3),
            credit_impact=impact,
            headline=f"Equity moved {chg:+.1f}%",
            detail=r["explanation"] or "",
            detected_at=r["detected_at"],
        ))

    return signals


def ingest_news_signals(since_hours: int = 4) -> list[MonitorSignal]:
    """Read recent signals from news monitors (news + RSS)."""
    signals = []

    for db_key, table_name in [("news", "news_articles"), ("rss", "rss_articles")]:
        db_path = MONITOR_DBS[db_key]
        if not db_path.exists():
            continue

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat()

        try:
            rows = conn.execute(f"""
                SELECT entity_name, title, credit_impact, severity,
                       claim_summary, credit_relevance, classified_at
                FROM {table_name}
                WHERE classified_at >= ? AND severity >= 2
                ORDER BY severity DESC, classified_at DESC
                LIMIT 50
            """, (cutoff,)).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            continue

        conn.close()

        for r in rows:
            signals.append(MonitorSignal(
                source=db_key,
                entity_name=r["entity_name"],
                signal_type=f"news_{r['credit_impact'] or 'neutral'}",
                severity=r["severity"] or 1,
                credit_impact=r["credit_impact"] or "neutral",
                headline=r["title"] or "",
                detail=r["claim_summary"] or r["credit_relevance"] or "",
                detected_at=r["classified_at"] or "",
            ))

    return signals


def ingest_rating_signals(since_hours: int = 24) -> list[MonitorSignal]:
    """Read recent rating actions."""
    db_path = MONITOR_DBS["rating"]
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat()

    try:
        rows = conn.execute("""
            SELECT entity_name, agency, action_type, headline,
                   severity, credit_impact, created_at
            FROM rating_actions
            WHERE created_at >= ? AND severity >= 2
            ORDER BY severity DESC
        """, (cutoff,)).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    conn.close()

    signals = []
    for r in rows:
        signals.append(MonitorSignal(
            source="rating",
            entity_name=r["entity_name"],
            signal_type=f"rating_{(r['action_type'] or 'action').lower()}",
            severity=r["severity"] or 3,
            credit_impact=r["credit_impact"] or "negative",
            headline=f"{r['agency'] or ''}: {r['headline'] or r['action_type'] or ''}",
            detail="",
            detected_at=r["created_at"] or "",
        ))

    return signals


def ingest_filing_signals(since_hours: int = 24) -> list[MonitorSignal]:
    """Read recent regulatory filings."""
    db_path = MONITOR_DBS["filing"]
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat()

    try:
        rows = conn.execute("""
            SELECT matched_entity, source, headline, severity,
                   credit_impact, credit_summary, created_at
            FROM filings
            WHERE created_at >= ? AND severity >= 2 AND matched_entity IS NOT NULL
            ORDER BY severity DESC
        """, (cutoff,)).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    conn.close()

    signals = []
    for r in rows:
        signals.append(MonitorSignal(
            source="filing",
            entity_name=r["matched_entity"],
            signal_type=f"filing_{r['credit_impact'] or 'neutral'}",
            severity=r["severity"] or 2,
            credit_impact=r["credit_impact"] or "neutral",
            headline=r["headline"] or "",
            detail=r["credit_summary"] or "",
            detected_at=r["created_at"] or "",
        ))

    return signals


def ingest_all_signals(since_hours: int = 4) -> list[MonitorSignal]:
    """Ingest signals from all monitor databases."""
    all_signals = []
    all_signals.extend(ingest_social_signals(since_hours))
    all_signals.extend(ingest_equity_signals(since_hours))
    all_signals.extend(ingest_news_signals(since_hours))
    all_signals.extend(ingest_rating_signals(since_hours=max(since_hours, 24)))
    all_signals.extend(ingest_filing_signals(since_hours=max(since_hours, 24)))

    # Sort by severity descending
    all_signals.sort(key=lambda s: s.severity, reverse=True)
    return all_signals


# ---------------------------------------------------------------------------
# Signal Enrichment & Scoring
# ---------------------------------------------------------------------------

def enrich_and_score(
    signal: MonitorSignal,
    spread_data: dict[str, float],
) -> PipelineSignal | None:
    """Enrich a raw monitor signal with spread context and scoring.

    Returns None if the entity has no spread data.
    """
    entity = signal.entity_name
    current_spread = spread_data.get(entity)

    # Try loading from market data if not in snapshot store
    if current_spread is None:
        mkt = load_market_data(index="xover")
        entity_data = mkt.get(entity)
        if entity_data:
            current_spread = entity_data.get("spread")

    if current_spread is None or current_spread <= 0:
        return None

    sector_map = _load_sector_map()
    sector = sector_map.get(entity, "")

    # Get spread momentum from snapshot store
    spread_chg = get_spread_change(entity, days=5, index="xover")
    spread_5d_bps = spread_chg["change_bps"] if spread_chg else 0.0
    spread_5d_pct = spread_chg["change_pct"] if spread_chg else 0.0

    spread_20d = get_spread_change(entity, days=20, index="xover")
    spread_5d_ago = spread_chg["prior"] if spread_chg else None
    spread_20d_ago = spread_20d["prior"] if spread_20d else None

    # Load entity profile for filings context
    profile = load_profile(entity)
    recent_filings = profile.get("news", [])[-5:]  # Last 5 news items as proxy

    # Determine direction from signal
    if signal.credit_impact == "negative" or signal.severity >= 4:
        direction = "SHORT_RISK"
    elif signal.credit_impact == "positive":
        direction = "LONG_RISK"
    else:
        direction = "SHORT_RISK" if current_spread > 500 else "LONG_RISK"

    # Compute credit signal score
    credit_result = compute_credit_signal_score(
        entity_name=entity,
        spread_bps=current_spread,
        direction=direction,
        conviction=min(signal.severity, 5),
        filings=recent_filings,
        spread_5d_ago=spread_5d_ago,
        spread_20d_ago=spread_20d_ago,
    )

    # Compute risk metrics
    risk = compute_name_risk(
        entity_name=entity,
        current_spread=current_spread,
        fair_spread=current_spread * 0.85,  # Simple assumption
        direction=direction,
        notional_m=DEFAULT_NOTIONAL_M,
        sector=sector,
        conviction=min(signal.severity, 5),
    )

    # Determine if alert-worthy
    alert_worthy = False
    alert_reasons = []

    if signal.severity >= ALERT_SEVERITY_MIN:
        alert_worthy = True
        alert_reasons.append(f"severity={signal.severity}")

    if credit_result.total_score >= ALERT_CREDIT_SCORE_MIN:
        alert_worthy = True
        alert_reasons.append(f"credit_score={credit_result.total_score:.0f}")

    if abs(spread_5d_pct) >= ALERT_SPREAD_CHANGE_PCT:
        alert_worthy = True
        alert_reasons.append(f"spread_5d={spread_5d_pct:+.1f}%")

    if signal.source == "rating" and signal.severity >= 3:
        alert_worthy = True
        alert_reasons.append("rating_action")

    return PipelineSignal(
        entity_name=entity,
        source=signal.source,
        signal_type=signal.signal_type,
        severity=signal.severity,
        headline=signal.headline[:200],
        current_spread=current_spread,
        spread_5d_change_bps=spread_5d_bps,
        spread_5d_change_pct=spread_5d_pct,
        credit_score=credit_result.total_score,
        credit_components=credit_result.components,
        direction=direction,
        suggested_notional_m=DEFAULT_NOTIONAL_M,
        dv01=risk.dv01,
        jtd=risk.jtd,
        alert_worthy=alert_worthy,
        alert_reason="; ".join(alert_reasons) if alert_reasons else "below_threshold",
        processed_at=datetime.now().isoformat(),
        sector=sector,
    )


# ---------------------------------------------------------------------------
# Telegram Alerting
# ---------------------------------------------------------------------------

def send_pipeline_alert(signal: PipelineSignal) -> bool:
    """Send a Telegram alert for a pipeline signal."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"  [PIPELINE] Telegram not configured — would alert: {signal.entity_name}")
        return False

    dir_emoji = "\U0001F534" if signal.direction == "SHORT_RISK" else "\U0001F7E2"
    sev_bar = "\u2588" * signal.severity + "\u2591" * (5 - signal.severity)

    # Build message
    msg = (
        f"<b>SIGNAL PIPELINE ALERT</b>\n"
        f"\n"
        f"{dir_emoji} <b>{signal.entity_name}</b>\n"
        f"Sector: {signal.sector or 'N/A'}\n"
        f"\n"
        f"<b>Signal:</b> {signal.signal_type} (from {signal.source})\n"
        f"<b>Severity:</b> {sev_bar} ({signal.severity}/5)\n"
        f"<b>Headline:</b> {signal.headline[:150]}\n"
        f"\n"
        f"<b>Spread:</b> {signal.current_spread:.0f}bps "
        f"({signal.spread_5d_change_bps:+.0f}bp / {signal.spread_5d_change_pct:+.1f}% 5d)\n"
        f"<b>Credit Score:</b> {signal.credit_score:.0f}/100\n"
        f"<b>Direction:</b> {signal.direction}\n"
        f"\n"
        f"<b>Risk ({DEFAULT_NOTIONAL_M:.0f}m notional):</b>\n"
        f"  DV01: ${signal.dv01:,.0f}\n"
        f"  JTD:  ${signal.jtd:,.0f}\n"
        f"\n"
        f"<b>Alert reason:</b> {signal.alert_reason}\n"
        f"\n"
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
    )

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        return resp.ok
    except Exception as e:
        print(f"  [PIPELINE] Telegram error: {e}")
        return False


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _already_alerted(conn: sqlite3.Connection, entity: str, source: str, hours: int = 4) -> bool:
    """Check if we already sent an alert for this entity+source recently."""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    row = conn.execute("""
        SELECT 1 FROM pipeline_signals
        WHERE entity_name = ? AND source = ? AND alert_sent = 1 AND processed_at >= ?
    """, (entity, source, cutoff)).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    since_hours: int = 4,
    dry_run: bool = False,
    entity_filter: str | None = None,
    verbose: bool = False,
) -> list[PipelineSignal]:
    """Run the full signal pipeline.

    1. Ingest signals from all monitors
    2. Enrich with spread data and score
    3. Check risk
    4. Send alerts
    5. Store results

    Args:
        since_hours: Look back N hours for monitor signals.
        dry_run: If True, don't send Telegram alerts.
        entity_filter: Only process signals for this entity (partial match).
        verbose: Print detailed output.

    Returns:
        List of processed PipelineSignal objects.
    """
    print(f"\n  {'='*60}")
    print(f"  SIGNAL PIPELINE — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  {'='*60}")

    # Step 0: Capture latest spread snapshot (if market data available)
    try:
        n_captured = capture_snapshot(index="xover")
        if n_captured > 0:
            print(f"  [SNAPSHOT] Captured {n_captured} spreads")
    except Exception:
        pass  # Non-critical — we'll use whatever is in the DB

    # Step 1: Ingest
    print(f"\n  [1/4] Ingesting monitor signals (last {since_hours}h)...")
    raw_signals = ingest_all_signals(since_hours=since_hours)

    if entity_filter:
        entity_lower = entity_filter.lower()
        raw_signals = [s for s in raw_signals if entity_lower in s.entity_name.lower()]

    print(f"  Found {len(raw_signals)} raw signals")
    by_source = {}
    for s in raw_signals:
        by_source[s.source] = by_source.get(s.source, 0) + 1
    for src, count in sorted(by_source.items()):
        print(f"    {src:<10s}: {count}")

    if not raw_signals:
        print("  No signals to process.")
        return []

    # Deduplicate by entity — keep highest severity per entity
    entity_best: dict[str, MonitorSignal] = {}
    for sig in raw_signals:
        key = sig.entity_name
        if key not in entity_best or sig.severity > entity_best[key].severity:
            entity_best[key] = sig

    unique_signals = list(entity_best.values())
    print(f"  Unique entities: {len(unique_signals)}")

    # Step 2: Load spread context
    print("\n  [2/4] Loading spread context...")
    spread_data = get_latest_spreads(index="xover")
    if not spread_data:
        # Fallback to market data Excel
        mkt = load_market_data(index="xover")
        spread_data = {name: d["spread"] for name, d in mkt.items() if d.get("spread")}
    print(f"  Spread data for {len(spread_data)} names")

    # Step 3: Enrich and score
    print("\n  [3/4] Enriching and scoring...")
    pipeline_signals: list[PipelineSignal] = []
    for sig in unique_signals:
        enriched = enrich_and_score(sig, spread_data)
        if enriched:
            pipeline_signals.append(enriched)

    pipeline_signals.sort(key=lambda s: s.credit_score, reverse=True)
    print(f"  Scored {len(pipeline_signals)} signals")

    alert_worthy = [s for s in pipeline_signals if s.alert_worthy]
    print(f"  Alert-worthy: {len(alert_worthy)}")

    # Step 4: Alert and store
    print("\n  [4/4] Alerting and storing...")
    pipeline_conn = get_pipeline_db()
    alerts_sent = 0

    for sig in pipeline_signals:
        # Check dedup
        if sig.alert_worthy and not _already_alerted(pipeline_conn, sig.entity_name, sig.source):
            if dry_run:
                print(f"  [DRY RUN] Would alert: {sig.entity_name} "
                      f"({sig.source}, score={sig.credit_score:.0f}, "
                      f"spread={sig.current_spread:.0f}bp)")
                sent = False
            else:
                sent = send_pipeline_alert(sig)
                if sent:
                    alerts_sent += 1

            # Update entity profile with signal change
            update_profile(sig.entity_name, "signal_changes", {
                "source": sig.source,
                "signal_type": sig.signal_type,
                "severity": sig.severity,
                "credit_score": sig.credit_score,
                "spread_bps": sig.current_spread,
                "direction": sig.direction,
                "description": f"[{sig.source}] {sig.headline[:80]}",
            })

            store_pipeline_signal(pipeline_conn, sig, alert_sent=sent)
        else:
            store_pipeline_signal(pipeline_conn, sig, alert_sent=False)

    pipeline_conn.close()

    # Summary
    print(f"\n  {'='*60}")
    print("  PIPELINE SUMMARY")
    print(f"  {'='*60}")
    print(f"  Signals ingested:  {len(raw_signals)}")
    print(f"  Entities scored:   {len(pipeline_signals)}")
    print(f"  Alert-worthy:      {len(alert_worthy)}")
    print(f"  Alerts sent:       {alerts_sent}")

    if verbose or len(alert_worthy) > 0:
        print(f"\n  {'Entity':<35s} {'Source':<8s} {'Sev':>4s} "
              f"{'Spread':>8s} {'5dChg':>8s} {'Score':>6s} {'Dir':<12s} {'Alert'}")
        print(f"  {'-'*95}")
        for sig in pipeline_signals[:20]:
            alert_flag = ">>> YES" if sig.alert_worthy else ""
            print(f"  {sig.entity_name:<35s} {sig.source:<8s} {sig.severity:>4d} "
                  f"{sig.current_spread:>8.0f} {sig.spread_5d_change_bps:>+7.0f} "
                  f"{sig.credit_score:>6.0f} {sig.direction:<12s} {alert_flag}")

    return pipeline_signals


# ---------------------------------------------------------------------------
# Status / History
# ---------------------------------------------------------------------------

def show_status(days: int = 7, entity_filter: str | None = None):
    """Show recent pipeline signals from the database."""
    conn = get_pipeline_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    query = """
        SELECT entity_name, source, signal_type, severity, current_spread,
               spread_5d_chg, credit_score, direction, alert_worthy,
               alert_sent, processed_at
        FROM pipeline_signals
        WHERE processed_at >= ?
    """
    params: list = [cutoff]

    if entity_filter:
        query += " AND entity_name LIKE ?"
        params.append(f"%{entity_filter}%")

    query += " ORDER BY processed_at DESC LIMIT 50"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print(f"  No pipeline signals in last {days} days.")
        return

    print(f"\n  Pipeline Signals (last {days} days)")
    print(f"  {'Date':<12s} {'Entity':<30s} {'Source':<8s} {'Sev':>4s} "
          f"{'Spread':>8s} {'Score':>6s} {'Dir':<12s} {'Sent'}")
    print(f"  {'-'*90}")

    for r in rows:
        date_short = r["processed_at"][:10] if r["processed_at"] else ""
        sent = "Y" if r["alert_sent"] else ""
        print(f"  {date_short:<12s} {r['entity_name']:<30s} {r['source']:<8s} "
              f"{r['severity']:>4d} {r['current_spread']:>8.0f} "
              f"{r['credit_score']:>6.0f} {r['direction']:<12s} {sent}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Closed-Loop Signal Pipeline — monitors -> analytics -> risk -> alerts"
    )
    parser.add_argument("--watch", action="store_true",
                        help="Run continuously")
    parser.add_argument("--interval", type=int, default=60,
                        help="Watch interval in seconds (default: 60)")
    parser.add_argument("--since", type=int, default=4,
                        help="Look back N hours for signals (default: 4)")
    parser.add_argument("--entity", type=str, default=None,
                        help="Filter to entity (partial match)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't send Telegram alerts")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output")
    parser.add_argument("--status", action="store_true",
                        help="Show recent pipeline signals")
    parser.add_argument("--days", type=int, default=7,
                        help="Lookback days for --status")
    args = parser.parse_args()

    if args.status:
        show_status(days=args.days, entity_filter=args.entity)
        return

    if args.watch:
        print(f"  Starting pipeline in watch mode (every {args.interval}s)...")
        print("  Press Ctrl+C to stop.\n")
        try:
            while True:
                run_pipeline(
                    since_hours=args.since,
                    dry_run=args.dry_run,
                    entity_filter=args.entity,
                    verbose=args.verbose,
                )
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n  Pipeline stopped.")
    else:
        run_pipeline(
            since_hours=args.since,
            dry_run=args.dry_run,
            entity_filter=args.entity,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()

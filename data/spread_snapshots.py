"""
Daily Spread Snapshot Store
===========================

Captures and stores daily CDS spread snapshots for all iTraxx constituents.
This is the missing persistence layer that enables:
  - Historical spread time series per name
  - Backtesting single-name CDS strategies
  - Rich/cheap analysis over time (z-scores, momentum)
  - Signal validation ("did the spread actually move after the alert?")

Storage: SQLite at data/spread_snapshots.db

Usage:
    # Capture today's spreads from market data Excel
    python -m data.spread_snapshots

    # Capture with specific file
    python -m data.spread_snapshots --file data/market_data/itrx_s44_20260218.xlsx

    # Show history for a name
    python -m data.spread_snapshots --history "INEOS Finance PLC" --days 90

    # Export all history to CSV
    python -m data.spread_snapshots --export

    # Show stats
    python -m data.spread_snapshots --stats

Programmatic:
    from data.spread_snapshots import capture_snapshot, get_spread_history, get_latest_spreads
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from data.market_data_loader import load_market_data, find_latest_market_data


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path("data/spread_snapshots.db")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS spread_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_name     TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,
    idx             TEXT NOT NULL DEFAULT 'xover',
    spread_bps      REAL,
    convention      TEXT DEFAULT 'Spread',
    points_upfront  REAL,
    weight          REAL,
    ticker          TEXT,
    source_file     TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(entity_name, snapshot_date, idx)
);
"""

CREATE_INDICES = """
CREATE INDEX IF NOT EXISTS idx_snap_entity ON spread_snapshots(entity_name);
CREATE INDEX IF NOT EXISTS idx_snap_date ON spread_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snap_idx ON spread_snapshots(idx);
CREATE INDEX IF NOT EXISTS idx_snap_entity_date ON spread_snapshots(entity_name, snapshot_date);
"""


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    """Get SQLite connection, creating DB and tables if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(CREATE_TABLE)
    conn.executescript(CREATE_INDICES)
    return conn


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def capture_snapshot(
    filepath: str | None = None,
    index: str = "xover",
    snapshot_date: str | None = None,
) -> int:
    """Capture a spread snapshot from the market data Excel file.

    Args:
        filepath: Path to market data Excel. Auto-detected if None.
        index: "xover" or "main".
        snapshot_date: Override date (ISO format). Defaults to today.

    Returns:
        Number of names stored.
    """
    market_data = load_market_data(filepath=filepath, index=index)
    if not market_data:
        print(f"[Snapshot] No market data found for index={index}")
        return 0

    date_str = snapshot_date or datetime.now().strftime("%Y-%m-%d")
    source = filepath or find_latest_market_data() or ""

    conn = get_connection()
    stored = 0

    for entity_name, data in market_data.items():
        spread = data.get("spread")
        if spread is None:
            continue

        try:
            conn.execute("""
                INSERT OR REPLACE INTO spread_snapshots
                    (entity_name, snapshot_date, idx, spread_bps, convention,
                     points_upfront, weight, ticker, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entity_name, date_str, index, spread,
                data.get("convention", "Spread"),
                data.get("points_upfront"),
                data.get("weight"),
                data.get("ticker"),
                str(source),
            ))
            stored += 1
        except sqlite3.Error as e:
            print(f"[Snapshot] Error storing {entity_name}: {e}")

    conn.commit()
    conn.close()
    return stored


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def get_spread_history(
    entity_name: str,
    days: int = 365,
    index: str = "xover",
) -> list[dict]:
    """Get historical spread snapshots for a single name.

    Returns list of dicts sorted by date ascending:
        [{"date": "2026-01-15", "spread_bps": 450.0, "points_upfront": 5.2}, ...]
    """
    conn = get_connection()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT snapshot_date, spread_bps, points_upfront, convention
        FROM spread_snapshots
        WHERE entity_name = ? AND idx = ? AND snapshot_date >= ?
        ORDER BY snapshot_date ASC
    """, (entity_name, index, cutoff)).fetchall()

    conn.close()
    return [
        {
            "date": row["snapshot_date"],
            "spread_bps": row["spread_bps"],
            "points_upfront": row["points_upfront"],
            "convention": row["convention"],
        }
        for row in rows
    ]


def get_latest_spreads(index: str = "xover") -> dict[str, float]:
    """Get the most recent spread for every name.

    Returns: {entity_name: spread_bps}
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT entity_name, spread_bps
        FROM spread_snapshots
        WHERE idx = ? AND snapshot_date = (
            SELECT MAX(snapshot_date) FROM spread_snapshots WHERE idx = ?
        )
    """, (index, index)).fetchall()

    conn.close()
    return {row["entity_name"]: row["spread_bps"] for row in rows}


def get_spread_on_date(
    entity_name: str,
    target_date: str,
    index: str = "xover",
) -> float | None:
    """Get the spread for a name on a specific date (or nearest prior date)."""
    conn = get_connection()
    row = conn.execute("""
        SELECT spread_bps FROM spread_snapshots
        WHERE entity_name = ? AND idx = ? AND snapshot_date <= ?
        ORDER BY snapshot_date DESC LIMIT 1
    """, (entity_name, index, target_date)).fetchone()

    conn.close()
    return row["spread_bps"] if row else None


def get_spread_change(
    entity_name: str,
    days: int = 5,
    index: str = "xover",
) -> dict | None:
    """Get spread change over N days for a name.

    Returns: {"current": float, "prior": float, "change_bps": float, "change_pct": float}
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT snapshot_date, spread_bps
        FROM spread_snapshots
        WHERE entity_name = ? AND idx = ?
        ORDER BY snapshot_date DESC LIMIT ?
    """, (entity_name, index, days + 1)).fetchall()

    conn.close()
    if len(rows) < 2:
        return None

    current = rows[0]["spread_bps"]
    prior = rows[-1]["spread_bps"]
    if prior is None or current is None or prior == 0:
        return None

    return {
        "current": current,
        "prior": prior,
        "change_bps": current - prior,
        "change_pct": (current - prior) / prior * 100,
        "current_date": rows[0]["snapshot_date"],
        "prior_date": rows[-1]["snapshot_date"],
    }


def get_universe_changes(
    days: int = 5,
    index: str = "xover",
    min_change_pct: float = 0.0,
) -> list[dict]:
    """Get spread changes for the entire universe, sorted by absolute change.

    Returns list of dicts with entity_name, current, prior, change_bps, change_pct.
    """
    conn = get_connection()

    # Get the two most relevant dates
    dates = conn.execute("""
        SELECT DISTINCT snapshot_date FROM spread_snapshots
        WHERE idx = ? ORDER BY snapshot_date DESC LIMIT ?
    """, (index, days + 1)).fetchall()

    if len(dates) < 2:
        conn.close()
        return []

    latest_date = dates[0]["snapshot_date"]
    prior_date = dates[-1]["snapshot_date"]

    rows = conn.execute("""
        SELECT
            c.entity_name,
            c.spread_bps AS current_spread,
            p.spread_bps AS prior_spread
        FROM spread_snapshots c
        JOIN spread_snapshots p
            ON c.entity_name = p.entity_name AND c.idx = p.idx
        WHERE c.idx = ?
            AND c.snapshot_date = ?
            AND p.snapshot_date = ?
            AND c.spread_bps IS NOT NULL
            AND p.spread_bps IS NOT NULL
            AND p.spread_bps > 0
    """, (index, latest_date, prior_date)).fetchall()

    conn.close()

    results = []
    for row in rows:
        change_bps = row["current_spread"] - row["prior_spread"]
        change_pct = change_bps / row["prior_spread"] * 100
        if abs(change_pct) >= min_change_pct:
            results.append({
                "entity_name": row["entity_name"],
                "current": row["current_spread"],
                "prior": row["prior_spread"],
                "change_bps": round(change_bps, 1),
                "change_pct": round(change_pct, 2),
            })

    results.sort(key=lambda x: abs(x["change_bps"]), reverse=True)
    return results


def get_snapshot_dates(index: str = "xover") -> list[str]:
    """Get all dates that have snapshots stored."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT snapshot_date FROM spread_snapshots
        WHERE idx = ? ORDER BY snapshot_date DESC
    """, (index,)).fetchall()
    conn.close()
    return [row["snapshot_date"] for row in rows]


def get_stats() -> dict:
    """Get database statistics."""
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) AS n FROM spread_snapshots").fetchone()["n"]
    names = conn.execute("SELECT COUNT(DISTINCT entity_name) AS n FROM spread_snapshots").fetchone()["n"]
    dates = conn.execute("SELECT COUNT(DISTINCT snapshot_date) AS n FROM spread_snapshots").fetchone()["n"]
    earliest = conn.execute("SELECT MIN(snapshot_date) AS d FROM spread_snapshots").fetchone()["d"]
    latest = conn.execute("SELECT MAX(snapshot_date) AS d FROM spread_snapshots").fetchone()["d"]
    conn.close()
    return {
        "total_rows": total,
        "unique_names": names,
        "unique_dates": dates,
        "earliest_date": earliest,
        "latest_date": latest,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Daily Spread Snapshot Store — capture and query CDS spread history"
    )
    parser.add_argument("--file", type=str, default=None,
                        help="Path to market data Excel file")
    parser.add_argument("--index", type=str, default="xover",
                        choices=["xover", "main"],
                        help="Which index to capture (default: xover)")
    parser.add_argument("--date", type=str, default=None,
                        help="Override snapshot date (YYYY-MM-DD)")
    parser.add_argument("--history", type=str, default=None,
                        help="Show history for entity name")
    parser.add_argument("--days", type=int, default=90,
                        help="Lookback days for --history (default: 90)")
    parser.add_argument("--changes", action="store_true",
                        help="Show universe spread changes")
    parser.add_argument("--export", action="store_true",
                        help="Export all data to CSV")
    parser.add_argument("--stats", action="store_true",
                        help="Show database statistics")
    parser.add_argument("--both", action="store_true",
                        help="Capture both xover and main")
    args = parser.parse_args()

    if args.stats:
        stats = get_stats()
        print(f"\n  Spread Snapshot Database")
        print(f"  {'='*40}")
        print(f"  Total rows:    {stats['total_rows']:,}")
        print(f"  Unique names:  {stats['unique_names']}")
        print(f"  Unique dates:  {stats['unique_dates']}")
        print(f"  Date range:    {stats['earliest_date']} to {stats['latest_date']}")
        return

    if args.history:
        history = get_spread_history(args.history, days=args.days, index=args.index)
        if not history:
            print(f"  No history found for '{args.history}'")
            return
        print(f"\n  Spread History: {args.history} (last {args.days} days)")
        print(f"  {'Date':<12s} {'Spread':>10s} {'PU':>8s}")
        print(f"  {'-'*32}")
        for h in history:
            pu = f"{h['points_upfront']:.2f}" if h['points_upfront'] else "-"
            print(f"  {h['date']:<12s} {h['spread_bps']:>10.1f} {pu:>8s}")
        return

    if args.changes:
        changes = get_universe_changes(days=args.days, index=args.index)
        if not changes:
            print("  No change data available (need >= 2 snapshots)")
            return
        print(f"\n  Spread Changes ({args.index.upper()}, {args.days}d)")
        print(f"  {'Name':<45s} {'Current':>8s} {'Prior':>8s} {'Chg(bp)':>8s} {'Chg%':>7s}")
        print(f"  {'-'*78}")
        for c in changes[:30]:
            print(f"  {c['entity_name']:<45s} {c['current']:>8.1f} {c['prior']:>8.1f} "
                  f"{c['change_bps']:>+8.1f} {c['change_pct']:>+6.1f}%")
        return

    if args.export:
        conn = get_connection()
        rows = conn.execute("""
            SELECT entity_name, snapshot_date, idx, spread_bps,
                   convention, points_upfront, weight, ticker
            FROM spread_snapshots ORDER BY snapshot_date, entity_name
        """).fetchall()
        conn.close()

        out_path = Path("outputs/spread_snapshots_export.csv")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            f.write("entity_name,snapshot_date,index,spread_bps,convention,points_upfront,weight,ticker\n")
            for r in rows:
                pu = r["points_upfront"] if r["points_upfront"] else ""
                wt = r["weight"] if r["weight"] else ""
                f.write(f"{r['entity_name']},{r['snapshot_date']},{r['idx']},"
                        f"{r['spread_bps']},{r['convention']},{pu},{wt},{r['ticker'] or ''}\n")
        print(f"  Exported {len(rows)} rows to {out_path}")
        return

    # Default: capture snapshot
    indices = ["xover", "main"] if args.both else [args.index]
    for idx in indices:
        n = capture_snapshot(filepath=args.file, index=idx, snapshot_date=args.date)
        print(f"  [{idx.upper()}] Stored {n} spread snapshots for {args.date or 'today'}")


if __name__ == "__main__":
    main()

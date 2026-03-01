#!/usr/bin/env python3
"""
Pipeline Runner — Unified entry point for the closed-loop system.

Combines daily spread capture, signal pipeline, and optional backtesting
into a single command.

Usage:
    # Full pipeline: capture spreads + run signal pipeline + alert
    python scripts/run_pipeline.py

    # Watch mode: run every 60 seconds
    python scripts/run_pipeline.py --watch

    # Capture spreads only (for daily cron job)
    python scripts/run_pipeline.py --capture-only

    # Run pipeline + backtest validation
    python scripts/run_pipeline.py --with-backtest

    # Dry run (no Telegram)
    python scripts/run_pipeline.py --dry-run
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_capture(both: bool = False):
    """Capture daily spread snapshots."""
    from data.spread_snapshots import capture_snapshot, get_stats

    print("\n  SPREAD CAPTURE")
    print("  " + "=" * 50)

    indices = ["xover", "main"] if both else ["xover"]
    for idx in indices:
        n = capture_snapshot(index=idx)
        print(f"  [{idx.upper()}] Stored {n} spread snapshots")

    stats = get_stats()
    print(f"  Database: {stats['unique_names']} names, {stats['unique_dates']} dates "
          f"({stats['earliest_date'] or 'empty'} to {stats['latest_date'] or 'empty'})")


def run_signal_pipeline(since_hours: int = 4, dry_run: bool = False,
                        entity: str | None = None, verbose: bool = False):
    """Run the closed-loop signal pipeline."""
    from monitors.signal_pipeline import run_pipeline
    return run_pipeline(
        since_hours=since_hours,
        dry_run=dry_run,
        entity_filter=entity,
        verbose=verbose,
    )


def run_backtest_validation(top_n: int = 10):
    """Run backtest on recent signals to validate historical performance."""
    from analytics.single_name_backtester import backtest_universe, print_universe_summary
    from data.spread_snapshots import get_stats

    stats = get_stats()
    if stats["unique_dates"] < 10:
        print("\n  [BACKTEST] Need at least 10 daily snapshots to backtest. Skipping.")
        return

    print("\n  BACKTEST VALIDATION")
    print("  " + "=" * 50)
    results = backtest_universe(strategy="mean_reversion", lookback_days=365, holding_days=20)
    if results:
        print_universe_summary(results, top_n=top_n)
    else:
        print("  No backtest results (not enough spread history yet).")


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline Runner — daily spread capture + signal pipeline + backtest"
    )
    parser.add_argument("--watch", action="store_true",
                        help="Run continuously")
    parser.add_argument("--interval", type=int, default=60,
                        help="Watch interval in seconds")
    parser.add_argument("--capture-only", action="store_true",
                        help="Only capture spread snapshots, don't run pipeline")
    parser.add_argument("--both", action="store_true",
                        help="Capture both xover and main")
    parser.add_argument("--with-backtest", action="store_true",
                        help="Also run backtest validation")
    parser.add_argument("--since", type=int, default=4,
                        help="Look back N hours for monitor signals")
    parser.add_argument("--entity", type=str, default=None,
                        help="Filter to entity")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't send Telegram alerts")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Detailed output")
    args = parser.parse_args()

    print(f"\n  {'='*60}")
    print(f"  APEX S44 PIPELINE RUNNER")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  {'='*60}")

    if args.watch:
        import time
        print(f"  Mode: WATCH (every {args.interval}s)")
        print(f"  Press Ctrl+C to stop.\n")
        try:
            while True:
                run_capture(both=args.both)
                run_signal_pipeline(
                    since_hours=args.since,
                    dry_run=args.dry_run,
                    entity=args.entity,
                    verbose=args.verbose,
                )
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n  Pipeline stopped.")
        return

    # Single run
    run_capture(both=args.both)

    if not args.capture_only:
        run_signal_pipeline(
            since_hours=args.since,
            dry_run=args.dry_run,
            entity=args.entity,
            verbose=args.verbose,
        )

    if args.with_backtest:
        run_backtest_validation()

    print(f"\n  Done. ({datetime.now():%H:%M:%S})\n")


if __name__ == "__main__":
    main()

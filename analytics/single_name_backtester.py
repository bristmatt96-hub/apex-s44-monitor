"""
Single-Name CDS Backtester
============================

Backtest CDS trading strategies using historical spread snapshots.
Unlike credit_backtest_engine.py (which tests macro-credit strategies on
FRED index data), this module tests single-name strategies on actual
iTraxx constituent spread history captured by data/spread_snapshots.py.

Example questions this answers:
  - "If I bought protection on INEOS when spread was >800bps, what happened?"
  - "Does buying after a 50bp widening in a week pay off on average?"
  - "What's the hit rate of RV trades: long the cheapest, short the richest?"
  - "How did conviction-4+ analyst calls perform historically?"

Usage:
    python -m analytics.single_name_backtester
    python -m analytics.single_name_backtester --entity "INEOS Finance PLC" --strategy mean_reversion
    python -m analytics.single_name_backtester --strategy rv_sector --top 10
    python -m analytics.single_name_backtester --list-strategies

Programmatic:
    from analytics.single_name_backtester import (
        backtest_mean_reversion, backtest_momentum, backtest_rv_pairs,
        backtest_signal_history, SingleNameBacktestResult
    )
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median, stdev

from data.spread_snapshots import (
    get_connection as get_snap_connection,
    get_spread_history,
    get_latest_spreads,
    get_snapshot_dates,
    get_stats,
)
from analytics.cds_pricer import cds_dv01, spread_to_upfront


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("outputs/backtest")

# Default notional for P&L calculations (in millions)
DEFAULT_NOTIONAL_M = 10.0

# Assumed recovery rate for P&L
RECOVERY = 0.40


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """A single backtest trade."""
    entity_name: str
    entry_date: str
    exit_date: str
    entry_spread: float
    exit_spread: float
    direction: str          # LONG_RISK (sell protection) or SHORT_RISK (buy protection)
    spread_change_bps: float
    pnl_bps: float          # P&L in spread bps (positive = profit)
    pnl_usd: float          # Approximate USD P&L
    holding_days: int
    signal_reason: str = ""


@dataclass
class SingleNameBacktestResult:
    """Aggregated results from a single-name backtest."""
    strategy_name: str
    entity_name: str         # "*" for universe-wide
    n_trades: int
    hit_rate: float          # % of profitable trades
    avg_pnl_bps: float
    median_pnl_bps: float
    total_pnl_bps: float
    sharpe: float            # Per-trade Sharpe
    max_drawdown_bps: float
    win_avg_bps: float
    loss_avg_bps: float
    profit_factor: float
    avg_holding_days: float
    trades: list[Trade] = field(default_factory=list)


# ---------------------------------------------------------------------------
# P&L Helper
# ---------------------------------------------------------------------------

def _compute_trade_pnl(
    entry_spread: float,
    exit_spread: float,
    direction: str,
    notional_m: float = DEFAULT_NOTIONAL_M,
) -> tuple[float, float]:
    """Compute P&L for a CDS trade.

    Returns (pnl_bps, pnl_usd).

    For LONG_RISK (sell protection): profit when spreads tighten.
    For SHORT_RISK (buy protection): profit when spreads widen.
    """
    spread_change = exit_spread - entry_spread

    if direction == "LONG_RISK":
        pnl_bps = -spread_change   # tightening = positive
    else:
        pnl_bps = spread_change    # widening = positive

    # Approximate USD P&L using DV01 at entry
    notional = notional_m * 1_000_000
    dv01 = cds_dv01(entry_spread, notional=notional) if entry_spread > 0 else 0
    pnl_usd = pnl_bps * dv01

    return round(pnl_bps, 1), round(pnl_usd, 0)


def _aggregate_results(
    strategy_name: str,
    entity_name: str,
    trades: list[Trade],
) -> SingleNameBacktestResult:
    """Compute aggregate statistics from a list of trades."""
    if not trades:
        return SingleNameBacktestResult(
            strategy_name=strategy_name, entity_name=entity_name,
            n_trades=0, hit_rate=0, avg_pnl_bps=0, median_pnl_bps=0,
            total_pnl_bps=0, sharpe=0, max_drawdown_bps=0,
            win_avg_bps=0, loss_avg_bps=0, profit_factor=0,
            avg_holding_days=0, trades=trades,
        )

    pnls = [t.pnl_bps for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    cumulative = []
    running = 0
    for p in pnls:
        running += p
        cumulative.append(running)

    peak = cumulative[0]
    max_dd = 0
    for c in cumulative:
        if c > peak:
            peak = c
        dd = c - peak
        if dd < max_dd:
            max_dd = dd

    gross_wins = sum(wins) if wins else 0
    gross_losses = abs(sum(losses)) if losses else 0.001

    std = stdev(pnls) if len(pnls) > 1 else 1.0

    return SingleNameBacktestResult(
        strategy_name=strategy_name,
        entity_name=entity_name,
        n_trades=len(trades),
        hit_rate=round(len(wins) / len(trades) * 100, 1),
        avg_pnl_bps=round(mean(pnls), 1),
        median_pnl_bps=round(median(pnls), 1),
        total_pnl_bps=round(sum(pnls), 1),
        sharpe=round(mean(pnls) / std, 2) if std > 0 else 0,
        max_drawdown_bps=round(max_dd, 1),
        win_avg_bps=round(mean(wins), 1) if wins else 0,
        loss_avg_bps=round(mean(losses), 1) if losses else 0,
        profit_factor=round(gross_wins / gross_losses, 2),
        avg_holding_days=round(mean([t.holding_days for t in trades]), 0),
        trades=trades,
    )


# ---------------------------------------------------------------------------
# Strategy: Mean Reversion
# ---------------------------------------------------------------------------

def backtest_mean_reversion(
    entity_name: str,
    lookback_days: int = 365,
    z_entry: float = 1.5,
    holding_days: int = 20,
    index: str = "xover",
) -> SingleNameBacktestResult:
    """Mean reversion: buy when spread is z_entry stdevs above rolling mean.

    Logic: if spread is >1.5 z-scores wide vs its own 60-day rolling avg,
    go LONG_RISK (sell protection) expecting reversion to mean.
    If <-1.5 z-scores tight, go SHORT_RISK.
    """
    history = get_spread_history(entity_name, days=lookback_days, index=index)
    if len(history) < 60 + holding_days:
        return _aggregate_results("mean_reversion", entity_name, [])

    spreads = [h["spread_bps"] for h in history]
    dates = [h["date"] for h in history]

    trades = []
    window = 60
    last_trade_idx = -holding_days  # prevent overlapping trades

    for i in range(window, len(spreads) - holding_days):
        if i - last_trade_idx < holding_days:
            continue

        lookback = spreads[i - window:i]
        avg = mean(lookback)
        std = stdev(lookback) if len(lookback) > 1 else 1.0
        if std < 1.0:
            continue

        z = (spreads[i] - avg) / std

        if z >= z_entry:
            # Wide → sell protection (LONG_RISK)
            direction = "LONG_RISK"
            reason = f"z={z:.1f} (spread wide vs {window}d avg)"
        elif z <= -z_entry:
            # Tight → buy protection (SHORT_RISK)
            direction = "SHORT_RISK"
            reason = f"z={z:.1f} (spread tight vs {window}d avg)"
        else:
            continue

        entry_spread = spreads[i]
        exit_spread = spreads[i + holding_days]
        pnl_bps, pnl_usd = _compute_trade_pnl(entry_spread, exit_spread, direction)

        trades.append(Trade(
            entity_name=entity_name,
            entry_date=dates[i],
            exit_date=dates[i + holding_days],
            entry_spread=entry_spread,
            exit_spread=exit_spread,
            direction=direction,
            spread_change_bps=round(exit_spread - entry_spread, 1),
            pnl_bps=pnl_bps,
            pnl_usd=pnl_usd,
            holding_days=holding_days,
            signal_reason=reason,
        ))
        last_trade_idx = i

    return _aggregate_results("mean_reversion", entity_name, trades)


# ---------------------------------------------------------------------------
# Strategy: Momentum
# ---------------------------------------------------------------------------

def backtest_momentum(
    entity_name: str,
    lookback_days: int = 365,
    momentum_window: int = 20,
    momentum_threshold_pct: float = 10.0,
    holding_days: int = 20,
    index: str = "xover",
) -> SingleNameBacktestResult:
    """Momentum: follow the trend when spreads move sharply.

    If spread widens >10% over 20 days → SHORT_RISK (buy protection, momentum).
    If spread tightens >10% over 20 days → LONG_RISK (sell protection, momentum).
    """
    history = get_spread_history(entity_name, days=lookback_days, index=index)
    if len(history) < momentum_window + holding_days + 5:
        return _aggregate_results("momentum", entity_name, [])

    spreads = [h["spread_bps"] for h in history]
    dates = [h["date"] for h in history]

    trades = []
    last_trade_idx = -holding_days

    for i in range(momentum_window, len(spreads) - holding_days):
        if i - last_trade_idx < holding_days:
            continue

        prior = spreads[i - momentum_window]
        current = spreads[i]
        if prior <= 0:
            continue
        chg_pct = (current - prior) / prior * 100

        if chg_pct >= momentum_threshold_pct:
            direction = "SHORT_RISK"
            reason = f"widened {chg_pct:.1f}% over {momentum_window}d"
        elif chg_pct <= -momentum_threshold_pct:
            direction = "LONG_RISK"
            reason = f"tightened {chg_pct:.1f}% over {momentum_window}d"
        else:
            continue

        exit_spread = spreads[i + holding_days]
        pnl_bps, pnl_usd = _compute_trade_pnl(current, exit_spread, direction)

        trades.append(Trade(
            entity_name=entity_name,
            entry_date=dates[i],
            exit_date=dates[i + holding_days],
            entry_spread=current,
            exit_spread=exit_spread,
            direction=direction,
            spread_change_bps=round(exit_spread - current, 1),
            pnl_bps=pnl_bps,
            pnl_usd=pnl_usd,
            holding_days=holding_days,
            signal_reason=reason,
        ))
        last_trade_idx = i

    return _aggregate_results("momentum", entity_name, trades)


# ---------------------------------------------------------------------------
# Strategy: Level-Based (Absolute Spread)
# ---------------------------------------------------------------------------

def backtest_spread_level(
    entity_name: str,
    lookback_days: int = 365,
    wide_threshold: float = 800.0,
    tight_threshold: float = 200.0,
    holding_days: int = 40,
    index: str = "xover",
) -> SingleNameBacktestResult:
    """Level-based: trade when absolute spread hits extreme levels.

    Spread > 800bps → LONG_RISK (distressed mean reversion).
    Spread < 200bps → SHORT_RISK (complacency, buy protection).
    """
    history = get_spread_history(entity_name, days=lookback_days, index=index)
    if len(history) < holding_days + 5:
        return _aggregate_results("spread_level", entity_name, [])

    spreads = [h["spread_bps"] for h in history]
    dates = [h["date"] for h in history]

    trades = []
    last_trade_idx = -holding_days

    for i in range(0, len(spreads) - holding_days):
        if i - last_trade_idx < holding_days:
            continue

        current = spreads[i]

        if current >= wide_threshold:
            direction = "LONG_RISK"
            reason = f"spread={current:.0f}bps >= {wide_threshold:.0f} (distressed level)"
        elif current <= tight_threshold:
            direction = "SHORT_RISK"
            reason = f"spread={current:.0f}bps <= {tight_threshold:.0f} (complacency level)"
        else:
            continue

        exit_spread = spreads[i + holding_days]
        pnl_bps, pnl_usd = _compute_trade_pnl(current, exit_spread, direction)

        trades.append(Trade(
            entity_name=entity_name,
            entry_date=dates[i],
            exit_date=dates[i + holding_days],
            entry_spread=current,
            exit_spread=exit_spread,
            direction=direction,
            spread_change_bps=round(exit_spread - current, 1),
            pnl_bps=pnl_bps,
            pnl_usd=pnl_usd,
            holding_days=holding_days,
            signal_reason=reason,
        ))
        last_trade_idx = i

    return _aggregate_results("spread_level", entity_name, trades)


# ---------------------------------------------------------------------------
# Strategy: Signal Validation (backtest monitor alerts)
# ---------------------------------------------------------------------------

def backtest_signal_history(
    entity_name: str,
    signals: list[dict],
    holding_days: int = 20,
    index: str = "xover",
) -> SingleNameBacktestResult:
    """Validate historical signals against actual spread moves.

    Takes a list of signals like:
        [{"date": "2026-01-15", "direction": "SHORT_RISK", "reason": "news severity=4"}, ...]

    For each signal, checks what happened to the spread over holding_days.
    This answers: "Did our alerts actually predict spread moves?"
    """
    from data.spread_snapshots import get_spread_on_date

    trades = []
    for sig in signals:
        sig_date = sig["date"]
        direction = sig.get("direction", "SHORT_RISK")
        reason = sig.get("reason", "signal")

        entry_spread = get_spread_on_date(entity_name, sig_date, index=index)
        if entry_spread is None:
            continue

        # Calculate exit date
        try:
            entry_dt = datetime.strptime(sig_date, "%Y-%m-%d")
        except ValueError:
            continue
        exit_dt = entry_dt + timedelta(days=holding_days)
        exit_date = exit_dt.strftime("%Y-%m-%d")

        exit_spread = get_spread_on_date(entity_name, exit_date, index=index)
        if exit_spread is None:
            continue

        pnl_bps, pnl_usd = _compute_trade_pnl(entry_spread, exit_spread, direction)

        trades.append(Trade(
            entity_name=entity_name,
            entry_date=sig_date,
            exit_date=exit_date,
            entry_spread=entry_spread,
            exit_spread=exit_spread,
            direction=direction,
            spread_change_bps=round(exit_spread - entry_spread, 1),
            pnl_bps=pnl_bps,
            pnl_usd=pnl_usd,
            holding_days=holding_days,
            signal_reason=reason,
        ))

    return _aggregate_results("signal_validation", entity_name, trades)


# ---------------------------------------------------------------------------
# Universe Screener: Run strategy across all names
# ---------------------------------------------------------------------------

def backtest_universe(
    strategy: str = "mean_reversion",
    lookback_days: int = 365,
    holding_days: int = 20,
    index: str = "xover",
    **kwargs,
) -> list[SingleNameBacktestResult]:
    """Run a backtest strategy across every name in the snapshot database.

    Returns list of results sorted by Sharpe ratio (descending).
    """
    latest = get_latest_spreads(index=index)
    if not latest:
        print("  No spread data found. Run `python -m data.spread_snapshots` first.")
        return []

    strategy_fn = {
        "mean_reversion": backtest_mean_reversion,
        "momentum": backtest_momentum,
        "spread_level": backtest_spread_level,
    }.get(strategy)

    if not strategy_fn:
        print(f"  Unknown strategy: {strategy}")
        return []

    results = []
    for name in sorted(latest.keys()):
        result = strategy_fn(
            entity_name=name,
            lookback_days=lookback_days,
            holding_days=holding_days,
            index=index,
            **kwargs,
        )
        if result.n_trades >= 3:
            results.append(result)

    results.sort(key=lambda r: r.sharpe, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_result(result: SingleNameBacktestResult, verbose: bool = False):
    """Print a single backtest result."""
    r = result
    print(f"\n  {'='*70}")
    print(f"  {r.strategy_name.upper()} — {r.entity_name}")
    print(f"  {'='*70}")
    print(f"  Trades: {r.n_trades}  |  Hit Rate: {r.hit_rate:.1f}%  |  "
          f"Sharpe: {r.sharpe:+.2f}  |  PF: {r.profit_factor:.2f}x")
    print(f"  Avg P&L: {r.avg_pnl_bps:+.1f}bp  |  Median: {r.median_pnl_bps:+.1f}bp  |  "
          f"Total: {r.total_pnl_bps:+.0f}bp  |  Max DD: {r.max_drawdown_bps:+.0f}bp")
    print(f"  Win Avg: {r.win_avg_bps:+.1f}bp  |  Loss Avg: {r.loss_avg_bps:+.1f}bp  |  "
          f"Avg Hold: {r.avg_holding_days:.0f}d")

    if verbose and r.trades:
        print(f"\n  {'Entry Date':<12s} {'Exit Date':<12s} {'Dir':<12s} "
              f"{'Entry':>8s} {'Exit':>8s} {'Chg':>8s} {'P&L(bp)':>8s} {'Reason'}")
        print(f"  {'-'*85}")
        for t in r.trades[:20]:
            print(f"  {t.entry_date:<12s} {t.exit_date:<12s} {t.direction:<12s} "
                  f"{t.entry_spread:>8.1f} {t.exit_spread:>8.1f} "
                  f"{t.spread_change_bps:>+8.1f} {t.pnl_bps:>+8.1f} {t.signal_reason[:30]}")
        if len(r.trades) > 20:
            print(f"  ... and {len(r.trades) - 20} more trades")


def print_universe_summary(results: list[SingleNameBacktestResult], top_n: int = 15):
    """Print summary of universe backtest."""
    if not results:
        print("  No results.")
        return

    strat = results[0].strategy_name
    print(f"\n  {'='*90}")
    print(f"  UNIVERSE BACKTEST: {strat.upper()}")
    print(f"  {'='*90}")
    print(f"  {'#':>3s} {'Entity':<40s} {'Trades':>7s} {'Hit%':>6s} "
          f"{'Avg(bp)':>8s} {'Total':>8s} {'Sharpe':>7s} {'PF':>6s}")
    print(f"  {'-'*88}")

    for i, r in enumerate(results[:top_n], 1):
        print(f"  {i:>3d} {r.entity_name:<40s} {r.n_trades:>7d} "
              f"{r.hit_rate:>5.1f}% {r.avg_pnl_bps:>+7.1f} "
              f"{r.total_pnl_bps:>+7.0f} {r.sharpe:>+6.2f} {r.profit_factor:>5.2f}x")

    # Universe aggregate
    all_trades = [t for r in results for t in r.trades]
    if all_trades:
        all_pnls = [t.pnl_bps for t in all_trades]
        agg_wins = [p for p in all_pnls if p > 0]
        print(f"\n  AGGREGATE: {len(all_trades)} trades across {len(results)} names")
        print(f"  Universe Hit Rate: {len(agg_wins)/len(all_trades)*100:.1f}%  |  "
              f"Avg: {mean(all_pnls):+.1f}bp  |  Total: {sum(all_pnls):+.0f}bp")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

STRATEGIES = {
    "mean_reversion": "Mean reversion on rolling z-score",
    "momentum": "Follow sharp spread moves",
    "spread_level": "Trade at absolute spread extremes",
}


def main():
    parser = argparse.ArgumentParser(
        description="Single-Name CDS Backtester — test strategies on spread history"
    )
    parser.add_argument("--entity", type=str, default=None,
                        help="Run on specific entity (default: entire universe)")
    parser.add_argument("--strategy", type=str, default="mean_reversion",
                        choices=list(STRATEGIES.keys()),
                        help="Strategy to backtest")
    parser.add_argument("--days", type=int, default=365,
                        help="Lookback days (default: 365)")
    parser.add_argument("--holding", type=int, default=20,
                        help="Holding period in days (default: 20)")
    parser.add_argument("--index", type=str, default="xover",
                        choices=["xover", "main"])
    parser.add_argument("--top", type=int, default=15,
                        help="Show top N results for universe backtest")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show individual trades")
    parser.add_argument("--list-strategies", action="store_true",
                        help="List available strategies")
    args = parser.parse_args()

    if args.list_strategies:
        print("\n  Available strategies:")
        for name, desc in STRATEGIES.items():
            print(f"    {name:<20s}  {desc}")
        return

    # Check we have data
    stats = get_stats()
    if stats["total_rows"] == 0:
        print("  No spread snapshots found.")
        print("  Run: python -m data.spread_snapshots  (to capture today's spreads)")
        return

    print(f"\n  Spread data: {stats['unique_names']} names, "
          f"{stats['unique_dates']} dates ({stats['earliest_date']} to {stats['latest_date']})")

    if args.entity:
        # Single-name backtest
        strategy_fn = {
            "mean_reversion": backtest_mean_reversion,
            "momentum": backtest_momentum,
            "spread_level": backtest_spread_level,
        }[args.strategy]

        result = strategy_fn(
            entity_name=args.entity,
            lookback_days=args.days,
            holding_days=args.holding,
            index=args.index,
        )
        print_result(result, verbose=args.verbose)
    else:
        # Universe backtest
        results = backtest_universe(
            strategy=args.strategy,
            lookback_days=args.days,
            holding_days=args.holding,
            index=args.index,
        )
        print_universe_summary(results, top_n=args.top)

        # Save results
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        summary = []
        for r in results:
            summary.append({
                "entity": r.entity_name,
                "n_trades": r.n_trades,
                "hit_rate": r.hit_rate,
                "avg_pnl_bps": r.avg_pnl_bps,
                "total_pnl_bps": r.total_pnl_bps,
                "sharpe": r.sharpe,
                "profit_factor": r.profit_factor,
            })
        out_file = OUTPUT_DIR / f"sn_backtest_{args.strategy}_{datetime.now():%Y%m%d}.json"
        with open(out_file, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n  Results saved to {out_file}")


if __name__ == "__main__":
    main()

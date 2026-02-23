#!/usr/bin/env python3
"""
Module 16: Insider & Flow Tracker
===================================
Tracks PDMR insider transactions (90-day lookback) via Finnhub, HY ETF flow
sentiment (IHYG.L / HYG / JNK), and short interest where available. Detects
cluster insider selling/buying patterns.

Data Sources:
  - Finnhub (insider_transactions) for PDMR filings
  - yfinance for ETF prices/volumes and short interest
  - crossover_constituents.py for name/ticker/sector mapping

Dependencies:
  - pip install finnhub-python yfinance pandas matplotlib numpy

Usage:
  set FINNHUB_API_KEY=your_key
  python insider_flow_tracker.py

Author: Built with Claude for European credit trading
"""

import os
import sys
import time
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

try:
    import finnhub
except ImportError:
    print("ERROR: pip install finnhub-python")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    print("ERROR: pip install yfinance")
    sys.exit(1)

warnings.filterwarnings("ignore")

# Import crossover constituents
try:
    from analytics.crossover_constituents import CONSTITUENTS
except ImportError:
    print("ERROR: crossover_constituents.py not found")
    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_LOOKBACK_DAYS = 90
FINNHUB_RATE_DELAY = 1.1  # seconds between calls

# HY ETF tickers
HY_ETFS = {
    "IHYG.L": "iShares EUR HY Corp Bond",
    "HYG": "iShares USD HY Corp Bond",
    "JNK": "SPDR Bloomberg HY Bond",
}

# Insider transaction codes
BUY_CODES = {"P", "A", "M"}   # Purchase, Acquisition, Exercise
SELL_CODES = {"S", "D", "F"}  # Sale, Disposition, Tax withholding

# Cluster thresholds
CLUSTER_WINDOW_DAYS = 30
CLUSTER_MIN_INSIDERS = 3

# Chart styling
CHART_BG = "#1a1a2e"
CHART_FG = "#e0e0e0"
ACCENT_BLUE = "#4fc3f7"
ACCENT_RED = "#ef5350"
ACCENT_GREEN = "#66bb6a"
ACCENT_ORANGE = "#ffa726"
ACCENT_PURPLE = "#ab47bc"


# =============================================================================
# TICKER CONVERSION
# =============================================================================

def yahoo_to_finnhub(yahoo_ticker: str) -> str:
    """Convert Yahoo Finance ticker to Finnhub format."""
    if "." in yahoo_ticker:
        return yahoo_ticker.rsplit(".", 1)[0]
    return yahoo_ticker


# =============================================================================
# DATA FETCHING - INSIDER TRANSACTIONS
# =============================================================================

def fetch_insider_transactions(client, ticker: str,
                                days: int = DEFAULT_LOOKBACK_DAYS) -> List[dict]:
    """Fetch insider transactions for a single company from Finnhub."""
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        result = client.stock_insider_transactions(ticker,
                                                    _from=start.strftime("%Y-%m-%d"),
                                                    to=end.strftime("%Y-%m-%d"))
        if result and isinstance(result, dict):
            txns = result.get("data", [])
            if txns and isinstance(txns, list):
                return [t for t in txns if t.get("transactionCode")]
        return []
    except Exception:
        return []


def fetch_all_insider_data(api_key: str,
                            days: int = DEFAULT_LOOKBACK_DAYS) -> Dict[str, List[dict]]:
    """Fetch insider data for all Crossover constituents."""
    client = finnhub.Client(api_key=api_key)
    all_data = {}
    total = len(CONSTITUENTS)

    print(f"\n  Fetching insider transactions for {total} names ({days}d lookback)...")
    print(f"  Rate limit: {FINNHUB_RATE_DELAY}s delay")

    for i, (name, info) in enumerate(CONSTITUENTS.items(), 1):
        ticker = yahoo_to_finnhub(info["ticker"])
        txns = fetch_insider_transactions(client, ticker, days)
        if txns:
            all_data[name] = txns
        if i % 10 == 0 or i == total:
            n_with = len(all_data)
            total_txns = sum(len(v) for v in all_data.values())
            print(f"    [{i:02d}/{total}] {n_with} names with data, {total_txns} transactions")
        time.sleep(FINNHUB_RATE_DELAY)

    print(f"  -> {len(all_data)}/{total} names have insider data")
    return all_data


# =============================================================================
# DATA FETCHING - SHORT INTEREST
# =============================================================================

def fetch_short_interest() -> pd.DataFrame:
    """Fetch short interest data via yfinance .info. Many EU names will be N/A."""
    print("\n  Fetching short interest data (best-effort, many EU names N/A)...")
    rows = []
    for name, info in CONSTITUENTS.items():
        ticker = info["ticker"]
        try:
            stock = yf.Ticker(ticker)
            si = stock.info
            short_pct = si.get("shortPercentOfFloat")
            short_ratio = si.get("shortRatio")
            if short_pct is not None or short_ratio is not None:
                rows.append({
                    "name": name,
                    "ticker": ticker,
                    "sector": info.get("sector", ""),
                    "short_pct_float": round(short_pct * 100, 2) if short_pct else np.nan,
                    "short_ratio": round(short_ratio, 2) if short_ratio else np.nan,
                })
        except Exception:
            pass

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("short_pct_float", ascending=False, na_position="last")
    print(f"  -> {len(df)} names with short interest data")
    return df


# =============================================================================
# DATA FETCHING - ETF FLOWS
# =============================================================================

def fetch_etf_flows(days: int = DEFAULT_LOOKBACK_DAYS) -> Dict[str, pd.DataFrame]:
    """Fetch HY ETF price/volume data as flow proxy."""
    print(f"\n  Fetching HY ETF data ({days}d)...")
    etf_data = {}

    for ticker, name in HY_ETFS.items():
        try:
            df = yf.download(ticker, period=f"{days}d", progress=False, auto_adjust=True)
            if df is not None and len(df) > 10:
                df = df.copy()
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                # Compute flow proxy: volume Z-score
                vol = df["Volume"].astype(float)
                vol_mean = vol.rolling(20, min_periods=5).mean()
                vol_std = vol.rolling(20, min_periods=5).std()
                df["volume_zscore"] = ((vol - vol_mean) / vol_std.replace(0, np.nan)).clip(-4, 4)
                # Price momentum
                close = df["Close"].astype(float)
                df["return_5d"] = close.pct_change(5)
                df["return_20d"] = close.pct_change(20)
                # Flow direction: high volume + negative return = outflow; high volume + positive = inflow
                df["flow_proxy"] = df["volume_zscore"] * np.sign(df["return_5d"].fillna(0))
                etf_data[ticker] = df
                print(f"    {ticker} ({name}): {len(df)} days OK")
        except Exception as e:
            print(f"    {ticker}: FAILED ({e})")

    return etf_data


# =============================================================================
# INSIDER ANALYSIS
# =============================================================================

def detect_cluster_activity(transactions: List[dict],
                             window: int = CLUSTER_WINDOW_DAYS,
                             min_insiders: int = CLUSTER_MIN_INSIDERS) -> Tuple[bool, bool]:
    """Detect cluster selling or buying activity.

    Returns (is_cluster_sell, is_cluster_buy).
    Cluster = 3+ distinct insiders transacting in same direction within window.
    """
    sell_names = set()
    buy_names = set()

    cutoff = datetime.now() - timedelta(days=window)

    for txn in transactions:
        filing_date = txn.get("filingDate", "")
        if filing_date:
            try:
                fd = datetime.strptime(filing_date, "%Y-%m-%d")
                if fd < cutoff:
                    continue
            except Exception:
                pass

        code = txn.get("transactionCode", "")
        insider = txn.get("name", "unknown")

        if code in SELL_CODES:
            sell_names.add(insider)
        elif code in BUY_CODES:
            buy_names.add(insider)

    is_cluster_sell = len(sell_names) >= min_insiders
    is_cluster_buy = len(buy_names) >= min_insiders

    return is_cluster_sell, is_cluster_buy


def compute_insider_metrics(name: str, transactions: List[dict]) -> dict:
    """Compute insider activity metrics for a single name."""
    n_buys = 0
    n_sells = 0
    buy_value = 0.0
    sell_value = 0.0

    for txn in transactions:
        code = txn.get("transactionCode", "")
        shares = abs(txn.get("share", 0) or 0)
        price = txn.get("transactionPrice", 0) or 0
        value = shares * price

        if code in BUY_CODES:
            n_buys += 1
            buy_value += value
        elif code in SELL_CODES:
            n_sells += 1
            sell_value += value

    is_cluster_sell, is_cluster_buy = detect_cluster_activity(transactions)

    net_value = buy_value - sell_value
    net_value_mm = net_value / 1e6  # in millions

    # Insider signal: -2 to +2
    signal = 0.0
    if n_buys + n_sells > 0:
        buy_ratio = n_buys / (n_buys + n_sells)
        signal = (buy_ratio - 0.5) * 2  # 0 -> -1, 0.5 -> 0, 1.0 -> +1

    if is_cluster_sell:
        signal = min(signal, -1.0)
        signal -= 0.5
    if is_cluster_buy:
        signal = max(signal, 1.0)
        signal += 0.5

    signal = np.clip(signal, -2, 2)

    info = CONSTITUENTS.get(name, {})

    return {
        "name": name,
        "ticker": info.get("ticker", ""),
        "sector": info.get("sector", ""),
        "rating": info.get("rating", ""),
        "country": info.get("country", ""),
        "n_buys": n_buys,
        "n_sells": n_sells,
        "n_total": n_buys + n_sells,
        "buy_value_mm": round(buy_value / 1e6, 2),
        "sell_value_mm": round(sell_value / 1e6, 2),
        "net_value_mm": round(net_value_mm, 2),
        "is_cluster_sell": is_cluster_sell,
        "is_cluster_buy": is_cluster_buy,
        "insider_signal": round(signal, 2),
    }


def compute_all_insider_metrics(all_data: Dict[str, List[dict]]) -> pd.DataFrame:
    """Compute insider metrics for all names with data."""
    rows = []
    for name, txns in all_data.items():
        metrics = compute_insider_metrics(name, txns)
        rows.append(metrics)

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("insider_signal", ascending=True)
    return df


def compute_etf_sentiment(etf_data: Dict[str, pd.DataFrame]) -> dict:
    """Compute HY ETF composite flow sentiment."""
    signals = []

    for ticker, df in etf_data.items():
        if len(df) < 10:
            continue
        latest_flow = df["flow_proxy"].iloc[-5:].mean() if "flow_proxy" in df.columns else 0
        ret_20d = df["return_20d"].iloc[-1] if "return_20d" in df.columns else 0
        vol_z = df["volume_zscore"].iloc[-5:].mean() if "volume_zscore" in df.columns else 0

        # Signal: positive = inflow/risk-on, negative = outflow/risk-off
        sig = latest_flow * 0.5 + (ret_20d * 10 if pd.notna(ret_20d) else 0) * 0.3 + vol_z * 0.2
        signals.append(sig)

    composite = np.mean(signals) if signals else 0.0
    composite = np.clip(composite, -2, 2)

    if composite > 0.5:
        regime = "RISK_ON"
    elif composite < -0.5:
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"

    return {
        "composite_flow_signal": round(composite, 2),
        "flow_regime": regime,
        "n_etfs": len(signals),
    }


def sector_insider_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate insider metrics by sector."""
    if len(df) == 0:
        return pd.DataFrame()

    rows = []
    for sector in sorted(df["sector"].unique()):
        sub = df[df["sector"] == sector]
        rows.append({
            "sector": sector,
            "n_names": len(sub),
            "avg_signal": round(sub["insider_signal"].mean(), 2),
            "n_cluster_sell": sub["is_cluster_sell"].sum(),
            "n_cluster_buy": sub["is_cluster_buy"].sum(),
            "total_net_mm": round(sub["net_value_mm"].sum(), 2),
            "total_buys": sub["n_buys"].sum(),
            "total_sells": sub["n_sells"].sum(),
        })

    return pd.DataFrame(rows).sort_values("avg_signal", ascending=True)


def flag_insider_warnings(df: pd.DataFrame) -> pd.DataFrame:
    """Flag names with cluster selling and negative signals."""
    if len(df) == 0:
        return pd.DataFrame()

    flagged = df[
        (df["is_cluster_sell"]) | (df["insider_signal"] <= -1.0)
    ].copy()

    if len(flagged) > 0:
        flagged = flagged.sort_values("insider_signal", ascending=True)
    return flagged


# =============================================================================
# CONSOLE REPORT
# =============================================================================

def print_report(df: pd.DataFrame, sector_df: pd.DataFrame,
                  short_df: pd.DataFrame, warnings_df: pd.DataFrame,
                  etf_sentiment: dict, etf_data: Dict[str, pd.DataFrame]):
    """Print insider & flow tracker report."""
    w = 100
    print("\n" + "=" * w)
    print("  INSIDER & FLOW TRACKER - iTRAXX CROSSOVER")
    print("=" * w)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Names with insider data: {len(df)}/{len(CONSTITUENTS)}")

    # 1. OVERVIEW
    print("\n" + "=" * w)
    print("  1. INSIDER ACTIVITY OVERVIEW")
    print("=" * w)
    if len(df) > 0:
        total_buys = df["n_buys"].sum()
        total_sells = df["n_sells"].sum()
        total_net = df["net_value_mm"].sum()
        n_cluster_sell = df["is_cluster_sell"].sum()
        n_cluster_buy = df["is_cluster_buy"].sum()
        print(f"  Total Buys:         {total_buys}")
        print(f"  Total Sells:        {total_sells}")
        print(f"  Net Value (MM):     {total_net:+.2f}")
        print(f"  Cluster Selling:    {n_cluster_sell} names")
        print(f"  Cluster Buying:     {n_cluster_buy} names")
    else:
        print("  No insider data available")

    # 2. FULL RANKING
    print("\n" + "=" * w)
    print("  2. INSIDER ACTIVITY RANKING (most bearish first)")
    print("=" * w)
    if len(df) > 0:
        print(f"  {'Name':<28s} {'Sector':<14s} {'Buys':>5s} {'Sells':>5s} {'Net MM':>8s}"
              f" {'ClrSell':>7s} {'ClrBuy':>7s} {'Signal':>7s}")
        print("  " + "-" * 90)
        for _, row in df.iterrows():
            cls = " YES" if row["is_cluster_sell"] else "  no"
            clb = " YES" if row["is_cluster_buy"] else "  no"
            print(f"  {row['name']:<28s} {row['sector']:<14s} {row['n_buys']:>5d} {row['n_sells']:>5d}"
                  f" {row['net_value_mm']:>+7.2f} {cls:>7s} {clb:>7s} {row['insider_signal']:>+6.2f}")

    # 3. CLUSTER SELLING
    print("\n" + "=" * w)
    print("  3. CLUSTER SELLING ALERTS")
    print("=" * w)
    cluster_sell = df[df["is_cluster_sell"]] if len(df) > 0 else pd.DataFrame()
    if len(cluster_sell) > 0:
        for _, row in cluster_sell.iterrows():
            print(f"  ** {row['name']:<26s} sells={row['n_sells']}  sell_value={row['sell_value_mm']:.2f}MM"
                  f"  signal={row['insider_signal']:+.2f}")
    else:
        print("  No cluster selling detected")

    # 4. CLUSTER BUYING
    print("\n" + "=" * w)
    print("  4. CLUSTER BUYING SIGNALS")
    print("=" * w)
    cluster_buy = df[df["is_cluster_buy"]] if len(df) > 0 else pd.DataFrame()
    if len(cluster_buy) > 0:
        for _, row in cluster_buy.iterrows():
            print(f"  ** {row['name']:<26s} buys={row['n_buys']}  buy_value={row['buy_value_mm']:.2f}MM"
                  f"  signal={row['insider_signal']:+.2f}")
    else:
        print("  No cluster buying detected")

    # 5. ETF FLOW SENTIMENT
    print("\n" + "=" * w)
    print("  5. HY ETF FLOW SENTIMENT")
    print("=" * w)
    print(f"  ETF Flow Regime:    {etf_sentiment.get('flow_regime', 'N/A')}")
    print(f"  Composite Signal:   {etf_sentiment.get('composite_flow_signal', 0):+.2f}")
    for ticker, name in HY_ETFS.items():
        if ticker in etf_data:
            edf = etf_data[ticker]
            if len(edf) > 0:
                ret_20 = edf["return_20d"].iloc[-1] if "return_20d" in edf.columns else np.nan
                vol_z = edf["volume_zscore"].iloc[-1] if "volume_zscore" in edf.columns else np.nan
                ret_str = f"{ret_20*100:+.1f}%" if pd.notna(ret_20) else "N/A"
                vol_str = f"{vol_z:+.1f}" if pd.notna(vol_z) else "N/A"
                print(f"  {ticker:<10s} {name:<30s} 20d_ret={ret_str:>7s}  vol_z={vol_str}")

    # 6. SHORT INTEREST
    print("\n" + "=" * w)
    print("  6. SHORT INTEREST (where available)")
    print("=" * w)
    if len(short_df) > 0:
        print(f"  {'Name':<28s} {'Sector':<14s} {'Short%Float':>12s} {'ShortRatio':>10s}")
        print("  " + "-" * 68)
        for _, row in short_df.head(20).iterrows():
            sp = f"{row['short_pct_float']:.2f}%" if pd.notna(row.get("short_pct_float")) else "N/A"
            sr = f"{row['short_ratio']:.2f}" if pd.notna(row.get("short_ratio")) else "N/A"
            print(f"  {row['name']:<28s} {row['sector']:<14s} {sp:>11s} {sr:>10s}")
    else:
        print("  No short interest data available (expected for EU names)")

    # 7. SECTOR SUMMARY
    print("\n" + "=" * w)
    print("  7. SECTOR INSIDER SUMMARY")
    print("=" * w)
    if len(sector_df) > 0:
        print(f"  {'Sector':<18s} {'#Names':>6s} {'AvgSig':>7s} {'ClrSell':>7s} {'ClrBuy':>7s}"
              f" {'NetMM':>8s} {'Buys':>5s} {'Sells':>5s}")
        print("  " + "-" * 70)
        for _, row in sector_df.iterrows():
            print(f"  {row['sector']:<18s} {row['n_names']:>5d} {row['avg_signal']:>+6.2f}"
                  f" {row['n_cluster_sell']:>6d} {row['n_cluster_buy']:>6d}"
                  f" {row['total_net_mm']:>+7.2f} {row['total_buys']:>5d} {row['total_sells']:>5d}")

    # 8. IMPLICATIONS
    print("\n" + "=" * w)
    print("  8. iTRAXX CROSSOVER IMPLICATIONS")
    print("=" * w)

    n_warnings = len(warnings_df) if warnings_df is not None else 0
    etf_regime = etf_sentiment.get("flow_regime", "NEUTRAL")

    if n_warnings > 3:
        print(f"  -> WARNING: {n_warnings} names with insider selling/negative signals")
        print("     Insider activity suggests deteriorating credit fundamentals")
    elif len(df) > 0 and df["insider_signal"].mean() > 0.3:
        print("  -> CONSTRUCTIVE: Net insider buying across Crossover universe")

    if etf_regime == "RISK_OFF":
        print("  -> HY ETF FLOWS: Risk-off positioning, outflows from HY")
        print("     Supports wider spreads / short positioning")
    elif etf_regime == "RISK_ON":
        print("  -> HY ETF FLOWS: Risk-on positioning, inflows to HY")
        print("     Supports tighter spreads / long positioning")
    else:
        print("  -> HY ETF FLOWS: Neutral flow environment")

    print("\n" + "=" * w)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(df: pd.DataFrame, sector_df: pd.DataFrame,
                    etf_data: Dict[str, pd.DataFrame], etf_sentiment: dict,
                    warnings_df: pd.DataFrame):
    """Create 6-panel insider & flow dashboard."""
    fig = plt.figure(figsize=(24, 18))
    fig.patch.set_facecolor(CHART_BG)
    gs = gridspec.GridSpec(3, 3, hspace=0.35, wspace=0.25,
                           left=0.06, right=0.96, top=0.93, bottom=0.05)

    fig.suptitle("INSIDER & FLOW TRACKER - CROSSOVER UNIVERSE",
                 color=ACCENT_BLUE, fontsize=18, fontweight="bold", y=0.97,
                 fontfamily="monospace")

    # --- Panel 1: Insider signal bar chart ---
    ax1 = fig.add_subplot(gs[0, :2])
    ax1.set_facecolor(CHART_BG)
    ax1.set_title("Insider Signal by Name", color=CHART_FG, fontsize=11)

    if len(df) > 0:
        display = df.head(30)
        names = display["name"].tolist()
        vals = display["insider_signal"].tolist()
        bar_colors = [ACCENT_RED if v < -0.5 else ACCENT_GREEN if v > 0.5 else CHART_FG for v in vals]
        y_pos = range(len(names))
        ax1.barh(y_pos, vals, color=bar_colors, alpha=0.7, height=0.7)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels([n[:20] for n in names], fontsize=6, color=CHART_FG)
        ax1.axvline(0, color=CHART_FG, linewidth=0.5, alpha=0.5)
        ax1.set_xlabel("Insider Signal (-2 to +2)", color=CHART_FG, fontsize=8)
        ax1.invert_yaxis()

    ax1.tick_params(colors=CHART_FG, labelsize=7)
    for spine in ax1.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 2: Summary box ---
    ax2 = fig.add_subplot(gs[0, 2])
    ax2.set_facecolor(CHART_BG)
    ax2.axis("off")
    ax2.set_title("Summary", color=CHART_FG, fontsize=11)

    if len(df) > 0:
        n_cluster_sell = df["is_cluster_sell"].sum()
        n_cluster_buy = df["is_cluster_buy"].sum()
        n_warnings = len(warnings_df) if warnings_df is not None else 0
        regime = etf_sentiment.get("flow_regime", "N/A")
        regime_color = ACCENT_RED if regime == "RISK_OFF" else \
                       ACCENT_GREEN if regime == "RISK_ON" else ACCENT_ORANGE

        lines = [
            f"Names with Data: {len(df)}/{len(CONSTITUENTS)}",
            f"Warnings: {n_warnings}",
            f"",
            f"Cluster Selling: {n_cluster_sell}",
            f"Cluster Buying: {n_cluster_buy}",
            f"",
            f"ETF Regime: {regime}",
            f"ETF Signal: {etf_sentiment.get('composite_flow_signal', 0):+.2f}",
        ]
        for i, line in enumerate(lines):
            color = regime_color if i == 6 else CHART_FG
            ax2.text(0.05, 0.92 - i * 0.10, line, transform=ax2.transAxes,
                    fontsize=11, color=color, fontfamily="monospace", va="top")

    # --- Panel 3: Sector heatmap ---
    ax3 = fig.add_subplot(gs[1, :2])
    ax3.set_facecolor(CHART_BG)
    ax3.set_title("Sector Insider Summary", color=CHART_FG, fontsize=11)

    if len(sector_df) > 0:
        sectors = sector_df["sector"].tolist()
        metrics = ["avg_signal", "n_cluster_sell", "total_net_mm"]
        metric_labels = ["Avg Signal", "Cluster Sell", "Net Value MM"]

        heatmap_data = np.zeros((len(sectors), len(metrics)))
        for i, (_, row) in enumerate(sector_df.iterrows()):
            heatmap_data[i, 0] = row.get("avg_signal", 0)
            heatmap_data[i, 1] = -row.get("n_cluster_sell", 0)  # negative = bad
            heatmap_data[i, 2] = row.get("total_net_mm", 0)

        max_abs = max(abs(heatmap_data).max(), 0.01)
        im = ax3.imshow(heatmap_data / max_abs, aspect="auto", cmap="RdYlGn",
                        vmin=-1, vmax=1)
        ax3.set_xticks(range(len(metrics)))
        ax3.set_xticklabels(metric_labels, fontsize=9, color=CHART_FG)
        ax3.set_yticks(range(len(sectors)))
        ax3.set_yticklabels(sectors, fontsize=8, color=CHART_FG)

        for i in range(len(sectors)):
            for j, m in enumerate(metrics):
                val = [sector_df.iloc[i]["avg_signal"],
                       sector_df.iloc[i]["n_cluster_sell"],
                       sector_df.iloc[i]["total_net_mm"]][j]
                fmt = f"{val:+.1f}" if j != 1 else f"{int(val)}"
                ax3.text(j, i, fmt, ha="center", va="center", color=CHART_FG, fontsize=8)

    ax3.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax3.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 4: ETF volume Z-score time series ---
    ax4 = fig.add_subplot(gs[1, 2])
    ax4.set_facecolor(CHART_BG)
    ax4.set_title("IHYG.L Volume Z-Score", color=CHART_FG, fontsize=11)

    ihyg = etf_data.get("IHYG.L")
    if ihyg is not None and "volume_zscore" in ihyg.columns:
        vz = ihyg["volume_zscore"].dropna()
        ax4.fill_between(vz.index, 0, vz.values, where=(vz > 0),
                         color=ACCENT_GREEN, alpha=0.3)
        ax4.fill_between(vz.index, 0, vz.values, where=(vz < 0),
                         color=ACCENT_RED, alpha=0.3)
        ax4.plot(vz.index, vz.values, color=ACCENT_BLUE, linewidth=1)
        ax4.axhline(0, color=CHART_FG, linewidth=0.5, alpha=0.5)
        ax4.set_ylabel("Volume Z", color=CHART_FG, fontsize=8)
    else:
        ax4.text(0.5, 0.5, "No IHYG data", ha="center", va="center",
                color=CHART_FG, fontsize=11, transform=ax4.transAxes)

    ax4.tick_params(colors=CHART_FG, labelsize=7)
    for spine in ax4.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 5: Cluster activity detail ---
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.set_facecolor(CHART_BG)
    ax5.axis("off")
    ax5.set_title("Cluster Activity Detail", color=ACCENT_ORANGE, fontsize=11)

    cluster = df[(df["is_cluster_sell"]) | (df["is_cluster_buy"])] if len(df) > 0 else pd.DataFrame()
    if len(cluster) > 0:
        for i, (_, row) in enumerate(cluster.head(10).iterrows()):
            ctype = "SELL" if row["is_cluster_sell"] else "BUY"
            color = ACCENT_RED if ctype == "SELL" else ACCENT_GREEN
            line = f"{ctype:4s} {row['name'][:20]:<20s} buys={row['n_buys']} sells={row['n_sells']}"
            ax5.text(0.02, 0.92 - i * 0.09, line, transform=ax5.transAxes,
                    fontsize=9, color=color, fontfamily="monospace", va="top")
    else:
        ax5.text(0.5, 0.5, "No cluster activity", ha="center", va="center",
                color=CHART_FG, fontsize=11, transform=ax5.transAxes)

    # --- Panel 6: Net value scatter ---
    ax6 = fig.add_subplot(gs[2, 1:])
    ax6.set_facecolor(CHART_BG)
    ax6.set_title("Net Value vs Insider Signal", color=CHART_FG, fontsize=11)

    if len(df) > 0:
        x = df["net_value_mm"].values
        y = df["insider_signal"].values
        colors_arr = [ACCENT_RED if s < -0.5 else ACCENT_GREEN if s > 0.5
                      else ACCENT_BLUE for s in y]
        ax6.scatter(x, y, c=colors_arr, alpha=0.6, s=40)
        ax6.axhline(0, color=CHART_FG, linewidth=0.5, alpha=0.3)
        ax6.axvline(0, color=CHART_FG, linewidth=0.5, alpha=0.3)
        ax6.set_xlabel("Net Value (MM)", color=CHART_FG, fontsize=8)
        ax6.set_ylabel("Insider Signal", color=CHART_FG, fontsize=8)

    ax6.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax6.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # Save
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "insider_flow_dashboard.png")
    plt.savefig(out_path, dpi=150, facecolor=CHART_BG, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Chart saved: insider_flow_dashboard.png")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run Insider & Flow Tracker pipeline."""
    w = 80
    print("\n" + "=" * w)
    print("  MODULE 16: INSIDER & FLOW TRACKER")
    print("  Insider Transactions, HY ETF Flows, Short Interest")
    print("=" * w)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Check API key
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        print("\n  ERROR: FINNHUB_API_KEY not set")
        print("  Set via: set FINNHUB_API_KEY=your_key")
        print("  Get free key: https://finnhub.io/register")
        return

    # 1. Fetch insider data
    print("\n  Step 1: Fetching insider transactions from Finnhub...")
    all_insider = fetch_all_insider_data(api_key)

    # 2. Compute metrics
    print("\n  Step 2: Computing insider metrics...")
    df = compute_all_insider_metrics(all_insider)
    print(f"  -> {len(df)} names with insider metrics")

    # 3. Fetch short interest (best effort)
    print("\n  Step 3: Fetching short interest...")
    short_df = fetch_short_interest()

    # 4. Fetch ETF flows
    print("\n  Step 4: Fetching HY ETF flow data...")
    etf_data = fetch_etf_flows()

    # 5. ETF sentiment
    print("\n  Step 5: Computing ETF flow sentiment...")
    etf_sentiment = compute_etf_sentiment(etf_data)
    print(f"  -> Regime: {etf_sentiment['flow_regime']}, Signal: {etf_sentiment['composite_flow_signal']:+.2f}")

    # 6. Sector summary
    print("\n  Step 6: Computing sector summaries...")
    sector_df = sector_insider_summary(df)

    # 7. Flag warnings
    print("\n  Step 7: Flagging insider warnings...")
    warnings_df = flag_insider_warnings(df)
    print(f"  -> {len(warnings_df)} names flagged")

    # 8. Report
    print_report(df, sector_df, short_df, warnings_df, etf_sentiment, etf_data)

    # 9. Chart
    print("\n  Step 9: Generating dashboard chart...")
    plot_dashboard(df, sector_df, etf_data, etf_sentiment, warnings_df)

    # 10. CSV
    if len(df) > 0:
        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "insider_flow_tracker.csv")
        df.to_csv(csv_path, index=False)
        print(f"  CSV saved: insider_flow_tracker.csv")

    print("\n  DONE.")


if __name__ == "__main__":
    main()

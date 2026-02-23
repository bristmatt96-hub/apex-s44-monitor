#!/usr/bin/env python3
"""
Equity-Implied Credit Signals
===============================
5 equity-based signals per iTraxx Crossover constituent that historically
lead credit spread moves by 1-3 months:

  1. Vol Regime      - Rising vol precedes spread widening
  2. Equity Momentum - Equity weakness leads credit weakness
  3. Drawdown Severity - Deep drawdowns signal fallen angel risk
  4. Leverage/MCap Erosion - Shrinking MCap = rising leverage = wider spreads
  5. Equity-Credit Beta - Vol sensitivity to equity declines = fragility

Each signal scores -2 to +2. Composite weighted average ranks all names.

Usage:
  pip install yfinance pandas matplotlib numpy
  python equity_credit_signals.py

Author: Built with Claude for macro credit trading
"""

import os
import sys
import warnings
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

warnings.filterwarnings("ignore")

PARENT_DIR = os.path.dirname(os.path.abspath(__file__))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import analytics.crossover_constituents as xoc

# =============================================================================
# CONFIGURATION
# =============================================================================

SIGNAL_WEIGHTS = {
    "vol_regime": 0.25,
    "momentum": 0.25,
    "drawdown": 0.20,
    "leverage": 0.20,
    "eq_credit_beta": 0.10,
}

CLASSIFICATIONS = [
    (1.0, "STRONG IMPROVEMENT"),
    (0.5, "IMPROVING"),
    (-0.5, "NEUTRAL"),
    (-1.0, "DETERIORATING"),
    (float("-inf"), "STRONG DETERIORATION"),
]


# =============================================================================
# INDIVIDUAL SIGNAL FUNCTIONS
# =============================================================================

def signal_vol_regime(vol_21d: float, vol_63d: float, vol_252d: float) -> Tuple[int, str]:
    """
    Equity volatility regime signal.
    Rising vol precedes spread widening by 1-3 months.

    Returns: (score -2 to +2, detail string)
    """
    if pd.isna(vol_21d) or vol_252d <= 0:
        return 0, "N/A"

    vol_ratio = vol_21d / vol_252d if vol_252d > 0 else 1.0

    # Absolute crisis override
    if vol_21d > 50:
        return -2, f"CRISIS (vol={vol_21d:.0f}%)"
    if vol_21d > 35:
        score = max(-2, -1 - int(vol_ratio > 1.5))
        return score, f"ELEVATED (vol={vol_21d:.0f}%, ratio={vol_ratio:.2f})"

    # Relative regime
    if vol_ratio > 1.5:
        return -2, f"CRISIS ratio ({vol_ratio:.2f})"
    elif vol_ratio > 1.0:
        return -1, f"ELEVATED ({vol_ratio:.2f})"
    elif vol_ratio > 0.7:
        return 0, f"NORMAL ({vol_ratio:.2f})"
    else:
        return 1, f"LOW ({vol_ratio:.2f})"


def signal_momentum(mom_63d: float, mom_126d: float) -> Tuple[int, str]:
    """
    Equity momentum signal.
    Equity weakness leads credit weakness by 1-3 months.
    """
    if pd.isna(mom_63d):
        return 0, "N/A"

    # Base score from 63d momentum
    if mom_63d > 15:
        score = 2
    elif mom_63d > 5:
        score = 1
    elif mom_63d > -5:
        score = 0
    elif mom_63d > -15:
        score = -1
    else:
        score = -2

    detail = f"63d={mom_63d:+.1f}%"

    # Accelerating decline penalty
    if not pd.isna(mom_126d) and mom_63d < 0 and mom_126d < 0:
        if mom_63d < mom_126d:  # getting worse faster
            score = max(-2, score - 1)
            detail += f" ACCEL (126d={mom_126d:+.1f}%)"
        else:
            detail += f" (126d={mom_126d:+.1f}%)"

    return score, detail


def signal_drawdown(drawdown_52w: float) -> Tuple[int, str]:
    """
    Drawdown severity signal.
    Deep drawdowns from 52-week high signal fallen angel risk.
    """
    if pd.isna(drawdown_52w):
        return 0, "N/A"

    if drawdown_52w > -5:
        return 1, f"Near highs ({drawdown_52w:+.1f}%)"
    elif drawdown_52w > -15:
        return 0, f"Normal ({drawdown_52w:+.1f}%)"
    elif drawdown_52w > -30:
        return -1, f"Significant ({drawdown_52w:+.1f}%)"
    else:
        return -2, f"SEVERE ({drawdown_52w:+.1f}%)"


def signal_leverage(leverage_ratio: float, mcap_change_63d: float) -> Tuple[int, str]:
    """
    Leverage / market cap erosion signal.
    Shrinking MCap with fixed debt = rising leverage = wider spreads.
    """
    if pd.isna(leverage_ratio):
        return 0, "N/A"

    # Base score from leverage level
    if leverage_ratio < 0.5:
        score = 1
    elif leverage_ratio < 1.0:
        score = 0
    elif leverage_ratio < 2.0:
        score = -1
    else:
        score = -2

    detail = f"Lev={leverage_ratio:.2f}x"

    # MCap erosion adjustment
    if not pd.isna(mcap_change_63d):
        if mcap_change_63d < -20:
            score = max(-2, score - 1)
            detail += f" MCap_chg={mcap_change_63d:+.0f}%!"
        elif mcap_change_63d > 20:
            score = min(2, score + 1)
            detail += f" MCap_chg={mcap_change_63d:+.0f}%"
        else:
            detail += f" MCap_chg={mcap_change_63d:+.0f}%"

    return score, detail


def signal_eq_credit_beta(prices: pd.Series) -> Tuple[int, str]:
    """
    Equity-credit beta signal.
    How sensitive is this name's vol to equity declines?
    High beta = fragile name, vol spikes on small equity moves.
    """
    if prices is None or len(prices) < 126:
        return 0, "N/A"

    returns = prices.pct_change().dropna()
    if len(returns) < 63:
        return 0, "N/A"

    # Compute rolling 21d vol
    vol_21d = returns.rolling(21).std() * np.sqrt(252)
    vol_change = vol_21d.diff()

    # Compare vol changes on negative return days vs positive
    daily_ret = returns.tail(252)
    vol_chg = vol_change.reindex(daily_ret.index)

    neg_days = daily_ret[daily_ret < -0.01]  # down >1% days
    if len(neg_days) < 10:
        return 0, "Insufficient neg days"

    # Average vol increase on negative days
    vol_on_neg = vol_chg.reindex(neg_days.index).dropna()
    if len(vol_on_neg) < 5:
        return 0, "Insufficient data"

    avg_vol_spike = vol_on_neg.mean() * 252  # annualize
    vol_sensitivity = abs(avg_vol_spike) / (returns.tail(252).std() * np.sqrt(252))

    if vol_sensitivity < 0.5:
        score = 1
        detail = f"Resilient (beta={vol_sensitivity:.2f})"
    elif vol_sensitivity < 1.5:
        score = 0
        detail = f"Normal (beta={vol_sensitivity:.2f})"
    elif vol_sensitivity < 3.0:
        score = -1
        detail = f"Fragile (beta={vol_sensitivity:.2f})"
    else:
        score = -2
        detail = f"VERY FRAGILE (beta={vol_sensitivity:.2f})"

    return score, detail


# =============================================================================
# COMPOSITE SIGNAL
# =============================================================================

def _classify(composite: float) -> str:
    """Map composite score to classification string."""
    for threshold, label in CLASSIFICATIONS:
        if composite >= threshold:
            return label
    return "STRONG DETERIORATION"


def compute_all_signals(metrics_df: pd.DataFrame, constituents: List) -> pd.DataFrame:
    """
    Compute all 5 signals + composite for each constituent.

    Returns DataFrame sorted by composite (most bearish first).
    """
    print(f"\n{'=' * 80}")
    print("  EQUITY-IMPLIED CREDIT SIGNALS")
    print(f"{'=' * 80}")

    rows = []
    for _, row in metrics_df.iterrows():
        # Find matching constituent for prices
        prices = None
        for c in constituents:
            if c.name == row["name"] and c.fetch_success and c.prices is not None:
                prices = c.prices
                break

        # Compute each signal
        s_vol, d_vol = signal_vol_regime(row["vol_21d"], row["vol_63d"], row["vol_252d"])
        s_mom, d_mom = signal_momentum(row.get("momentum_63d"), row.get("momentum_126d"))
        s_dd, d_dd = signal_drawdown(row["drawdown_52w"])
        s_lev, d_lev = signal_leverage(row.get("leverage_ratio"), row.get("mcap_change_63d"))
        s_beta, d_beta = signal_eq_credit_beta(prices)

        # Clamp all signals to [-2, +2]
        signals = {
            "vol_regime": max(-2, min(2, s_vol)),
            "momentum": max(-2, min(2, s_mom)),
            "drawdown": max(-2, min(2, s_dd)),
            "leverage": max(-2, min(2, s_lev)),
            "eq_credit_beta": max(-2, min(2, s_beta)),
        }

        # Weighted composite
        composite = sum(signals[k] * SIGNAL_WEIGHTS[k] for k in signals)
        classification = _classify(composite)

        rows.append({
            "name": row["name"],
            "ticker": row["ticker"],
            "sector": row["sector"],
            "rating": row["rating"],
            "sig_vol": signals["vol_regime"],
            "sig_mom": signals["momentum"],
            "sig_dd": signals["drawdown"],
            "sig_lev": signals["leverage"],
            "sig_beta": signals["eq_credit_beta"],
            "composite": round(composite, 3),
            "classification": classification,
            "detail_vol": d_vol,
            "detail_mom": d_mom,
            "detail_dd": d_dd,
            "detail_lev": d_lev,
            "detail_beta": d_beta,
        })

        sig_bar = "+" * max(0, int(composite * 3)) if composite > 0 else "-" * max(0, int(-composite * 3))
        print(f"  {row['name']:<30s} | Vol={s_vol:+d} Mom={s_mom:+d} DD={s_dd:+d} "
              f"Lev={s_lev:+d} Beta={s_beta:+d} | Comp={composite:>+6.2f} | {classification}")

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("composite", ascending=True).reset_index(drop=True)

    print(f"\n  Computed: {len(df)} names")
    return df


# =============================================================================
# SECTOR AGGREGATION & RANKING
# =============================================================================

def sector_summary(signals_df: pd.DataFrame) -> pd.DataFrame:
    """Average composite signal by sector."""
    if len(signals_df) == 0:
        return pd.DataFrame()

    sector_agg = signals_df.groupby("sector").agg({
        "name": "count",
        "composite": "mean",
        "sig_vol": "mean",
        "sig_mom": "mean",
        "sig_dd": "mean",
        "sig_lev": "mean",
        "sig_beta": "mean",
    }).rename(columns={"name": "count"})

    sector_agg["pct_deteriorating"] = signals_df.groupby("sector").apply(
        lambda g: (g["classification"].isin(["DETERIORATING", "STRONG DETERIORATION"])).mean() * 100
    )
    sector_agg["pct_improving"] = signals_df.groupby("sector").apply(
        lambda g: (g["classification"].isin(["IMPROVING", "STRONG IMPROVEMENT"])).mean() * 100
    )

    sector_agg = sector_agg.sort_values("composite").reset_index()
    for col in ["composite", "sig_vol", "sig_mom", "sig_dd", "sig_lev", "sig_beta"]:
        sector_agg[col] = sector_agg[col].round(2)
    sector_agg["pct_deteriorating"] = sector_agg["pct_deteriorating"].round(0)
    sector_agg["pct_improving"] = sector_agg["pct_improving"].round(0)

    return sector_agg


def rank_constituents(signals_df: pd.DataFrame) -> pd.DataFrame:
    """Add rank column (1 = most bullish) and quartile."""
    if len(signals_df) == 0:
        return signals_df

    df = signals_df.copy()
    df["rank"] = df["composite"].rank(ascending=False, method="min").astype(int)
    n = len(df)
    df["quartile"] = pd.cut(df["rank"], bins=[0, n * 0.25, n * 0.5, n * 0.75, n + 1],
                             labels=["Q1 (Best)", "Q2", "Q3", "Q4 (Worst)"])
    return df.sort_values("composite", ascending=True).reset_index(drop=True)


# =============================================================================
# CONSOLE OUTPUT
# =============================================================================

def print_report(signals_df: pd.DataFrame, sector_df: pd.DataFrame):
    """Print full equity credit signals report."""
    print(f"\n{'=' * 110}")
    print("  EQUITY-IMPLIED CREDIT SIGNALS - FULL REPORT")
    print(f"{'=' * 110}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Signal weights: Vol={SIGNAL_WEIGHTS['vol_regime']:.0%} Mom={SIGNAL_WEIGHTS['momentum']:.0%} "
          f"DD={SIGNAL_WEIGHTS['drawdown']:.0%} Lev={SIGNAL_WEIGHTS['leverage']:.0%} "
          f"Beta={SIGNAL_WEIGHTS['eq_credit_beta']:.0%}")

    # Full ranking
    print(f"\n{'=' * 110}")
    print("  1. FULL SIGNAL RANKING (most bearish first)")
    print(f"{'=' * 110}")
    print(f"  {'Rank':>4s} {'Name':<28s} {'Sector':<15s} {'Vol':>4s} {'Mom':>4s} {'DD':>4s} "
          f"{'Lev':>4s} {'Beta':>5s} {'Comp':>7s} {'Class':<22s}")
    print("  " + "-" * 106)

    for _, row in signals_df.iterrows():
        rank = row.get("rank", "")
        print(f"  {rank:>4} {row['name']:<28s} {row['sector']:<15s} "
              f"{row['sig_vol']:>+4d} {row['sig_mom']:>+4d} {row['sig_dd']:>+4d} "
              f"{row['sig_lev']:>+4d} {row['sig_beta']:>+5d} {row['composite']:>+7.2f} {row['classification']:<22s}")

    # Top 5 bearish
    print(f"\n{'=' * 110}")
    print("  2. TOP 5 MOST BEARISH (buy protection candidates)")
    print(f"{'=' * 110}")
    for _, row in signals_df.head(5).iterrows():
        print(f"  >>> {row['name']:<30s} Composite: {row['composite']:>+.2f} ({row['classification']})")
        print(f"      Vol: {row['detail_vol']}")
        print(f"      Mom: {row['detail_mom']}")
        print(f"      DD:  {row['detail_dd']}")
        print(f"      Lev: {row['detail_lev']}")
        print()

    # Top 5 bullish
    print(f"{'=' * 110}")
    print("  3. TOP 5 MOST BULLISH (sell protection candidates)")
    print(f"{'=' * 110}")
    for _, row in signals_df.tail(5).iloc[::-1].iterrows():
        print(f"  <<< {row['name']:<30s} Composite: {row['composite']:>+.2f} ({row['classification']})")
        print(f"      Vol: {row['detail_vol']}")
        print(f"      Mom: {row['detail_mom']}")
        print(f"      DD:  {row['detail_dd']}")
        print(f"      Lev: {row['detail_lev']}")
        print()

    # Sector summary
    if len(sector_df) > 0:
        print(f"{'=' * 110}")
        print("  4. SECTOR SIGNAL SUMMARY")
        print(f"{'=' * 110}")
        print(f"  {'Sector':<20s} {'Count':>5s} {'Composite':>10s} {'%Deter':>8s} {'%Improv':>8s} "
              f"{'AvgVol':>7s} {'AvgMom':>7s} {'AvgDD':>7s} {'AvgLev':>7s}")
        print("  " + "-" * 85)
        for _, row in sector_df.iterrows():
            print(f"  {row['sector']:<20s} {int(row['count']):>5d} {row['composite']:>+10.2f} "
                  f"{row['pct_deteriorating']:>7.0f}% {row['pct_improving']:>7.0f}% "
                  f"{row['sig_vol']:>+7.2f} {row['sig_mom']:>+7.2f} {row['sig_dd']:>+7.2f} {row['sig_lev']:>+7.2f}")

    # Distribution summary
    print(f"\n{'=' * 110}")
    print("  5. SIGNAL DISTRIBUTION")
    print(f"{'=' * 110}")
    for cls in ["STRONG DETERIORATION", "DETERIORATING", "NEUTRAL", "IMPROVING", "STRONG IMPROVEMENT"]:
        n = len(signals_df[signals_df["classification"] == cls])
        bar = "|" * n
        print(f"  {cls:<25s} {n:>3d} {bar}")

    # iTRAXX implications
    print(f"\n{'=' * 110}")
    print("  6. iTRAXX CROSSOVER IMPLICATIONS")
    print(f"{'=' * 110}")

    avg_comp = signals_df["composite"].mean()
    n_strong_det = len(signals_df[signals_df["classification"] == "STRONG DETERIORATION"])
    n_det = len(signals_df[signals_df["classification"].isin(["DETERIORATING", "STRONG DETERIORATION"])])

    if avg_comp < -0.5 or n_strong_det > 5:
        print("  >>> BEARISH: Broad equity deterioration across constituents")
        print("  >>> BUY Crossover protection, reduce single-name exposure")
    elif avg_comp < -0.2 or n_det > len(signals_df) * 0.4:
        print("  >>> CAUTIOUS: Elevated number of deteriorating names")
        print("  >>> Selective approach: avoid weak names, maintain quality longs")
    elif avg_comp > 0.3:
        print("  >>> BULLISH: Broad equity improvement supporting credit")
        print("  >>> SELL Crossover protection, add single-name longs")
    else:
        print("  >>> MIXED: No strong directional bias from equity signals")
        print("  >>> Focus on relative value between strong and weak names")

    print("\n" + "=" * 110)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(signals_df: pd.DataFrame, sector_df: pd.DataFrame,
                    metrics_df: pd.DataFrame):
    """Create equity credit signals dashboard."""
    if len(signals_df) == 0:
        print("  No data to plot.")
        return

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "EQUITY-IMPLIED CREDIT SIGNALS - iTRAXX CROSSOVER CONSTITUENTS",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(
        0.5, 0.955,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(signals_df)} names | "
        f"Weights: Vol={SIGNAL_WEIGHTS['vol_regime']:.0%} Mom={SIGNAL_WEIGHTS['momentum']:.0%} "
        f"DD={SIGNAL_WEIGHTS['drawdown']:.0%} Lev={SIGNAL_WEIGHTS['leverage']:.0%} Beta={SIGNAL_WEIGHTS['eq_credit_beta']:.0%}",
        ha="center", fontsize=9, color="gray",
    )

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # --- Panel 1: Composite Signal Bar Chart ---
    ax1 = fig.add_subplot(gs[0, :2])
    sorted_df = signals_df.sort_values("composite", ascending=True)
    n = len(sorted_df)
    # Color gradient: red (bearish) -> yellow (neutral) -> green (bullish)
    cmap = plt.cm.RdYlGn
    norm_vals = (sorted_df["composite"].values - sorted_df["composite"].min())
    val_range = sorted_df["composite"].max() - sorted_df["composite"].min()
    if val_range > 0:
        norm_vals = norm_vals / val_range
    else:
        norm_vals = np.full(n, 0.5)
    colors = [cmap(v) for v in norm_vals]

    ax1.barh(range(n), sorted_df["composite"].values, color=colors, edgecolor="white", linewidth=0.3)
    ax1.set_yticks(range(n))
    ax1.set_yticklabels([f"{name[:18]} ({cls[:8]})" for name, cls in
                          zip(sorted_df["name"], sorted_df["classification"])], fontsize=5.5)
    ax1.axvline(0, color="black", linewidth=0.8)
    ax1.axvline(-0.5, color="#e74c3c", linewidth=0.7, linestyle="--")
    ax1.axvline(0.5, color="#2ecc71", linewidth=0.7, linestyle="--")
    ax1.set_title("Composite Credit Signal - All Constituents", fontweight="bold")
    ax1.set_xlabel("Signal (negative = bearish for credit)")
    ax1.grid(True, alpha=0.3, axis="x")

    # --- Panel 2: Summary Box ---
    ax_sum = fig.add_subplot(gs[0, 2])
    ax_sum.set_xlim(0, 1)
    ax_sum.set_ylim(0, 1)
    ax_sum.axis("off")

    avg_comp = signals_df["composite"].mean()
    n_sd = len(signals_df[signals_df["classification"] == "STRONG DETERIORATION"])
    n_d = len(signals_df[signals_df["classification"] == "DETERIORATING"])
    n_n = len(signals_df[signals_df["classification"] == "NEUTRAL"])
    n_i = len(signals_df[signals_df["classification"] == "IMPROVING"])
    n_si = len(signals_df[signals_df["classification"] == "STRONG IMPROVEMENT"])

    box = FancyBboxPatch((0.05, 0.05), 0.9, 0.9, boxstyle="round,pad=0.05",
                          facecolor="#2c3e50", alpha=0.15, edgecolor="#2c3e50", linewidth=2)
    ax_sum.add_patch(box)
    ax_sum.text(0.5, 0.90, "SIGNAL SUMMARY", ha="center", fontsize=12, fontweight="bold")
    ax_sum.text(0.5, 0.78, f"Avg Composite: {avg_comp:+.3f}", ha="center", fontsize=11, fontweight="bold",
                color="#2ecc71" if avg_comp > 0.2 else "#e74c3c" if avg_comp < -0.2 else "#f39c12")

    y = 0.63
    for label, count, color in [
        ("Strong Deter.", n_sd, "#c0392b"), ("Deteriorating", n_d, "#e74c3c"),
        ("Neutral", n_n, "#f39c12"), ("Improving", n_i, "#2ecc71"),
        ("Strong Improv.", n_si, "#27ae60"),
    ]:
        ax_sum.text(0.15, y, label, fontsize=8, va="center")
        ax_sum.text(0.75, y, str(count), fontsize=11, fontweight="bold", va="center", color=color)
        y -= 0.09

    # --- Panel 3: Sector Heatmap ---
    ax2 = fig.add_subplot(gs[1, :2])
    if len(sector_df) > 0:
        sig_cols = ["sig_vol", "sig_mom", "sig_dd", "sig_lev", "sig_beta", "composite"]
        heatmap_data = sector_df.set_index("sector")[sig_cols].copy()
        heatmap_data = heatmap_data.sort_values("composite")

        im = ax2.imshow(heatmap_data.values, cmap="RdYlGn", aspect="auto", vmin=-2, vmax=2)
        ax2.set_yticks(range(len(heatmap_data)))
        ax2.set_yticklabels(heatmap_data.index, fontsize=7)
        col_labels = ["Vol", "Momentum", "Drawdown", "Leverage", "Beta", "Composite"]
        ax2.set_xticks(range(len(sig_cols)))
        ax2.set_xticklabels(col_labels, fontsize=8)
        ax2.set_title("Sector Signal Heatmap (red = bearish, green = bullish)", fontweight="bold", fontsize=10)

        # Annotate
        for i in range(len(heatmap_data)):
            for j in range(len(sig_cols)):
                val = heatmap_data.iloc[i, j]
                ax2.text(j, i, f"{val:+.1f}", ha="center", va="center", fontsize=6.5,
                         color="white" if abs(val) > 1.2 else "black")

        plt.colorbar(im, ax=ax2, fraction=0.02, pad=0.04)

    # --- Panel 4: Signal Distribution Histograms ---
    ax3 = fig.add_subplot(gs[1, 2])
    signal_cols = ["sig_vol", "sig_mom", "sig_dd", "sig_lev", "sig_beta"]
    signal_labels = ["Vol", "Mom", "DD", "Lev", "Beta"]
    colors_hist = ["#8e44ad", "#3498db", "#e67e22", "#e74c3c", "#27ae60"]
    means = []
    for col in signal_cols:
        means.append(signals_df[col].mean())

    x = np.arange(len(signal_labels))
    ax3.bar(x, means, color=colors_hist, edgecolor="white", alpha=0.8)
    ax3.set_xticks(x)
    ax3.set_xticklabels(signal_labels, fontsize=9)
    ax3.set_ylabel("Average Signal")
    ax3.axhline(0, color="black", linewidth=0.8)
    ax3.set_title("Average Signal by Type", fontweight="bold", fontsize=10)
    ax3.grid(True, alpha=0.3, axis="y")

    # Annotate
    for i, v in enumerate(means):
        ax3.text(i, v + 0.05 if v >= 0 else v - 0.15, f"{v:+.2f}", ha="center", fontsize=8)

    # --- Panel 5: Composite vs Drawdown Scatter ---
    ax4 = fig.add_subplot(gs[2, 0])
    if "drawdown_52w" in metrics_df.columns:
        merged = signals_df.merge(metrics_df[["name", "drawdown_52w"]], on="name", how="left")
        if len(merged) > 0:
            cls_colors = {
                "STRONG DETERIORATION": "#c0392b", "DETERIORATING": "#e74c3c",
                "NEUTRAL": "#f39c12", "IMPROVING": "#2ecc71", "STRONG IMPROVEMENT": "#27ae60",
            }
            for _, row in merged.iterrows():
                c = cls_colors.get(row["classification"], "#95a5a6")
                ax4.scatter(row["drawdown_52w"], row["composite"], c=c, s=40, alpha=0.7,
                            edgecolor="white", linewidth=0.5)

            # Label extremes
            for _, row in merged.nsmallest(5, "composite").iterrows():
                ax4.annotate(row["name"][:12], (row["drawdown_52w"], row["composite"]),
                             fontsize=5.5, alpha=0.8)

            ax4.set_xlabel("Drawdown from 52w High (%)")
            ax4.set_ylabel("Composite Signal")
            ax4.axhline(0, color="gray", linewidth=0.7, linestyle="--")
            ax4.set_title("Signal vs Drawdown", fontweight="bold", fontsize=10)
            ax4.grid(True, alpha=0.3)

    # --- Panel 6: Top 10 Deteriorating Detail ---
    ax5 = fig.add_subplot(gs[2, 1:])
    worst = signals_df.head(10).copy()
    if len(worst) > 0:
        categories = ["sig_vol", "sig_mom", "sig_dd", "sig_lev", "sig_beta"]
        cat_labels = ["Vol", "Mom", "DD", "Lev", "Beta"]
        cat_colors = ["#8e44ad", "#3498db", "#e67e22", "#e74c3c", "#27ae60"]

        y_positions = np.arange(len(worst))
        width = 0.15
        for i, (cat, color) in enumerate(zip(categories, cat_colors)):
            offset = (i - 2) * width
            vals = worst[cat].values
            ax5.barh(y_positions + offset, vals, height=width, color=color, alpha=0.8,
                     edgecolor="white", linewidth=0.3, label=cat_labels[i])

        ax5.set_yticks(y_positions)
        ax5.set_yticklabels([n[:22] for n in worst["name"]], fontsize=7)
        ax5.axvline(0, color="black", linewidth=0.8)
        ax5.set_xlabel("Signal Score")
        ax5.set_title("Top 10 Bearish Names - Signal Breakdown", fontweight="bold", fontsize=10)
        ax5.legend(fontsize=7, loc="lower right")
        ax5.grid(True, alpha=0.3, axis="x")

    plt.savefig("equity_credit_signals_dashboard.png", dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: equity_credit_signals_dashboard.png")
    plt.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 70)
    print("  EQUITY-IMPLIED CREDIT SIGNALS")
    print("  iTraxx Crossover Constituents")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. Get constituent data
    print("  Step 1: Fetching constituent data...")
    constituents = xoc.fetch_all_constituents(use_cache=True)
    success = [c for c in constituents if c.fetch_success]

    print(f"\n  Step 2: Computing equity metrics...")
    metrics_df = xoc.compute_equity_metrics(success)

    # 2. Compute signals
    print(f"\n  Step 3: Computing credit signals...")
    signals_df = compute_all_signals(metrics_df, success)

    # 3. Sector summary
    print(f"\n  Step 4: Sector aggregation...")
    sector_df = sector_summary(signals_df)

    # 4. Rank
    ranked_df = rank_constituents(signals_df)

    # 5. Report
    print_report(ranked_df, sector_df)

    # 6. Dashboard
    print("\n  Generating dashboard chart...")
    plot_dashboard(ranked_df, sector_df, metrics_df)

    # 7. Save
    if len(ranked_df) > 0:
        ranked_df.to_csv("equity_credit_signals.csv", index=False)
        print(f"  Signals saved: equity_credit_signals.csv")
    if len(sector_df) > 0:
        sector_df.to_csv("equity_credit_sector_signals.csv", index=False)
        print(f"  Sector signals saved: equity_credit_sector_signals.csv")

    print("\n  DONE.\n")


if __name__ == "__main__":
    main()

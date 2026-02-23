#!/usr/bin/env python3
"""
Merton Single-Name Distance-to-Default Model
==============================================
Classical structural credit model applied to each iTraxx Crossover constituent.
Treats equity as a call option on firm assets (Black-Scholes-Merton framework).

For each constituent, solves for:
  - Asset Value (V) and Asset Volatility (sigma_V) via iterative solver
  - Distance to Default (DD)
  - Implied probability of default
  - Implied credit spread (bps)

Tracks DD changes over time to detect credit deterioration/improvement.

Data Sources: Yahoo Finance (via crossover_constituents module), FRED (risk-free rate)

Usage:
  pip install yfinance pandas matplotlib numpy scipy
  python merton_single_name.py

Author: Built with Claude for macro credit trading
"""

import os
import sys
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
from scipy.optimize import fsolve
from scipy.stats import norm

warnings.filterwarnings("ignore")

# Add parent directory for imports
PARENT_DIR = os.path.dirname(os.path.abspath(__file__))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import analytics.crossover_constituents as xoc

# =============================================================================
# CONFIGURATION
# =============================================================================

RISK_FREE_RATE = 0.035      # ~3.5% EUR risk-free (overridden from FRED if available)
DEBT_MATURITY_T = 5.0       # 5-year average maturity assumption for HY
RECOVERY_RATE = 0.40        # Standard HY recovery
DD_DETERIORATION_THRESHOLD = -0.5  # 4-week DD decline that triggers flag
DD_IMPROVEMENT_THRESHOLD = 0.5
DD_LOOKBACK_WEEKS = 52      # Weekly DD snapshots over past year

# Quality tier thresholds
DD_TIERS = {
    "Safe":         (3.0, float("inf")),
    "Adequate":     (2.0, 3.0),
    "Vulnerable":   (1.0, 2.0),
    "Distressed":   (0.5, 1.0),
    "Default_Risk": (float("-inf"), 0.5),
}


# =============================================================================
# MERTON MODEL SOLVER
# =============================================================================

def solve_merton(E: float, sigma_E: float, D: float, r: float, T: float = 5.0) -> Optional[Dict]:
    """
    Solve the Merton structural credit model for asset value and asset volatility.

    In the Merton framework, equity is a call option on firm assets:
      E = V * N(d1) - D * exp(-r*T) * N(d2)      ... equity value equation
      sigma_E * E = N(d1) * sigma_V * V           ... volatility relationship

    Parameters:
        E: equity market cap ($M)
        sigma_E: equity volatility (annualized, decimal e.g. 0.35 for 35%)
        D: face value of debt ($M)
        r: risk-free rate (decimal e.g. 0.035)
        T: time to debt maturity in years

    Returns:
        dict with V, sigma_V, d1, d2, DD, default_prob, implied_spread_bps
        or None if solver fails
    """
    if E <= 0 or D <= 0 or sigma_E <= 0.001:
        return None

    def equations(unknowns):
        V, sigma_V = unknowns
        if V <= 0 or sigma_V <= 0.001:
            return [1e10, 1e10]

        d1 = (np.log(V / D) + (r + 0.5 * sigma_V**2) * T) / (sigma_V * np.sqrt(T))
        d2 = d1 - sigma_V * np.sqrt(T)

        eq1 = V * norm.cdf(d1) - D * np.exp(-r * T) * norm.cdf(d2) - E
        eq2 = norm.cdf(d1) * sigma_V * V - sigma_E * E

        return [eq1, eq2]

    # Initial guess
    V0 = E + D
    sigma_V0 = sigma_E * E / V0

    try:
        solution, info, ier, msg = fsolve(equations, [V0, sigma_V0], full_output=True)
        V_solved, sigma_V_solved = solution

        if V_solved <= 0 or sigma_V_solved <= 0.001 or ier != 1:
            # Fallback: simplified DD formula
            return _simplified_merton(E, sigma_E, D, r, T)

        d1 = (np.log(V_solved / D) + (r + 0.5 * sigma_V_solved**2) * T) / (sigma_V_solved * np.sqrt(T))
        d2 = d1 - sigma_V_solved * np.sqrt(T)

        DD = d2  # Distance to Default
        default_prob = norm.cdf(-d2)  # N(-d2) = probability of default

        # Implied credit spread (risk-neutral)
        risky_debt_value = D * np.exp(-r * T) * norm.cdf(d2) + V_solved * norm.cdf(-d1)
        riskfree_debt_value = D * np.exp(-r * T)
        if risky_debt_value > 0 and riskfree_debt_value > 0:
            implied_spread = -(1 / T) * np.log(risky_debt_value / riskfree_debt_value) * 10000
        else:
            implied_spread = 0

        return {
            "V": V_solved,
            "sigma_V": sigma_V_solved,
            "d1": d1,
            "d2": d2,
            "DD": DD,
            "default_prob": default_prob * 100,
            "implied_spread_bps": max(0, implied_spread),
            "method": "full",
        }

    except Exception:
        return _simplified_merton(E, sigma_E, D, r, T)


def _simplified_merton(E: float, sigma_E: float, D: float, r: float, T: float) -> Optional[Dict]:
    """
    Simplified Merton fallback when the full solver doesn't converge.
    Assumes V = E + D, sigma_V = sigma_E * E / (E + D).
    """
    try:
        V = E + D
        sigma_V = sigma_E * E / V

        d1 = (np.log(V / D) + (r + 0.5 * sigma_V**2) * T) / (sigma_V * np.sqrt(T))
        d2 = d1 - sigma_V * np.sqrt(T)

        DD = d2
        default_prob = norm.cdf(-d2)

        risky_debt_value = D * np.exp(-r * T) * norm.cdf(d2) + V * norm.cdf(-d1)
        riskfree_debt_value = D * np.exp(-r * T)
        if risky_debt_value > 0 and riskfree_debt_value > 0:
            implied_spread = -(1 / T) * np.log(risky_debt_value / riskfree_debt_value) * 10000
        else:
            implied_spread = 0

        return {
            "V": V,
            "sigma_V": sigma_V,
            "d1": d1,
            "d2": d2,
            "DD": DD,
            "default_prob": default_prob * 100,
            "implied_spread_bps": max(0, implied_spread),
            "method": "simplified",
        }
    except Exception:
        return None


# =============================================================================
# BATCH COMPUTATION
# =============================================================================

def compute_merton_all(metrics_df: pd.DataFrame, constituents: List,
                       risk_free_rate: float = None) -> pd.DataFrame:
    """
    Run the Merton model for all constituents.

    Returns DataFrame with columns:
      name, ticker, sector, rating, DD, default_prob, implied_spread_bps,
      asset_value_mm, asset_vol, leverage_ratio, quality_tier, method
    """
    r = risk_free_rate if risk_free_rate is not None else RISK_FREE_RATE

    print(f"\n{'=' * 80}")
    print("  MERTON DISTANCE-TO-DEFAULT MODEL")
    print(f"{'=' * 80}")
    print(f"  Risk-free rate: {r*100:.1f}%  |  Debt maturity: {DEBT_MATURITY_T:.0f}yr  |  Recovery: {RECOVERY_RATE*100:.0f}%")
    print()

    rows = []
    for _, row in metrics_df.iterrows():
        E = row["market_cap_mm"]
        sigma_E = row["vol_252d"] / 100.0  # convert % to decimal
        D = row["total_debt_mm"]

        if E <= 0 or D <= 0:
            print(f"  [SKIP] {row['name']:<30s} | MCap=${E:,.0f}M Debt=${D:,.0f}M (invalid)")
            continue

        result = solve_merton(E, sigma_E, D, r, DEBT_MATURITY_T)
        if result is None:
            print(f"  [FAIL] {row['name']:<30s} | Solver did not converge")
            continue

        # Classify quality tier
        dd = result["DD"]
        tier = "Unknown"
        for tier_name, (lo, hi) in DD_TIERS.items():
            if lo <= dd < hi:
                tier = tier_name
                break

        rows.append({
            "name": row["name"],
            "ticker": row["ticker"],
            "sector": row["sector"],
            "rating": row["rating"],
            "DD": round(dd, 3),
            "default_prob": round(result["default_prob"], 2),
            "implied_spread_bps": round(result["implied_spread_bps"], 0),
            "asset_value_mm": round(result["V"], 0),
            "asset_vol": round(result["sigma_V"] * 100, 1),
            "leverage_ratio": round(D / E, 2) if E > 0 else np.nan,
            "quality_tier": tier,
            "method": result["method"],
        })

        print(f"  [OK]   {row['name']:<30s} | DD={dd:>+6.2f} | PD={result['default_prob']:>5.1f}% | "
              f"Spread={result['implied_spread_bps']:>6.0f}bp | Tier={tier} | {result['method']}")

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("DD", ascending=True).reset_index(drop=True)

    print(f"\n  Computed: {len(df)} names")
    return df


def compute_dd_timeseries(constituent, risk_free_rate: float = None,
                           lookback_weeks: int = DD_LOOKBACK_WEEKS) -> pd.DataFrame:
    """
    Compute weekly DD snapshots for a single constituent over the past year.
    Uses weekly closing prices and rolling 63-day vol at each snapshot point.
    """
    r = risk_free_rate if risk_free_rate is not None else RISK_FREE_RATE
    prices = constituent.prices
    if prices is None or len(prices) < 126:
        return pd.DataFrame()

    prices = prices.sort_index()
    returns = prices.pct_change().dropna()

    # Weekly snapshots
    weekly_dates = prices.resample("W-FRI").last().dropna().index
    weekly_dates = weekly_dates[-lookback_weeks:] if len(weekly_dates) > lookback_weeks else weekly_dates

    rows = []
    for dt in weekly_dates:
        mask = prices.index <= dt
        p = prices[mask]
        ret = returns[returns.index <= dt]

        if len(p) < 63 or len(ret) < 63:
            continue

        current_price = p.iloc[-1]
        vol_63d = ret.tail(63).std() * np.sqrt(252)

        # Use market cap proportional to price change from latest
        latest_mcap = constituent.market_cap
        if latest_mcap > 0 and prices.iloc[-1] > 0:
            E = latest_mcap * (current_price / prices.iloc[-1])
        else:
            continue

        D = constituent.total_debt
        if D <= 0:
            continue

        result = solve_merton(E, vol_63d, D, r, DEBT_MATURITY_T)
        if result is not None:
            rows.append({
                "date": dt,
                "DD": result["DD"],
                "default_prob": result["default_prob"],
                "implied_spread_bps": result["implied_spread_bps"],
                "price": current_price,
                "vol_63d": vol_63d * 100,
            })

    return pd.DataFrame(rows)


def compute_dd_changes(merton_df: pd.DataFrame, constituents: List,
                        weeks: int = 4) -> pd.DataFrame:
    """
    Compute recent DD change (4 weeks) for each constituent.
    Adds columns: DD_4w_ago, DD_change, DD_direction.
    """
    r = RISK_FREE_RATE
    changes = []

    for _, row in merton_df.iterrows():
        # Find matching constituent
        const = None
        for c in constituents:
            if c.name == row["name"] and c.fetch_success:
                const = c
                break
        if const is None:
            changes.append({**row.to_dict(), "DD_4w_ago": np.nan, "DD_change": np.nan, "DD_direction": "UNKNOWN"})
            continue

        ts = compute_dd_timeseries(const, r, lookback_weeks=weeks + 4)
        if len(ts) < 2:
            changes.append({**row.to_dict(), "DD_4w_ago": np.nan, "DD_change": np.nan, "DD_direction": "UNKNOWN"})
            continue

        dd_now = row["DD"]
        dd_then = ts.iloc[0]["DD"]  # earliest available
        dd_change = dd_now - dd_then

        if dd_change < DD_DETERIORATION_THRESHOLD:
            direction = "DETERIORATING"
        elif dd_change > DD_IMPROVEMENT_THRESHOLD:
            direction = "IMPROVING"
        else:
            direction = "STABLE"

        changes.append({
            **row.to_dict(),
            "DD_4w_ago": round(dd_then, 3),
            "DD_change": round(dd_change, 3),
            "DD_direction": direction,
        })

    return pd.DataFrame(changes)


def flag_deteriorating(dd_changes_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return DataFrames of deteriorating and improving names."""
    deteriorating = dd_changes_df[dd_changes_df["DD_direction"] == "DETERIORATING"].copy()
    improving = dd_changes_df[dd_changes_df["DD_direction"] == "IMPROVING"].copy()
    return deteriorating, improving


# =============================================================================
# CONSOLE OUTPUT
# =============================================================================

def print_report(merton_df: pd.DataFrame, dd_changes: pd.DataFrame,
                  deteriorating: pd.DataFrame, improving: pd.DataFrame):
    """Print full Merton model report."""
    print(f"\n{'=' * 110}")
    print("  MERTON DISTANCE-TO-DEFAULT - FULL REPORT")
    print(f"{'=' * 110}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Risk-Free: {RISK_FREE_RATE*100:.1f}% | Maturity: {DEBT_MATURITY_T:.0f}yr | Recovery: {RECOVERY_RATE*100:.0f}%")

    # Full ranking
    print(f"\n{'=' * 110}")
    print("  1. FULL DD RANKING (worst credit quality first)")
    print(f"{'=' * 110}")
    print(f"  {'Rank':>4s} {'Name':<30s} {'Sector':<15s} {'Rating':>6s} {'DD':>7s} {'PD%':>6s} "
          f"{'Spread':>8s} {'Tier':<14s} {'Method'}")
    print("  " + "-" * 106)

    for i, (_, row) in enumerate(merton_df.iterrows()):
        print(f"  {i+1:>4d} {row['name']:<30s} {row['sector']:<15s} {row['rating']:>6s} "
              f"{row['DD']:>+7.2f} {row['default_prob']:>5.1f}% "
              f"{row['implied_spread_bps']:>7.0f}bp {row['quality_tier']:<14s} {row['method']}")

    # Quality tier summary
    print(f"\n{'=' * 110}")
    print("  2. QUALITY TIER SUMMARY")
    print(f"{'=' * 110}")
    for tier_name in DD_TIERS:
        names = merton_df[merton_df["quality_tier"] == tier_name]
        if len(names) > 0:
            name_list = ", ".join(names["name"].values[:8])
            print(f"  {tier_name:<14s} ({len(names):>2d} names): {name_list}")

    # Deteriorating / Improving
    if len(dd_changes) > 0 and "DD_change" in dd_changes.columns:
        print(f"\n{'=' * 110}")
        print("  3. DD TRAJECTORY (4-week change)")
        print(f"{'=' * 110}")

        if len(deteriorating) > 0:
            print(f"\n  DETERIORATING ({len(deteriorating)} names):")
            for _, row in deteriorating.iterrows():
                chg = row.get("DD_change", np.nan)
                chg_str = f"{chg:+.2f}" if pd.notna(chg) else "N/A"
                print(f"    >>> {row['name']:<30s} DD: {row['DD']:>+6.2f} | 4w Change: {chg_str} | {row['quality_tier']}")

        if len(improving) > 0:
            print(f"\n  IMPROVING ({len(improving)} names):")
            for _, row in improving.iterrows():
                chg = row.get("DD_change", np.nan)
                chg_str = f"{chg:+.2f}" if pd.notna(chg) else "N/A"
                print(f"    <<< {row['name']:<30s} DD: {row['DD']:>+6.2f} | 4w Change: {chg_str} | {row['quality_tier']}")

    # Sector averages
    print(f"\n{'=' * 110}")
    print("  4. SECTOR AVERAGE DD")
    print(f"{'=' * 110}")
    sector_avg = merton_df.groupby("sector").agg({"DD": "mean", "default_prob": "mean", "name": "count"})
    sector_avg = sector_avg.rename(columns={"name": "count"}).sort_values("DD")

    for sector, row in sector_avg.iterrows():
        print(f"  {sector:<20s} ({int(row['count'])} names)  Avg DD: {row['DD']:>+6.2f}  Avg PD: {row['default_prob']:>5.1f}%")

    # Trading implications
    print(f"\n{'=' * 110}")
    print("  5. iTRAXX CROSSOVER IMPLICATIONS")
    print(f"{'=' * 110}")

    n_distressed = len(merton_df[merton_df["quality_tier"].isin(["Distressed", "Default_Risk"])])
    n_deteriorating = len(deteriorating) if len(deteriorating) > 0 else 0
    avg_dd = merton_df["DD"].mean()

    if n_distressed > 5 or n_deteriorating > 5:
        print("  >>> ELEVATED STRESS: Multiple names in distress/deteriorating")
        print("  >>> Consider: BUY Crossover protection, reduce single-name longs")
    elif avg_dd < 1.5:
        print("  >>> CAUTION: Average DD below 1.5 - broad credit quality concern")
        print("  >>> Consider: Reduce Crossover beta, move up in quality")
    elif avg_dd > 2.5 and n_deteriorating < 3:
        print("  >>> CONSTRUCTIVE: Strong average DD, few deteriorating names")
        print("  >>> Consider: Maintain/add Crossover longs, harvest carry")
    else:
        print("  >>> MIXED: Selective approach warranted")
        print("  >>> Consider: Avoid specific deteriorating names, maintain diversified exposure")

    if len(deteriorating) > 0:
        print(f"\n  SINGLE-NAME SHORTS TO CONSIDER:")
        for _, row in deteriorating.head(5).iterrows():
            print(f"    - BUY PROTECTION on {row['name']} (DD={row['DD']:+.2f}, {row['sector']})")

    if len(improving) > 0:
        print(f"\n  SINGLE-NAME LONGS TO CONSIDER:")
        for _, row in improving.head(5).iterrows():
            print(f"    - SELL PROTECTION on {row['name']} (DD={row['DD']:+.2f}, {row['sector']})")

    print("\n" + "=" * 110)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(merton_df: pd.DataFrame, dd_changes: pd.DataFrame,
                    constituents: List):
    """Create Merton DD dashboard visualization."""
    if len(merton_df) == 0:
        print("  No data to plot.")
        return

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "MERTON DISTANCE-TO-DEFAULT - iTRAXX CROSSOVER CONSTITUENTS",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(
        0.5, 0.955,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"r={RISK_FREE_RATE*100:.1f}% T={DEBT_MATURITY_T:.0f}yr RR={RECOVERY_RATE*100:.0f}% | {len(merton_df)} names",
        ha="center", fontsize=10, color="gray",
    )

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # --- Panel 1: DD Horizontal Bar Chart (sorted) ---
    ax1 = fig.add_subplot(gs[0, :2])
    sorted_df = merton_df.sort_values("DD", ascending=True)
    tier_colors = {
        "Safe": "#27ae60", "Adequate": "#2ecc71", "Vulnerable": "#f39c12",
        "Distressed": "#e74c3c", "Default_Risk": "#c0392b", "Unknown": "#95a5a6",
    }
    colors = [tier_colors.get(t, "#95a5a6") for t in sorted_df["quality_tier"]]

    ax1.barh(range(len(sorted_df)), sorted_df["DD"].values, color=colors, edgecolor="white", linewidth=0.3)
    ax1.set_yticks(range(len(sorted_df)))
    ax1.set_yticklabels([f"{n[:18]} ({r})" for n, r in zip(sorted_df["name"], sorted_df["rating"])], fontsize=6)
    ax1.axvline(0.5, color="#c0392b", linewidth=1.0, linestyle="--", label="Default Risk")
    ax1.axvline(1.0, color="#e74c3c", linewidth=0.8, linestyle="--", label="Distressed")
    ax1.axvline(2.0, color="#f39c12", linewidth=0.8, linestyle="--", label="Vulnerable")
    ax1.axvline(3.0, color="#2ecc71", linewidth=0.8, linestyle="--", label="Safe")
    ax1.set_title("Distance to Default - All Constituents", fontweight="bold")
    ax1.set_xlabel("DD (higher = safer)")
    ax1.legend(fontsize=7, loc="lower right")
    ax1.grid(True, alpha=0.3, axis="x")

    # --- Panel 2: Summary Box ---
    ax_sum = fig.add_subplot(gs[0, 2])
    ax_sum.set_xlim(0, 1)
    ax_sum.set_ylim(0, 1)
    ax_sum.axis("off")

    n_safe = len(merton_df[merton_df["quality_tier"] == "Safe"])
    n_adequate = len(merton_df[merton_df["quality_tier"] == "Adequate"])
    n_vulnerable = len(merton_df[merton_df["quality_tier"] == "Vulnerable"])
    n_distressed = len(merton_df[merton_df["quality_tier"].isin(["Distressed", "Default_Risk"])])
    avg_dd = merton_df["DD"].mean()
    med_dd = merton_df["DD"].median()

    box = FancyBboxPatch((0.05, 0.05), 0.9, 0.9, boxstyle="round,pad=0.05",
                          facecolor="#2c3e50", alpha=0.15, edgecolor="#2c3e50", linewidth=2)
    ax_sum.add_patch(box)
    ax_sum.text(0.5, 0.90, "DD SUMMARY", ha="center", fontsize=12, fontweight="bold")
    ax_sum.text(0.5, 0.78, f"Mean DD: {avg_dd:.2f}  |  Median: {med_dd:.2f}", ha="center", fontsize=10)

    y = 0.65
    for label, count, color in [("Safe", n_safe, "#27ae60"), ("Adequate", n_adequate, "#2ecc71"),
                                  ("Vulnerable", n_vulnerable, "#f39c12"), ("Distressed+Default", n_distressed, "#e74c3c")]:
        ax_sum.text(0.2, y, f"{label}:", fontsize=9, va="center")
        ax_sum.text(0.7, y, f"{count}", fontsize=12, fontweight="bold", va="center", color=color)
        y -= 0.10

    # DD trajectory summary
    if "DD_direction" in dd_changes.columns:
        n_det = len(dd_changes[dd_changes["DD_direction"] == "DETERIORATING"])
        n_imp = len(dd_changes[dd_changes["DD_direction"] == "IMPROVING"])
        ax_sum.text(0.5, 0.18, f"4-Week Trajectory:", ha="center", fontsize=9)
        ax_sum.text(0.5, 0.08, f"Deteriorating: {n_det}  |  Improving: {n_imp}",
                    ha="center", fontsize=10, fontweight="bold",
                    color="#e74c3c" if n_det > n_imp else "#2ecc71")

    # --- Panel 3: DD vs Implied Spread Scatter ---
    ax2 = fig.add_subplot(gs[1, 0])
    if len(merton_df) > 0:
        colors_scatter = [tier_colors.get(t, "#95a5a6") for t in merton_df["quality_tier"]]
        ax2.scatter(merton_df["DD"], merton_df["implied_spread_bps"], c=colors_scatter,
                    s=50, alpha=0.7, edgecolor="white", linewidth=0.5)
        # Label worst names
        worst = merton_df.nsmallest(5, "DD")
        for _, row in worst.iterrows():
            ax2.annotate(row["name"][:12], (row["DD"], row["implied_spread_bps"]),
                         fontsize=6, alpha=0.8, ha="left")
        ax2.set_xlabel("Distance to Default")
        ax2.set_ylabel("Implied Spread (bps)")
        ax2.set_title("DD vs Implied Spread", fontweight="bold", fontsize=10)
        ax2.grid(True, alpha=0.3)

    # --- Panel 4: Sector Average DD ---
    ax3 = fig.add_subplot(gs[1, 1])
    sector_dd = merton_df.groupby("sector")["DD"].mean().sort_values()
    if len(sector_dd) > 0:
        s_colors = ["#e74c3c" if d < 1.5 else "#f39c12" if d < 2.5 else "#2ecc71" for d in sector_dd.values]
        ax3.barh(range(len(sector_dd)), sector_dd.values, color=s_colors, edgecolor="white")
        ax3.set_yticks(range(len(sector_dd)))
        ax3.set_yticklabels(sector_dd.index, fontsize=7)
        ax3.axvline(1.5, color="#e74c3c", linewidth=0.8, linestyle="--")
        ax3.axvline(2.5, color="#f39c12", linewidth=0.8, linestyle="--")
        ax3.set_title("Sector Average DD", fontweight="bold", fontsize=10)
        ax3.set_xlabel("Avg Distance to Default")
        ax3.grid(True, alpha=0.3, axis="x")

    # --- Panel 5: Default Probability Distribution ---
    ax4 = fig.add_subplot(gs[1, 2])
    if len(merton_df) > 0:
        pd_vals = merton_df["default_prob"].clip(0, 50)
        ax4.hist(pd_vals, bins=20, color="#3498db", edgecolor="white", alpha=0.8)
        ax4.axvline(pd_vals.median(), color="red", linewidth=1.5, linestyle="--",
                    label=f"Median: {pd_vals.median():.1f}%")
        ax4.set_xlabel("Implied Default Probability (%)")
        ax4.set_ylabel("Count")
        ax4.set_title("Default Probability Distribution", fontweight="bold", fontsize=10)
        ax4.legend(fontsize=8)
        ax4.grid(True, alpha=0.3)

    # --- Panel 6: DD Change Arrows (top movers) ---
    ax5 = fig.add_subplot(gs[2, :2])
    if "DD_change" in dd_changes.columns:
        valid_changes = dd_changes.dropna(subset=["DD_change"]).copy()
        if len(valid_changes) > 0:
            valid_changes = valid_changes.sort_values("DD_change")
            top_n = min(25, len(valid_changes))
            show = pd.concat([valid_changes.head(top_n // 2), valid_changes.tail(top_n // 2)])
            show = show.drop_duplicates(subset=["name"]).sort_values("DD_change")

            chg_colors = ["#e74c3c" if c < -0.2 else "#2ecc71" if c > 0.2 else "#95a5a6"
                          for c in show["DD_change"]]
            ax5.barh(range(len(show)), show["DD_change"].values, color=chg_colors, edgecolor="white", linewidth=0.3)
            ax5.set_yticks(range(len(show)))
            ax5.set_yticklabels([f"{n[:20]}" for n in show["name"]], fontsize=6)
            ax5.axvline(0, color="black", linewidth=0.8)
            ax5.axvline(DD_DETERIORATION_THRESHOLD, color="#e74c3c", linewidth=0.7, linestyle="--")
            ax5.axvline(DD_IMPROVEMENT_THRESHOLD, color="#2ecc71", linewidth=0.7, linestyle="--")
            ax5.set_title("4-Week DD Change (negative = deteriorating)", fontweight="bold")
            ax5.set_xlabel("DD Change")
            ax5.grid(True, alpha=0.3, axis="x")
    else:
        ax5.text(0.5, 0.5, "DD change data not available", ha="center", va="center", transform=ax5.transAxes)
        ax5.set_title("4-Week DD Change", fontweight="bold")

    # --- Panel 7: Quality Tier Breakdown ---
    ax6 = fig.add_subplot(gs[2, 2])
    tier_order = ["Safe", "Adequate", "Vulnerable", "Distressed", "Default_Risk"]
    tier_counts = merton_df["quality_tier"].value_counts()
    tier_sorted = pd.Series(index=tier_order, dtype=int)
    for t in tier_order:
        tier_sorted[t] = tier_counts.get(t, 0)
    tier_sorted = tier_sorted[tier_sorted > 0]

    if len(tier_sorted) > 0:
        t_colors = [tier_colors.get(t, "#95a5a6") for t in tier_sorted.index]
        wedges, texts, autotexts = ax6.pie(
            tier_sorted.values, labels=tier_sorted.index, colors=t_colors,
            autopct="%1.0f%%", startangle=90, textprops={"fontsize": 8},
        )
        for t in autotexts:
            t.set_fontsize(8)
            t.set_fontweight("bold")
        ax6.set_title("Quality Tier Distribution", fontweight="bold", fontsize=10)

    plt.savefig("merton_single_name_dashboard.png", dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: merton_single_name_dashboard.png")
    plt.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 70)
    print("  MERTON SINGLE-NAME DISTANCE-TO-DEFAULT MODEL")
    print("  iTraxx Crossover Constituents")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Risk-Free: {RISK_FREE_RATE*100:.1f}% | Maturity: {DEBT_MATURITY_T:.0f}yr | Recovery: {RECOVERY_RATE*100:.0f}%")
    print()

    # 1. Get constituent data
    print("  Step 1: Fetching constituent data...")
    constituents = xoc.fetch_all_constituents(use_cache=True)
    success = [c for c in constituents if c.fetch_success]

    print(f"\n  Step 2: Computing equity metrics...")
    metrics_df = xoc.compute_equity_metrics(success)

    # 2. Run Merton model
    print(f"\n  Step 3: Running Merton model...")
    merton_df = compute_merton_all(metrics_df, success)

    # 3. Compute DD changes
    print(f"\n  Step 4: Computing DD trajectory (4-week changes)...")
    dd_changes = compute_dd_changes(merton_df, success)
    deteriorating, improving = flag_deteriorating(dd_changes)

    # 4. Report
    print_report(merton_df, dd_changes, deteriorating, improving)

    # 5. Dashboard
    print("\n  Generating dashboard chart...")
    plot_dashboard(merton_df, dd_changes, success)

    # 6. Save CSVs
    if len(merton_df) > 0:
        merton_df.to_csv("merton_dd_results.csv", index=False)
        print(f"  Results saved: merton_dd_results.csv")
    if len(dd_changes) > 0:
        dd_changes.to_csv("merton_dd_changes.csv", index=False)
        print(f"  Changes saved: merton_dd_changes.csv")

    print("\n  DONE.\n")


if __name__ == "__main__":
    main()

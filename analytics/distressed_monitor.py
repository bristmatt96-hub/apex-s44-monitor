#!/usr/bin/env python3
"""
Module 13: Distressed / LME Monitor
====================================
Computes liquidity stress scores, cash burn timelines, and tiered watch lists
for iTraxx Crossover constituents. Identifies names at risk of distress,
liquidity crises, or potential liability management exercises (LMEs).

Based on:
  - Ch.19 "Distressed Credits, Bankruptcy, and Distressed Exchanges"
  - Ch.8 "Credit Ratios" (liquidity metrics)
  - Ch.26 "Credit Snapshot" (cash flow adequacy)

Dependencies:
  - crossover_constituents.py (ConstituentData with fundamentals)
  - fundamental_credit_analysis.py (credit ratios)
  - merton_single_name.py (Merton Distance-to-Default)

Usage:
  python distressed_monitor.py

Author: Built with Claude for macro credit trading
"""

import os
import sys
import warnings
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

try:
    from analytics.crossover_constituents import (
        ConstituentData, CONSTITUENTS, fetch_all_constituents,
    )
    from analytics.fundamental_credit_analysis import compute_all_ratios, _safe_latest
except ImportError as e:
    print(f"ERROR: Missing dependency: {e}")
    sys.exit(1)

try:
    from analytics.merton_single_name import compute_merton_all
    HAS_MERTON = True
except ImportError:
    print("WARNING: merton_single_name.py not found - Merton DD component will be zero")
    HAS_MERTON = False

warnings.filterwarnings("ignore")


# =============================================================================
# CONFIGURATION
# =============================================================================

# Tier thresholds for watch list (higher = more distressed)
TIER_THRESHOLDS = {
    "IMMINENT":  80,   # Tier 1: immediate distress risk
    "ELEVATED":  60,   # Tier 2: heightened monitoring
    "MONITOR":   40,   # Tier 3: early warning
}

# Colors for tiers
TIER_COLORS = {
    "IMMINENT":  "#c0392b",
    "ELEVATED":  "#e74c3c",
    "MONITOR":   "#f39c12",
    "SAFE":      "#2ecc71",
}


# =============================================================================
# LIQUIDITY SCORE COMPUTATION
# =============================================================================

def compute_liquidity_score(c: ConstituentData, ratios_row: dict,
                            merton_row: dict = None) -> dict:
    """
    Compute a 0-100 liquidity stress score for a single constituent.
    Higher = more distressed.

    Components:
      Cash/Current Liabilities (30 pts)
      FCF/Debt generation      (25 pts)
      Interest coverage        (20 pts)
      Leverage extremes        (15 pts)
      Merton DD proximity      (10 pts)
    """
    result = {
        "name": c.name,
        "ticker": c.ticker,
        "sector": c.sector,
        "rating": c.rating,
        "country": c.country,
    }

    total_score = 0

    # --- Component 1: Cash / Current Liabilities (30 pts) ---
    cash = _safe_latest(c.cash) if c.cash is not None else np.nan
    cl = _safe_latest(c.current_liabilities) if c.current_liabilities is not None else np.nan
    current_ratio = c.current_ratio

    # Use current ratio from .info if available, otherwise compute
    if current_ratio > 0:
        cr = current_ratio
    elif not np.isnan(cash) and not np.isnan(cl) and cl > 0:
        cr = cash / cl
    else:
        cr = np.nan

    if not np.isnan(cr):
        if cr < 0.3:
            c1_score = 30
        elif cr < 0.5:
            c1_score = 25
        elif cr < 0.8:
            c1_score = 15
        elif cr < 1.0:
            c1_score = 8
        else:
            c1_score = 0
    else:
        c1_score = 10  # no data = moderate concern

    result["cash_cl_ratio"] = round(cr, 2) if not np.isnan(cr) else np.nan
    result["score_cash_cl"] = c1_score
    total_score += c1_score

    # --- Component 2: FCF/Debt generation (25 pts) ---
    fcf_debt = ratios_row.get("fcf_debt_pct", np.nan)
    if not np.isnan(fcf_debt):
        if fcf_debt < -5:
            c2_score = 25
        elif fcf_debt < 0:
            c2_score = 20
        elif fcf_debt < 5:
            c2_score = 10
        else:
            c2_score = 0
    else:
        c2_score = 10

    result["fcf_debt_pct"] = round(fcf_debt, 1) if not np.isnan(fcf_debt) else np.nan
    result["score_fcf_debt"] = c2_score
    total_score += c2_score

    # --- Component 3: Interest coverage (20 pts) ---
    coverage = ratios_row.get("interest_coverage", np.nan)
    if not np.isnan(coverage):
        if coverage < 1.5:
            c3_score = 20
        elif coverage < 2.5:
            c3_score = 15
        elif coverage < 3.5:
            c3_score = 8
        else:
            c3_score = 0
    else:
        c3_score = 8

    result["interest_coverage"] = round(coverage, 1) if not np.isnan(coverage) else np.nan
    result["score_coverage"] = c3_score
    total_score += c3_score

    # --- Component 4: Leverage extremes (15 pts) ---
    leverage = ratios_row.get("gross_leverage", np.nan)
    if not np.isnan(leverage):
        if leverage > 8:
            c4_score = 15
        elif leverage > 6:
            c4_score = 10
        elif leverage > 4:
            c4_score = 5
        else:
            c4_score = 0
    else:
        c4_score = 5

    result["gross_leverage"] = round(leverage, 1) if not np.isnan(leverage) else np.nan
    result["score_leverage"] = c4_score
    total_score += c4_score

    # --- Component 5: Merton DD proximity (10 pts) ---
    dd = np.nan
    if merton_row is not None:
        dd = merton_row.get("DD", merton_row.get("dd", np.nan))

    if not np.isnan(dd):
        if dd < 0.5:
            c5_score = 10
        elif dd < 1.0:
            c5_score = 7
        elif dd < 1.5:
            c5_score = 4
        else:
            c5_score = 0
    else:
        c5_score = 3  # no Merton data = small concern

    result["merton_dd"] = round(dd, 2) if not np.isnan(dd) else np.nan
    result["score_merton"] = c5_score
    total_score += c5_score

    result["total_score"] = total_score

    # Tier assignment
    if total_score >= TIER_THRESHOLDS["IMMINENT"]:
        result["tier"] = "IMMINENT"
    elif total_score >= TIER_THRESHOLDS["ELEVATED"]:
        result["tier"] = "ELEVATED"
    elif total_score >= TIER_THRESHOLDS["MONITOR"]:
        result["tier"] = "MONITOR"
    else:
        result["tier"] = "SAFE"

    return result


def estimate_months_of_liquidity(c: ConstituentData, ratios_row: dict) -> float:
    """
    Estimate months of liquidity remaining if the company is burning cash.

    If EBITDA < (Interest + Capex), company is net cash-burning.
    Monthly burn rate = (Interest + Capex - EBITDA) / 12
    Months remaining = Cash / monthly burn rate

    Returns months remaining, or np.inf if not burning cash, or np.nan if no data.
    """
    ebitda = ratios_row.get("ebitda_mm", np.nan)
    interest = ratios_row.get("interest_expense_mm", np.nan)
    capex = ratios_row.get("capex_mm", np.nan)
    cash = ratios_row.get("cash_mm", np.nan)

    if np.isnan(ebitda) or np.isnan(interest) or np.isnan(cash):
        return np.nan

    # Use capex = 0 if not available
    cap = capex if not np.isnan(capex) else 0

    # Is the company burning cash?
    obligations = interest + cap
    if ebitda >= obligations:
        return np.inf  # Not burning cash

    # Monthly burn rate
    annual_burn = obligations - ebitda
    monthly_burn = annual_burn / 12.0

    if monthly_burn <= 0:
        return np.inf

    months = cash / monthly_burn
    return max(0, months)


# =============================================================================
# UNIVERSE-LEVEL COMPUTATION
# =============================================================================

def compute_distressed_scores(constituents: List[ConstituentData],
                               ratios_df: pd.DataFrame,
                               merton_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Compute liquidity stress scores for all constituents.
    Returns DataFrame sorted by total_score (highest distress first).
    """
    # Build lookup dicts from ratios_df and merton_df
    ratios_lookup = {}
    if len(ratios_df) > 0:
        for _, row in ratios_df.iterrows():
            ratios_lookup[row["name"]] = row.to_dict()

    merton_lookup = {}
    if merton_df is not None and len(merton_df) > 0:
        for _, row in merton_df.iterrows():
            merton_lookup[row["name"]] = row.to_dict()

    rows = []
    for c in constituents:
        if not c.fetch_success or not c.has_fundamentals:
            continue

        ratios_row = ratios_lookup.get(c.name, {})
        merton_row = merton_lookup.get(c.name, None)

        score = compute_liquidity_score(c, ratios_row, merton_row)

        # Add months of liquidity
        months = estimate_months_of_liquidity(c, ratios_row)
        score["months_liquidity"] = round(months, 1) if not np.isinf(months) and not np.isnan(months) else months

        # Add raw financial context
        score["total_debt_mm"] = c.total_debt
        score["cash_mm"] = ratios_row.get("cash_mm", np.nan)
        score["ebitda_mm"] = ratios_row.get("ebitda_mm", np.nan)
        score["fcf_mm"] = ratios_row.get("fcf_mm", np.nan)
        score["market_cap_mm"] = c.market_cap
        score["enterprise_value_mm"] = c.enterprise_value

        rows.append(score)

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("total_score", ascending=False)
    return df


def generate_watch_list(stress_df: pd.DataFrame) -> dict:
    """
    Generate tiered watch list from stress scores.
    Returns dict with keys: 'IMMINENT', 'ELEVATED', 'MONITOR', summary stats.
    """
    result = {
        "IMMINENT": stress_df[stress_df["tier"] == "IMMINENT"],
        "ELEVATED": stress_df[stress_df["tier"] == "ELEVATED"],
        "MONITOR":  stress_df[stress_df["tier"] == "MONITOR"],
        "SAFE":     stress_df[stress_df["tier"] == "SAFE"],
    }
    result["n_imminent"] = len(result["IMMINENT"])
    result["n_elevated"] = len(result["ELEVATED"])
    result["n_monitor"] = len(result["MONITOR"])
    result["n_safe"] = len(result["SAFE"])
    result["avg_score"] = stress_df["total_score"].mean() if len(stress_df) > 0 else 0
    return result


# =============================================================================
# CONSOLE REPORT
# =============================================================================

def print_report(stress_df: pd.DataFrame, watch: dict):
    """Print comprehensive distressed monitoring report."""
    if len(stress_df) == 0:
        print("  No data available.")
        return

    print("\n" + "=" * 120)
    print("  DISTRESSED / LME MONITOR  - iTRAXX CROSSOVER UNIVERSE")
    print("=" * 120)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Names scored: {len(stress_df)}")
    print(f"  Tier 1 IMMINENT: {watch['n_imminent']}  |  "
          f"Tier 2 ELEVATED: {watch['n_elevated']}  |  "
          f"Tier 3 MONITOR: {watch['n_monitor']}  |  "
          f"SAFE: {watch['n_safe']}")
    print(f"  Average stress score: {watch['avg_score']:.1f} / 100")
    print()

    # --- Section 1: Full Liquidity Ranking ---
    print(f"{'=' * 120}")
    print("  1. FULL LIQUIDITY STRESS RANKING (highest distress first)")
    print(f"{'=' * 120}")
    print(f"  {'Name':<28s} {'Sector':<15s} {'Rtg':>4s} {'Score':>6s} {'Tier':<10s} "
          f"{'Cash/CL':>8s} {'Coverage':>9s} {'Leverage':>9s} {'FCF/Debt':>9s} {'MertonDD':>9s}")
    print("  " + "-" * 116)

    for _, row in stress_df.iterrows():
        scr = f"{row['total_score']}"
        ccl = f"{row['cash_cl_ratio']:.2f}" if pd.notna(row['cash_cl_ratio']) else "N/A"
        cov = f"{row['interest_coverage']:.1f}x" if pd.notna(row['interest_coverage']) else "N/A"
        lev = f"{row['gross_leverage']:.1f}x" if pd.notna(row['gross_leverage']) else "N/A"
        fcf = f"{row['fcf_debt_pct']:+.1f}%" if pd.notna(row['fcf_debt_pct']) else "N/A"
        dd = f"{row['merton_dd']:.2f}" if pd.notna(row['merton_dd']) else "N/A"
        tier = row['tier']

        print(f"  {row['name']:<28s} {row['sector']:<15s} {row['rating']:>4s} {scr:>6s} {tier:<10s} "
              f"{ccl:>8s} {cov:>9s} {lev:>9s} {fcf:>9s} {dd:>9s}")

    # --- Section 2: Tier 1 IMMINENT Detail ---
    imminent = watch["IMMINENT"]
    print(f"\n{'=' * 120}")
    print(f"  2. TIER 1  - IMMINENT DISTRESS RISK ({len(imminent)} names)")
    print(f"{'=' * 120}")
    if len(imminent) > 0:
        for _, row in imminent.iterrows():
            _print_distress_detail(row)
    else:
        print("  No names at imminent risk.")

    # --- Section 3: Tier 2 ELEVATED ---
    elevated = watch["ELEVATED"]
    print(f"\n{'=' * 120}")
    print(f"  3. TIER 2  - ELEVATED RISK ({len(elevated)} names)")
    print(f"{'=' * 120}")
    if len(elevated) > 0:
        for _, row in elevated.iterrows():
            scr = f"{row['total_score']}"
            months = row.get('months_liquidity', np.nan)
            months_str = f"{months:.0f} months" if not np.isnan(months) and not np.isinf(months) else "Not burning"
            lev = f"{row['gross_leverage']:.1f}x" if pd.notna(row['gross_leverage']) else "N/A"
            cov = f"{row['interest_coverage']:.1f}x" if pd.notna(row['interest_coverage']) else "N/A"
            print(f"  {row['name']:<28s} Score={scr}  Lev={lev}  Cov={cov}  Liquidity={months_str}")
    else:
        print("  No names at elevated risk.")

    # --- Section 4: Tier 3 MONITOR ---
    monitor = watch["MONITOR"]
    print(f"\n{'=' * 120}")
    print(f"  4. TIER 3  - EARLY WARNING ({len(monitor)} names)")
    print(f"{'=' * 120}")
    if len(monitor) > 0:
        for _, row in monitor.iterrows():
            scr = f"{row['total_score']}"
            lev = f"{row['gross_leverage']:.1f}x" if pd.notna(row['gross_leverage']) else "N/A"
            print(f"  {row['name']:<28s} Score={scr}  Leverage={lev}  Rating={row['rating']}")
    else:
        print("  No names on early warning.")

    # --- Section 5: Cash Burn Timelines ---
    burn_df = stress_df[
        stress_df["months_liquidity"].notna() &
        ~stress_df["months_liquidity"].apply(lambda x: np.isinf(x) if not np.isnan(x) else True)
    ].sort_values("months_liquidity", ascending=True)

    print(f"\n{'=' * 120}")
    print(f"  5. CASH BURN TIMELINES ({len(burn_df)} names burning cash)")
    print(f"{'=' * 120}")
    if len(burn_df) > 0:
        for _, row in burn_df.iterrows():
            months = row['months_liquidity']
            cash = f"${row['cash_mm']:,.0f}M" if pd.notna(row['cash_mm']) else "N/A"
            severity = "CRITICAL" if months < 12 else "CONCERN" if months < 24 else "WATCH"
            print(f"  [{severity:8s}] {row['name']:<28s} {months:>5.1f} months  Cash={cash}  Score={row['total_score']}")
    else:
        print("  No names currently burning cash (all EBITDA > Interest + Capex).")

    # --- Section 6: Sector Distress Map ---
    print(f"\n{'=' * 120}")
    print("  6. SECTOR DISTRESS MAP")
    print(f"{'=' * 120}")
    sector_agg = stress_df.groupby("sector").agg({
        "name": "count",
        "total_score": "mean",
        "gross_leverage": "mean",
        "interest_coverage": "mean",
    }).rename(columns={"name": "count"}).sort_values("total_score", ascending=False)

    print(f"  {'Sector':<20s} {'Count':>5s} {'Avg Score':>10s} {'Avg Lev':>8s} {'Avg Cov':>8s}")
    print("  " + "-" * 55)
    for sector, row in sector_agg.iterrows():
        lev = f"{row['gross_leverage']:.1f}x" if pd.notna(row['gross_leverage']) else "N/A"
        cov = f"{row['interest_coverage']:.1f}x" if pd.notna(row['interest_coverage']) else "N/A"
        print(f"  {sector:<20s} {int(row['count']):>5d} {row['total_score']:>10.1f} {lev:>8s} {cov:>8s}")

    print("\n" + "=" * 120)


def _print_distress_detail(row):
    """Print detailed breakdown for a single distressed name."""
    print(f"\n  {'=' * 80}")
    print(f"  {row['name']} ({row['ticker']})  - {row['sector']} | {row['rating']} | SCORE: {row['total_score']}/100")
    print(f"  {'=' * 80}")

    # Score breakdown
    print(f"  Score Breakdown:")
    print(f"    Cash/CL:      {row['score_cash_cl']:>3d}/30  "
          f"(ratio: {row['cash_cl_ratio']:.2f})" if pd.notna(row['cash_cl_ratio']) else
          f"    Cash/CL:      {row['score_cash_cl']:>3d}/30  (ratio: N/A)")
    print(f"    FCF/Debt:     {row['score_fcf_debt']:>3d}/25  "
          f"({row['fcf_debt_pct']:+.1f}%)" if pd.notna(row['fcf_debt_pct']) else
          f"    FCF/Debt:     {row['score_fcf_debt']:>3d}/25  (N/A)")
    print(f"    Coverage:     {row['score_coverage']:>3d}/20  "
          f"({row['interest_coverage']:.1f}x)" if pd.notna(row['interest_coverage']) else
          f"    Coverage:     {row['score_coverage']:>3d}/20  (N/A)")
    print(f"    Leverage:     {row['score_leverage']:>3d}/15  "
          f"({row['gross_leverage']:.1f}x)" if pd.notna(row['gross_leverage']) else
          f"    Leverage:     {row['score_leverage']:>3d}/15  (N/A)")
    print(f"    Merton DD:    {row['score_merton']:>3d}/10  "
          f"(DD={row['merton_dd']:.2f})" if pd.notna(row['merton_dd']) else
          f"    Merton DD:    {row['score_merton']:>3d}/10  (N/A)")

    # Financials
    debt = f"${row['total_debt_mm']:,.0f}M" if pd.notna(row['total_debt_mm']) else "N/A"
    cash = f"${row['cash_mm']:,.0f}M" if pd.notna(row['cash_mm']) else "N/A"
    ebitda = f"${row['ebitda_mm']:,.0f}M" if pd.notna(row['ebitda_mm']) else "N/A"
    fcf = f"${row['fcf_mm']:,.0f}M" if pd.notna(row['fcf_mm']) else "N/A"
    mcap = f"${row['market_cap_mm']:,.0f}M" if pd.notna(row['market_cap_mm']) else "N/A"
    print(f"  Financials:  Debt={debt}  Cash={cash}  EBITDA={ebitda}  FCF={fcf}  MCap={mcap}")

    # Months of liquidity
    months = row.get('months_liquidity', np.nan)
    if not np.isnan(months):
        if np.isinf(months):
            print(f"  Cash Burn:   Not currently burning cash")
        else:
            print(f"  Cash Burn:   ~{months:.0f} months of liquidity remaining")
    else:
        print(f"  Cash Burn:   Insufficient data")


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(stress_df: pd.DataFrame, watch: dict):
    """Create 24x18 distressed monitor dashboard (6 panels)."""
    if len(stress_df) == 0:
        print("  No data to plot.")
        return

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "DISTRESSED / LME MONITOR  - iTRAXX CROSSOVER UNIVERSE",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(
        0.5, 0.955,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(stress_df)} names scored",
        ha="center", fontsize=10, color="gray",
    )

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # ---- Panel 1: Liquidity Score Distribution (horizontal bars by tier) ----
    ax1 = fig.add_subplot(gs[0, :2])
    sorted_df = stress_df.sort_values("total_score", ascending=True)
    colors = [TIER_COLORS.get(t, "#95a5a6") for t in sorted_df["tier"]]

    ax1.barh(range(len(sorted_df)), sorted_df["total_score"].values, color=colors,
             edgecolor="white", linewidth=0.3)
    ax1.set_yticks(range(len(sorted_df)))
    ax1.set_yticklabels([n[:22] for n in sorted_df["name"]], fontsize=5.5)
    ax1.axvline(TIER_THRESHOLDS["MONITOR"], color="#f39c12", linewidth=1, linestyle="--",
                label=f"Monitor ({TIER_THRESHOLDS['MONITOR']})")
    ax1.axvline(TIER_THRESHOLDS["ELEVATED"], color="#e74c3c", linewidth=1, linestyle="--",
                label=f"Elevated ({TIER_THRESHOLDS['ELEVATED']})")
    ax1.axvline(TIER_THRESHOLDS["IMMINENT"], color="#c0392b", linewidth=1, linestyle="--",
                label=f"Imminent ({TIER_THRESHOLDS['IMMINENT']})")
    ax1.set_title("Liquidity Stress Score (0-100)", fontweight="bold")
    ax1.set_xlabel("Score (higher = more distressed)")
    ax1.legend(fontsize=7, loc="lower right")
    ax1.grid(True, alpha=0.3, axis="x")

    # ---- Panel 2: Summary Box ----
    ax_sum = fig.add_subplot(gs[0, 2])
    ax_sum.set_xlim(0, 1)
    ax_sum.set_ylim(0, 1)
    ax_sum.axis("off")

    box = FancyBboxPatch((0.05, 0.05), 0.9, 0.9, boxstyle="round,pad=0.05",
                          facecolor="#2c3e50", alpha=0.15, edgecolor="#2c3e50", linewidth=2)
    ax_sum.add_patch(box)
    ax_sum.text(0.5, 0.90, "DISTRESS SUMMARY", ha="center", fontsize=12, fontweight="bold")
    ax_sum.text(0.5, 0.76, f"Names Scored: {len(stress_df)}", ha="center", fontsize=10)

    imm_color = "#c0392b" if watch['n_imminent'] > 0 else "#2ecc71"
    ax_sum.text(0.5, 0.62, f"IMMINENT: {watch['n_imminent']}", ha="center", fontsize=13,
                fontweight="bold", color=imm_color)
    ax_sum.text(0.5, 0.50, f"ELEVATED: {watch['n_elevated']}", ha="center", fontsize=11,
                color="#e74c3c" if watch['n_elevated'] > 3 else "#f39c12")
    ax_sum.text(0.5, 0.38, f"MONITOR: {watch['n_monitor']}", ha="center", fontsize=10,
                color="#f39c12")
    ax_sum.text(0.5, 0.26, f"SAFE: {watch['n_safe']}", ha="center", fontsize=10, color="#2ecc71")

    avg = watch['avg_score']
    avg_color = "#c0392b" if avg > 50 else "#e74c3c" if avg > 35 else "#f39c12" if avg > 25 else "#2ecc71"
    ax_sum.text(0.5, 0.12, f"Avg Score: {avg:.0f}/100", ha="center", fontsize=11, color=avg_color)

    # ---- Panel 3: Cash Burn Timeline (months remaining) ----
    ax3 = fig.add_subplot(gs[1, 0])
    burn_df = stress_df[
        stress_df["months_liquidity"].notna() &
        stress_df["months_liquidity"].apply(lambda x: not np.isinf(x) if not np.isnan(x) else False)
    ].nsmallest(15, "months_liquidity")

    if len(burn_df) > 0:
        burn_colors = []
        for m in burn_df["months_liquidity"]:
            if m < 12:
                burn_colors.append("#c0392b")
            elif m < 24:
                burn_colors.append("#e74c3c")
            elif m < 36:
                burn_colors.append("#f39c12")
            else:
                burn_colors.append("#f1c40f")

        ax3.barh(range(len(burn_df)), burn_df["months_liquidity"].values, color=burn_colors,
                 edgecolor="white", linewidth=0.5)
        ax3.set_yticks(range(len(burn_df)))
        ax3.set_yticklabels([n[:20] for n in burn_df["name"]], fontsize=7)
        ax3.axvline(12, color="red", linewidth=1, linestyle="--", label="12 months")
        ax3.axvline(24, color="orange", linewidth=1, linestyle="--", label="24 months")
        ax3.set_title("Cash Burn Timeline (months remaining)", fontweight="bold", fontsize=10)
        ax3.set_xlabel("Months")
        ax3.legend(fontsize=7)
        ax3.grid(True, alpha=0.3, axis="x")
    else:
        ax3.text(0.5, 0.5, "No names burning cash", ha="center", va="center", fontsize=11)
        ax3.set_title("Cash Burn Timeline", fontweight="bold", fontsize=10)

    # ---- Panel 4: Score Distribution Histogram ----
    ax4 = fig.add_subplot(gs[1, 1])
    bins = np.arange(0, 105, 5)
    n_vals, bin_edges, patches = ax4.hist(stress_df["total_score"], bins=bins,
                                           edgecolor="white", linewidth=0.5, color="#3498db")
    # Color bins by tier
    for patch, left_edge in zip(patches, bin_edges[:-1]):
        if left_edge >= TIER_THRESHOLDS["IMMINENT"]:
            patch.set_facecolor("#c0392b")
        elif left_edge >= TIER_THRESHOLDS["ELEVATED"]:
            patch.set_facecolor("#e74c3c")
        elif left_edge >= TIER_THRESHOLDS["MONITOR"]:
            patch.set_facecolor("#f39c12")
        else:
            patch.set_facecolor("#2ecc71")

    ax4.axvline(TIER_THRESHOLDS["MONITOR"], color="#f39c12", linewidth=1.5, linestyle="--")
    ax4.axvline(TIER_THRESHOLDS["ELEVATED"], color="#e74c3c", linewidth=1.5, linestyle="--")
    ax4.axvline(TIER_THRESHOLDS["IMMINENT"], color="#c0392b", linewidth=1.5, linestyle="--")
    ax4.set_title("Score Distribution", fontweight="bold", fontsize=10)
    ax4.set_xlabel("Stress Score")
    ax4.set_ylabel("Count")
    ax4.grid(True, alpha=0.3, axis="y")

    # ---- Panel 5: Liquidity Ratio vs Merton DD Scatter ----
    ax5 = fig.add_subplot(gs[1, 2])
    scatter_df = stress_df.dropna(subset=["cash_cl_ratio", "merton_dd"])
    if len(scatter_df) > 0:
        scatter_colors = [TIER_COLORS.get(t, "#95a5a6") for t in scatter_df["tier"]]
        ax5.scatter(scatter_df["cash_cl_ratio"], scatter_df["merton_dd"],
                   c=scatter_colors, s=60, alpha=0.7, edgecolor="white", linewidth=0.5)

        # Label distressed names
        for _, row in scatter_df.iterrows():
            if row["tier"] in ("IMMINENT", "ELEVATED"):
                ax5.annotate(row["name"][:12], (row["cash_cl_ratio"], row["merton_dd"]),
                           fontsize=6, alpha=0.8, xytext=(3, 3), textcoords="offset points")

        ax5.axhline(1.0, color="red", linewidth=0.8, linestyle="--", alpha=0.7)
        ax5.axvline(1.0, color="orange", linewidth=0.8, linestyle="--", alpha=0.7)
        ax5.set_xlabel("Cash / Current Liabilities")
        ax5.set_ylabel("Merton Distance-to-Default")
        ax5.set_title("Liquidity vs Market Distress", fontweight="bold", fontsize=10)
        ax5.grid(True, alpha=0.3)
    else:
        ax5.text(0.5, 0.5, "Insufficient data", ha="center", va="center", fontsize=11)
        ax5.set_title("Liquidity vs Market Distress", fontweight="bold", fontsize=10)

    # ---- Panel 6: Sector Distress Heatmap ----
    ax6 = fig.add_subplot(gs[2, :])
    sector_agg = stress_df.groupby("sector").agg({
        "total_score": "mean",
        "gross_leverage": "mean",
        "interest_coverage": "mean",
        "fcf_debt_pct": "mean",
        "name": "count",
    }).rename(columns={"name": "count"}).sort_values("total_score", ascending=False)

    if len(sector_agg) > 0:
        # Normalize for heatmap
        display_cols = ["total_score", "gross_leverage", "interest_coverage", "fcf_debt_pct"]
        norm_data = sector_agg[display_cols].copy()
        for col in display_cols:
            vals = norm_data[col].dropna()
            if len(vals) > 0 and vals.max() != vals.min():
                norm_data[col] = (norm_data[col] - vals.min()) / (vals.max() - vals.min())
            else:
                norm_data[col] = 0.5

        # Invert coverage and FCF (higher = better = should be green)
        if "interest_coverage" in norm_data.columns:
            norm_data["interest_coverage"] = 1 - norm_data["interest_coverage"]
        if "fcf_debt_pct" in norm_data.columns:
            norm_data["fcf_debt_pct"] = 1 - norm_data["fcf_debt_pct"]

        im = ax6.imshow(norm_data.values, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=1)
        ax6.set_yticks(range(len(norm_data)))
        ax6.set_yticklabels([f"{s} ({int(sector_agg.loc[s, 'count'])})" for s in norm_data.index], fontsize=7)
        col_labels = ["Avg Score", "Avg Leverage", "Avg Coverage*", "Avg FCF/Debt*"]
        ax6.set_xticks(range(len(col_labels)))
        ax6.set_xticklabels(col_labels, fontsize=8)
        ax6.set_title("Sector Distress Map (red = worse)  |  *inverted: red=low coverage/FCF", fontweight="bold", fontsize=10)

        for i, sector in enumerate(sector_agg.index):
            for j, col in enumerate(display_cols):
                val = sector_agg.loc[sector, col]
                if pd.notna(val):
                    if col == "total_score":
                        txt = f"{val:.0f}"
                    elif col == "gross_leverage":
                        txt = f"{val:.1f}x"
                    elif col == "interest_coverage":
                        txt = f"{val:.1f}x"
                    else:
                        txt = f"{val:+.1f}%"
                    ax6.text(j, i, txt, ha="center", va="center", fontsize=6.5, color="black")

    plt.savefig("distressed_monitor.png", dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: distressed_monitor.png")
    plt.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 80)
    print("  MODULE 13: DISTRESSED / LME MONITOR")
    print("  Liquidity Stress Scores, Cash Burn & Watch Lists")
    print("=" * 80)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. Fetch data
    print("  Step 1: Fetching constituent data...")
    constituents = fetch_all_constituents(use_cache=True)
    n_fund = sum(1 for c in constituents if c.has_fundamentals)
    print(f"  -> {n_fund} names with fundamentals")

    # 2. Compute fundamental ratios (Module 11)
    print("\n  Step 2: Computing fundamental credit ratios...")
    ratios_df = compute_all_ratios(constituents)
    print(f"  -> {len(ratios_df)} names with ratios")

    # 3. Compute Merton DD (if available)
    merton_df = None
    if HAS_MERTON:
        print("\n  Step 3: Computing Merton Distance-to-Default...")
        try:
            from analytics.crossover_constituents import compute_equity_metrics
            equity_df = compute_equity_metrics(constituents)
            merton_df = compute_merton_all(equity_df, constituents)
            print(f"  -> {len(merton_df)} names with Merton DD")
        except Exception as e:
            print(f"  -> Merton DD failed: {e}")
            merton_df = None
    else:
        print("\n  Step 3: Merton DD not available (module missing)")

    # 4. Compute distress scores
    print("\n  Step 4: Computing liquidity stress scores...")
    stress_df = compute_distressed_scores(constituents, ratios_df, merton_df)
    watch = generate_watch_list(stress_df)
    print(f"  -> {len(stress_df)} names scored")

    # 5. Report
    print_report(stress_df, watch)

    # 6. Dashboard
    print("\n  Step 6: Generating dashboard chart...")
    plot_dashboard(stress_df, watch)

    # 7. CSV
    if len(stress_df) > 0:
        stress_df.to_csv("distressed_monitor.csv", index=False)
        print(f"  CSV saved: distressed_monitor.csv")

    print("\n  DONE.\n")
    return stress_df


if __name__ == "__main__":
    main()

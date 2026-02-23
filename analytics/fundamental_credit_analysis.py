#!/usr/bin/env python3
"""
Module 11: Fundamental Credit Analysis
=======================================
Computes traditional credit ratios (Debt/EBITDA, interest coverage, FCF/Debt,
margins) from yfinance financial statements for iTraxx Crossover constituents.
Generates credit snapshots, trend analysis, and sector comparisons.

Based on:
  - Ch.8 "Credit Ratios" (A Pragmatist's Guide to Leveraged Finance)
  - Ch.26 "Credit Snapshot"
  - Ch.9 "Business Trend Analysis"

Dependencies:
  - crossover_constituents.py (ConstituentData with has_fundamentals)

Usage:
  python fundamental_credit_analysis.py

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
except ImportError:
    print("ERROR: crossover_constituents.py must be in the same directory")
    sys.exit(1)

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Credit ratio thresholds (from Ch.8 / industry practice)
LEVERAGE_THRESHOLDS = {
    "IG":       2.5,   # investment-grade territory
    "BB":       4.0,   # typical BB range
    "HIGH":     6.0,   # concerning
    "DISTRESS": 8.0,   # distressed territory
}

COVERAGE_THRESHOLDS = {
    "STRONG":   5.0,   # very comfortable
    "ADEQUATE": 3.0,   # adequate
    "WEAK":     2.0,   # watch closely
    "DANGER":   1.5,   # imminent risk
}

FCF_DEBT_THRESHOLDS = {
    "STRONG":   10.0,  # >10% FCF/Debt
    "ADEQUATE":  5.0,
    "WEAK":      0.0,  # positive but low
}


# =============================================================================
# CORE RATIO COMPUTATION
# =============================================================================

def _safe_latest(series: Optional[pd.Series]) -> float:
    """Get the latest (most recent) value from a series, or NaN."""
    if series is None or len(series) == 0:
        return np.nan
    return float(series.iloc[-1])


def _safe_prev(series: Optional[pd.Series], offset: int = 1) -> float:
    """Get a historical value from a series (offset from end), or NaN."""
    if series is None or len(series) <= offset:
        return np.nan
    return float(series.iloc[-(1 + offset)])


def _cagr(series: Optional[pd.Series], years: int = 3) -> float:
    """Compute CAGR over N years from an annual series."""
    if series is None or len(series) < years + 1:
        return np.nan
    start = float(series.iloc[-(1 + years)])
    end = float(series.iloc[-1])
    if start <= 0 or end <= 0:
        return np.nan
    return (end / start) ** (1.0 / years) - 1.0


def compute_latest_ratios(c: ConstituentData) -> dict:
    """
    Compute 8 key credit ratios for a single constituent.

    Returns dict with keys:
      gross_leverage, net_leverage, interest_coverage, fixed_charge_coverage,
      fcf_debt_pct, operating_margin_pct, ebitda_margin_pct, ev_ebitda
    """
    result = {
        "name": c.name,
        "ticker": c.ticker,
        "sector": c.sector,
        "rating": c.rating,
        "country": c.country,
    }

    total_debt = c.total_debt  # from .info, in $M
    ebitda = _safe_latest(c.ebitda)
    interest = _safe_latest(c.interest_expense)
    capex = _safe_latest(c.capex)
    fcf = _safe_latest(c.free_cash_flow)
    cash = _safe_latest(c.cash)
    ev = c.enterprise_value

    # Interest expense is often stored as negative in yfinance
    if not np.isnan(interest) and interest < 0:
        interest = abs(interest)
    # Capex is typically negative in yfinance
    if not np.isnan(capex) and capex < 0:
        capex = abs(capex)

    # 1. Gross Leverage = Total Debt / EBITDA
    if not np.isnan(ebitda) and ebitda > 0 and total_debt > 0:
        result["gross_leverage"] = total_debt / ebitda
    else:
        result["gross_leverage"] = np.nan

    # 2. Net Leverage = (Total Debt - Cash) / EBITDA
    if not np.isnan(ebitda) and ebitda > 0 and total_debt > 0:
        net_debt = total_debt - (cash if not np.isnan(cash) else 0)
        result["net_leverage"] = net_debt / ebitda
    else:
        result["net_leverage"] = np.nan

    # 3. Interest Coverage = EBITDA / Interest Expense
    if not np.isnan(ebitda) and not np.isnan(interest) and interest > 0:
        result["interest_coverage"] = ebitda / interest
    else:
        result["interest_coverage"] = np.nan

    # 4. Fixed Charge Coverage = (EBITDA - Capex) / Interest
    if not np.isnan(ebitda) and not np.isnan(interest) and interest > 0:
        adj_ebitda = ebitda - (capex if not np.isnan(capex) else 0)
        result["fixed_charge_coverage"] = adj_ebitda / interest
    else:
        result["fixed_charge_coverage"] = np.nan

    # 5. FCF / Debt (%)
    if not np.isnan(fcf) and total_debt > 0:
        result["fcf_debt_pct"] = (fcf / total_debt) * 100
    else:
        result["fcf_debt_pct"] = np.nan

    # 6. Operating Margin (%)
    if c.operating_margin != 0:
        result["operating_margin_pct"] = c.operating_margin * 100
    else:
        rev = _safe_latest(c.total_revenue)
        op_inc = _safe_latest(c.operating_income)
        if not np.isnan(rev) and rev > 0 and not np.isnan(op_inc):
            result["operating_margin_pct"] = (op_inc / rev) * 100
        else:
            result["operating_margin_pct"] = np.nan

    # 7. EBITDA Margin (%)
    if c.ebitda_margin != 0:
        result["ebitda_margin_pct"] = c.ebitda_margin * 100
    else:
        rev = _safe_latest(c.total_revenue)
        if not np.isnan(rev) and rev > 0 and not np.isnan(ebitda):
            result["ebitda_margin_pct"] = (ebitda / rev) * 100
        else:
            result["ebitda_margin_pct"] = np.nan

    # 8. EV / EBITDA
    if not np.isnan(ebitda) and ebitda > 0 and ev > 0:
        result["ev_ebitda"] = ev / ebitda
    else:
        result["ev_ebitda"] = np.nan

    return result


def compute_3yr_trends(c: ConstituentData) -> dict:
    """
    Compute 3-year trend metrics for a single constituent.

    Returns dict with:
      revenue_cagr, ebitda_cagr, margin_trajectory, leverage_trajectory
    """
    result = {"name": c.name}

    # Revenue CAGR
    result["revenue_cagr"] = _cagr(c.total_revenue, 3)

    # EBITDA CAGR
    result["ebitda_cagr"] = _cagr(c.ebitda, 3)

    # Margin trajectory (compare latest vs 2yr-ago EBITDA margin)
    if c.ebitda is not None and c.total_revenue is not None:
        if len(c.ebitda) >= 3 and len(c.total_revenue) >= 3:
            latest_margin = float(c.ebitda.iloc[-1]) / float(c.total_revenue.iloc[-1]) if float(c.total_revenue.iloc[-1]) > 0 else np.nan
            old_margin = float(c.ebitda.iloc[-3]) / float(c.total_revenue.iloc[-3]) if float(c.total_revenue.iloc[-3]) > 0 else np.nan
            if not np.isnan(latest_margin) and not np.isnan(old_margin):
                diff = latest_margin - old_margin
                if diff > 0.02:
                    result["margin_trajectory"] = "IMPROVING"
                elif diff < -0.02:
                    result["margin_trajectory"] = "WORSENING"
                else:
                    result["margin_trajectory"] = "STABLE"
            else:
                result["margin_trajectory"] = "N/A"
        else:
            result["margin_trajectory"] = "N/A"
    else:
        result["margin_trajectory"] = "N/A"

    # Leverage trajectory (compare latest vs 2yr-ago Debt/EBITDA)
    if c.ebitda is not None and len(c.ebitda) >= 3:
        latest_ebitda = float(c.ebitda.iloc[-1])
        old_ebitda = float(c.ebitda.iloc[-3])
        if latest_ebitda > 0 and old_ebitda > 0 and c.total_debt > 0:
            latest_lev = c.total_debt / latest_ebitda
            old_lev = c.total_debt / old_ebitda  # approximate: using current debt for both
            diff = latest_lev - old_lev
            if diff < -0.5:
                result["leverage_trajectory"] = "DELEVERAGING"
            elif diff > 0.5:
                result["leverage_trajectory"] = "INCREASING"
            else:
                result["leverage_trajectory"] = "FLAT"
        else:
            result["leverage_trajectory"] = "N/A"
    else:
        result["leverage_trajectory"] = "N/A"

    return result


# =============================================================================
# UNIVERSE-LEVEL COMPUTATION
# =============================================================================

def compute_all_ratios(constituents: List[ConstituentData]) -> pd.DataFrame:
    """
    Compute credit ratios for all constituents with fundamental data.
    Returns DataFrame sorted by gross leverage (worst first), with flag columns.
    """
    rows = []
    for c in constituents:
        if not c.fetch_success or not c.has_fundamentals:
            continue

        ratios = compute_latest_ratios(c)
        trends = compute_3yr_trends(c)

        # Merge
        row = {**ratios}
        row["revenue_cagr"] = trends.get("revenue_cagr", np.nan)
        row["ebitda_cagr"] = trends.get("ebitda_cagr", np.nan)
        row["margin_trajectory"] = trends.get("margin_trajectory", "N/A")
        row["leverage_trajectory"] = trends.get("leverage_trajectory", "N/A")

        # Raw financials for downstream modules ($M)
        row["total_debt_mm"] = c.total_debt
        row["ebitda_mm"] = _safe_latest(c.ebitda)
        row["interest_expense_mm"] = abs(_safe_latest(c.interest_expense)) if not np.isnan(_safe_latest(c.interest_expense)) else np.nan
        row["fcf_mm"] = _safe_latest(c.free_cash_flow)
        row["cash_mm"] = _safe_latest(c.cash)
        row["revenue_mm"] = _safe_latest(c.total_revenue)
        row["capex_mm"] = abs(_safe_latest(c.capex)) if not np.isnan(_safe_latest(c.capex)) else np.nan
        row["enterprise_value_mm"] = c.enterprise_value
        row["market_cap_mm"] = c.market_cap
        row["current_ratio"] = c.current_ratio
        row["operating_cashflow_mm"] = _safe_latest(c.operating_cash_flow)

        # Flags
        cov = row.get("interest_coverage", np.nan)
        lev = row.get("gross_leverage", np.nan)
        fcf = row.get("fcf_debt_pct", np.nan)

        flags = []
        if not np.isnan(cov) and cov < COVERAGE_THRESHOLDS["WEAK"]:
            flags.append("LOW_COV")
        if not np.isnan(lev) and lev > LEVERAGE_THRESHOLDS["HIGH"]:
            flags.append("HIGH_LEV")
        if not np.isnan(fcf) and fcf < 0:
            flags.append("NEG_FCF")

        row["flags"] = ", ".join(flags) if flags else ""
        row["n_flags"] = len(flags)

        rows.append(row)

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("gross_leverage", ascending=False, na_position="last")
    return df


# =============================================================================
# CONSOLE REPORT
# =============================================================================

def print_report(ratios_df: pd.DataFrame):
    """Print comprehensive fundamental credit analysis report."""
    if len(ratios_df) == 0:
        print("  No fundamental data available.")
        return

    n = len(ratios_df)
    n_lev = ratios_df["gross_leverage"].notna().sum()

    print("\n" + "=" * 120)
    print("  FUNDAMENTAL CREDIT ANALYSIS  - iTRAXX CROSSOVER UNIVERSE")
    print("=" * 120)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Names with fundamentals: {n}")
    print()

    # --- Section 1: Full Ratio Ranking Table ---
    print(f"{'=' * 120}")
    print("  1. CREDIT RATIO RANKING (sorted by leverage, highest first)")
    print(f"{'=' * 120}")
    print(f"  {'Name':<28s} {'Sector':<15s} {'Rtg':>4s} {'Debt/EBITDA':>11s} {'Net Lev':>8s} "
          f"{'Coverage':>9s} {'FCF/Debt':>9s} {'EBITDA%':>8s} {'EV/EBITDA':>10s} {'Flags'}")
    print("  " + "-" * 116)

    for _, row in ratios_df.iterrows():
        gl = f"{row['gross_leverage']:.1f}x" if pd.notna(row['gross_leverage']) else "N/A"
        nl = f"{row['net_leverage']:.1f}x" if pd.notna(row['net_leverage']) else "N/A"
        cov = f"{row['interest_coverage']:.1f}x" if pd.notna(row['interest_coverage']) else "N/A"
        fcf = f"{row['fcf_debt_pct']:+.1f}%" if pd.notna(row['fcf_debt_pct']) else "N/A"
        em = f"{row['ebitda_margin_pct']:.1f}%" if pd.notna(row['ebitda_margin_pct']) else "N/A"
        ev = f"{row['ev_ebitda']:.1f}x" if pd.notna(row['ev_ebitda']) else "N/A"
        flags = row.get('flags', '')

        print(f"  {row['name']:<28s} {row['sector']:<15s} {row['rating']:>4s} {gl:>11s} {nl:>8s} "
              f"{cov:>9s} {fcf:>9s} {em:>8s} {ev:>10s} {flags}")

    # --- Section 2: Credit Quality Alerts ---
    flagged = ratios_df[ratios_df["n_flags"] > 0].sort_values("n_flags", ascending=False)
    print(f"\n{'=' * 120}")
    print(f"  2. CREDIT QUALITY ALERTS ({len(flagged)} names flagged)")
    print(f"{'=' * 120}")

    if len(flagged) > 0:
        for _, row in flagged.iterrows():
            gl = f"{row['gross_leverage']:.1f}x" if pd.notna(row['gross_leverage']) else "N/A"
            cov = f"{row['interest_coverage']:.1f}x" if pd.notna(row['interest_coverage']) else "N/A"
            fcf = f"{row['fcf_debt_pct']:+.1f}%" if pd.notna(row['fcf_debt_pct']) else "N/A"
            print(f"  [{row['flags']:20s}] {row['name']:<28s} | Lev={gl} | Cov={cov} | FCF/Debt={fcf}")
    else:
        print("  No names flagged.")

    # --- Section 3: Sector Credit Quality Averages ---
    print(f"\n{'=' * 120}")
    print("  3. SECTOR CREDIT QUALITY AVERAGES")
    print(f"{'=' * 120}")

    sector_agg = ratios_df.groupby("sector").agg({
        "name": "count",
        "gross_leverage": "mean",
        "interest_coverage": "mean",
        "ebitda_margin_pct": "mean",
        "fcf_debt_pct": "mean",
        "revenue_cagr": "mean",
    }).rename(columns={"name": "count"}).sort_values("gross_leverage", ascending=False)

    print(f"  {'Sector':<20s} {'Count':>5s} {'Avg Lev':>8s} {'Avg Cov':>8s} {'EBITDA%':>8s} {'FCF/Debt':>9s} {'Rev CAGR':>9s}")
    print("  " + "-" * 70)
    for sector, row in sector_agg.iterrows():
        lev = f"{row['gross_leverage']:.1f}x" if pd.notna(row['gross_leverage']) else "N/A"
        cov = f"{row['interest_coverage']:.1f}x" if pd.notna(row['interest_coverage']) else "N/A"
        em = f"{row['ebitda_margin_pct']:.1f}%" if pd.notna(row['ebitda_margin_pct']) else "N/A"
        fcf = f"{row['fcf_debt_pct']:+.1f}%" if pd.notna(row['fcf_debt_pct']) else "N/A"
        cagr = f"{row['revenue_cagr']*100:+.1f}%" if pd.notna(row['revenue_cagr']) else "N/A"
        print(f"  {sector:<20s} {int(row['count']):>5d} {lev:>8s} {cov:>8s} {em:>8s} {fcf:>9s} {cagr:>9s}")

    # --- Section 4: Credit Snapshots - Weakest 5 ---
    lev_valid = ratios_df.dropna(subset=["gross_leverage"])
    if len(lev_valid) > 0:
        weakest = lev_valid.nlargest(5, "gross_leverage")
        print(f"\n{'=' * 120}")
        print("  4. CREDIT SNAPSHOTS  - 5 WEAKEST NAMES (highest leverage)")
        print(f"{'=' * 120}")
        for _, row in weakest.iterrows():
            _print_snapshot(row)

    # --- Section 5: Credit Snapshots - Strongest 5 ---
    if len(lev_valid) > 0:
        strongest = lev_valid.nsmallest(5, "gross_leverage")
        print(f"\n{'=' * 120}")
        print("  5. CREDIT SNAPSHOTS  - 5 STRONGEST NAMES (lowest leverage)")
        print(f"{'=' * 120}")
        for _, row in strongest.iterrows():
            _print_snapshot(row)

    print("\n" + "=" * 120)


def _print_snapshot(row):
    """Print a detailed credit snapshot for a single name."""
    print(f"\n  {'-' * 80}")
    print(f"  {row['name']} ({row['ticker']})  - {row['sector']} | {row['rating']} | {row['country']}")
    print(f"  {'-' * 80}")

    # Financials
    debt = f"${row['total_debt_mm']:,.0f}M" if pd.notna(row['total_debt_mm']) else "N/A"
    ebitda = f"${row['ebitda_mm']:,.0f}M" if pd.notna(row['ebitda_mm']) else "N/A"
    rev = f"${row['revenue_mm']:,.0f}M" if pd.notna(row['revenue_mm']) else "N/A"
    cash = f"${row['cash_mm']:,.0f}M" if pd.notna(row['cash_mm']) else "N/A"
    fcf = f"${row['fcf_mm']:,.0f}M" if pd.notna(row['fcf_mm']) else "N/A"
    interest = f"${row['interest_expense_mm']:,.0f}M" if pd.notna(row['interest_expense_mm']) else "N/A"
    capex = f"${row['capex_mm']:,.0f}M" if pd.notna(row['capex_mm']) else "N/A"
    ev_str = f"${row['enterprise_value_mm']:,.0f}M" if pd.notna(row['enterprise_value_mm']) and row['enterprise_value_mm'] > 0 else "N/A"

    print(f"  Financials:  Revenue={rev}  EBITDA={ebitda}  Debt={debt}  Cash={cash}")
    print(f"               FCF={fcf}  Interest={interest}  Capex={capex}  EV={ev_str}")

    # Ratios
    gl = f"{row['gross_leverage']:.1f}x" if pd.notna(row['gross_leverage']) else "N/A"
    nl = f"{row['net_leverage']:.1f}x" if pd.notna(row['net_leverage']) else "N/A"
    cov = f"{row['interest_coverage']:.1f}x" if pd.notna(row['interest_coverage']) else "N/A"
    fcc = f"{row['fixed_charge_coverage']:.1f}x" if pd.notna(row['fixed_charge_coverage']) else "N/A"
    fcf_d = f"{row['fcf_debt_pct']:+.1f}%" if pd.notna(row['fcf_debt_pct']) else "N/A"
    em = f"{row['ebitda_margin_pct']:.1f}%" if pd.notna(row['ebitda_margin_pct']) else "N/A"
    om = f"{row['operating_margin_pct']:.1f}%" if pd.notna(row['operating_margin_pct']) else "N/A"
    ev_eb = f"{row['ev_ebitda']:.1f}x" if pd.notna(row['ev_ebitda']) else "N/A"

    print(f"  Ratios:      Gross Leverage={gl}  Net Leverage={nl}  Interest Coverage={cov}")
    print(f"               Fixed Charge Coverage={fcc}  FCF/Debt={fcf_d}")
    print(f"               EBITDA Margin={em}  Operating Margin={om}  EV/EBITDA={ev_eb}")

    # Trends
    rc = f"{row['revenue_cagr']*100:+.1f}%" if pd.notna(row['revenue_cagr']) else "N/A"
    ec = f"{row['ebitda_cagr']*100:+.1f}%" if pd.notna(row['ebitda_cagr']) else "N/A"
    mt = row.get('margin_trajectory', 'N/A')
    lt = row.get('leverage_trajectory', 'N/A')

    print(f"  Trends:      Revenue CAGR (3yr)={rc}  EBITDA CAGR (3yr)={ec}")
    print(f"               Margin Trajectory={mt}  Leverage Trajectory={lt}")

    # Flags
    flags = row.get('flags', '')
    if flags:
        print(f"  ** ALERTS:   {flags}")


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(ratios_df: pd.DataFrame):
    """Create 24x18 fundamental credit analysis dashboard (6 panels)."""
    if len(ratios_df) == 0:
        print("  No data to plot.")
        return

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "FUNDAMENTAL CREDIT ANALYSIS  - iTRAXX CROSSOVER UNIVERSE",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(
        0.5, 0.955,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(ratios_df)} names with fundamentals",
        ha="center", fontsize=10, color="gray",
    )

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # ---- Panel 1: Leverage Distribution (horizontal bars, color-coded) ----
    ax1 = fig.add_subplot(gs[0, :2])
    lev_data = ratios_df.dropna(subset=["gross_leverage"]).sort_values("gross_leverage", ascending=True)
    # Cap display at 15x for readability
    lev_display = lev_data["gross_leverage"].clip(upper=15)
    if len(lev_data) > 0:
        colors = []
        for lev in lev_data["gross_leverage"]:
            if lev > LEVERAGE_THRESHOLDS["DISTRESS"]:
                colors.append("#c0392b")
            elif lev > LEVERAGE_THRESHOLDS["HIGH"]:
                colors.append("#e74c3c")
            elif lev > LEVERAGE_THRESHOLDS["BB"]:
                colors.append("#f39c12")
            elif lev > LEVERAGE_THRESHOLDS["IG"]:
                colors.append("#f1c40f")
            else:
                colors.append("#2ecc71")

        ax1.barh(range(len(lev_data)), lev_display.values, color=colors,
                 edgecolor="white", linewidth=0.3)
        ax1.set_yticks(range(len(lev_data)))
        ax1.set_yticklabels([n[:22] for n in lev_data["name"]], fontsize=5.5)
        ax1.axvline(LEVERAGE_THRESHOLDS["IG"], color="#2ecc71", linewidth=1, linestyle="--", label=f"{LEVERAGE_THRESHOLDS['IG']}x IG")
        ax1.axvline(LEVERAGE_THRESHOLDS["BB"], color="#f39c12", linewidth=1, linestyle="--", label=f"{LEVERAGE_THRESHOLDS['BB']}x BB")
        ax1.axvline(LEVERAGE_THRESHOLDS["HIGH"], color="#e74c3c", linewidth=1, linestyle="--", label=f"{LEVERAGE_THRESHOLDS['HIGH']}x High")
        ax1.set_title("Gross Leverage (Debt / EBITDA)", fontweight="bold")
        ax1.set_xlabel("Debt/EBITDA (capped at 15x for display)")
        ax1.legend(fontsize=7, loc="lower right")
        ax1.grid(True, alpha=0.3, axis="x")

    # ---- Panel 2: Universe Summary Box ----
    ax_sum = fig.add_subplot(gs[0, 2])
    ax_sum.set_xlim(0, 1)
    ax_sum.set_ylim(0, 1)
    ax_sum.axis("off")

    lev_valid = ratios_df["gross_leverage"].dropna()
    cov_valid = ratios_df["interest_coverage"].dropna()
    fcf_valid = ratios_df["fcf_debt_pct"].dropna()
    n_flagged = (ratios_df["n_flags"] > 0).sum()

    avg_lev = lev_valid.mean() if len(lev_valid) > 0 else np.nan
    med_lev = lev_valid.median() if len(lev_valid) > 0 else np.nan
    avg_cov = cov_valid.mean() if len(cov_valid) > 0 else np.nan
    avg_fcf = fcf_valid.mean() if len(fcf_valid) > 0 else np.nan

    box = FancyBboxPatch((0.05, 0.05), 0.9, 0.9, boxstyle="round,pad=0.05",
                          facecolor="#2c3e50", alpha=0.15, edgecolor="#2c3e50", linewidth=2)
    ax_sum.add_patch(box)
    ax_sum.text(0.5, 0.90, "CREDIT UNIVERSE SUMMARY", ha="center", fontsize=12, fontweight="bold")
    ax_sum.text(0.5, 0.78, f"Names: {len(ratios_df)}  |  Flagged: {n_flagged}", ha="center", fontsize=10,
                color="#e74c3c" if n_flagged > 10 else "#f39c12" if n_flagged > 5 else "#2ecc71")

    lev_color = "#e74c3c" if not np.isnan(avg_lev) and avg_lev > 5 else "#f39c12" if not np.isnan(avg_lev) and avg_lev > 3 else "#2ecc71"
    ax_sum.text(0.5, 0.64, f"Avg Leverage: {avg_lev:.1f}x" if not np.isnan(avg_lev) else "Avg Leverage: N/A",
                ha="center", fontsize=11, color=lev_color)
    ax_sum.text(0.5, 0.52, f"Median Leverage: {med_lev:.1f}x" if not np.isnan(med_lev) else "Med Leverage: N/A",
                ha="center", fontsize=10)

    cov_color = "#2ecc71" if not np.isnan(avg_cov) and avg_cov > 4 else "#f39c12" if not np.isnan(avg_cov) and avg_cov > 2 else "#e74c3c"
    ax_sum.text(0.5, 0.40, f"Avg Coverage: {avg_cov:.1f}x" if not np.isnan(avg_cov) else "Avg Coverage: N/A",
                ha="center", fontsize=11, color=cov_color)
    ax_sum.text(0.5, 0.28, f"Avg FCF/Debt: {avg_fcf:+.1f}%" if not np.isnan(avg_fcf) else "Avg FCF/Debt: N/A",
                ha="center", fontsize=10,
                color="#2ecc71" if not np.isnan(avg_fcf) and avg_fcf > 5 else "#e74c3c")

    n_low_cov = ratios_df["flags"].str.contains("LOW_COV", na=False).sum()
    n_high_lev = ratios_df["flags"].str.contains("HIGH_LEV", na=False).sum()
    n_neg_fcf = ratios_df["flags"].str.contains("NEG_FCF", na=False).sum()
    ax_sum.text(0.5, 0.14, f"LOW_COV: {n_low_cov}  |  HIGH_LEV: {n_high_lev}  |  NEG_FCF: {n_neg_fcf}",
                ha="center", fontsize=9, color="#e74c3c")

    # ---- Panel 3: Coverage vs Leverage Scatter (colored by sector) ----
    ax3 = fig.add_subplot(gs[1, 0])
    scatter_df = ratios_df.dropna(subset=["gross_leverage", "interest_coverage"])
    if len(scatter_df) > 0:
        sectors = sorted(scatter_df["sector"].unique())
        cmap = plt.cm.Set3(np.linspace(0, 1, max(len(sectors), 1)))
        sector_colors = {s: cmap[i] for i, s in enumerate(sectors)}

        for _, row in scatter_df.iterrows():
            x = min(row["gross_leverage"], 15)  # cap for display
            y = min(row["interest_coverage"], 20)
            ax3.scatter(x, y, s=50, c=[sector_colors.get(row["sector"], "gray")],
                       alpha=0.7, edgecolor="white", linewidth=0.5)
            if row["n_flags"] > 0:
                ax3.annotate(row["name"][:12], (x, y), fontsize=5, alpha=0.7,
                           xytext=(3, 3), textcoords="offset points")

        ax3.axhline(COVERAGE_THRESHOLDS["WEAK"], color="red", linewidth=0.8, linestyle="--", alpha=0.7)
        ax3.axhline(COVERAGE_THRESHOLDS["ADEQUATE"], color="orange", linewidth=0.8, linestyle="--", alpha=0.7)
        ax3.axvline(LEVERAGE_THRESHOLDS["BB"], color="orange", linewidth=0.8, linestyle="--", alpha=0.7)
        ax3.axvline(LEVERAGE_THRESHOLDS["HIGH"], color="red", linewidth=0.8, linestyle="--", alpha=0.7)
        ax3.set_xlabel("Gross Leverage (Debt/EBITDA)")
        ax3.set_ylabel("Interest Coverage (EBITDA/Interest)")
        ax3.set_title("Coverage vs Leverage", fontweight="bold", fontsize=10)
        ax3.grid(True, alpha=0.3)

    # ---- Panel 4: Sector Credit Quality Heatmap ----
    ax4 = fig.add_subplot(gs[1, 1:])
    sector_agg = ratios_df.groupby("sector").agg({
        "gross_leverage": "mean",
        "interest_coverage": "mean",
        "ebitda_margin_pct": "mean",
        "revenue_cagr": "mean",
    }).dropna(how="all")

    if len(sector_agg) > 0:
        display_data = sector_agg.copy()
        col_names = ["Leverage", "Coverage", "EBITDA Margin", "Revenue Growth"]

        # Normalize (for heatmap color)
        norm_data = display_data.copy()
        for col in display_data.columns:
            vals = display_data[col].dropna()
            if len(vals) > 0 and vals.max() != vals.min():
                norm_data[col] = (display_data[col] - vals.min()) / (vals.max() - vals.min())
            else:
                norm_data[col] = 0.5

        # For leverage, invert (higher = worse = red)
        if "gross_leverage" in norm_data.columns:
            norm_data["gross_leverage"] = 1 - norm_data["gross_leverage"]
        # For coverage, margin, growth: higher = better = green (keep as is for RdYlGn)

        # Sort by average of normalized scores (worst sectors first)
        norm_data["avg_score"] = norm_data.mean(axis=1)
        norm_data = norm_data.sort_values("avg_score", ascending=True)
        display_data = display_data.loc[norm_data.index]
        norm_data = norm_data.drop(columns=["avg_score"])

        im = ax4.imshow(norm_data.values, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)
        ax4.set_yticks(range(len(norm_data)))
        ax4.set_yticklabels(norm_data.index, fontsize=7)
        ax4.set_xticks(range(len(col_names)))
        ax4.set_xticklabels(col_names, fontsize=8)
        ax4.set_title("Sector Credit Quality Heatmap (green=better)", fontweight="bold", fontsize=10)

        for i, sector in enumerate(display_data.index):
            for j, col in enumerate(display_data.columns):
                val = display_data.loc[sector, col]
                if pd.notna(val):
                    if col == "revenue_cagr":
                        txt = f"{val*100:+.1f}%"
                    elif col == "ebitda_margin_pct":
                        txt = f"{val:.0f}%"
                    elif col == "gross_leverage":
                        txt = f"{val:.1f}x"
                    else:
                        txt = f"{val:.1f}x"
                    ax4.text(j, i, txt, ha="center", va="center", fontsize=6.5, color="black")

    # ---- Panel 5: FCF/Debt Ranking (top 15 bars) ----
    ax5 = fig.add_subplot(gs[2, :2])
    fcf_data = ratios_df.dropna(subset=["fcf_debt_pct"]).sort_values("fcf_debt_pct", ascending=True)
    if len(fcf_data) > 0:
        # Show all names
        colors_fcf = []
        for v in fcf_data["fcf_debt_pct"]:
            if v < 0:
                colors_fcf.append("#e74c3c")
            elif v < FCF_DEBT_THRESHOLDS["ADEQUATE"]:
                colors_fcf.append("#f39c12")
            elif v < FCF_DEBT_THRESHOLDS["STRONG"]:
                colors_fcf.append("#f1c40f")
            else:
                colors_fcf.append("#2ecc71")

        ax5.barh(range(len(fcf_data)), fcf_data["fcf_debt_pct"].values, color=colors_fcf,
                 edgecolor="white", linewidth=0.3)
        ax5.set_yticks(range(len(fcf_data)))
        ax5.set_yticklabels([n[:22] for n in fcf_data["name"]], fontsize=5.5)
        ax5.axvline(0, color="black", linewidth=1)
        ax5.axvline(FCF_DEBT_THRESHOLDS["ADEQUATE"], color="orange", linewidth=0.8, linestyle="--")
        ax5.axvline(FCF_DEBT_THRESHOLDS["STRONG"], color="green", linewidth=0.8, linestyle="--")
        ax5.set_title("FCF / Debt (%)  - Repayment Capacity", fontweight="bold")
        ax5.set_xlabel("FCF / Total Debt (%)")
        ax5.grid(True, alpha=0.3, axis="x")

    # ---- Panel 6: Margin vs Growth Scatter (colored by rating) ----
    ax6 = fig.add_subplot(gs[2, 2])
    mg_df = ratios_df.dropna(subset=["ebitda_margin_pct", "revenue_cagr"])
    if len(mg_df) > 0:
        rating_colors = {
            "BB+": "#27ae60", "BB": "#2ecc71", "BB-": "#f1c40f",
            "B+": "#f39c12", "B": "#e67e22", "B-": "#e74c3c", "CCC": "#c0392b"
        }
        for _, row in mg_df.iterrows():
            c = rating_colors.get(row["rating"], "#95a5a6")
            ax6.scatter(row["revenue_cagr"] * 100, row["ebitda_margin_pct"],
                       s=50, c=[c], alpha=0.7, edgecolor="white", linewidth=0.5)

        ax6.set_xlabel("Revenue CAGR 3yr (%)")
        ax6.set_ylabel("EBITDA Margin (%)")
        ax6.set_title("Margin vs Growth (color=rating)", fontweight="bold", fontsize=10)
        ax6.axhline(15, color="gray", linewidth=0.5, linestyle=":")
        ax6.axvline(0, color="gray", linewidth=0.5, linestyle=":")
        ax6.grid(True, alpha=0.3)

        # Legend
        from matplotlib.lines import Line2D
        legend_elements = [Line2D([0], [0], marker='o', color='w', markerfacecolor=v,
                                   label=k, markersize=6) for k, v in rating_colors.items()]
        ax6.legend(handles=legend_elements, fontsize=6, loc="lower right", ncol=2)

    plt.savefig("fundamental_credit_analysis.png", dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: fundamental_credit_analysis.png")
    plt.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 80)
    print("  MODULE 11: FUNDAMENTAL CREDIT ANALYSIS")
    print("  Credit Ratios, Trends & Snapshots")
    print("=" * 80)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. Fetch data (uses cache)
    print("  Step 1: Fetching constituent data (with fundamentals)...")
    constituents = fetch_all_constituents(use_cache=True)
    n_fund = sum(1 for c in constituents if c.has_fundamentals)
    print(f"  -> {n_fund} names with fundamental data")

    # 2. Compute ratios
    print("\n  Step 2: Computing credit ratios and trends...")
    ratios_df = compute_all_ratios(constituents)
    print(f"  -> {len(ratios_df)} names computed")

    # 3. Report
    print_report(ratios_df)

    # 4. Dashboard
    print("\n  Step 4: Generating dashboard chart...")
    plot_dashboard(ratios_df)

    # 5. CSV Export
    if len(ratios_df) > 0:
        ratios_df.to_csv("fundamental_credit_analysis.csv", index=False)
        print(f"  CSV saved: fundamental_credit_analysis.csv")

    print("\n  DONE.\n")
    return ratios_df


if __name__ == "__main__":
    main()

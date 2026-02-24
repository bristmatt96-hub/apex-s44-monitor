#!/usr/bin/env python3
"""
Fund Business Plan Generator
==============================
Generates a structured investment memo / business plan for an iTraxx equity
tranche dispersion strategy hedge fund. Uses live data from all modules to
populate the investment thesis, financial projections, and risk framework.

Sections:
  1. Executive Summary
  2. Investment Thesis (uses live dispersion signals and macro regime)
  3. Strategy Description (tranche mechanics, entry/exit framework)
  4. Fund Structure (domicile, fees, terms, service providers)
  5. Team & Organization (roles, compensation, org chart)
  6. Financial Projections (3yr P&L, 3 scenarios, break-even)
  7. Risk Framework (limits, monitoring, stress testing)
  8. Regulatory & Compliance (AIFMD, ISDA, EMIR)
  9. Operational Setup (technology = this dashboard, data sources)
  10. Appendix (assumptions, glossary)

Usage:
  python -m analytics.fund_business_plan
  python -m analytics.fund_business_plan --aum 250 --domicile Ireland --json
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

warnings.filterwarnings("ignore")

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs" / "pitch"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_TARGET_AUM = 100_000_000   # $100mm target
DEFAULT_DOMICILE = "Luxembourg"     # SCSp-RAIF
DEFAULT_MGMT_FEE = 0.015           # 1.5%
DEFAULT_PERF_FEE = 0.20            # 20%
DEFAULT_HURDLE = 0.05              # 5% hurdle rate


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class FundStructure:
    """Fund legal and commercial structure."""
    fund_name: str
    domicile: str
    vehicle: str              # SCSp-RAIF, ICAV, SPC etc
    mgmt_fee_pct: float
    perf_fee_pct: float
    hurdle_rate: float
    lock_up_months: int
    redemption_notice_days: int
    min_investment: float
    target_aum: float
    max_aum: float
    fund_admin: str
    prime_broker: str
    auditor: str
    legal_counsel: str


@dataclass
class TeamMember:
    """Team member definition."""
    role: str
    title: str
    compensation_base: float
    compensation_bonus_pct: float
    description: str


@dataclass
class FinancialProjection:
    """Year-by-year financial projection."""
    year: int
    scenario: str             # "Bull", "Base", "Bear"
    aum_start: float
    aum_end: float
    gross_return_pct: float
    net_return_pct: float
    mgmt_fee_revenue: float
    perf_fee_revenue: float
    total_revenue: float
    total_costs: float
    net_income: float
    margin_pct: float


@dataclass
class BusinessPlan:
    """Complete business plan."""
    timestamp: str
    fund_structure: FundStructure
    team: List[TeamMember]
    projections: List[FinancialProjection]
    plan_text: str            # full text of the plan
    break_even_aum: float
    target_sharpe: float
    target_vol: float


# =============================================================================
# FUND STRUCTURE
# =============================================================================

def define_fund_structure(target_aum: float = DEFAULT_TARGET_AUM,
                           domicile: str = DEFAULT_DOMICILE,
                           mgmt_fee: float = DEFAULT_MGMT_FEE,
                           perf_fee: float = DEFAULT_PERF_FEE,
                           hurdle: float = DEFAULT_HURDLE) -> FundStructure:
    """Define fund legal and commercial structure."""
    if domicile == "Luxembourg":
        vehicle = "SCSp-RAIF"
        fund_admin = "Alter Domus (Luxembourg)"
        legal = "Arendt & Medernach"
    elif domicile == "Ireland":
        vehicle = "ICAV (QIF)"
        fund_admin = "Apex Fund Services (Dublin)"
        legal = "Matheson LLP"
    elif domicile == "Cayman":
        vehicle = "SPC (Segregated Portfolio Company)"
        fund_admin = "Maples Fund Services"
        legal = "Maples and Calder"
    else:
        vehicle = "SCSp-RAIF"
        fund_admin = "Alter Domus"
        legal = "Local counsel"

    return FundStructure(
        fund_name="Correlation Alpha Fund",
        domicile=domicile,
        vehicle=vehicle,
        mgmt_fee_pct=mgmt_fee,
        perf_fee_pct=perf_fee,
        hurdle_rate=hurdle,
        lock_up_months=12,
        redemption_notice_days=90,
        min_investment=1_000_000,
        target_aum=target_aum,
        max_aum=target_aum * 5,
        fund_admin=fund_admin,
        prime_broker="Goldman Sachs / J.P. Morgan (dual PB)",
        auditor="KPMG / Deloitte",
        legal_counsel=legal,
    )


# =============================================================================
# TEAM DEFINITION
# =============================================================================

def define_team(aum: float = DEFAULT_TARGET_AUM) -> List[TeamMember]:
    """Define team scaled by AUM."""
    aum_mm = aum / 1e6

    team = [
        TeamMember("PM/CIO", "Chief Investment Officer & Portfolio Manager",
                   350000, 0.30,
                   "Overall strategy, portfolio construction, final trade approval. "
                   "10+ years structured credit experience."),
        TeamMember("Quant/Structurer", "Senior Quantitative Strategist",
                   250000, 0.25,
                   "Copula modeling, Greeks computation, signal development. "
                   "PhD in mathematics/finance."),
        TeamMember("Trader", "Senior Credit Trader",
                   220000, 0.25,
                   "Trade execution, broker relationships, market color. "
                   "ISDA/CSA negotiation, clearing ops."),
        TeamMember("Risk Manager", "Head of Risk",
                   200000, 0.20,
                   "VaR, stress testing, limit monitoring, margin management. "
                   "FRM/CFA, compliance oversight."),
        TeamMember("Analyst", "Credit Research Analyst",
                   150000, 0.15,
                   "Single-name credit analysis, fundamental research, "
                   "sector coverage, distressed monitoring."),
        TeamMember("COO/CFO", "Chief Operating Officer & CFO",
                   200000, 0.15,
                   "Fund operations, NAV oversight, investor relations, "
                   "regulatory reporting, service provider management."),
    ]

    # Scale team with AUM
    if aum_mm >= 250:
        team.extend([
            TeamMember("Jr Analyst", "Junior Analyst",
                       100000, 0.10, "Supporting research, data management, reporting."),
            TeamMember("Tech/Data", "Technology & Data Engineer",
                       180000, 0.15, "Dashboard maintenance, data pipeline, cloud infrastructure."),
            TeamMember("Compliance", "Compliance Officer",
                       160000, 0.10, "AIFMD reporting, trade surveillance, AML/KYC."),
            TeamMember("Operations", "Operations Analyst",
                       120000, 0.10, "Trade settlement, reconciliation, margin calls."),
        ])
    elif aum_mm >= 100:
        team.extend([
            TeamMember("Jr Analyst", "Junior Analyst",
                       100000, 0.10, "Supporting research, data management."),
            TeamMember("Tech/Data", "Technology & Data Engineer",
                       180000, 0.15, "Dashboard maintenance, data pipeline."),
        ])

    return team


# =============================================================================
# FINANCIAL PROJECTIONS
# =============================================================================

def compute_projections(fund: FundStructure,
                         team: List[TeamMember],
                         years: int = 3) -> List[FinancialProjection]:
    """
    Compute 3-year financial projections under Bull/Base/Bear scenarios.
    """
    # Return scenarios for dispersion strategy
    scenarios = {
        "Bull":  {"gross_return": [0.18, 0.15, 0.14], "aum_growth": [0.50, 0.40, 0.30]},
        "Base":  {"gross_return": [0.10, 0.09, 0.08], "aum_growth": [0.30, 0.20, 0.15]},
        "Bear":  {"gross_return": [-0.05, 0.03, 0.06], "aum_growth": [0.00, -0.20, 0.10]},
    }

    # Fixed costs
    total_base_comp = sum(m.compensation_base for m in team)
    office_rent = 250000   # annual
    data_systems = 200000  # Bloomberg, exchange fees, cloud
    legal_audit = 150000
    insurance = 80000
    misc = 100000
    fixed_costs = total_base_comp + office_rent + data_systems + legal_audit + insurance + misc

    projections = []
    for scenario_name, params in scenarios.items():
        aum_current = fund.target_aum

        for y in range(years):
            gross_ret = params["gross_return"][min(y, len(params["gross_return"]) - 1)]
            aum_growth = params["aum_growth"][min(y, len(params["aum_growth"]) - 1)]

            # AUM at start of year
            aum_start = aum_current

            # Revenue
            mgmt_fee = aum_start * fund.mgmt_fee_pct
            # Performance fee: on returns above hurdle
            excess_return = max(0, gross_ret - fund.hurdle_rate)
            perf_fee = aum_start * excess_return * fund.perf_fee_pct

            total_revenue = mgmt_fee + perf_fee

            # Costs scale with AUM (variable component)
            variable_costs = aum_start * 0.002  # 20bps for ops, clearing, data
            bonus_pool = sum(m.compensation_base * m.compensation_bonus_pct for m in team)
            # Scale bonus by performance
            bonus_factor = 1.0 if gross_ret > fund.hurdle_rate else 0.5 if gross_ret > 0 else 0.2
            total_costs = fixed_costs + variable_costs + bonus_pool * bonus_factor

            net_income = total_revenue - total_costs
            margin = net_income / total_revenue * 100 if total_revenue > 0 else -100

            # Net return to investors (after fees)
            net_return = gross_ret - fund.mgmt_fee_pct - excess_return * fund.perf_fee_pct

            # AUM at end of year (return + flows)
            aum_after_return = aum_start * (1 + net_return)
            aum_end = aum_after_return * (1 + aum_growth)
            aum_end = max(aum_end, 0)

            projections.append(FinancialProjection(
                year=y + 1,
                scenario=scenario_name,
                aum_start=round(aum_start, 0),
                aum_end=round(aum_end, 0),
                gross_return_pct=round(gross_ret * 100, 1),
                net_return_pct=round(net_return * 100, 1),
                mgmt_fee_revenue=round(mgmt_fee, 0),
                perf_fee_revenue=round(perf_fee, 0),
                total_revenue=round(total_revenue, 0),
                total_costs=round(total_costs, 0),
                net_income=round(net_income, 0),
                margin_pct=round(margin, 1),
            ))

            aum_current = aum_end

    return projections


def compute_break_even_aum(fund: FundStructure,
                             team: List[TeamMember],
                             assumed_return: float = 0.08) -> float:
    """Compute the AUM needed to break even at assumed return."""
    total_base_comp = sum(m.compensation_base for m in team)
    fixed_costs = total_base_comp + 250000 + 200000 + 150000 + 80000 + 100000  # same as above
    bonus_pool = sum(m.compensation_base * m.compensation_bonus_pct for m in team) * 0.8

    # Revenue per $1 AUM:
    # mgmt_fee + perf_fee_rate
    excess_return = max(0, assumed_return - fund.hurdle_rate)
    revenue_per_dollar = fund.mgmt_fee_pct + excess_return * fund.perf_fee_pct
    # Variable cost per $1: ~20bps
    variable_per_dollar = 0.002

    net_per_dollar = revenue_per_dollar - variable_per_dollar
    if net_per_dollar <= 0:
        return float("inf")

    break_even = (fixed_costs + bonus_pool) / net_per_dollar
    return round(break_even, 0)


# =============================================================================
# BUSINESS PLAN TEXT GENERATION
# =============================================================================

def generate_plan_text(fund: FundStructure,
                        team: List[TeamMember],
                        projections: List[FinancialProjection],
                        break_even: float,
                        dispersion_score: float = 0,
                        macro_regime: str = "MEDIUM_CORR") -> str:
    """Generate the full business plan as formatted text."""
    lines = []

    def section(title, level=1):
        if level == 1:
            lines.append("\n" + "=" * 100)
            lines.append(f"  {title}")
            lines.append("=" * 100)
        else:
            lines.append(f"\n  {title}")
            lines.append("  " + "-" * 80)

    # 1. Executive Summary
    section("1. EXECUTIVE SUMMARY")
    lines.append(f"  Fund Name:     {fund.fund_name}")
    lines.append(f"  Strategy:      European credit tranche dispersion (correlation arbitrage)")
    lines.append(f"  Universe:      iTraxx Main (125 IG names) & iTraxx Crossover (75 HY names)")
    lines.append(f"  Target AUM:    ${fund.target_aum/1e6:.0f}mm (max ${fund.max_aum/1e6:.0f}mm)")
    lines.append(f"  Target Return: 8-12% net (Sharpe 1.0-1.5)")
    lines.append(f"  Target Vol:    6-10% annualized")
    lines.append(f"  Domicile:      {fund.domicile} ({fund.vehicle})")
    lines.append(f"  Fees:          {fund.mgmt_fee_pct*100:.1f}% mgmt / {fund.perf_fee_pct*100:.0f}% perf "
                 f"(over {fund.hurdle_rate*100:.0f}% hurdle)")
    lines.append(f"  Team:          {len(team)} professionals")
    lines.append(f"  Break-even:    ${break_even/1e6:.0f}mm AUM")
    lines.append("")
    lines.append("  The fund exploits the persistent mispricing between implied correlation")
    lines.append("  (embedded in equity tranche prices) and realized correlation (observed in")
    lines.append("  constituent equity returns). This 'correlation risk premium' has been a")
    lines.append("  consistent source of alpha in European credit markets since 2004.")

    # 2. Investment Thesis
    section("2. INVESTMENT THESIS")
    lines.append("  Core Thesis:")
    lines.append("  The market systematically overprices correlation in index tranches:")
    lines.append("    - Implied correlation (from equity tranche) > realized correlation")
    lines.append("    - This gap = 'correlation risk premium' = structural alpha source")
    lines.append("    - Dispersion trades capture this premium with defined risk")
    lines.append("")
    lines.append("  Current Market Signal:")
    if dispersion_score < -0.3:
        lines.append(f"    - Dispersion signal: {dispersion_score:+.2f} (FAVORABLE for long dispersion)")
        lines.append(f"    - Macro regime: {macro_regime}")
        lines.append("    - Recommendation: Build long dispersion position in equity tranches")
    elif dispersion_score > 0.3:
        lines.append(f"    - Dispersion signal: {dispersion_score:+.2f} (FAVORABLE for short dispersion)")
        lines.append(f"    - Macro regime: {macro_regime}")
        lines.append("    - Recommendation: Build short dispersion position")
    else:
        lines.append(f"    - Dispersion signal: {dispersion_score:+.2f} (NEUTRAL)")
        lines.append(f"    - Macro regime: {macro_regime}")
        lines.append("    - Recommendation: Carry harvesting, wait for signal")
    lines.append("")
    lines.append("  Edge Sources:")
    lines.append("    1. Structural: Dealer hedging creates systematic correlation supply")
    lines.append("    2. Quantitative: Proprietary signal framework (22-module analytics)")
    lines.append("    3. Fundamental: Bottom-up single-name credit research")
    lines.append("    4. Tactical: Merton model identifies equity-credit dislocations")

    # 3. Strategy Description
    section("3. STRATEGY DESCRIPTION")
    lines.append("  Primary Strategy: Equity Tranche Dispersion")
    lines.append("    - Buy protection on equity tranche (0-3% Main, 0-10% Xover)")
    lines.append("    - Delta-hedge with index protection (sell index)")
    lines.append("    - Net position: long idiosyncratic risk, short systematic risk")
    lines.append("    - Profit when: individual names differentiate (dispersion)")
    lines.append("    - Loss when: correlation spikes (systemic event)")
    lines.append("")
    lines.append("  Secondary Strategies:")
    lines.append("    - Carry harvesting: sell index protection when signals support")
    lines.append("    - Relative value: Main vs Crossover basis trades")
    lines.append("    - Tactical: directional trades on signal extremes (+/-1.5)")
    lines.append("")
    lines.append("  Entry/Exit Framework:")
    lines.append("    - ENTER: Composite dispersion signal > |0.5| with HIGH confidence")
    lines.append("    - SIZE: 5-25% of AUM per trade, scaled by signal strength")
    lines.append("    - HEDGE: Delta-neutral (hedge ratio = tranche CS01 / index CS01)")
    lines.append("    - EXIT: Signal reversal, time decay exceeds carry, risk limit breach")
    lines.append("    - STOP: Portfolio VaR 99% > 5% AUM or worst-case stress > 15% AUM")

    # 4. Fund Structure
    section("4. FUND STRUCTURE")
    lines.append(f"  Legal Vehicle:       {fund.vehicle} ({fund.domicile})")
    lines.append(f"  Management Fee:      {fund.mgmt_fee_pct*100:.1f}% per annum (monthly accrual)")
    lines.append(f"  Performance Fee:     {fund.perf_fee_pct*100:.0f}% of profits above {fund.hurdle_rate*100:.0f}% hurdle")
    lines.append(f"  High Water Mark:     Yes (perpetual)")
    lines.append(f"  Lock-up:             {fund.lock_up_months} months (soft, 2% early redemption fee)")
    lines.append(f"  Redemption Notice:   {fund.redemption_notice_days} days")
    lines.append(f"  Min Investment:      ${fund.min_investment/1e6:.1f}mm")
    lines.append(f"  NAV Frequency:       Monthly")
    lines.append("")
    lines.append("  Service Providers:")
    lines.append(f"    Fund Admin:    {fund.fund_admin}")
    lines.append(f"    Prime Broker:  {fund.prime_broker}")
    lines.append(f"    Auditor:       {fund.auditor}")
    lines.append(f"    Legal:         {fund.legal_counsel}")

    # 5. Team
    section("5. TEAM & ORGANIZATION")
    for i, m in enumerate(team, 1):
        lines.append(f"\n  {i}. {m.title} ({m.role})")
        lines.append(f"     Compensation: ${m.compensation_base/1000:.0f}k base + "
                     f"{m.compensation_bonus_pct*100:.0f}% discretionary bonus")
        lines.append(f"     Role: {m.description}")

    total_comp = sum(m.compensation_base for m in team)
    total_bonus = sum(m.compensation_base * m.compensation_bonus_pct for m in team)
    lines.append(f"\n  Total base compensation: ${total_comp/1e6:.1f}mm")
    lines.append(f"  Total potential bonus:   ${total_bonus/1e6:.1f}mm")

    # 6. Financial Projections
    section("6. FINANCIAL PROJECTIONS (3-YEAR)")
    for scenario in ["Bull", "Base", "Bear"]:
        lines.append(f"\n  --- {scenario.upper()} CASE ---")
        scen_proj = [p for p in projections if p.scenario == scenario]
        lines.append(f"  {'Year':>6s} {'AUM Start':>12s} {'Gross Ret':>10s} {'Net Ret':>10s} "
                     f"{'Revenue':>12s} {'Costs':>12s} {'Net Income':>12s} {'Margin':>8s}")
        lines.append("  " + "-" * 90)
        for p in scen_proj:
            lines.append(f"  {p.year:>6d} ${p.aum_start/1e6:>10.0f}mm {p.gross_return_pct:>+9.1f}% "
                         f"{p.net_return_pct:>+9.1f}% ${p.total_revenue/1e6:>10.1f}mm "
                         f"${p.total_costs/1e6:>10.1f}mm ${p.net_income/1e6:>10.1f}mm "
                         f"{p.margin_pct:>+6.0f}%")

    lines.append(f"\n  Break-even AUM (at 8% gross return): ${break_even/1e6:.0f}mm")

    # 7. Risk Framework
    section("7. RISK FRAMEWORK")
    lines.append("  Risk Limits:")
    lines.append("    - Max CS01: 50bps of AUM per 1bp spread move")
    lines.append("    - Max JTD single name: 2% of AUM")
    lines.append("    - Max JTD total: 10% of AUM")
    lines.append("    - Max leverage: 10x gross/AUM")
    lines.append("    - Max VaR 99%: 5% of AUM (10-day)")
    lines.append("    - Max Rho01: 1% of AUM per 1% correlation move")
    lines.append("")
    lines.append("  Monitoring:")
    lines.append("    - Real-time portfolio risk dashboard (this system)")
    lines.append("    - Daily VaR, Greeks, JTD reporting")
    lines.append("    - Weekly stress test review")
    lines.append("    - Monthly risk committee meeting")
    lines.append("    - Independent risk review (quarterly)")
    lines.append("")
    lines.append("  Counterparty Risk:")
    lines.append("    - Dual prime broker for operational resilience")
    lines.append("    - ISDA/CSA with daily margining (VM)")
    lines.append("    - Central clearing where mandated (EMIR)")
    lines.append("    - Max 25% NAV exposure to any single counterparty")

    # 8. Regulatory
    section("8. REGULATORY & COMPLIANCE")
    if fund.domicile == "Luxembourg":
        lines.append("  AIFMD: Full-scope AIFM license (delegation to PM entity)")
        lines.append("  RAIF: Reserved Alternative Investment Fund (no CSSF product approval)")
        lines.append("  Passporting: Marketing via Annex IV reporting to EU investors")
    elif fund.domicile == "Ireland":
        lines.append("  AIFMD: Full-scope AIFM (or third-country under reverse solicitation)")
        lines.append("  QIF: Qualifying Investor Fund (min EUR 100k investment)")
    else:
        lines.append("  Offshore: Cayman SPC, marketed via reverse solicitation")

    lines.append("")
    lines.append("  ISDA/CSA Requirements:")
    lines.append("    - ISDA 2002 Master Agreement with all dealer counterparties")
    lines.append("    - CSA with daily variation margin (cash/govts)")
    lines.append("    - Initial margin: ISDA SIMM methodology")
    lines.append("")
    lines.append("  EMIR Obligations:")
    lines.append("    - iTraxx Main/Crossover indices: mandatory clearing (LCH CDSClear)")
    lines.append("    - Tranche positions: bilateral with ISDA/CSA")
    lines.append("    - Trade reporting: DTCC/Regis-TR")

    # 9. Operational Setup
    section("9. OPERATIONAL SETUP")
    lines.append("  Technology Stack:")
    lines.append("    - Analytics: Proprietary 22-module Python dashboard")
    lines.append("    - Modules: Index analysis, single-name fundamentals, alt data,")
    lines.append("               tranche pricing, dispersion signals, strategy engine,")
    lines.append("               portfolio risk, and this business plan generator")
    lines.append("    - Data Sources: FRED, ECB SDW, yFinance, Finnhub, QuantLib")
    lines.append("    - Infrastructure: AWS/Azure cloud, Flask web interface")
    lines.append("")
    lines.append("  Data Sources:")
    lines.append("    - Market data: Bloomberg Terminal + FRED (free macro)")
    lines.append("    - Credit data: Markit (CDS spreads), ECB (index levels)")
    lines.append("    - Equity data: Yahoo Finance (constituents), yfinance")
    lines.append("    - Alt data: Finnhub (insider, news), ECB BLS (lending)")
    lines.append("    - Models: Merton distance-to-default, Gaussian copula")

    # 10. Appendix
    section("10. APPENDIX")
    lines.append("  Key Assumptions:")
    lines.append("    - Correlation risk premium persists (10-year average: ~5-8% annualized)")
    lines.append("    - Market liquidity in iTraxx tranches sufficient for target AUM")
    lines.append("    - Dealer balance sheet capacity for bilateral tranche trading")
    lines.append("    - No regulatory changes restricting tranche trading")
    lines.append("")
    lines.append("  Glossary:")
    lines.append("    - Dispersion: Degree of differentiation among individual credit returns")
    lines.append("    - Base Correlation: Implied correlation from equity tranche pricing")
    lines.append("    - CS01: Dollar P&L from 1bp parallel shift in credit spreads")
    lines.append("    - Rho01: Dollar P&L from 1% absolute change in correlation")
    lines.append("    - JTD: Jump-to-default loss if a single name defaults")
    lines.append("    - Delta Ratio: Tranche CS01 / Index CS01 (hedge ratio)")
    lines.append("    - LHP: Large Homogeneous Portfolio (copula approximation)")
    lines.append("    - RAIF: Reserved Alternative Investment Fund (Luxembourg)")

    lines.append("\n" + "=" * 100)
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"  This document was generated by the Fund Business Plan module")
    lines.append(f"  of the European Credit Analytics Dashboard (22 modules)")
    lines.append("=" * 100)

    return "\n".join(lines)


# =============================================================================
# CONSOLE REPORT
# =============================================================================

def print_report(plan: BusinessPlan):
    """Print the full business plan to console."""
    print(plan.plan_text)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(plan: BusinessPlan):
    """Create business plan visualization dashboard."""
    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        f"FUND BUSINESS PLAN - {plan.fund_structure.fund_name.upper()}",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(0.5, 0.955,
             f"Generated: {plan.timestamp} | Target AUM: "
             f"${plan.fund_structure.target_aum/1e6:.0f}mm | "
             f"{plan.fund_structure.domicile} ({plan.fund_structure.vehicle})",
             ha="center", fontsize=10, color="gray")

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    projections = plan.projections

    # --- Panel 1: AUM Trajectory (3 scenarios, shaded) ---
    ax1 = fig.add_subplot(gs[0, 0:2])
    for scenario, color, ls in [("Bull", "#2ecc71", "-"), ("Base", "#3498db", "--"), ("Bear", "#e74c3c", ":")]:
        scen_proj = [p for p in projections if p.scenario == scenario]
        years = [0] + [p.year for p in scen_proj]
        aums = [plan.fund_structure.target_aum / 1e6]
        aums.extend([p.aum_end / 1e6 for p in scen_proj])
        ax1.plot(years, aums, color=color, linewidth=2, linestyle=ls, marker="o",
                 markersize=5, label=f"{scenario} case")
        # Shade between scenarios
        if scenario == "Bull":
            bull_aums = aums
        elif scenario == "Bear":
            bear_aums = aums

    if 'bull_aums' in dir() and 'bear_aums' in dir():
        ax1.fill_between(years, bear_aums, bull_aums, alpha=0.1, color="#3498db")

    ax1.axhline(plan.break_even_aum / 1e6, color="gray", linewidth=1, linestyle="--",
                label=f"Break-even (${plan.break_even_aum/1e6:.0f}mm)")
    ax1.set_xlabel("Year")
    ax1.set_ylabel("AUM ($mm)")
    ax1.legend(fontsize=8)
    ax1.set_title("AUM Trajectory (3 Scenarios)", fontweight="bold")
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(-0.1, 3.1)

    # --- Panel 2: Revenue/Cost Waterfall (Base Y1) ---
    ax2 = fig.add_subplot(gs[0, 2])
    base_y1 = [p for p in projections if p.scenario == "Base" and p.year == 1]
    if base_y1:
        p = base_y1[0]
        components = ["Mgmt Fee", "Perf Fee", "Costs", "Net Income"]
        values = [p.mgmt_fee_revenue / 1e6, p.perf_fee_revenue / 1e6,
                  -p.total_costs / 1e6, p.net_income / 1e6]
        colors = ["#2ecc71", "#3498db", "#e74c3c",
                  "#2ecc71" if p.net_income > 0 else "#e74c3c"]

        bars = ax2.bar(range(len(components)), values, color=colors, edgecolor="white")
        ax2.set_xticks(range(len(components)))
        ax2.set_xticklabels(components, fontsize=8)
        ax2.axhline(0, color="black", linewidth=0.8)
        ax2.set_ylabel("$mm")
        for i, v in enumerate(values):
            ax2.text(i, v + 0.05, f"${v:+.1f}mm", ha="center", fontsize=7)
    ax2.set_title("Revenue/Cost (Base Y1)", fontweight="bold", fontsize=10)
    ax2.grid(True, alpha=0.3, axis="y")

    # --- Panel 3: Team Cost Breakdown ---
    ax3 = fig.add_subplot(gs[1, 0])
    team = plan.team
    roles = [m.role[:12] for m in team]
    base_comps = [m.compensation_base / 1000 for m in team]
    bonus_comps = [m.compensation_base * m.compensation_bonus_pct / 1000 for m in team]

    x = np.arange(len(roles))
    width = 0.4
    ax3.barh(x - width / 2, base_comps, width, label="Base ($k)", color="#2980b9", edgecolor="white")
    ax3.barh(x + width / 2, bonus_comps, width, label="Max Bonus ($k)", color="#f39c12", edgecolor="white")
    ax3.set_yticks(x)
    ax3.set_yticklabels(roles, fontsize=7)
    ax3.set_xlabel("$k")
    ax3.legend(fontsize=7)
    ax3.invert_yaxis()
    ax3.set_title("Team Compensation", fontweight="bold", fontsize=10)
    ax3.grid(True, alpha=0.3, axis="x")

    # --- Panel 4: Risk Budget Allocation ---
    ax4 = fig.add_subplot(gs[1, 1])
    risk_categories = ["Dispersion\n(Primary)", "Carry\n(Secondary)", "Rel Value",
                        "Tactical", "Cash/Margin"]
    risk_pcts = [50, 25, 10, 10, 5]
    colors_risk = ["#e74c3c", "#2ecc71", "#3498db", "#f39c12", "#95a5a6"]
    wedges, texts, autotexts = ax4.pie(risk_pcts, labels=risk_categories,
                                         autopct="%1.0f%%", colors=colors_risk,
                                         textprops={"fontsize": 7}, startangle=90)
    for t in autotexts:
        t.set_fontsize(8)
    ax4.set_title("Risk Budget Allocation", fontweight="bold", fontsize=10)

    # --- Panel 5: Break-Even Analysis ---
    ax5 = fig.add_subplot(gs[1, 2])
    aum_range = np.linspace(20e6, 300e6, 50)
    fund = plan.fund_structure
    for ret, color, label in [(0.12, "#2ecc71", "12% gross"), (0.08, "#3498db", "8% gross"),
                               (0.04, "#f39c12", "4% gross")]:
        net_incomes = []
        for aum in aum_range:
            mgmt = aum * fund.mgmt_fee_pct
            excess = max(0, ret - fund.hurdle_rate)
            perf = aum * excess * fund.perf_fee_pct
            # Simplified costs
            total_comp = sum(m.compensation_base for m in plan.team)
            fixed = total_comp + 780000  # rent + data + legal + insurance + misc
            variable = aum * 0.002
            bonus = sum(m.compensation_base * m.compensation_bonus_pct for m in plan.team) * 0.8
            costs = fixed + variable + bonus
            net_incomes.append((mgmt + perf - costs) / 1e6)

        ax5.plot(aum_range / 1e6, net_incomes, color=color, linewidth=1.5, label=label)

    ax5.axhline(0, color="black", linewidth=1, linestyle="--")
    ax5.axvline(plan.break_even_aum / 1e6, color="gray", linewidth=1, linestyle=":",
                label=f"B/E=${plan.break_even_aum/1e6:.0f}mm")
    ax5.set_xlabel("AUM ($mm)")
    ax5.set_ylabel("Net Income ($mm)")
    ax5.legend(fontsize=7)
    ax5.set_title("Break-Even Analysis", fontweight="bold", fontsize=10)
    ax5.grid(True, alpha=0.3)

    # --- Panel 6: Historical Dispersion Strategy Returns (simulated) ---
    ax6 = fig.add_subplot(gs[2, :])
    # Simulate monthly returns of a dispersion strategy
    np.random.seed(42)
    n_months = 120  # 10 years
    dates = pd.date_range(end=datetime.now(), periods=n_months, freq="ME")

    # Dispersion strategy: positive carry with occasional drawdowns
    carry_component = np.random.normal(0.006, 0.010, n_months)  # ~7% ann with 3.5% vol
    # Add correlation spike events (2-3 times in 10 years)
    for shock_month in [15, 45, 72, 95]:
        if shock_month < n_months:
            carry_component[shock_month] = -0.08  # 8% drawdown
            carry_component[min(shock_month + 1, n_months - 1)] = -0.03
            carry_component[min(shock_month + 2, n_months - 1)] = 0.04  # recovery

    cum_returns = np.cumprod(1 + carry_component) * 100

    ax6.plot(dates, cum_returns, color="#2980b9", linewidth=1.5, label="Dispersion Strategy (simulated)")
    # Add drawdown shading
    peak = pd.Series(cum_returns).cummax()
    drawdown = (cum_returns - peak.values) / peak.values * 100
    ax6.fill_between(dates, cum_returns, peak.values, where=cum_returns < peak.values,
                      alpha=0.2, color="#e74c3c", label="Drawdown")

    # Stats box
    ann_ret = (cum_returns[-1] / 100) ** (12 / n_months) - 1
    monthly_std = np.std(carry_component)
    ann_vol = monthly_std * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    max_dd = min(drawdown)

    stats_text = (f"Ann. Return: {ann_ret*100:.1f}%\n"
                  f"Ann. Vol: {ann_vol*100:.1f}%\n"
                  f"Sharpe: {sharpe:.2f}\n"
                  f"Max DD: {max_dd:.1f}%")
    ax6.text(0.02, 0.95, stats_text, transform=ax6.transAxes, fontsize=9,
             va="top", family="monospace",
             bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    ax6.set_ylabel("Cumulative Return (indexed to 100)")
    ax6.legend(fontsize=8, loc="upper left")
    ax6.set_title("Simulated Dispersion Strategy Returns (10 Years)", fontweight="bold")
    ax6.grid(True, alpha=0.3)

    plt.savefig(str(OUTPUTS_DIR / "fund_business_plan.png"), dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: fund_business_plan.png")
    plt.close()
    return fig


# =============================================================================
# CSV EXPORT
# =============================================================================

# =============================================================================
# WORD DOCUMENT EXPORT
# =============================================================================

def export_to_docx(plan: BusinessPlan) -> str:
    """Export business plan as a professionally formatted Word document.

    Returns the file path to the generated .docx file.
    """
    try:
        from docx import Document
        from docx.shared import Inches, Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.section import WD_ORIENT
    except ImportError:
        print("  WARNING: python-docx not installed. pip install python-docx")
        return ""

    doc = Document()

    # -- Styles ---------------------------------------------------------------
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)
    font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    para_format = style.paragraph_format
    para_format.space_after = Pt(6)
    para_format.line_spacing = 1.15

    # Heading styles
    for level, (size, color) in enumerate(
        [(Pt(24), RGBColor(0x1B, 0x3A, 0x5C)),   # Heading 1: navy
         (Pt(16), RGBColor(0x1B, 0x3A, 0x5C)),   # Heading 2: navy
         (Pt(13), RGBColor(0x44, 0x72, 0xC4))],  # Heading 3: blue
        start=1,
    ):
        hs = doc.styles[f"Heading {level}"]
        hs.font.name = "Calibri Light"
        hs.font.size = size
        hs.font.color.rgb = color
        hs.font.bold = True

    navy = RGBColor(0x1B, 0x3A, 0x5C)
    dark_gray = RGBColor(0x33, 0x33, 0x33)
    light_gray = RGBColor(0x66, 0x66, 0x66)

    # -- Helper functions -----------------------------------------------------
    def add_table_with_style(headers, rows, col_widths=None):
        """Add a formatted table to the document."""
        table = doc.add_table(rows=1 + len(rows), cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Light Grid Accent 1"

        # Header row
        hdr = table.rows[0]
        for i, h in enumerate(headers):
            cell = hdr.cells[i]
            cell.text = h
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(10)

        # Data rows
        for r_idx, row_data in enumerate(rows):
            row = table.rows[r_idx + 1]
            for c_idx, val in enumerate(row_data):
                cell = row.cells[c_idx]
                cell.text = str(val)
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in cell.paragraphs[0].runs:
                    run.font.size = Pt(10)

        if col_widths:
            for i, w in enumerate(col_widths):
                for row in table.rows:
                    row.cells[i].width = Cm(w)

        doc.add_paragraph("")  # spacing after table
        return table

    # -- Title Page -----------------------------------------------------------
    for _ in range(6):
        doc.add_paragraph("")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(plan.fund_structure.fund_name.upper())
    run.font.size = Pt(32)
    run.font.color.rgb = navy
    run.bold = True

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("CONFIDENTIAL INVESTMENT MEMORANDUM")
    run.font.size = Pt(16)
    run.font.color.rgb = light_gray

    doc.add_paragraph("")

    date_para = doc.add_paragraph()
    date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = date_para.add_run(plan.timestamp)
    run.font.size = Pt(14)
    run.font.color.rgb = light_gray

    doc.add_paragraph("")
    doc.add_paragraph("")

    disclaimer = doc.add_paragraph()
    disclaimer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = disclaimer.add_run(
        "This document is strictly confidential and is intended solely for the "
        "recipient. It does not constitute an offer to sell or a solicitation of "
        "an offer to buy any securities. Past performance is not indicative of "
        "future results."
    )
    run.font.size = Pt(9)
    run.font.color.rgb = light_gray
    run.italic = True

    doc.add_page_break()

    # -- Table of Contents (static) -------------------------------------------
    doc.add_heading("TABLE OF CONTENTS", level=1)
    doc.add_paragraph("")

    toc_items = [
        "1. Executive Summary",
        "2. Investment Thesis",
        "3. Strategy Description",
        "4. Fund Structure",
        "5. Team & Organization",
        "6. Financial Projections",
        "7. Risk Framework",
        "8. Regulatory & Compliance",
        "9. Operational Setup",
        "10. Appendix",
    ]
    for item in toc_items:
        p = doc.add_paragraph(item)
        p.paragraph_format.space_after = Pt(8)
        for run in p.runs:
            run.font.size = Pt(12)
            run.font.color.rgb = navy

    doc.add_page_break()

    # -- Parse plan text into sections ----------------------------------------
    plan_text = plan.plan_text
    # Split on the section divider pattern: "===...==="
    raw_sections = plan_text.split("=" * 100)

    # Build (title, body) pairs from the raw sections
    sections = []
    for chunk in raw_sections:
        lines = chunk.strip().split("\n")
        if not lines:
            continue
        # First non-empty line after the === divider is the section title
        title_line = ""
        body_lines = []
        found_title = False
        for line in lines:
            stripped = line.strip()
            if not found_title and stripped and not stripped.startswith("-"):
                # Check if it looks like a section title (starts with number or is the generated footer)
                if (stripped and stripped[0].isdigit() and "." in stripped[:4]):
                    title_line = stripped
                    found_title = True
                elif "Generated:" in stripped or "This document was generated" in stripped:
                    # Footer section, skip
                    break
                else:
                    body_lines.append(line)
            else:
                body_lines.append(line)

        if title_line:
            sections.append((title_line, "\n".join(body_lines)))

    # -- Write sections to document -------------------------------------------
    fund = plan.fund_structure

    for sec_title, sec_body in sections:
        # Section heading
        doc.add_heading(sec_title, level=1)

        # Parse body lines and add formatted paragraphs
        body_lines = sec_body.split("\n")
        i = 0
        while i < len(body_lines):
            line = body_lines[i]
            stripped = line.strip()

            if not stripped or stripped.startswith("-" * 10):
                i += 1
                continue

            # Detect sub-headers (lines that end with : and are indented)
            if stripped.endswith(":") and len(stripped) < 60 and not stripped.startswith("-"):
                doc.add_heading(stripped, level=2)
                i += 1
                continue

            # Detect sub-sub-headers (--- BULL CASE --- etc)
            if stripped.startswith("---") and stripped.endswith("---"):
                clean = stripped.strip("-").strip()
                doc.add_heading(clean, level=3)
                i += 1
                continue

            # Detect bullet items (start with - or numbered items)
            if stripped.startswith("- ") or stripped.startswith("* "):
                p = doc.add_paragraph(stripped[2:], style="List Bullet")
                for run in p.runs:
                    run.font.size = Pt(11)
                i += 1
                continue

            # Detect numbered sub-items (e.g. "1. Structural: ...")
            if (len(stripped) > 2 and stripped[0].isdigit()
                    and stripped[1] == "." and stripped[2] == " "
                    and "EXECUTIVE" not in stripped
                    and "INVESTMENT" not in stripped
                    and "STRATEGY" not in stripped
                    and "FUND" not in stripped):
                p = doc.add_paragraph(stripped, style="List Number")
                for run in p.runs:
                    run.font.size = Pt(11)
                i += 1
                continue

            # Detect key-value pairs (e.g. "Fund Name:     value")
            if ":" in stripped and stripped.index(":") < 25:
                parts = stripped.split(":", 1)
                p = doc.add_paragraph()
                run_key = p.add_run(parts[0].strip() + ": ")
                run_key.bold = True
                run_key.font.size = Pt(11)
                run_val = p.add_run(parts[1].strip())
                run_val.font.size = Pt(11)
                i += 1
                continue

            # Column header rows (for projection tables in text)
            if "Year" in stripped and "AUM Start" in stripped:
                # Skip the text-based table header/data - we'll use a proper table
                i += 1
                continue

            # Regular paragraph
            if stripped:
                p = doc.add_paragraph(stripped)
                for run in p.runs:
                    run.font.size = Pt(11)
            i += 1

        # After Section 5 (Team), insert a proper team table
        if "5." in sec_title and "TEAM" in sec_title.upper():
            doc.add_heading("Compensation Summary", level=2)
            headers = ["Role", "Title", "Base Salary", "Bonus %", "Max Total"]
            rows = []
            for m in plan.team:
                rows.append([
                    m.role,
                    m.title,
                    f"${m.compensation_base/1000:.0f}k",
                    f"{m.compensation_bonus_pct*100:.0f}%",
                    f"${m.compensation_base*(1+m.compensation_bonus_pct)/1000:.0f}k",
                ])
            total_base = sum(m.compensation_base for m in plan.team)
            rows.append(["TOTAL", f"{len(plan.team)} members", f"${total_base/1000:.0f}k", "", ""])
            add_table_with_style(headers, rows, col_widths=[3, 5, 3, 2.5, 3])

        # After Section 6 (Projections), insert a proper projections table
        if "6." in sec_title and "PROJECTION" in sec_title.upper():
            for scenario in ["Bull", "Base", "Bear"]:
                doc.add_heading(f"{scenario} Case", level=2)
                headers = ["Year", "AUM Start", "Gross Ret", "Net Ret",
                           "Revenue", "Costs", "Net Income", "Margin"]
                rows = []
                for p in plan.projections:
                    if p.scenario == scenario:
                        rows.append([
                            str(p.year),
                            f"${p.aum_start/1e6:.0f}mm",
                            f"{p.gross_return_pct:+.1f}%",
                            f"{p.net_return_pct:+.1f}%",
                            f"${p.total_revenue/1e6:.1f}mm",
                            f"${p.total_costs/1e6:.1f}mm",
                            f"${p.net_income/1e6:.1f}mm",
                            f"{p.margin_pct:+.0f}%",
                        ])
                add_table_with_style(headers, rows,
                                     col_widths=[1.5, 2.5, 2, 2, 2.5, 2.5, 2.5, 2])

        doc.add_page_break()

    # -- Footer with page numbers ---------------------------------------------
    section = doc.sections[0]
    footer = section.footer
    footer_para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer_para.add_run("CONFIDENTIAL  |  ")
    run.font.size = Pt(8)
    run.font.color.rgb = light_gray
    run = footer_para.add_run(f"{plan.fund_structure.fund_name}")
    run.font.size = Pt(8)
    run.font.color.rgb = light_gray

    # -- Save -----------------------------------------------------------------
    docx_path = str(OUTPUTS_DIR / "fund_business_plan.docx")
    doc.save(docx_path)
    print(f"  Exported: {docx_path}")
    return docx_path


def export_csv(plan: BusinessPlan):
    """Export business plan data to CSV files."""
    # 1. Projections
    rows = []
    for p in plan.projections:
        rows.append({
            "year": p.year,
            "scenario": p.scenario,
            "aum_start": p.aum_start,
            "aum_end": p.aum_end,
            "gross_return_pct": p.gross_return_pct,
            "net_return_pct": p.net_return_pct,
            "mgmt_fee": p.mgmt_fee_revenue,
            "perf_fee": p.perf_fee_revenue,
            "total_revenue": p.total_revenue,
            "total_costs": p.total_costs,
            "net_income": p.net_income,
            "margin_pct": p.margin_pct,
        })
    pd.DataFrame(rows).to_csv(str(OUTPUTS_DIR / "fund_projections.csv"), index=False)
    print(f"  Exported: fund_projections.csv ({len(rows)} rows)")

    # 2. Team costs
    team_rows = []
    for m in plan.team:
        team_rows.append({
            "role": m.role,
            "title": m.title,
            "base_salary": m.compensation_base,
            "max_bonus_pct": m.compensation_bonus_pct * 100,
            "max_bonus": m.compensation_base * m.compensation_bonus_pct,
            "total_max_comp": m.compensation_base * (1 + m.compensation_bonus_pct),
        })
    pd.DataFrame(team_rows).to_csv(str(OUTPUTS_DIR / "fund_team_costs.csv"), index=False)
    print(f"  Exported: fund_team_costs.csv ({len(team_rows)} roles)")


# =============================================================================
# MAIN
# =============================================================================

def main(target_aum: float = DEFAULT_TARGET_AUM,
         domicile: str = DEFAULT_DOMICILE,
         mgmt_fee: float = DEFAULT_MGMT_FEE,
         perf_fee: float = DEFAULT_PERF_FEE,
         hurdle: float = DEFAULT_HURDLE,
         dispersion_score: float = -0.5,
         macro_regime: str = "LOW_CORR"):
    """Generate full business plan."""
    print("\n" + "=" * 70)
    print("  FUND BUSINESS PLAN GENERATOR")
    print("  Correlation Alpha Fund - iTraxx Tranche Dispersion")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Target AUM: ${target_aum/1e6:.0f}mm")
    print(f"  Domicile: {domicile}")

    # 1. Fund structure
    print("\n  Defining fund structure...")
    fund = define_fund_structure(target_aum, domicile, mgmt_fee, perf_fee, hurdle)
    print(f"  Vehicle: {fund.vehicle}")
    print(f"  Fees: {fund.mgmt_fee_pct*100:.1f}% / {fund.perf_fee_pct*100:.0f}% "
          f"(over {fund.hurdle_rate*100:.0f}% hurdle)")

    # 2. Team
    print("\n  Building team...")
    team = define_team(target_aum)
    print(f"  Team size: {len(team)}")
    total_comp = sum(m.compensation_base for m in team)
    print(f"  Total base compensation: ${total_comp/1e6:.1f}mm")

    # 3. Financial projections
    print("\n  Computing 3-year projections (Bull/Base/Bear)...")
    projections = compute_projections(fund, team, years=3)

    # 4. Break-even
    break_even = compute_break_even_aum(fund, team)
    print(f"  Break-even AUM: ${break_even/1e6:.0f}mm")

    # 5. Generate plan text
    print("\n  Generating business plan text...")
    plan_text = generate_plan_text(fund, team, projections, break_even,
                                    dispersion_score, macro_regime)

    plan = BusinessPlan(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        fund_structure=fund,
        team=team,
        projections=projections,
        plan_text=plan_text,
        break_even_aum=break_even,
        target_sharpe=1.2,
        target_vol=0.08,
    )

    # 6. Print report
    print_report(plan)

    # 7. Plot dashboard
    print("\n  Generating chart...")
    plot_dashboard(plan)

    # 8. Export CSVs
    print("\n  Exporting CSV data...")
    export_csv(plan)

    # 9. Export Word document
    print("\n  Generating Word document...")
    docx_path = export_to_docx(plan)
    if docx_path:
        print(f"  Word document: {docx_path}")

    print(f"\n  DONE - Business plan generated")
    print(f"  Fund: {fund.fund_name}")
    print(f"  Target AUM: ${target_aum/1e6:.0f}mm | Break-even: ${break_even/1e6:.0f}mm")

    return plan


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fund Business Plan Generator -- iTraxx tranche dispersion fund")
    parser.add_argument("--aum", type=float, default=DEFAULT_TARGET_AUM / 1e6, help="Target AUM in $mm (default: 200)")
    parser.add_argument("--domicile", default=DEFAULT_DOMICILE, help="Fund domicile (default: Cayman)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of console report")
    args = parser.parse_args()
    main(target_aum=args.aum * 1e6, domicile=args.domicile)

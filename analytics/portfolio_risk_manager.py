#!/usr/bin/env python3
"""
Portfolio Risk Manager
=======================
Aggregated risk management for an iTraxx tranche trading portfolio.
Computes total Greeks, JTD exposure, parametric VaR, stress testing,
margin estimates, and risk limit monitoring.

Capabilities:
  - Aggregate Greeks across tranche, index, and single-name positions
  - Jump-to-default (JTD) exposure per name
  - Parametric VaR (95/99) and CVaR
  - 8-scenario stress testing
  - Risk limit traffic light system
  - ISDA SIMM proxy margin estimate

Data Sources:
  - tranche_strategy_engine (active trades, Greeks)
  - cds_tranche_pricer (tranche pricing data)
  - scenario_analysis_engine (CreditPosition, scenarios)

Usage:
  python -m analytics.portfolio_risk_manager
  python -m analytics.portfolio_risk_manager --aum 100 --json
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

warnings.filterwarnings("ignore")

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs" / "risk"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_AUM = 250_000_000  # $250m — matches Brummer pitch

# Risk limits — institutional credit portfolio
RISK_LIMITS = {
    # Stop-loss cascade
    "daily_stop_loss_pct":      {"limit": 0.01,    "unit": "% of NAV",           "label": "Daily Stop-Loss",
                                 "action": "Flatten all positions; review before resuming"},
    "weekly_stop_loss_pct":     {"limit": 0.02,    "unit": "% of NAV",           "label": "Weekly Stop-Loss",
                                 "action": "50% risk reduction; regime reassessment"},
    "monthly_drawdown_pct":     {"limit": 0.035,   "unit": "% of NAV",           "label": "Monthly Drawdown",
                                 "action": "Reduce to 25% risk; CIO approval to rebuild"},
    "max_peak_to_trough_pct":   {"limit": 0.05,    "unit": "% of NAV",           "label": "Max Peak-to-Trough",
                                 "action": "Full de-risk; strategy review with risk committee"},
    # Concentration
    "max_single_name_pct":      {"limit": 0.05,    "unit": "% per name",         "label": "Single-Name Conc.",
                                 "action": "Hard limit — no exceptions"},
    # Liquidity
    "liquidity_test_pct":       {"limit": 0.90,    "unit": "% in 5 days",        "label": "Liquidity Test",
                                 "action": "Ongoing monitoring — portfolio must be liquidatable"},
    # Greeks limits (retained)
    "max_cs01_pct_aum":         {"limit": 0.005,   "unit": "% of AUM per 1bp",   "label": "Max CS01"},
    "max_jtd_single_pct":       {"limit": 0.02,    "unit": "% of AUM",           "label": "Max JTD Single Name"},
    "max_jtd_total_pct":        {"limit": 0.10,    "unit": "% of AUM",           "label": "Max JTD Total"},
    "max_leverage":             {"limit": 10.0,    "unit": "x gross/AUM",        "label": "Max Leverage"},
    "max_var99_pct":            {"limit": 0.05,    "unit": "% of AUM",           "label": "Max VaR 99%"},
    "max_rho01_pct":            {"limit": 0.01,    "unit": "% of AUM per 1%corr","label": "Max Rho01"},
}

# VaR parameters
SPREAD_VOL_DAILY = 3.0      # daily spread vol (bps)
CORR_VOL_DAILY = 0.005      # daily correlation vol (absolute)
SPREAD_CORR_CORR = 0.40     # correlation between spread and correlation risk


# Stress scenarios (same as tranche_strategy_engine)
SCENARIOS = {
    "HARD_LANDING": {
        "label": "Hard Landing", "color": "#e74c3c",
        "spread_chg_bps": +350, "corr_chg": +0.20, "defaults": 3, "vix_target": 45,
    },
    "SOFT_LANDING": {
        "label": "Soft Landing", "color": "#2ecc71",
        "spread_chg_bps": -30, "corr_chg": -0.05, "defaults": 0, "vix_target": 15,
    },
    "NO_LANDING": {
        "label": "No Landing", "color": "#f39c12",
        "spread_chg_bps": +30, "corr_chg": 0.0, "defaults": 0, "vix_target": 18,
    },
    "STAGFLATION": {
        "label": "Stagflation", "color": "#9b59b6",
        "spread_chg_bps": +250, "corr_chg": +0.15, "defaults": 2, "vix_target": 32,
    },
    "CREDIT_CRISIS": {
        "label": "Credit Crisis", "color": "#1a1a2e",
        "spread_chg_bps": +600, "corr_chg": +0.35, "defaults": 5, "vix_target": 65,
    },
    "CORRELATION_SPIKE": {
        "label": "Correlation Spike", "color": "#c0392b",
        "spread_chg_bps": +100, "corr_chg": +0.40, "defaults": 1, "vix_target": 35,
    },
    "MULTI_DEFAULT": {
        "label": "Multi Default", "color": "#2c3e50",
        "spread_chg_bps": +150, "corr_chg": +0.10, "defaults": 3, "vix_target": 38,
    },
    "SPREAD_GAMMA": {
        "label": "Spread Gamma", "color": "#e67e22",
        "spread_chg_bps": +200, "corr_chg": +0.05, "defaults": 0, "vix_target": 28,
    },
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PortfolioPosition:
    """Generic position in the risk portfolio."""
    position_id: str
    position_type: str         # "tranche", "index", "single_name"
    index_name: str            # "Main" or "Crossover"
    description: str
    notional_mm: float
    direction: float           # +1 = long risk, -1 = short risk (long protection)
    cs01_per_mm: float
    rho01_per_mm: float
    theta_daily_per_mm: float
    current_spread: float
    duration: float
    tranche_label: str = ""
    attach: float = 0
    detach: float = 0


@dataclass
class JTDExposure:
    """Jump-to-default exposure for a single name."""
    name: str
    sector: str
    rating: str
    spread_bps: float
    recovery_rate: float
    jtd_tranche_pct: float     # loss in tranche as % of tranche notional
    jtd_index_pct: float       # loss in index leg
    jtd_net_pct: float         # net JTD
    jtd_dollar: float          # net JTD in dollars
    pct_aum: float             # as % of AUM


@dataclass
class VaRResult:
    """Value-at-Risk computation result."""
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    holding_period: int
    spread_contribution: float
    corr_contribution: float
    diversification_benefit: float
    var_95_pct_aum: float
    var_99_pct_aum: float


@dataclass
class RiskLimitStatus:
    """Status of a risk limit."""
    limit_name: str
    limit_label: str
    current_value: float
    limit_value: float
    utilization_pct: float
    status: str                # "OK" / "WARNING" / "BREACH"
    unit: str


@dataclass
class PortfolioRiskReport:
    """Complete portfolio risk report."""
    timestamp: str
    aum: float
    # Aggregated Greeks
    total_cs01: float
    total_rho01: float
    total_theta_daily: float
    gross_notional: float
    net_notional: float
    leverage: float
    # Risk metrics
    var_result: VaRResult
    # Stress test
    stress_results: Dict[str, float]
    # JTD
    jtd_total: float
    jtd_worst_name: str
    jtd_worst_amount: float
    # Limits
    limit_statuses: List[RiskLimitStatus]
    n_ok: int
    n_warning: int
    n_breach: int
    # Margin
    estimated_im: float


# =============================================================================
# PORTFOLIO AGGREGATION
# =============================================================================

def aggregate_portfolio_greeks(positions: List[PortfolioPosition]) -> Dict:
    """
    Aggregate Greeks across all positions.
    Returns total CS01, Rho01, Theta, notionals by type.
    """
    total_cs01 = 0
    total_rho01 = 0
    total_theta = 0
    gross_notional = 0
    net_notional = 0

    by_type = {}
    by_index = {}

    for p in positions:
        cs01 = p.direction * p.cs01_per_mm * p.notional_mm / 1e6
        rho01 = p.direction * p.rho01_per_mm * p.notional_mm / 1e6
        theta = p.direction * p.theta_daily_per_mm * p.notional_mm / 1e6

        total_cs01 += cs01
        total_rho01 += rho01
        total_theta += theta
        gross_notional += p.notional_mm
        net_notional += p.direction * p.notional_mm

        # By type
        if p.position_type not in by_type:
            by_type[p.position_type] = {"cs01": 0, "rho01": 0, "theta": 0, "notional": 0}
        by_type[p.position_type]["cs01"] += cs01
        by_type[p.position_type]["rho01"] += rho01
        by_type[p.position_type]["theta"] += theta
        by_type[p.position_type]["notional"] += p.notional_mm

        # By index
        if p.index_name not in by_index:
            by_index[p.index_name] = {"cs01": 0, "rho01": 0, "notional": 0}
        by_index[p.index_name]["cs01"] += cs01
        by_index[p.index_name]["rho01"] += rho01
        by_index[p.index_name]["notional"] += p.notional_mm

    return {
        "total_cs01": round(total_cs01, 2),
        "total_rho01": round(total_rho01, 2),
        "total_theta": round(total_theta, 2),
        "gross_notional": round(gross_notional, 2),
        "net_notional": round(net_notional, 2),
        "by_type": by_type,
        "by_index": by_index,
    }


# =============================================================================
# JUMP-TO-DEFAULT (JTD) ANALYSIS
# =============================================================================

def compute_jtd_table(positions: List[PortfolioPosition],
                       n_names_main: int = 125,
                       n_names_xover: int = 75,
                       recovery: float = 0.40,
                       aum: float = DEFAULT_AUM) -> List[JTDExposure]:
    """
    Compute jump-to-default exposure for each name in the portfolio.
    Assumes equal-weight index/tranche exposure.
    """
    # Group tranche positions
    tranche_positions = [p for p in positions if p.position_type == "tranche"]
    index_positions = [p for p in positions if p.position_type == "index"]

    jtd_results = []

    # For synthetic demonstration, create JTD for worst-case names
    for idx_name, n_names in [("Main", n_names_main), ("Crossover", n_names_xover)]:
        lgd = 1.0 - recovery
        per_name_loss = lgd / n_names  # loss fraction per name default

        # Find tranche positions for this index
        tr_for_idx = [p for p in tranche_positions if p.index_name == idx_name]
        ix_for_idx = [p for p in index_positions if p.index_name == idx_name]

        if not tr_for_idx and not ix_for_idx:
            continue

        # Generate sample names for top 15
        sectors = ["Banks", "Insurance", "Autos", "Telecoms", "Energy",
                   "Utilities", "Industrials", "Consumer", "Healthcare", "Chemicals"]
        if idx_name == "Crossover":
            ratings = ["BB+", "BB", "BB-", "B+", "B"]
            spreads = np.random.RandomState(42).uniform(200, 600, 15)
        else:
            ratings = ["A-", "BBB+", "BBB", "BBB-"]
            spreads = np.random.RandomState(42).uniform(30, 150, 15)

        for i in range(15):
            name = f"{idx_name[:4]}_{i+1:03d}"
            sector = sectors[i % len(sectors)]
            rating = ratings[i % len(ratings)]
            spread = spreads[i]

            # Tranche JTD
            jtd_tranche_total = 0
            for tp in tr_for_idx:
                tranche_width = tp.detach - tp.attach
                if tranche_width <= 0:
                    continue
                # Does this default hit the tranche?
                if per_name_loss > tp.attach:
                    tranche_hit = min(per_name_loss, tp.detach) - tp.attach
                    tranche_loss_pct = tranche_hit / tranche_width
                    jtd_tranche_total += tp.direction * tranche_loss_pct * tp.notional_mm * 1e6

            # Index JTD
            jtd_index_total = 0
            for ip in ix_for_idx:
                index_loss = per_name_loss
                jtd_index_total += ip.direction * index_loss * ip.notional_mm * 1e6

            net_jtd = -(jtd_tranche_total + jtd_index_total)  # loss on default
            pct_aum = net_jtd / aum * 100 if aum > 0 else 0

            jtd_results.append(JTDExposure(
                name=name,
                sector=sector,
                rating=rating,
                spread_bps=round(spread, 1),
                recovery_rate=recovery,
                jtd_tranche_pct=round(jtd_tranche_total / (aum if aum > 0 else 1) * 100, 4),
                jtd_index_pct=round(jtd_index_total / (aum if aum > 0 else 1) * 100, 4),
                jtd_net_pct=round(pct_aum, 4),
                jtd_dollar=round(net_jtd, 0),
                pct_aum=round(abs(pct_aum), 4),
            ))

    # Sort by absolute JTD
    jtd_results.sort(key=lambda x: abs(x.jtd_dollar), reverse=True)
    return jtd_results


# =============================================================================
# PARAMETRIC VaR
# =============================================================================

def compute_parametric_var(total_cs01: float,
                            total_rho01: float,
                            holding_period: int = 10,
                            confidence_95: float = 1.645,
                            confidence_99: float = 2.326,
                            spread_vol: float = SPREAD_VOL_DAILY,
                            corr_vol: float = CORR_VOL_DAILY,
                            cross_corr: float = SPREAD_CORR_CORR,
                            aum: float = DEFAULT_AUM) -> VaRResult:
    """
    Compute parametric VaR using spread and correlation risk factors.

    VaR = sqrt(hp) * sqrt(sigma_spread^2 * CS01^2 + sigma_corr^2 * Rho01^2
                          + 2 * rho * sigma_spread * sigma_corr * CS01 * Rho01)
    """
    hp_sqrt = np.sqrt(holding_period)

    # Scale Greeks to dollar terms
    # CS01: total $ P&L per 1bp spread move
    # Rho01: total $ P&L per 1% absolute correlation move
    spread_risk = abs(total_cs01) * spread_vol  # daily spread risk ($)
    corr_risk = abs(total_rho01) * corr_vol * 100  # daily corr risk ($) (corr_vol is per 1abs, Rho01 is per 1%)

    # Combined variance with correlation
    variance = (spread_risk ** 2 + corr_risk ** 2 +
                2 * cross_corr * spread_risk * corr_risk)
    daily_vol = np.sqrt(max(0, variance))

    # Undiversified (sum of standalone)
    undiversified = spread_risk + corr_risk
    diversification = 1 - (daily_vol / undiversified) if undiversified > 0 else 0

    # VaR
    var_95 = daily_vol * hp_sqrt * confidence_95
    var_99 = daily_vol * hp_sqrt * confidence_99

    # CVaR (expected shortfall) - approximate for normal distribution
    # E[X | X > VaR] = mu + sigma * phi(z) / (1 - Phi(z))
    cvar_factor_95 = stats.norm.pdf(confidence_95) / (1 - 0.95)
    cvar_factor_99 = stats.norm.pdf(confidence_99) / (1 - 0.99)
    cvar_95 = daily_vol * hp_sqrt * cvar_factor_95
    cvar_99 = daily_vol * hp_sqrt * cvar_factor_99

    return VaRResult(
        var_95=round(var_95, 0),
        var_99=round(var_99, 0),
        cvar_95=round(cvar_95, 0),
        cvar_99=round(cvar_99, 0),
        holding_period=holding_period,
        spread_contribution=round(spread_risk * hp_sqrt * confidence_99, 0),
        corr_contribution=round(corr_risk * hp_sqrt * confidence_99, 0),
        diversification_benefit=round(diversification * 100, 1),
        var_95_pct_aum=round(var_95 / aum * 100, 3) if aum > 0 else 0,
        var_99_pct_aum=round(var_99 / aum * 100, 3) if aum > 0 else 0,
    )


# =============================================================================
# STRESS TESTING
# =============================================================================

def stress_test_portfolio(positions: List[PortfolioPosition],
                           scenarios: Dict = None,
                           aum: float = DEFAULT_AUM) -> Dict[str, Dict]:
    """
    Stress test the entire portfolio under 8 scenarios.
    """
    if scenarios is None:
        scenarios = SCENARIOS

    results = {}
    for name, s in scenarios.items():
        spread_chg = s["spread_chg_bps"]
        corr_chg = s["corr_chg"]
        n_defaults = s["defaults"]

        total_spread_pnl = 0
        total_corr_pnl = 0
        total_default_pnl = 0

        for p in positions:
            # Spread P&L
            if p.position_type == "tranche":
                # Tranche spread moves more (leverage via delta)
                effective_spread_chg = spread_chg * (p.cs01_per_mm / 450)  # normalize
            else:
                effective_spread_chg = spread_chg

            spread_pnl = p.direction * effective_spread_chg * p.cs01_per_mm * p.notional_mm / 1e6
            total_spread_pnl += spread_pnl

            # Correlation P&L (tranche only)
            corr_pnl = p.direction * corr_chg * 100 * p.rho01_per_mm * p.notional_mm / 1e6
            total_corr_pnl += corr_pnl

            # Default P&L
            if n_defaults > 0 and p.position_type in ("tranche", "index"):
                n_names = 125 if p.index_name == "Main" else 75
                per_default = 0.60 / n_names
                cum_loss = per_default * n_defaults

                if p.position_type == "tranche":
                    tranche_width = p.detach - p.attach
                    if tranche_width > 0 and cum_loss > p.attach:
                        tranche_hit = min(cum_loss, p.detach) - p.attach
                        loss_pct = tranche_hit / tranche_width
                        total_default_pnl += -p.direction * loss_pct * p.notional_mm * 1e6
                else:
                    total_default_pnl += -p.direction * cum_loss * p.notional_mm * 1e6

        net_pnl = total_spread_pnl + total_corr_pnl + total_default_pnl
        results[name] = {
            "label": s["label"],
            "spread_pnl": round(total_spread_pnl, 0),
            "corr_pnl": round(total_corr_pnl, 0),
            "default_pnl": round(total_default_pnl, 0),
            "net_pnl": round(net_pnl, 0),
            "pct_aum": round(net_pnl / aum * 100, 2) if aum > 0 else 0,
        }

    return results


# =============================================================================
# RISK LIMITS
# =============================================================================

def check_risk_limits(greeks: Dict,
                       var_result: VaRResult,
                       jtd_table: List[JTDExposure],
                       aum: float = DEFAULT_AUM) -> List[RiskLimitStatus]:
    """
    Check all risk limits and return traffic-light status.
    """
    statuses = []

    # 1. Max CS01
    cs01_pct = abs(greeks["total_cs01"]) / aum if aum > 0 else 0
    limit = RISK_LIMITS["max_cs01_pct_aum"]
    util = cs01_pct / limit["limit"] * 100 if limit["limit"] > 0 else 0
    status = "OK" if util < 80 else "WARNING" if util < 100 else "BREACH"
    statuses.append(RiskLimitStatus(
        limit_name="max_cs01_pct_aum", limit_label=limit["label"],
        current_value=cs01_pct, limit_value=limit["limit"],
        utilization_pct=round(util, 1), status=status, unit=limit["unit"],
    ))

    # 2. Max JTD single name
    worst_jtd = max(jtd_table, key=lambda x: abs(x.pct_aum)) if jtd_table else None
    worst_pct = worst_jtd.pct_aum / 100 if worst_jtd else 0
    limit = RISK_LIMITS["max_jtd_single_pct"]
    util = worst_pct / limit["limit"] * 100 if limit["limit"] > 0 else 0
    status = "OK" if util < 80 else "WARNING" if util < 100 else "BREACH"
    statuses.append(RiskLimitStatus(
        limit_name="max_jtd_single_pct", limit_label=limit["label"],
        current_value=worst_pct, limit_value=limit["limit"],
        utilization_pct=round(util, 1), status=status, unit=limit["unit"],
    ))

    # 3. Max JTD total
    total_jtd = sum(abs(j.jtd_dollar) for j in jtd_table) / aum if aum > 0 else 0
    limit = RISK_LIMITS["max_jtd_total_pct"]
    util = total_jtd / limit["limit"] * 100 if limit["limit"] > 0 else 0
    status = "OK" if util < 80 else "WARNING" if util < 100 else "BREACH"
    statuses.append(RiskLimitStatus(
        limit_name="max_jtd_total_pct", limit_label=limit["label"],
        current_value=total_jtd, limit_value=limit["limit"],
        utilization_pct=round(util, 1), status=status, unit=limit["unit"],
    ))

    # 4. Max leverage
    leverage = greeks["gross_notional"] / (aum / 1e6) if aum > 0 else 0
    limit = RISK_LIMITS["max_leverage"]
    util = leverage / limit["limit"] * 100 if limit["limit"] > 0 else 0
    status = "OK" if util < 80 else "WARNING" if util < 100 else "BREACH"
    statuses.append(RiskLimitStatus(
        limit_name="max_leverage", limit_label=limit["label"],
        current_value=leverage, limit_value=limit["limit"],
        utilization_pct=round(util, 1), status=status, unit=limit["unit"],
    ))

    # 5. Max VaR 99%
    var_pct = var_result.var_99 / aum if aum > 0 else 0
    limit = RISK_LIMITS["max_var99_pct"]
    util = var_pct / limit["limit"] * 100 if limit["limit"] > 0 else 0
    status = "OK" if util < 80 else "WARNING" if util < 100 else "BREACH"
    statuses.append(RiskLimitStatus(
        limit_name="max_var99_pct", limit_label=limit["label"],
        current_value=var_pct, limit_value=limit["limit"],
        utilization_pct=round(util, 1), status=status, unit=limit["unit"],
    ))

    # 6. Max Rho01
    rho_pct = abs(greeks["total_rho01"]) / aum if aum > 0 else 0
    limit = RISK_LIMITS["max_rho01_pct"]
    util = rho_pct / limit["limit"] * 100 if limit["limit"] > 0 else 0
    status = "OK" if util < 80 else "WARNING" if util < 100 else "BREACH"
    statuses.append(RiskLimitStatus(
        limit_name="max_rho01_pct", limit_label=limit["label"],
        current_value=rho_pct, limit_value=limit["limit"],
        utilization_pct=round(util, 1), status=status, unit=limit["unit"],
    ))

    return statuses


def estimate_initial_margin(positions: List[PortfolioPosition]) -> float:
    """
    Estimate ISDA SIMM-like initial margin.
    Simplified: IM ~ 5% of gross notional for index positions,
                     15% for tranche positions (higher margin requirement).
    """
    total_im = 0
    for p in positions:
        if p.position_type == "tranche":
            total_im += p.notional_mm * 0.15 * 1e6  # 15% of notional
        else:
            total_im += p.notional_mm * 0.05 * 1e6  # 5% of notional

    return round(total_im, 0)


# =============================================================================
# SAMPLE PORTFOLIO
# =============================================================================

def create_sample_portfolio() -> List[PortfolioPosition]:
    """Create sample portfolio with tranche and index positions."""
    positions = [
        # Long dispersion on Crossover: buy equity tranche prot + sell index prot
        PortfolioPosition(
            position_id="XOVER_EQ_LONG_PROT",
            position_type="tranche",
            index_name="Crossover",
            description="Crossover 0-10% equity tranche (long protection)",
            notional_mm=15.0,
            direction=-1.0,  # long protection = short risk
            cs01_per_mm=4200,
            rho01_per_mm=-6500,
            theta_daily_per_mm=-25,
            current_spread=2800,
            duration=4.5,
            tranche_label="0-10%",
            attach=0.0,
            detach=0.10,
        ),
        PortfolioPosition(
            position_id="XOVER_IDX_SHORT_PROT",
            position_type="index",
            index_name="Crossover",
            description="Crossover index (short protection = sell index)",
            notional_mm=140.0,
            direction=1.0,  # short protection = long risk
            cs01_per_mm=450,
            rho01_per_mm=0,
            theta_daily_per_mm=0,
            current_spread=300,
            duration=4.5,
        ),
        # Long dispersion on Main: buy equity tranche prot + sell index prot
        PortfolioPosition(
            position_id="MAIN_EQ_LONG_PROT",
            position_type="tranche",
            index_name="Main",
            description="Main 0-3% equity tranche (long protection)",
            notional_mm=15.0,
            direction=-1.0,
            cs01_per_mm=5500,
            rho01_per_mm=-8750,
            theta_daily_per_mm=-30,
            current_spread=1300,
            duration=4.5,
            tranche_label="0-3%",
            attach=0.0,
            detach=0.03,
        ),
        PortfolioPosition(
            position_id="MAIN_IDX_SHORT_PROT",
            position_type="index",
            index_name="Main",
            description="Main index (short protection = sell index)",
            notional_mm=183.0,
            direction=1.0,
            cs01_per_mm=450,
            rho01_per_mm=0,
            theta_daily_per_mm=0,
            current_spread=55,
            duration=4.8,
        ),
        # Outright Crossover index protection
        PortfolioPosition(
            position_id="XOVER_DIR_LONG",
            position_type="index",
            index_name="Crossover",
            description="Crossover outright (short protection, carry trade)",
            notional_mm=50.0,
            direction=1.0,
            cs01_per_mm=450,
            rho01_per_mm=0,
            theta_daily_per_mm=0,
            current_spread=300,
            duration=4.5,
        ),
    ]
    return positions


# =============================================================================
# BUILD FULL RISK REPORT
# =============================================================================

def build_risk_report(positions: List[PortfolioPosition],
                       aum: float = DEFAULT_AUM,
                       holding_period: int = 10) -> PortfolioRiskReport:
    """Build complete portfolio risk report."""
    # 1. Aggregate Greeks
    greeks = aggregate_portfolio_greeks(positions)

    # 2. JTD table
    jtd_table = compute_jtd_table(positions, aum=aum)

    # 3. VaR
    var_result = compute_parametric_var(
        greeks["total_cs01"], greeks["total_rho01"],
        holding_period=holding_period, aum=aum,
    )

    # 4. Stress test
    stress_results = stress_test_portfolio(positions, aum=aum)

    # 5. Risk limits
    limit_statuses = check_risk_limits(greeks, var_result, jtd_table, aum)

    # 6. Margin
    estimated_im = estimate_initial_margin(positions)

    # Summary
    leverage = greeks["gross_notional"] / (aum / 1e6) if aum > 0 else 0
    worst_jtd = max(jtd_table, key=lambda x: abs(x.jtd_dollar)) if jtd_table else None
    n_ok = sum(1 for s in limit_statuses if s.status == "OK")
    n_warning = sum(1 for s in limit_statuses if s.status == "WARNING")
    n_breach = sum(1 for s in limit_statuses if s.status == "BREACH")

    return PortfolioRiskReport(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        aum=aum,
        total_cs01=greeks["total_cs01"],
        total_rho01=greeks["total_rho01"],
        total_theta_daily=greeks["total_theta"],
        gross_notional=greeks["gross_notional"],
        net_notional=greeks["net_notional"],
        leverage=round(leverage, 2),
        var_result=var_result,
        stress_results=stress_results,
        jtd_total=sum(abs(j.jtd_dollar) for j in jtd_table),
        jtd_worst_name=worst_jtd.name if worst_jtd else "N/A",
        jtd_worst_amount=worst_jtd.jtd_dollar if worst_jtd else 0,
        limit_statuses=limit_statuses,
        n_ok=n_ok,
        n_warning=n_warning,
        n_breach=n_breach,
        estimated_im=estimated_im,
    )


# =============================================================================
# CONSOLE REPORT
# =============================================================================

def print_report(report: PortfolioRiskReport,
                  positions: List[PortfolioPosition],
                  jtd_table: List[JTDExposure]):
    """Print formatted risk report."""
    aum = report.aum
    aum_mm = aum / 1e6

    print("\n" + "=" * 110)
    print("  PORTFOLIO RISK MANAGER")
    print("=" * 110)
    print(f"  Generated: {report.timestamp}")
    print(f"  AUM: ${aum_mm:.0f}mm")

    # 1. Portfolio summary
    print(f"\n{'=' * 110}")
    print("  1. PORTFOLIO SUMMARY")
    print(f"{'=' * 110}")
    print(f"  Gross notional:   ${report.gross_notional:.1f}mm")
    print(f"  Net notional:     ${report.net_notional:+.1f}mm")
    print(f"  Leverage:         {report.leverage:.1f}x AUM")
    print(f"  Positions:        {len(positions)}")
    print(f"  Estimated IM:     ${report.estimated_im/1e6:.1f}mm ({report.estimated_im/aum*100:.1f}% of AUM)")

    # Position detail
    print(f"\n  {'ID':<25s} {'Type':<10s} {'Index':<10s} {'Notional':>10s} {'Dir':>5s} {'CS01/mm':>9s}")
    print("  " + "-" * 80)
    for p in positions:
        d = "Long" if p.direction > 0 else "Short"
        print(f"  {p.position_id:<25s} {p.position_type:<10s} {p.index_name:<10s} "
              f"${p.notional_mm:>8.1f}mm {d:>5s} {p.cs01_per_mm:>8.0f}")

    # 2. Aggregated Greeks
    print(f"\n{'=' * 110}")
    print("  2. AGGREGATED GREEKS")
    print(f"{'=' * 110}")
    print(f"  Total CS01:    ${report.total_cs01:>+12,.0f}  (P&L per 1bp parallel spread move)")
    print(f"  Total Rho01:   ${report.total_rho01:>+12,.0f}  (P&L per 1% absolute corr move)")
    print(f"  Total Theta:   ${report.total_theta_daily:>+12,.0f}/day  (time decay)")

    greeks = aggregate_portfolio_greeks(positions)
    print(f"\n  By position type:")
    for ptype, g in greeks["by_type"].items():
        print(f"    {ptype:<10s}: CS01=${g['cs01']:>+10,.0f}  Rho01=${g['rho01']:>+10,.0f}  "
              f"Notional=${g['notional']:>.1f}mm")

    # 3. JTD table
    print(f"\n{'=' * 110}")
    print("  3. JUMP-TO-DEFAULT EXPOSURE (Top 15)")
    print(f"{'=' * 110}")
    print(f"  {'Name':<15s} {'Sector':<12s} {'Rating':>6s} {'Spread':>8s} "
          f"{'JTD $':>12s} {'% AUM':>7s}")
    print("  " + "-" * 65)
    for j in jtd_table[:15]:
        print(f"  {j.name:<15s} {j.sector:<12s} {j.rating:>6s} {j.spread_bps:>7.1f} "
              f"${j.jtd_dollar:>+10,.0f} {j.pct_aum:>6.3f}%")
    print(f"\n  Total JTD exposure: ${report.jtd_total:,.0f}")
    print(f"  Worst single name: {report.jtd_worst_name} (${report.jtd_worst_amount:+,.0f})")

    # 4. VaR
    vr = report.var_result
    print(f"\n{'=' * 110}")
    print(f"  4. VALUE-AT-RISK ({vr.holding_period}-day holding period)")
    print(f"{'=' * 110}")
    print(f"  VaR 95%:  ${vr.var_95:>12,.0f}  ({vr.var_95_pct_aum:.3f}% of AUM)")
    print(f"  VaR 99%:  ${vr.var_99:>12,.0f}  ({vr.var_99_pct_aum:.3f}% of AUM)")
    print(f"  CVaR 95%: ${vr.cvar_95:>12,.0f}")
    print(f"  CVaR 99%: ${vr.cvar_99:>12,.0f}")
    print(f"\n  Contribution by factor:")
    print(f"    Spread risk:  ${vr.spread_contribution:>12,.0f}")
    print(f"    Corr risk:    ${vr.corr_contribution:>12,.0f}")
    print(f"    Diversification benefit: {vr.diversification_benefit:.1f}%")

    # 5. Stress test
    print(f"\n{'=' * 110}")
    print("  5. STRESS TEST (8 SCENARIOS)")
    print(f"{'=' * 110}")
    print(f"  {'Scenario':<20s} {'Net P&L':>14s} {'% AUM':>8s} {'Spread':>12s} "
          f"{'Corr':>12s} {'Default':>12s}")
    print("  " + "-" * 85)
    for name, r in report.stress_results.items():
        pnl_str = f"${r['net_pnl']/1e6:+.2f}mm" if abs(r["net_pnl"]) > 1e6 else f"${r['net_pnl']:>+10,.0f}"
        print(f"  {r['label']:<20s} {pnl_str:>14s} {r['pct_aum']:>+7.2f}% "
              f"${r['spread_pnl']:>+10,.0f} ${r['corr_pnl']:>+10,.0f} "
              f"${r['default_pnl']:>+10,.0f}")

    # 6. Risk limits
    print(f"\n{'=' * 110}")
    print("  6. RISK LIMITS")
    print(f"{'=' * 110}")
    for ls in report.limit_statuses:
        icon = "[OK]" if ls.status == "OK" else "[!!]" if ls.status == "WARNING" else "[XX]"
        print(f"  {icon} {ls.limit_label:<25s} | Current: {ls.current_value:.6f} | "
              f"Limit: {ls.limit_value:.4f} | Util: {ls.utilization_pct:.0f}% | {ls.status}")

    print(f"\n  Summary: {report.n_ok} OK, {report.n_warning} WARNING, {report.n_breach} BREACH")

    print("\n" + "=" * 110)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(report: PortfolioRiskReport,
                    positions: List[PortfolioPosition],
                    jtd_table: List[JTDExposure]):
    """Create portfolio risk dashboard."""
    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "PORTFOLIO RISK MANAGER",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(0.5, 0.955,
             f"Generated: {report.timestamp} | AUM: ${report.aum/1e6:.0f}mm | "
             f"Leverage: {report.leverage:.1f}x",
             ha="center", fontsize=10, color="gray")

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # --- Panel 1: Greeks Decomposition ---
    ax1 = fig.add_subplot(gs[0, 0])
    greeks = aggregate_portfolio_greeks(positions)
    types = list(greeks["by_type"].keys())
    cs01_vals = [greeks["by_type"][t]["cs01"] for t in types]
    rho01_vals = [greeks["by_type"][t]["rho01"] for t in types]

    x = np.arange(len(types))
    width = 0.35
    ax1.bar(x - width / 2, cs01_vals, width, label="CS01", color="#2980b9", edgecolor="white")
    ax1.bar(x + width / 2, rho01_vals, width, label="Rho01", color="#8e44ad", edgecolor="white")
    ax1.set_xticks(x)
    ax1.set_xticklabels(types, fontsize=8)
    ax1.axhline(0, color="black", linewidth=0.8)
    ax1.legend(fontsize=7)
    ax1.set_ylabel("$ per 1bp/1%")
    ax1.set_title("Greeks by Position Type", fontweight="bold", fontsize=10)
    ax1.grid(True, alpha=0.3, axis="y")

    # --- Panel 2: Risk Limits Traffic Light ---
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.axis("off")
    ax2.set_title("Risk Limits", fontweight="bold", fontsize=10)

    y_pos = 0.92
    for ls in report.limit_statuses:
        if ls.status == "OK":
            color = "#2ecc71"
            icon = "OK"
        elif ls.status == "WARNING":
            color = "#f39c12"
            icon = "!!"
        else:
            color = "#e74c3c"
            icon = "XX"

        # Draw bar
        bar_width = min(ls.utilization_pct / 100, 1.5)
        ax2.barh(y_pos, bar_width, height=0.08, color=color, alpha=0.7,
                 transform=ax2.transAxes)
        ax2.text(0.02, y_pos, f"[{icon}] {ls.limit_label}", transform=ax2.transAxes,
                 fontsize=7, va="center", fontweight="bold")
        ax2.text(0.85, y_pos, f"{ls.utilization_pct:.0f}%", transform=ax2.transAxes,
                 fontsize=7, va="center", color=color, fontweight="bold")
        y_pos -= 0.14

    # Summary at bottom
    ax2.text(0.5, 0.05, f"{report.n_ok} OK | {report.n_warning} WARN | {report.n_breach} BREACH",
             transform=ax2.transAxes, ha="center", fontsize=9, fontweight="bold")

    # --- Panel 3: JTD Waterfall (Top 10) ---
    ax3 = fig.add_subplot(gs[0, 2])
    if jtd_table:
        top_jtd = jtd_table[:10]
        names = [j.name[:12] for j in top_jtd]
        amounts = [j.jtd_dollar for j in top_jtd]
        colors = ["#e74c3c" if a > 0 else "#2ecc71" for a in amounts]
        ax3.barh(range(len(names)), amounts, color=colors, edgecolor="white")
        ax3.set_yticks(range(len(names)))
        ax3.set_yticklabels(names, fontsize=7)
        ax3.axvline(0, color="black", linewidth=0.8)
        ax3.set_xlabel("JTD ($)")
        ax3.invert_yaxis()
    ax3.set_title("JTD Exposure (Top 10 Names)", fontweight="bold", fontsize=10)
    ax3.grid(True, alpha=0.3, axis="x")

    # --- Panel 4: VaR Visualization ---
    ax4 = fig.add_subplot(gs[1, 0])
    vr = report.var_result
    metrics = ["VaR 95%", "VaR 99%", "CVaR 95%", "CVaR 99%"]
    values = [vr.var_95, vr.var_99, vr.cvar_95, vr.cvar_99]
    colors_var = ["#3498db", "#2980b9", "#e74c3c", "#c0392b"]
    ax4.bar(range(len(metrics)), values, color=colors_var, edgecolor="white")
    ax4.set_xticks(range(len(metrics)))
    ax4.set_xticklabels(metrics, fontsize=8)
    ax4.set_ylabel("$ at Risk")
    for i, v in enumerate(values):
        ax4.text(i, v + max(values) * 0.02, f"${v:,.0f}", ha="center", fontsize=6)
    ax4.set_title(f"VaR ({vr.holding_period}-day)", fontweight="bold", fontsize=10)
    ax4.grid(True, alpha=0.3, axis="y")

    # --- Panel 5: Stress Test P&L ---
    ax5 = fig.add_subplot(gs[1, 1:])
    sr = report.stress_results
    scenario_names = [sr[k]["label"][:15] for k in sr]
    net_pnls = [sr[k]["net_pnl"] for k in sr]
    spread_pnls = [sr[k]["spread_pnl"] for k in sr]
    corr_pnls = [sr[k]["corr_pnl"] for k in sr]
    default_pnls = [sr[k]["default_pnl"] for k in sr]

    x = np.arange(len(scenario_names))
    width = 0.22
    ax5.bar(x - 1.5 * width, spread_pnls, width, label="Spread", color="#2980b9", edgecolor="white")
    ax5.bar(x - 0.5 * width, corr_pnls, width, label="Correlation", color="#8e44ad", edgecolor="white")
    ax5.bar(x + 0.5 * width, default_pnls, width, label="Default", color="#e74c3c", edgecolor="white")
    ax5.bar(x + 1.5 * width, net_pnls, width, label="Net", color="#2c3e50", edgecolor="white")
    ax5.set_xticks(x)
    ax5.set_xticklabels(scenario_names, fontsize=7, rotation=30, ha="right")
    ax5.axhline(0, color="black", linewidth=0.8)
    ax5.legend(fontsize=7)
    ax5.set_ylabel("P&L ($)")
    ax5.set_title("Stress Test P&L Decomposition", fontweight="bold", fontsize=10)
    ax5.grid(True, alpha=0.3, axis="y")

    # --- Panel 6: Exposure Breakdown Pie ---
    ax6 = fig.add_subplot(gs[2, 0])
    by_type = greeks["by_type"]
    labels = list(by_type.keys())
    sizes = [by_type[t]["notional"] for t in labels]
    colors_pie = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6"][:len(labels)]
    ax6.pie(sizes, labels=labels, autopct="%1.0f%%", colors=colors_pie,
            textprops={"fontsize": 8}, startangle=90)
    ax6.set_title("Notional by Position Type", fontweight="bold", fontsize=10)

    # --- Panel 7: Margin Utilization ---
    ax7 = fig.add_subplot(gs[2, 1])
    im = report.estimated_im
    aum_val = report.aum
    margin_pct = im / aum_val * 100 if aum_val > 0 else 0
    available = aum_val - im

    ax7.barh(["Initial Margin", "Available"], [im, available],
             color=["#e74c3c", "#2ecc71"], edgecolor="white")
    ax7.set_xlabel("$ Amount")
    for i, (v, label) in enumerate(zip([im, available], ["IM", "Avail"])):
        ax7.text(v / 2, i, f"${v/1e6:.1f}mm ({v/aum_val*100:.0f}%)",
                 ha="center", va="center", fontsize=8, fontweight="bold")
    ax7.set_title("Margin Utilization", fontweight="bold", fontsize=10)

    # --- Panel 8: Position Summary Table ---
    ax8 = fig.add_subplot(gs[2, 2])
    ax8.axis("off")
    ax8.set_title("Portfolio Summary", fontweight="bold", fontsize=10)

    summary_lines = [
        f"AUM:           ${aum_val/1e6:.0f}mm",
        f"Gross Notional: ${report.gross_notional:.0f}mm",
        f"Leverage:       {report.leverage:.1f}x",
        f"Net CS01:       ${report.total_cs01:+,.0f}",
        f"Net Rho01:      ${report.total_rho01:+,.0f}",
        f"Net Theta/day:  ${report.total_theta_daily:+,.0f}",
        f"VaR 99% (10d):  ${vr.var_99:,.0f} ({vr.var_99_pct_aum:.2f}%)",
        f"Est. IM:        ${im/1e6:.1f}mm ({margin_pct:.0f}%)",
        f"Positions:      {len(positions)}",
        f"Limits:         {report.n_ok}OK/{report.n_warning}WARN/{report.n_breach}BREACH",
    ]
    y_pos = 0.92
    for line in summary_lines:
        ax8.text(0.05, y_pos, line, transform=ax8.transAxes, fontsize=8,
                 family="monospace", va="top")
        y_pos -= 0.09

    plt.savefig(str(OUTPUTS_DIR / "portfolio_risk_manager.png"), dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: portfolio_risk_manager.png")
    plt.close()
    return fig


# =============================================================================
# CSV EXPORT
# =============================================================================

def export_csv(report: PortfolioRiskReport,
                positions: List[PortfolioPosition],
                jtd_table: List[JTDExposure]):
    """Export risk data to CSV files."""
    # 1. Portfolio risk summary
    rows = [{
        "timestamp": report.timestamp,
        "aum": report.aum,
        "gross_notional_mm": report.gross_notional,
        "leverage": report.leverage,
        "total_cs01": report.total_cs01,
        "total_rho01": report.total_rho01,
        "total_theta_daily": report.total_theta_daily,
        "var_95": report.var_result.var_95,
        "var_99": report.var_result.var_99,
        "cvar_99": report.var_result.cvar_99,
        "estimated_im": report.estimated_im,
        "n_limits_ok": report.n_ok,
        "n_limits_warning": report.n_warning,
        "n_limits_breach": report.n_breach,
    }]
    pd.DataFrame(rows).to_csv(str(OUTPUTS_DIR / "portfolio_risk_summary.csv"), index=False)
    print(f"  Exported: portfolio_risk_summary.csv")

    # 2. JTD table
    jtd_rows = [{
        "name": j.name,
        "sector": j.sector,
        "rating": j.rating,
        "spread_bps": j.spread_bps,
        "jtd_dollar": j.jtd_dollar,
        "pct_aum": j.pct_aum,
    } for j in jtd_table]
    pd.DataFrame(jtd_rows).to_csv(str(OUTPUTS_DIR / "jtd_table.csv"), index=False)
    print(f"  Exported: jtd_table.csv ({len(jtd_rows)} names)")

    # 3. Stress test
    stress_rows = []
    for name, r in report.stress_results.items():
        stress_rows.append({
            "scenario": r["label"],
            "net_pnl": r["net_pnl"],
            "pct_aum": r["pct_aum"],
            "spread_pnl": r["spread_pnl"],
            "corr_pnl": r["corr_pnl"],
            "default_pnl": r["default_pnl"],
        })
    pd.DataFrame(stress_rows).to_csv(str(OUTPUTS_DIR / "portfolio_stress_test.csv"), index=False)
    print(f"  Exported: portfolio_stress_test.csv ({len(stress_rows)} scenarios)")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run portfolio risk manager with sample portfolio."""
    print("\n" + "=" * 70)
    print("  PORTFOLIO RISK MANAGER")
    print("  iTraxx Tranche Portfolio Risk Analytics")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  AUM: ${DEFAULT_AUM/1e6:.0f}mm")

    # 1. Create sample portfolio
    print("\n  Building sample portfolio...")
    positions = create_sample_portfolio()
    print(f"  Positions: {len(positions)}")
    for p in positions:
        d = "Long" if p.direction > 0 else "Short"
        print(f"    {p.position_id}: {p.description[:40]} | ${p.notional_mm:.0f}mm {d}")

    # 2. Build risk report
    print("\n  Computing risk metrics...")
    report = build_risk_report(positions, aum=DEFAULT_AUM, holding_period=10)
    jtd_table = compute_jtd_table(positions, aum=DEFAULT_AUM)

    # 3. Print report
    print_report(report, positions, jtd_table)

    # 4. Plot dashboard
    print("\n  Generating chart...")
    plot_dashboard(report, positions, jtd_table)

    # 5. Export CSVs
    print("\n  Exporting CSV data...")
    export_csv(report, positions, jtd_table)

    print(f"\n  DONE - Portfolio risk analysis complete")
    print(f"  Leverage: {report.leverage:.1f}x | VaR99: ${report.var_result.var_99:,.0f}")
    print(f"  Limits: {report.n_ok} OK, {report.n_warning} WARNING, {report.n_breach} BREACH")

    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Portfolio Risk Manager -- iTraxx tranche portfolio risk analytics")
    parser.add_argument("--aum", type=float, default=DEFAULT_AUM / 1e6, help="AUM in $mm (default: 100)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of console report")
    args = parser.parse_args()
    main()

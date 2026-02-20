"""
Standalone Risk Metrics Calculator — Strategies in Credit

Comprehensive risk metrics for any single name or the full portfolio:

    Single-Name:
        DV01, CS01, JTD, RPV01, Points Upfront, 5Y/1Y PD
        Spread VaR (1-day 95% and 99%, parametric)
        Expected Shortfall (CVaR)

    Portfolio:
        Aggregate DV01, CS01, JTD (gross/net)
        Spread VaR (95%, 99%) — parametric, assuming normal daily moves
        Expected Shortfall (CVaR 95%, 99%)
        Concentration risk (HHI by name, sector, rating)
        Portfolio Greeks summary (delta, gamma, theta, carry)
        Largest 5 risk contributors

Usage:
    python -m analytics.risk_metrics --name "INEOS Finance PLC"
    python -m analytics.risk_metrics --portfolio
    python -m analytics.risk_metrics --portfolio --json
    python -m analytics.risk_metrics --portfolio --detail
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev

import numpy as np
from scipy import stats as sp_stats

from analytics.cds_pricer import (
    cds_dv01,
    cds_cs01,
    jump_to_default,
    implied_default_probability,
    spread_to_upfront,
    _risky_annuity,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NAV_MILLIONS = 500.0
ISDA_RECOVERY = 0.40
TRADING_DAYS_PER_YEAR = 252
CONFIDENCE_95 = sp_stats.norm.ppf(0.95)   # 1.6449
CONFIDENCE_99 = sp_stats.norm.ppf(0.99)   # 2.3263

# Daily spread vol assumptions by rating bucket (bps)
# Calibrated to typical European HY CDS daily moves
DAILY_VOL_BY_RATING = {
    "IG":  1.5,
    "BB+": 2.0,
    "BB":  3.0,
    "B":   5.0,
    "B-":  8.0,
    "CCC": 15.0,
}

# Rating bucket thresholds (consistent with codebase)
RATING_BUCKETS = [
    ("IG",   0,    150),
    ("BB",   150,  300),
    ("B",    300,  500),
    ("B-",   500,  800),
    ("CCC",  800,  9999),
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class NameRiskMetrics:
    """Comprehensive risk metrics for a single CDS name."""
    entity_name: str
    direction: str                   # LONG_RISK / SHORT_RISK
    notional_m: float                # Millions
    current_spread: float            # bps
    fair_spread: float               # bps
    sector: str
    implied_rating: str
    conviction: int

    # CDS analytics
    dv01: float = 0.0               # Dollar DV01 (absolute)
    signed_dv01: float = 0.0        # Signed (+ = gains on widening)
    cs01: float = 0.0               # Credit spread sensitivity
    jtd: float = 0.0                # Jump-to-default P&L
    rpv01: float = 0.0              # Risky PV01 (years)
    points_upfront: float = 0.0     # Points upfront (%)
    pd_5y: float = 0.0              # 5-year cumulative default prob
    pd_1y: float = 0.0              # 1-year default prob (approx)

    # VaR & CVaR (1-day, in USD)
    daily_vol_bps: float = 0.0      # Assumed daily spread vol
    var_95: float = 0.0             # 1-day 95% VaR ($)
    var_99: float = 0.0             # 1-day 99% VaR ($)
    cvar_95: float = 0.0            # Expected Shortfall 95% ($)
    cvar_99: float = 0.0            # Expected Shortfall 99% ($)

    # Carry
    annual_carry: float = 0.0       # $ per year (+ = receive, - = pay)


@dataclass
class ConcentrationMetrics:
    """Portfolio concentration analysis."""
    hhi_name: float = 0.0           # Herfindahl by name (0-10000)
    hhi_sector: float = 0.0         # Herfindahl by sector
    hhi_rating: float = 0.0         # Herfindahl by rating
    hhi_interpretation: str = ""    # LOW, MODERATE, HIGH
    largest_position_pct: float = 0.0
    top5_concentration_pct: float = 0.0
    sector_breakdown: dict = field(default_factory=dict)
    rating_breakdown: dict = field(default_factory=dict)


@dataclass
class PortfolioGreeks:
    """Portfolio-level Greeks summary."""
    delta: float = 0.0              # $ DV01 (net spread sensitivity)
    gamma: float = 0.0              # Change in DV01 per 10bp move
    theta: float = 0.0              # Daily time decay (carry / 252)
    vega: float = 0.0               # Sensitivity to vol change


@dataclass
class PortfolioRiskMetrics:
    """Full portfolio risk dashboard."""
    report_date: str = ""
    nav_millions: float = NAV_MILLIONS
    position_count: int = 0

    # Aggregate CDS metrics
    gross_dv01: float = 0.0
    net_dv01: float = 0.0
    gross_cs01: float = 0.0
    net_cs01: float = 0.0
    gross_jtd: float = 0.0
    net_jtd: float = 0.0
    long_jtd: float = 0.0
    short_jtd: float = 0.0

    # VaR & CVaR (1-day, portfolio level, $)
    var_95: float = 0.0
    var_99: float = 0.0
    cvar_95: float = 0.0
    cvar_99: float = 0.0

    # VaR as bps of NAV
    var_95_bps: float = 0.0
    var_99_bps: float = 0.0

    # Concentration
    concentration: ConcentrationMetrics = field(default_factory=ConcentrationMetrics)

    # Greeks
    greeks: PortfolioGreeks = field(default_factory=PortfolioGreeks)

    # Carry
    gross_carry: float = 0.0        # Absolute carry $
    net_carry: float = 0.0          # Net carry $

    # Per-name breakdown
    positions: list = field(default_factory=list)
    top5_risk: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rating classification
# ---------------------------------------------------------------------------

def classify_rating(spread: float) -> str:
    """Classify into rating bucket by spread."""
    for rating, low, high in RATING_BUCKETS:
        if low <= spread < high:
            return rating
    return "CCC"


def get_daily_vol(rating: str) -> float:
    """Get assumed daily spread vol for a rating bucket."""
    return DAILY_VOL_BY_RATING.get(rating, 5.0)


# ---------------------------------------------------------------------------
# Single-name risk computation
# ---------------------------------------------------------------------------

def compute_name_risk(
    entity_name: str,
    current_spread: float,
    fair_spread: float,
    direction: str,
    notional_m: float,
    sector: str = "",
    conviction: int = 3,
) -> NameRiskMetrics:
    """Compute comprehensive risk metrics for a single name."""

    notional = notional_m * 1_000_000
    is_prot_buyer = direction == "SHORT_RISK"
    implied_rating = classify_rating(current_spread)

    # CDS pricer
    dv01 = cds_dv01(current_spread, notional=notional) if current_spread > 0 else 0.0
    cs01 = cds_cs01(current_spread, notional=notional) if current_spread > 0 else 0.0
    jtd = jump_to_default(
        current_spread, notional=notional, is_protection_buyer=is_prot_buyer
    ) if current_spread > 0 else 0.0
    rpv01 = _risky_annuity(current_spread) if current_spread > 0 else 0.0
    pu = spread_to_upfront(current_spread) if current_spread > 0 else 0.0
    pd_5y = implied_default_probability(current_spread) if current_spread > 0 else 0.0

    # 1-year PD (simple approximation)
    if current_spread > 0:
        h = (current_spread / 10_000) / (1 - ISDA_RECOVERY)
        pd_1y = 1 - math.exp(-h)
    else:
        pd_1y = 0.0

    # Signed DV01
    signed_dv01 = dv01 if is_prot_buyer else -dv01

    # Daily vol & VaR
    daily_vol = get_daily_vol(implied_rating)

    # Parametric VaR: VaR = DV01 * z * daily_vol
    var_95 = abs(dv01) * CONFIDENCE_95 * daily_vol
    var_99 = abs(dv01) * CONFIDENCE_99 * daily_vol

    # CVaR (Expected Shortfall) for normal distribution
    # ES_alpha = DV01 * sigma * phi(z_alpha) / (1 - alpha)
    phi_95 = sp_stats.norm.pdf(CONFIDENCE_95)
    phi_99 = sp_stats.norm.pdf(CONFIDENCE_99)
    cvar_95 = abs(dv01) * daily_vol * phi_95 / 0.05
    cvar_99 = abs(dv01) * daily_vol * phi_99 / 0.01

    # Carry
    annual_carry = notional * current_spread / 10_000
    if is_prot_buyer:
        annual_carry = -annual_carry

    return NameRiskMetrics(
        entity_name=entity_name,
        direction=direction,
        notional_m=notional_m,
        current_spread=current_spread,
        fair_spread=fair_spread,
        sector=sector,
        implied_rating=implied_rating,
        conviction=conviction,
        dv01=round(dv01, 2),
        signed_dv01=round(signed_dv01, 2),
        cs01=round(cs01, 2),
        jtd=round(jtd, 0),
        rpv01=round(rpv01, 3),
        points_upfront=round(pu, 2),
        pd_5y=round(pd_5y, 4),
        pd_1y=round(pd_1y, 4),
        daily_vol_bps=round(daily_vol, 1),
        var_95=round(var_95, 0),
        var_99=round(var_99, 0),
        cvar_95=round(cvar_95, 0),
        cvar_99=round(cvar_99, 0),
        annual_carry=round(annual_carry, 0),
    )


# ---------------------------------------------------------------------------
# Portfolio risk computation
# ---------------------------------------------------------------------------

def load_portfolio() -> dict | None:
    """Load latest portfolio JSON."""
    portfolio_dir = Path("outputs/portfolio")
    if not portfolio_dir.exists():
        return None
    candidates = sorted(
        portfolio_dir.glob("portfolio_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    with open(candidates[0]) as f:
        return json.load(f)


def load_sector_mapping() -> dict[str, str]:
    """Load entity -> sector from xover_s44.json."""
    path = "indices/xover_s44.json"
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    mapping = {}
    for sector, names in data.get("sectors", {}).items():
        for name in names:
            mapping[name] = sector
    return mapping


def compute_concentration(positions: list[NameRiskMetrics], nav: float) -> ConcentrationMetrics:
    """Compute portfolio concentration metrics."""
    if not positions:
        return ConcentrationMetrics()

    total_gross = sum(abs(p.notional_m) for p in positions)

    # HHI by name (sum of squared weight percentages)
    name_weights = [(abs(p.notional_m) / total_gross * 100) for p in positions]
    hhi_name = sum(w**2 for w in name_weights)

    # HHI by sector
    sector_notional: dict[str, float] = {}
    for p in positions:
        sector_notional[p.sector] = sector_notional.get(p.sector, 0) + abs(p.notional_m)
    sector_weights = [(v / total_gross * 100) for v in sector_notional.values()]
    hhi_sector = sum(w**2 for w in sector_weights)

    # HHI by rating
    rating_notional: dict[str, float] = {}
    for p in positions:
        rating_notional[p.implied_rating] = rating_notional.get(
            p.implied_rating, 0
        ) + abs(p.notional_m)
    rating_weights = [(v / total_gross * 100) for v in rating_notional.values()]
    hhi_rating = sum(w**2 for w in rating_weights)

    # Interpretation
    if hhi_name > 3000:
        interp = "HIGH"
    elif hhi_name > 1500:
        interp = "MODERATE"
    else:
        interp = "LOW"

    # Top position & top 5
    sorted_weights = sorted(name_weights, reverse=True)
    largest = sorted_weights[0] if sorted_weights else 0
    top5 = sum(sorted_weights[:5])

    # Breakdowns as %
    sector_bd = {k: round(v / total_gross * 100, 1) for k, v in
                 sorted(sector_notional.items(), key=lambda x: -x[1])}
    rating_bd = {k: round(v / total_gross * 100, 1) for k, v in
                 sorted(rating_notional.items(), key=lambda x: -x[1])}

    return ConcentrationMetrics(
        hhi_name=round(hhi_name, 0),
        hhi_sector=round(hhi_sector, 0),
        hhi_rating=round(hhi_rating, 0),
        hhi_interpretation=interp,
        largest_position_pct=round(largest, 1),
        top5_concentration_pct=round(top5, 1),
        sector_breakdown=sector_bd,
        rating_breakdown=rating_bd,
    )


def compute_portfolio_greeks(
    positions: list[NameRiskMetrics],
    nav: float,
) -> PortfolioGreeks:
    """Compute portfolio-level Greeks.

    Delta:  Net DV01 ($ change per 1bp move)
    Gamma:  Change in DV01 for a 10bp parallel shift (convexity)
    Theta:  Daily carry (net carry / 252)
    Vega:   Sensitivity to volatility (sum of VaR contributions)
    """
    # Delta = sum of signed DV01
    delta = sum(p.signed_dv01 for p in positions)

    # Gamma: approximate by bumping spreads +10bp and re-computing DV01
    bumped_dv01_sum = 0.0
    for p in positions:
        bumped_spread = p.current_spread + 10
        bumped_dv01 = cds_dv01(bumped_spread, notional=p.notional_m * 1_000_000)
        sign = 1 if p.direction == "SHORT_RISK" else -1
        bumped_dv01_sum += sign * bumped_dv01

    gamma = (bumped_dv01_sum - delta) / 10  # Per bp

    # Theta: daily carry
    net_carry = sum(p.annual_carry for p in positions)
    theta = net_carry / TRADING_DAYS_PER_YEAR

    # Vega: sum of individual VaRs (approximation)
    vega = sum(p.var_95 for p in positions)

    return PortfolioGreeks(
        delta=round(delta, 2),
        gamma=round(gamma, 2),
        theta=round(theta, 0),
        vega=round(vega, 0),
    )


def compute_portfolio_var(
    positions: list[NameRiskMetrics],
    correlation: float = 0.3,
) -> tuple[float, float, float, float]:
    """Compute portfolio VaR assuming pairwise correlation between names.

    Uses parametric normal VaR with a constant correlation assumption.

    Var_portfolio^2 = sum_i(VaR_i^2) + 2 * rho * sum_{i<j}(VaR_i * VaR_j)

    Returns (var_95, var_99, cvar_95, cvar_99) in USD.
    """
    n = len(positions)
    if n == 0:
        return 0, 0, 0, 0

    # Individual 1-day VaRs (directional: DV01 * z * vol)
    individual_vars_95 = []
    individual_vars_99 = []

    for p in positions:
        # Use signed DV01 so direction is preserved
        var_95 = abs(p.signed_dv01) * CONFIDENCE_95 * p.daily_vol_bps
        var_99 = abs(p.signed_dv01) * CONFIDENCE_99 * p.daily_vol_bps
        individual_vars_95.append(var_95)
        individual_vars_99.append(var_99)

    # Portfolio VaR with correlation
    # Var_p^2 = sum(Vi^2) + 2*rho*sum_{i<j}(Vi*Vj)
    def portfolio_var(indiv):
        sum_sq = sum(v**2 for v in indiv)
        cross = 0.0
        for i in range(len(indiv)):
            for j in range(i + 1, len(indiv)):
                cross += indiv[i] * indiv[j]
        return math.sqrt(sum_sq + 2 * correlation * cross)

    pvar_95 = portfolio_var(individual_vars_95)
    pvar_99 = portfolio_var(individual_vars_99)

    # CVaR (scaled from VaR)
    phi_95 = sp_stats.norm.pdf(CONFIDENCE_95)
    phi_99 = sp_stats.norm.pdf(CONFIDENCE_99)
    pcvar_95 = pvar_95 * phi_95 / (0.05 * CONFIDENCE_95)
    pcvar_99 = pvar_99 * phi_99 / (0.01 * CONFIDENCE_99)

    return round(pvar_95, 0), round(pvar_99, 0), round(pcvar_95, 0), round(pcvar_99, 0)


def compute_portfolio_risk(portfolio: dict = None) -> PortfolioRiskMetrics:
    """Compute full portfolio risk dashboard."""

    if not portfolio:
        portfolio = load_portfolio()
    if not portfolio:
        return PortfolioRiskMetrics(report_date=datetime.now().strftime("%Y-%m-%d"))

    nav = portfolio.get("nav_millions", NAV_MILLIONS)
    nav_usd = nav * 1_000_000
    sector_map = load_sector_mapping()

    # Compute per-name risk
    name_risks: list[NameRiskMetrics] = []
    for p in portfolio.get("top_positions", []):
        sector = p.get("sector", sector_map.get(p["entity_name"], "Unknown"))
        risk = compute_name_risk(
            entity_name=p["entity_name"],
            current_spread=p["current_spread"],
            fair_spread=p.get("fair_spread", 0),
            direction=p["direction"],
            notional_m=p.get("notional_millions", 10),
            sector=sector,
            conviction=p.get("conviction", 3),
        )
        name_risks.append(risk)

    # Aggregates
    gross_dv01 = sum(abs(p.dv01) for p in name_risks)
    net_dv01 = sum(p.signed_dv01 for p in name_risks)
    gross_cs01 = sum(abs(p.cs01) for p in name_risks)
    net_cs01 = net_dv01  # Same for single-name CDS
    gross_jtd = sum(abs(p.jtd) for p in name_risks)

    long_jtd = sum(p.jtd for p in name_risks if p.direction == "LONG_RISK")
    short_jtd = sum(p.jtd for p in name_risks if p.direction == "SHORT_RISK")
    net_jtd = long_jtd + short_jtd

    # Portfolio VaR
    var_95, var_99, cvar_95, cvar_99 = compute_portfolio_var(name_risks)

    # Concentration
    concentration = compute_concentration(name_risks, nav)

    # Greeks
    greeks = compute_portfolio_greeks(name_risks, nav)

    # Carry
    gross_carry = sum(abs(p.annual_carry) for p in name_risks)
    net_carry = sum(p.annual_carry for p in name_risks)

    # Top 5 risk contributors (by VaR)
    sorted_by_var = sorted(name_risks, key=lambda p: -p.var_99)
    top5 = [
        {
            "entity_name": p.entity_name,
            "direction": p.direction,
            "var_99": p.var_99,
            "dv01": p.dv01,
            "jtd": p.jtd,
            "spread": p.current_spread,
        }
        for p in sorted_by_var[:5]
    ]

    return PortfolioRiskMetrics(
        report_date=datetime.now().strftime("%Y-%m-%d"),
        nav_millions=nav,
        position_count=len(name_risks),
        gross_dv01=round(gross_dv01, 0),
        net_dv01=round(net_dv01, 0),
        gross_cs01=round(gross_cs01, 0),
        net_cs01=round(net_cs01, 0),
        gross_jtd=round(gross_jtd, 0),
        net_jtd=round(net_jtd, 0),
        long_jtd=round(long_jtd, 0),
        short_jtd=round(short_jtd, 0),
        var_95=round(var_95, 0),
        var_99=round(var_99, 0),
        cvar_95=round(cvar_95, 0),
        cvar_99=round(cvar_99, 0),
        var_95_bps=round(var_95 / nav_usd * 10000, 2),
        var_99_bps=round(var_99 / nav_usd * 10000, 2),
        concentration=concentration,
        greeks=greeks,
        gross_carry=round(gross_carry, 0),
        net_carry=round(net_carry, 0),
        positions=[asdict(p) for p in name_risks],
        top5_risk=top5,
    )


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def print_name_risk(risk: NameRiskMetrics) -> None:
    """Print single-name risk metrics."""
    W = 72
    dir_tag = "SHORT" if risk.direction == "SHORT_RISK" else "LONG"
    stars = "*" * risk.conviction

    print()
    print("=" * W)
    print(f"  RISK METRICS: {risk.entity_name}")
    print(f"  {dir_tag} {stars} ({risk.conviction}/5)  |  "
          f"{risk.sector}  |  {risk.implied_rating}")
    print("=" * W)

    print()
    print("  CDS ANALYTICS")
    print("  " + "-" * 45)
    print(f"  Current Spread:    {risk.current_spread:>8.0f} bp")
    print(f"  Fair Spread:       {risk.fair_spread:>8.0f} bp")
    print(f"  Points Upfront:    {risk.points_upfront:>+8.2f}%")
    print(f"  RPV01:             {risk.rpv01:>8.3f} y")
    print(f"  Notional:          ${risk.notional_m:>7.1f}M")

    print()
    print("  RISK SENSITIVITIES")
    print("  " + "-" * 45)
    print(f"  DV01:              ${risk.dv01:>10,.0f}")
    print(f"  Signed DV01:       ${risk.signed_dv01:>+10,.0f}")
    print(f"  CS01:              ${risk.cs01:>10,.0f}")
    print(f"  JTD:               ${risk.jtd:>10,.0f}")

    print()
    print("  DEFAULT PROBABILITY")
    print("  " + "-" * 45)
    print(f"  5Y Cumulative PD:  {risk.pd_5y * 100:>8.1f}%")
    print(f"  1Y Annualised PD:  {risk.pd_1y * 100:>8.2f}%")

    print()
    print("  VALUE AT RISK (1-Day, Parametric)")
    print("  " + "-" * 45)
    print(f"  Daily Spread Vol:  {risk.daily_vol_bps:>8.1f} bp")
    print(f"  VaR (95%):         ${risk.var_95:>10,.0f}")
    print(f"  VaR (99%):         ${risk.var_99:>10,.0f}")
    print(f"  CVaR (95%):        ${risk.cvar_95:>10,.0f}")
    print(f"  CVaR (99%):        ${risk.cvar_99:>10,.0f}")

    print()
    print("  CARRY")
    print("  " + "-" * 45)
    carry_label = "Premium Cost" if risk.direction == "SHORT_RISK" else "Carry Income"
    print(f"  {carry_label}:  ${risk.annual_carry:>+10,.0f}/yr")
    print(f"  Daily Carry:       ${risk.annual_carry / 252:>+10,.0f}/day")

    print()
    print("=" * W)


def print_portfolio_risk(metrics: PortfolioRiskMetrics, detail: bool = False) -> None:
    """Print portfolio risk dashboard."""
    W = 72
    nav_usd = metrics.nav_millions * 1_000_000

    print()
    print("=" * W)
    print("  STRATEGIES IN CREDIT — Portfolio Risk Dashboard")
    print(f"  {metrics.report_date}  |  NAV: ${metrics.nav_millions:.0f}M  |  "
          f"{metrics.position_count} positions")
    print("=" * W)

    # Aggregate sensitivities
    print()
    print("  AGGREGATE SENSITIVITIES")
    print("  " + "-" * 50)
    print(f"  {'':>20} {'Gross':>12} {'Net':>12}")
    print(f"  {'DV01':>20} ${metrics.gross_dv01:>11,.0f} ${metrics.net_dv01:>+11,.0f}")
    print(f"  {'CS01':>20} ${metrics.gross_cs01:>11,.0f} ${metrics.net_cs01:>+11,.0f}")
    print(f"  {'JTD':>20} ${metrics.gross_jtd:>11,.0f} ${metrics.net_jtd:>+11,.0f}")
    print(f"  {'JTD (Long)':>20} ${metrics.long_jtd:>+11,.0f}")
    print(f"  {'JTD (Short)':>20} ${metrics.short_jtd:>+11,.0f}")

    # VaR
    print()
    print("  VALUE AT RISK (1-Day, Parametric, rho=0.30)")
    print("  " + "-" * 50)
    print(f"  VaR (95%):         ${metrics.var_95:>10,.0f}  "
          f"({metrics.var_95_bps:.2f} bp NAV)")
    print(f"  VaR (99%):         ${metrics.var_99:>10,.0f}  "
          f"({metrics.var_99_bps:.2f} bp NAV)")
    print(f"  CVaR (95%):        ${metrics.cvar_95:>10,.0f}")
    print(f"  CVaR (99%):        ${metrics.cvar_99:>10,.0f}")

    # Greeks
    g = metrics.greeks
    print()
    print("  PORTFOLIO GREEKS")
    print("  " + "-" * 50)
    print(f"  Delta (Net DV01):  ${g.delta:>+10,.0f}/bp")
    print(f"  Gamma (Convexity): ${g.gamma:>+10,.2f}/bp^2")
    print(f"  Theta (Daily Carry):${g.theta:>+10,.0f}/day")
    print(f"  Vega (Vol Sens):   ${g.vega:>10,.0f}")

    # Carry
    print()
    print("  CARRY ANALYSIS")
    print("  " + "-" * 50)
    print(f"  Gross Carry:       ${metrics.gross_carry:>10,.0f}/yr")
    print(f"  Net Carry:         ${metrics.net_carry:>+10,.0f}/yr")
    print(f"  Net Carry (bps):   {metrics.net_carry / nav_usd * 10000:>+8.1f} bp/yr")

    # Concentration
    c = metrics.concentration
    print()
    print("  CONCENTRATION RISK")
    print("  " + "-" * 50)
    print(f"  HHI (Name):        {c.hhi_name:>8,.0f}  ({c.hhi_interpretation})")
    print(f"  HHI (Sector):      {c.hhi_sector:>8,.0f}")
    print(f"  HHI (Rating):      {c.hhi_rating:>8,.0f}")
    print(f"  Largest Position:  {c.largest_position_pct:>7.1f}%")
    print(f"  Top 5 Conc:        {c.top5_concentration_pct:>7.1f}%")

    if c.sector_breakdown:
        print(f"\n  Sector Breakdown:")
        for sector, pct in c.sector_breakdown.items():
            bar_len = int(pct / 2)
            print(f"    {sector:<22} {pct:>5.1f}%  {'#' * bar_len}")

    if c.rating_breakdown:
        print(f"\n  Rating Breakdown:")
        for rating, pct in c.rating_breakdown.items():
            bar_len = int(pct / 2)
            print(f"    {rating:<22} {pct:>5.1f}%  {'#' * bar_len}")

    # Top 5 risk contributors
    print()
    print("  TOP 5 RISK CONTRIBUTORS (by 99% VaR)")
    print("  " + "-" * 50)
    print(f"  {'Entity':<28} {'Dir':>5} {'VaR99':>10} {'DV01':>8} {'Spread':>7}")
    for t in metrics.top5_risk:
        dir_tag = "S" if t["direction"] == "SHORT_RISK" else "L"
        print(f"  {t['entity_name'][:27]:<28} {dir_tag:>5} "
              f"${t['var_99']:>9,.0f} ${t['dv01']:>7,.0f} "
              f"{t['spread']:>6.0f}")

    if detail:
        print()
        print("  FULL POSITION DETAIL")
        print("  " + "-" * 60)
        print(f"  {'Entity':<25} {'Dir':>3} {'DV01':>8} {'JTD':>9} "
              f"{'VaR99':>8} {'Carry':>9} {'PD5Y':>6}")

        for p in sorted(metrics.positions, key=lambda x: -abs(x.get("var_99", 0))):
            d = "S" if p["direction"] == "SHORT_RISK" else "L"
            print(f"  {p['entity_name'][:24]:<25} {d:>3} "
                  f"${p['dv01']:>7,.0f} ${p['jtd']:>8,.0f} "
                  f"${p['var_99']:>7,.0f} ${p['annual_carry']:>+8,.0f} "
                  f"{p['pd_5y'] * 100:>5.1f}%")

    print()
    print("=" * W)


# ---------------------------------------------------------------------------
# Data loading for --name mode
# ---------------------------------------------------------------------------

def find_name_in_portfolio(name: str) -> dict | None:
    """Find a name in the portfolio (fuzzy match)."""
    portfolio = load_portfolio()
    if not portfolio:
        return None
    target = name.lower()
    for p in portfolio.get("top_positions", []):
        if p["entity_name"].lower() == target:
            return p
    # Fuzzy
    for p in portfolio.get("top_positions", []):
        if target in p["entity_name"].lower():
            return p
    return None


def find_name_in_screen(name: str) -> dict | None:
    """Find a name in the xover_screen Excel."""
    from openpyxl import load_workbook as lwb
    screen_path = None
    output_dir = Path("outputs")
    if output_dir.exists():
        candidates = sorted(
            output_dir.glob("xover_screen_*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            screen_path = str(candidates[0])

    if not screen_path:
        return None

    sector_map = load_sector_mapping()
    wb = lwb(screen_path, read_only=True, data_only=True)
    ws = wb["Screen Results"]

    target = name.lower()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        entity = str(row[0])
        if target in entity.lower():
            spread = float(row[4]) if row[4] else 0.0
            fair = float(row[5]) if row[5] else 0.0
            direction = str(row[1]) if row[1] else "FLAT"
            conviction = int(row[2]) if row[2] else 3
            wb.close()
            return {
                "entity_name": entity,
                "current_spread": spread,
                "fair_spread": fair,
                "direction": direction,
                "conviction": conviction,
                "sector": sector_map.get(entity, "Unknown"),
                "notional_millions": 10.0,
            }

    wb.close()
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Strategies in Credit — Standalone Risk Metrics Calculator"
    )
    parser.add_argument("--name", type=str, default=None,
                        help='Entity name (e.g., "INEOS Finance PLC")')
    parser.add_argument("--portfolio", action="store_true",
                        help="Compute full portfolio risk")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--detail", action="store_true",
                        help="Show detailed position breakdown")
    args = parser.parse_args()

    if args.name:
        # Single-name mode
        pos = find_name_in_portfolio(args.name)
        if not pos:
            pos = find_name_in_screen(args.name)
        if not pos:
            print(f"ERROR: No data found for '{args.name}'")
            print("  Try: python -m analytics.risk_metrics --portfolio")
            sys.exit(1)

        sector_map = load_sector_mapping()
        risk = compute_name_risk(
            entity_name=pos["entity_name"],
            current_spread=pos["current_spread"],
            fair_spread=pos.get("fair_spread", 0),
            direction=pos["direction"],
            notional_m=pos.get("notional_millions", 10),
            sector=pos.get("sector", sector_map.get(pos["entity_name"], "Unknown")),
            conviction=pos.get("conviction", 3),
        )

        if args.json:
            print(json.dumps(asdict(risk), indent=2, default=str))
        else:
            print_name_risk(risk)

    elif args.portfolio:
        metrics = compute_portfolio_risk()
        if metrics.position_count == 0:
            print("ERROR: No portfolio found. Run: python -m agents.strategist")
            sys.exit(1)

        if args.json:
            print(json.dumps(asdict(metrics), indent=2, default=str))
        else:
            print_portfolio_risk(metrics, detail=args.detail)

    else:
        parser.print_help()
        print("\nExamples:")
        print('  python -m analytics.risk_metrics --name "INEOS Finance PLC"')
        print("  python -m analytics.risk_metrics --portfolio")
        print("  python -m analytics.risk_metrics --portfolio --detail")
        sys.exit(0)


if __name__ == "__main__":
    main()

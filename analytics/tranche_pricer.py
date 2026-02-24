"""
Gaussian Copula Tranche Pricer — Full-Fat Engine
=================================================

One-factor Gaussian copula model for pricing standard CDO tranches on
iTraxx Main and Crossover indices. Combines:

  1. Gauss-Hermite quadrature integration (50 points, more accurate)
  2. Large Homogeneous Portfolio (LHP) fast path (for scenario tables)
  3. Heterogeneous portfolio pricing (per-name PD/LGD/weight vectors)
  4. CDS curve bootstrapping from Merton-implied spreads
  5. ECB Statistical Data Warehouse integration for live index levels
  6. Full Greeks: CS01, CS02, Rho01, Theta, Recovery01, JTD
  7. Base correlation calibration & parametric smile
  8. Strategy P&L scenario analysis

The model:
    asset_i = sqrt(rho) * M  +  sqrt(1 - rho) * epsilon_i
    where M ~ N(0,1) is the systematic factor, epsilon_i ~ N(0,1) idiosyncratic.
    Default if asset_i < Phi^{-1}(PD_i).

Standard tranche structures:
    iTraxx Main S44:      0-3% equity, 3-6% mezz, 6-12% senior, 12-100% super senior
    iTraxx Crossover S44: 0-10% equity (upfront+500bp running), 10-20% mezz, 20-35% senior, 35-100% super sr

Usage:
    python -m analytics.tranche_pricer --index-spread 350
    python -m analytics.tranche_pricer --strategy
    python -m analytics.tranche_pricer --calibrate --equity-upfront 35
    python -m analytics.tranche_pricer --full-report
    python -m analytics.tranche_pricer --help

References:
    Li, D.X. (2000) "On Default Correlation: A Copula Function Approach"
    O'Kane, D. (2008) "Modelling Single-name and Multi-name Credit Derivatives"
"""

import argparse
import json
import math
import os
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import integrate, optimize
from scipy.stats import norm

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.patches import FancyBboxPatch
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    import QuantLib as ql
    HAS_QUANTLIB = True
except ImportError:
    HAS_QUANTLIB = False


# ===========================================================================
# Constants
# ===========================================================================

ISDA_RECOVERY = 0.40
RISK_FREE_RATE = 0.03
N_NAMES_MAIN = 125       # iTraxx Main S44
N_NAMES_XOVER = 75       # iTraxx Crossover S44
STANDARD_COUPON = 500     # HY equity tranche running coupon (bps)
N_QUADRATURE = 50         # Gauss-Hermite quadrature points
MATURITY_YEARS = 5.0

# Standard iTraxx Xover tranche structure (backward compat)
STANDARD_TRANCHES = {
    "equity":      {"attachment": 0.00, "detachment": 0.10, "coupon_bps": 500,  "traded_upfront": True},
    "mezzanine":   {"attachment": 0.10, "detachment": 0.20, "coupon_bps": 0,    "traded_upfront": False},
    "senior":      {"attachment": 0.20, "detachment": 0.35, "coupon_bps": 0,    "traded_upfront": False},
    "super_senior": {"attachment": 0.35, "detachment": 1.00, "coupon_bps": 0,   "traded_upfront": False},
}

# iTraxx Main S44 standard tranche structure
MAIN_TRANCHES = [
    {"label": "0-3%",    "attach": 0.00, "detach": 0.03},
    {"label": "3-6%",    "attach": 0.03, "detach": 0.06},
    {"label": "6-12%",   "attach": 0.06, "detach": 0.12},
    {"label": "12-100%", "attach": 0.12, "detach": 1.00},
]

# iTraxx Crossover S44 standard tranche structure
CROSSOVER_TRANCHES = [
    {"label": "0-10%",   "attach": 0.00, "detach": 0.10},
    {"label": "10-20%",  "attach": 0.10, "detach": 0.20},
    {"label": "20-35%",  "attach": 0.20, "detach": 0.35},
    {"label": "35-100%", "attach": 0.35, "detach": 1.00},
]

# Default recovery rates by rating bucket
RECOVERY_RATES = {
    "AAA": 0.40, "AA+": 0.40, "AA": 0.40, "AA-": 0.40,
    "A+": 0.40, "A": 0.40, "A-": 0.40,
    "BBB+": 0.40, "BBB": 0.40, "BBB-": 0.40,
    "BB+": 0.35, "BB": 0.35, "BB-": 0.35,
    "B+": 0.30, "B": 0.30, "B-": 0.30,
    "CCC": 0.25, "CC": 0.20, "C": 0.15,
}


# ===========================================================================
# Dataclasses
# ===========================================================================

@dataclass
class TrancheAnalytics:
    """Full analytics for a single tranche (backward-compatible with scenario table)."""
    attachment: float
    detachment: float
    width: float
    index_spread: float
    base_correlation: float
    recovery: float
    maturity: float

    expected_loss_pct: float     # Expected loss as % of tranche notional
    premium_leg_pv: float        # PV of premium leg (RPV01)
    protection_leg_pv: float     # PV of protection leg
    fair_spread_bps: float       # Breakeven spread in bps
    upfront_pct: float           # Upfront payment (for equity tranche)
    mtm: float                   # Mark-to-market ($)

    cs01: float                  # $ change for 1bp index spread widening
    tranche_dv01: float          # $ change for 1bp tranche spread move
    delta: float                 # Tranche spread move per 1bp index move
    gamma: float                 # Convexity: change in delta per 1bp
    leverage: float              # Tranche notional loss / index notional loss
    notional: float = 10_000_000


@dataclass
class StrategyPnL:
    """P&L for a tranche position under a spread scenario."""
    bump_bps: float
    new_index_spread: float
    position_pnl: float
    cumulative_pnl: float = 0.0


@dataclass
class CDSCurve:
    """Bootstrapped CDS curve for a single name."""
    name: str
    ticker: str
    sector: str
    rating: str
    spread_5y_bps: float
    hazard_rate: float
    survival_prob_5y: float
    default_prob_5y: float
    recovery_rate: float
    source: str  # "merton_implied", "market", or "synthetic"
    weight: float = 1.0


@dataclass
class TranchePrice:
    """Pricing result for a single tranche (full-fat version)."""
    index_name: str
    attach: float
    detach: float
    tranche_label: str
    expected_loss_pct: float
    fair_spread_bps: float
    upfront_pct: float
    running_bps: float
    base_correlation: float
    risky_duration: float
    tranche_width: float


@dataclass
class TrancheGreeks:
    """Greeks for a tranche position."""
    tranche_label: str
    cs01_per_mm: float          # P&L per 1bp parallel shift per $1mm notional
    cs02_per_mm: float          # convexity
    rho01_per_mm: float         # P&L per 1% absolute correlation shift per $1mm
    theta_daily_per_mm: float   # time decay per day per $1mm
    recovery_01_per_mm: float   # sensitivity to 1% recovery change
    delta_ratio: float          # tranche CS01 / index CS01 (hedge ratio)
    jtd_worst: Dict             # top 5 worst JTD names


# ===========================================================================
# Core LHP Model (Fast Path — used by scenario table & pitch deck)
# ===========================================================================

def _implied_default_prob(spread_bps: float, recovery: float = ISDA_RECOVERY,
                          maturity: float = 5.0) -> float:
    """Implied cumulative default probability from spread.
        PD = 1 - exp(-h * T)  where h = s/(1-R)
    """
    s = spread_bps / 10_000
    h = s / (1 - recovery)
    return 1 - math.exp(-h * maturity)


def _conditional_default_prob(pd: float, rho: float, m: float) -> float:
    """Conditional default probability given systematic factor M = m.
    P(default | M = m) = Phi( (Phi^{-1}(PD) - sqrt(rho)*m) / sqrt(1-rho) )
    """
    if pd <= 0:
        return 0.0
    if pd >= 1:
        return 1.0
    threshold = norm.ppf(pd)
    numerator = threshold - math.sqrt(rho) * m
    denominator = math.sqrt(1 - rho)
    return norm.cdf(numerator / denominator)


def _conditional_expected_loss(pd: float, rho: float, m: float,
                               recovery: float = ISDA_RECOVERY) -> float:
    """Conditional expected portfolio loss fraction given M = m (LHP)."""
    return _conditional_default_prob(pd, rho, m) * (1.0 - recovery)


def _tranche_expected_loss_conditional(pd: float, rho: float, m: float,
                                        attachment: float, detachment: float,
                                        recovery: float = ISDA_RECOVERY) -> float:
    """Conditional expected tranche loss fraction given M = m (LHP).
    E[L_tranche | M] = (1/width) * (min(L, D) - min(L, A))
    """
    loss = _conditional_expected_loss(pd, rho, m, recovery)
    width = detachment - attachment
    tranche_loss = (min(loss, detachment) - min(loss, attachment)) / width
    return max(0.0, tranche_loss)


def expected_tranche_loss(index_spread: float, correlation: float,
                          attachment: float, detachment: float,
                          recovery: float = ISDA_RECOVERY,
                          maturity: float = 5.0) -> float:
    """Unconditional expected tranche loss (% of tranche notional) — LHP fast path.
    Integrates over the systematic factor M ~ N(0,1) using scipy.integrate.quad.
    """
    pd = _implied_default_prob(index_spread, recovery, maturity)
    if pd <= 0:
        return 0.0
    if pd >= 1:
        return 1.0

    def integrand(m):
        cond_loss = _tranche_expected_loss_conditional(
            pd, correlation, m, attachment, detachment, recovery
        )
        return cond_loss * norm.pdf(m)

    result, _ = integrate.quad(integrand, -6, 6, limit=100)
    return max(0.0, min(1.0, result))


def _risky_annuity_tranche(index_spread: float, correlation: float,
                           attachment: float, detachment: float,
                           recovery: float = ISDA_RECOVERY,
                           maturity: float = 5.0,
                           risk_free_rate: float = RISK_FREE_RATE) -> float:
    """Risky annuity for the tranche (RPV01).
    RPV01 = sum over quarterly dates of DF(t_i) * (1 - EL(t_i)) * dt
    """
    n_periods = int(maturity * 4)
    dt = 0.25
    rpv01 = 0.0
    for i in range(1, n_periods + 1):
        t = i * dt
        el_t = expected_tranche_loss(
            index_spread, correlation, attachment, detachment, recovery, t
        )
        df = math.exp(-risk_free_rate * t)
        survival = 1.0 - el_t
        rpv01 += df * survival * dt
    return rpv01


def _protection_leg_tranche(index_spread: float, correlation: float,
                            attachment: float, detachment: float,
                            recovery: float = ISDA_RECOVERY,
                            maturity: float = 5.0,
                            risk_free_rate: float = RISK_FREE_RATE) -> float:
    """PV of protection leg for tranche (per unit tranche notional)."""
    n_steps = int(maturity * 4)
    dt = 0.25
    prot_pv = 0.0
    prev_el = 0.0
    for i in range(1, n_steps + 1):
        t = i * dt
        el_t = expected_tranche_loss(
            index_spread, correlation, attachment, detachment, recovery, t
        )
        d_el = el_t - prev_el
        t_mid = t - dt / 2
        df = math.exp(-risk_free_rate * t_mid)
        prot_pv += df * d_el
        prev_el = el_t
    return prot_pv


# ===========================================================================
# Gauss-Hermite Quadrature Engine (Full-Fat Path)
# ===========================================================================

def _gauss_hermite_nodes_weights(n: int = N_QUADRATURE) -> Tuple[np.ndarray, np.ndarray]:
    """Get Gauss-Hermite quadrature nodes and weights for N(0,1) integration."""
    nodes, weights = np.polynomial.hermite.hermgauss(n)
    nodes = nodes * np.sqrt(2)
    weights = weights / np.sqrt(np.pi)
    return nodes, weights


def conditional_default_prob_vec(unconditional_pd: float, correlation: float,
                                 systematic_factor: float) -> float:
    """Conditional default probability given systematic factor M (numpy-friendly)."""
    if correlation <= 0:
        return unconditional_pd
    if correlation >= 1:
        return 1.0 if systematic_factor < norm.ppf(unconditional_pd) else 0.0
    threshold = norm.ppf(max(1e-10, min(1 - 1e-10, unconditional_pd)))
    sqrt_rho = np.sqrt(correlation)
    sqrt_one_minus_rho = np.sqrt(1.0 - correlation)
    return norm.cdf((threshold - sqrt_rho * systematic_factor) / sqrt_one_minus_rho)


def expected_portfolio_loss_conditional(pd_vector: np.ndarray,
                                         lgd_vector: np.ndarray,
                                         weight_vector: np.ndarray,
                                         correlation: float,
                                         systematic_factor: float) -> float:
    """Expected portfolio loss conditional on systematic factor M.
    E[L|M] = sum_i w_i * LGD_i * p_i(M)
    For heterogeneous portfolios (per-name PD/LGD/weight).
    """
    cond_pds = np.array([
        conditional_default_prob_vec(pd, correlation, systematic_factor)
        for pd in pd_vector
    ])
    return np.sum(weight_vector * lgd_vector * cond_pds)


def expected_tranche_loss_heterogeneous(attach: float, detach: float,
                                          pd_vector: np.ndarray,
                                          lgd_vector: np.ndarray,
                                          weight_vector: np.ndarray,
                                          correlation: float,
                                          n_points: int = N_QUADRATURE) -> float:
    """Expected tranche loss using Gauss-Hermite quadrature.
    Full heterogeneous portfolio — uses per-name PD, LGD, and weights.
    """
    if detach <= attach:
        return 0.0
    nodes, weights = _gauss_hermite_nodes_weights(n_points)
    tranche_width = detach - attach
    total = 0.0
    for i in range(n_points):
        M = nodes[i]
        w = weights[i]
        cond_loss = expected_portfolio_loss_conditional(
            pd_vector, lgd_vector, weight_vector, correlation, M
        )
        tranche_loss = (min(cond_loss, detach) - min(cond_loss, attach)) / tranche_width
        total += w * tranche_loss
    return max(0.0, total)


def expected_tranche_loss_lhp(attach: float, detach: float,
                                avg_pd: float, avg_lgd: float,
                                correlation: float,
                                n_points: int = N_QUADRATURE) -> float:
    """LHP approximation via Gauss-Hermite quadrature.
    Assumes all names have the same PD, LGD, and equal weight.
    Uses Vasicek distribution for portfolio loss.
    """
    if detach <= attach or avg_pd <= 0:
        return 0.0
    nodes, weights = _gauss_hermite_nodes_weights(n_points)
    tranche_width = detach - attach
    threshold = norm.ppf(max(1e-10, min(1 - 1e-10, avg_pd)))
    sqrt_rho = np.sqrt(max(0.001, correlation))
    sqrt_one_minus_rho = np.sqrt(max(0.001, 1.0 - correlation))
    total = 0.0
    for i in range(n_points):
        M = nodes[i]
        w = weights[i]
        cond_pd = norm.cdf((threshold - sqrt_rho * M) / sqrt_one_minus_rho)
        cond_loss = avg_lgd * cond_pd
        tranche_loss = (min(cond_loss, detach) - min(cond_loss, attach)) / tranche_width
        total += w * tranche_loss
    return max(0.0, total)


def risky_duration_approx(hazard_rate_avg: float, maturity: float = MATURITY_YEARS,
                           rf_rate: float = RISK_FREE_RATE) -> float:
    """Approximate risky duration (DV01 scaling) for a tranche."""
    dt = 0.25
    n_periods = int(maturity / dt)
    total = 0.0
    for i in range(1, n_periods + 1):
        t = i * dt
        discount = np.exp(-(rf_rate + hazard_rate_avg) * t)
        total += dt * discount
    return total


# ===========================================================================
# CDS Curve Bootstrapping
# ===========================================================================

def hazard_rate_from_spread(spread_bps: float, recovery: float = 0.40) -> float:
    """Constant hazard rate from 5Y CDS spread: h = s / (1 - R)."""
    if spread_bps <= 0:
        return 1e-6
    return spread_bps / (1.0 - recovery) / 10000.0


def survival_probability(hazard_rate: float, t: float) -> float:
    """P(no default before time t) = exp(-h * t)"""
    return np.exp(-hazard_rate * t)


def default_probability(hazard_rate: float, t: float) -> float:
    """P(default before time t) = 1 - exp(-h * t)"""
    return 1.0 - np.exp(-hazard_rate * t)


def bootstrap_cds_curves_from_merton(merton_results: List[Dict],
                                       recovery_override: float = None,
                                       scaling_factor: float = 1.0) -> List[CDSCurve]:
    """Convert Merton model results to CDS curves with hazard rates."""
    curves = []
    for res in merton_results:
        spread = res.get("implied_spread_bps", 0) * scaling_factor
        if spread <= 0:
            continue
        rating = res.get("rating", "BBB")
        recovery = recovery_override if recovery_override is not None else RECOVERY_RATES.get(rating, 0.40)
        hr = hazard_rate_from_spread(spread, recovery)
        sp = survival_probability(hr, MATURITY_YEARS)
        dp = default_probability(hr, MATURITY_YEARS)
        curves.append(CDSCurve(
            name=res["name"],
            ticker=res.get("ticker", ""),
            sector=res.get("sector", ""),
            rating=rating,
            spread_5y_bps=round(spread, 1),
            hazard_rate=hr,
            survival_prob_5y=sp,
            default_prob_5y=dp,
            recovery_rate=recovery,
            source="merton_implied",
        ))
    if curves:
        w = 1.0 / len(curves)
        for c in curves:
            c.weight = w
    return curves


def calibrate_scaling_factor(ecb_index_spread: float,
                              avg_merton_spread: float) -> float:
    """Scaling factor to calibrate Merton-implied spreads to market."""
    if avg_merton_spread <= 0:
        return 1.0
    return max(0.3, min(3.0, ecb_index_spread / avg_merton_spread))


def generate_synthetic_cds_curves(index_name: str = "Main",
                                    n_names: int = 125,
                                    avg_spread: float = 60,
                                    spread_std: float = 30,
                                    recovery: float = 0.40) -> List[CDSCurve]:
    """Generate synthetic CDS curves for standalone testing."""
    np.random.seed(42)
    if index_name == "Main":
        sectors = ["Banks", "Insurance", "Autos", "Telecoms", "Utilities",
                    "Energy", "Industrials", "Consumer", "Healthcare", "Chemicals",
                    "Technology", "Real Estate", "Retail", "Mining", "Transport"]
        ratings = ["AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"]
        rating_weights = [0.05, 0.15, 0.20, 0.20, 0.20, 0.15, 0.05]
    else:
        sectors = ["Telecoms", "Autos", "Airlines", "Metals", "Retail",
                    "Energy", "Real Estate", "Healthcare", "Gaming", "Chemicals"]
        ratings = ["BB+", "BB", "BB-", "B+", "B", "B-", "CCC"]
        rating_weights = [0.20, 0.25, 0.20, 0.15, 0.10, 0.07, 0.03]

    log_mean = np.log(avg_spread) - 0.5 * (spread_std / avg_spread) ** 2
    log_std = np.sqrt(np.log(1 + (spread_std / avg_spread) ** 2))
    spreads = np.random.lognormal(log_mean, log_std, n_names)
    spreads = np.clip(spreads, 5, 2000)

    curves = []
    w = 1.0 / n_names
    for i in range(n_names):
        spread = spreads[i]
        rating = np.random.choice(ratings, p=rating_weights)
        sector = np.random.choice(sectors)
        r = RECOVERY_RATES.get(rating, recovery)
        hr = hazard_rate_from_spread(spread, r)
        curves.append(CDSCurve(
            name=f"Name_{i+1:03d}",
            ticker=f"SYN{i+1:03d}",
            sector=sector,
            rating=rating,
            spread_5y_bps=round(spread, 1),
            hazard_rate=hr,
            survival_prob_5y=survival_probability(hr, MATURITY_YEARS),
            default_prob_5y=default_probability(hr, MATURITY_YEARS),
            recovery_rate=r,
            source="synthetic",
            weight=w,
        ))
    return curves


# ===========================================================================
# ECB Index Data
# ===========================================================================

def fetch_ecb_index_data() -> Dict:
    """Fetch iTraxx Main and Crossover daily levels from ECB SDW."""
    result = {}
    if not HAS_REQUESTS or not HAS_PANDAS:
        return result

    ecb_series = {
        "main_5y": "FM.D.U2.EUR.4F.KR.MAAC_5Y.HSTA",
        "crossover_5y": "FM.D.U2.EUR.4F.KR.XOAC_5Y.HSTA",
    }

    for key, series_key in ecb_series.items():
        try:
            url = f"https://data-api.ecb.europa.eu/service/data/{series_key}"
            params = {"startPeriod": "2022-01-01", "format": "csvdata"}
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200 and len(resp.text) > 100:
                from io import StringIO
                df = pd.read_csv(StringIO(resp.text))
                if "TIME_PERIOD" in df.columns and "OBS_VALUE" in df.columns:
                    dates = pd.to_datetime(df["TIME_PERIOD"])
                    vals = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
                    s = pd.Series(vals.values, index=dates, name=key).dropna().sort_index()
                    if len(s) > 10:
                        result[key] = s
                        print(f"  ECB {key}: {len(s)} obs, latest={s.iloc[-1]:.1f}bps ({s.index[-1].strftime('%Y-%m-%d')})")
        except Exception as e:
            print(f"  ECB {key}: fetch failed - {str(e)[:80]}")

    # Fallback keys
    if "main_5y" not in result:
        for alt_key in ["FM.D.U2.EUR.4F.KR.MAAC.HSTA", "FM.B.U2.EUR.4F.KR.MAAC.HZ"]:
            try:
                url = f"https://data-api.ecb.europa.eu/service/data/{alt_key}"
                resp = requests.get(url, params={"startPeriod": "2022-01-01", "format": "csvdata"}, timeout=30)
                if resp.status_code == 200 and len(resp.text) > 100:
                    from io import StringIO
                    df = pd.read_csv(StringIO(resp.text))
                    if "TIME_PERIOD" in df.columns and "OBS_VALUE" in df.columns:
                        dates = pd.to_datetime(df["TIME_PERIOD"])
                        vals = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
                        s = pd.Series(vals.values, index=dates, name="main_5y").dropna().sort_index()
                        if len(s) > 10:
                            result["main_5y"] = s
                            break
            except Exception:
                continue

    if "crossover_5y" not in result:
        for alt_key in ["FM.D.U2.EUR.4F.KR.XOAC.HSTA", "FM.B.U2.EUR.4F.KR.XO.HZ"]:
            try:
                url = f"https://data-api.ecb.europa.eu/service/data/{alt_key}"
                resp = requests.get(url, params={"startPeriod": "2022-01-01", "format": "csvdata"}, timeout=30)
                if resp.status_code == 200 and len(resp.text) > 100:
                    from io import StringIO
                    df = pd.read_csv(StringIO(resp.text))
                    if "TIME_PERIOD" in df.columns and "OBS_VALUE" in df.columns:
                        dates = pd.to_datetime(df["TIME_PERIOD"])
                        vals = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
                        s = pd.Series(vals.values, index=dates, name="crossover_5y").dropna().sort_index()
                        if len(s) > 10:
                            result["crossover_5y"] = s
                            break
            except Exception:
                continue

    return result


# ===========================================================================
# Parametric Base Correlation
# ===========================================================================

def _parametric_base_correlation(detach: float, index_name: str) -> float:
    """Parametric base correlation smile — monotonically increasing with detachment.
    Main S44:      0-3% equity ~22%, 3-6% mezz ~38%, 6-12% senior ~55%, 12-100% super ~75%
    Crossover S44: 0-10% equity ~28%, 10-20% mezz ~48%, 20-35% senior ~65%, 35-100% super ~80%
    """
    if index_name == "Main":
        if detach <= 0.03:
            return 0.22
        elif detach <= 0.06:
            return 0.38
        elif detach <= 0.12:
            return 0.55
        else:
            return 0.75
    else:  # Crossover
        if detach <= 0.10:
            return 0.28
        elif detach <= 0.20:
            return 0.48
        elif detach <= 0.35:
            return 0.65
        else:
            return 0.80


# ===========================================================================
# Base Correlation Calibration
# ===========================================================================

def gaussian_copula_base_correlation(
    tranche_spread: float,
    attachment: float,
    detachment: float,
    index_spread: float,
    recovery: float = ISDA_RECOVERY,
    maturity: float = 5.0,
    correlation_guess: float = 0.3,
    is_upfront: bool = False,
    running_coupon: float = 500,
) -> float:
    """Calibrate base correlation from market tranche spread.
    For equity tranche (traded on upfront + running):
        tranche_spread = upfront percentage (e.g., 35 for 35%)
    For mezzanine/senior (traded on running):
        tranche_spread = running spread in bps
    """
    def objective(rho):
        if is_upfront:
            prot = _protection_leg_tranche(
                index_spread, rho, attachment, detachment, recovery, maturity
            )
            rpv01 = _risky_annuity_tranche(
                index_spread, rho, attachment, detachment, recovery, maturity
            )
            model_upfront = (prot - running_coupon / 10_000 * rpv01) * 100
            return model_upfront - tranche_spread
        else:
            prot = _protection_leg_tranche(
                index_spread, rho, attachment, detachment, recovery, maturity
            )
            rpv01 = _risky_annuity_tranche(
                index_spread, rho, attachment, detachment, recovery, maturity
            )
            if rpv01 <= 0:
                return 1e6
            model_spread = prot / rpv01 * 10_000
            return model_spread - tranche_spread

    try:
        return optimize.brentq(objective, 0.001, 0.999, xtol=1e-6, maxiter=200)
    except ValueError:
        pass

    # Scan for sign changes if standard bracket fails
    scan_points = [0.001, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10,
                   0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80,
                   0.90, 0.95, 0.99, 0.999]
    vals = [(rho, objective(rho)) for rho in scan_points]
    for i in range(len(vals) - 1):
        rho_a, f_a = vals[i]
        rho_b, f_b = vals[i + 1]
        if f_a * f_b < 0:
            try:
                return optimize.brentq(objective, rho_a, rho_b, xtol=1e-6, maxiter=200)
            except ValueError:
                continue
    closest = min(vals, key=lambda x: abs(x[1]))
    return closest[0]


def calibrate_base_correlation_from_spread(attach: float, detach: float,
                                            target_spread_bps: float,
                                            pd_vector: np.ndarray,
                                            lgd_vector: np.ndarray,
                                            weight_vector: np.ndarray,
                                            avg_hazard_rate: float,
                                            use_lhp: bool = True) -> float:
    """Solve for base correlation matching a target tranche spread (full-fat version)."""
    avg_pd = np.mean(pd_vector)
    avg_lgd = np.mean(lgd_vector)

    def objective(corr):
        if use_lhp:
            el = expected_tranche_loss_lhp(attach, detach, avg_pd, avg_lgd, corr)
        else:
            el = expected_tranche_loss_heterogeneous(
                attach, detach, pd_vector, lgd_vector, weight_vector, corr
            )
        rd = risky_duration_approx(avg_hazard_rate)
        model_spread = el / rd * 10000 if rd > 0 else 0
        return model_spread - target_spread_bps

    try:
        return optimize.brentq(objective, 0.01, 0.99, xtol=1e-4)
    except Exception:
        return _parametric_base_correlation(detach, "Main")


# ===========================================================================
# Tranche Pricing — LHP (backward-compatible interface)
# ===========================================================================

def price_tranche(
    attachment: float,
    detachment: float,
    index_spread: float,
    base_correlation: float,
    recovery: float = ISDA_RECOVERY,
    maturity: float = 5.0,
    notional: float = 10_000_000,
    running_coupon_bps: float = 0,
) -> TrancheAnalytics:
    """Price a tranche given base correlation — LHP fast path.
    This is the backward-compatible interface used by tranche_scenario_table
    and pitch_deck.
    """
    width = detachment - attachment

    el = expected_tranche_loss(
        index_spread, base_correlation, attachment, detachment, recovery, maturity
    )
    prot_pv = _protection_leg_tranche(
        index_spread, base_correlation, attachment, detachment, recovery, maturity
    )
    rpv01 = _risky_annuity_tranche(
        index_spread, base_correlation, attachment, detachment, recovery, maturity
    )

    fair_spread = (prot_pv / rpv01 * 10_000) if rpv01 > 0 else 0
    if running_coupon_bps > 0:
        upfront = (prot_pv - running_coupon_bps / 10_000 * rpv01) * 100
    else:
        upfront = 0.0

    mtm = prot_pv * notional - running_coupon_bps / 10_000 * rpv01 * notional

    # Risk metrics via finite differences
    bump = 1.0
    el_up = expected_tranche_loss(
        index_spread + bump, base_correlation, attachment, detachment, recovery, maturity
    )
    prot_up = _protection_leg_tranche(
        index_spread + bump, base_correlation, attachment, detachment, recovery, maturity
    )
    rpv01_up = _risky_annuity_tranche(
        index_spread + bump, base_correlation, attachment, detachment, recovery, maturity
    )
    fair_up = (prot_up / rpv01_up * 10_000) if rpv01_up > 0 else 0

    prot_dn = _protection_leg_tranche(
        max(1.0, index_spread - bump), base_correlation, attachment, detachment, recovery, maturity
    )
    rpv01_dn = _risky_annuity_tranche(
        max(1.0, index_spread - bump), base_correlation, attachment, detachment, recovery, maturity
    )
    fair_dn = (prot_dn / rpv01_dn * 10_000) if rpv01_dn > 0 else 0

    mtm_up = prot_up * notional - running_coupon_bps / 10_000 * rpv01_up * notional
    mtm_dn = prot_dn * notional - running_coupon_bps / 10_000 * rpv01_dn * notional
    cs01 = (mtm_up - mtm_dn) / 2
    tranche_dv01 = rpv01 * notional / 10_000
    delta = (fair_up - fair_dn) / 2

    # Gamma (convexity)
    fair_up2, fair_dn2 = 0.0, 0.0
    if index_spread + 2 * bump > 0:
        prot_up2 = _protection_leg_tranche(
            index_spread + 2 * bump, base_correlation, attachment, detachment, recovery, maturity
        )
        rpv01_up2 = _risky_annuity_tranche(
            index_spread + 2 * bump, base_correlation, attachment, detachment, recovery, maturity
        )
        fair_up2 = (prot_up2 / rpv01_up2 * 10_000) if rpv01_up2 > 0 else 0

    if index_spread - 2 * bump > 0:
        prot_dn2 = _protection_leg_tranche(
            index_spread - 2 * bump, base_correlation, attachment, detachment, recovery, maturity
        )
        rpv01_dn2 = _risky_annuity_tranche(
            index_spread - 2 * bump, base_correlation, attachment, detachment, recovery, maturity
        )
        fair_dn2 = (prot_dn2 / rpv01_dn2 * 10_000) if rpv01_dn2 > 0 else 0

    delta_up = fair_up2 - fair_up if fair_up2 else delta
    delta_dn = fair_up - fair_dn if fair_dn else delta
    gamma = delta_up - delta_dn
    leverage = delta * (1.0 / width) if width > 0 else 0

    return TrancheAnalytics(
        attachment=attachment,
        detachment=detachment,
        width=width,
        index_spread=index_spread,
        base_correlation=base_correlation,
        recovery=recovery,
        maturity=maturity,
        expected_loss_pct=el * 100,
        premium_leg_pv=rpv01,
        protection_leg_pv=prot_pv,
        fair_spread_bps=fair_spread,
        upfront_pct=upfront,
        mtm=mtm,
        cs01=cs01,
        tranche_dv01=tranche_dv01,
        delta=delta,
        gamma=gamma,
        leverage=leverage,
        notional=notional,
    )


def tranche_risk_metrics(
    attachment: float, detachment: float, index_spread: float,
    base_correlation: float, recovery: float = ISDA_RECOVERY,
    maturity: float = 5.0, notional: float = 10_000_000,
    running_coupon_bps: float = 0,
) -> TrancheAnalytics:
    """Alias for price_tranche."""
    return price_tranche(
        attachment, detachment, index_spread, base_correlation,
        recovery, maturity, notional, running_coupon_bps,
    )


# ===========================================================================
# Tranche Pricing — Full-Fat (Heterogeneous Portfolio)
# ===========================================================================

def price_single_tranche(attach: float, detach: float,
                          pd_vector: np.ndarray,
                          lgd_vector: np.ndarray,
                          weight_vector: np.ndarray,
                          correlation: float,
                          avg_hazard_rate: float,
                          index_name: str = "Main",
                          label: str = "0-3%",
                          use_lhp: bool = True) -> TranchePrice:
    """Price a single tranche using Gaussian copula with Gauss-Hermite quadrature."""
    if use_lhp and len(pd_vector) > 50:
        avg_pd = np.mean(pd_vector)
        avg_lgd = np.mean(lgd_vector)
        el = expected_tranche_loss_lhp(attach, detach, avg_pd, avg_lgd, correlation)
    else:
        el = expected_tranche_loss_heterogeneous(
            attach, detach, pd_vector, lgd_vector, weight_vector, correlation
        )

    rd = risky_duration_approx(avg_hazard_rate)
    tranche_width = detach - attach
    fair_spread_bps = el / rd * 10000 if rd > 0 else 0

    is_equity = (attach == 0.0)
    if is_equity:
        running_bps = 500.0
        upfront_pct = max(0, (fair_spread_bps - running_bps) * rd / 10000)
    else:
        running_bps = fair_spread_bps
        upfront_pct = 0.0

    return TranchePrice(
        index_name=index_name,
        attach=attach,
        detach=detach,
        tranche_label=label,
        expected_loss_pct=round(el * 100, 4),
        fair_spread_bps=round(fair_spread_bps, 1),
        upfront_pct=round(upfront_pct * 100, 2),
        running_bps=round(running_bps, 1),
        base_correlation=round(correlation, 4),
        risky_duration=round(rd, 3),
        tranche_width=tranche_width,
    )


def price_all_tranches(cds_curves: List[CDSCurve],
                        index_name: str = "Main",
                        base_corr_surface: Dict[str, float] = None,
                        recovery_override: float = None) -> List[TranchePrice]:
    """Price all standard tranches for a given index using CDS curves."""
    tranches = MAIN_TRANCHES if index_name == "Main" else CROSSOVER_TRANCHES

    pd_vector = np.array([c.default_prob_5y for c in cds_curves])
    lgd_vector = (np.array([1.0 - recovery_override] * len(cds_curves))
                  if recovery_override is not None
                  else np.array([1.0 - c.recovery_rate for c in cds_curves]))
    weight_vector = np.array([c.weight for c in cds_curves])
    if weight_vector.sum() > 0:
        weight_vector = weight_vector / weight_vector.sum()

    avg_hazard_rate = np.mean([c.hazard_rate for c in cds_curves])
    results = []
    for t in tranches:
        label = t["label"]
        corr = (base_corr_surface[label] if base_corr_surface and label in base_corr_surface
                else _parametric_base_correlation(t["detach"], index_name))
        tp = price_single_tranche(
            t["attach"], t["detach"],
            pd_vector, lgd_vector, weight_vector,
            corr, avg_hazard_rate,
            index_name=index_name, label=label,
            use_lhp=(len(cds_curves) > 50),
        )
        results.append(tp)
    return results


# ===========================================================================
# Full Greeks (CS01, CS02, Rho01, Theta, Recovery01, JTD)
# ===========================================================================

def compute_tranche_greeks(tranche: TranchePrice,
                            cds_curves: List[CDSCurve],
                            recovery_override: float = None) -> TrancheGreeks:
    """Compute numerical Greeks via bump-and-reprice. All per $1mm tranche notional."""
    pd_vector = np.array([c.default_prob_5y for c in cds_curves])
    lgd_vector = (np.array([1.0 - recovery_override] * len(cds_curves))
                  if recovery_override is not None
                  else np.array([1.0 - c.recovery_rate for c in cds_curves]))
    weight_vector = np.array([c.weight for c in cds_curves])
    if weight_vector.sum() > 0:
        weight_vector = weight_vector / weight_vector.sum()

    avg_hazard_rate = np.mean([c.hazard_rate for c in cds_curves])
    avg_pd = np.mean(pd_vector)
    avg_lgd = np.mean(lgd_vector)
    corr = tranche.base_correlation
    attach = tranche.attach
    detach = tranche.detach
    use_lhp = len(cds_curves) > 50

    def _el(pd_bump=0, corr_bump=0, recovery_bump=0):
        adj_pd = max(1e-6, min(0.999, avg_pd + pd_bump))
        adj_corr = max(0.01, min(0.99, corr + corr_bump))
        adj_lgd = max(0.01, avg_lgd - recovery_bump)
        if use_lhp:
            return expected_tranche_loss_lhp(attach, detach, adj_pd, adj_lgd, adj_corr)
        else:
            pd_vec_adj = np.clip(pd_vector + pd_bump, 1e-6, 0.999)
            lgd_vec_adj = np.clip(lgd_vector - recovery_bump, 0.01, 1.0)
            return expected_tranche_loss_heterogeneous(
                attach, detach, pd_vec_adj, lgd_vec_adj, weight_vector, adj_corr
            )

    el_base = _el()
    rd = risky_duration_approx(avg_hazard_rate)

    # CS01: PD bump per 1bp spread
    avg_survival = np.mean([c.survival_prob_5y for c in cds_curves])
    avg_recovery = np.mean([c.recovery_rate for c in cds_curves])
    pd_bump_per_1bp = (1.0 / (1.0 - avg_recovery) / 10000.0) * MATURITY_YEARS * avg_survival

    el_up = _el(pd_bump=pd_bump_per_1bp)
    el_dn = _el(pd_bump=-pd_bump_per_1bp)
    cs01 = (el_up - el_dn) / 2.0 * 1e6

    # CS02 (convexity)
    cs02 = (el_up + el_dn - 2 * el_base) * 1e6

    # Rho01: correlation sensitivity per 1% absolute
    el_corr_up = _el(corr_bump=0.01)
    el_corr_dn = _el(corr_bump=-0.01)
    rho01 = (el_corr_up - el_corr_dn) / 2.0 * 1e6

    # Recovery01
    el_rec_up = _el(recovery_bump=0.01)
    recovery_01 = (el_rec_up - el_base) * 1e6

    # Theta (approximate)
    theta_daily = -el_base / (MATURITY_YEARS * 365) * 1e6

    # Delta ratio
    index_cs01_per_mm = rd / 10000 * 1e6
    delta_ratio = cs01 / index_cs01_per_mm if index_cs01_per_mm > 0 else 0

    # JTD: worst 5 names
    jtd = {}
    n_names = len(cds_curves)
    tranche_width = detach - attach
    for c in sorted(cds_curves, key=lambda x: x.default_prob_5y, reverse=True)[:5]:
        name_loss = (1.0 / n_names) * (1.0 - c.recovery_rate)
        if name_loss > attach:
            tranche_hit = min(name_loss, detach) - attach
            jtd_pct = tranche_hit / tranche_width * 100
        else:
            jtd_pct = 0
        jtd[c.name] = round(jtd_pct, 2)

    return TrancheGreeks(
        tranche_label=tranche.tranche_label,
        cs01_per_mm=round(cs01, 2),
        cs02_per_mm=round(cs02, 4),
        rho01_per_mm=round(rho01, 2),
        theta_daily_per_mm=round(theta_daily, 2),
        recovery_01_per_mm=round(recovery_01, 2),
        delta_ratio=round(delta_ratio, 2),
        jtd_worst=jtd,
    )


# ===========================================================================
# Strategy P&L Analysis (backward-compatible)
# ===========================================================================

def tranche_strategy_analysis(
    index_spread: float,
    base_correlations: dict[str, float],
    positions: list[dict],
    bumps: list[float] | None = None,
) -> dict[str, list[StrategyPnL]]:
    """Analyse tranche strategy P&L across parallel spread scenarios."""
    if bumps is None:
        bumps = [-50, -25, 0, +25, +50, +100, +200]

    results: dict[str, list[StrategyPnL]] = {}

    for pos in positions:
        tranche_name = pos["tranche"]
        tranche_def = STANDARD_TRANCHES[tranche_name]
        direction = pos["direction"]
        notional = pos["notional"]
        rho = base_correlations.get(tranche_name, 0.3)
        running = tranche_def["coupon_bps"]
        att = tranche_def["attachment"]
        det = tranche_def["detachment"]

        base_analytics = price_tranche(
            att, det, index_spread, rho, notional=notional,
            running_coupon_bps=running,
        )
        base_mtm = base_analytics.mtm

        pnl_list = []
        for bump in bumps:
            new_spread = max(1.0, index_spread + bump)
            bumped = price_tranche(
                att, det, new_spread, rho, notional=notional,
                running_coupon_bps=running,
            )
            raw_pnl = bumped.mtm - base_mtm
            signed_pnl = raw_pnl if direction == "SHORT_RISK" else -raw_pnl
            pnl_list.append(StrategyPnL(
                bump_bps=bump,
                new_index_spread=new_spread,
                position_pnl=signed_pnl,
            ))

        results[f"{tranche_name}_{direction}"] = pnl_list

    return results


# ===========================================================================
# Display Helpers
# ===========================================================================

def print_tranche_analytics(analytics: TrancheAnalytics, name: str = ""):
    """Print formatted analytics for a single tranche."""
    label = name or f"{analytics.attachment*100:.0f}-{analytics.detachment*100:.0f}%"
    print(f"\n  {'-'*55}")
    print(f"  {label} Tranche")
    print(f"  {'-'*55}")
    print(f"  Attachment:         {analytics.attachment*100:.0f}%")
    print(f"  Detachment:         {analytics.detachment*100:.0f}%")
    print(f"  Width:              {analytics.width*100:.0f}%")
    print(f"  Base Correlation:   {analytics.base_correlation:.2%}")
    print(f"  Expected Loss:      {analytics.expected_loss_pct:.2f}%")
    print(f"  Fair Spread:        {analytics.fair_spread_bps:.0f}bps")
    if analytics.upfront_pct != 0:
        print(f"  Upfront:            {analytics.upfront_pct:.2f}% + 500bps running")
    print(f"  Protection Leg PV:  {analytics.protection_leg_pv:.6f}")
    print(f"  RPV01:              {analytics.premium_leg_pv:.4f}")
    print(f"  CS01:               ${analytics.cs01:,.0f}")
    print(f"  Tranche DV01:       ${analytics.tranche_dv01:,.0f}")
    print(f"  Delta:              {analytics.delta:.2f}")
    print(f"  Gamma:              {analytics.gamma:.4f}")
    print(f"  Leverage:           {analytics.leverage:.1f}x")
    print(f"  Notional:           ${analytics.notional:,.0f}")


def print_strategy_table(
    all_results: dict[str, list[StrategyPnL]],
    index_spread: float,
):
    """Print P&L grid for strategy analysis."""
    if not all_results:
        return
    bumps = [p.bump_bps for p in list(all_results.values())[0]]
    print(f"\n  {'='*90}")
    print(f"  P&L BY SPREAD SCENARIO (Index @ {index_spread:.0f}bps)")
    print(f"  {'='*90}")
    header = f"  {'Position':<32}"
    for b in bumps:
        header += f"  {b:+.0f}bp".rjust(11)
    print(header)
    print(f"  {'-'*32}  " + "  ".join(["-"*9] * len(bumps)))

    total_by_bump = {b: 0.0 for b in bumps}
    for name, pnl_list in all_results.items():
        row = f"  {name:<32}"
        for p in pnl_list:
            row += f"  ${p.position_pnl/1000:>+8,.1f}k"
            total_by_bump[p.bump_bps] += p.position_pnl
        print(row)

    print(f"  {'-'*32}  " + "  ".join(["-"*9] * len(bumps)))
    total_row = f"  {'TOTAL P&L':<32}"
    for b in bumps:
        total_row += f"  ${total_by_bump[b]/1000:>+8,.1f}k"
    print(total_row)

    print(f"\n  CONVEXITY CHECK:")
    for name, pnl_list in all_results.items():
        pnl_map = {p.bump_bps: p.position_pnl for p in pnl_list}
        if 50 in pnl_map and 100 in pnl_map and pnl_map[50] != 0:
            ratio_100_50 = pnl_map[100] / pnl_map[50]
            ratio_200_100 = pnl_map[200] / pnl_map[100] if 200 in pnl_map and pnl_map[100] != 0 else 0
            print(f"    {name}: +100bp/{'+50bp'} = {ratio_100_50:.2f}x,  "
                  f"+200bp/{'+100bp'} = {ratio_200_100:.2f}x")


def print_full_report(main_tranches: List[TranchePrice],
                       xover_tranches: List[TranchePrice],
                       main_greeks: List[TrancheGreeks],
                       xover_greeks: List[TrancheGreeks],
                       main_curves: List[CDSCurve],
                       xover_curves: List[CDSCurve],
                       ecb_data: Dict):
    """Print formatted full tranche pricing report."""
    print("\n" + "=" * 110)
    print("  CDS & TRANCHE PRICER - GAUSSIAN COPULA ENGINE")
    print("=" * 110)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Model: One-factor Gaussian copula, Gauss-Hermite quadrature ({N_QUADRATURE} points)")
    print(f"  Maturity: {MATURITY_YEARS:.0f}Y")
    if ecb_data:
        for k, s in ecb_data.items():
            print(f"  ECB {k}: {s.iloc[-1]:.1f}bps ({s.index[-1].strftime('%Y-%m-%d')})")

    # CDS Curve Summary
    for idx_name, curves in [("Main", main_curves), ("Crossover", xover_curves)]:
        if not curves:
            continue
        print(f"\n{'=' * 110}")
        print(f"  CDS CURVE SUMMARY - iTRAXX {idx_name.upper()}")
        print(f"{'=' * 110}")
        spreads = [c.spread_5y_bps for c in curves]
        print(f"  Names: {len(curves)} | Avg spread: {np.mean(spreads):.1f}bps | "
              f"Median: {np.median(spreads):.1f}bps | Std: {np.std(spreads):.1f}bps")
        print(f"  Avg hazard rate: {np.mean([c.hazard_rate for c in curves])*10000:.2f}bps/yr")
        print(f"  Avg 5Y default prob: {np.mean([c.default_prob_5y for c in curves])*100:.2f}%")

        print(f"\n  Top 10 widest spreads:")
        print(f"  {'Name':<30s} {'Sector':<15s} {'Rating':>6s} {'Spread':>8s} {'PD 5Y':>7s} {'Hazard':>8s}")
        print("  " + "-" * 80)
        for c in sorted(curves, key=lambda x: x.spread_5y_bps, reverse=True)[:10]:
            print(f"  {c.name:<30s} {c.sector:<15s} {c.rating:>6s} {c.spread_5y_bps:>7.1f} "
                  f"{c.default_prob_5y*100:>6.2f}% {c.hazard_rate*10000:>7.2f}")

    # Tranche Pricing
    for idx_name, tranches, greeks in [("MAIN", main_tranches, main_greeks),
                                         ("CROSSOVER", xover_tranches, xover_greeks)]:
        if not tranches:
            continue
        print(f"\n{'=' * 110}")
        print(f"  iTRAXX {idx_name} TRANCHE PRICING")
        print(f"{'=' * 110}")
        print(f"  {'Tranche':<10s} {'Exp Loss%':>9s} {'Fair Spd':>9s} {'Upfront%':>9s} "
              f"{'Running':>8s} {'Base Corr':>10s} {'Duration':>9s}")
        print("  " + "-" * 70)
        for t in tranches:
            print(f"  {t.tranche_label:<10s} {t.expected_loss_pct:>8.3f}% {t.fair_spread_bps:>8.1f} "
                  f"{t.upfront_pct:>8.2f}% {t.running_bps:>7.1f} {t.base_correlation:>9.3f} "
                  f"{t.risky_duration:>8.3f}")

    # Greeks
    for idx_name, greeks in [("MAIN", main_greeks), ("CROSSOVER", xover_greeks)]:
        if not greeks:
            continue
        print(f"\n{'=' * 110}")
        print(f"  GREEKS - iTRAXX {idx_name} (per $1mm notional)")
        print(f"{'=' * 110}")
        print(f"  {'Tranche':<10s} {'CS01':>8s} {'CS02':>8s} {'Rho01':>8s} {'Theta/d':>8s} "
              f"{'Rec01':>8s} {'Delta':>7s}")
        print("  " + "-" * 65)
        for g in greeks:
            print(f"  {g.tranche_label:<10s} {g.cs01_per_mm:>7.1f}$ {g.cs02_per_mm:>7.2f}$ "
                  f"{g.rho01_per_mm:>7.1f}$ {g.theta_daily_per_mm:>7.1f}$ "
                  f"{g.recovery_01_per_mm:>7.1f}$ {g.delta_ratio:>6.1f}x")

    # JTD table
    for idx_name, greeks in [("MAIN", main_greeks), ("CROSSOVER", xover_greeks)]:
        if not greeks:
            continue
        eq_tranche = greeks[0]
        if eq_tranche.jtd_worst:
            print(f"\n{'=' * 110}")
            print(f"  JUMP-TO-DEFAULT EXPOSURE - {idx_name} EQUITY ({eq_tranche.tranche_label})")
            print(f"{'=' * 110}")
            print(f"  {'Name':<30s} {'JTD Loss %':>12s}")
            print("  " + "-" * 45)
            for name, pct in sorted(eq_tranche.jtd_worst.items(), key=lambda x: x[1], reverse=True):
                print(f"  {name:<30s} {pct:>11.2f}%")

    # Base Correlation Surface
    print(f"\n{'=' * 110}")
    print("  BASE CORRELATION SURFACE")
    print(f"{'=' * 110}")
    print(f"  {'Index':<12s} {'Tranche':<10s} {'Detach':>8s} {'Base Corr':>10s}")
    print("  " + "-" * 45)
    for t in main_tranches:
        print(f"  {'Main':<12s} {t.tranche_label:<10s} {t.detach*100:>7.1f}% {t.base_correlation:>9.3f}")
    for t in xover_tranches:
        print(f"  {'Crossover':<12s} {t.tranche_label:<10s} {t.detach*100:>7.1f}% {t.base_correlation:>9.3f}")

    print("\n" + "=" * 110)


# ===========================================================================
# Visualization (9-panel dashboard)
# ===========================================================================

def plot_dashboard(main_tranches: List[TranchePrice],
                    xover_tranches: List[TranchePrice],
                    main_greeks: List[TrancheGreeks],
                    xover_greeks: List[TrancheGreeks],
                    main_curves: List[CDSCurve],
                    xover_curves: List[CDSCurve],
                    ecb_data: Dict,
                    output_path: str = "outputs/tranche_dashboard.png"):
    """Create 9-panel tranche pricing dashboard."""
    if not HAS_MATPLOTLIB:
        print("  matplotlib not available, skipping dashboard")
        return

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle("CDS & TRANCHE PRICER - GAUSSIAN COPULA ENGINE",
                 fontsize=18, fontweight="bold", y=0.98)
    fig.text(0.5, 0.955,
             f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
             f"Model: 1F Gaussian Copula | Quadrature: {N_QUADRATURE} points",
             ha="center", fontsize=10, color="gray")

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # Panel 1: Base Correlation Smile
    ax1 = fig.add_subplot(gs[0, 0])
    if main_tranches:
        ax1.plot([t.detach * 100 for t in main_tranches],
                 [t.base_correlation for t in main_tranches],
                 "o-", color="#3498db", linewidth=2, markersize=6, label="Main")
    if xover_tranches:
        ax1.plot([t.detach * 100 for t in xover_tranches],
                 [t.base_correlation for t in xover_tranches],
                 "s-", color="#e74c3c", linewidth=2, markersize=6, label="Crossover")
    ax1.set_xlabel("Detachment Point (%)")
    ax1.set_ylabel("Base Correlation")
    ax1.set_title("Base Correlation Smile", fontweight="bold")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    # Panel 2: Expected Tranche Loss
    ax2 = fig.add_subplot(gs[0, 1])
    if main_tranches:
        labels_m = [t.tranche_label for t in main_tranches]
        els_m = [t.expected_loss_pct for t in main_tranches]
        x = np.arange(len(labels_m))
        ax2.bar(x - 0.2, els_m, 0.35, label="Main", color="#3498db", alpha=0.8)
    if xover_tranches:
        labels_x = [t.tranche_label for t in xover_tranches]
        els_x = [t.expected_loss_pct for t in xover_tranches]
        x2 = np.arange(len(labels_x))
        ax2.bar(x2 + 0.2, els_x, 0.35, label="Crossover", color="#e74c3c", alpha=0.8)
    ax2.set_ylabel("Expected Loss (%)")
    ax2.set_title("Tranche Expected Loss", fontweight="bold")
    combined_labels = labels_m if main_tranches else (labels_x if xover_tranches else [])
    if combined_labels:
        ax2.set_xticks(range(len(combined_labels)))
        ax2.set_xticklabels(combined_labels, fontsize=7, rotation=45)
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3, axis="y")

    # Panel 3: CS01
    ax3 = fig.add_subplot(gs[0, 2])
    if main_greeks:
        labels_mg = [g.tranche_label for g in main_greeks]
        cs01_m = [g.cs01_per_mm for g in main_greeks]
        bars = ax3.bar(np.arange(len(labels_mg)), cs01_m, 0.6, color="#3498db", alpha=0.8)
        ax3.set_xticks(np.arange(len(labels_mg)))
        ax3.set_xticklabels(labels_mg, fontsize=7, rotation=45)
    ax3.set_ylabel("CS01 ($ per $1mm)")
    ax3.set_title("Spread Delta (CS01) - Main", fontweight="bold")
    ax3.grid(True, alpha=0.3, axis="y")

    # Panel 4: Rho01
    ax4 = fig.add_subplot(gs[1, 0])
    if main_greeks:
        rho01_m = [g.rho01_per_mm for g in main_greeks]
        colors = ["#e74c3c" if r < 0 else "#2ecc71" for r in rho01_m]
        ax4.bar(range(len(main_greeks)), rho01_m, color=colors, alpha=0.8)
        ax4.set_xticks(range(len(main_greeks)))
        ax4.set_xticklabels([g.tranche_label for g in main_greeks], fontsize=7, rotation=45)
    ax4.set_ylabel("Rho01 ($ per $1mm per 1% corr)")
    ax4.set_title("Correlation Sensitivity (Rho01) - Main", fontweight="bold")
    ax4.axhline(0, color="black", linewidth=0.8)
    ax4.grid(True, alpha=0.3, axis="y")

    # Panel 5: CDS Spread Distribution
    ax5 = fig.add_subplot(gs[1, 1])
    if main_curves:
        ax5.hist([c.spread_5y_bps for c in main_curves], bins=30, alpha=0.6,
                 color="#3498db", label=f"Main (n={len(main_curves)})")
    if xover_curves:
        ax5.hist([c.spread_5y_bps for c in xover_curves], bins=30, alpha=0.6,
                 color="#e74c3c", label=f"Xover (n={len(xover_curves)})")
    ax5.set_xlabel("5Y CDS Spread (bps)")
    ax5.set_ylabel("Count")
    ax5.set_title("CDS Spread Distribution", fontweight="bold")
    ax5.legend(fontsize=8)
    ax5.grid(True, alpha=0.3, axis="y")

    # Panel 6: ECB Index Time Series
    ax6 = fig.add_subplot(gs[1, 2])
    if ecb_data and HAS_PANDAS:
        for key, series in ecb_data.items():
            label = "Main 5Y" if "main" in key else "Crossover 5Y"
            color = "#3498db" if "main" in key else "#e74c3c"
            ax6.plot(series.index, series.values, color=color, linewidth=1.5, label=label)
        ax6.set_ylabel("Spread (bps)")
        ax6.set_title("iTraxx Index Levels (ECB)", fontweight="bold")
        ax6.legend(fontsize=8)
        ax6.grid(True, alpha=0.3)
    else:
        ax6.text(0.5, 0.5, "ECB data\nnot available", ha="center", va="center",
                fontsize=12, color="gray", transform=ax6.transAxes)
        ax6.set_title("iTraxx Index Levels", fontweight="bold")

    # Panel 7: Delta Ratio
    ax7 = fig.add_subplot(gs[2, 0])
    if main_greeks:
        deltas_m = [g.delta_ratio for g in main_greeks]
        colors = ["#e74c3c" if d > 10 else "#f39c12" if d > 5 else "#2ecc71" for d in deltas_m]
        ax7.barh(range(len(main_greeks)), deltas_m, color=colors, alpha=0.8)
        ax7.set_yticks(range(len(main_greeks)))
        ax7.set_yticklabels([g.tranche_label for g in main_greeks], fontsize=8)
        ax7.axvline(1, color="black", linewidth=0.8, linestyle="--")
    ax7.set_xlabel("Delta Ratio (Tranche CS01 / Index CS01)")
    ax7.set_title("Tranche Leverage (Delta) - Main", fontweight="bold")
    ax7.grid(True, alpha=0.3, axis="x")

    # Panel 8: Summary Box
    ax8 = fig.add_subplot(gs[2, 1])
    ax8.set_xlim(0, 1)
    ax8.set_ylim(0, 1)
    ax8.axis("off")
    box = FancyBboxPatch((0.05, 0.05), 0.9, 0.9, boxstyle="round,pad=0.05",
                          facecolor="#2c3e50", alpha=0.15, edgecolor="#2c3e50", linewidth=2)
    ax8.add_patch(box)
    ax8.text(0.5, 0.92, "PRICING SUMMARY", ha="center", fontsize=13, fontweight="bold")
    y = 0.80
    if main_curves:
        avg_spd = np.mean([c.spread_5y_bps for c in main_curves])
        ax8.text(0.5, y, f"Main: {len(main_curves)} names, avg spread {avg_spd:.0f}bps",
                ha="center", fontsize=9)
        y -= 0.10
    if xover_curves:
        avg_spd = np.mean([c.spread_5y_bps for c in xover_curves])
        ax8.text(0.5, y, f"Crossover: {len(xover_curves)} names, avg spread {avg_spd:.0f}bps",
                ha="center", fontsize=9)
        y -= 0.10
    if main_greeks:
        eq_g = main_greeks[0]
        eq_t = main_tranches[0]
        ax8.text(0.5, y, f"Main Equity: EL={eq_t.expected_loss_pct:.2f}%, Delta={eq_g.delta_ratio:.1f}x",
                ha="center", fontsize=9, color="#3498db")
        y -= 0.10
    if xover_greeks:
        eq_g = xover_greeks[0]
        eq_t = xover_tranches[0]
        ax8.text(0.5, y, f"Xover Equity: EL={eq_t.expected_loss_pct:.2f}%, Delta={eq_g.delta_ratio:.1f}x",
                ha="center", fontsize=9, color="#e74c3c")
        y -= 0.10
    ax8.text(0.5, y, f"Copula: 1-Factor Gaussian, Quadrature: {N_QUADRATURE} points",
             ha="center", fontsize=9, color="gray")

    # Panel 9: Fair Spread Comparison
    ax9 = fig.add_subplot(gs[2, 2])
    if main_tranches and xover_tranches:
        n_max = max(len(main_tranches), len(xover_tranches))
        x = np.arange(n_max)
        spreads_m = [t.fair_spread_bps for t in main_tranches] + [0] * (n_max - len(main_tranches))
        spreads_x = [t.fair_spread_bps for t in xover_tranches] + [0] * (n_max - len(xover_tranches))
        labels_all = ([t.tranche_label for t in main_tranches] if len(main_tranches) >= len(xover_tranches)
                      else [t.tranche_label for t in xover_tranches])
        ax9.bar(x - 0.2, spreads_m[:n_max], 0.35, label="Main", color="#3498db", alpha=0.8)
        ax9.bar(x + 0.2, spreads_x[:n_max], 0.35, label="Crossover", color="#e74c3c", alpha=0.8)
        ax9.set_xticks(x)
        ax9.set_xticklabels(labels_all[:n_max], fontsize=7, rotation=45)
    ax9.set_ylabel("Fair Spread (bps)")
    ax9.set_title("Fair Spread by Tranche", fontweight="bold")
    ax9.legend(fontsize=8)
    ax9.grid(True, alpha=0.3, axis="y")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n  Dashboard saved: {output_path}")
    plt.close()


# ===========================================================================
# CLI
# ===========================================================================

def _load_strategist_portfolio() -> dict | None:
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


def cmd_index_spread(args):
    """Price all standard Xover tranches at the given index spread."""
    spread = args.index_spread
    rho_equity = args.equity_corr
    rho_mezz = args.mezz_corr
    rho_senior = args.senior_corr
    notional = args.notional * 1_000_000

    print(f"\n{'='*70}")
    print(f"  iTraxx XOVER TRANCHE ANALYTICS")
    print(f"  Index Spread: {spread:.0f}bps  |  Recovery: {ISDA_RECOVERY:.0%}  |"
          f"  Maturity: 5Y  |  Names: {N_NAMES_XOVER}")
    print(f"{'='*70}")

    pd = _implied_default_prob(spread, ISDA_RECOVERY, 5.0)
    print(f"\n  Implied 5Y Default Probability: {pd:.1%}")
    print(f"  Expected Portfolio Loss (LHP):  {pd*(1-ISDA_RECOVERY):.1%}")

    tranches = [
        ("0-10% Equity",       0.00, 0.10, rho_equity, 500),
        ("10-20% Mezzanine",   0.10, 0.20, rho_mezz,   0),
        ("20-35% Senior",      0.20, 0.35, rho_senior,  0),
        ("35-100% Super Senior", 0.35, 1.00, 0.80,      0),
    ]

    analytics_list = []
    for name, att, det, rho, coupon in tranches:
        a = price_tranche(att, det, spread, rho, notional=notional, running_coupon_bps=coupon)
        analytics_list.append((name, a))
        print_tranche_analytics(a, name)

    # Summary
    print(f"\n  {'='*70}")
    print(f"  TRANCHE SUMMARY")
    print(f"  {'='*70}")
    print(f"  {'Tranche':<22} {'EL%':>6} {'Spread':>8} {'Upfront':>9} "
          f"{'CS01':>10} {'Delta':>7} {'Gamma':>8} {'Leverage':>9}")
    print(f"  {'-'*22} {'-'*6} {'-'*8} {'-'*9} {'-'*10} {'-'*7} {'-'*8} {'-'*9}")
    for name, a in analytics_list:
        uf_str = f"{a.upfront_pct:.1f}%+500" if a.upfront_pct != 0 else "--"
        print(f"  {name:<22} {a.expected_loss_pct:>5.1f}% {a.fair_spread_bps:>7.0f}bp "
              f"{uf_str:>9} ${a.cs01:>9,.0f} {a.delta:>6.2f} {a.gamma:>8.4f} "
              f"{a.leverage:>8.1f}x")
    print(f"  {'='*70}")
    return analytics_list


def cmd_strategy(args):
    """Show tranche strategy analysis using portfolio hedges."""
    portfolio = _load_strategist_portfolio()
    if not portfolio:
        print("Error: No portfolio found. Run agents/strategist.py first.", file=sys.stderr)
        sys.exit(1)

    index_spread = args.index_spread or 350.0
    hedges = portfolio.get("hedges", [])

    positions = []
    for h in hedges:
        instrument = h.get("instrument", "").lower()
        if "tranche" in instrument or "equity" in instrument:
            if "equity" in instrument or "0-10" in instrument:
                tranche = "equity"
            elif "mezz" in instrument or "10-25" in instrument or "3-7" in instrument:
                tranche = "mezzanine"
            elif "senior" in instrument or "25-100" in instrument:
                tranche = "senior"
            else:
                tranche = "mezzanine"
            positions.append({
                "tranche": tranche,
                "direction": h["direction"],
                "notional": h["notional_millions"] * 1_000_000,
                "instrument": h["instrument"],
                "rationale": h.get("rationale", ""),
            })

    if not positions:
        print("\n  No tranche hedges found in strategist portfolio.")
        print("  Showing default convex hedge strategy:\n")
        positions = [{
            "tranche": "equity",
            "direction": "SHORT_RISK",
            "notional": 15_000_000,
            "instrument": "iTraxx Xover 0-10% equity tranche",
            "rationale": "Convex downside protection",
        }]

    base_correlations = {
        "equity": args.equity_corr,
        "mezzanine": args.mezz_corr,
        "senior": args.senior_corr,
    }

    print(f"\n{'='*90}")
    print(f"  iTraxx XOVER TRANCHE STRATEGY ANALYSIS")
    print(f"  Index: {index_spread:.0f}bps")
    print(f"{'='*90}")

    for p in positions:
        tag = "BUY PROTECTION" if p["direction"] == "SHORT_RISK" else "SELL PROTECTION"
        tranche_def = STANDARD_TRANCHES[p["tranche"]]
        att = tranche_def["attachment"]
        det = tranche_def["detachment"]
        print(f"\n    [{tag}] {p['instrument']}")
        print(f"      Notional: ${p['notional']/1e6:.1f}M  |  Tranche: {att*100:.0f}-{det*100:.0f}%")
        print(f"      Rationale: {p.get('rationale', 'N/A')}")

    results = tranche_strategy_analysis(index_spread, base_correlations, positions)
    print_strategy_table(results, index_spread)
    print(f"\n  {'='*90}")


def cmd_calibrate(args):
    """Calibrate base correlation from market data."""
    spread = args.index_spread
    equity_uf = args.equity_upfront

    print(f"\n{'='*60}")
    print(f"  BASE CORRELATION CALIBRATION")
    print(f"  Index: {spread:.0f}bps  |  Equity Upfront: {equity_uf:.1f}%")
    print(f"{'='*60}")

    rho = gaussian_copula_base_correlation(
        tranche_spread=equity_uf,
        attachment=0.0,
        detachment=0.10,
        index_spread=spread,
        is_upfront=True,
        running_coupon=500,
    )

    print(f"\n  Calibrated equity base correlation: {rho:.4f} ({rho:.1%})")
    a = price_tranche(0.0, 0.10, spread, rho, running_coupon_bps=500)
    print(f"  Model upfront at calibrated rho:    {a.upfront_pct:.2f}%")
    print(f"  Target upfront:                     {equity_uf:.2f}%")
    print(f"  Difference:                         {abs(a.upfront_pct - equity_uf):.4f}%")
    print(f"\n{'='*60}")


def cmd_full_report(args):
    """Full report: both indices with Greeks, visualization, and CSV export."""
    print("\n" + "=" * 70)
    print("  CDS & TRANCHE PRICER — FULL REPORT")
    print("  Gaussian Copula Engine for iTraxx Main & Crossover")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if HAS_QUANTLIB:
        print(f"  QuantLib: v{ql.__version__}")

    # ECB data
    print("\n  Fetching ECB iTraxx index data...")
    ecb_data = fetch_ecb_index_data()

    # Try Merton data, fall back to synthetic
    main_curves = []
    xover_curves = []

    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import crossover_constituents as xoc
        import merton_single_name as msn
        print("\n  Loading Crossover constituents for Merton-implied spreads...")
        xo_const = xoc.fetch_all_constituents(use_cache=True)
        success = [c for c in xo_const if c.fetch_success]
        if success:
            metrics_df = xoc.compute_equity_metrics(success)
            const_map = {c.name: c for c in success}
            merton_results = []
            for _, row in metrics_df.iterrows():
                c = const_map.get(row["name"])
                if c and c.market_cap > 0 and c.total_debt > 0:
                    result = msn.solve_merton(
                        equity_value=c.market_cap, debt_face=c.total_debt,
                        equity_vol=row["vol_252d"] / 100,
                        risk_free_rate=0.03, time_horizon=1.0,
                    )
                    if result and result.get("implied_spread_bps", 0) > 0:
                        merton_results.append({
                            "name": row["name"], "ticker": row["ticker"],
                            "sector": row["sector"], "rating": row["rating"],
                            "implied_spread_bps": result["implied_spread_bps"],
                        })
            if merton_results:
                avg_merton = np.mean([r["implied_spread_bps"] for r in merton_results])
                sf = 1.0
                if "crossover_5y" in ecb_data:
                    sf = calibrate_scaling_factor(ecb_data["crossover_5y"].iloc[-1], avg_merton)
                xover_curves = bootstrap_cds_curves_from_merton(merton_results, scaling_factor=sf)
                print(f"  Crossover CDS curves: {len(xover_curves)} names")
    except (ImportError, Exception) as e:
        print(f"  Crossover Merton data not available: {str(e)[:60]}")

    if not main_curves:
        print("\n  Using SYNTHETIC Main CDS curves (125 names, avg ~60bps)")
        main_curves = generate_synthetic_cds_curves("Main", 125, 60, 25, 0.40)
    if not xover_curves:
        print("  Using SYNTHETIC Crossover CDS curves (75 names, avg ~300bps)")
        xover_curves = generate_synthetic_cds_curves("Crossover", 75, 300, 150, 0.35)

    # Price tranches
    print("\n  Pricing Main tranches...")
    main_tranches = price_all_tranches(main_curves, "Main")
    print("\n  Pricing Crossover tranches...")
    xover_tranches = price_all_tranches(xover_curves, "Crossover")

    # Greeks
    print("\n  Computing Main Greeks...")
    main_greeks = [compute_tranche_greeks(t, main_curves) for t in main_tranches]
    print("  Computing Crossover Greeks...")
    xover_greeks = [compute_tranche_greeks(t, xover_curves) for t in xover_tranches]

    # Report
    print_full_report(main_tranches, xover_tranches, main_greeks, xover_greeks,
                       main_curves, xover_curves, ecb_data)

    # Dashboard
    if HAS_MATPLOTLIB:
        print("\n  Generating dashboard chart...")
        plot_dashboard(main_tranches, xover_tranches, main_greeks, xover_greeks,
                        main_curves, xover_curves, ecb_data)

    # CSV export
    if HAS_PANDAS:
        rows = []
        for t, g in zip(main_tranches + xover_tranches, main_greeks + xover_greeks):
            rows.append({
                "index": t.index_name, "tranche": t.tranche_label,
                "attach": t.attach, "detach": t.detach,
                "expected_loss_pct": t.expected_loss_pct,
                "fair_spread_bps": t.fair_spread_bps,
                "upfront_pct": t.upfront_pct, "running_bps": t.running_bps,
                "base_correlation": t.base_correlation,
                "risky_duration": t.risky_duration,
                "cs01_per_mm": g.cs01_per_mm, "cs02_per_mm": g.cs02_per_mm,
                "rho01_per_mm": g.rho01_per_mm, "delta_ratio": g.delta_ratio,
            })
        Path("outputs").mkdir(exist_ok=True)
        pd.DataFrame(rows).to_csv("outputs/tranche_pricing_summary.csv", index=False)
        print("  Saved: outputs/tranche_pricing_summary.csv")

    print("\n  DONE.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Gaussian Copula Tranche Pricer — iTraxx Main & Crossover"
    )
    parser.add_argument("--index-spread", type=float, default=350.0,
                        help="Index spread in bps (default: 350)")
    parser.add_argument("--strategy", action="store_true",
                        help="Show tranche strategy analysis from portfolio hedges")
    parser.add_argument("--calibrate", action="store_true",
                        help="Calibrate base correlation from market data")
    parser.add_argument("--full-report", action="store_true",
                        help="Full report: both indices, Greeks, dashboard, CSV")
    parser.add_argument("--equity-upfront", type=float, default=35.0,
                        help="Equity tranche upfront (%%) for calibration (default: 35)")
    parser.add_argument("--equity-corr", type=float, default=0.25,
                        help="Equity base correlation (default: 0.25)")
    parser.add_argument("--mezz-corr", type=float, default=0.45,
                        help="Mezzanine base correlation (default: 0.45)")
    parser.add_argument("--senior-corr", type=float, default=0.65,
                        help="Senior base correlation (default: 0.65)")
    parser.add_argument("--notional", type=float, default=10,
                        help="Tranche notional in millions (default: 10)")
    args = parser.parse_args()

    if args.full_report:
        cmd_full_report(args)
    elif args.calibrate:
        cmd_calibrate(args)
    elif args.strategy:
        cmd_strategy(args)
    else:
        cmd_index_spread(args)


if __name__ == "__main__":
    main()

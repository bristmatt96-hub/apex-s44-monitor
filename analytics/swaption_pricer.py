"""
CDS Swaption Pricer -- Black-76 + SABR Volatility Surface
==========================================================
Prices payer and receiver swaptions on iTraxx Main (5Y) and Crossover (5Y)
using the Black-76 lognormal model with SABR volatility smile calibration.

Features:
  - Forward spread derivation from flat hazard rate model
  - SABR volatility surface (Hagan et al. 2002, beta=0.5 for credit)
  - Black-76 closed-form pricing for payer/receiver swaptions
  - Analytic Greeks: delta (CS01), gamma (CS02), vega, theta
  - Payer-receiver parity validation
  - 7 pre-built multi-leg strategies (straddle, strangle, risk reversal, etc.)
  - Scenario stress testing (5 macro scenarios)
  - 7-panel matplotlib dashboard

Indices:
  iTraxx Crossover S44 (75 names, 5Y) -- HY swaptions
  iTraxx Main S44 (125 names, 5Y)     -- IG swaptions

Expiry grid: 1M, 3M, 6M, 1Y into 5Y CDS
Strike grid: ATM +/- 25, 50, 100 bps

Usage:
    python -m analytics.swaption_pricer
    python -m analytics.swaption_pricer --index Crossover --expiry 3
    python -m analytics.swaption_pricer --json
    python -m analytics.swaption_pricer --chart-only

Author: Built with Claude for macro credit trading
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize, brentq
from scipy.stats import norm

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ===========================================================================
# Constants
# ===========================================================================

INDICES = {
    "Crossover": {
        "n_names": 75,
        "tenor_years": 5,
        "recovery": 0.35,
        "ecb_key": "FM.D.U2.EUR.4F.KR.XOAC_5Y.HSTA",
        "default_spread_bps": 300,
    },
    "Main": {
        "n_names": 125,
        "tenor_years": 5,
        "recovery": 0.40,
        "ecb_key": "FM.D.U2.EUR.4F.KR.MAAC_5Y.HSTA",
        "default_spread_bps": 60,
    },
}

EXPIRY_GRID = [1, 3, 6, 12]                        # months
STRIKE_OFFSETS = [-100, -50, -25, 0, 25, 50, 100]  # bps from ATM
SABR_BETA = 0.5                                     # fixed for credit
RISK_FREE_RATE = 0.030                               # EUR risk-free

# Default ATM vols (annualised lognormal) when no market data available
DEFAULT_VOLS: dict[str, dict[int, float]] = {
    "Crossover": {1: 0.55, 3: 0.50, 6: 0.48, 12: 0.45},
    "Main":      {1: 0.45, 3: 0.42, 6: 0.40, 12: 0.38},
}

# Default SABR skew parameters when no market wing vols available
DEFAULT_SABR_SKEW: dict[str, dict[str, float]] = {
    "Crossover": {"rho": -0.30, "volvol": 0.40},
    "Main":      {"rho": -0.25, "volvol": 0.35},
}


# ===========================================================================
# Dataclasses
# ===========================================================================

@dataclass
class SwaptionSpec:
    """Defines a single CDS index swaption contract."""
    index: str              # "Crossover" or "Main"
    expiry_months: int      # option expiry in months
    tenor_years: float      # underlying CDS tenor (typically 5)
    strike_bps: float       # strike spread in bps
    is_payer: bool          # True = right to buy protection
    notional: float = 10.0  # notional in $millions


@dataclass
class SABRParams:
    """SABR calibration result for one expiry point."""
    index: str
    expiry_months: int
    forward_bps: float
    alpha: float            # vol backbone
    beta: float             # fixed 0.5 for credit
    rho: float              # skew (typically negative)
    volvol: float           # smile curvature
    atm_vol: float          # ATM implied vol (annualised)
    calibration_error: float = 0.0


@dataclass
class SwaptionPrice:
    """Pricing result for a single swaption."""
    spec: SwaptionSpec
    premium_bps_running: float
    premium_upfront_pct: float
    premium_dollar: float       # in $millions (notional units)
    implied_vol: float
    forward_spread_bps: float
    rpv01: float
    moneyness: str              # "ITM", "ATM", "OTM"
    intrinsic_value: float
    time_value: float
    exercise_probability: float


@dataclass
class SwaptionGreeks:
    """Risk sensitivities for a swaption position."""
    delta: float    # dV/dS per bp (CS01) in $K per bp
    gamma: float    # d2V/dS2 (CS02) -- convexity
    vega: float     # dV/dvol per 1% vol in $K
    theta: float    # dV/dt per day in $K
    carry: float    # net premium accrual per day in $K


@dataclass
class SwaptionStrategy:
    """Multi-leg swaption strategy with aggregated risk."""
    name: str
    description: str
    legs: list  # list of (SwaptionSpec, SwaptionPrice, SwaptionGreeks, weight)
    net_premium_dollar: float
    net_delta: float
    net_gamma: float
    net_vega: float
    net_theta: float
    max_loss: float
    breakeven_upper: float  # upper breakeven spread (bps)
    breakeven_lower: float  # lower breakeven spread (bps), 0 if N/A


# ===========================================================================
# Market Data
# ===========================================================================

def fetch_ecb_index_spreads() -> dict[str, float]:
    """
    Fetch current iTraxx Main and Crossover 5Y spreads from ECB SDW.
    Returns dict like {"Crossover": 310.5, "Main": 58.2} in bps.
    Falls back to defaults if unavailable.
    """
    result = {}
    if not HAS_REQUESTS:
        print("  WARNING: requests not available, using default spreads")
        return {idx: cfg["default_spread_bps"] for idx, cfg in INDICES.items()}

    for idx_name, cfg in INDICES.items():
        try:
            url = f"https://data-api.ecb.europa.eu/service/data/{cfg['ecb_key']}"
            params = {"startPeriod": "2024-01-01", "format": "csvdata"}
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200 and len(resp.text) > 100:
                import io
                df = pd.read_csv(io.StringIO(resp.text))
                if "OBS_VALUE" in df.columns and "TIME_PERIOD" in df.columns:
                    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
                    df = df.sort_values("TIME_PERIOD")
                    latest = float(df["OBS_VALUE"].iloc[-1])
                    result[idx_name] = latest
                    date_str = df["TIME_PERIOD"].iloc[-1].strftime("%Y-%m-%d")
                    print(f"  {idx_name} 5Y: {latest:.1f} bps (ECB SDW, {date_str})")
                    continue
        except Exception as e:
            print(f"  WARNING: ECB fetch failed for {idx_name}: {str(e)[:60]}")

        result[idx_name] = cfg["default_spread_bps"]
        print(f"  {idx_name} 5Y: {cfg['default_spread_bps']:.0f} bps (DEFAULT)")

    return result


# ===========================================================================
# Forward Spread & RPV01
# ===========================================================================

def compute_rpv01(spread_bps: float, tenor_years: float, recovery: float,
                  risk_free: float = RISK_FREE_RATE) -> float:
    """
    Risky PV01 (risky annuity) for a CDS contract.
    Flat hazard rate model with quarterly payments.
    """
    hazard = (spread_bps / 10_000) / (1.0 - recovery)
    rpv01 = 0.0
    for q in range(1, int(tenor_years * 4) + 1):
        t = q / 4.0
        surv = math.exp(-hazard * t)
        disc = math.exp(-risk_free * t)
        rpv01 += 0.25 * surv * disc
    return rpv01


def compute_forward_spread(spot_bps: float, expiry_months: int,
                            tenor_years: float, recovery: float,
                            risk_free: float = RISK_FREE_RATE) -> tuple[float, float]:
    """
    Forward CDS spread and forward RPV01.

    F = spot * RPV01_full / RPV01_forward, derived from no-arbitrage
    condition equating spot and forward protection value.

    Returns (forward_spread_bps, forward_rpv01).
    """
    t_expiry = expiry_months / 12.0
    t_total = t_expiry + tenor_years

    rpv01_full = compute_rpv01(spot_bps, t_total, recovery, risk_free)
    rpv01_front = compute_rpv01(spot_bps, t_expiry, recovery, risk_free)
    rpv01_fwd = max(rpv01_full - rpv01_front, 0.01)

    # Forward protection value from hazard rate
    hazard = (spot_bps / 10_000) / (1.0 - recovery)
    surv_expiry = math.exp(-hazard * t_expiry)
    surv_total = math.exp(-hazard * t_total)
    pv_prot_fwd = (1.0 - recovery) * (surv_expiry - surv_total)

    fwd_bps = (pv_prot_fwd / rpv01_fwd) * 10_000 if rpv01_fwd > 0 else spot_bps
    return fwd_bps, rpv01_fwd


# ===========================================================================
# SABR Volatility Model
# ===========================================================================

def sabr_implied_vol(F: float, K: float, T: float,
                      alpha: float, beta: float, rho: float,
                      volvol: float) -> float:
    """
    Hagan et al. (2002) SABR implied vol approximation.

    Parameters
    ----------
    F : forward spread (bps)
    K : strike spread (bps)
    T : time to expiry (years)
    alpha : SABR alpha (vol backbone)
    beta : SABR beta (0.5 for credit)
    rho : SABR rho (skew, typically negative for credit)
    volvol : SABR nu (smile curvature)

    Returns
    -------
    Black-76 implied volatility (annualised, decimal).
    """
    if F <= 0 or K <= 0 or T <= 1e-10 or alpha <= 0:
        return 0.0

    # ATM case
    if abs(F - K) < 1e-6:
        fk_mid = F
        term1 = alpha / (fk_mid ** (1.0 - beta))
        correction = 1.0 + (
            ((1.0 - beta) ** 2 / 24.0) * (alpha ** 2 / fk_mid ** (2.0 - 2.0 * beta))
            + 0.25 * rho * beta * volvol * alpha / (fk_mid ** (1.0 - beta))
            + (2.0 - 3.0 * rho ** 2) / 24.0 * volvol ** 2
        ) * T
        return max(term1 * correction, 1e-6)

    fk_mid = math.sqrt(F * K)
    log_fk = math.log(F / K)

    # z and x(z)
    z = (volvol / alpha) * (fk_mid ** (1.0 - beta)) * log_fk
    if abs(z) < 1e-10:
        xz = 1.0
    else:
        sqrt_term = math.sqrt(1.0 - 2.0 * rho * z + z ** 2)
        xz = z / math.log((sqrt_term + z - rho) / (1.0 - rho))

    numer = alpha
    denom = (fk_mid ** (1.0 - beta)) * (
        1.0
        + ((1.0 - beta) ** 2 / 24.0) * log_fk ** 2
        + ((1.0 - beta) ** 4 / 1920.0) * log_fk ** 4
    )
    correction = 1.0 + (
        ((1.0 - beta) ** 2 / 24.0) * (alpha ** 2 / fk_mid ** (2.0 - 2.0 * beta))
        + 0.25 * rho * beta * volvol * alpha / (fk_mid ** (1.0 - beta))
        + (2.0 - 3.0 * rho ** 2) / 24.0 * volvol ** 2
    ) * T

    vol = (numer / denom) * xz * correction
    return max(vol, 1e-6)


def _solve_sabr_alpha(F: float, T: float, beta: float,
                       rho: float, volvol: float,
                       target_atm_vol: float) -> float:
    """Invert SABR ATM vol formula to solve for alpha."""
    approx = target_atm_vol * (F ** (1.0 - beta))

    def err(a):
        if a <= 0:
            return 1e10
        return sabr_implied_vol(F, F, T, a, beta, rho, volvol) - target_atm_vol

    try:
        return max(brentq(err, approx * 0.05, approx * 10.0, xtol=1e-8), 1e-6)
    except (ValueError, RuntimeError):
        return approx


def calibrate_sabr(forward_bps: float, expiry_months: int, index: str,
                    atm_vol: float | None = None,
                    wing_vols: dict[float, float] | None = None) -> SABRParams:
    """
    Calibrate SABR parameters for one expiry point.

    Parameters
    ----------
    forward_bps : forward spread in bps
    expiry_months : option expiry in months
    index : "Crossover" or "Main"
    atm_vol : ATM implied vol (optional, uses defaults if None)
    wing_vols : {strike_offset_bps: implied_vol} for wings (optional)

    Returns
    -------
    SABRParams with calibrated alpha, rho, volvol.
    """
    T = expiry_months / 12.0
    beta = SABR_BETA

    if atm_vol is None:
        atm_vol = DEFAULT_VOLS.get(index, DEFAULT_VOLS["Crossover"]).get(
            expiry_months, 0.45)

    skew = DEFAULT_SABR_SKEW.get(index, DEFAULT_SABR_SKEW["Crossover"])

    if wing_vols is None or len(wing_vols) < 2:
        # Default skew -- solve alpha from ATM vol
        rho = skew["rho"]
        volvol = skew["volvol"]
        alpha = _solve_sabr_alpha(forward_bps, T, beta, rho, volvol, atm_vol)
        return SABRParams(
            index=index, expiry_months=expiry_months,
            forward_bps=forward_bps, alpha=alpha, beta=beta,
            rho=rho, volvol=volvol, atm_vol=atm_vol,
        )

    # Calibrate alpha, rho, volvol from ATM + wings
    def objective(params):
        a, r, v = params
        if a <= 0 or v <= 0 or abs(r) >= 1:
            return 1e10
        err = 0.0
        model_atm = sabr_implied_vol(forward_bps, forward_bps, T, a, beta, r, v)
        err += (model_atm - atm_vol) ** 2 * 4.0  # weight ATM higher
        for offset, mkt_vol in wing_vols.items():
            K = forward_bps + offset
            if K > 0:
                model_vol = sabr_implied_vol(forward_bps, K, T, a, beta, r, v)
                err += (model_vol - mkt_vol) ** 2
        return err

    alpha0 = _solve_sabr_alpha(forward_bps, T, beta, skew["rho"], skew["volvol"], atm_vol)
    res = minimize(objective, [alpha0, skew["rho"], skew["volvol"]],
                   bounds=[(1e-4, 5.0), (-0.99, 0.99), (0.01, 2.0)],
                   method="L-BFGS-B")
    a_cal, r_cal, v_cal = res.x

    return SABRParams(
        index=index, expiry_months=expiry_months,
        forward_bps=forward_bps, alpha=a_cal, beta=beta,
        rho=r_cal, volvol=v_cal, atm_vol=atm_vol,
        calibration_error=res.fun,
    )


def build_vol_surface(spot_spreads: dict[str, float],
                       user_vols: dict | None = None) -> dict[str, list[SABRParams]]:
    """
    Build SABR vol surface for all indices and expiries.

    Returns {"Crossover": [SABRParams_1M, _3M, _6M, _12M], "Main": [...]}.
    """
    surface: dict[str, list[SABRParams]] = {}
    for idx_name, spot in spot_spreads.items():
        idx_params: list[SABRParams] = []
        cfg = INDICES[idx_name]
        for exp in EXPIRY_GRID:
            fwd, _ = compute_forward_spread(spot, exp, cfg["tenor_years"], cfg["recovery"])
            atm_vol = None
            wing_vols = None
            if user_vols and idx_name in user_vols and exp in user_vols[idx_name]:
                uv = user_vols[idx_name][exp]
                atm_vol = uv.get("atm")
                wing_vols = uv.get("wings")
            params = calibrate_sabr(fwd, exp, idx_name, atm_vol, wing_vols)
            idx_params.append(params)
            print(f"  SABR {idx_name} {exp:>2}M: alpha={params.alpha:.4f} "
                  f"rho={params.rho:+.3f} volvol={params.volvol:.3f} "
                  f"ATM_vol={params.atm_vol:.1%}")
        surface[idx_name] = idx_params
    return surface


# ===========================================================================
# Black-76 Pricing Engine
# ===========================================================================

def black76_price(F: float, K: float, T: float, sigma: float,
                   rpv01: float, is_payer: bool) -> float:
    """
    Black-76 swaption price in bps-running terms.

    Payer:   RPV01 * [F*N(d1) - K*N(d2)]
    Receiver: RPV01 * [K*N(-d2) - F*N(-d1)]
    """
    if T <= 0 or sigma <= 0 or F <= 0 or K <= 0:
        if is_payer:
            return max(F - K, 0) * rpv01
        return max(K - F, 0) * rpv01

    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if is_payer:
        prem = rpv01 * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        prem = rpv01 * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

    return max(prem, 0.0)


def validate_parity(payer_price: float, receiver_price: float,
                     fwd: float, strike: float, rpv01: float,
                     tolerance: float = 0.5) -> tuple[bool, float]:
    """
    Payer - Receiver = RPV01 * (F - K).
    Returns (is_valid, error_bps).
    """
    theoretical = rpv01 * (fwd - strike)
    actual = payer_price - receiver_price
    error = abs(actual - theoretical)
    return error < tolerance, round(error, 4)


def _get_sabr_for_expiry(index: str, expiry_months: int,
                          surface: dict[str, list[SABRParams]]) -> SABRParams:
    """Find or interpolate SABR params for a given expiry."""
    params_list = surface.get(index, [])
    for p in params_list:
        if p.expiry_months == expiry_months:
            return p
    if params_list:
        return min(params_list, key=lambda p: abs(p.expiry_months - expiry_months))
    return SABRParams(
        index=index, expiry_months=expiry_months,
        forward_bps=INDICES[index]["default_spread_bps"],
        alpha=0.3, beta=SABR_BETA, rho=-0.25, volvol=0.35, atm_vol=0.45,
    )


def price_swaption(spec: SwaptionSpec,
                    sabr_surface: dict[str, list[SABRParams]],
                    spot_spreads: dict[str, float]) -> tuple[SwaptionPrice, SwaptionGreeks]:
    """
    Price a single swaption and compute Greeks.

    Returns (SwaptionPrice, SwaptionGreeks).
    """
    cfg = INDICES[spec.index]
    T = spec.expiry_months / 12.0

    fwd, rpv01 = compute_forward_spread(
        spot_spreads[spec.index], spec.expiry_months,
        spec.tenor_years, cfg["recovery"])

    sabr = _get_sabr_for_expiry(spec.index, spec.expiry_months, sabr_surface)
    iv = sabr_implied_vol(fwd, spec.strike_bps, T,
                           sabr.alpha, sabr.beta, sabr.rho, sabr.volvol)

    base_price = black76_price(fwd, spec.strike_bps, T, iv, rpv01, spec.is_payer)

    # Unit conversions
    premium_upfront = base_price / rpv01 if rpv01 > 0 else 0
    premium_dollar = premium_upfront / 10_000 * spec.notional

    # Moneyness
    if spec.is_payer:
        intrinsic = max(fwd - spec.strike_bps, 0) * rpv01
    else:
        intrinsic = max(spec.strike_bps - fwd, 0) * rpv01
    time_val = base_price - intrinsic

    if abs(fwd - spec.strike_bps) < 5:
        moneyness = "ATM"
    elif (spec.is_payer and fwd > spec.strike_bps) or (not spec.is_payer and spec.strike_bps > fwd):
        moneyness = "ITM"
    else:
        moneyness = "OTM"

    # Exercise probability
    if T > 0 and iv > 0:
        d2 = (math.log(fwd / spec.strike_bps) - 0.5 * iv ** 2 * T) / (iv * math.sqrt(T))
        ex_prob = norm.cdf(d2) if spec.is_payer else norm.cdf(-d2)
    else:
        ex_prob = 1.0 if intrinsic > 0 else 0.0

    price = SwaptionPrice(
        spec=spec,
        premium_bps_running=round(base_price, 4),
        premium_upfront_pct=round(premium_upfront / 100, 4),
        premium_dollar=round(premium_dollar, 6),
        implied_vol=round(iv, 4),
        forward_spread_bps=round(fwd, 2),
        rpv01=round(rpv01, 6),
        moneyness=moneyness,
        intrinsic_value=round(intrinsic, 4),
        time_value=round(time_val, 4),
        exercise_probability=round(ex_prob, 4),
    )

    # Greeks via finite difference
    greeks = _compute_greeks(spec, sabr, spot_spreads, fwd, rpv01, iv, T, base_price)
    return price, greeks


def _compute_greeks(spec: SwaptionSpec, sabr: SABRParams,
                     spot_spreads: dict[str, float],
                     fwd: float, rpv01: float, iv: float,
                     T: float, base_price: float) -> SwaptionGreeks:
    """Greeks via finite-difference bumps."""
    cfg = INDICES[spec.index]
    bump_s = 1.0        # 1 bp
    bump_v = 0.01       # 1% absolute
    bump_t = 1.0 / 365  # 1 day

    # Delta (CS01): bump spot +/- 1bp
    fwd_up, rpv01_up = compute_forward_spread(
        spot_spreads[spec.index] + bump_s, spec.expiry_months,
        spec.tenor_years, cfg["recovery"])
    iv_up = sabr_implied_vol(fwd_up, spec.strike_bps, T,
                              sabr.alpha, sabr.beta, sabr.rho, sabr.volvol)
    p_up = black76_price(fwd_up, spec.strike_bps, T, iv_up, rpv01_up, spec.is_payer)

    fwd_dn, rpv01_dn = compute_forward_spread(
        spot_spreads[spec.index] - bump_s, spec.expiry_months,
        spec.tenor_years, cfg["recovery"])
    iv_dn = sabr_implied_vol(fwd_dn, spec.strike_bps, T,
                              sabr.alpha, sabr.beta, sabr.rho, sabr.volvol)
    p_dn = black76_price(fwd_dn, spec.strike_bps, T, iv_dn, rpv01_dn, spec.is_payer)

    delta = (p_up - p_dn) / (2 * bump_s) * spec.notional * 1000  # $K per bp

    # Gamma (CS02)
    gamma = (p_up - 2 * base_price + p_dn) / (bump_s ** 2) * spec.notional * 1000

    # Vega
    p_v = black76_price(fwd, spec.strike_bps, T, iv + bump_v, rpv01, spec.is_payer)
    vega = (p_v - base_price) / bump_v * spec.notional * 1000

    # Theta
    T_m = max(T - bump_t, 1e-4)
    iv_t = sabr_implied_vol(fwd, spec.strike_bps, T_m,
                             sabr.alpha, sabr.beta, sabr.rho, sabr.volvol)
    p_t = black76_price(fwd, spec.strike_bps, T_m, iv_t, rpv01, spec.is_payer)
    theta = (p_t - base_price) * spec.notional * 1000

    # Carry
    carry = -base_price / (T * 365) * spec.notional * 1000 if T > 0 else 0

    return SwaptionGreeks(
        delta=round(delta, 4),
        gamma=round(gamma, 4),
        vega=round(vega, 4),
        theta=round(theta, 4),
        carry=round(carry, 4),
    )


# ===========================================================================
# Strategy Builder
# ===========================================================================

def default_strategies(index: str, spot_spread: float,
                        expiry_months: int = 3,
                        notional: float = 10.0) -> list[tuple[str, list[tuple[SwaptionSpec, float]]]]:
    """
    7 pre-built strategies for a given index.
    Returns [(name, [(SwaptionSpec, weight), ...]), ...].
    """
    K_atm = round(spot_spread)
    K_otm = round(spot_spread + 50)
    K_deep = round(spot_spread + 100)
    K_itm = round(max(spot_spread - 50, 10))

    def s(strike, is_payer, n=notional):
        return SwaptionSpec(index, expiry_months, 5.0, strike, is_payer, n)

    return [
        ("ATM Payer",       [(s(K_atm, True), +1)]),
        ("ATM Receiver",    [(s(K_atm, False), +1)]),
        ("Payer Spread",    [(s(K_atm, True), +1), (s(K_otm, True), -1)]),
        ("Straddle",        [(s(K_atm, True), +1), (s(K_atm, False), +1)]),
        ("Strangle",        [(s(K_otm, True), +1), (s(K_itm, False), +1)]),
        ("Risk Reversal",   [(s(K_otm, True), +1), (s(K_itm, False), -1)]),
        ("1x2 Payer Spread", [(s(K_atm, True), +1), (s(K_deep, True), -2)]),
    ]


def build_strategy(name: str,
                    legs: list[tuple[SwaptionSpec, float]],
                    sabr_surface: dict[str, list[SABRParams]],
                    spot_spreads: dict[str, float]) -> SwaptionStrategy:
    """Build and price a multi-leg strategy."""
    priced_legs = []
    net_prem = net_d = net_g = net_v = net_t = 0.0

    for spec, weight in legs:
        price, greeks = price_swaption(spec, sabr_surface, spot_spreads)
        priced_legs.append((spec, price, greeks, weight))
        net_prem += weight * price.premium_dollar
        net_d += weight * greeks.delta
        net_g += weight * greeks.gamma
        net_v += weight * greeks.vega
        net_t += weight * greeks.theta

    max_loss = sum(abs(w * p.premium_dollar) for _, p, _, w in priced_legs if w > 0)
    upper_be, lower_be = _find_breakevens(priced_legs, spot_spreads)
    desc = _describe_strategy(priced_legs)

    return SwaptionStrategy(
        name=name, description=desc, legs=priced_legs,
        net_premium_dollar=round(net_prem, 6),
        net_delta=round(net_d, 4),
        net_gamma=round(net_g, 4),
        net_vega=round(net_v, 4),
        net_theta=round(net_t, 4),
        max_loss=round(max_loss, 6),
        breakeven_upper=round(upper_be, 1),
        breakeven_lower=round(lower_be, 1),
    )


def _find_breakevens(priced_legs, spot_spreads) -> tuple[float, float]:
    """Grid search for upper/lower breakeven spreads at expiry."""
    if not priced_legs:
        return 0.0, 0.0

    fwd = priced_legs[0][1].forward_spread_bps
    net_cost = sum(w * p.premium_dollar for _, p, _, w in priced_legs)

    spread_range = np.linspace(max(fwd * 0.2, 10), fwd * 3, 500)
    pnls = np.zeros(len(spread_range))

    for i, s in enumerate(spread_range):
        pnl = -net_cost
        for spec, price, _, weight in priced_legs:
            if spec.is_payer:
                payoff = max(s - spec.strike_bps, 0) * price.rpv01
            else:
                payoff = max(spec.strike_bps - s, 0) * price.rpv01
            pnl += weight * payoff * spec.notional / 10_000
        pnls[i] = pnl

    upper_be = lower_be = 0.0
    sign_changes = np.where(np.diff(np.sign(pnls)))[0]
    for idx in sign_changes:
        be = spread_range[idx]
        if be > fwd:
            upper_be = be
        else:
            lower_be = be

    return upper_be, lower_be


def _describe_strategy(priced_legs) -> str:
    parts = []
    for spec, _, _, weight in priced_legs:
        action = "Buy" if weight > 0 else "Sell"
        opt = "Payer" if spec.is_payer else "Receiver"
        parts.append(f"{action} {abs(weight):.0f}x {spec.index} {spec.expiry_months}M "
                      f"{opt} K={spec.strike_bps:.0f}")
    return " | ".join(parts)


# ===========================================================================
# Scenario Stress Testing
# ===========================================================================

def stress_test_strategies(strategies: list[SwaptionStrategy],
                            spot_spreads: dict[str, float]) -> list[dict]:
    """
    Re-price strategies under 5 macro scenarios.
    Returns list of dicts for tabular display.
    """
    scenarios = _load_scenarios()

    results = []
    for strat in strategies:
        row: dict = {"strategy": strat.name, "premium": strat.net_premium_dollar}
        idx = strat.legs[0][0].index if strat.legs else "Crossover"

        for sc_key, sc in scenarios.items():
            if idx == "Crossover":
                stressed = spot_spreads.get(idx, 300) + sc["eur_hy_chg"]
            else:
                stressed = spot_spreads.get(idx, 60) + sc["eur_ig_chg"]
            stressed = max(stressed, 5)

            pnl = -strat.net_premium_dollar
            for spec, price, _, weight in strat.legs:
                if spec.is_payer:
                    payoff = max(stressed - spec.strike_bps, 0) * price.rpv01
                else:
                    payoff = max(spec.strike_bps - stressed, 0) * price.rpv01
                pnl += weight * payoff * spec.notional / 10_000
            row[sc["name"]] = round(pnl, 4)

        # Probability-weighted E[P&L]
        prob_pnl = sum(sc["prob"] * row.get(sc["name"], 0) for sc in scenarios.values())
        row["E[P&L]"] = round(prob_pnl, 4)
        results.append(row)

    return results


def _load_scenarios() -> dict:
    """Load scenarios from scenario_analysis.py or use built-in fallback."""
    try:
        from analytics.scenario_analysis import SCENARIOS as _sc
        mapped = {}
        for key, sc in _sc.items():
            mapped[key] = {
                "name": sc.name,
                "prob": sc.probability,
                "eur_hy_chg": sc.eur_hy_spread_chg,
                "eur_ig_chg": sc.us_ig_spread_chg * 0.9,
            }
        return mapped
    except (ImportError, AttributeError):
        pass

    # Built-in fallback
    return {
        "HARD_LANDING":  {"name": "HARD LANDING",  "prob": 0.15, "eur_hy_chg": +400, "eur_ig_chg": +72},
        "SOFT_LANDING":  {"name": "SOFT LANDING",  "prob": 0.35, "eur_hy_chg": +30,  "eur_ig_chg": +9},
        "NO_LANDING":    {"name": "NO LANDING",    "prob": 0.30, "eur_hy_chg": -30,  "eur_ig_chg": -9},
        "STAGFLATION":   {"name": "STAGFLATION",   "prob": 0.10, "eur_hy_chg": +200, "eur_ig_chg": +45},
        "CREDIT_CRISIS": {"name": "CREDIT CRISIS", "prob": 0.10, "eur_hy_chg": +700, "eur_ig_chg": +135},
    }


# ===========================================================================
# Charts (7 panels)
# ===========================================================================

def plot_dashboard(sabr_surface: dict[str, list[SABRParams]],
                    spot_spreads: dict[str, float],
                    strategies: list[SwaptionStrategy],
                    scenario_results: list[dict],
                    pricing_grid: dict) -> str | None:
    """
    7-panel swaption dashboard chart.
    Saves to cds_swaption_dashboard.png, returns filepath.
    """
    if not HAS_MATPLOTLIB:
        print("  WARNING: matplotlib not available, skipping chart")
        return None

    fig = plt.figure(figsize=(24, 28))
    fig.patch.set_facecolor("white")
    fig.suptitle("CDS SWAPTION PRICER — BLACK-76 + SABR",
                  fontsize=18, fontweight="bold", y=0.98)
    fig.text(0.5, 0.965,
             f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
             f"Model: Black-76 | Vol: SABR (beta={SABR_BETA})",
             ha="center", fontsize=10, color="gray")

    gs = gridspec.GridSpec(4, 2, hspace=0.35, wspace=0.30, top=0.95, bottom=0.03)

    # Colours
    c_xover = "#e74c3c"
    c_main = "#3498db"
    idx_colors = {"Crossover": c_xover, "Main": c_main}

    # --- Panel 1: Vol Surface Heatmap ---
    ax1 = fig.add_subplot(gs[0, 0])
    _plot_vol_surface(ax1, sabr_surface, spot_spreads, idx_colors)

    # --- Panel 2: Payoff Diagram ---
    ax2 = fig.add_subplot(gs[0, 1])
    _plot_payoff_diagram(ax2, strategies, spot_spreads)

    # --- Panel 3-4: Greeks Dashboard (2x2 sub-grid) ---
    gs_greeks = gridspec.GridSpecFromSubplotSpec(2, 2, subplot_spec=gs[1, 0], hspace=0.35, wspace=0.30)
    _plot_greeks_dashboard(fig, gs_greeks, pricing_grid, spot_spreads, idx_colors)

    # --- Panel 5: Scenario Heatmap ---
    ax5 = fig.add_subplot(gs[1, 1])
    _plot_scenario_heatmap(ax5, scenario_results)

    # --- Panel 6: Premium Term Structure ---
    ax6 = fig.add_subplot(gs[2, 0])
    _plot_premium_term_structure(ax6, pricing_grid, spot_spreads, idx_colors)

    # --- Panel 7: Skew Chart ---
    ax7 = fig.add_subplot(gs[2, 1])
    _plot_skew_chart(ax7, sabr_surface, spot_spreads, idx_colors)

    # --- Panel 8: Breakeven Decay ---
    ax8 = fig.add_subplot(gs[3, :])
    _plot_breakeven_decay(ax8, strategies)

    outpath = "cds_swaption_dashboard.png"
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    print(f"  Chart saved: {outpath}")
    plt.close()
    return outpath


def _plot_vol_surface(ax, sabr_surface, spot_spreads, colors):
    """Panel 1: SABR implied vol heatmap across strikes x expiries."""
    for idx_name, params_list in sabr_surface.items():
        spot = spot_spreads.get(idx_name, 100)
        vols_data = []
        for p in params_list:
            row = []
            for offset in STRIKE_OFFSETS:
                K = spot + offset
                if K > 0:
                    T = p.expiry_months / 12.0
                    v = sabr_implied_vol(p.forward_bps, K, T,
                                          p.alpha, p.beta, p.rho, p.volvol)
                    row.append(v * 100)
                else:
                    row.append(0)
            vols_data.append(row)

        vols_arr = np.array(vols_data)
        expiry_labels = [f"{p.expiry_months}M" for p in params_list]
        strike_labels = [f"{o:+d}" for o in STRIKE_OFFSETS]

        if idx_name == list(sabr_surface.keys())[0]:
            im = ax.imshow(vols_arr, cmap="YlOrRd", aspect="auto")
            ax.set_xticks(range(len(strike_labels)))
            ax.set_xticklabels(strike_labels, fontsize=8)
            ax.set_yticks(range(len(expiry_labels)))
            ax.set_yticklabels(expiry_labels, fontsize=8)
            ax.set_xlabel("Strike Offset (bps)")
            ax.set_ylabel("Expiry")

            for i in range(vols_arr.shape[0]):
                for j in range(vols_arr.shape[1]):
                    ax.text(j, i, f"{vols_arr[i, j]:.1f}",
                            ha="center", va="center", fontsize=7)

    first_idx = list(sabr_surface.keys())[0]
    ax.set_title(f"SABR Vol Surface — {first_idx} (%)", fontweight="bold")
    ax.grid(False)


def _plot_payoff_diagram(ax, strategies, spot_spreads):
    """Panel 2: Strategy P&L at expiry vs spread level."""
    if not strategies:
        ax.text(0.5, 0.5, "No strategies", ha="center", va="center")
        return

    first_idx = strategies[0].legs[0][0].index if strategies[0].legs else "Crossover"
    spot = spot_spreads.get(first_idx, 300)
    spread_range = np.linspace(max(spot * 0.3, 10), spot * 2.5, 200)

    strat_colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22"]
    for i, strat in enumerate(strategies[:7]):
        pnls = []
        for s in spread_range:
            pnl = -strat.net_premium_dollar
            for spec, price, _, weight in strat.legs:
                if spec.is_payer:
                    payoff = max(s - spec.strike_bps, 0) * price.rpv01
                else:
                    payoff = max(spec.strike_bps - s, 0) * price.rpv01
                pnl += weight * payoff * spec.notional / 10_000
            pnls.append(pnl)
        ax.plot(spread_range, pnls, color=strat_colors[i % len(strat_colors)],
                linewidth=1.5, label=strat.name, alpha=0.85)

    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.axvline(spot, color="gray", linewidth=0.8, linestyle=":", alpha=0.5)
    ax.set_xlabel("Spread at Expiry (bps)")
    ax.set_ylabel("P&L ($M)")
    ax.set_title("Strategy Payoff at Expiry", fontweight="bold")
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(True, alpha=0.3)


def _plot_greeks_dashboard(fig, gs_greeks, pricing_grid, spot_spreads, colors):
    """Panel 3-4: 4-panel Greeks (delta, gamma, vega, theta) vs strike."""
    greek_names = ["delta", "gamma", "vega", "theta"]
    greek_labels = ["Delta (CS01, $K/bp)", "Gamma (CS02)", "Vega ($K/1%vol)", "Theta ($K/day)"]

    for g_idx, (gname, glabel) in enumerate(zip(greek_names, greek_labels)):
        ax = fig.add_subplot(gs_greeks[g_idx // 2, g_idx % 2])
        for idx_name in spot_spreads:
            strikes = []
            values = []
            spot = spot_spreads[idx_name]
            for offset in STRIKE_OFFSETS:
                K = round(spot + offset)
                key = (idx_name, 3, K, True)  # 3M payer as reference
                if key in pricing_grid:
                    _, _, greeks = pricing_grid[key]
                    strikes.append(K)
                    values.append(getattr(greeks, gname))
            if strikes:
                ax.plot(strikes, values, "o-", color=colors.get(idx_name, "#666"),
                        linewidth=1.5, markersize=4, label=idx_name)
        ax.set_title(glabel, fontsize=9, fontweight="bold")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)


def _plot_scenario_heatmap(ax, scenario_results):
    """Panel 5: Strategy P&L under each scenario."""
    if not scenario_results or not HAS_PANDAS:
        ax.text(0.5, 0.5, "No scenario data", ha="center", va="center")
        return

    df = pd.DataFrame(scenario_results)
    sc_cols = [c for c in df.columns if c not in ("strategy", "premium", "E[P&L]")]
    if not sc_cols:
        return

    data = df[sc_cols].values
    strat_labels = [s[:25] for s in df["strategy"]]

    im = ax.imshow(data, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(sc_cols)))
    ax.set_xticklabels(sc_cols, fontsize=7, rotation=30, ha="right")
    ax.set_yticks(range(len(strat_labels)))
    ax.set_yticklabels(strat_labels, fontsize=7)

    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, f"{data[i, j]:.3f}",
                    ha="center", va="center", fontsize=6)

    ax.set_title("Scenario P&L ($M)", fontweight="bold")
    ax.grid(False)


def _plot_premium_term_structure(ax, pricing_grid, spot_spreads, colors):
    """Panel 6: ATM payer/receiver premium vs expiry."""
    for idx_name in spot_spreads:
        spot = spot_spreads[idx_name]
        K_atm = round(spot)
        payer_prems = []
        receiver_prems = []
        expiries = []
        for exp in EXPIRY_GRID:
            p_key = (idx_name, exp, K_atm, True)
            r_key = (idx_name, exp, K_atm, False)
            if p_key in pricing_grid and r_key in pricing_grid:
                expiries.append(exp)
                payer_prems.append(pricing_grid[p_key][1].premium_upfront_pct * 100)
                receiver_prems.append(pricing_grid[r_key][1].premium_upfront_pct * 100)

        if expiries:
            c = colors.get(idx_name, "#666")
            ax.plot(expiries, payer_prems, "o-", color=c, linewidth=2,
                    label=f"{idx_name} Payer")
            ax.plot(expiries, receiver_prems, "s--", color=c, linewidth=1.5,
                    alpha=0.6, label=f"{idx_name} Receiver")

    ax.set_xlabel("Expiry (months)")
    ax.set_ylabel("Premium (% of notional)")
    ax.set_title("ATM Premium Term Structure", fontweight="bold")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)


def _plot_skew_chart(ax, sabr_surface, spot_spreads, colors):
    """Panel 7: Implied vol smile per expiry with SABR fit."""
    for idx_name, params_list in sabr_surface.items():
        c = colors.get(idx_name, "#666")
        spot = spot_spreads.get(idx_name, 100)
        for p in params_list:
            T = p.expiry_months / 12.0
            strikes = [spot + o for o in STRIKE_OFFSETS if (spot + o) > 0]
            vols = [sabr_implied_vol(p.forward_bps, K, T,
                                      p.alpha, p.beta, p.rho, p.volvol) * 100
                    for K in strikes]
            ax.plot(strikes, vols, "o-", color=c, alpha=0.4 + 0.15 * EXPIRY_GRID.index(p.expiry_months),
                    markersize=3, linewidth=1.2,
                    label=f"{idx_name} {p.expiry_months}M" if idx_name == list(sabr_surface.keys())[0] else "")

    ax.set_xlabel("Strike (bps)")
    ax.set_ylabel("Implied Vol (%)")
    ax.set_title("SABR Vol Smile by Expiry", fontweight="bold")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)


def _plot_breakeven_decay(ax, strategies):
    """Panel 8: Breakeven spread vs time-to-expiry for payer strategies."""
    strat_colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6"]
    payer_strats = [s for s in strategies if s.breakeven_upper > 0][:5]

    if not payer_strats:
        ax.text(0.5, 0.5, "No payer strategies with breakevens", ha="center", va="center")
        return

    for i, strat in enumerate(payer_strats):
        if not strat.legs:
            continue
        spec0 = strat.legs[0][0]
        T_full = spec0.expiry_months / 12.0
        days = np.linspace(1, spec0.expiry_months * 30, 50)
        breakevens = []
        for d in days:
            t_remaining = max((T_full - d / 365), 0.001)
            # Approximate: breakeven widens as time value decays
            time_fraction = t_remaining / T_full
            be = strat.breakeven_upper + (1 - time_fraction) * 20  # spread widens with decay
            breakevens.append(be)

        ax.plot(days, breakevens, color=strat_colors[i % len(strat_colors)],
                linewidth=2, label=strat.name)

    ax.set_xlabel("Days from Now")
    ax.set_ylabel("Breakeven Spread (bps)")
    ax.set_title("Breakeven Decay — Payer Strategies", fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)


# ===========================================================================
# Console Report
# ===========================================================================

def print_report(spot_spreads: dict[str, float],
                  sabr_surface: dict[str, list[SABRParams]],
                  pricing_grid: dict,
                  strategies: list[SwaptionStrategy],
                  scenario_results: list[dict]):
    """Print formatted console report."""
    print("\n" + "=" * 70)
    print("  CDS SWAPTION PRICER -- BLACK-76 + SABR")
    print("=" * 70)
    print(f"  Timestamp:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Model:      Black-76 lognormal | SABR beta={SABR_BETA}")
    print(f"  Risk-Free:  {RISK_FREE_RATE:.1%}")
    print()

    # Market data
    print("  MARKET DATA")
    print("  " + "-" * 40)
    for idx, s in spot_spreads.items():
        cfg = INDICES[idx]
        fwd_3m, rpv01_3m = compute_forward_spread(s, 3, cfg["tenor_years"], cfg["recovery"])
        print(f"  {idx:>12}: spot={s:>7.1f}  fwd_3M={fwd_3m:>7.1f}  RPV01={rpv01_3m:.4f}")
    print()

    # SABR surface summary
    print("  SABR VOLATILITY SURFACE")
    print("  " + "-" * 40)
    for idx, params_list in sabr_surface.items():
        for p in params_list:
            print(f"  {idx:>12} {p.expiry_months:>2}M: a={p.alpha:.4f}  "
                  f"rho={p.rho:+.3f}  nu={p.volvol:.3f}  ATM={p.atm_vol:.1%}")
    print()

    # Parity checks
    print("  PAYER-RECEIVER PARITY CHECKS")
    print("  " + "-" * 40)
    violations = 0
    checks = 0
    for idx in spot_spreads:
        for exp in EXPIRY_GRID:
            for offset in STRIKE_OFFSETS:
                K = round(spot_spreads[idx] + offset)
                if K <= 0:
                    continue
                p_key = (idx, exp, K, True)
                r_key = (idx, exp, K, False)
                if p_key in pricing_grid and r_key in pricing_grid:
                    pp = pricing_grid[p_key][1]
                    rp = pricing_grid[r_key][1]
                    ok, err = validate_parity(
                        pp.premium_bps_running, rp.premium_bps_running,
                        pp.forward_spread_bps, K, pp.rpv01)
                    checks += 1
                    if not ok:
                        violations += 1
    print(f"  Checked: {checks} | Violations: {violations}")
    print()

    # Strategy summary
    print("  STRATEGY SUMMARY")
    print("  " + "-" * 68)
    print(f"  {'Strategy':<30} {'Prem($M)':>9} {'Delta':>8} {'Gamma':>8} {'Vega':>8} {'Theta':>8}")
    print("  " + "-" * 68)
    for s in strategies:
        print(f"  {s.name:<30} {s.net_premium_dollar:>9.4f} {s.net_delta:>8.2f} "
              f"{s.net_gamma:>8.2f} {s.net_vega:>8.2f} {s.net_theta:>8.2f}")
    print()

    # Scenario table
    if scenario_results:
        print("  SCENARIO STRESS TEST")
        print("  " + "-" * 68)
        sc_keys = [k for k in scenario_results[0] if k not in ("strategy", "premium")]
        header = f"  {'Strategy':<25} " + " ".join(f"{k:>10}" for k in sc_keys)
        print(header)
        print("  " + "-" * 68)
        for row in scenario_results:
            vals = " ".join(f"{row.get(k, 0):>10.3f}" for k in sc_keys)
            print(f"  {row['strategy']:<25} {vals}")
    print()


# ===========================================================================
# Main Pipeline
# ===========================================================================

def run_analysis(index: str = "Both", expiry_months: int = 3,
                  output_json: bool = False, chart_only: bool = False) -> dict:
    """
    Full swaption analysis pipeline.

    Parameters
    ----------
    index : "Both", "Crossover", or "Main"
    expiry_months : default expiry for strategies
    output_json : if True, return dict instead of printing
    chart_only : if True, skip report and just generate chart

    Returns
    -------
    dict with keys: spot_spreads, strategies, scenario_results, pricing_grid, chart_path
    """
    print("\n" + "=" * 70)
    print("  CDS SWAPTION PRICER")
    print("  Black-76 + SABR Volatility Surface")
    print("=" * 70)

    # 1. Market data
    print("\n  Step 1: Fetching market data...")
    spot_spreads = fetch_ecb_index_spreads()
    if index != "Both":
        spot_spreads = {k: v for k, v in spot_spreads.items() if k == index}

    # 2. SABR calibration
    print("\n  Step 2: Calibrating SABR vol surface...")
    sabr_surface = build_vol_surface(spot_spreads)

    # 3. Price full grid
    print("\n  Step 3: Pricing swaption grid...")
    pricing_grid: dict = {}
    n_priced = 0
    for idx in spot_spreads:
        for exp in EXPIRY_GRID:
            for offset in STRIKE_OFFSETS:
                K = round(spot_spreads[idx] + offset)
                if K <= 0:
                    continue
                for is_payer in [True, False]:
                    spec = SwaptionSpec(idx, exp, 5.0, K, is_payer)
                    price, greeks = price_swaption(spec, sabr_surface, spot_spreads)
                    pricing_grid[(idx, exp, K, is_payer)] = (spec, price, greeks)
                    n_priced += 1
    print(f"  Priced {n_priced} swaptions across grid")

    # 4. Build strategies
    print("\n  Step 4: Building strategies...")
    all_strategies: list[SwaptionStrategy] = []
    for idx in spot_spreads:
        strats = default_strategies(idx, spot_spreads[idx], expiry_months)
        for name, legs in strats:
            strategy = build_strategy(f"{idx} {name}", legs, sabr_surface, spot_spreads)
            all_strategies.append(strategy)
    print(f"  Built {len(all_strategies)} strategies")

    # 5. Scenario stress test
    print("\n  Step 5: Scenario stress testing...")
    scenario_results = stress_test_strategies(all_strategies, spot_spreads)

    # 6. Report
    if not chart_only:
        print_report(spot_spreads, sabr_surface, pricing_grid,
                      all_strategies, scenario_results)

    # 7. Chart
    print("\n  Step 6: Generating dashboard chart...")
    chart_path = plot_dashboard(sabr_surface, spot_spreads,
                                 all_strategies, scenario_results, pricing_grid)

    # 8. CSV export
    if HAS_PANDAS and not output_json:
        _export_csvs(all_strategies, scenario_results, pricing_grid, spot_spreads)

    print("\n  DONE.\n")

    return {
        "spot_spreads": spot_spreads,
        "strategies": [asdict(s) if hasattr(s, '__dataclass_fields__') else s for s in all_strategies],
        "scenario_results": scenario_results,
        "n_priced": n_priced,
        "chart_path": chart_path,
    }


def _export_csvs(strategies, scenario_results, pricing_grid, spot_spreads):
    """Export strategy and pricing CSVs."""
    # Strategy summary
    rows = []
    for s in strategies:
        rows.append({
            "strategy": s.name, "premium_$M": s.net_premium_dollar,
            "delta": s.net_delta, "gamma": s.net_gamma,
            "vega": s.net_vega, "theta": s.net_theta,
            "max_loss": s.max_loss,
            "be_upper": s.breakeven_upper, "be_lower": s.breakeven_lower,
        })
    pd.DataFrame(rows).to_csv("swaption_strategies.csv", index=False)
    print(f"  Saved: swaption_strategies.csv")

    # Scenario results
    pd.DataFrame(scenario_results).to_csv("swaption_scenarios.csv", index=False)
    print(f"  Saved: swaption_scenarios.csv")

    # Pricing grid
    grid_rows = []
    for (idx, exp, K, is_payer), (spec, price, greeks) in pricing_grid.items():
        grid_rows.append({
            "index": idx, "expiry_months": exp, "strike_bps": K,
            "type": "Payer" if is_payer else "Receiver",
            "premium_running": price.premium_bps_running,
            "premium_upfront_%": price.premium_upfront_pct,
            "implied_vol": price.implied_vol,
            "forward": price.forward_spread_bps,
            "moneyness": price.moneyness,
            "exercise_prob": price.exercise_probability,
            "delta": greeks.delta, "gamma": greeks.gamma,
            "vega": greeks.vega, "theta": greeks.theta,
        })
    pd.DataFrame(grid_rows).to_csv("swaption_pricing_grid.csv", index=False)
    print(f"  Saved: swaption_pricing_grid.csv")


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CDS Swaption Pricer -- Black-76 + SABR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--index", type=str, default="Both",
                        choices=["Both", "Crossover", "Main"],
                        help="Index to price (default: Both)")
    parser.add_argument("--expiry", type=int, default=3,
                        choices=[1, 3, 6, 12],
                        help="Default strategy expiry in months (default: 3)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--chart-only", action="store_true",
                        help="Generate chart only, skip detailed report")
    args = parser.parse_args()

    result = run_analysis(
        index=args.index,
        expiry_months=args.expiry,
        output_json=args.json,
        chart_only=args.chart_only,
    )

    if args.json:
        # Serialise for JSON output (strip non-serialisable objects)
        out = {
            "spot_spreads": result["spot_spreads"],
            "n_priced": result["n_priced"],
            "scenario_results": result["scenario_results"],
            "chart_path": result["chart_path"],
        }
        print(json.dumps(out, indent=2, default=str))

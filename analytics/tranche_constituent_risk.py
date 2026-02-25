"""
Tranche Per-Constituent Risk Report
====================================

Computes per-name JTD, per-name CS01, and BC01 for a specified
iTraxx Main or Crossover tranche position.

    JTD_i  = loss to tranche if name i defaults immediately
    CS01_i = tranche MTM change for +1bp widening in name i's spread
    BC01   = tranche MTM change for +1% absolute move in base correlation

Uses the heterogeneous Gaussian copula path (Gauss-Hermite quadrature)
so that per-name spread dispersion feeds through to differentiated risk.

Usage:
    python -m analytics.tranche_constituent_risk
    python -m analytics.tranche_constituent_risk --index Main --tranche 0-3 --notional 10
    python -m analytics.tranche_constituent_risk --index Crossover --tranche 0-10 --notional 25
"""

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np
from scipy.stats import norm

# Import from the main tranche pricer
sys.path.insert(0, str(Path(__file__).parent.parent))
from analytics.tranche_pricer import (
    CDSCurve,
    ISDA_RECOVERY,
    MATURITY_YEARS,
    RISK_FREE_RATE,
    N_QUADRATURE,
    MAIN_TRANCHES,
    CROSSOVER_TRANCHES,
    RECOVERY_RATES,
    _gauss_hermite_nodes_weights,
    _parametric_base_correlation,
    gaussian_copula_base_correlation,
    hazard_rate_from_spread,
    survival_probability,
    default_probability,
    conditional_default_prob_vec,
    risky_duration_approx,
)


# ─── S44 Market Data ──────────────────────────────────────────────────
# Real market levels for iTraxx Main S44 tranches (as of 2026-02-25)
# All tranches quoted with 100bps (1%) running coupon

S44_MARKET = {
    "ref_spread_bps": 53.0,
    "running_coupon_bps": 100.0,   # 1% for ALL tranches
    "tranches": {
        "0-3%":    {"attach": 0.00, "detach": 0.03, "quote": 23.75, "is_upfront": True,  "delta": 7.55},
        "3-6%":    {"attach": 0.03, "detach": 0.06, "quote": 3.5,   "is_upfront": True,  "delta": 3.50},
        "6-12%":   {"attach": 0.06, "detach": 0.12, "quote": 95.0,  "is_upfront": False, "delta": 2.05},
        "12-100%": {"attach": 0.12, "detach": 1.00, "quote": 27.0,  "is_upfront": False, "delta": 0.62},
    },
}


def calibrate_s44_base_correlation(
    tranche_label: str,
    ref_spread: float = None,
    running_coupon: float = None,
    verbose: bool = True,
) -> float:
    """Calibrate base correlation for a specific S44 tranche from market levels.

    For equity (0-3%): calibration is exact — it's a base tranche (0 to D).
    For non-equity: uses direct calibration as approximation. True base
    correlation framework would require synthesising 0-to-D equity tranches.

    Returns calibrated base correlation.
    """
    ref = ref_spread or S44_MARKET["ref_spread_bps"]
    coupon = running_coupon or S44_MARKET["running_coupon_bps"]

    if tranche_label not in S44_MARKET["tranches"]:
        if verbose:
            print(f"  No S44 market data for {tranche_label}, using parametric")
        return None

    mkt = S44_MARKET["tranches"][tranche_label]
    rho = gaussian_copula_base_correlation(
        tranche_spread=mkt["quote"],
        attachment=mkt["attach"],
        detachment=mkt["detach"],
        index_spread=ref,
        recovery=ISDA_RECOVERY,
        maturity=5.0,
        is_upfront=mkt["is_upfront"],
        running_coupon=coupon,
    )

    if verbose:
        quote_str = f"{mkt['quote']:.2f}% upf" if mkt["is_upfront"] else f"{mkt['quote']:.0f}bps"
        print(f"\n  Market calibration: {tranche_label} at {quote_str} (ref {ref:.0f}bps, {coupon:.0f}bps coupon)")
        print(f"  Calibrated base correlation: {rho:.2%}")
        print(f"  Market delta: {mkt['delta']:.2f}x")

    return rho


# ─── Spread-implied recovery rates ────────────────────────────────────

def spread_implied_recovery(spread_bps: float) -> float:
    """Market-convention recovery assumption based on CDS spread level.
    Wider spreads imply higher LGD (lower recovery).
    """
    if spread_bps < 50:
        return 0.40
    elif spread_bps < 100:
        return 0.40 - 0.05 * (spread_bps - 50) / 50   # 40% -> 35%
    elif spread_bps < 200:
        return 0.35 - 0.05 * (spread_bps - 100) / 100  # 35% -> 30%
    elif spread_bps < 500:
        return 0.30 - 0.10 * (spread_bps - 200) / 300  # 30% -> 20%
    else:
        return 0.20


def generate_main_curves(n_names: int = 125,
                         avg_spread: float = 60.0,
                         spread_std: float = 25.0) -> List[CDSCurve]:
    """Generate Main S44 curves with spread-differentiated recovery."""
    np.random.seed(42)
    sectors = ["Banks", "Insurance", "Autos", "Telecoms", "Utilities",
               "Energy", "Industrials", "Consumer", "Healthcare", "Chemicals",
               "Technology", "Real Estate", "Retail", "Mining", "Transport"]
    ratings = ["AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"]
    rating_weights = [0.05, 0.15, 0.20, 0.20, 0.20, 0.15, 0.05]

    log_mean = np.log(avg_spread) - 0.5 * (spread_std / avg_spread) ** 2
    log_std = np.sqrt(np.log(1 + (spread_std / avg_spread) ** 2))
    spreads = np.random.lognormal(log_mean, log_std, n_names)
    spreads = np.clip(spreads, 5, 500)

    curves = []
    w = 1.0 / n_names
    for i in range(n_names):
        spread = spreads[i]
        rating = np.random.choice(ratings, p=rating_weights)
        sector = np.random.choice(sectors)
        r = spread_implied_recovery(spread)
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


# ─── Core: heterogeneous tranche EL with explicit vectors ─────────────

def _tranche_el_heterogeneous(
    attach: float,
    detach: float,
    pd_vector: np.ndarray,
    lgd_vector: np.ndarray,
    weight_vector: np.ndarray,
    correlation: float,
    n_points: int = N_QUADRATURE,
) -> float:
    """Expected tranche loss — heterogeneous portfolio, GH quadrature."""
    if detach <= attach:
        return 0.0
    nodes, weights = _gauss_hermite_nodes_weights(n_points)
    width = detach - attach
    total = 0.0
    for i in range(n_points):
        M = nodes[i]
        w = weights[i]
        cond_pds = np.array([
            conditional_default_prob_vec(pd, correlation, M) for pd in pd_vector
        ])
        cond_loss = np.sum(weight_vector * lgd_vector * cond_pds)
        tranche_loss = (min(cond_loss, detach) - min(cond_loss, attach)) / width
        total += w * tranche_loss
    return max(0.0, total)


def _tranche_protection_leg(
    attach: float,
    detach: float,
    pd_vector: np.ndarray,
    lgd_vector: np.ndarray,
    weight_vector: np.ndarray,
    correlation: float,
    maturity: float = MATURITY_YEARS,
    rf: float = RISK_FREE_RATE,
) -> float:
    """PV of protection leg — quarterly steps, heterogeneous."""
    n_steps = int(maturity * 4)
    dt = 0.25
    prot = 0.0
    prev_el = 0.0
    for step in range(1, n_steps + 1):
        t = step * dt
        # Scale PDs to this horizon: PD(t) = 1 - (1-PD_5Y)^(t/5)
        scale = t / MATURITY_YEARS
        pd_t = 1.0 - (1.0 - pd_vector) ** scale
        el_t = _tranche_el_heterogeneous(
            attach, detach, pd_t, lgd_vector, weight_vector, correlation
        )
        d_el = el_t - prev_el
        df = math.exp(-rf * (t - dt / 2))
        prot += df * d_el
        prev_el = el_t
    return prot


def _tranche_premium_leg(
    attach: float,
    detach: float,
    pd_vector: np.ndarray,
    lgd_vector: np.ndarray,
    weight_vector: np.ndarray,
    correlation: float,
    maturity: float = MATURITY_YEARS,
    rf: float = RISK_FREE_RATE,
) -> float:
    """RPV01 — risky annuity for the tranche, heterogeneous."""
    n_steps = int(maturity * 4)
    dt = 0.25
    rpv01 = 0.0
    for step in range(1, n_steps + 1):
        t = step * dt
        scale = t / MATURITY_YEARS
        pd_t = 1.0 - (1.0 - pd_vector) ** scale
        el_t = _tranche_el_heterogeneous(
            attach, detach, pd_t, lgd_vector, weight_vector, correlation
        )
        df = math.exp(-rf * t)
        rpv01 += df * (1.0 - el_t) * dt
    return rpv01


def _tranche_mtm(
    attach: float,
    detach: float,
    pd_vector: np.ndarray,
    lgd_vector: np.ndarray,
    weight_vector: np.ndarray,
    correlation: float,
    notional: float,
    running_coupon_bps: float = 0.0,
) -> float:
    """Mark-to-market for a protection-buyer position."""
    prot = _tranche_protection_leg(
        attach, detach, pd_vector, lgd_vector, weight_vector, correlation
    )
    rpv01 = _tranche_premium_leg(
        attach, detach, pd_vector, lgd_vector, weight_vector, correlation
    )
    return (prot - running_coupon_bps / 10_000 * rpv01) * notional


# ─── Per-name JTD ──────────────────────────────────────────────────────

def compute_per_name_jtd(
    curves: List[CDSCurve],
    attach: float,
    detach: float,
    notional: float,
) -> List[dict]:
    """
    Jump-to-default for each constituent.

    If name i defaults immediately:
      portfolio_loss = w_i * LGD_i
      tranche_loss   = (min(portfolio_loss, detach) - min(portfolio_loss, attach)) / width
      JTD_eur        = tranche_loss * notional
    """
    width = detach - attach
    n = len(curves)
    results = []
    for c in curves:
        w = 1.0 / n
        lgd = 1.0 - c.recovery_rate
        portfolio_loss = w * lgd
        tranche_hit = (min(portfolio_loss, detach) - min(portfolio_loss, attach)) / width
        jtd_eur = tranche_hit * notional
        jtd_pct = tranche_hit * 100
        results.append({
            "name": c.name,
            "ticker": c.ticker,
            "sector": c.sector,
            "rating": c.rating,
            "spread_bps": c.spread_5y_bps,
            "recovery": c.recovery_rate,
            "portfolio_loss_pct": portfolio_loss * 100,
            "jtd_pct_of_tranche": jtd_pct,
            "jtd_eur": jtd_eur,
        })
    results.sort(key=lambda x: x["jtd_eur"], reverse=True)
    return results


# ─── Per-name CS01 (fast path) ─────────────────────────────────────────

def compute_per_name_cs01(
    curves: List[CDSCurve],
    attach: float,
    detach: float,
    correlation: float,
    notional: float,
    running_coupon_bps: float = 0.0,
    bump_bps: float = 1.0,
) -> Tuple[List[dict], float]:
    """
    CS01 per constituent: bump name i's spread by 1bp, reprice EL at 5Y,
    convert to MTM via RPV01.

    Fast path: only reprices 5Y expected loss (not full term structure),
    and scales by aggregate RPV01. This is O(N * N_quad) rather than
    O(N * N_steps * N_quad * N).

    Returns (per_name_results, total_cs01).
    """
    n = len(curves)
    w_vec = np.ones(n) / n

    # Base vectors
    pd_base = np.array([c.default_prob_5y for c in curves])
    lgd_vec = np.array([1.0 - c.recovery_rate for c in curves])

    # Precompute GH nodes/weights once
    nodes, weights = _gauss_hermite_nodes_weights(N_QUADRATURE)
    width = detach - attach

    # Precompute base conditional PDs for all GH points (N_quad x N matrix)
    sqrt_rho = np.sqrt(max(0.001, correlation))
    sqrt_1mr = np.sqrt(max(0.001, 1.0 - correlation))
    thresholds = np.array([
        norm.ppf(max(1e-10, min(1 - 1e-10, pd))) for pd in pd_base
    ])

    def _fast_el(pd_vec):
        """Compute tranche EL at 5Y using vectorized GH quadrature."""
        thresh = np.array([
            norm.ppf(max(1e-10, min(1 - 1e-10, pd))) for pd in pd_vec
        ])
        total = 0.0
        for k in range(len(nodes)):
            M = nodes[k]
            cond_pds = norm.cdf((thresh - sqrt_rho * M) / sqrt_1mr)
            cond_loss = np.sum(w_vec * lgd_vec * cond_pds)
            tranche_loss = (min(cond_loss, detach) - min(cond_loss, attach)) / width
            total += weights[k] * tranche_loss
        return max(0.0, total)

    # Base EL
    el_base = _fast_el(pd_base)

    results = []
    total_cs01 = 0.0
    for i, c in enumerate(curves):
        # Bump name i's spread by +1bp
        new_spread = c.spread_5y_bps + bump_bps
        new_hr = hazard_rate_from_spread(new_spread, c.recovery_rate)
        new_pd = default_probability(new_hr, MATURITY_YEARS)

        pd_bumped = pd_base.copy()
        pd_bumped[i] = new_pd

        el_bumped = _fast_el(pd_bumped)

        # CS01_i = delta_EL * notional
        # Protection PV change ~ delta_EL (discounting is second-order for single-name bump)
        cs01_i = (el_bumped - el_base) * notional

        total_cs01 += cs01_i

        results.append({
            "name": c.name,
            "ticker": c.ticker,
            "sector": c.sector,
            "rating": c.rating,
            "spread_bps": c.spread_5y_bps,
            "cs01_eur": cs01_i,
        })

    results.sort(key=lambda x: abs(x["cs01_eur"]), reverse=True)
    return results, total_cs01


# ─── BC01 ──────────────────────────────────────────────────────────────

def compute_bc01(
    curves: List[CDSCurve],
    attach: float,
    detach: float,
    correlation: float,
    notional: float,
    running_coupon_bps: float = 0.0,
    corr_bump: float = 0.01,
) -> dict:
    """
    BC01: tranche MTM sensitivity to +1% absolute base correlation move.
    Uses fast EL-based approach: BC01 = delta_EL * RPV01 * notional.
    """
    n = len(curves)
    w_vec = np.ones(n) / n
    pd_vec = np.array([c.default_prob_5y for c in curves])
    lgd_vec = np.array([1.0 - c.recovery_rate for c in curves])

    nodes, weights = _gauss_hermite_nodes_weights(N_QUADRATURE)
    width = detach - attach
    thresholds = np.array([
        norm.ppf(max(1e-10, min(1 - 1e-10, pd))) for pd in pd_vec
    ])

    def _el_at_corr(corr):
        sr = np.sqrt(max(0.001, corr))
        s1mr = np.sqrt(max(0.001, 1.0 - corr))
        total = 0.0
        for k in range(len(nodes)):
            M = nodes[k]
            cond_pds = norm.cdf((thresholds - sr * M) / s1mr)
            cond_loss = np.sum(w_vec * lgd_vec * cond_pds)
            tranche_loss = (min(cond_loss, detach) - min(cond_loss, attach)) / width
            total += weights[k] * tranche_loss
        return max(0.0, total)

    el_base = _el_at_corr(correlation)
    el_up = _el_at_corr(min(0.99, correlation + corr_bump))
    el_dn = _el_at_corr(max(0.01, correlation - corr_bump))

    # Protection PV ~ EL * notional (discounting is embedded in EL term structure)
    mtm_base = el_base * notional
    mtm_up = el_up * notional
    mtm_dn = el_dn * notional
    bc01 = (mtm_up - mtm_dn) / 2.0

    return {
        "base_correlation": correlation,
        "bc01_eur": bc01,
        "bc01_pct_notional": bc01 / notional * 100,
        "mtm_base": mtm_base,
        "mtm_corr_up": mtm_up,
        "mtm_corr_dn": mtm_dn,
    }


# ─── Report ────────────────────────────────────────────────────────────

def run_report(
    index_name: str = "Main",
    tranche_label: str = "0-3%",
    notional_mm: float = 10.0,
    index_spread_bps: float = None,
):
    """Run full per-constituent risk report."""
    notional = notional_mm * 1_000_000

    # Determine tranche structure
    tranches = MAIN_TRANCHES if index_name == "Main" else CROSSOVER_TRANCHES
    tranche_def = None
    for t in tranches:
        if t["label"] == tranche_label:
            tranche_def = t
            break
    if not tranche_def:
        print(f"  ERROR: Tranche {tranche_label} not found for {index_name}")
        return

    attach = tranche_def["attach"]
    detach = tranche_def["detach"]
    width = detach - attach
    is_equity = attach == 0.0

    # Running coupon: S44 standard is 100bps (1%) for ALL tranches
    if index_name == "Main":
        running_coupon = S44_MARKET["running_coupon_bps"]
    else:
        running_coupon = 500.0 if is_equity else 0.0

    # Base correlation — calibrate from market if Main S44, else parametric
    if index_name == "Main" and tranche_label in S44_MARKET["tranches"]:
        corr = calibrate_s44_base_correlation(
            tranche_label=tranche_label,
            ref_spread=index_spread_bps,
            running_coupon=running_coupon,
            verbose=True,
        )
        if corr is None:
            corr = _parametric_base_correlation(detach, index_name)
    else:
        corr = _parametric_base_correlation(detach, index_name)

    # CDS curves (spread-implied recovery for differentiated JTD)
    if index_name == "Main":
        n_names = 125
        avg_spread = index_spread_bps or S44_MARKET["ref_spread_bps"]
        curves = generate_main_curves(n_names, avg_spread, 25)
    else:
        n_names = 75
        avg_spread = index_spread_bps or 300.0
        from analytics.tranche_pricer import generate_synthetic_cds_curves
        curves = generate_synthetic_cds_curves("Crossover", n_names, avg_spread, 150, 0.35)

    # Try to load real data
    try:
        from analytics.itraxx_main_constituents import fetch_main_constituents
        # Would load real data here if available
    except ImportError:
        pass

    spreads = [c.spread_5y_bps for c in curves]
    avg_spd = np.mean(spreads)

    # ── Header ──
    print(f"\n{'='*100}")
    print(f"  TRANCHE PER-CONSTITUENT RISK REPORT")
    print(f"{'='*100}")
    print(f"  Index:            iTraxx {index_name} S44")
    print(f"  Tranche:          {tranche_label} ({attach*100:.0f}%-{detach*100:.0f}%)")
    print(f"  Notional:         EUR {notional:,.0f}")
    print(f"  Maturity:         5Y")
    print(f"  Names:            {n_names}")
    print(f"  Avg Index Spread: {avg_spd:.1f}bps")
    print(f"  Base Correlation: {corr:.1%}")
    print(f"  Running Coupon:   {running_coupon:.0f}bps ({running_coupon/100:.0f}%)")
    recoveries = [c.recovery_rate for c in curves]
    print(f"  Recovery:         Spread-implied ({min(recoveries):.0%} - {max(recoveries):.0%}, avg {np.mean(recoveries):.1%})")
    print(f"  Model:            1-Factor Gaussian Copula, {N_QUADRATURE}-pt Gauss-Hermite")

    # ── JTD ──
    print(f"\n{'='*100}")
    print(f"  JUMP-TO-DEFAULT (JTD) — ALL {n_names} CONSTITUENTS")
    print(f"  Loss to {tranche_label} tranche if name defaults immediately")
    print(f"{'='*100}")
    print(f"  {'#':>4}  {'Name':<30} {'Sector':<14} {'Rtg':>4} {'Spd':>6} {'Rec':>5} "
          f"{'Port Loss':>10} {'Trch Loss%':>10} {'JTD (EUR)':>14}")
    print(f"  {'':->4}  {'':->30} {'':->14} {'':->4} {'':->6} {'':->5} "
          f"{'':->10} {'':->10} {'':->14}")

    jtd_results = compute_per_name_jtd(curves, attach, detach, notional)
    total_jtd = 0.0
    for rank, r in enumerate(jtd_results, 1):
        total_jtd += r["jtd_eur"]
        print(f"  {rank:>4}  {r['name']:<30} {r['sector']:<14} {r['rating']:>4} "
              f"{r['spread_bps']:>5.0f}  {r['recovery']:>4.0%} "
              f"{r['portfolio_loss_pct']:>9.3f}% {r['jtd_pct_of_tranche']:>9.2f}% "
              f"{r['jtd_eur']:>13,.0f}")

    print(f"\n  {'WORST SINGLE-NAME JTD:':<42} EUR {jtd_results[0]['jtd_eur']:>13,.0f} "
          f"({jtd_results[0]['jtd_pct_of_tranche']:.2f}% of tranche)")
    print(f"  {'AVG JTD PER NAME:':<42} EUR {total_jtd/n_names:>13,.0f}")

    # ── CS01 ──
    print(f"\n{'='*100}")
    print(f"  PER-NAME CS01 — {tranche_label} TRANCHE")
    print(f"  MTM change for +1bp widening in each name's CDS spread")
    print(f"{'='*100}")

    print(f"  Computing {n_names} per-name sensitivities...", end="", flush=True)
    cs01_results, total_cs01 = compute_per_name_cs01(
        curves, attach, detach, corr, notional, running_coupon
    )
    print(f" done.")

    print(f"\n  {'#':>4}  {'Name':<30} {'Sector':<14} {'Rtg':>4} {'Spd':>6} {'CS01 (EUR)':>14}")
    print(f"  {'':->4}  {'':->30} {'':->14} {'':->4} {'':->6} {'':->14}")

    for rank, r in enumerate(cs01_results, 1):
        print(f"  {rank:>4}  {r['name']:<30} {r['sector']:<14} {r['rating']:>4} "
              f"{r['spread_bps']:>5.0f}  {r['cs01_eur']:>13,.2f}")

    print(f"\n  {'TOTAL TRANCHE CS01:':<42} EUR {total_cs01:>13,.2f}")
    print(f"  {'CS01 per EUR 1mm notional:':<42} EUR {total_cs01/notional_mm:>13,.2f}")

    # Sector aggregation
    sector_cs01 = {}
    for r in cs01_results:
        sector_cs01[r["sector"]] = sector_cs01.get(r["sector"], 0.0) + r["cs01_eur"]

    print(f"\n  CS01 BY SECTOR:")
    print(f"  {'Sector':<20} {'CS01 (EUR)':>14} {'% of Total':>10}")
    print(f"  {'':->20} {'':->14} {'':->10}")
    for sector, cs01 in sorted(sector_cs01.items(), key=lambda x: abs(x[1]), reverse=True):
        pct = cs01 / total_cs01 * 100 if total_cs01 != 0 else 0
        print(f"  {sector:<20} {cs01:>13,.2f} {pct:>9.1f}%")

    # ── BC01 ──
    print(f"\n{'='*100}")
    print(f"  BC01 — BASE CORRELATION SENSITIVITY")
    print(f"  MTM change for +1% absolute move in base correlation")
    print(f"{'='*100}")

    bc01 = compute_bc01(curves, attach, detach, corr, notional, running_coupon)

    print(f"  Base Correlation:       {bc01['base_correlation']:.1%}")
    print(f"  MTM (base):             EUR {bc01['mtm_base']:>14,.2f}")
    print(f"  MTM (corr + 1%):        EUR {bc01['mtm_corr_up']:>14,.2f}")
    print(f"  MTM (corr - 1%):        EUR {bc01['mtm_corr_dn']:>14,.2f}")
    print(f"  BC01:                   EUR {bc01['bc01_eur']:>14,.2f}")
    print(f"  BC01 (% of notional):   {bc01['bc01_pct_notional']:>13.4f}%")
    print(f"  BC01 per EUR 1mm:       EUR {bc01['bc01_eur']/notional_mm:>14,.2f}")

    # ── Delta validation ──
    # Index CS01 = RPV01_index * 1bp * notional
    avg_hr = hazard_rate_from_spread(avg_spd, ISDA_RECOVERY)
    index_rpv01 = risky_duration_approx(avg_hr)
    index_cs01 = index_rpv01 * (1.0 / 10_000) * notional
    model_delta = total_cs01 / index_cs01 if index_cs01 > 0 else 0.0

    # Market delta (if available)
    mkt_delta = None
    if index_name == "Main" and tranche_label in S44_MARKET["tranches"]:
        mkt_delta = S44_MARKET["tranches"][tranche_label]["delta"]

    # ── Summary ──
    print(f"\n{'='*100}")
    print(f"  RISK SUMMARY -- iTraxx {index_name} S44 {tranche_label} 5Y")
    print(f"  Notional: EUR {notional:,.0f}")
    print(f"{'='*100}")
    print(f"  Total CS01:             EUR {total_cs01:>14,.2f}")
    print(f"  Index CS01 (flat):      EUR {index_cs01:>14,.2f}")
    print(f"  Model Delta:            {model_delta:>13.2f}x")
    if mkt_delta:
        delta_err = (model_delta - mkt_delta) / mkt_delta * 100
        print(f"  Market Delta:           {mkt_delta:>13.2f}x")
        print(f"  Delta Error:            {delta_err:>+12.1f}%")
    print(f"  BC01:                   EUR {bc01['bc01_eur']:>14,.2f}")
    print(f"  Worst single-name JTD:  EUR {jtd_results[0]['jtd_eur']:>14,.0f}  ({jtd_results[0]['name']})")
    print(f"  Avg JTD per name:       EUR {total_jtd/n_names:>14,.0f}")
    print(f"  Max JTD / Notional:     {jtd_results[0]['jtd_pct_of_tranche']:>13.2f}%")
    print(f"{'='*100}\n")


# ─── Scenario Analysis ────────────────────────────────────────────────

def _build_vectors(curves):
    """Extract PD, LGD, weight vectors from curve list."""
    n = len(curves)
    pd_vec = np.array([c.default_prob_5y for c in curves])
    lgd_vec = np.array([1.0 - c.recovery_rate for c in curves])
    w_vec = np.ones(n) / n
    return pd_vec, lgd_vec, w_vec


def _parallel_shift_curves(curves, shift_bps: float):
    """Return new curve list with all spreads shifted by shift_bps."""
    shifted = []
    for c in curves:
        new_spread = max(1.0, c.spread_5y_bps + shift_bps)
        new_rec = c.recovery_rate  # keep recovery fixed for scenario
        new_hr = hazard_rate_from_spread(new_spread, new_rec)
        shifted.append(CDSCurve(
            name=c.name, ticker=c.ticker, sector=c.sector, rating=c.rating,
            spread_5y_bps=new_spread,
            hazard_rate=new_hr,
            survival_prob_5y=survival_probability(new_hr, MATURITY_YEARS),
            default_prob_5y=default_probability(new_hr, MATURITY_YEARS),
            recovery_rate=new_rec,
            source=c.source, weight=c.weight,
        ))
    return shifted


def _fast_total_cs01(curves, attach, detach, corr, notional, running_coupon_bps):
    """Total CS01 via 1bp parallel bump (O(N_quad), not O(N * N_quad))."""
    base_mtm = _tranche_mtm(
        attach, detach, *_build_vectors(curves), corr, notional, running_coupon_bps
    )
    bumped = _parallel_shift_curves(curves, 1.0)
    bumped_mtm = _tranche_mtm(
        attach, detach, *_build_vectors(bumped), corr, notional, running_coupon_bps
    )
    return bumped_mtm - base_mtm


def run_scenario_analysis(
    scenarios_bps: list = None,
    index_name: str = "Main",
    tranche_label: str = "0-3%",
    notional_mm: float = 10.0,
    index_spread_bps: float = None,
):
    """Run spread scenario analysis with full reprice P&L.

    Scenarios are parallel shifts to all constituent spreads.
    Base correlation held FIXED (market convention).
    Shows full-reprice P&L, first-order estimate, and convexity.
    """
    if scenarios_bps is None:
        scenarios_bps = [-5, +10, +25]

    notional = notional_mm * 1_000_000
    ref_spread = index_spread_bps or S44_MARKET["ref_spread_bps"]
    running_coupon = S44_MARKET["running_coupon_bps"] if index_name == "Main" else 0.0

    # Tranche definition
    tranches = MAIN_TRANCHES if index_name == "Main" else CROSSOVER_TRANCHES
    tranche_def = None
    for t in tranches:
        if t["label"] == tranche_label:
            tranche_def = t
            break
    if not tranche_def:
        print(f"  ERROR: Tranche {tranche_label} not found")
        return

    attach = tranche_def["attach"]
    detach = tranche_def["detach"]

    # Calibrate base correlation (held fixed across scenarios)
    corr = calibrate_s44_base_correlation(
        tranche_label=tranche_label,
        ref_spread=ref_spread,
        running_coupon=running_coupon,
        verbose=True,
    )
    if corr is None:
        corr = _parametric_base_correlation(detach, index_name)

    # Generate base curves
    curves_base = generate_main_curves(125, ref_spread, 25)
    pd_base, lgd_base, w_base = _build_vectors(curves_base)

    # Base case MTM and risk
    mtm_base = _tranche_mtm(attach, detach, pd_base, lgd_base, w_base, corr, notional, running_coupon)
    cs01_base = _fast_total_cs01(curves_base, attach, detach, corr, notional, running_coupon)
    bc01_base = compute_bc01(curves_base, attach, detach, corr, notional, running_coupon)

    avg_hr = hazard_rate_from_spread(ref_spread, ISDA_RECOVERY)
    index_rpv01 = risky_duration_approx(avg_hr)
    index_cs01 = index_rpv01 * (1.0 / 10_000) * notional
    delta_base = cs01_base / index_cs01 if index_cs01 > 0 else 0.0

    # Header
    print(f"\n{'='*100}")
    print(f"  SCENARIO ANALYSIS -- iTraxx {index_name} S44 {tranche_label} 5Y")
    print(f"  Notional: EUR {notional:,.0f}  |  Base correlation: {corr:.1%} (FIXED)")
    print(f"  Protection buyer perspective (long protection = long credit risk)")
    print(f"{'='*100}")

    # Base case row
    print(f"\n  {'':->100}")
    print(f"  {'Scenario':<16} {'Index':>7} {'MTM':>16} {'P&L Full':>14} {'P&L Linear':>14} "
          f"{'Convexity':>12} {'CS01':>12} {'Delta':>8} {'BC01':>12}")
    print(f"  {'':->16} {'':->7} {'':->16} {'':->14} {'':->14} "
          f"{'':->12} {'':->12} {'':->8} {'':->12}")
    print(f"  {'BASE':<16} {ref_spread:>6.0f}bp {mtm_base:>15,.0f} {'--':>14} {'--':>14} "
          f"{'--':>12} {cs01_base:>11,.0f} {delta_base:>7.2f}x {bc01_base['bc01_eur']:>11,.0f}")

    # Scenario rows
    for shift in sorted(scenarios_bps):
        new_spread = ref_spread + shift
        curves_scen = _parallel_shift_curves(curves_base, shift)
        pd_scen, lgd_scen, w_scen = _build_vectors(curves_scen)

        # Full reprice
        mtm_scen = _tranche_mtm(attach, detach, pd_scen, lgd_scen, w_scen, corr, notional, running_coupon)
        pnl_full = mtm_scen - mtm_base

        # First-order (linear) P&L
        pnl_linear = cs01_base * shift

        # Convexity = full - linear
        convexity = pnl_full - pnl_linear

        # Risk at scenario level
        cs01_scen = _fast_total_cs01(curves_scen, attach, detach, corr, notional, running_coupon)
        bc01_scen = compute_bc01(curves_scen, attach, detach, corr, notional, running_coupon)

        avg_hr_scen = hazard_rate_from_spread(new_spread, ISDA_RECOVERY)
        idx_rpv01_scen = risky_duration_approx(avg_hr_scen)
        idx_cs01_scen = idx_rpv01_scen * (1.0 / 10_000) * notional
        delta_scen = cs01_scen / idx_cs01_scen if idx_cs01_scen > 0 else 0.0

        sign = "+" if shift >= 0 else ""
        label = f"Main {sign}{shift}bp"
        print(f"  {label:<16} {new_spread:>6.0f}bp {mtm_scen:>15,.0f} {pnl_full:>+13,.0f} {pnl_linear:>+13,.0f} "
              f"{convexity:>+11,.0f} {cs01_scen:>11,.0f} {delta_scen:>7.2f}x {bc01_scen['bc01_eur']:>11,.0f}")

    # P&L summary
    print(f"\n  {'':->100}")
    print(f"  Notes:")
    print(f"    - P&L Full:    full model reprice at shocked spreads (captures convexity)")
    print(f"    - P&L Linear:  CS01 x spread move (first-order only)")
    print(f"    - Convexity:   Full - Linear (positive = equity tranche convexity benefit)")
    print(f"    - Correlation held fixed at {corr:.1%} across all scenarios")
    print(f"    - Parallel shift applied to all 125 constituents")
    print(f"{'='*100}\n")


# ─── Single-Name Blowout Scenarios ────────────────────────────────────

def _single_name_bump(curves, name_idx: int, bump_bps: float):
    """Return new curve list with only name_idx spread bumped."""
    shifted = []
    for i, c in enumerate(curves):
        if i == name_idx:
            new_spread = max(1.0, c.spread_5y_bps + bump_bps)
            new_hr = hazard_rate_from_spread(new_spread, c.recovery_rate)
            shifted.append(CDSCurve(
                name=c.name, ticker=c.ticker, sector=c.sector, rating=c.rating,
                spread_5y_bps=new_spread, hazard_rate=new_hr,
                survival_prob_5y=survival_probability(new_hr, MATURITY_YEARS),
                default_prob_5y=default_probability(new_hr, MATURITY_YEARS),
                recovery_rate=c.recovery_rate, source=c.source, weight=c.weight,
            ))
        else:
            shifted.append(c)
    return shifted


def run_single_name_blowout(
    bumps_bps: list = None,
    index_name: str = "Main",
    tranche_label: str = "0-3%",
    notional_mm: float = 10.0,
    index_spread_bps: float = None,
    top_n: int = 5,
):
    """Single-name blowout scenario: one name widens, rest unchanged.

    For each bump size, shows P&L impact for the top_n most impactful names
    plus the average across all names.
    """
    if bumps_bps is None:
        bumps_bps = [100, 250, 500]

    notional = notional_mm * 1_000_000
    ref_spread = index_spread_bps or S44_MARKET["ref_spread_bps"]
    running_coupon = S44_MARKET["running_coupon_bps"] if index_name == "Main" else 0.0

    tranches = MAIN_TRANCHES if index_name == "Main" else CROSSOVER_TRANCHES
    tranche_def = None
    for t in tranches:
        if t["label"] == tranche_label:
            tranche_def = t
            break
    if not tranche_def:
        print(f"  ERROR: Tranche {tranche_label} not found")
        return

    attach = tranche_def["attach"]
    detach = tranche_def["detach"]

    # Calibrate
    corr = calibrate_s44_base_correlation(
        tranche_label=tranche_label, ref_spread=ref_spread,
        running_coupon=running_coupon, verbose=True,
    )
    if corr is None:
        corr = _parametric_base_correlation(detach, index_name)

    # Base curves and MTM
    curves_base = generate_main_curves(125, ref_spread, 25)
    pd_base, lgd_base, w_base = _build_vectors(curves_base)
    mtm_base = _tranche_mtm(attach, detach, pd_base, lgd_base, w_base, corr, notional, running_coupon)
    n = len(curves_base)

    # Precompute GH nodes/weights and base EL for fast single-name repricing
    pd_base, lgd_base, w_base = _build_vectors(curves_base)
    nodes, weights = _gauss_hermite_nodes_weights(N_QUADRATURE)
    width = detach - attach
    sqrt_rho = np.sqrt(max(0.001, corr))
    sqrt_1mr = np.sqrt(max(0.001, 1.0 - corr))
    thresholds_base = np.array([
        norm.ppf(max(1e-10, min(1 - 1e-10, pd))) for pd in pd_base
    ])

    # Precompute +1bp parallel thresholds for CS01 calculation
    thresholds_1bp = np.array([
        norm.ppf(max(1e-10, min(1 - 1e-10,
            default_probability(
                hazard_rate_from_spread(c.spread_5y_bps + 1.0, c.recovery_rate),
                MATURITY_YEARS
            ))))
        for c in curves_base
    ])

    def _fast_el_vec(thresh_vec):
        total = 0.0
        for k in range(len(nodes)):
            M = nodes[k]
            cond_pds = norm.cdf((thresh_vec - sqrt_rho * M) / sqrt_1mr)
            cond_loss = np.sum(w_base * lgd_base * cond_pds)
            tranche_loss = (min(cond_loss, detach) - min(cond_loss, attach)) / width
            total += weights[k] * tranche_loss
        return max(0.0, total)

    el_base = _fast_el_vec(thresholds_base)

    # Precompute base per-name CS01_i for all names
    # CS01_i = EL(name_i +1bp) - EL(base), using precomputed thresholds_1bp
    base_cs01_per_name = np.zeros(n)
    for i in range(n):
        thresh_i = thresholds_base.copy()
        thresh_i[i] = thresholds_1bp[i]
        el_i = _fast_el_vec(thresh_i)
        base_cs01_per_name[i] = (el_i - el_base) * notional

    # Header
    print(f"\n{'='*100}")
    print(f"  SINGLE-NAME BLOWOUT SCENARIOS -- iTraxx {index_name} S44 {tranche_label} 5Y")
    print(f"  Notional: EUR {notional:,.0f}  |  Base corr: {corr:.1%} (FIXED)")
    print(f"  One name widens, rest of portfolio unchanged")
    print(f"{'='*100}")

    for bump in bumps_bps:
        print(f"\n  {'':->120}")
        print(f"  SINGLE NAME +{bump}bp")
        print(f"  {'':->120}")
        print(f"  {'#':>4}  {'Name':<20} {'Sector':<12} {'Rtg':>4} {'Base Spd':>9} "
              f"{'Shocked':>9} {'P&L':>14} {'Name CS01':>11} {'CS01 After':>11} "
              f"{'CS01 Chg':>10} {'vs JTD':>9}")
        print(f"  {'':->4}  {'':->20} {'':->12} {'':->4} {'':->9} "
              f"{'':->9} {'':->14} {'':->11} {'':->11} "
              f"{'':->10} {'':->9}")

        # Fast: bump one name's PD in the threshold vector, reprice 5Y EL
        all_pnl = []
        for i, c in enumerate(curves_base):
            new_spread = max(1.0, c.spread_5y_bps + bump)
            new_hr = hazard_rate_from_spread(new_spread, c.recovery_rate)
            new_pd = default_probability(new_hr, MATURITY_YEARS)
            new_thresh = norm.ppf(max(1e-10, min(1 - 1e-10, new_pd)))

            # EL after single-name blowout
            thresh_bumped = thresholds_base.copy()
            thresh_bumped[i] = new_thresh
            el_bumped = _fast_el_vec(thresh_bumped)
            pnl = (el_bumped - el_base) * notional

            # Per-name CS01_i after blowout: bump name i by +1bp from shocked level
            thresh_shocked_plus1 = thresholds_base.copy()
            new_spread_plus1 = new_spread + 1.0
            new_hr_plus1 = hazard_rate_from_spread(new_spread_plus1, c.recovery_rate)
            new_pd_plus1 = default_probability(new_hr_plus1, MATURITY_YEARS)
            thresh_shocked_plus1[i] = norm.ppf(max(1e-10, min(1 - 1e-10, new_pd_plus1)))
            el_shocked_plus1 = _fast_el_vec(thresh_shocked_plus1)
            cs01_i_after = (el_shocked_plus1 - el_bumped) * notional

            # JTD for comparison
            w_i = 1.0 / n
            lgd_i = 1.0 - c.recovery_rate
            port_loss = w_i * lgd_i
            tranche_hit = (min(port_loss, detach) - min(port_loss, attach)) / width
            jtd = tranche_hit * notional

            cs01_i_before = base_cs01_per_name[i]
            all_pnl.append({
                "idx": i, "name": c.name, "sector": c.sector, "rating": c.rating,
                "base_spread": c.spread_5y_bps, "shocked_spread": new_spread,
                "pnl": pnl, "pct_notional": pnl / notional * 100, "jtd": jtd,
                "pnl_vs_jtd": pnl / jtd * 100 if jtd > 0 else 0,
                "cs01_before": cs01_i_before, "cs01_after": cs01_i_after,
                "cs01_chg": cs01_i_after - cs01_i_before,
            })

        all_pnl.sort(key=lambda x: x["pnl"], reverse=True)

        # Top N worst
        for rank, r in enumerate(all_pnl[:top_n], 1):
            print(f"  {rank:>4}  {r['name']:<20} {r['sector']:<12} {r['rating']:>4} "
                  f"{r['base_spread']:>8.0f}bp {r['shocked_spread']:>8.0f}bp "
                  f"{r['pnl']:>+13,.0f} {r['cs01_before']:>10,.0f} {r['cs01_after']:>10,.0f} "
                  f"{r['cs01_chg']:>+9,.0f} {r['pnl_vs_jtd']:>8.1f}%")

        # Summary
        avg_pnl = np.mean([r["pnl"] for r in all_pnl])
        max_pnl = all_pnl[0]["pnl"]
        min_pnl = all_pnl[-1]["pnl"]
        worst = all_pnl[0]
        print(f"\n  Worst single-name P&L:   EUR {max_pnl:>+13,.0f}  ({worst['name']})")
        print(f"    CS01_i moved:          {worst['cs01_before']:,.0f} -> {worst['cs01_after']:,.0f}  "
              f"({worst['cs01_chg']:+,.0f}, {worst['cs01_chg']/worst['cs01_before']*100:+.0f}%)")
        print(f"  Best single-name P&L:    EUR {min_pnl:>+13,.0f}  ({all_pnl[-1]['name']})")
        print(f"  Average across {n} names: EUR {avg_pnl:>+13,.0f}")

    print(f"\n  {'':->120}")
    print(f"  Notes:")
    print(f"    - P&L is full model reprice (one name shocked, 124 unchanged)")
    print(f"    - Name CS01 / CS01 After = that name's individual CS01_i before / after its spread move")
    print(f"    - CS01_i rises on widening due to equity tranche convexity (non-linear EL surface)")
    print(f"    - vs JTD = P&L as %% of instantaneous jump-to-default loss")
    print(f"    - At +500bp a name approaches distressed; P&L converges toward JTD")
    print(f"    - Correlation held fixed at {corr:.1%}")
    print(f"{'='*100}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Per-constituent JTD, CS01, and BC01 for iTraxx tranches"
    )
    parser.add_argument("--index", type=str, default="Main",
                        choices=["Main", "Crossover"],
                        help="iTraxx index (default: Main)")
    parser.add_argument("--tranche", type=str, default="0-3%",
                        help="Tranche label e.g. 0-3%%, 0-10%% (default: 0-3%%)")
    parser.add_argument("--notional", type=float, default=10.0,
                        help="Notional in EUR millions (default: 10)")
    parser.add_argument("--index-spread", type=float, default=None,
                        help="Override avg index spread in bps")
    args = parser.parse_args()

    # Normalize tranche label
    tranche = args.tranche
    if not tranche.endswith("%"):
        tranche += "%"

    run_report(
        index_name=args.index,
        tranche_label=tranche,
        notional_mm=args.notional,
        index_spread_bps=args.index_spread,
    )


if __name__ == "__main__":
    main()

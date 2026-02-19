"""
Gaussian Copula Tranche Pricer for iTraxx Index Tranches

Implements the one-factor Gaussian copula model (Li 2000) with Large
Homogeneous Portfolio (LHP) approximation for pricing standard CDO
tranches on the iTraxx Crossover index.

The model:
    asset_i = sqrt(rho) * M  +  sqrt(1 - rho) * epsilon_i
    where M ~ N(0,1) is the systematic factor, epsilon_i ~ N(0,1) idiosyncratic.
    Default if asset_i < Phi^{-1}(PD_i).

Standard iTraxx Xover tranches:
    0-10%   equity    (traded upfront + 500bp running)
    10-25%  mezzanine
    25-100% senior

Key functions:
    gaussian_copula_base_correlation()  - Calibrate base correlation from market
    price_tranche()                     - Price tranche given base correlation
    tranche_risk_metrics()              - CS01, DV01, delta, gamma, expected loss
    tranche_strategy_analysis()         - P&L across parallel spread bumps

Usage:
    python -m analytics.tranche_pricer --index-spread 350
    python -m analytics.tranche_pricer --strategy
    python -m analytics.tranche_pricer --calibrate --equity-upfront 35
    python -m analytics.tranche_pricer --help

Reference:
    Li, D.X. (2000) "On Default Correlation: A Copula Function Approach"
    O'Kane, D. (2008) "Modelling Single-name and Multi-name Credit Derivatives"
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from scipy import integrate
from scipy.optimize import brentq
from scipy.stats import norm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ISDA_RECOVERY = 0.40
RISK_FREE_RATE = 0.03
N_NAMES = 75            # iTraxx Xover S44 has 75 names
STANDARD_COUPON = 500    # HY equity tranche running coupon (bps)

# Standard iTraxx Xover tranche structure
STANDARD_TRANCHES = {
    "equity":    {"attachment": 0.00, "detachment": 0.10, "coupon_bps": 500,  "traded_upfront": True},
    "mezzanine": {"attachment": 0.10, "detachment": 0.25, "coupon_bps": 0,    "traded_upfront": False},
    "senior":    {"attachment": 0.25, "detachment": 1.00, "coupon_bps": 0,    "traded_upfront": False},
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TrancheAnalytics:
    """Full analytics for a single tranche."""
    attachment: float
    detachment: float
    width: float
    index_spread: float
    base_correlation: float
    recovery: float
    maturity: float

    expected_loss_pct: float     # Expected loss as % of tranche notional
    premium_leg_pv: float        # PV of premium leg (per unit tranche notional)
    protection_leg_pv: float     # PV of protection leg (per unit tranche notional)
    fair_spread_bps: float       # Breakeven spread in bps
    upfront_pct: float           # Upfront payment (for equity tranche)
    mtm: float                   # Mark-to-market ($)

    cs01: float                  # $ change for 1bp index spread widening
    tranche_dv01: float          # $ change for 1bp tranche spread move
    delta: float                 # Tranche spread move per 1bp index move
    gamma: float                 # Convexity: change in delta per 1bp index move
    leverage: float              # Tranche notional loss / index notional loss
    notional: float = 10_000_000


@dataclass
class StrategyPnL:
    """P&L for a tranche position under a spread scenario."""
    bump_bps: float
    new_index_spread: float
    position_pnl: float
    cumulative_pnl: float = 0.0


# ---------------------------------------------------------------------------
# Core Gaussian Copula Model (LHP Approximation)
# ---------------------------------------------------------------------------

def _implied_default_prob(spread_bps: float, recovery: float = ISDA_RECOVERY,
                          maturity: float = 5.0) -> float:
    """Implied cumulative default probability from spread.

    Uses the standard approximation:
        PD = 1 - exp(-spread / (1-R) * T)

    But for the copula model we need the risk-neutral PD, so we use:
        PD = 1 - exp(-h * T)  where h = s/(1-R)
    """
    s = spread_bps / 10_000
    h = s / (1 - recovery)
    return 1 - math.exp(-h * maturity)


def _conditional_default_prob(pd: float, rho: float, m: float) -> float:
    """Conditional default probability given systematic factor M = m.

    P(default | M = m) = Phi( (Phi^{-1}(PD) - sqrt(rho)*m) / sqrt(1-rho) )

    Args:
        pd:  Marginal (unconditional) default probability
        rho: Asset correlation parameter
        m:   Realisation of the systematic factor
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
    """Conditional expected portfolio loss fraction given M = m.

    Under LHP approximation, the portfolio loss fraction equals
    the conditional default probability * (1-R), because all names
    have the same default probability and recovery.
    """
    return _conditional_default_prob(pd, rho, m) * (1.0 - recovery)


def _tranche_expected_loss_conditional(pd: float, rho: float, m: float,
                                        attachment: float, detachment: float,
                                        recovery: float = ISDA_RECOVERY) -> float:
    """Conditional expected tranche loss fraction given M = m.

    The tranche loss is:
        E[L_tranche | M] = (1/width) * (min(L, D) - min(L, A))
    where L = portfolio loss fraction, A = attachment, D = detachment.

    Under LHP, L is deterministic given M:
        L = conditional_default_prob(m) * (1-R)
    """
    loss = _conditional_expected_loss(pd, rho, m, recovery)
    width = detachment - attachment

    tranche_loss = (min(loss, detachment) - min(loss, attachment)) / width
    return max(0.0, tranche_loss)


def expected_tranche_loss(index_spread: float, correlation: float,
                          attachment: float, detachment: float,
                          recovery: float = ISDA_RECOVERY,
                          maturity: float = 5.0) -> float:
    """Unconditional expected tranche loss (% of tranche notional).

    Integrates over the systematic factor M ~ N(0,1):
        E[L_tranche] = integral_{-inf}^{inf} E[L_tranche|M=m] * phi(m) dm

    Uses scipy.integrate.quad for numerical integration.
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

    RPV01 = sum over quarterly dates of:
        DF(t_i) * (1 - EL(t_i)) * dt

    where EL(t_i) is the expected tranche loss at time t_i.
    """
    n_periods = int(maturity * 4)  # Quarterly
    dt = 0.25
    rpv01 = 0.0

    for i in range(1, n_periods + 1):
        t = i * dt
        # Scale index spread PD to this time horizon
        el_t = expected_tranche_loss(
            index_spread, correlation, attachment, detachment,
            recovery, t
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
    """PV of protection leg for tranche (per unit tranche notional).

    Approximated as sum over small time steps of:
        DF(t_mid) * dEL(t) * dt

    where dEL is the incremental expected loss over the period.
    """
    n_steps = int(maturity * 4)  # Quarterly steps
    dt = 0.25
    prot_pv = 0.0
    prev_el = 0.0

    for i in range(1, n_steps + 1):
        t = i * dt
        el_t = expected_tranche_loss(
            index_spread, correlation, attachment, detachment,
            recovery, t
        )
        d_el = el_t - prev_el
        t_mid = t - dt / 2
        df = math.exp(-risk_free_rate * t_mid)
        prot_pv += df * d_el
        prev_el = el_t

    return prot_pv


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
        running_coupon = 500bps standard

    For mezzanine/senior (traded on running):
        tranche_spread = running spread in bps

    Returns:
        Base correlation (0 to 1)
    """
    def objective(rho):
        if is_upfront:
            # Equity: PV(protection) - PV(upfront) - PV(running coupon) = 0
            prot = _protection_leg_tranche(
                index_spread, rho, attachment, detachment, recovery, maturity
            )
            rpv01 = _risky_annuity_tranche(
                index_spread, rho, attachment, detachment, recovery, maturity
            )
            model_upfront = (prot - running_coupon / 10_000 * rpv01) * 100
            return model_upfront - tranche_spread
        else:
            # Mezz/Senior: fair spread calculation
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
        return brentq(objective, 0.001, 0.999, xtol=1e-6, maxiter=200)
    except ValueError:
        # If root not bracketed, return the guess
        return correlation_guess


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
    """Price a tranche given base correlation.

    Uses the base correlation approach:
        For tranche [A, D], use correlation calibrated to [0, D] and [0, A]
        tranches and difference the expected losses.

    For simplicity, here we use a single correlation per tranche (the
    base correlation for the detachment point), which is the standard
    market convention.

    Args:
        attachment: Lower attachment point (e.g., 0.0 for equity)
        detachment: Upper detachment point (e.g., 0.10 for equity)
        index_spread: Current index spread in bps
        base_correlation: Calibrated base correlation
        recovery: Recovery rate (default 40%)
        maturity: Maturity in years (default 5)
        notional: Tranche notional ($)
        running_coupon_bps: Running coupon in bps (500 for equity, 0 otherwise)

    Returns:
        TrancheAnalytics dataclass with full pricing results
    """
    width = detachment - attachment

    # Expected loss
    el = expected_tranche_loss(
        index_spread, base_correlation, attachment, detachment, recovery, maturity
    )

    # Protection leg PV
    prot_pv = _protection_leg_tranche(
        index_spread, base_correlation, attachment, detachment, recovery, maturity
    )

    # Premium leg (RPV01)
    rpv01 = _risky_annuity_tranche(
        index_spread, base_correlation, attachment, detachment, recovery, maturity
    )

    # Fair spread (breakeven)
    fair_spread = (prot_pv / rpv01 * 10_000) if rpv01 > 0 else 0

    # Upfront (for equity tranche)
    if running_coupon_bps > 0:
        upfront = (prot_pv - running_coupon_bps / 10_000 * rpv01) * 100
    else:
        upfront = 0.0

    # MTM = (protection - premium) * notional
    # For new trade at fair spread, MTM = 0
    mtm = prot_pv * notional - running_coupon_bps / 10_000 * rpv01 * notional

    # Risk metrics via finite differences
    bump = 1.0  # 1bp
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

    el_dn = expected_tranche_loss(
        max(1.0, index_spread - bump), base_correlation, attachment, detachment,
        recovery, maturity
    )
    prot_dn = _protection_leg_tranche(
        max(1.0, index_spread - bump), base_correlation, attachment, detachment,
        recovery, maturity
    )
    rpv01_dn = _risky_annuity_tranche(
        max(1.0, index_spread - bump), base_correlation, attachment, detachment,
        recovery, maturity
    )
    fair_dn = (prot_dn / rpv01_dn * 10_000) if rpv01_dn > 0 else 0

    # CS01: $ change in MTM per 1bp index widening
    mtm_up = prot_up * notional - running_coupon_bps / 10_000 * rpv01_up * notional
    mtm_dn = prot_dn * notional - running_coupon_bps / 10_000 * rpv01_dn * notional
    cs01 = (mtm_up - mtm_dn) / 2

    # Tranche DV01 (per 1bp of tranche running spread)
    tranche_dv01 = rpv01 * notional / 10_000

    # Delta: tranche spread move per 1bp index move
    delta = (fair_up - fair_dn) / 2

    # Gamma: change in delta per 1bp index move (convexity)
    fair_up2 = 0.0
    fair_dn2 = 0.0
    if index_spread + 2 * bump > 0:
        prot_up2 = _protection_leg_tranche(
            index_spread + 2 * bump, base_correlation, attachment, detachment,
            recovery, maturity
        )
        rpv01_up2 = _risky_annuity_tranche(
            index_spread + 2 * bump, base_correlation, attachment, detachment,
            recovery, maturity
        )
        fair_up2 = (prot_up2 / rpv01_up2 * 10_000) if rpv01_up2 > 0 else 0

    if index_spread - 2 * bump > 0:
        prot_dn2 = _protection_leg_tranche(
            index_spread - 2 * bump, base_correlation, attachment, detachment,
            recovery, maturity
        )
        rpv01_dn2 = _risky_annuity_tranche(
            index_spread - 2 * bump, base_correlation, attachment, detachment,
            recovery, maturity
        )
        fair_dn2 = (prot_dn2 / rpv01_dn2 * 10_000) if rpv01_dn2 > 0 else 0

    delta_up = fair_up2 - fair_up if fair_up2 else delta
    delta_dn = fair_up - fair_dn if fair_dn else delta
    gamma = delta_up - delta_dn  # Second derivative of spread

    # Leverage: tranche loss sensitivity / index loss sensitivity
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
    attachment: float,
    detachment: float,
    index_spread: float,
    base_correlation: float,
    recovery: float = ISDA_RECOVERY,
    maturity: float = 5.0,
    notional: float = 10_000_000,
    running_coupon_bps: float = 0,
) -> TrancheAnalytics:
    """Compute full risk metrics for a tranche. Alias for price_tranche."""
    return price_tranche(
        attachment, detachment, index_spread, base_correlation,
        recovery, maturity, notional, running_coupon_bps,
    )


def tranche_strategy_analysis(
    index_spread: float,
    base_correlations: dict[str, float],
    positions: list[dict],
    bumps: list[float] | None = None,
) -> dict[str, list[StrategyPnL]]:
    """Analyse tranche strategy P&L across parallel spread scenarios.

    Args:
        index_spread: Current index spread (bps)
        base_correlations: Dict of tranche name -> base correlation
        positions: List of position dicts with keys:
            - tranche: tranche name (equity/mezzanine/senior)
            - direction: LONG_RISK or SHORT_RISK
            - notional: position notional ($)
        bumps: List of spread bumps in bps (default: standard set)

    Returns:
        Dict of tranche name -> list of StrategyPnL
    """
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

        # Base case MTM
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
            # Direction: SHORT_RISK = protection buyer = gains on widening
            if direction == "SHORT_RISK":
                signed_pnl = raw_pnl
            else:  # LONG_RISK = protection seller
                signed_pnl = -raw_pnl

            pnl_list.append(StrategyPnL(
                bump_bps=bump,
                new_index_spread=new_spread,
                position_pnl=signed_pnl,
            ))

        results[f"{tranche_name}_{direction}"] = pnl_list

    return results


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

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

    # Header
    header = f"  {'Position':<32}"
    for b in bumps:
        header += f"  {b:+.0f}bp".rjust(11)
    print(header)
    print(f"  {'-'*32}  " + "  ".join(["-"*9] * len(bumps)))

    # Per-position rows
    total_by_bump = {b: 0.0 for b in bumps}

    for name, pnl_list in all_results.items():
        row = f"  {name:<32}"
        for p in pnl_list:
            row += f"  ${p.position_pnl/1000:>+8,.1f}k"
            total_by_bump[p.bump_bps] += p.position_pnl
        print(row)

    # Total row
    print(f"  {'-'*32}  " + "  ".join(["-"*9] * len(bumps)))
    total_row = f"  {'TOTAL P&L':<32}"
    for b in bumps:
        total_row += f"  ${total_by_bump[b]/1000:>+8,.1f}k"
    print(total_row)

    # Highlight convexity
    print(f"\n  CONVEXITY CHECK:")
    for name, pnl_list in all_results.items():
        pnl_map = {p.bump_bps: p.position_pnl for p in pnl_list}
        if 50 in pnl_map and 100 in pnl_map and 200 in pnl_map:
            ratio_100_50 = pnl_map[100] / pnl_map[50] if pnl_map[50] != 0 else 0
            ratio_200_100 = pnl_map[200] / pnl_map[100] if pnl_map[100] != 0 else 0
            print(f"    {name}: +100bp/{'+50bp'} = {ratio_100_50:.2f}x,  "
                  f"+200bp/{'+100bp'} = {ratio_200_100:.2f}x")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
    """Price all standard tranches at the given index spread."""
    spread = args.index_spread
    rho_equity = args.equity_corr
    rho_mezz = args.mezz_corr
    rho_senior = args.senior_corr
    notional = args.notional * 1_000_000

    print(f"\n{'='*70}")
    print(f"  iTraxx XOVER TRANCHE ANALYTICS")
    print(f"  Index Spread: {spread:.0f}bps  |  Recovery: {ISDA_RECOVERY:.0%}  |"
          f"  Maturity: 5Y  |  Names: {N_NAMES}")
    print(f"{'='*70}")

    # Implied index default probability
    pd = _implied_default_prob(spread, ISDA_RECOVERY, 5.0)
    print(f"\n  Implied 5Y Default Probability: {pd:.1%}")
    print(f"  Expected Portfolio Loss (LHP):  {pd*(1-ISDA_RECOVERY):.1%}")

    tranches = [
        ("0-10% Equity",    0.00, 0.10, rho_equity, 500),
        ("10-25% Mezzanine", 0.10, 0.25, rho_mezz,   0),
        ("25-100% Senior",   0.25, 1.00, rho_senior,  0),
    ]

    analytics_list = []
    for name, att, det, rho, coupon in tranches:
        a = price_tranche(
            att, det, spread, rho, notional=notional,
            running_coupon_bps=coupon,
        )
        analytics_list.append((name, a))
        print_tranche_analytics(a, name)

    # Summary table
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
        print("Error: No portfolio found. Run agents/strategist.py first.",
              file=sys.stderr)
        sys.exit(1)

    # Extract index spread and hedges
    index_spread = args.index_spread or 350.0
    hedges = portfolio.get("hedges", [])

    # Build tranche positions from hedges
    positions = []
    for h in hedges:
        instrument = h.get("instrument", "").lower()
        if "tranche" in instrument or "equity" in instrument:
            # Parse tranche from instrument name
            if "equity" in instrument or "0-10" in instrument:
                tranche = "equity"
            elif "mezz" in instrument or "10-25" in instrument or "3-7" in instrument:
                # Map 3-7% to mezzanine (closest standard tranche)
                tranche = "mezzanine"
            elif "senior" in instrument or "25-100" in instrument:
                tranche = "senior"
            else:
                tranche = "mezzanine"  # Default to mezz for non-standard

            positions.append({
                "tranche": tranche,
                "direction": h["direction"],
                "notional": h["notional_millions"] * 1_000_000,
                "instrument": h["instrument"],
                "rationale": h.get("rationale", ""),
            })

    # If no tranche hedges in portfolio, show a default strategy
    if not positions:
        print("\n  No tranche hedges found in strategist portfolio.")
        print("  Showing default convex hedge strategy:\n")
        positions = [
            {
                "tranche": "equity",
                "direction": "SHORT_RISK",
                "notional": 15_000_000,
                "instrument": "iTraxx Xover 0-10% equity tranche",
                "rationale": "Convex downside protection",
            },
        ]

    base_correlations = {
        "equity": args.equity_corr,
        "mezzanine": args.mezz_corr,
        "senior": args.senior_corr,
    }

    print(f"\n{'='*90}")
    print(f"  iTraxx XOVER TRANCHE STRATEGY ANALYSIS")
    print(f"  Index: {index_spread:.0f}bps  |  Portfolio net: "
          f"{portfolio.get('net_bias', {}).get('net_exposure_pct', 0):+.1f}%")
    print(f"{'='*90}")

    # Show positions
    print(f"\n  TRANCHE POSITIONS:")
    for p in positions:
        tag = "BUY PROTECTION" if p["direction"] == "SHORT_RISK" else "SELL PROTECTION"
        tranche_def = STANDARD_TRANCHES[p["tranche"]]
        att = tranche_def["attachment"]
        det = tranche_def["detachment"]
        print(f"    [{tag}] {p['instrument']}")
        print(f"      Notional: ${p['notional']/1e6:.1f}M  |  "
              f"Tranche: {att*100:.0f}-{det*100:.0f}%")
        print(f"      Rationale: {p.get('rationale', 'N/A')}")

    # Price each position
    print(f"\n  CURRENT ANALYTICS:")
    for p in positions:
        tranche_def = STANDARD_TRANCHES[p["tranche"]]
        rho = base_correlations[p["tranche"]]
        a = price_tranche(
            tranche_def["attachment"],
            tranche_def["detachment"],
            index_spread,
            rho,
            notional=p["notional"],
            running_coupon_bps=tranche_def["coupon_bps"],
        )
        print_tranche_analytics(a, p["instrument"][:50])

    # Strategy P&L analysis
    results = tranche_strategy_analysis(
        index_spread, base_correlations, positions,
    )
    print_strategy_table(results, index_spread)

    # Also show combined with index hedge if present
    index_hedges = [h for h in hedges if "index" in h.get("instrument", "").lower()
                    and "tranche" not in h.get("instrument", "").lower()]

    if index_hedges:
        print(f"\n  {'='*90}")
        print(f"  COMBINED HEDGE P&L (Tranches + Index)")
        print(f"  {'='*90}")

        bumps = [-50, -25, 0, +25, +50, +100, +200]

        # Index hedge DV01
        for ih in index_hedges:
            ih_notional = ih["notional_millions"] * 1_000_000
            # Approximate index DV01 from risky annuity
            from analytics.cds_pricer import _risky_annuity as cds_rpv01
            rpv01 = cds_rpv01(index_spread)
            idx_dv01 = ih_notional * rpv01 / 10_000
            is_long = ih["direction"] == "LONG_RISK"

            header = f"  {'Scenario':<20}"
            for b in bumps:
                header += f"  {b:+.0f}bp".rjust(11)
            print(header)
            print(f"  {'-'*20}  " + "  ".join(["-"*9] * len(bumps)))

            # Tranche P&L
            tranche_pnl = {}
            for b in bumps:
                tranche_pnl[b] = sum(
                    pnl.position_pnl
                    for pnl_list in results.values()
                    for pnl in pnl_list
                    if pnl.bump_bps == b
                )

            row = f"  {'Tranche hedges':<20}"
            for b in bumps:
                row += f"  ${tranche_pnl[b]/1000:>+8,.1f}k"
            print(row)

            # Index hedge P&L
            row = f"  {'Index hedge':<20}"
            for b in bumps:
                idx_pnl = idx_dv01 * b * (-1 if is_long else 1)
                row += f"  ${idx_pnl/1000:>+8,.1f}k"
            print(row)

            # Combined
            print(f"  {'-'*20}  " + "  ".join(["-"*9] * len(bumps)))
            row = f"  {'COMBINED':<20}"
            for b in bumps:
                idx_pnl = idx_dv01 * b * (-1 if is_long else 1)
                combined = tranche_pnl[b] + idx_pnl
                row += f"  ${combined/1000:>+8,.1f}k"
            print(row)

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

    # Verify
    a = price_tranche(0.0, 0.10, spread, rho, running_coupon_bps=500)
    print(f"  Model upfront at calibrated rho:    {a.upfront_pct:.2f}%")
    print(f"  Target upfront:                     {equity_uf:.2f}%")
    print(f"  Difference:                         {abs(a.upfront_pct - equity_uf):.4f}%")
    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Gaussian Copula Tranche Pricer -- iTraxx Xover"
    )
    parser.add_argument(
        "--index-spread", type=float, default=350.0,
        help="Index spread in bps (default: 350)",
    )
    parser.add_argument(
        "--strategy", action="store_true",
        help="Show tranche strategy analysis from portfolio hedges",
    )
    parser.add_argument(
        "--calibrate", action="store_true",
        help="Calibrate base correlation from market data",
    )
    parser.add_argument(
        "--equity-upfront", type=float, default=35.0,
        help="Equity tranche upfront (%) for calibration (default: 35)",
    )
    parser.add_argument(
        "--equity-corr", type=float, default=0.25,
        help="Equity base correlation (default: 0.25)",
    )
    parser.add_argument(
        "--mezz-corr", type=float, default=0.45,
        help="Mezzanine base correlation (default: 0.45)",
    )
    parser.add_argument(
        "--senior-corr", type=float, default=0.65,
        help="Senior base correlation (default: 0.65)",
    )
    parser.add_argument(
        "--notional", type=float, default=10,
        help="Tranche notional in millions (default: 10)",
    )
    args = parser.parse_args()

    if args.calibrate:
        cmd_calibrate(args)
    elif args.strategy:
        cmd_strategy(args)
    else:
        cmd_index_spread(args)


if __name__ == "__main__":
    main()

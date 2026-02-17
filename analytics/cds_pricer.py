"""
CDS Pricer - ISDA Standard Model Implementation

Prices single-name CDS contracts using the ISDA standard model.
Supports:
- Par spread calculation
- Mark-to-market valuation
- DV01 and CS01
- Hazard rate bootstrapping from market spreads
- Recovery rate sensitivity

References:
- ISDA CDS Standard Model (2014)
- O'Kane, D. (2008) "Modelling Single-name and Multi-name Credit Derivatives"
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, date
from loguru import logger


@dataclass
class CDSContract:
    """Represents a single-name CDS contract."""
    reference_entity: str
    notional: float = 10_000_000.0   # 10M standard
    spread_bps: float = 100.0        # Running spread in bps
    recovery_rate: float = 0.40      # Standard 40% for senior unsecured
    maturity_years: float = 5.0      # Standard 5Y
    currency: str = "EUR"
    trade_date: Optional[date] = None
    coupon_bps: float = 100.0        # Standard coupon (100bps for IG, 500bps for HY)


@dataclass
class CDSValuation:
    """CDS valuation output."""
    par_spread_bps: float
    mark_to_market: float
    upfront_pct: float
    dv01: float                      # Dollar value of 1bp spread move
    cs01: float                      # Credit spread 01
    hazard_rate: float               # Annualised default probability
    survival_prob_5y: float          # 5-year survival probability
    jump_to_default: float           # Loss if immediate default


def bootstrap_hazard_rate(
    spread_bps: float,
    recovery_rate: float = 0.40,
) -> float:
    """
    Bootstrap flat hazard rate from market spread.

    Uses the approximation: h ≈ s / (1 - R)
    where h = hazard rate, s = spread, R = recovery rate.
    """
    spread_decimal = spread_bps / 10_000.0
    if recovery_rate >= 1.0:
        return 0.0
    return spread_decimal / (1.0 - recovery_rate)


def survival_probability(
    hazard_rate: float,
    time_years: float,
) -> float:
    """Calculate survival probability: Q(t) = exp(-h*t)."""
    return np.exp(-hazard_rate * time_years)


def price_cds(
    contract: CDSContract,
    discount_rate: float = 0.03,
    time_steps_per_year: int = 4,
) -> CDSValuation:
    """
    Price a CDS contract using the ISDA standard model approximation.

    Uses a simplified implementation of the hazard rate model:
    1. Bootstrap hazard rate from market spread
    2. Calculate protection leg PV (expected loss payments)
    3. Calculate premium leg PV (expected spread payments)
    4. Compute par spread, MTM, and risk sensitivities

    Args:
        contract: CDS contract to price
        discount_rate: Risk-free discount rate
        time_steps_per_year: Quarterly payment frequency (4)

    Returns:
        CDSValuation with all pricing outputs
    """
    h = bootstrap_hazard_rate(contract.spread_bps, contract.recovery_rate)
    R = contract.recovery_rate
    T = contract.maturity_years
    r = discount_rate
    N = contract.notional
    dt = 1.0 / time_steps_per_year
    n_steps = int(T * time_steps_per_year)

    # Protection leg PV: sum of discounted expected loss payments
    protection_pv = 0.0
    # Premium leg PV: sum of discounted expected spread payments
    premium_pv = 0.0

    for i in range(1, n_steps + 1):
        t = i * dt
        t_prev = (i - 1) * dt

        # Survival probabilities
        q_t = survival_probability(h, t)
        q_prev = survival_probability(h, t_prev)

        # Discount factor
        df = np.exp(-r * t)

        # Protection leg: (1-R) * probability of default in period * DF
        default_prob = q_prev - q_t
        protection_pv += (1.0 - R) * default_prob * df

        # Premium leg: spread * dt * survival probability * DF
        premium_pv += dt * q_t * df

    # Par spread: the spread that makes MTM = 0
    par_spread_bps = (protection_pv / premium_pv) * 10_000.0 if premium_pv > 0 else 0.0

    # Mark-to-market
    coupon_decimal = contract.coupon_bps / 10_000.0
    mtm = N * (protection_pv - coupon_decimal * premium_pv)

    # Upfront percentage
    upfront_pct = (contract.spread_bps - contract.coupon_bps) / 10_000.0 * premium_pv

    # DV01: change in MTM for 1bp spread move
    h_up = bootstrap_hazard_rate(contract.spread_bps + 1.0, contract.recovery_rate)
    protection_pv_up = 0.0
    premium_pv_up = 0.0
    for i in range(1, n_steps + 1):
        t = i * dt
        t_prev = (i - 1) * dt
        q_t = survival_probability(h_up, t)
        q_prev = survival_probability(h_up, t_prev)
        df = np.exp(-r * t)
        protection_pv_up += (1.0 - R) * (q_prev - q_t) * df
        premium_pv_up += dt * q_t * df

    mtm_up = N * (protection_pv_up - coupon_decimal * premium_pv_up)
    dv01 = abs(mtm_up - mtm)

    # CS01 (same as DV01 for single-name CDS)
    cs01 = dv01

    # Jump-to-default loss
    jtd = N * (1.0 - R)

    # 5Y survival probability
    surv_5y = survival_probability(h, 5.0)

    return CDSValuation(
        par_spread_bps=par_spread_bps,
        mark_to_market=mtm,
        upfront_pct=upfront_pct,
        dv01=dv01,
        cs01=cs01,
        hazard_rate=h,
        survival_prob_5y=surv_5y,
        jump_to_default=jtd,
    )


def spread_sensitivity(
    contract: CDSContract,
    spread_shocks_bps: List[float] = None,
    discount_rate: float = 0.03,
) -> Dict[float, float]:
    """
    Calculate MTM across a range of spread shocks.

    Args:
        contract: Base CDS contract
        spread_shocks_bps: List of spread changes to evaluate
        discount_rate: Risk-free rate

    Returns:
        Dict mapping spread_shock → MTM
    """
    if spread_shocks_bps is None:
        spread_shocks_bps = [-100, -50, -25, -10, 0, 10, 25, 50, 100, 200]

    results = {}
    for shock in spread_shocks_bps:
        shocked = CDSContract(
            reference_entity=contract.reference_entity,
            notional=contract.notional,
            spread_bps=max(1.0, contract.spread_bps + shock),
            recovery_rate=contract.recovery_rate,
            maturity_years=contract.maturity_years,
            currency=contract.currency,
            coupon_bps=contract.coupon_bps,
        )
        val = price_cds(shocked, discount_rate)
        results[shock] = val.mark_to_market

    return results


def recovery_sensitivity(
    contract: CDSContract,
    recovery_rates: List[float] = None,
    discount_rate: float = 0.03,
) -> Dict[float, CDSValuation]:
    """
    Calculate valuations across recovery rate assumptions.

    Args:
        contract: Base CDS contract
        recovery_rates: List of recovery rates to test
        discount_rate: Risk-free rate

    Returns:
        Dict mapping recovery_rate → CDSValuation
    """
    if recovery_rates is None:
        recovery_rates = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]

    results = {}
    for rr in recovery_rates:
        shocked = CDSContract(
            reference_entity=contract.reference_entity,
            notional=contract.notional,
            spread_bps=contract.spread_bps,
            recovery_rate=rr,
            maturity_years=contract.maturity_years,
            currency=contract.currency,
            coupon_bps=contract.coupon_bps,
        )
        results[rr] = price_cds(shocked, discount_rate)

    return results

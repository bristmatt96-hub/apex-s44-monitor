"""
Risk Metrics

Credit portfolio risk calculations:
- DV01 (dollar value of 1bp)
- CS01 (credit spread 01)
- Jump-to-default (JTD)
- Spread VaR (Value at Risk)
- Expected shortfall
- Concentration metrics
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class PositionRisk:
    """Risk metrics for a single position."""
    entity_name: str
    notional: float
    spread_bps: float
    dv01: float
    cs01: float
    jump_to_default: float
    recovery_rate: float
    direction: str  # long / short


@dataclass
class PortfolioRisk:
    """Aggregated portfolio risk metrics."""
    total_dv01: float
    total_cs01: float
    total_jtd_long: float      # JTD if any long protection name defaults
    total_jtd_short: float     # JTD exposure on short protection
    gross_notional: float
    net_notional: float
    spread_var_95: float       # 1-day 95% VaR
    spread_var_99: float       # 1-day 99% VaR
    expected_shortfall_95: float
    concentration_hhi: float   # Herfindahl index (0-1)
    largest_position_pct: float
    n_positions: int


def compute_dv01(
    notional: float,
    spread_bps: float,
    maturity_years: float = 5.0,
    recovery_rate: float = 0.40,
) -> float:
    """
    Approximate DV01 for a CDS position.

    DV01 ≈ Notional × Risky Duration × 0.0001

    Risky duration accounts for the probability-weighted
    time the contract survives.
    """
    # Bootstrap hazard rate
    h = (spread_bps / 10_000.0) / (1.0 - recovery_rate)

    # Risky annuity (quarterly payments)
    risky_annuity = 0.0
    for t in np.arange(0.25, maturity_years + 0.01, 0.25):
        surv = np.exp(-h * t)
        disc = np.exp(-0.03 * t)  # Assume 3% risk-free
        risky_annuity += 0.25 * surv * disc

    return notional * risky_annuity * 0.0001


def compute_jtd(
    notional: float,
    recovery_rate: float = 0.40,
) -> float:
    """Jump-to-default loss = Notional × (1 - Recovery)."""
    return notional * (1.0 - recovery_rate)


def compute_spread_var(
    positions: List[PositionRisk],
    confidence: float = 0.95,
    holding_period_days: int = 1,
    spread_vol_bps: float = 5.0,
) -> float:
    """
    Parametric spread VaR using normal distribution assumption.

    VaR = sum(DV01 * direction_sign) * spread_vol * z_score * sqrt(T)

    Args:
        positions: List of position risk metrics
        confidence: Confidence level (0.95 or 0.99)
        holding_period_days: Holding period
        spread_vol_bps: Daily spread volatility in bps

    Returns:
        VaR in currency units (positive = potential loss)
    """
    from scipy.stats import norm

    z = norm.ppf(confidence)
    sqrt_t = np.sqrt(holding_period_days)

    # Net DV01 exposure (long protection = positive, short = negative)
    total_risk = 0.0
    for pos in positions:
        sign = 1.0 if pos.direction == "long" else -1.0
        total_risk += pos.dv01 * sign

    var = abs(total_risk) * spread_vol_bps * z * sqrt_t
    return var


def compute_portfolio_risk(
    positions: List[PositionRisk],
    spread_vol_bps: float = 5.0,
) -> PortfolioRisk:
    """
    Compute full portfolio risk metrics.

    Args:
        positions: List of position risk metrics
        spread_vol_bps: Daily spread volatility assumption

    Returns:
        PortfolioRisk with all aggregated metrics
    """
    if not positions:
        return PortfolioRisk(
            total_dv01=0, total_cs01=0, total_jtd_long=0, total_jtd_short=0,
            gross_notional=0, net_notional=0, spread_var_95=0, spread_var_99=0,
            expected_shortfall_95=0, concentration_hhi=0, largest_position_pct=0,
            n_positions=0,
        )

    total_dv01 = sum(p.dv01 for p in positions)
    total_cs01 = sum(p.cs01 for p in positions)

    # JTD by direction
    jtd_long = sum(p.jump_to_default for p in positions if p.direction == "long")
    jtd_short = sum(p.jump_to_default for p in positions if p.direction == "short")

    # Notionals
    gross = sum(abs(p.notional) for p in positions)
    long_notional = sum(p.notional for p in positions if p.direction == "long")
    short_notional = sum(p.notional for p in positions if p.direction == "short")
    net = abs(long_notional - short_notional)

    # VaR
    var_95 = compute_spread_var(positions, 0.95, spread_vol_bps=spread_vol_bps)
    var_99 = compute_spread_var(positions, 0.99, spread_vol_bps=spread_vol_bps)

    # Expected shortfall (approximate: ES ≈ VaR * 1.28 for normal)
    es_95 = var_95 * 1.28

    # Concentration (HHI)
    if gross > 0:
        weights = [abs(p.notional) / gross for p in positions]
        hhi = sum(w**2 for w in weights)
        largest_pct = max(weights)
    else:
        hhi = 0.0
        largest_pct = 0.0

    return PortfolioRisk(
        total_dv01=total_dv01,
        total_cs01=total_cs01,
        total_jtd_long=jtd_long,
        total_jtd_short=jtd_short,
        gross_notional=gross,
        net_notional=net,
        spread_var_95=var_95,
        spread_var_99=var_99,
        expected_shortfall_95=es_95,
        concentration_hhi=hhi,
        largest_position_pct=largest_pct,
        n_positions=len(positions),
    )

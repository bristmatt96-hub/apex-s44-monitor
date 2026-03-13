"""
Tranche Pricer - Gaussian Copula + Base Correlation

Prices CDO tranches (iTraxx Main and Crossover tranches) using:
- One-factor Gaussian copula model
- Base correlation framework
- Large homogeneous pool approximation

References:
- Li, D.X. (2000) "On Default Correlation: A Copula Function Approach"
- O'Kane, D. (2008) "Modelling Single-name and Multi-name Credit Derivatives"
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger


@dataclass
class TrancheSpec:
    """Defines a CDO tranche."""
    name: str
    attachment: float      # Lower strike (e.g. 0.03 for 3%)
    detachment: float      # Upper strike (e.g. 0.06 for 6%)
    index_name: str = "iTraxx Crossover S44"


@dataclass
class TrancheValuation:
    """Tranche pricing output."""
    tranche_name: str
    expected_loss: float
    spread_bps: float
    delta: float           # Sensitivity to index spread
    base_correlation: float
    subordination: float   # Protection from lower tranches


# Standard iTraxx tranche definitions
ITRAXX_MAIN_TRANCHES = [
    TrancheSpec("0-3%", 0.00, 0.03, "iTraxx Main"),
    TrancheSpec("3-6%", 0.03, 0.06, "iTraxx Main"),
    TrancheSpec("6-9%", 0.06, 0.09, "iTraxx Main"),
    TrancheSpec("9-12%", 0.09, 0.12, "iTraxx Main"),
    TrancheSpec("12-22%", 0.12, 0.22, "iTraxx Main"),
    TrancheSpec("22-100%", 0.22, 1.00, "iTraxx Main"),
]

ITRAXX_XOVER_TRANCHES = [
    TrancheSpec("0-10%", 0.00, 0.10, "iTraxx Crossover"),
    TrancheSpec("10-15%", 0.10, 0.15, "iTraxx Crossover"),
    TrancheSpec("15-25%", 0.15, 0.25, "iTraxx Crossover"),
    TrancheSpec("25-35%", 0.25, 0.35, "iTraxx Crossover"),
    TrancheSpec("35-100%", 0.35, 1.00, "iTraxx Crossover"),
]


def _gaussian_copula_loss_distribution(
    n_names: int,
    default_prob: float,
    correlation: float,
    n_integration_points: int = 50,
) -> np.ndarray:
    """
    Compute portfolio loss distribution using one-factor Gaussian copula.

    Uses the large homogeneous pool (LHP) approximation where all
    names have the same default probability and pairwise correlation.

    Args:
        n_names: Number of names in the portfolio
        default_prob: Individual default probability
        correlation: Pairwise asset correlation (rho)
        n_integration_points: Gauss-Hermite quadrature points

    Returns:
        Array of (loss_fraction, probability) pairs
    """
    if correlation <= 0 or correlation >= 1:
        correlation = max(0.001, min(0.999, correlation))

    sqrt_rho = np.sqrt(correlation)
    sqrt_1_rho = np.sqrt(1.0 - correlation)

    # Gauss-Hermite quadrature for the common factor
    points, weights = np.polynomial.hermite.hermgauss(n_integration_points)
    # Transform to standard normal
    points = points * np.sqrt(2)
    weights = weights / np.sqrt(np.pi)

    # For each common factor realisation, compute conditional default prob
    losses = np.zeros(n_names + 1)

    for z, w in zip(points, weights):
        # Conditional default probability given common factor z
        cond_dp = norm.cdf(
            (norm.ppf(default_prob) - sqrt_rho * z) / sqrt_1_rho
        )
        # Expected loss fraction = conditional default probability
        # Using LHP approximation (n → ∞), loss is deterministic given z
        loss_fraction = cond_dp
        loss_idx = min(int(loss_fraction * n_names + 0.5), n_names)
        losses[loss_idx] += w

    return losses


def expected_tranche_loss(
    attachment: float,
    detachment: float,
    portfolio_loss_dist: np.ndarray,
    n_names: int,
    recovery_rate: float = 0.40,
) -> float:
    """
    Calculate expected loss for a tranche given the portfolio loss distribution.

    Args:
        attachment: Lower strike
        detachment: Upper strike
        portfolio_loss_dist: Loss distribution from copula model
        n_names: Number of names
        recovery_rate: Recovery rate assumption

    Returns:
        Expected tranche loss as fraction of tranche notional
    """
    tranche_width = detachment - attachment
    if tranche_width <= 0:
        return 0.0

    total_el = 0.0
    for i, prob in enumerate(portfolio_loss_dist):
        if prob < 1e-15:
            continue
        loss_fraction = (i / n_names) * (1.0 - recovery_rate)
        # Tranche loss = max(0, min(loss - attachment, tranche_width)) / tranche_width
        tranche_loss = max(0.0, min(loss_fraction - attachment, tranche_width))
        total_el += prob * tranche_loss / tranche_width

    return total_el


def price_tranche(
    tranche: TrancheSpec,
    index_spread_bps: float,
    n_names: int = 75,
    recovery_rate: float = 0.40,
    correlation: float = 0.30,
    maturity_years: float = 5.0,
    discount_rate: float = 0.03,
) -> TrancheValuation:
    """
    Price a CDO tranche using the Gaussian copula model.

    Args:
        tranche: Tranche specification
        index_spread_bps: Current index spread
        n_names: Number of names in the index
        recovery_rate: Average recovery rate
        correlation: Asset correlation (or base correlation)
        maturity_years: Tranche maturity
        discount_rate: Risk-free rate

    Returns:
        TrancheValuation with spread and risk metrics
    """
    from analytics.cds_pricer import bootstrap_hazard_rate, survival_probability

    # Bootstrap hazard rate from index spread
    h = bootstrap_hazard_rate(index_spread_bps, recovery_rate)
    default_prob = 1.0 - survival_probability(h, maturity_years)

    # Compute loss distribution
    loss_dist = _gaussian_copula_loss_distribution(
        n_names, default_prob, correlation
    )

    # Expected tranche loss
    el = expected_tranche_loss(
        tranche.attachment, tranche.detachment,
        loss_dist, n_names, recovery_rate
    )

    # Tranche spread (simplified: EL / risky annuity)
    # Risky annuity ≈ sum of discounted survival probabilities
    risky_annuity = sum(
        np.exp(-discount_rate * t) * survival_probability(h, t)
        for t in np.arange(0.25, maturity_years + 0.01, 0.25)
    ) * 0.25

    tranche_spread_bps = (el / risky_annuity * 10_000.0) if risky_annuity > 0 else 0.0

    # Delta: sensitivity to 1bp index spread move
    h_up = bootstrap_hazard_rate(index_spread_bps + 1.0, recovery_rate)
    dp_up = 1.0 - survival_probability(h_up, maturity_years)
    loss_dist_up = _gaussian_copula_loss_distribution(n_names, dp_up, correlation)
    el_up = expected_tranche_loss(
        tranche.attachment, tranche.detachment,
        loss_dist_up, n_names, recovery_rate
    )
    delta = (el_up - el) * 10_000.0

    return TrancheValuation(
        tranche_name=tranche.name,
        expected_loss=el,
        spread_bps=tranche_spread_bps,
        delta=delta,
        base_correlation=correlation,
        subordination=tranche.attachment,
    )


def calibrate_base_correlation(
    tranche: TrancheSpec,
    market_spread_bps: float,
    index_spread_bps: float,
    n_names: int = 75,
    recovery_rate: float = 0.40,
    maturity_years: float = 5.0,
) -> float:
    """
    Calibrate base correlation to match market tranche spread.

    Finds the correlation parameter that reproduces the observed
    market spread for a given tranche.

    Args:
        tranche: Tranche to calibrate
        market_spread_bps: Observed market spread
        index_spread_bps: Current index spread
        n_names: Number of index names
        recovery_rate: Recovery rate
        maturity_years: Maturity

    Returns:
        Implied base correlation
    """
    def objective(rho):
        val = price_tranche(
            tranche, index_spread_bps, n_names,
            recovery_rate, rho, maturity_years
        )
        return val.spread_bps - market_spread_bps

    try:
        result = brentq(objective, 0.01, 0.99, xtol=1e-6)
        return result
    except ValueError:
        logger.warning(
            "Base correlation calibration failed for {} at {}bps",
            tranche.name, market_spread_bps
        )
        return 0.30  # Return default

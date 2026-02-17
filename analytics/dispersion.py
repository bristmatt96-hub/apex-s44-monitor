"""
Dispersion Analysis

Implied vs realised correlation and dispersion metrics.
Key for:
- Tranche trading (correlation is the key input)
- Single-name vs index basis trades
- Identifying idiosyncratic vs systematic risk periods
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class DispersionMetrics:
    """Dispersion and correlation metrics."""
    implied_correlation: float       # From tranche market
    realised_correlation: float      # From spread moves
    correlation_gap: float           # Implied minus realised
    spread_dispersion: float         # Cross-sectional std of spread changes
    spread_dispersion_z: float       # Dispersion z-score vs history
    idiosyncratic_ratio: float       # Fraction of variance from idiosyncratic risk
    regime_signal: str               # high_dispersion / low_dispersion / normal


def compute_realised_correlation(
    spread_changes: Dict[str, List[float]],
) -> float:
    """
    Compute average pairwise correlation of spread changes.

    Args:
        spread_changes: Dict of entity_name → list of daily spread changes

    Returns:
        Average pairwise correlation
    """
    entities = list(spread_changes.keys())
    n = len(entities)
    if n < 2:
        return 0.0

    # Build matrix of spread changes
    min_len = min(len(v) for v in spread_changes.values())
    if min_len < 10:
        return 0.0

    matrix = np.array([spread_changes[e][:min_len] for e in entities])

    # Correlation matrix
    corr_matrix = np.corrcoef(matrix)

    # Average off-diagonal correlation
    mask = ~np.eye(n, dtype=bool)
    avg_corr = np.mean(corr_matrix[mask])

    return float(avg_corr)


def compute_spread_dispersion(
    spread_changes: Dict[str, List[float]],
    lookback: int = 20,
) -> float:
    """
    Compute cross-sectional dispersion of spread changes.

    High dispersion = idiosyncratic moves dominating
    Low dispersion = systematic/correlated moves
    """
    if not spread_changes:
        return 0.0

    # Get most recent changes
    recent = []
    for changes in spread_changes.values():
        if len(changes) >= lookback:
            recent.append(np.std(changes[-lookback:]))

    if not recent:
        return 0.0

    return float(np.mean(recent))


def compute_dispersion_metrics(
    spread_changes: Dict[str, List[float]],
    implied_correlation: float = 0.30,
    historical_dispersion: List[float] = None,
) -> DispersionMetrics:
    """
    Compute full dispersion metrics.

    Args:
        spread_changes: Entity → daily spread change series
        implied_correlation: Current implied correlation from tranche market
        historical_dispersion: Historical dispersion values for z-score

    Returns:
        DispersionMetrics
    """
    realised = compute_realised_correlation(spread_changes)
    dispersion = compute_spread_dispersion(spread_changes)

    # Correlation gap
    gap = implied_correlation - realised

    # Dispersion z-score
    if historical_dispersion and len(historical_dispersion) > 10:
        mean_d = np.mean(historical_dispersion)
        std_d = np.std(historical_dispersion)
        z = (dispersion - mean_d) / std_d if std_d > 0 else 0.0
    else:
        z = 0.0

    # Idiosyncratic ratio (1 - correlation ≈ idiosyncratic fraction)
    idio_ratio = max(0.0, 1.0 - abs(realised))

    # Signal
    if z > 1.0:
        signal = "high_dispersion"
    elif z < -1.0:
        signal = "low_dispersion"
    else:
        signal = "normal"

    return DispersionMetrics(
        implied_correlation=implied_correlation,
        realised_correlation=realised,
        correlation_gap=gap,
        spread_dispersion=dispersion,
        spread_dispersion_z=z,
        idiosyncratic_ratio=idio_ratio,
        regime_signal=signal,
    )

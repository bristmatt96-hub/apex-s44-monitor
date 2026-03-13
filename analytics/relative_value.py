"""
Relative Value Analysis

Rich/cheap scoring across the credit universe.
Compares names on:
- Current spread vs historical average (z-score)
- Spread vs fundamental fair value
- Sector relative value
- Index basis (single-name vs index-implied spread)
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class RVScore:
    """Relative value score for a single name."""
    entity_name: str
    current_spread_bps: float
    fair_spread_bps: float
    historical_mean_bps: float
    historical_std_bps: float
    z_score: float                  # (current - mean) / std
    rv_score: float                 # Composite RV score (-100 to +100)
    sector: str = ""
    sector_percentile: float = 0.5  # Where it sits vs sector peers
    index_basis_bps: float = 0.0    # Single-name minus index-implied
    signal: str = "flat"            # cheap / rich / flat


def compute_z_score(
    current: float,
    historical_spreads: List[float],
) -> tuple:
    """Compute z-score of current spread vs historical."""
    if len(historical_spreads) < 5:
        return 0.0, current, 0.0

    mean = np.mean(historical_spreads)
    std = np.std(historical_spreads)

    if std < 1.0:
        return 0.0, mean, std

    z = (current - mean) / std
    return z, mean, std


def sector_percentile(
    entity_spread: float,
    sector_spreads: List[float],
) -> float:
    """Rank a name's spread within its sector peers."""
    if not sector_spreads:
        return 0.5

    below = sum(1 for s in sector_spreads if s < entity_spread)
    return below / len(sector_spreads)


def compute_rv_score(
    current_spread_bps: float,
    fair_spread_bps: float,
    historical_spreads: List[float] = None,
    sector_spreads: List[float] = None,
    index_implied_bps: float = None,
    sector: str = "",
    entity_name: str = "",
) -> RVScore:
    """
    Compute composite relative value score.

    Positive RV score = cheap (buy protection is expensive, short protection)
    Negative RV score = rich (buy protection is cheap, buy protection)

    Components:
    1. Fair value gap: current vs model fair spread (40% weight)
    2. Z-score: current vs historical distribution (30% weight)
    3. Sector relative: ranking within peers (20% weight)
    4. Index basis: single-name vs index implied (10% weight)
    """
    # 1. Fair value gap
    if fair_spread_bps > 0:
        fv_gap = (current_spread_bps - fair_spread_bps) / fair_spread_bps * 100
    else:
        fv_gap = 0.0

    # 2. Z-score
    if historical_spreads:
        z, hist_mean, hist_std = compute_z_score(current_spread_bps, historical_spreads)
    else:
        z, hist_mean, hist_std = 0.0, current_spread_bps, 0.0

    # 3. Sector percentile
    if sector_spreads:
        sect_pct = sector_percentile(current_spread_bps, sector_spreads)
    else:
        sect_pct = 0.5

    # 4. Index basis
    if index_implied_bps is not None:
        basis = current_spread_bps - index_implied_bps
    else:
        basis = 0.0

    # Composite score
    rv = (
        0.40 * np.clip(fv_gap, -100, 100) +
        0.30 * np.clip(z * 25, -100, 100) +    # Scale z-score
        0.20 * (sect_pct - 0.5) * 200 +         # Centre on 0
        0.10 * np.clip(basis / 5, -100, 100)     # Scale basis
    )

    # Signal
    if rv > 15:
        signal = "cheap"   # Wide vs fair → short protection
    elif rv < -15:
        signal = "rich"    # Tight vs fair → buy protection
    else:
        signal = "flat"

    return RVScore(
        entity_name=entity_name,
        current_spread_bps=current_spread_bps,
        fair_spread_bps=fair_spread_bps,
        historical_mean_bps=hist_mean,
        historical_std_bps=hist_std,
        z_score=z,
        rv_score=float(np.clip(rv, -100, 100)),
        sector=sector,
        sector_percentile=sect_pct,
        index_basis_bps=basis,
        signal=signal,
    )


def rank_universe(
    scores: List[RVScore],
) -> List[RVScore]:
    """Rank the universe by absolute RV score (biggest mispricings first)."""
    return sorted(scores, key=lambda s: abs(s.rv_score), reverse=True)

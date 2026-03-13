"""
Maturity Wall Analysis

Analyses HY debt maturity profiles to identify refinancing risk.
Key for:
- Identifying credits that MUST refinance at higher rates
- Sector-level maturity wall pressure
- Timing of spread widening from refinancing stress

Uses data/maturity_wall.json for the Xover S44 universe.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class MaturityProfile:
    """Maturity profile for a single entity."""
    entity_name: str
    total_debt: float                    # Total outstanding debt
    maturities: Dict[str, float]        # year → amount maturing
    nearest_maturity_year: int
    nearest_maturity_amount: float
    pct_maturing_2y: float              # % of total debt maturing within 2 years
    pct_maturing_3y: float              # % within 3 years
    refinancing_risk: str                # low / medium / high / critical
    current_spread_bps: Optional[float] = None
    sector: str = ""


@dataclass
class MaturityWallSummary:
    """Sector/universe level maturity wall summary."""
    total_maturing_2y: float
    total_maturing_3y: float
    critical_names: List[str]
    high_risk_names: List[str]
    by_year: Dict[str, float]
    by_sector: Dict[str, float]


def load_maturity_data(data_path: str = None) -> Dict:
    """Load maturity wall data from JSON."""
    if data_path is None:
        data_path = Path("data/maturity_wall.json")
    else:
        data_path = Path(data_path)

    if not data_path.exists():
        logger.warning("Maturity data not found at {}", data_path)
        return {}

    with open(data_path) as f:
        return json.load(f)


def assess_refinancing_risk(
    pct_2y: float,
    spread_bps: float = None,
    leverage: float = None,
) -> str:
    """
    Classify refinancing risk based on maturity profile and fundamentals.

    Critical: >40% of debt maturing in 2 years + wide spreads
    High: >30% in 2 years or >50% in 3 years
    Medium: >15% in 2 years
    Low: <15% in 2 years
    """
    risk = "low"

    if pct_2y > 0.40:
        risk = "critical"
    elif pct_2y > 0.30:
        risk = "high"
    elif pct_2y > 0.15:
        risk = "medium"

    # Upgrade risk if spreads are wide (harder to refinance)
    if spread_bps and spread_bps > 500 and risk == "medium":
        risk = "high"
    if spread_bps and spread_bps > 800 and risk == "high":
        risk = "critical"

    # Upgrade risk if leverage is high
    if leverage and leverage > 5.0 and risk in ("medium", "low"):
        risk = "high" if risk == "medium" else "medium"

    return risk


def analyze_maturity_profile(
    entity_name: str,
    maturities: Dict[str, float],
    total_debt: float = None,
    spread_bps: float = None,
    leverage: float = None,
    sector: str = "",
) -> MaturityProfile:
    """
    Analyze maturity profile for a single entity.

    Args:
        entity_name: Company name
        maturities: Dict of year → amount maturing
        total_debt: Total outstanding debt (calculated if None)
        spread_bps: Current CDS spread
        leverage: Net debt / EBITDA
        sector: Sector classification

    Returns:
        MaturityProfile with risk assessment
    """
    current_year = datetime.now().year

    if total_debt is None:
        total_debt = sum(maturities.values())

    if total_debt <= 0:
        return MaturityProfile(
            entity_name=entity_name,
            total_debt=0,
            maturities=maturities,
            nearest_maturity_year=0,
            nearest_maturity_amount=0,
            pct_maturing_2y=0,
            pct_maturing_3y=0,
            refinancing_risk="low",
            current_spread_bps=spread_bps,
            sector=sector,
        )

    # Calculate maturity buckets
    maturing_2y = sum(
        amt for year_str, amt in maturities.items()
        if int(year_str) <= current_year + 2
    )
    maturing_3y = sum(
        amt for year_str, amt in maturities.items()
        if int(year_str) <= current_year + 3
    )

    pct_2y = maturing_2y / total_debt
    pct_3y = maturing_3y / total_debt

    # Nearest maturity
    future_maturities = {
        int(y): a for y, a in maturities.items()
        if int(y) >= current_year and a > 0
    }
    if future_maturities:
        nearest_year = min(future_maturities.keys())
        nearest_amount = future_maturities[nearest_year]
    else:
        nearest_year = 0
        nearest_amount = 0

    risk = assess_refinancing_risk(pct_2y, spread_bps, leverage)

    return MaturityProfile(
        entity_name=entity_name,
        total_debt=total_debt,
        maturities=maturities,
        nearest_maturity_year=nearest_year,
        nearest_maturity_amount=nearest_amount,
        pct_maturing_2y=pct_2y,
        pct_maturing_3y=pct_3y,
        refinancing_risk=risk,
        current_spread_bps=spread_bps,
        sector=sector,
    )


def analyze_universe(
    maturity_data: Dict = None,
) -> MaturityWallSummary:
    """
    Analyze maturity wall across the full universe.

    Returns:
        MaturityWallSummary with aggregated metrics
    """
    if maturity_data is None:
        maturity_data = load_maturity_data()

    if not maturity_data:
        return MaturityWallSummary(
            total_maturing_2y=0, total_maturing_3y=0,
            critical_names=[], high_risk_names=[],
            by_year={}, by_sector={},
        )

    profiles = []
    by_year: Dict[str, float] = {}
    by_sector: Dict[str, float] = {}

    for entity_name, data in maturity_data.items():
        maturities = data.get("maturities", {})
        profile = analyze_maturity_profile(
            entity_name=entity_name,
            maturities=maturities,
            total_debt=data.get("total_debt"),
            spread_bps=data.get("spread_bps"),
            leverage=data.get("leverage"),
            sector=data.get("sector", ""),
        )
        profiles.append(profile)

        # Aggregate by year
        for year, amt in maturities.items():
            by_year[year] = by_year.get(year, 0.0) + amt

        # Aggregate by sector
        sector = profile.sector or "Other"
        by_sector[sector] = by_sector.get(sector, 0.0) + profile.total_debt

    critical = [p.entity_name for p in profiles if p.refinancing_risk == "critical"]
    high_risk = [p.entity_name for p in profiles if p.refinancing_risk == "high"]

    return MaturityWallSummary(
        total_maturing_2y=sum(p.pct_maturing_2y * p.total_debt for p in profiles),
        total_maturing_3y=sum(p.pct_maturing_3y * p.total_debt for p in profiles),
        critical_names=critical,
        high_risk_names=high_risk,
        by_year=dict(sorted(by_year.items())),
        by_sector=by_sector,
    )

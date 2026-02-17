"""
Core Data Models for Credit Catalyst

Domain models for credit analysis:
- Credit entities (reference entities, CDS contracts)
- Signals (credit recommendations)
- Market data (CDS spreads, bond prices)
- Portfolio positions
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, Dict, Any, List


class Direction(Enum):
    """Credit recommendation direction."""
    LONG = "long"       # Buy protection (bearish on credit)
    SHORT = "short"     # Sell protection (bullish on credit)
    FLAT = "flat"       # No position


class Conviction(Enum):
    """Conviction level for recommendations."""
    LOW = 1
    MEDIUM_LOW = 2
    MEDIUM = 3
    MEDIUM_HIGH = 4
    HIGH = 5


class RatingBucket(Enum):
    """Credit rating bucket."""
    IG = "IG"           # Investment grade (BBB- and above)
    BB = "BB"           # High yield BB
    B = "B"             # High yield B
    CCC = "CCC"         # Distressed
    NR = "NR"           # Not rated


class AlertPriority(Enum):
    """Alert priority level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class CreditEntity:
    """A reference entity in the credit universe."""
    name: str
    ticker: str
    sector: str = ""
    country: str = ""
    index_membership: List[str] = field(default_factory=list)  # e.g. ["iTraxx Xover S44", "iTraxx Main S44"]
    rating_sp: str = ""
    rating_moodys: str = ""
    rating_fitch: str = ""
    outlook: str = "stable"     # stable / negative / positive / watch_negative / watch_positive
    recovery_rate: float = 0.40
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def composite_rating(self) -> str:
        """Return the most conservative rating available."""
        ratings = [r for r in [self.rating_sp, self.rating_moodys, self.rating_fitch] if r]
        return ratings[0] if ratings else "NR"

    @property
    def rating_bucket(self) -> RatingBucket:
        """Classify into rating bucket."""
        r = self.composite_rating.upper().replace("+", "").replace("-", "")
        if r in ("AAA", "AA", "A", "BBB"):
            return RatingBucket.IG
        elif r in ("BB",):
            return RatingBucket.BB
        elif r in ("B",):
            return RatingBucket.B
        elif r in ("CCC", "CC", "C", "D"):
            return RatingBucket.CCC
        return RatingBucket.NR


@dataclass
class CreditSignal:
    """A credit recommendation signal."""
    entity_name: str
    direction: Direction
    conviction: int = 3             # 1-5
    fair_spread_bps: float = 0.0
    current_spread_bps: float = 0.0
    credit_score: float = 50.0      # 0-100
    source: str = ""                # Which agent/monitor generated this
    timestamp: datetime = field(default_factory=datetime.now)
    reasoning: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def spread_gap_bps(self) -> float:
        """Gap between current and fair spread."""
        return self.current_spread_bps - self.fair_spread_bps


@dataclass
class CDSSpread:
    """CDS spread observation."""
    entity_name: str
    spread_bps: float
    tenor: str = "5Y"              # 1Y, 3Y, 5Y, 7Y, 10Y
    currency: str = "EUR"
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""


@dataclass
class CreditPosition:
    """A CDS position in the portfolio."""
    entity_name: str
    direction: Direction            # Long = bought protection, Short = sold protection
    notional: float = 10_000_000.0
    spread_at_entry_bps: float = 0.0
    current_spread_bps: float = 0.0
    recovery_rate: float = 0.40
    maturity_years: float = 5.0
    coupon_bps: float = 100.0      # 100 for IG, 500 for HY
    entry_date: Optional[date] = None
    dv01: float = 0.0
    mtm: float = 0.0

    @property
    def pnl_bps(self) -> float:
        """Mark-to-market P&L in basis points."""
        if self.direction == Direction.LONG:
            return self.current_spread_bps - self.spread_at_entry_bps
        elif self.direction == Direction.SHORT:
            return self.spread_at_entry_bps - self.current_spread_bps
        return 0.0


@dataclass
class CreditAlert:
    """A real-time credit alert."""
    entity_name: str
    alert_type: str             # RATING_ACTION, FILING, CREDIT_EVENT, EARNINGS, NEWS
    priority: AlertPriority
    headline: str
    detail: str = ""
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    actionable: bool = False
    suggested_action: Optional[str] = None


@dataclass
class PortfolioSummary:
    """Portfolio state at a point in time."""
    timestamp: datetime
    positions: List[CreditPosition]
    total_notional: float
    net_dv01: float
    total_mtm: float
    n_longs: int = 0
    n_shorts: int = 0
    n_names: int = 0

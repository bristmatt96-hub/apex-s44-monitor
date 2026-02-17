"""
Credit Catalyst - Core Infrastructure

Shared models, configuration, caching, and database access.
"""

from core.config import settings
from core.models import (
    CreditEntity,
    CreditSignal,
    CreditPosition,
    CreditAlert,
    CDSSpread,
    Direction,
    Conviction,
    RatingBucket,
    AlertPriority,
)

__all__ = [
    "settings",
    "CreditEntity",
    "CreditSignal",
    "CreditPosition",
    "CreditAlert",
    "CDSSpread",
    "Direction",
    "Conviction",
    "RatingBucket",
    "AlertPriority",
]

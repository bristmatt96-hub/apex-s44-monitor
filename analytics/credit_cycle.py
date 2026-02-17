"""
Credit Cycle Regime Classification

Classifies the current credit market regime using:
- ECB lending survey data
- Spread levels and volatility
- Default rate trends
- New issuance volumes
- Fund flow data

Regimes: expansion / late_cycle / downturn / recovery
"""

from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class RegimeClassification:
    """Credit cycle regime output."""
    regime: str                  # expansion / late_cycle / downturn / recovery
    confidence: float            # 0-1
    signals: Dict[str, str]     # Individual indicator readings
    transition_probability: float  # Probability of regime change in next quarter
    summary: str = ""
    date: str = ""


class CreditCycleClassifier:
    """
    Classifies credit market regime from macro and market signals.

    Uses a simple rules-based approach that can be enhanced with
    ML models as historical data accumulates.
    """

    # Thresholds for regime classification
    REGIME_RULES = {
        "expansion": {
            "spread_z": (-1.0, 0.5),       # Spreads below average
            "spread_trend": "tightening",
            "default_rate": (0.0, 2.0),     # Low defaults
        },
        "late_cycle": {
            "spread_z": (-0.5, 1.0),
            "spread_trend": "stable",
            "default_rate": (1.0, 3.0),
        },
        "downturn": {
            "spread_z": (0.5, 5.0),         # Spreads wide
            "spread_trend": "widening",
            "default_rate": (3.0, 20.0),
        },
        "recovery": {
            "spread_z": (0.0, 2.0),
            "spread_trend": "tightening",
            "default_rate": (2.0, 8.0),      # Defaults still elevated but falling
        },
    }

    def classify(
        self,
        spread_z_score: float = 0.0,
        spread_trend: str = "stable",
        default_rate_pct: float = 2.0,
        ecb_lending_tightening: bool = False,
        issuance_strong: bool = True,
    ) -> RegimeClassification:
        """
        Classify current regime from input signals.

        Args:
            spread_z_score: Current spread vs 5Y average (z-score)
            spread_trend: tightening / stable / widening
            default_rate_pct: Trailing 12M HY default rate
            ecb_lending_tightening: ECB survey shows tightening
            issuance_strong: HY new issuance above average

        Returns:
            RegimeClassification
        """
        scores = {regime: 0.0 for regime in self.REGIME_RULES}
        signals = {}

        # Score each regime
        for regime, rules in self.REGIME_RULES.items():
            z_lo, z_hi = rules["spread_z"]
            if z_lo <= spread_z_score <= z_hi:
                scores[regime] += 1.0

            if spread_trend == rules["spread_trend"]:
                scores[regime] += 1.0

            dr_lo, dr_hi = rules["default_rate"]
            if dr_lo <= default_rate_pct <= dr_hi:
                scores[regime] += 1.0

        # Additional signals
        if ecb_lending_tightening:
            scores["late_cycle"] += 0.5
            scores["downturn"] += 0.5
            signals["ecb_lending"] = "tightening"
        else:
            scores["expansion"] += 0.5
            signals["ecb_lending"] = "easing"

        if issuance_strong:
            scores["expansion"] += 0.5
            signals["issuance"] = "strong"
        else:
            scores["downturn"] += 0.3
            scores["late_cycle"] += 0.3
            signals["issuance"] = "weak"

        signals["spread_z"] = f"{spread_z_score:.1f}"
        signals["spread_trend"] = spread_trend
        signals["default_rate"] = f"{default_rate_pct:.1f}%"

        # Pick highest scoring regime
        best_regime = max(scores, key=scores.get)
        total = sum(scores.values())
        confidence = scores[best_regime] / total if total > 0 else 0.0

        return RegimeClassification(
            regime=best_regime,
            confidence=confidence,
            signals=signals,
            transition_probability=1.0 - confidence,
            summary=f"Credit cycle: {best_regime} (confidence {confidence:.0%})",
            date=datetime.now().strftime("%Y-%m-%d"),
        )

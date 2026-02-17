"""
Portfolio Strategist Agent

Takes individual credit assessments from the Analyst, overlays
macro regime, correlation structure, and tranche analysis to produce
portfolio-level recommendations.

Handles relative value across iTraxx Main and Crossover indices.

Outputs:
- Portfolio-level long/short recommendations
- Relative value rankings
- Index vs single-name basis trades
- Tranche strategy recommendations
- Risk budget allocation
"""

import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from core.config import settings
from agents.analyst import CreditAssessment


@dataclass
class PortfolioRecommendation:
    """Portfolio-level strategy output."""
    date: str
    regime: str                          # risk-on / risk-off / transitioning
    regime_confidence: float             # 0-1
    top_longs: List[Dict[str, Any]] = field(default_factory=list)
    top_shorts: List[Dict[str, Any]] = field(default_factory=list)
    basis_trades: List[Dict[str, Any]] = field(default_factory=list)
    tranche_view: Dict[str, Any] = field(default_factory=dict)
    risk_budget: Dict[str, float] = field(default_factory=dict)
    summary: str = ""


@dataclass
class RelativeValueScore:
    """Relative value ranking for a single name."""
    entity_name: str
    rv_score: float              # -100 (rich) to +100 (cheap)
    z_score: float               # Current spread vs historical
    peer_percentile: float       # Rank within sector
    basis_vs_index: float        # Single-name vs index spread
    direction: str = "flat"


class PortfolioStrategist:
    """
    AI-powered portfolio strategist for credit markets.

    Combines individual credit assessments with macro regime
    analysis and correlation structure to produce portfolio-level
    recommendations.
    """

    def __init__(self):
        self._client = None

    def _get_client(self):
        """Lazy-init Anthropic client."""
        if self._client is None and ANTHROPIC_AVAILABLE:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    async def build_portfolio_view(
        self,
        assessments: List[CreditAssessment],
        macro_context: Optional[Dict] = None,
    ) -> PortfolioRecommendation:
        """
        Build portfolio-level recommendations from individual assessments.

        Args:
            assessments: List of individual credit assessments
            macro_context: Optional macro indicators (ECB, PMIs, etc.)

        Returns:
            PortfolioRecommendation with top ideas and strategy
        """
        client = self._get_client()

        if not client:
            # Fallback: simple sorting by conviction * direction
            return self._build_simple_recommendation(assessments)

        # Build context for Claude
        assessment_summary = []
        for a in assessments:
            assessment_summary.append({
                "name": a.entity_name,
                "score": a.credit_score,
                "spread": a.fair_spread_bps,
                "direction": a.direction,
                "conviction": a.conviction,
                "sector": a.sector,
                "summary": a.summary,
            })

        user_msg = (
            "Based on the following individual credit assessments, "
            "provide portfolio-level recommendations.\n\n"
            f"Assessments:\n{json.dumps(assessment_summary, indent=2)}\n\n"
        )

        if macro_context:
            user_msg += f"Macro context:\n{json.dumps(macro_context, indent=2)}\n\n"

        user_msg += (
            "Provide:\n"
            "1. Top 5 long protection ideas (weakening credits)\n"
            "2. Top 5 short protection ideas (improving credits)\n"
            "3. Any index vs single-name basis trade opportunities\n"
            "4. Overall regime assessment (risk-on/risk-off)\n"
            "5. Risk budget allocation by sector\n\n"
            "Return as JSON."
        )

        try:
            response = client.messages.create(
                model=settings.llm.model,
                max_tokens=2048,
                system=(
                    "You are a credit portfolio strategist specialising in "
                    "iTraxx Main and Crossover. Produce actionable portfolio "
                    "recommendations with clear reasoning."
                ),
                messages=[{"role": "user", "content": user_msg}],
            )

            import re
            text = response.content[0].text
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = {}

            return PortfolioRecommendation(
                date=datetime.now().strftime("%Y-%m-%d"),
                regime=result.get("regime", "unknown"),
                regime_confidence=result.get("regime_confidence", 0.5),
                top_longs=result.get("top_longs", []),
                top_shorts=result.get("top_shorts", []),
                basis_trades=result.get("basis_trades", []),
                tranche_view=result.get("tranche_view", {}),
                risk_budget=result.get("risk_budget", {}),
                summary=result.get("summary", ""),
            )

        except Exception as e:
            logger.error("Portfolio strategy failed: {}", e)
            return self._build_simple_recommendation(assessments)

    def _build_simple_recommendation(
        self, assessments: List[CreditAssessment]
    ) -> PortfolioRecommendation:
        """Fallback: sort by conviction and direction."""
        shorts = sorted(
            [a for a in assessments if a.direction == "short"],
            key=lambda a: a.conviction,
            reverse=True,
        )
        longs = sorted(
            [a for a in assessments if a.direction == "long"],
            key=lambda a: a.conviction,
            reverse=True,
        )

        return PortfolioRecommendation(
            date=datetime.now().strftime("%Y-%m-%d"),
            regime="unknown",
            regime_confidence=0.0,
            top_longs=[
                {"name": a.entity_name, "conviction": a.conviction, "spread": a.fair_spread_bps}
                for a in longs[:5]
            ],
            top_shorts=[
                {"name": a.entity_name, "conviction": a.conviction, "spread": a.fair_spread_bps}
                for a in shorts[:5]
            ],
            summary="Simple sort by conviction (API unavailable)",
        )

    async def relative_value_screen(
        self, assessments: List[CreditAssessment]
    ) -> List[RelativeValueScore]:
        """
        Screen for relative value across the universe.

        Identifies names that are rich or cheap relative to:
        - Their own history
        - Sector peers
        - Index implied spread
        """
        scores = []
        for a in assessments:
            rv = RelativeValueScore(
                entity_name=a.entity_name,
                rv_score=0.0,
                z_score=0.0,
                peer_percentile=0.5,
                basis_vs_index=0.0,
                direction=a.direction,
            )

            # If we have spread data, compute basic RV metrics
            if a.current_spread_bps and a.fair_spread_bps:
                spread_diff = a.current_spread_bps - a.fair_spread_bps
                rv.rv_score = spread_diff  # positive = cheap, negative = rich
                rv.direction = "long" if spread_diff > 20 else ("short" if spread_diff < -20 else "flat")

            scores.append(rv)

        # Sort by absolute RV score (biggest mispricings first)
        scores.sort(key=lambda s: abs(s.rv_score), reverse=True)
        return scores

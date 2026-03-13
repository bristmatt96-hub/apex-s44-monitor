"""
Credit Analyst Agent

Takes raw data from monitors, applies ingested book knowledge,
runs analytics, and produces credit assessments using Claude API
with 471 knowledge chunks as context.

Outputs per name:
- Credit score (0-100)
- Fair spread estimate (bps)
- Direction: long / short / flat
- Conviction level: 1-5
- Key risk factors
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict
from loguru import logger

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from core.config import settings


@dataclass
class CreditAssessment:
    """Output of the credit analyst for a single name."""
    entity_name: str
    ticker: str
    assessment_date: str
    credit_score: float          # 0-100, higher = better credit quality
    fair_spread_bps: float       # Fair CDS spread estimate
    current_spread_bps: Optional[float] = None
    direction: str = "flat"      # long / short / flat (protection)
    conviction: int = 3          # 1 (low) to 5 (high)
    risk_factors: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    rating: Optional[str] = None
    sector: Optional[str] = None
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class CreditAnalyst:
    """
    AI-powered credit analyst using Claude API.

    Uses the knowledge base (471 chunks from credit analysis books)
    as system context for reasoning about credit quality.
    """

    def __init__(self):
        self.knowledge_path = Path("knowledge/processed")
        self.snapshots_path = Path("snapshots")
        self.knowledge_chunks: List[str] = []
        self._client = None

    def _get_client(self):
        """Lazy-init Anthropic client."""
        if self._client is None and ANTHROPIC_AVAILABLE:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def load_knowledge(self, max_chunks: int = 50) -> int:
        """Load knowledge base chunks for system context."""
        if not self.knowledge_path.exists():
            logger.warning("Knowledge base not found at {}", self.knowledge_path)
            return 0

        chunks = []
        for chunk_file in sorted(self.knowledge_path.glob("*.json"))[:max_chunks]:
            try:
                with open(chunk_file) as f:
                    data = json.load(f)
                    text = data.get("text", data.get("content", ""))
                    if text:
                        chunks.append(text)
            except Exception as e:
                logger.debug("Failed to load chunk {}: {}", chunk_file, e)

        self.knowledge_chunks = chunks
        logger.info("Loaded {} knowledge chunks", len(chunks))
        return len(chunks)

    def load_snapshot(self, entity_name: str) -> Optional[Dict]:
        """Load a company snapshot by name."""
        # Try exact filename match
        for snapshot_file in self.snapshots_path.glob("*.json"):
            try:
                with open(snapshot_file) as f:
                    data = json.load(f)
                    if data.get("company_name", "").lower() == entity_name.lower():
                        return data
            except Exception:
                continue

        # Try fuzzy filename match
        clean_name = entity_name.lower().replace(" ", "_").replace("-", "_")
        for snapshot_file in self.snapshots_path.glob("*.json"):
            if clean_name in snapshot_file.stem.lower():
                try:
                    with open(snapshot_file) as f:
                        return json.load(f)
                except Exception:
                    continue

        return None

    def _build_system_prompt(self) -> str:
        """Build system prompt with knowledge base context."""
        base = (
            "You are an expert credit analyst specializing in European high-yield "
            "and investment-grade credit markets. You analyse single-name CDS, "
            "iTraxx Main and Crossover index constituents.\n\n"
            "Your task is to assess credit quality and produce actionable "
            "recommendations (long protection, short protection, or flat) "
            "with conviction levels.\n\n"
            "Focus on: leverage ratios, interest coverage, FCF generation, "
            "maturity walls, covenant headroom, sponsor behaviour, sector "
            "dynamics, and rating agency trajectory.\n\n"
        )

        if self.knowledge_chunks:
            knowledge_context = "\n---\n".join(self.knowledge_chunks[:20])
            base += (
                "Reference knowledge from credit analysis literature:\n"
                f"{knowledge_context}\n\n"
            )

        return base

    async def assess_credit(
        self,
        entity_name: str,
        market_data: Optional[Dict] = None,
        news_context: Optional[str] = None,
    ) -> CreditAssessment:
        """
        Produce a credit assessment for a single name.

        Args:
            entity_name: Company/entity name
            market_data: Optional current market data (spreads, prices)
            news_context: Optional recent news/events context

        Returns:
            CreditAssessment with score, direction, and analysis
        """
        snapshot = self.load_snapshot(entity_name)
        client = self._get_client()

        if not client:
            logger.warning("Anthropic client not available, returning default assessment")
            return CreditAssessment(
                entity_name=entity_name,
                ticker="",
                assessment_date=datetime.now().strftime("%Y-%m-%d"),
                credit_score=50.0,
                fair_spread_bps=0.0,
                summary="Assessment unavailable - API not configured",
            )

        # Build the user message with all available context
        user_msg = f"Assess the credit quality of: {entity_name}\n\n"

        if snapshot:
            user_msg += f"Company data:\n{json.dumps(snapshot, indent=2, default=str)}\n\n"

        if market_data:
            user_msg += f"Current market data:\n{json.dumps(market_data, indent=2)}\n\n"

        if news_context:
            user_msg += f"Recent news/events:\n{news_context}\n\n"

        user_msg += (
            "Provide your assessment in the following JSON format:\n"
            "{\n"
            '  "credit_score": <0-100>,\n'
            '  "fair_spread_bps": <number>,\n'
            '  "direction": "long" | "short" | "flat",\n'
            '  "conviction": <1-5>,\n'
            '  "risk_factors": ["..."],\n'
            '  "catalysts": ["..."],\n'
            '  "summary": "2-3 sentence assessment"\n'
            "}"
        )

        try:
            response = client.messages.create(
                model=settings.llm.model,
                max_tokens=1024,
                system=self._build_system_prompt(),
                messages=[{"role": "user", "content": user_msg}],
            )

            # Parse response
            text = response.content[0].text
            # Try to extract JSON from the response
            import re
            json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = {}

            return CreditAssessment(
                entity_name=entity_name,
                ticker=snapshot.get("ticker", "") if snapshot else "",
                assessment_date=datetime.now().strftime("%Y-%m-%d"),
                credit_score=result.get("credit_score", 50.0),
                fair_spread_bps=result.get("fair_spread_bps", 0.0),
                direction=result.get("direction", "flat"),
                conviction=result.get("conviction", 3),
                risk_factors=result.get("risk_factors", []),
                catalysts=result.get("catalysts", []),
                rating=snapshot.get("ratings", {}).get("composite") if snapshot else None,
                sector=snapshot.get("sector") if snapshot else None,
                summary=result.get("summary", ""),
            )

        except Exception as e:
            logger.error("Credit assessment failed for {}: {}", entity_name, e)
            return CreditAssessment(
                entity_name=entity_name,
                ticker="",
                assessment_date=datetime.now().strftime("%Y-%m-%d"),
                credit_score=50.0,
                fair_spread_bps=0.0,
                summary=f"Assessment failed: {e}",
            )

    async def assess_universe(
        self, entity_names: List[str]
    ) -> List[CreditAssessment]:
        """Assess multiple credits sequentially."""
        assessments = []
        for name in entity_names:
            assessment = await self.assess_credit(name)
            assessments.append(assessment)
        return assessments

"""
Credit Catalyst - AI Agent Layer

Three-agent architecture for credit analysis:
- Analyst: Credit assessment per name using Claude API + knowledge base
- Strategist: Portfolio-level recommendations and relative value
- Briefing: Morning briefs, real-time alerts, weekly summaries
"""

from agents.analyst import CreditAnalyst
from agents.strategist import PortfolioStrategist
from agents.briefing import BriefingAgent

__all__ = ["CreditAnalyst", "PortfolioStrategist", "BriefingAgent"]

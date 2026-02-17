#!/usr/bin/env python3
"""
Credit Catalyst - Strategic Credit Analysis System

Identifies mispriced credits in iTraxx Main and Crossover,
outputs long/short/flat recommendations for single-name CDS,
and analyses index tranches.

Usage:
    python main.py                  # Show system status
    python main.py --assess NAME    # Assess a single credit
    python main.py --universe       # Assess full universe
    python main.py --brief          # Generate morning brief
    python main.py --rv             # Run relative value screen
    python main.py --scenarios      # Run scenario analysis
    python main.py --config         # Show configuration
"""

import asyncio
import argparse
import json
import signal
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    level="INFO",
)
logger.add(
    "logs/credit_catalyst_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
)


from core.config import settings


def load_universe() -> list:
    """Load the credit universe from indices/xover_s44.json."""
    xover_path = Path("indices/xover_s44.json")
    if not xover_path.exists():
        logger.warning("Index file not found: {}", xover_path)
        return []

    with open(xover_path) as f:
        data = json.load(f)

    # Handle both list and dict formats
    if isinstance(data, list):
        return [item.get("name", item.get("entity", "")) for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        return list(data.get("constituents", data.get("names", data)).keys()) if isinstance(
            data.get("constituents", data.get("names", data)), dict
        ) else data.get("constituents", data.get("names", []))

    return []


async def assess_single(name: str):
    """Assess a single credit name."""
    from agents.analyst import CreditAnalyst

    analyst = CreditAnalyst()
    analyst.load_knowledge(max_chunks=30)

    logger.info("Assessing credit: {}", name)
    assessment = await analyst.assess_credit(name)

    print(f"\n{'='*60}")
    print(f"CREDIT ASSESSMENT: {assessment.entity_name}")
    print(f"{'='*60}")
    print(f"Date:         {assessment.assessment_date}")
    print(f"Credit Score: {assessment.credit_score:.0f}/100")
    print(f"Fair Spread:  {assessment.fair_spread_bps:.0f}bps")
    print(f"Direction:    {assessment.direction.upper()}")
    print(f"Conviction:   {assessment.conviction}/5")
    print(f"Rating:       {assessment.rating or 'N/A'}")
    print(f"Sector:       {assessment.sector or 'N/A'}")
    if assessment.risk_factors:
        print(f"\nRisk Factors:")
        for rf in assessment.risk_factors:
            print(f"  - {rf}")
    if assessment.catalysts:
        print(f"\nCatalysts:")
        for c in assessment.catalysts:
            print(f"  - {c}")
    print(f"\nSummary: {assessment.summary}")
    print(f"{'='*60}\n")


async def assess_universe():
    """Assess the full credit universe."""
    from agents.analyst import CreditAnalyst
    from agents.strategist import PortfolioStrategist

    universe = load_universe()
    if not universe:
        logger.error("No names in universe")
        return

    analyst = CreditAnalyst()
    analyst.load_knowledge(max_chunks=30)

    logger.info("Assessing {} credits...", len(universe))
    assessments = await analyst.assess_universe(universe)

    # Portfolio-level view
    strategist = PortfolioStrategist()
    recommendation = await strategist.build_portfolio_view(assessments)

    print(f"\n{'='*60}")
    print(f"PORTFOLIO RECOMMENDATION")
    print(f"{'='*60}")
    print(f"Regime: {recommendation.regime} (confidence: {recommendation.regime_confidence:.0%})")
    print(f"\nTop Longs (buy protection):")
    for l in recommendation.top_longs[:5]:
        print(f"  - {l.get('name', 'N/A')} (conviction: {l.get('conviction', 'N/A')})")
    print(f"\nTop Shorts (sell protection):")
    for s in recommendation.top_shorts[:5]:
        print(f"  - {s.get('name', 'N/A')} (conviction: {s.get('conviction', 'N/A')})")
    print(f"\n{recommendation.summary}")
    print(f"{'='*60}\n")


async def generate_brief():
    """Generate and optionally send morning brief."""
    from agents.briefing import BriefingAgent

    briefer = BriefingAgent()
    brief = await briefer.generate_morning_brief()

    print(brief.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))

    # Send via Telegram if configured
    if settings.telegram.is_configured:
        sent = await briefer.send_morning_brief()
        if sent:
            logger.info("Morning brief sent via Telegram")


def show_config():
    """Display current configuration."""
    print(f"\n{'='*60}")
    print("Credit Catalyst Configuration")
    print(f"{'='*60}")
    print(f"\nLLM Model:    {settings.llm.model}")
    print(f"Database:     {settings.database.url}")
    print(f"Telegram:     {'configured' if settings.telegram.is_configured else 'not configured'}")
    print(f"Debug:        {settings.debug}")
    print(f"Log Level:    {settings.log_level}")
    print(f"\nIndex Config:")
    print(f"  iTraxx Main S{settings.indices.itraxx_main_series}: {settings.indices.itraxx_main_names} names")
    print(f"  iTraxx Xover S{settings.indices.itraxx_xover_series}: {settings.indices.itraxx_xover_names} names")
    print(f"\nAnalytics:")
    print(f"  Recovery Rate: {settings.analytics.default_recovery_rate:.0%}")
    print(f"  Discount Rate: {settings.analytics.default_discount_rate:.0%}")
    print(f"  Scenarios:     {settings.analytics.scenario_count}")

    # Show universe
    universe = load_universe()
    print(f"\nUniverse: {len(universe)} names loaded")

    # Show snapshots
    snapshots = list(Path("snapshots").glob("*.json")) if Path("snapshots").exists() else []
    print(f"Snapshots: {len(snapshots)} credit profiles")

    # Show knowledge base
    kb_path = Path("knowledge/processed")
    chunks = list(kb_path.glob("*.json")) if kb_path.exists() else []
    print(f"Knowledge: {len(chunks)} chunks")

    print(f"{'='*60}\n")


def show_status():
    """Show system status overview."""
    print(f"\n{'='*60}")
    print("Credit Catalyst - System Status")
    print(f"{'='*60}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Check directories
    dirs_status = {
        "analytics": Path("analytics").exists(),
        "agents": Path("agents").exists(),
        "monitors": Path("monitors").exists(),
        "knowledge": Path("knowledge").exists(),
        "snapshots": Path("snapshots").exists(),
        "data": Path("data").exists(),
        "indices": Path("indices").exists(),
        "app": Path("app").exists(),
        "alerts": Path("alerts").exists(),
    }

    print("\nComponents:")
    for name, exists in dirs_status.items():
        status = "OK" if exists else "MISSING"
        print(f"  {name:20s} [{status}]")

    show_config()


def main():
    parser = argparse.ArgumentParser(
        description="Credit Catalyst - Strategic Credit Analysis System"
    )
    parser.add_argument("--assess", type=str, metavar="NAME", help="Assess a single credit name")
    parser.add_argument("--universe", action="store_true", help="Assess full credit universe")
    parser.add_argument("--brief", action="store_true", help="Generate morning brief")
    parser.add_argument("--rv", action="store_true", help="Run relative value screen")
    parser.add_argument("--scenarios", action="store_true", help="Run scenario analysis")
    parser.add_argument("--config", action="store_true", help="Show configuration")

    args = parser.parse_args()

    if args.config:
        show_config()
        return

    if args.assess:
        asyncio.run(assess_single(args.assess))
        return

    if args.universe:
        asyncio.run(assess_universe())
        return

    if args.brief:
        asyncio.run(generate_brief())
        return

    # Default: show status
    show_status()


if __name__ == "__main__":
    main()

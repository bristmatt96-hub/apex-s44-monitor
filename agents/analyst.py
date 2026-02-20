"""
Credit Analyst Agent

Takes a company name and iTraxx index, queries the knowledge base for context,
loads real market data (CDS spreads), calls Claude API for credit assessment,
and returns a CreditAssessment object.

Usage:
    python -m agents.analyst "INEOS Finance PLC" --index Xover
"""

import argparse
import json
import os
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv

from core.models import CreditAssessment, Direction, ItraxxIndex
from data.market_data_loader import load_market_data, get_spread_context
from knowledge.retriever import KnowledgeRetriever

load_dotenv(override=True)

SYSTEM_PROMPT = """You are a senior European credit analyst with 25 years experience in CDS markets.
You specialise in iTraxx Main (125 investment-grade names) and iTraxx Crossover (75 high-yield names).

Today's date is {today}. All catalysts must be forward-looking from this date.
Do not reference events before February 2026 unless they are historical context.

You have been provided with real market data including the current 5Y CDS spread.
Use this as the current_spread in your output — do NOT estimate it.
Your fair_spread estimate should differ from the current spread based on your fundamental analysis.
If no market data is provided, estimate the spread based on rating/sector and mark your thesis accordingly.

Vary your fair value estimates based on rating, sector, and company-specific factors.
Use your knowledge of typical CDS spread ranges:
AAA/AA 20-50bps, A 50-100bps, BBB 100-200bps, BB 200-400bps, B 400-700bps, CCC 700-1500bps.

CONVICTION SCORING - THIS IS CRITICAL:
- 1/5: No edge, insufficient information, no clear catalyst
- 2/5: Slight lean but low confidence, generic thesis
- 3/5: Moderate view with some supporting evidence
- 4/5: Strong conviction with clear catalyst and multiple supporting factors
- 5/5: Exceptional — only for the most obvious mispricings with imminent catalysts
MANDATORY DISTRIBUTION: Out of 75 names, you MUST score approximately:
- 5/5: 0-2 names maximum
- 4/5: 5-10 names maximum
- 3/5: 20-30 names (this is the default for a name with a reasonable view)
- 2/5: 20-30 names (slight lean, limited edge)
- 1/5: 5-15 names (no meaningful view)
If you are giving 4/5 to more than 15% of names, you are not being discriminating enough.
A conviction of 4 means you would put significant capital behind this trade.

Be specific about catalysts — they must be time-bound (e.g. "Q2 2026 earnings on 15 May" not "earnings").

Respond with ONLY valid JSON matching this exact schema:
{{
    "entity_name": "string",
    "itraxx_index": "Main" or "Xover",
    "current_spread": float (5Y CDS spread in bps — use the MARKET DATA value provided),
    "fair_spread": float (your model fair value in bps),
    "direction": "LONG_RISK" or "SHORT_RISK" or "FLAT",
    "conviction": int 1-5,
    "signal_sources": ["list of sources informing this view"],
    "thesis": "2-3 sentence thesis",
    "catalyst": "specific time-bound catalyst",
    "key_risks": ["risk 1", "risk 2", "risk 3"],
    "fundamental_metrics": {{"leverage": float, "coverage": float, "fcf_yield": float}}
}}

No markdown, no explanation, no code fences. Just the JSON object."""


# Cache market data so we don't reload per call during batch runs
_market_data_cache: dict[str, dict] = {}


def _get_market_data(index: str) -> dict:
    """Load and cache market data for the given index."""
    key = index.lower()
    if key not in _market_data_cache:
        _market_data_cache[key] = load_market_data(index=key)
    return _market_data_cache[key]


CREDIT_SOURCES = {
    "Covenants.pdf", "distressed exchanges.pdf", "Ranking of Debt.pdf",
    "Maturities and Calls.pdf", "CLO\u2019s.pdf", "Coupons.pdf",
    "Credit Snapshot.pdf", "Valuation Process Moyer.pdf",
    "amendments and consents.pdf", "New Issues.pdf", "Financial Issues.pdf",
    "business trend analysis.pdf", "Decision Process.pdf", "equity info.pdf",
    "news events.pdf", "Ownership and Management.pdf",
    "portfolio management.pdf", "relative value analysis.pdf",
    "Data science and credit analysis.pdf",
}

MAX_CHUNKS = 12
MIN_CREDIT_CHUNKS = 4


def get_knowledge_context(entity_name: str, index: str) -> str:
    """Query the knowledge base for relevant credit analysis context.

    Biases retrieval towards credit-specific chunks: always includes a
    dedicated credit query and guarantees at least MIN_CREDIT_CHUNKS
    from credit category sources out of MAX_CHUNKS total.
    """
    retriever = KnowledgeRetriever(knowledge_path="knowledge")

    queries = [
        # Entity-specific
        f"{entity_name} credit analysis CDS spread",
        # Index-level context
        f"{index} index credit default swap relative value",
        # General credit fundamentals
        "credit analysis leverage coverage ratio fundamental assessment",
        # Dedicated credit-bias query (always included)
        "credit covenants leverage distressed debt restructuring CDS spread analysis",
    ]

    all_results = []
    seen_ids = set()
    for q in queries:
        for r in retriever.query(q, top_k=4, min_score=0.05):
            if r.chunk_id not in seen_ids:
                seen_ids.add(r.chunk_id)
                all_results.append(r)

    if not all_results:
        return ""

    # Split into credit and non-credit results
    credit_results = [r for r in all_results if r.source in CREDIT_SOURCES]
    other_results = [r for r in all_results if r.source not in CREDIT_SOURCES]

    # Sort each group by relevance descending
    credit_results.sort(key=lambda r: r.relevance_score, reverse=True)
    other_results.sort(key=lambda r: r.relevance_score, reverse=True)

    # Guarantee at least MIN_CREDIT_CHUNKS credit results, fill rest by relevance
    final = credit_results[:MIN_CREDIT_CHUNKS]
    remaining_slots = MAX_CHUNKS - len(final)

    # Merge leftover credit + all other, sorted by score, to fill remaining
    leftover_credit = credit_results[MIN_CREDIT_CHUNKS:]
    pool = leftover_credit + other_results
    pool.sort(key=lambda r: r.relevance_score, reverse=True)
    final.extend(pool[:remaining_slots])

    return retriever.format_context_for_agent(final)


def assess_credit(entity_name: str, index: str) -> CreditAssessment:
    """Run the analyst agent for a single name.

    Args:
        entity_name: Company name (e.g. "INEOS Finance PLC")
        index: iTraxx index — "Main" or "Xover"

    Returns:
        CreditAssessment object
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment or .env file")

    client = anthropic.Anthropic(api_key=api_key)

    # Build context from knowledge base
    knowledge_context = get_knowledge_context(entity_name, index)

    # Load real market data
    market_data = _get_market_data(index)
    spread_context = get_spread_context(entity_name, market_data)

    # Load accumulated entity profile
    profile_summary = ""
    try:
        from data.entity_profile_manager import get_profile_summary
        profile_summary = get_profile_summary(entity_name)
    except Exception:
        pass

    # Inject today's date into system prompt
    today_str = datetime.now().strftime("%d %B %Y")
    system_prompt = SYSTEM_PROMPT.format(today=today_str)

    user_message_parts = [
        f"Produce a credit assessment for: {entity_name}",
        f"Index: iTraxx {index}",
    ]
    if spread_context:
        user_message_parts.append(f"\n{spread_context}")
    if profile_summary:
        user_message_parts.append(f"\n{profile_summary}")
    if knowledge_context:
        user_message_parts.append(f"\n{knowledge_context}")

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": "\n".join(user_message_parts)}],
    )

    # Extract text from response
    raw = message.content[0].text.strip()

    # Strip code fences if Claude added them despite instructions
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    data = json.loads(raw)
    data["updated_at"] = datetime.now().isoformat()

    # Store assessment in entity profile
    try:
        from data.entity_profile_manager import update_profile
        update_profile(entity_name, "analyst_assessments", {
            "direction": data.get("direction"),
            "conviction": data.get("conviction"),
            "current_spread": data.get("current_spread"),
            "fair_spread": data.get("fair_spread"),
            "thesis": data.get("thesis"),
            "catalyst": data.get("catalyst"),
            "updated_at": data.get("updated_at"),
        })
    except Exception:
        pass

    return CreditAssessment(**data)


def main():
    parser = argparse.ArgumentParser(description="Credit Analyst Agent")
    parser.add_argument("entity", type=str, help="Company name (e.g. 'INEOS Finance PLC')")
    parser.add_argument(
        "--index",
        type=str,
        choices=["Main", "Xover"],
        default="Xover",
        help="iTraxx index (default: Xover)",
    )
    args = parser.parse_args()

    print(f"Analysing {args.entity} (iTraxx {args.index})...\n")

    # Show market data if available
    market_data = _get_market_data(args.index)
    spread_ctx = get_spread_context(args.entity, market_data)
    if spread_ctx:
        print(f"Market: {spread_ctx}\n")

    try:
        assessment = assess_credit(args.entity, args.index)
    except json.JSONDecodeError as e:
        print(f"Error: Claude returned invalid JSON — {e}", file=sys.stderr)
        sys.exit(1)
    except anthropic.APIError as e:
        print(f"Error: Anthropic API — {e}", file=sys.stderr)
        sys.exit(1)

    # Pretty print
    print(f"Entity:     {assessment.entity_name}")
    print(f"Index:      iTraxx {assessment.itraxx_index.value}")
    print(f"Direction:  {assessment.direction.value}")
    print(f"Conviction: {assessment.conviction}/5")
    print(f"Spread:     {assessment.current_spread:.0f} bps (fair: {assessment.fair_spread:.0f} bps)")
    print(f"Thesis:     {assessment.thesis}")
    print(f"Catalyst:   {assessment.catalyst}")
    print(f"Risks:      {', '.join(assessment.key_risks)}")
    print(f"Signals:    {', '.join(assessment.signal_sources)}")
    print(f"Metrics:    {assessment.fundamental_metrics}")
    print(f"\nFull JSON:\n{assessment.model_dump_json(indent=2)}")


if __name__ == "__main__":
    main()

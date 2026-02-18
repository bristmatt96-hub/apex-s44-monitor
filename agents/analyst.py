"""
Credit Analyst Agent

Takes a company name and iTraxx index, queries the knowledge base for context,
calls Claude API for credit assessment, and returns a CreditAssessment object.

Usage:
    python -m agents.analyst "Ardagh Group" --index Xover
"""

import argparse
import json
import os
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv

from core.models import CreditAssessment, Direction, ItraxxIndex
from knowledge.retriever import KnowledgeRetriever

load_dotenv(override=True)

SYSTEM_PROMPT = """You are a senior European credit analyst with 25 years experience in CDS markets.
You specialise in iTraxx Main (125 investment-grade names) and iTraxx Crossover (75 high-yield names).

When given a company name and index, produce a credit assessment in JSON format.
Use your expertise to estimate reasonable values where exact market data is not available.
Be specific about catalysts — they must be time-bound (e.g. "Q3 earnings on 15 Nov" not "earnings").

Respond with ONLY valid JSON matching this exact schema:
{
    "entity_name": "string",
    "itraxx_index": "Main" or "Xover",
    "current_spread": float (5Y CDS spread in bps, your best estimate),
    "fair_spread": float (your model fair value in bps),
    "direction": "LONG_RISK" or "SHORT_RISK" or "FLAT",
    "conviction": int 1-5,
    "signal_sources": ["list of sources informing this view"],
    "thesis": "2-3 sentence thesis",
    "catalyst": "specific time-bound catalyst",
    "key_risks": ["risk 1", "risk 2", "risk 3"],
    "fundamental_metrics": {"leverage": float, "coverage": float, "fcf_yield": float}
}

No markdown, no explanation, no code fences. Just the JSON object."""


def get_knowledge_context(entity_name: str, index: str) -> str:
    """Query the knowledge base for relevant credit analysis context."""
    retriever = KnowledgeRetriever(knowledge_path="knowledge")

    queries = [
        f"{entity_name} credit analysis CDS spread",
        f"{index} index credit default swap relative value",
        "credit analysis leverage coverage ratio fundamental assessment",
    ]

    all_results = []
    seen_ids = set()
    for q in queries:
        for r in retriever.query(q, top_k=3, min_score=0.05):
            if r.chunk_id not in seen_ids:
                seen_ids.add(r.chunk_id)
                all_results.append(r)

    if not all_results:
        return ""

    return retriever.format_context_for_agent(all_results[:8])


def assess_credit(entity_name: str, index: str) -> CreditAssessment:
    """Run the analyst agent for a single name.

    Args:
        entity_name: Company name (e.g. "Ardagh Group")
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

    user_message_parts = [
        f"Produce a credit assessment for: {entity_name}",
        f"Index: iTraxx {index}",
    ]
    if knowledge_context:
        user_message_parts.append(f"\n{knowledge_context}")

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
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

    return CreditAssessment(**data)


def main():
    parser = argparse.ArgumentParser(description="Credit Analyst Agent")
    parser.add_argument("entity", type=str, help="Company name (e.g. 'Ardagh Group')")
    parser.add_argument(
        "--index",
        type=str,
        choices=["Main", "Xover"],
        default="Main",
        help="iTraxx index (default: Main)",
    )
    args = parser.parse_args()

    print(f"Analysing {args.entity} (iTraxx {args.index})...\n")

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

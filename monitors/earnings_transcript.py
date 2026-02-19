"""
Earnings Transcript Analyser

Processes earnings call transcripts through Claude with a credit-specific lens.
Focuses on covenant language shifts, leverage guidance, refinancing commentary,
liquidity runway, capex signals, and management tone -- the signals that move
CDS spreads.

Stores signals to data/earnings_signals/ for quarter-over-quarter comparison.
When a prior quarter signal exists, Claude compares language deterioration.

Usage:
    python -m monitors.earnings_transcript --company "INEOS Finance PLC" --transcript-file path/to/transcript.txt
    python -m monitors.earnings_transcript --company "SBB" --transcript-file transcript.txt --quarter "Q4 2025"
    python -m monitors.earnings_transcript --company "Worldline SA/France" --transcript-file wln.txt --json
    python -m monitors.earnings_transcript --company "TUI AG" --transcript-file tui.txt --no-save
"""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from data.market_data_loader import get_spread_context, load_market_data

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SIGNALS_DIR = "data/earnings_signals"
MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 2048
MAX_TRANSCRIPT_CHARS = 80_000  # ~20k tokens -- safe for Claude context

# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class EarningsSignal:
    """Structured output from earnings transcript credit analysis."""

    entity_name: str
    quarter: str                           # "Q4 2025", "Q1 2026"
    signal: str                            # "positive" | "negative" | "neutral"
    severity: int                          # 1-5 (1=minor colour, 5=critical red flag)
    covenant_language: dict = field(default_factory=dict)
    leverage_guidance: dict = field(default_factory=dict)
    refinancing: dict = field(default_factory=dict)
    liquidity: dict = field(default_factory=dict)
    capex_signals: dict = field(default_factory=dict)
    tone_shift: str = "stable"             # "improving" | "stable" | "deteriorating"
    key_quotes: list = field(default_factory=list)
    summary: str = ""
    analysed_at: str = ""
    prior_quarter_file: str = ""


# ---------------------------------------------------------------------------
# Claude System Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a senior European high-yield credit analyst specialising in CDS markets.
You are analysing an earnings call transcript for credit-relevant signals that affect CDS spreads.

Your job is NOT equity analysis. Ignore revenue beats/misses, share price targets, and EPS guidance.
Focus exclusively on the six dimensions below that drive CDS spread movements.

## The Six Credit Dimensions

1. COVENANT LANGUAGE
   Track the tone management uses when discussing financial covenants.
   The deterioration spectrum is:
     "well within" > "comfortable headroom" > "adequate" > "monitoring closely" > "in discussions with lenders" > "waiver sought"
   Any leftward shift is positive; any rightward shift is a red flag.
   Note specific covenant ratios mentioned (net leverage, interest coverage, fixed charge).

2. LEVERAGE GUIDANCE
   Extract: current net debt/EBITDA, target ratio, expected timeline to hit target.
   Flag: upward revisions to leverage, pushed-out deleveraging timelines, EBITDA definition changes.
   Compare to prior quarter if provided.

3. REFINANCING COMMENTARY
   Identify: maturity wall references, bond/loan refinancing plans, bank amendment talks, new issuance.
   Red flags: "exploring options", "in discussions", pushed-back timelines, mention of advisors.
   Green flags: "completed refinancing", "extended maturity", "oversubscribed", proactive liability management.

4. LIQUIDITY RUNWAY
   Extract: cash on hand, undrawn revolver capacity, months of runway.
   Flag: revolver drawdowns, tightening availability, reliance on asset sales for liquidity.
   Note any minimum liquidity covenants.

5. CAPEX / ASSET DISPOSAL SIGNALS
   Identify: capex cuts or deferrals, asset sale programs, non-core divestitures.
   Defensive capex cuts in a leveraged name = credit negative (signals stress).
   Strategic disposals at good multiples = credit positive (deleveraging).

6. MANAGEMENT TONE
   Assess overall confidence level. Watch for:
   - Hedging language: "subject to", "if conditions permit", "we hope to"
   - Increased use of qualifiers vs prior quarter
   - Avoiding direct answers on leverage/liquidity questions
   - Defensive posture vs Q&A challenges

## Output Format

Return ONLY valid JSON (no markdown, no code fences, no commentary):

{
    "signal": "positive" | "negative" | "neutral",
    "severity": 1-5,
    "covenant_language": {
        "current_tone": "string describing tone this quarter",
        "prior_tone": "string if prior quarter available, else null",
        "direction": "improving" | "stable" | "deteriorating" | "unknown",
        "specific_ratios_mentioned": ["list of covenant metrics mentioned"],
        "key_observation": "one sentence"
    },
    "leverage_guidance": {
        "current_leverage": "net debt/EBITDA as stated or null",
        "target_leverage": "target ratio or null",
        "timeline": "when they expect to hit target or null",
        "trajectory": "deleveraging" | "stable" | "releveraging" | "unclear",
        "key_observation": "one sentence"
    },
    "refinancing": {
        "upcoming_maturities_mentioned": ["list of maturities discussed"],
        "plans": "summary of refi plans or null",
        "status": "completed" | "in_progress" | "planned" | "no_mention",
        "red_flags": ["list of concerning statements"],
        "green_flags": ["list of positive statements"]
    },
    "liquidity": {
        "cash_position": "stated cash or null",
        "revolver_availability": "undrawn revolver or null",
        "runway_months": estimated months of runway as integer or null,
        "concerns": ["list of liquidity concerns"],
        "key_observation": "one sentence"
    },
    "capex_signals": {
        "direction": "increasing" | "stable" | "cutting" | "not_discussed",
        "asset_disposals": "summary or null",
        "is_defensive": true/false,
        "key_observation": "one sentence"
    },
    "tone_shift": "improving" | "stable" | "deteriorating",
    "key_quotes": [
        "exact quote 1 from transcript (max 2 sentences)",
        "exact quote 2",
        "exact quote 3"
    ],
    "summary": "2-3 sentence credit-focused summary of the earnings call"
}

## Severity Scale
- 1: Minor colour, no spread impact expected
- 2: Slight shift in one dimension, 5-10bps potential move
- 3: Material shift in 2+ dimensions, 10-25bps potential move
- 4: Significant deterioration, 25-50bps+ widening risk
- 5: Critical red flags (covenant breach risk, liquidity crisis, refi wall), 50bps+ widening

## Rules
- Extract EXACT quotes from the transcript. Do not paraphrase.
- If a dimension is not discussed, use null values and note "not_discussed".
- Be sceptical of management spin. Read between the lines.
- A company saying "we are comfortable with our liquidity" while drawing down its revolver is a red flag.
- Always assess the GAP between what management says and what the numbers show.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def infer_quarter() -> str:
    """Infer the most recent reporting quarter from current date."""
    now = datetime.now()
    month = now.month
    year = now.year
    # Earnings reported ~6 weeks after quarter end
    if month <= 3:
        return f"Q4 {year - 1}"
    if month <= 6:
        return f"Q1 {year}"
    if month <= 9:
        return f"Q2 {year}"
    return f"Q3 {year}"


def entity_slug(name: str) -> str:
    """Convert entity name to filesystem-safe slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def signal_path(entity_name: str, quarter: str) -> str:
    """Build path for a signal JSON file."""
    slug = entity_slug(entity_name)
    q_slug = quarter.lower().replace(" ", "_")
    return os.path.join(SIGNALS_DIR, f"{slug}_{q_slug}.json")


def find_prior_quarter_signal(entity_name: str, quarter: str) -> dict | None:
    """Look for the most recent prior quarter signal for comparison."""
    # Parse current quarter
    match = re.match(r"Q(\d)\s+(\d{4})", quarter)
    if not match:
        return None

    q_num = int(match.group(1))
    year = int(match.group(2))

    # Walk backwards through quarters
    for _ in range(4):
        q_num -= 1
        if q_num < 1:
            q_num = 4
            year -= 1
        prior_q = f"Q{q_num} {year}"
        path = signal_path(entity_name, prior_q)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)

    return None


def save_signal(sig: EarningsSignal) -> str:
    """Persist signal to data/earnings_signals/."""
    Path(SIGNALS_DIR).mkdir(parents=True, exist_ok=True)
    path = signal_path(sig.entity_name, sig.quarter)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(sig), f, indent=2, default=str)
    return path


# ---------------------------------------------------------------------------
# Core Analysis
# ---------------------------------------------------------------------------

def analyse_transcript(
    entity_name: str,
    transcript: str,
    quarter: str,
    spread_ctx: str | None = None,
    prior_signal: dict | None = None,
) -> EarningsSignal:
    """Run earnings transcript through Claude for credit analysis.

    Args:
        entity_name: Xover constituent name
        transcript: Full text of earnings call transcript
        quarter: e.g. "Q4 2025"
        spread_ctx: CDS spread context string from market_data_loader
        prior_signal: Prior quarter signal dict for comparison

    Returns:
        EarningsSignal with all six dimensions populated
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment or .env file")

    client = anthropic.Anthropic(api_key=api_key)

    # Truncate long transcripts
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[TRANSCRIPT TRUNCATED]"

    # Build user message
    parts = [
        f"Analyse the following earnings call transcript for: {entity_name}",
        f"Reporting period: {quarter}",
    ]

    if spread_ctx:
        parts.append(f"\n{spread_ctx}")

    if prior_signal:
        prior_summary = json.dumps({
            "quarter": prior_signal.get("quarter"),
            "signal": prior_signal.get("signal"),
            "severity": prior_signal.get("severity"),
            "covenant_language": prior_signal.get("covenant_language"),
            "leverage_guidance": prior_signal.get("leverage_guidance"),
            "refinancing": prior_signal.get("refinancing"),
            "liquidity": prior_signal.get("liquidity"),
            "tone_shift": prior_signal.get("tone_shift"),
            "summary": prior_signal.get("summary"),
        }, indent=2)
        parts.append(
            f"\nPRIOR QUARTER SIGNAL ({prior_signal.get('quarter', 'unknown')}):\n"
            f"{prior_summary}\n"
            "Compare this quarter's language and tone to the prior quarter above. "
            "Flag any deterioration or improvement."
        )

    parts.append(f"\n--- TRANSCRIPT BEGIN ---\n{transcript}\n--- TRANSCRIPT END ---")

    user_message = "\n".join(parts)

    # Call Claude
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    # Parse response
    raw = message.content[0].text.strip()

    # Strip code fences if Claude added them
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error parsing Claude response: {e}", file=sys.stderr)
        print(f"Raw response:\n{raw[:500]}", file=sys.stderr)
        raise

    # Build EarningsSignal
    prior_path = ""
    if prior_signal:
        prior_path = signal_path(
            entity_name, prior_signal.get("quarter", "")
        )

    return EarningsSignal(
        entity_name=entity_name,
        quarter=quarter,
        signal=data.get("signal", "neutral"),
        severity=max(1, min(5, data.get("severity", 1))),
        covenant_language=data.get("covenant_language", {}),
        leverage_guidance=data.get("leverage_guidance", {}),
        refinancing=data.get("refinancing", {}),
        liquidity=data.get("liquidity", {}),
        capex_signals=data.get("capex_signals", {}),
        tone_shift=data.get("tone_shift", "stable"),
        key_quotes=data.get("key_quotes", []),
        summary=data.get("summary", ""),
        analysed_at=datetime.now().isoformat(),
        prior_quarter_file=prior_path,
    )


# ---------------------------------------------------------------------------
# Report Formatting
# ---------------------------------------------------------------------------

SIGNAL_COLOURS = {
    "positive": "+",
    "negative": "!",
    "neutral": "~",
}

SEVERITY_BAR = {
    1: "#....",
    2: "##...",
    3: "###..",
    4: "####.",
    5: "#####",
}


def print_report(sig: EarningsSignal):
    """Print formatted terminal report."""
    marker = SIGNAL_COLOURS.get(sig.signal, "?")
    bar = SEVERITY_BAR.get(sig.severity, "?????")

    print("=" * 100)
    print("  CREDIT CATALYST -- EARNINGS TRANSCRIPT ANALYSIS")
    print(f"  {datetime.now().strftime('%d %B %Y %H:%M')}")
    print("=" * 100)

    print(f"\n  Entity:    {sig.entity_name}")
    print(f"  Quarter:   {sig.quarter}")
    print(f"  Signal:    [{marker}] {sig.signal.upper()}")
    print(f"  Severity:  [{bar}] {sig.severity}/5")
    print(f"  Tone:      {sig.tone_shift}")

    if sig.prior_quarter_file:
        print(f"  Prior QoQ: compared to {sig.prior_quarter_file}")

    print(f"\n  Summary: {sig.summary}")

    # Covenant language
    cov = sig.covenant_language
    if cov:
        print("\n" + "-" * 100)
        print("  1. COVENANT LANGUAGE")
        print("-" * 100)
        print(f"     Current tone:  {cov.get('current_tone', 'N/A')}")
        if cov.get("prior_tone"):
            print(f"     Prior tone:    {cov.get('prior_tone')}")
        print(f"     Direction:     {cov.get('direction', 'unknown')}")
        ratios = cov.get("specific_ratios_mentioned", [])
        if ratios:
            print(f"     Ratios cited:  {', '.join(ratios)}")
        if cov.get("key_observation"):
            print(f"     >> {cov['key_observation']}")

    # Leverage guidance
    lev = sig.leverage_guidance
    if lev:
        print("\n" + "-" * 100)
        print("  2. LEVERAGE GUIDANCE")
        print("-" * 100)
        print(f"     Current:     {lev.get('current_leverage', 'N/A')}")
        print(f"     Target:      {lev.get('target_leverage', 'N/A')}")
        print(f"     Timeline:    {lev.get('timeline', 'N/A')}")
        print(f"     Trajectory:  {lev.get('trajectory', 'unclear')}")
        if lev.get("key_observation"):
            print(f"     >> {lev['key_observation']}")

    # Refinancing
    refi = sig.refinancing
    if refi:
        print("\n" + "-" * 100)
        print("  3. REFINANCING")
        print("-" * 100)
        mats = refi.get("upcoming_maturities_mentioned", [])
        if mats:
            print(f"     Maturities:  {', '.join(str(m) for m in mats)}")
        print(f"     Plans:       {refi.get('plans', 'N/A')}")
        print(f"     Status:      {refi.get('status', 'no_mention')}")
        for flag in refi.get("red_flags", []):
            print(f"     [!] RED:     {flag}")
        for flag in refi.get("green_flags", []):
            print(f"     [+] GREEN:   {flag}")

    # Liquidity
    liq = sig.liquidity
    if liq:
        print("\n" + "-" * 100)
        print("  4. LIQUIDITY")
        print("-" * 100)
        print(f"     Cash:        {liq.get('cash_position', 'N/A')}")
        print(f"     Revolver:    {liq.get('revolver_availability', 'N/A')}")
        runway = liq.get("runway_months")
        if runway is not None:
            label = f"{runway} months"
            if runway < 12:
                label += "  !! SHORT RUNWAY"
            print(f"     Runway:      {label}")
        for concern in liq.get("concerns", []):
            print(f"     [!] {concern}")
        if liq.get("key_observation"):
            print(f"     >> {liq['key_observation']}")

    # Capex signals
    capex = sig.capex_signals
    if capex:
        print("\n" + "-" * 100)
        print("  5. CAPEX / ASSET DISPOSALS")
        print("-" * 100)
        print(f"     Direction:    {capex.get('direction', 'not_discussed')}")
        if capex.get("asset_disposals"):
            print(f"     Disposals:    {capex['asset_disposals']}")
        if capex.get("is_defensive"):
            print("     [!] DEFENSIVE CUTS DETECTED")
        if capex.get("key_observation"):
            print(f"     >> {capex['key_observation']}")

    # Key quotes
    if sig.key_quotes:
        print("\n" + "-" * 100)
        print("  6. KEY QUOTES")
        print("-" * 100)
        for i, quote in enumerate(sig.key_quotes, 1):
            # Wrap long quotes
            wrapped = quote[:200] + "..." if len(quote) > 200 else quote
            print(f'     [{i}] "{wrapped}"')

    print("\n" + "=" * 100)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Earnings Transcript Credit Analyser"
    )
    parser.add_argument(
        "--company", type=str, required=True,
        help="Xover entity name (e.g. 'INEOS Finance PLC')",
    )
    parser.add_argument(
        "--transcript-file", type=str, required=True,
        help="Path to text transcript file",
    )
    parser.add_argument(
        "--quarter", type=str, default=None,
        help="Reporting quarter (e.g. 'Q4 2025'). Auto-inferred if omitted.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of formatted report",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Don't persist signal to data/earnings_signals/",
    )
    args = parser.parse_args()

    # Validate transcript file
    if not os.path.exists(args.transcript_file):
        print(f"Error: Transcript file not found: {args.transcript_file}",
              file=sys.stderr)
        sys.exit(1)

    # Read transcript
    with open(args.transcript_file, encoding="utf-8") as f:
        transcript = f.read().strip()

    if not transcript:
        print("Error: Transcript file is empty.", file=sys.stderr)
        sys.exit(1)

    # Infer quarter if not provided
    quarter = args.quarter or infer_quarter()

    # Load CDS spread context
    try:
        market_data = load_market_data(index="xover")
        spread_ctx = get_spread_context(args.company, market_data)
    except Exception:
        spread_ctx = None

    # Look for prior quarter signal
    prior_signal = find_prior_quarter_signal(args.company, quarter)
    if prior_signal:
        print(f"  Found prior quarter signal: {prior_signal.get('quarter')}",
              flush=True)

    # Run analysis
    print(f"  Analysing {args.company} ({quarter})...", flush=True)
    sig = analyse_transcript(
        entity_name=args.company,
        transcript=transcript,
        quarter=quarter,
        spread_ctx=spread_ctx,
        prior_signal=prior_signal,
    )

    # Save signal
    if not args.no_save:
        path = save_signal(sig)
        print(f"  Signal saved: {path}", flush=True)

    # Output
    if args.json:
        print(json.dumps(asdict(sig), indent=2, default=str))
    else:
        print_report(sig)


if __name__ == "__main__":
    main()

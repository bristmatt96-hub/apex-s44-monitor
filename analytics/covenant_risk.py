"""
Covenant Risk Analyser

Dual approach:
1. Check data/covenant_profiles.json for manually-entered covenant data
2. If no manual profile exists, call Claude API with knowledge base context
   to assess covenant risk, with explicit confidence/data quality ratings

Cross-references with maturity wall data and current CDS spreads.

Usage:
    python -m analytics.covenant_risk                        # All 75 names
    python -m analytics.covenant_risk --limit 10 --delay 2   # First 10
    python -m analytics.covenant_risk --name "SBB"           # Single name
    python -m analytics.covenant_risk --json                  # JSON output
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from data.market_data_loader import get_spread_context, load_market_data
from knowledge.retriever import KnowledgeRetriever

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROFILES_PATH = "data/covenant_profiles.json"
MATURITY_WALL_PATH = "data/maturity_wall.json"
INDEX_PATH = "indices/xover_s44.json"
MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1536

# Credit-specific knowledge sources for retriever bias
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


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------
@dataclass
class CovenantRiskAssessment:
    """Output for a single name's covenant risk analysis."""

    entity_name: str
    data_source: str                       # "manual_profile" | "claude_inferred"
    data_quality: str                      # "verified" | "partial" | "inferred"
    covenant_quality_score: int            # 1-5 (1=strong protections, 5=no protections)
    lme_vulnerability_score: int           # 1-5 (1=low risk, 5=critical LME risk)
    risk_flags: list = field(default_factory=list)
    missing_information: list = field(default_factory=list)
    recommended_actions: list = field(default_factory=list)
    current_spread_bps: float = 0.0
    maturity_wall_risk: str = "unknown"    # "none" | "moderate" | "elevated" | "critical"
    nearest_maturity: str = ""
    nearest_maturity_size_eur_m: float = 0.0
    documentation_vintage: str = ""
    sponsor: str = ""
    summary: str = ""
    confidence_notes: str = ""
    assessed_at: str = ""


# ---------------------------------------------------------------------------
# Claude System Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a senior European leveraged finance lawyer and credit analyst specialising in high yield bond and leveraged loan documentation.

You are assessing COVENANT RISK and LIABILITY MANAGEMENT EXERCISE (LME) VULNERABILITY for a specific credit name in the iTraxx Crossover index.

## Your Task

For the given entity, assess:

1. COVENANT QUALITY (score 1-5):
   1 = Strong creditor protections (maintenance covenants, tight baskets, post-2023 docs with blockers)
   2 = Good protections (standard HY docs with reasonable limits)
   3 = Average (typical covenant-lite with some protections)
   4 = Weak (ZIRP-era covenant-lite, broad baskets, limited protections)
   5 = Minimal/None (IG-style unsecured with no meaningful restrictions, or aggressive sponsor docs)

2. LME VULNERABILITY (score 1-5):
   1 = Low (J.Crew blockers, uptier protection, strong intercreditor)
   2 = Moderate (some protections but gaps exist)
   3 = Elevated (covenant-lite with transferable assets, no uptier protection)
   4 = High (aggressive ZIRP-era docs, sponsor with LME track record)
   5 = Critical (active distress + weak docs + no creditor protections + imminent maturity wall)

3. RISK FLAGS: Specific documentation concerns

4. MISSING INFORMATION: What you do NOT have access to and would need

5. RECOMMENDED ACTIONS: Where to find the missing information

## CRITICAL: Data Quality and Confidence

You MUST include a "data_quality" field:
- "verified": You have specific confirmed information (from the manual profile or known public sources)
- "partial": You have some information but significant gaps
- "inferred": You are mostly guessing from general knowledge of the sector, sponsor, and documentation vintage

You MUST include "confidence_notes" explaining:
- What you know for certain vs what you are inferring
- What assumptions you are making
- Where your assessment could be materially wrong

DO NOT pretend to have information you don't have. If you don't know the covenant terms, say so explicitly.

## Documentation Vintage Risk

Pre-2015: Generally stronger docs (post-GFC tightening)
2015-2018: Gradual loosening, some covenant-lite
2019-2022: Peak ZIRP-era, most aggressive docs, highest LME risk
2023+: Post-Serta/Boardrider reforms, some J.Crew blockers appearing

## Output Format

Return ONLY valid JSON (no markdown, no code fences):

{
    "covenant_quality_score": 1-5,
    "lme_vulnerability_score": 1-5,
    "data_quality": "verified" | "partial" | "inferred",
    "risk_flags": ["specific flag 1", "specific flag 2"],
    "missing_information": ["No access to credit agreement", "Sponsor aggression unknown"],
    "recommended_actions": ["Obtain OM from Debtwire", "Check Companies House for intercreditor filing"],
    "documentation_vintage": "year or range",
    "sponsor": "sponsor name or null",
    "summary": "2-3 sentence assessment",
    "confidence_notes": "Explain what is known vs inferred"
}
"""


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_profiles() -> dict:
    """Load manually-entered covenant profiles."""
    if not os.path.exists(PROFILES_PATH):
        return {}
    with open(PROFILES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    # Remove template entry
    data.pop("_template", None)
    return data


def load_maturity_wall() -> dict:
    """Load maturity wall data, keyed by entity name."""
    if not os.path.exists(MATURITY_WALL_PATH):
        return {}
    with open(MATURITY_WALL_PATH, encoding="utf-8") as f:
        data = json.load(f)
    # Build lookup by name
    result = {}
    for category, names in data.items():
        if isinstance(names, list):
            for entry in names:
                if isinstance(entry, dict) and "name" in entry:
                    result[entry["name"]] = {**entry, "category": category}
    return result


def load_constituents() -> list[str]:
    """Load Xover S44 constituent names."""
    with open(INDEX_PATH, encoding="utf-8") as f:
        data = json.load(f)
    names = []
    for sector_names in data["sectors"].values():
        names.extend(sector_names)
    return sorted(names)


# ---------------------------------------------------------------------------
# Knowledge Base Retrieval (credit-biased)
# ---------------------------------------------------------------------------

def get_covenant_knowledge(entity_name: str) -> str:
    """Retrieve covenant-specific knowledge from the knowledge base."""
    retriever = KnowledgeRetriever(knowledge_path="knowledge")

    queries = [
        f"{entity_name} covenants credit agreement documentation",
        "covenant analysis headroom leverage test incurrence maintenance",
        "distressed debt LME liability management uptier priming J.Crew",
        "credit documentation restricted payments unrestricted subsidiary baskets",
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

    # Prioritise credit sources
    credit_results = [r for r in all_results if r.source in CREDIT_SOURCES]
    other_results = [r for r in all_results if r.source not in CREDIT_SOURCES]
    credit_results.sort(key=lambda r: r.relevance_score, reverse=True)
    other_results.sort(key=lambda r: r.relevance_score, reverse=True)

    final = credit_results[:5]
    remaining = 8 - len(final)
    pool = credit_results[5:] + other_results
    pool.sort(key=lambda r: r.relevance_score, reverse=True)
    final.extend(pool[:remaining])

    return retriever.format_context_for_agent(final)


# ---------------------------------------------------------------------------
# Assessment from Manual Profile
# ---------------------------------------------------------------------------

def assess_from_profile(
    entity_name: str,
    profile: dict,
    spread_bps: float,
    maturity_info: dict | None,
) -> CovenantRiskAssessment:
    """Build assessment from a manually-entered covenant profile."""
    cov = profile.get("covenants", {})
    lme = profile.get("lme_provisions", {})
    mat = profile.get("maturity_profile", {})
    cap = profile.get("capital_structure", {})

    # Covenant quality score heuristics
    cov_score = 3  # default average
    if cov.get("maintenance_covenants"):
        cov_score = max(1, cov_score - 1)
    if cov.get("springing_covenant"):
        cov_score = max(1, cov_score - 1)
    baskets = cov.get("key_baskets", {})
    for _, val in baskets.items():
        if isinstance(val, str) and "HIGH RISK" in val.upper():
            cov_score = min(5, cov_score + 1)
    vintage = profile.get("documentation_vintage", "")
    if any(y in vintage for y in ["2019", "2020", "2021", "2022"]):
        cov_score = min(5, cov_score + 1)

    # LME vulnerability heuristics
    lme_score = 3  # default
    if lme.get("j_crew_blocker") is False:
        lme_score = min(5, lme_score + 1)
    if lme.get("uptier_protection") is False:
        lme_score = min(5, lme_score + 1)
    asset_risk = lme.get("asset_stripping_risk", "") or ""
    if "CRITICAL" in asset_risk.upper():
        lme_score = 5
    elif "HIGH" in asset_risk.upper():
        lme_score = min(5, lme_score + 1)
    distress_pct = profile.get("distress_probability_pct", 0) or 0
    if distress_pct > 80:
        lme_score = min(5, lme_score + 1)
    elif distress_pct > 50:
        lme_score = min(5, lme_score + 1)

    # Risk flags
    flags = []
    if distress_pct > 50:
        flags.append(f"Debtwire distress probability: {distress_pct:.0f}%")
    if profile.get("lifecycle_status") == "Distressed":
        flags.append("Lifecycle status: DISTRESSED")
    if cov.get("maintenance_covenants") is False:
        flags.append("No maintenance covenants (covenant-lite)")
    if lme.get("j_crew_blocker") is False:
        flags.append("No J.Crew blocker -- unrestricted subsidiary risk")
    if lme.get("uptier_protection") is False:
        flags.append("No uptier protection -- priming risk")
    if "CRITICAL" in asset_risk.upper() or "HIGH" in asset_risk.upper():
        flags.append(f"Asset stripping risk: {asset_risk}")
    lev = cap.get("net_leverage")
    if lev and lev > 6:
        flags.append(f"Extreme leverage: {lev:.1f}x net debt/EBITDA")

    # Missing information
    missing = []
    if not cov.get("incurrence_covenants", {}).get("leverage_test"):
        missing.append("Incurrence leverage test threshold unknown")
    if lme.get("j_crew_blocker") is None:
        missing.append("J.Crew blocker status unknown")
    if lme.get("uptier_protection") is None:
        missing.append("Uptier protection status unknown")
    if lme.get("intercreditor_type") is None:
        missing.append("Intercreditor agreement type unknown")
    if not cap.get("ebitda_eur_m"):
        missing.append("EBITDA figure not available")

    # Recommended actions
    actions = []
    if missing:
        actions.append("Obtain Offering Memorandum from Debtwire or IntraLinks")
    sponsor = profile.get("sponsor")
    if sponsor:
        actions.append(f"Review {sponsor} LME track record across portfolio")
    if any("intercreditor" in m.lower() for m in missing):
        actions.append("Check Companies House / EDGAR for intercreditor filing")
    if profile.get("lifecycle_status") == "Distressed":
        actions.append("Monitor Debtwire/Reorg for restructuring advisors")

    # Maturity wall risk
    mat_risk = "none"
    near_mat = mat.get("nearest_maturity", "")
    near_size = mat.get("nearest_maturity_size_eur_m", 0) or 0
    total_24m = mat.get("total_maturities_within_24m_eur_m", 0) or 0
    if total_24m > 1000:
        mat_risk = "critical"
    elif total_24m > 500:
        mat_risk = "elevated"
    elif total_24m > 0:
        mat_risk = "moderate"

    # Determine data quality
    has_covenants = cov.get("springing_covenant") or cov.get("maintenance_covenants")
    has_lme = lme.get("j_crew_blocker") is not None or lme.get("uptier_protection") is not None
    if has_covenants and has_lme:
        dq = "verified"
    elif has_covenants or has_lme or len(profile.get("capital_structure", {}).get("instruments", [])) > 2:
        dq = "partial"
    else:
        dq = "inferred"

    return CovenantRiskAssessment(
        entity_name=entity_name,
        data_source="manual_profile",
        data_quality=dq,
        covenant_quality_score=max(1, min(5, cov_score)),
        lme_vulnerability_score=max(1, min(5, lme_score)),
        risk_flags=flags,
        missing_information=missing,
        recommended_actions=actions,
        current_spread_bps=spread_bps,
        maturity_wall_risk=mat_risk,
        nearest_maturity=near_mat,
        nearest_maturity_size_eur_m=near_size,
        documentation_vintage=profile.get("documentation_vintage", ""),
        sponsor=sponsor or "",
        summary=profile.get("notes", ""),
        confidence_notes=f"Based on Debtwire export ({profile.get('last_updated', 'unknown')}). "
                         f"Capital structure data available; covenant detail mostly unavailable.",
        assessed_at=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# Assessment from Claude API
# ---------------------------------------------------------------------------

def assess_from_claude(
    entity_name: str,
    spread_bps: float,
    spread_ctx: str | None,
    maturity_info: dict | None,
    knowledge_ctx: str,
) -> CovenantRiskAssessment:
    """Call Claude to assess covenant risk when no manual profile exists."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)

    parts = [
        f"Assess covenant risk and LME vulnerability for: {entity_name}",
        f"CDS spread: {spread_bps:.0f}bps" if spread_bps else "",
    ]

    if spread_ctx:
        parts.append(f"\n{spread_ctx}")

    if maturity_info:
        mat_str = json.dumps(maturity_info, indent=2, default=str)
        parts.append(f"\nMATURITY WALL DATA:\n{mat_str}")

    parts.append(
        "\nIMPORTANT: No manually-entered covenant profile exists for this name. "
        "You must assess based on your general knowledge. Be explicit about what "
        "you know versus what you are inferring. If you are guessing, say so."
    )

    if knowledge_ctx:
        parts.append(f"\n{knowledge_ctx}")

    user_message = "\n".join(p for p in parts if p)

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  Error parsing Claude response for {entity_name}: {e}", file=sys.stderr)
        # Return a conservative default
        return CovenantRiskAssessment(
            entity_name=entity_name,
            data_source="claude_inferred",
            data_quality="inferred",
            covenant_quality_score=3,
            lme_vulnerability_score=3,
            risk_flags=["PARSE ERROR -- Claude response could not be parsed"],
            missing_information=["All covenant data missing"],
            recommended_actions=["Obtain Offering Memorandum from Debtwire"],
            current_spread_bps=spread_bps,
            summary="Assessment failed -- Claude response parsing error",
            assessed_at=datetime.now().isoformat(),
        )

    # Maturity wall risk from spread + maturity data
    mat_risk = "unknown"
    near_mat = ""
    near_size = 0.0
    if maturity_info:
        mat_risk = maturity_info.get("category", "unknown")
        near_mat = str(maturity_info.get("next_maturity", ""))
        near_size = maturity_info.get("amount_eur_bn", 0) * 1000  # bn -> m

    return CovenantRiskAssessment(
        entity_name=entity_name,
        data_source="claude_inferred",
        data_quality=data.get("data_quality", "inferred"),
        covenant_quality_score=max(1, min(5, data.get("covenant_quality_score", 3))),
        lme_vulnerability_score=max(1, min(5, data.get("lme_vulnerability_score", 3))),
        risk_flags=data.get("risk_flags", []),
        missing_information=data.get("missing_information", []),
        recommended_actions=data.get("recommended_actions", []),
        current_spread_bps=spread_bps,
        maturity_wall_risk=mat_risk,
        nearest_maturity=near_mat,
        nearest_maturity_size_eur_m=near_size,
        documentation_vintage=data.get("documentation_vintage", ""),
        sponsor=data.get("sponsor") or "",
        summary=data.get("summary", ""),
        confidence_notes=data.get("confidence_notes", ""),
        assessed_at=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# Main Assessment Pipeline
# ---------------------------------------------------------------------------

def assess_name(
    entity_name: str,
    profiles: dict,
    market_data: dict,
    maturity_wall: dict,
) -> CovenantRiskAssessment:
    """Assess a single name -- manual profile first, Claude as fallback."""
    # Get current spread
    spread_bps = 0.0
    mkt = market_data.get(entity_name, {})
    if mkt:
        spread_bps = mkt.get("spread", 0) or 0

    spread_ctx = get_spread_context(entity_name, market_data) if market_data else None

    # Maturity wall lookup (fuzzy match on name)
    mat_info = None
    name_lower = entity_name.lower()
    for mat_name, mat_data in maturity_wall.items():
        if mat_name.lower() in name_lower or name_lower in mat_name.lower():
            mat_info = mat_data
            break
    # Also check by first significant word
    if not mat_info:
        words = [w for w in entity_name.split() if len(w) > 3 and w.lower() not in
                 {"finance", "group", "holdings", "international", "europe", "european"}]
        for mat_name, mat_data in maturity_wall.items():
            for w in words:
                if w.lower() in mat_name.lower():
                    mat_info = mat_data
                    break

    # Check manual profiles (by xover_name or entity_name)
    profile = profiles.get(entity_name)
    if not profile:
        # Try matching by xover_name field
        for _, p in profiles.items():
            if p.get("xover_name") == entity_name:
                profile = p
                break

    if profile:
        return assess_from_profile(entity_name, profile, spread_bps, mat_info)

    # No manual profile -- use Claude
    knowledge_ctx = get_covenant_knowledge(entity_name)
    return assess_from_claude(
        entity_name, spread_bps, spread_ctx, mat_info, knowledge_ctx
    )


# ---------------------------------------------------------------------------
# Report Formatting
# ---------------------------------------------------------------------------

QUALITY_LABELS = {1: "Strong", 2: "Good", 3: "Average", 4: "Weak", 5: "Minimal"}
LME_LABELS = {1: "Low", 2: "Moderate", 3: "Elevated", 4: "High", 5: "Critical"}
SCORE_BAR = {1: "#....", 2: "##...", 3: "###..", 4: "####.", 5: "#####"}
DQ_ICONS = {"verified": "[V]", "partial": "[P]", "inferred": "[?]"}


def print_report(assessments: list[CovenantRiskAssessment]):
    """Print formatted terminal report."""
    print("=" * 110)
    print("  STRATEGIES IN CREDIT -- COVENANT RISK ANALYSIS")
    print(f"  {datetime.now().strftime('%d %B %Y %H:%M')}")
    print("=" * 110)

    # Summary table
    print(f"\n  {'Entity':<38} {'CDS':>6} {'Cov':>4} {'LME':>4} {'Data':>5} {'Mat Risk':<10} {'Source':<16}")
    print("  " + "-" * 105)

    # Sort by LME vulnerability desc, then covenant quality desc
    sorted_a = sorted(assessments, key=lambda a: (a.lme_vulnerability_score, a.covenant_quality_score), reverse=True)

    for a in sorted_a:
        dq_icon = DQ_ICONS.get(a.data_quality, "[?]")
        spread_str = f"{a.current_spread_bps:.0f}" if a.current_spread_bps else "N/A"
        mat_str = a.maturity_wall_risk[:8] if a.maturity_wall_risk else ""
        src = "Manual" if a.data_source == "manual_profile" else "Claude"
        print(f"  {a.entity_name[:36]:<38} {spread_str:>6} {a.covenant_quality_score:>4} "
              f"{a.lme_vulnerability_score:>4} {dq_icon:>5} {mat_str:<10} {src:<16}")

    # Detailed cards for high-risk names (LME >= 4)
    high_risk = [a for a in sorted_a if a.lme_vulnerability_score >= 4]
    if high_risk:
        print(f"\n{'=' * 110}")
        print(f"  HIGH-RISK NAMES (LME vulnerability >= 4)")
        print(f"{'=' * 110}")

        for a in high_risk:
            cov_label = QUALITY_LABELS.get(a.covenant_quality_score, "?")
            lme_label = LME_LABELS.get(a.lme_vulnerability_score, "?")
            print(f"\n  {a.entity_name}")
            print(f"  {'.'*60}")
            print(f"    CDS Spread:       {a.current_spread_bps:.0f}bps" if a.current_spread_bps else "    CDS Spread:       N/A")
            print(f"    Covenant Quality: [{SCORE_BAR[a.covenant_quality_score]}] {a.covenant_quality_score}/5 ({cov_label})")
            print(f"    LME Vulnerability:[{SCORE_BAR[a.lme_vulnerability_score]}] {a.lme_vulnerability_score}/5 ({lme_label})")
            print(f"    Data Quality:     {a.data_quality}")
            print(f"    Doc Vintage:      {a.documentation_vintage or 'unknown'}")
            if a.sponsor:
                print(f"    Sponsor:          {a.sponsor}")
            print(f"    Maturity Risk:    {a.maturity_wall_risk}")
            if a.nearest_maturity:
                print(f"    Nearest Maturity: {a.nearest_maturity} (EUR {a.nearest_maturity_size_eur_m:.0f}m)")

            if a.risk_flags:
                print(f"    Risk Flags:")
                for flag in a.risk_flags:
                    print(f"      [!] {flag}")

            if a.missing_information:
                print(f"    Missing Information:")
                for mi in a.missing_information:
                    print(f"      [?] {mi}")

            if a.recommended_actions:
                print(f"    Recommended Actions:")
                for ra in a.recommended_actions:
                    print(f"      >> {ra}")

            if a.confidence_notes:
                notes = a.confidence_notes[:300]
                print(f"    Confidence: {notes}")

            print(f"    Summary: {a.summary[:200]}")

    # Statistics
    print(f"\n{'-' * 110}")
    total = len(assessments)
    manual = sum(1 for a in assessments if a.data_source == "manual_profile")
    verified = sum(1 for a in assessments if a.data_quality == "verified")
    partial = sum(1 for a in assessments if a.data_quality == "partial")
    inferred = sum(1 for a in assessments if a.data_quality == "inferred")
    high_lme = sum(1 for a in assessments if a.lme_vulnerability_score >= 4)

    print(f"  Total: {total} | Manual: {manual} | Claude: {total - manual}")
    print(f"  Data Quality: {verified} verified, {partial} partial, {inferred} inferred")
    print(f"  High LME Risk (>=4): {high_lme} names")
    print(f"  Avg Covenant Score: {sum(a.covenant_quality_score for a in assessments)/total:.1f}/5")
    print(f"  Avg LME Score: {sum(a.lme_vulnerability_score for a in assessments)/total:.1f}/5")
    print(f"{'=' * 110}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Covenant Risk Analyser")
    parser.add_argument(
        "--name", type=str, default=None,
        help="Analyse a single entity name",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit to first N names (for testing)",
    )
    parser.add_argument(
        "--delay", type=float, default=2.0,
        help="Seconds between Claude API calls (default: 2.0)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of formatted report",
    )
    args = parser.parse_args()

    # Load data
    profiles = load_profiles()
    market_data = load_market_data(index="xover")
    maturity_wall = load_maturity_wall()

    if args.name:
        names = [args.name]
    else:
        names = load_constituents()
        if args.limit:
            names = names[:args.limit]

    total = len(names)
    assessments = []
    manual_count = 0

    print(f"  Covenant risk analysis for {total} names")
    print(f"  Manual profiles loaded: {len(profiles)}")
    print()

    for i, name in enumerate(names, 1):
        # Check if manual profile exists
        has_profile = name in profiles or any(
            p.get("xover_name") == name for p in profiles.values()
        )
        source_tag = "PROFILE" if has_profile else "CLAUDE"
        print(f"  [{i}/{total}] {name} ({source_tag})...", end=" ", flush=True)

        try:
            a = assess_name(name, profiles, market_data, maturity_wall)
            assessments.append(a)
            if has_profile:
                manual_count += 1
            print(f"Cov={a.covenant_quality_score} LME={a.lme_vulnerability_score} [{a.data_quality}]")
        except Exception as e:
            print(f"FAILED -- {str(e)[:60]}")

        # Delay only for Claude calls
        if not has_profile and i < total:
            time.sleep(args.delay)

    print(f"\n  Completed: {len(assessments)}/{total} ({manual_count} from profiles)")

    if not assessments:
        print("  No assessments produced.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        output = [asdict(a) for a in assessments]
        print(json.dumps(output, indent=2, default=str))
    else:
        print_report(assessments)


if __name__ == "__main__":
    main()

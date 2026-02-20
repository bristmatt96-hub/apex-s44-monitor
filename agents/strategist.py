"""
Portfolio Construction Agent (Strategist)

Takes all CreditAssessments from the latest universe screen and asks Claude
to construct an optimal portfolio as a senior credit PM running a $500M
European HY book on a multi-manager platform.

Risk limits enforced:
    - Max 5% single-name exposure
    - Max 25% sector concentration
    - 5% drawdown triggers review
    - 7.5% drawdown hard stop

Outputs:
    - RiskSnapshot object (core/models.py)
    - outputs/portfolio/portfolio_YYYYMMDD.xlsx (multi-sheet Excel)
    - outputs/portfolio/portfolio_YYYYMMDD.pdf  (one-page summary)

Usage:
    python -m agents.strategist                              # From latest screen
    python -m agents.strategist --screen-file outputs/xover_screen_20260218.xlsx
    python -m agents.strategist --no-pdf                     # Skip PDF
    python -m agents.strategist --notional 250               # $250M book
"""

import argparse
import json
import os
import sys
import time as _time
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from loguru import logger

from agents.briefing import find_latest_screen, load_assessments_from_excel
from core.models import CreditAssessment, Direction, ItraxxIndex, RiskSnapshot
from knowledge.retriever import KnowledgeRetriever

load_dotenv(override=True)

OUTPUT_DIR = Path("outputs/portfolio")

# ---------------------------------------------------------------------------
# System prompt for the PM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior credit portfolio manager with 20 years experience running European high-yield credit books at a multi-manager hedge fund platform.

You are managing a ${notional}M European HY book focused on iTraxx Crossover (75 names).
Your mandate: generate alpha through single-name CDS while maintaining strict risk discipline.

RISK LIMITS (hard constraints - never breach these):
- Max 5% single-name exposure (i.e. ${max_single_name}M notional per name)
- Max 25% sector concentration (as % of gross exposure)
- 5% portfolio drawdown triggers formal review
- 7.5% portfolio drawdown is hard stop (liquidate to flat)
- Minimum 10 positions for diversification
- Gross exposure between 80-200% of NAV
- Net exposure between -30% to +50% of NAV

YOUR TASK:
Given the analyst assessments for all names in the universe, construct a portfolio:

1. Select your TOP 10 POSITIONS (mix of long and short risk) with sizing (% of book in 0.5% increments)
2. Provide full SECTOR ALLOCATION (% of gross exposure per sector)
3. Provide RATING BUCKET ALLOCATION (BB, B, CCC, split-rated — estimate from spreads)
4. State your NET LONG/SHORT BIAS with reasoning
5. List KEY PORTFOLIO RISKS (3-5 specific risks)
6. Suggest HEDGES (index, tranche, or single-name)
7. Provide 3 STRESS SCENARIOS with estimated P&L impact in bps and $M

PORTFOLIO CONSTRUCTION PRINCIPLES:
- Weight positions by conviction: 5/5 = full size (4-5%), 3/5 = half size (1.5-2.5%)
- No single sector > 25% of gross exposure
- Favor names with clear catalysts and asymmetric risk/reward
- Include hedges: iTraxx Xover index overlay if too directionally biased
- Round all notionals to nearest $0.5M

Respond with ONLY valid JSON matching this exact schema:
{
    "portfolio_date": "YYYY-MM-DD",
    "nav_millions": float,
    "top_positions": [
        {
            "rank": int,
            "entity_name": "string",
            "direction": "LONG_RISK" or "SHORT_RISK",
            "conviction": int 1-5,
            "size_pct": float,
            "notional_millions": float,
            "current_spread": float,
            "fair_spread": float,
            "thesis": "1 sentence",
            "catalyst": "specific time-bound catalyst",
            "sector": "string",
            "estimated_rating": "BB" or "B" or "CCC" or "BB/B" etc.
        }
    ],
    "sector_allocation": {"sector_name": float_pct_of_gross},
    "rating_buckets": {"BB": float_pct, "B": float_pct, "CCC": float_pct},
    "net_bias": {
        "direction": "NET_LONG" or "NET_SHORT" or "NEUTRAL",
        "net_exposure_pct": float,
        "reasoning": "2 sentences explaining directional stance"
    },
    "key_risks": ["risk 1", "risk 2", "risk 3"],
    "hedges": [
        {
            "instrument": "string (e.g. iTraxx Xover, 0-3% tranche, single-name)",
            "direction": "LONG_RISK" or "SHORT_RISK",
            "notional_millions": float,
            "rationale": "string"
        }
    ],
    "stress_scenarios": [
        {
            "scenario": "descriptive name",
            "description": "what happens",
            "estimated_pnl_bps": float (negative = loss),
            "estimated_pnl_millions": float
        }
    ],
    "risk_summary": {
        "gross_exposure_pct": float,
        "net_exposure_pct": float,
        "long_exposure_pct": float,
        "short_exposure_pct": float,
        "position_count": int,
        "avg_conviction": float,
        "largest_position_pct": float,
        "spread_duration": float (portfolio weighted avg 5Y CDS spread in bps),
        "estimated_carry_bps": float
    },
    "pair_trades": [
        {
            "long_name": "string",
            "short_name": "string",
            "rationale": "string",
            "spread_differential": float
        }
    ],
    "commentary": "2-3 sentence portfolio construction rationale"
}

No markdown, no explanation, no code fences. Just the JSON object."""


# ---------------------------------------------------------------------------
# Knowledge context
# ---------------------------------------------------------------------------

def get_portfolio_knowledge() -> str:
    """Query knowledge base for portfolio construction and risk management context."""
    retriever = KnowledgeRetriever(knowledge_path="knowledge")

    queries = [
        "portfolio construction credit allocation position sizing",
        "risk management drawdown stop loss portfolio limits",
        "relative value analysis CDS basis trade pair trade",
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

    return retriever.format_context_for_agent(all_results[:6])


# ---------------------------------------------------------------------------
# Format assessments for prompt
# ---------------------------------------------------------------------------

def format_assessments_for_prompt(
    assessments: list[CreditAssessment],
) -> str:
    """Format all assessments as a compact table for the prompt."""
    lines = ["ANALYST ASSESSMENTS (all names in universe):"]
    lines.append("")

    longs = [a for a in assessments if a.direction == Direction.LONG_RISK]
    shorts = [a for a in assessments if a.direction == Direction.SHORT_RISK]
    flats = [a for a in assessments if a.direction == Direction.FLAT]

    lines.append(f"Total: {len(assessments)} names | "
                 f"Longs: {len(longs)} | Shorts: {len(shorts)} | Flat: {len(flats)}")
    lines.append("")

    for a in sorted(assessments, key=lambda x: (-x.conviction, x.entity_name)):
        mispricing = a.fair_spread - a.current_spread
        lines.append(
            f"- {a.entity_name} | {a.direction.value} | "
            f"Conv {a.conviction}/5 | "
            f"{a.current_spread:.0f}/{a.fair_spread:.0f} ({mispricing:+.0f}bps) | "
            f"Cat: {a.catalyst[:40] if a.catalyst else '-'}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sector mapping from index file
# ---------------------------------------------------------------------------

def load_sector_mapping(index: str = "xover") -> dict[str, str]:
    """Load entity -> sector mapping from index JSON."""
    index_files = {
        "xover": "indices/xover_s44.json",
        "main": "indices/main_s44.json",
    }
    path = index_files.get(index.lower(), "indices/xover_s44.json")

    if not os.path.exists(path):
        return {}

    with open(path) as f:
        data = json.load(f)

    mapping = {}
    for sector, names in data.get("sectors", {}).items():
        for name in names:
            mapping[name] = sector

    return mapping


# ---------------------------------------------------------------------------
# Call Claude to construct portfolio
# ---------------------------------------------------------------------------

def construct_portfolio(
    assessments: list[CreditAssessment],
    notional: float = 500.0,
    index: str = "xover",
) -> dict:
    """Call Claude API to construct optimal portfolio from assessments.

    Args:
        assessments: List of CreditAssessment objects
        notional: Portfolio NAV in millions (default $500M)
        index: Index name for sector mapping

    Returns:
        Portfolio construction dict
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment or .env file")

    client = anthropic.Anthropic(api_key=api_key, timeout=120.0)

    # Build system prompt with actual notional
    max_single_name = notional * 0.05
    system = SYSTEM_PROMPT.replace("${notional}", f"{notional:.0f}")
    system = system.replace("${max_single_name}", f"{max_single_name:.0f}")

    # Build user message
    user_parts = [
        f"Construct a portfolio for a ${notional:.0f}M European HY book.",
        f"Date: {datetime.now().strftime('%Y-%m-%d')}",
        "",
    ]

    # Add sector context
    sector_map = load_sector_mapping(index)
    if sector_map:
        user_parts.append("SECTOR MAPPING:")
        for name, sector in sorted(sector_map.items()):
            user_parts.append(f"  {name} -> {sector}")
        user_parts.append("")

    # Add assessments
    user_parts.append(format_assessments_for_prompt(assessments))

    # Add knowledge context
    knowledge = get_portfolio_knowledge()
    if knowledge:
        user_parts.append("")
        user_parts.append(knowledge)

    # Retry up to 3 times for connection errors
    last_err = None
    for attempt in range(1, 4):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": "\n".join(user_parts)}],
            )
            break
        except anthropic.APIConnectionError as e:
            last_err = e
            wait = attempt * 5
            logger.warning(f"Connection error (attempt {attempt}/3), retrying in {wait}s...")
            _time.sleep(wait)
    else:
        raise last_err

    # Extract text from response
    raw = message.content[0].text.strip()

    # Strip code fences if Claude added them despite instructions
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    portfolio = json.loads(raw)

    # Validate risk limits
    _validate_portfolio(portfolio, notional)

    return portfolio


def _validate_portfolio(portfolio: dict, notional: float) -> None:
    """Validate portfolio against risk limits and log warnings."""
    risk = portfolio.get("risk_summary", {})

    # Single name check
    largest = risk.get("largest_position_pct", 0)
    if largest > 5.0:
        logger.warning(f"BREACH: Largest position {largest:.1f}% exceeds 5% limit")

    # Sector check
    sectors = portfolio.get("sector_allocation", {})
    for sector, pct in sectors.items():
        if pct > 25.0:
            logger.warning(f"BREACH: Sector '{sector}' at {pct:.1f}% exceeds 25% limit")

    # Gross exposure check
    gross = risk.get("gross_exposure_pct", 0)
    if gross < 80 or gross > 200:
        logger.warning(f"WARNING: Gross exposure {gross:.0f}% outside 80-200% range")

    # Net exposure check
    net = risk.get("net_exposure_pct", 0)
    if net < -30 or net > 50:
        logger.warning(f"WARNING: Net exposure {net:.1f}% outside -30% to +50% range")

    # Position count check
    count = risk.get("position_count", 0)
    if count < 10:
        logger.warning(f"WARNING: Only {count} positions (minimum 10 required)")


# ---------------------------------------------------------------------------
# Build RiskSnapshot from portfolio
# ---------------------------------------------------------------------------

def build_risk_snapshot(portfolio: dict, notional: float) -> RiskSnapshot:
    """Convert Claude's portfolio output into a RiskSnapshot model object."""
    risk = portfolio.get("risk_summary", {})
    positions = portfolio.get("top_positions", [])

    # Top 5 positions by size
    sorted_pos = sorted(positions, key=lambda p: abs(p.get("size_pct", 0)), reverse=True)
    top_5 = [
        {
            "entity_name": p["entity_name"],
            "direction": p["direction"],
            "size_pct": abs(p.get("size_pct", 0)),
            "notional_millions": abs(p.get("notional_millions", 0)),
            "current_spread": p.get("current_spread", 0),
        }
        for p in sorted_pos[:5]
    ]

    # Stress tests
    stress_tests = {}
    for s in portfolio.get("stress_scenarios", []):
        stress_tests[s["scenario"]] = {
            "description": s.get("description", ""),
            "pnl_bps": s.get("estimated_pnl_bps", 0),
            "pnl_millions": s.get("estimated_pnl_millions", 0),
        }

    # Correlation matrix placeholder — PM doesn't produce this, mark as empty
    # A future quantitative agent could fill this in
    correlation_matrix = {}

    return RiskSnapshot(
        timestamp=datetime.now(),
        gross_exposure=risk.get("gross_exposure_pct", 0),
        net_exposure=risk.get("net_exposure_pct", 0),
        sector_concentration=portfolio.get("sector_allocation", {}),
        rating_buckets=portfolio.get("rating_buckets", {}),
        spread_duration=risk.get("spread_duration", 0),
        top_5_positions=top_5,
        stress_tests=stress_tests,
        current_drawdown=0.0,  # No live P&L yet
        max_drawdown_30d=0.0,  # No history yet
        correlation_matrix=correlation_matrix,
    )


# ---------------------------------------------------------------------------
# Excel output (multi-sheet)
# ---------------------------------------------------------------------------

def write_portfolio_excel(portfolio: dict, notional: float) -> str:
    """Write portfolio to multi-sheet Excel workbook. Returns filepath."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filepath = str(OUTPUT_DIR / f"portfolio_{date_str}.xlsx")

    wb = Workbook()
    risk = portfolio.get("risk_summary", {})
    positions = portfolio.get("top_positions", [])

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    section_font = Font(bold=True, size=12, color="1F4E79")
    label_font = Font(bold=True, size=11)
    long_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    short_fill = PatternFill(start_color="FCE4EC", end_color="FCE4EC", fill_type="solid")
    thin_border = Border(bottom=Side(style="thin", color="CCCCCC"))
    breach_font = Font(bold=True, color="DC3545")

    # ---- Sheet 1: Top Positions ----
    ws = wb.active
    ws.title = "Top Positions"

    headers = ["Rank", "Entity", "Direction", "Conviction", "Size %",
               "Notional $M", "Spread", "Fair", "Misprice", "Rating",
               "Sector", "Thesis", "Catalyst"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, p in enumerate(positions, 2):
        spread = p.get("current_spread", 0)
        fair = p.get("fair_spread", 0)
        ws.cell(row=row_idx, column=1, value=p.get("rank", row_idx - 1))
        ws.cell(row=row_idx, column=2, value=p.get("entity_name", ""))
        dir_cell = ws.cell(row=row_idx, column=3, value=p.get("direction", ""))
        ws.cell(row=row_idx, column=4, value=p.get("conviction", 0))
        ws.cell(row=row_idx, column=5, value=abs(p.get("size_pct", 0)))
        ws.cell(row=row_idx, column=6, value=abs(p.get("notional_millions", 0)))
        ws.cell(row=row_idx, column=7, value=round(spread, 1))
        ws.cell(row=row_idx, column=8, value=round(fair, 1))
        ws.cell(row=row_idx, column=9, value=round(fair - spread, 1))
        ws.cell(row=row_idx, column=10, value=p.get("estimated_rating", ""))
        ws.cell(row=row_idx, column=11, value=p.get("sector", ""))
        ws.cell(row=row_idx, column=12, value=p.get("thesis", ""))
        ws.cell(row=row_idx, column=13, value=p.get("catalyst", ""))

        if p.get("direction") == "LONG_RISK":
            dir_cell.fill = long_fill
        elif p.get("direction") == "SHORT_RISK":
            dir_cell.fill = short_fill

        for col in range(1, len(headers) + 1):
            ws.cell(row=row_idx, column=col).border = thin_border

    col_widths = [6, 40, 14, 12, 10, 12, 10, 10, 10, 10, 20, 55, 45]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row_idx in range(2, len(positions) + 2):
        for col in [12, 13]:
            ws.cell(row=row_idx, column=col).alignment = Alignment(
                wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"

    # ---- Sheet 2: Risk Summary ----
    rs = wb.create_sheet("Risk Summary")
    rs.cell(row=1, column=1, value="Portfolio Risk Summary").font = section_font
    rs.merge_cells("A1:D1")

    row = 3
    rs.cell(row=row, column=1, value="Overview").font = section_font
    row += 1
    nav_val = portfolio.get("nav_millions", notional)
    overview_items = [
        ("NAV ($M)", nav_val),
        ("Gross Exposure (%)", risk.get("gross_exposure_pct", 0)),
        ("Net Exposure (%)", risk.get("net_exposure_pct", 0)),
        ("Long Exposure (%)", risk.get("long_exposure_pct", 0)),
        ("Short Exposure (%)", risk.get("short_exposure_pct", 0)),
        ("Position Count", risk.get("position_count", len(positions))),
        ("Avg Conviction", risk.get("avg_conviction", 0)),
        ("Largest Position (%)", risk.get("largest_position_pct", 0)),
        ("Spread Duration (bps)", risk.get("spread_duration", 0)),
        ("Estimated Carry (bps)", risk.get("estimated_carry_bps", 0)),
    ]
    for label, value in overview_items:
        rs.cell(row=row, column=1, value=label).font = label_font
        val_cell = rs.cell(row=row, column=2,
                           value=round(value, 2) if isinstance(value, float) else value)
        # Flag breaches
        if label == "Largest Position (%)" and value > 5.0:
            val_cell.font = breach_font
        row += 1

    # Net bias
    row += 1
    rs.cell(row=row, column=1, value="Directional Bias").font = section_font
    row += 1
    net_bias = portfolio.get("net_bias", {})
    rs.cell(row=row, column=1, value="Direction").font = label_font
    rs.cell(row=row, column=2, value=net_bias.get("direction", ""))
    row += 1
    rs.cell(row=row, column=1, value="Net Exposure (%)").font = label_font
    rs.cell(row=row, column=2, value=net_bias.get("net_exposure_pct", 0))
    row += 1
    rs.cell(row=row, column=1, value="Reasoning").font = label_font
    rs.cell(row=row, column=2, value=net_bias.get("reasoning", ""))
    rs.cell(row=row, column=2).alignment = Alignment(wrap_text=True)

    # Key portfolio risks
    row += 2
    rs.cell(row=row, column=1, value="Key Portfolio Risks").font = section_font
    row += 1
    for i, risk_item in enumerate(portfolio.get("key_risks", []), 1):
        rs.cell(row=row, column=1, value=f"{i}.")
        rs.cell(row=row, column=2, value=risk_item)
        rs.cell(row=row, column=2).alignment = Alignment(wrap_text=True)
        row += 1

    # Commentary
    row += 1
    rs.cell(row=row, column=1, value="PM Commentary").font = section_font
    row += 1
    rs.cell(row=row, column=1, value=portfolio.get("commentary", ""))
    rs.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    rs.cell(row=row, column=1).alignment = Alignment(wrap_text=True)

    rs.column_dimensions["A"].width = 25
    rs.column_dimensions["B"].width = 55
    rs.column_dimensions["C"].width = 15
    rs.column_dimensions["D"].width = 15

    # ---- Sheet 3: Sector & Ratings ----
    sa = wb.create_sheet("Allocation")

    sa.cell(row=1, column=1, value="Sector Allocation (% of gross)").font = section_font
    sa.merge_cells("A1:C1")
    sa.cell(row=2, column=1, value="Sector").font = label_font
    sa.cell(row=2, column=2, value="Allocation %").font = label_font
    sa.cell(row=2, column=3, value="Limit %").font = label_font
    sa.cell(row=2, column=4, value="Headroom %").font = label_font
    for col in range(1, 5):
        sa.cell(row=2, column=col).fill = header_fill
        sa.cell(row=2, column=col).font = header_font

    row = 3
    for sector, pct in sorted(portfolio.get("sector_allocation", {}).items(),
                               key=lambda x: -x[1]):
        sa.cell(row=row, column=1, value=sector)
        alloc_cell = sa.cell(row=row, column=2, value=round(pct, 1))
        sa.cell(row=row, column=3, value=25.0)
        headroom = 25.0 - pct
        hr_cell = sa.cell(row=row, column=4, value=round(headroom, 1))
        if headroom < 0:
            alloc_cell.font = breach_font
            hr_cell.font = breach_font
        for col in range(1, 5):
            sa.cell(row=row, column=col).border = thin_border
        row += 1

    row += 2
    sa.cell(row=row, column=1, value="Rating Bucket Allocation (%)").font = section_font
    sa.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    row += 1
    sa.cell(row=row, column=1, value="Rating").font = label_font
    sa.cell(row=row, column=2, value="Allocation %").font = label_font
    for col in range(1, 3):
        sa.cell(row=row, column=col).fill = header_fill
        sa.cell(row=row, column=col).font = header_font
    row += 1
    for bucket, pct in sorted(portfolio.get("rating_buckets", {}).items()):
        sa.cell(row=row, column=1, value=bucket)
        sa.cell(row=row, column=2, value=round(pct, 1))
        for col in range(1, 3):
            sa.cell(row=row, column=col).border = thin_border
        row += 1

    sa.column_dimensions["A"].width = 25
    sa.column_dimensions["B"].width = 16
    sa.column_dimensions["C"].width = 12
    sa.column_dimensions["D"].width = 14

    # ---- Sheet 4: Hedges & Pairs ----
    hp = wb.create_sheet("Hedges & Pairs")

    hp.cell(row=1, column=1, value="Suggested Hedges").font = section_font
    hp.merge_cells("A1:D1")
    hp.cell(row=2, column=1, value="Instrument").font = label_font
    hp.cell(row=2, column=2, value="Direction").font = label_font
    hp.cell(row=2, column=3, value="Notional $M").font = label_font
    hp.cell(row=2, column=4, value="Rationale").font = label_font
    for col in range(1, 5):
        hp.cell(row=2, column=col).fill = header_fill
        hp.cell(row=2, column=col).font = header_font

    row = 3
    for h in portfolio.get("hedges", []):
        hp.cell(row=row, column=1, value=h.get("instrument", ""))
        hp.cell(row=row, column=2, value=h.get("direction", ""))
        hp.cell(row=row, column=3, value=abs(h.get("notional_millions", 0)))
        hp.cell(row=row, column=4, value=h.get("rationale", ""))
        hp.cell(row=row, column=4).alignment = Alignment(wrap_text=True)
        for col in range(1, 5):
            hp.cell(row=row, column=col).border = thin_border
        row += 1

    row += 2
    hp.cell(row=row, column=1, value="Pair Trades").font = section_font
    hp.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    row += 1
    hp.cell(row=row, column=1, value="Long").font = label_font
    hp.cell(row=row, column=2, value="Short").font = label_font
    hp.cell(row=row, column=3, value="Spread Diff").font = label_font
    hp.cell(row=row, column=4, value="Rationale").font = label_font
    for col in range(1, 5):
        hp.cell(row=row, column=col).fill = header_fill
        hp.cell(row=row, column=col).font = header_font
    row += 1
    for p in portfolio.get("pair_trades", []):
        hp.cell(row=row, column=1, value=p.get("long_name", ""))
        hp.cell(row=row, column=2, value=p.get("short_name", ""))
        hp.cell(row=row, column=3, value=p.get("spread_differential", 0))
        hp.cell(row=row, column=4, value=p.get("rationale", ""))
        hp.cell(row=row, column=4).alignment = Alignment(wrap_text=True)
        for col in range(1, 5):
            hp.cell(row=row, column=col).border = thin_border
        row += 1

    hp.column_dimensions["A"].width = 35
    hp.column_dimensions["B"].width = 35
    hp.column_dimensions["C"].width = 14
    hp.column_dimensions["D"].width = 55

    # ---- Sheet 5: Stress Scenarios ----
    ss = wb.create_sheet("Stress Scenarios")

    ss.cell(row=1, column=1, value="Stress Scenarios").font = section_font
    ss.merge_cells("A1:D1")
    ss.cell(row=2, column=1, value="Scenario").font = label_font
    ss.cell(row=2, column=2, value="Description").font = label_font
    ss.cell(row=2, column=3, value="P&L (bps)").font = label_font
    ss.cell(row=2, column=4, value="P&L ($M)").font = label_font
    for col in range(1, 5):
        ss.cell(row=2, column=col).fill = header_fill
        ss.cell(row=2, column=col).font = header_font

    row = 3
    for s in portfolio.get("stress_scenarios", []):
        ss.cell(row=row, column=1, value=s.get("scenario", ""))
        ss.cell(row=row, column=2, value=s.get("description", ""))
        ss.cell(row=row, column=2).alignment = Alignment(wrap_text=True)
        pnl_bps = s.get("estimated_pnl_bps", 0)
        pnl_m = s.get("estimated_pnl_millions", 0)
        bps_cell = ss.cell(row=row, column=3, value=round(pnl_bps, 1))
        m_cell = ss.cell(row=row, column=4, value=round(pnl_m, 2))
        if pnl_bps < 0:
            bps_cell.font = Font(color="DC3545", bold=True)
            m_cell.font = Font(color="DC3545", bold=True)
        else:
            bps_cell.font = Font(color="28A745", bold=True)
            m_cell.font = Font(color="28A745", bold=True)
        for col in range(1, 5):
            ss.cell(row=row, column=col).border = thin_border
        row += 1

    ss.column_dimensions["A"].width = 30
    ss.column_dimensions["B"].width = 55
    ss.column_dimensions["C"].width = 14
    ss.column_dimensions["D"].width = 14

    wb.save(filepath)
    return filepath


# ---------------------------------------------------------------------------
# PDF generator (one-page summary)
# ---------------------------------------------------------------------------

def generate_portfolio_pdf(portfolio: dict) -> str:
    """Generate a professional A4 PDF portfolio summary. Returns filepath."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filepath = str(OUTPUT_DIR / f"portfolio_{date_str}.pdf")

    DARK_NAVY = colors.HexColor("#0D1B2A")
    NAVY = colors.HexColor("#1B2838")
    STEEL = colors.HexColor("#415A77")
    LIGHT_STEEL = colors.HexColor("#778DA9")
    OFF_WHITE = colors.HexColor("#F8F9FA")
    LONG_GREEN = colors.HexColor("#28A745")
    SHORT_RED = colors.HexColor("#DC3545")
    DIVIDER = colors.HexColor("#DEE2E6")
    BODY_COLOR = colors.HexColor("#212529")

    base = getSampleStyleSheet()
    styles = {
        "section": ParagraphStyle(
            "section", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11,
            textColor=NAVY, leading=14,
            spaceBefore=8, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontName="Helvetica", fontSize=8.5,
            textColor=BODY_COLOR, leading=11,
        ),
        "body_bold": ParagraphStyle(
            "body_bold", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=8.5,
            textColor=BODY_COLOR, leading=11,
        ),
        "metric_label": ParagraphStyle(
            "metric_label", parent=base["Normal"],
            fontName="Helvetica", fontSize=7.5,
            textColor=STEEL, leading=10, alignment=TA_CENTER,
        ),
        "metric_value": ParagraphStyle(
            "metric_value", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=13,
            textColor=NAVY, leading=16, alignment=TA_CENTER,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"],
            fontName="Helvetica", fontSize=7.5,
            textColor=STEEL, leading=9,
        ),
        "small_bold": ParagraphStyle(
            "small_bold", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=7.5,
            textColor=BODY_COLOR, leading=9,
        ),
        "commentary": ParagraphStyle(
            "commentary", parent=base["Normal"],
            fontName="Helvetica-Oblique", fontSize=9,
            textColor=STEEL, leading=12,
            spaceBefore=2, spaceAfter=3,
        ),
        "stress_neg": ParagraphStyle(
            "stress_neg", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=8,
            textColor=SHORT_RED, leading=10,
        ),
        "stress_pos": ParagraphStyle(
            "stress_pos", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=8,
            textColor=LONG_GREEN, leading=10,
        ),
    }

    width, height = A4
    risk = portfolio.get("risk_summary", {})
    positions = portfolio.get("top_positions", [])
    nav = portfolio.get("nav_millions", 500)

    def on_page(canvas, doc):
        header_h = 48
        canvas.setFillColor(DARK_NAVY)
        canvas.rect(0, height - header_h, width, header_h, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(1.8 * cm, height - 22,
                          f"Portfolio Construction -- {portfolio.get('portfolio_date', date_str)}")
        canvas.setFillColor(LIGHT_STEEL)
        canvas.setFont("Helvetica", 8.5)
        canvas.drawString(1.8 * cm, height - 37,
                          f"iTraxx Xover S44  |  NAV: ${nav:.0f}M  |  "
                          f"{risk.get('position_count', len(positions))} positions")
        net_exp = risk.get("net_exposure_pct", 0)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawRightString(width - 1.5 * cm, height - 22, f"Net: {net_exp:+.0f}%")
        canvas.setFillColor(DIVIDER)
        canvas.rect(0, 16, width, 0.5, fill=1, stroke=0)
        canvas.setFillColor(LIGHT_STEEL)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawCentredString(width / 2, 7,
                                 "Strategies in Credit  |  Confidential  |  Not Investment Advice")

    frame = Frame(1.5 * cm, 1.0 * cm, width - 3.0 * cm, height - 5.5 * cm, id="main")
    doc = BaseDocTemplate(filepath, pagesize=A4,
                          leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                          topMargin=4.2 * cm, bottomMargin=1.0 * cm)
    doc.addPageTemplates([PageTemplate(id="portfolio", frames=[frame], onPage=on_page)])

    story = []
    usable = width - 3.0 * cm

    # Commentary
    commentary = portfolio.get("commentary", "")
    if commentary:
        story.append(Paragraph(f'"{commentary}"', styles["commentary"]))
        story.append(Spacer(1, 4))

    # --- Risk Overview ---
    story.append(Paragraph("RISK OVERVIEW", styles["section"]))
    ov_labels = ["Gross", "Net", "Longs", "Shorts", "Positions", "Carry"]
    ov_values = [
        f'{risk.get("gross_exposure_pct", 0):.0f}%',
        f'{risk.get("net_exposure_pct", 0):+.0f}%',
        f'{risk.get("long_exposure_pct", 0):.0f}%',
        f'{risk.get("short_exposure_pct", 0):.0f}%',
        str(risk.get("position_count", len(positions))),
        f'{risk.get("estimated_carry_bps", 0):.0f}bp',
    ]
    ov_header = [Paragraph(l, styles["metric_label"]) for l in ov_labels]
    ov_vals = [Paragraph(v, styles["metric_value"]) for v in ov_values]
    col_w = usable / 6
    ov_table = Table([ov_header, ov_vals], colWidths=[col_w] * 6)
    ov_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), OFF_WHITE),
        ("BOX", (0, 0), (-1, -1), 0.5, DIVIDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, DIVIDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ov_table)
    story.append(Spacer(1, 6))

    # --- Top Positions Table ---
    longs = [p for p in positions if p.get("direction") == "LONG_RISK"]
    shorts = [p for p in positions if p.get("direction") == "SHORT_RISK"]

    story.append(Paragraph(
        f"TOP POSITIONS ({len(longs)}L / {len(shorts)}S)", styles["section"]))

    pos_headers = ["#", "Entity", "Dir", "Size%", "Spread", "Fair", "Conv", "Rating", "Catalyst"]
    pos_header_row = [Paragraph(f"<b>{h}</b>", styles["small"]) for h in pos_headers]
    pos_rows = [pos_header_row]
    for p in positions:
        spread = p.get("current_spread", 0)
        fair = p.get("fair_spread", 0)
        dir_short = "L" if p.get("direction") == "LONG_RISK" else "S"
        pos_rows.append([
            Paragraph(str(p.get("rank", "")), styles["body"]),
            Paragraph(p.get("entity_name", "")[:28], styles["body"]),
            Paragraph(dir_short, styles["body_bold"]),
            Paragraph(f'{abs(p.get("size_pct", 0)):.1f}%', styles["body_bold"]),
            Paragraph(f"{spread:.0f}", styles["body"]),
            Paragraph(f"{fair:.0f}", styles["body"]),
            Paragraph(f'{p.get("conviction", 0)}/5', styles["body"]),
            Paragraph(p.get("estimated_rating", ""), styles["small"]),
            Paragraph(p.get("catalyst", "")[:35], styles["small"]),
        ])

    pos_cw = [usable * f for f in [0.04, 0.22, 0.04, 0.07, 0.07, 0.07, 0.06, 0.07, 0.24]]
    pos_table = Table(pos_rows, colWidths=pos_cw)
    pos_style_cmds = [
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (6, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), OFF_WHITE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, DIVIDER),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, DIVIDER),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]
    # Color long/short rows
    for i, p in enumerate(positions, 1):
        color = LONG_GREEN if p.get("direction") == "LONG_RISK" else SHORT_RED
        pos_style_cmds.append(("TEXTCOLOR", (2, i), (3, i), color))
    pos_table.setStyle(TableStyle(pos_style_cmds))
    story.append(pos_table)
    story.append(Spacer(1, 6))

    # --- Two-column: Sector + Ratings side by side ---
    story.append(Paragraph("ALLOCATION", styles["section"]))

    # Sector mini-table
    sec_data = [[Paragraph("<b>Sector</b>", styles["small_bold"]),
                 Paragraph("<b>%</b>", styles["small_bold"])]]
    for sector, pct in sorted(portfolio.get("sector_allocation", {}).items(),
                               key=lambda x: -x[1]):
        headroom_color = "#DC3545" if pct > 25 else BODY_COLOR
        sec_data.append([
            Paragraph(sector, styles["body"]),
            Paragraph(f'<font color="{headroom_color}">{pct:.0f}%</font>', styles["body_bold"]),
        ])

    # Rating mini-table
    rat_data = [[Paragraph("<b>Rating</b>", styles["small_bold"]),
                 Paragraph("<b>%</b>", styles["small_bold"])]]
    for bucket, pct in sorted(portfolio.get("rating_buckets", {}).items()):
        rat_data.append([
            Paragraph(bucket, styles["body"]),
            Paragraph(f"{pct:.0f}%", styles["body_bold"]),
        ])

    half = usable * 0.48
    sec_tbl = Table(sec_data, colWidths=[half * 0.65, half * 0.35])
    sec_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), OFF_WHITE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, DIVIDER),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    rat_tbl = Table(rat_data, colWidths=[half * 0.65, half * 0.35])
    rat_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), OFF_WHITE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, DIVIDER),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    side_by_side = Table([[sec_tbl, rat_tbl]], colWidths=[half, half])
    side_by_side.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(side_by_side)
    story.append(Spacer(1, 6))

    # --- Stress Scenarios ---
    story.append(Paragraph("STRESS SCENARIOS", styles["section"]))
    stress_data = [[
        Paragraph("<b>Scenario</b>", styles["small_bold"]),
        Paragraph("<b>Description</b>", styles["small_bold"]),
        Paragraph("<b>P&L bps</b>", styles["small_bold"]),
        Paragraph("<b>P&L $M</b>", styles["small_bold"]),
    ]]
    for s in portfolio.get("stress_scenarios", []):
        pnl_bps = s.get("estimated_pnl_bps", 0)
        pnl_m = s.get("estimated_pnl_millions", 0)
        pnl_style = "stress_neg" if pnl_bps < 0 else "stress_pos"
        stress_data.append([
            Paragraph(s.get("scenario", ""), styles["body_bold"]),
            Paragraph(s.get("description", "")[:60], styles["small"]),
            Paragraph(f"{pnl_bps:+.0f}", styles[pnl_style]),
            Paragraph(f"${pnl_m:+.1f}M", styles[pnl_style]),
        ])
    str_cw = [usable * f for f in [0.22, 0.46, 0.14, 0.14]]
    str_table = Table(stress_data, colWidths=str_cw)
    str_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), OFF_WHITE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, DIVIDER),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, DIVIDER),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(str_table)
    story.append(Spacer(1, 6))

    # --- Hedges ---
    hedges = portfolio.get("hedges", [])
    if hedges:
        story.append(Paragraph("HEDGES", styles["section"]))
        for h in hedges:
            story.append(Paragraph(
                f"<b>{h.get('instrument', '')}</b> {h.get('direction', '')} "
                f"${abs(h.get('notional_millions', 0)):.0f}M -- {h.get('rationale', '')}",
                styles["body"],
            ))
        story.append(Spacer(1, 4))

    # --- Key Risks ---
    key_risks = portfolio.get("key_risks", [])
    if key_risks:
        story.append(Paragraph("KEY RISKS", styles["section"]))
        for i, r in enumerate(key_risks, 1):
            story.append(Paragraph(f"{i}. {r}", styles["body"]))

    doc.build(story)
    return filepath


# ---------------------------------------------------------------------------
# Telegram summary
# ---------------------------------------------------------------------------

def build_telegram_summary(portfolio: dict) -> str:
    """Build a concise Telegram summary of the portfolio construction."""
    risk = portfolio.get("risk_summary", {})
    positions = portfolio.get("top_positions", [])
    hedges = portfolio.get("hedges", [])
    pairs = portfolio.get("pair_trades", [])
    nav = portfolio.get("nav_millions", 500)
    net_bias = portfolio.get("net_bias", {})

    longs = [p for p in positions if p.get("direction") == "LONG_RISK"]
    shorts = [p for p in positions if p.get("direction") == "SHORT_RISK"]

    lines = []
    lines.append(f"<b>PORTFOLIO -- {portfolio.get('portfolio_date', 'Today')}</b>")
    lines.append(f"NAV: ${nav:.0f}M | {len(positions)} positions | "
                 f"Bias: {net_bias.get('direction', '?')}")
    lines.append("")

    lines.append(f"<b>RISK:</b> "
                 f"Gross {risk.get('gross_exposure_pct', 0):.0f}% | "
                 f"Net {risk.get('net_exposure_pct', 0):+.0f}% | "
                 f"Carry {risk.get('estimated_carry_bps', 0):.0f}bp")
    lines.append("")

    lines.append(f"<b>TOP LONGS ({len(longs)}):</b>")
    for p in sorted(longs, key=lambda x: x.get("size_pct", 0), reverse=True)[:5]:
        lines.append(
            f"  {p['entity_name'][:30]} {abs(p.get('size_pct', 0)):.1f}% "
            f"Conv{p.get('conviction', 0)}")
    lines.append("")

    lines.append(f"<b>TOP SHORTS ({len(shorts)}):</b>")
    for p in sorted(shorts, key=lambda x: abs(x.get("size_pct", 0)), reverse=True)[:5]:
        lines.append(
            f"  {p['entity_name'][:30]} {abs(p.get('size_pct', 0)):.1f}% "
            f"Conv{p.get('conviction', 0)}")
    lines.append("")

    # Stress
    stress = portfolio.get("stress_scenarios", [])
    if stress:
        lines.append("<b>STRESS:</b>")
        for s in stress:
            lines.append(f"  {s.get('scenario', '')}: "
                         f"{s.get('estimated_pnl_bps', 0):+.0f}bp "
                         f"(${s.get('estimated_pnl_millions', 0):+.1f}M)")
        lines.append("")

    lines.append(f"Strategies in Credit | {datetime.now().strftime('%H:%M')} UTC")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Portfolio Construction Agent (Strategist)")
    parser.add_argument(
        "--index", type=str, choices=["xover", "main"], default="xover",
        help="Index to load screen for (default: xover)",
    )
    parser.add_argument(
        "--screen-file", type=str, default=None,
        help="Path to specific screen Excel file (default: latest in outputs/)",
    )
    parser.add_argument(
        "--notional", type=float, default=500.0,
        help="Portfolio NAV in millions (default: 500)",
    )
    parser.add_argument(
        "--no-pdf", action="store_true",
        help="Skip PDF generation",
    )
    parser.add_argument(
        "--no-excel", action="store_true",
        help="Skip Excel generation",
    )
    parser.add_argument(
        "--no-telegram", action="store_true",
        help="Skip Telegram summary preview",
    )
    args = parser.parse_args()

    # Find screen file
    if args.screen_file:
        screen_path = args.screen_file
    else:
        screen_path = find_latest_screen(args.index)

    if not screen_path or not os.path.exists(screen_path):
        print("Error: No screen file found. Run scripts/run_universe.py first.", file=sys.stderr)
        sys.exit(1)

    screen_date = os.path.basename(screen_path).replace(
        f"{args.index}_screen_", "").replace(".xlsx", "")
    print(f"Loading screen: {screen_path} (date: {screen_date})")

    # Load assessments
    assessments = load_assessments_from_excel(screen_path)
    print(f"Loaded {len(assessments)} assessments")

    if not assessments:
        print("Error: No assessments found in screen file.", file=sys.stderr)
        sys.exit(1)

    # Construct portfolio via Claude API
    print(f"\nConstructing portfolio (${args.notional:.0f}M NAV)...")
    print("Calling Claude API with all assessments + knowledge base context...")

    try:
        portfolio = construct_portfolio(
            assessments, notional=args.notional, index=args.index
        )
    except json.JSONDecodeError as e:
        print(f"Error: Claude returned invalid JSON -- {e}", file=sys.stderr)
        sys.exit(1)
    except anthropic.APIError as e:
        print(f"Error: Anthropic API -- {e}", file=sys.stderr)
        sys.exit(1)

    # Build RiskSnapshot
    snapshot = build_risk_snapshot(portfolio, args.notional)
    print(f"\nRiskSnapshot built: gross={snapshot.gross_exposure:.0f}% "
          f"net={snapshot.net_exposure:+.0f}% "
          f"spread_dur={snapshot.spread_duration:.0f}bps")

    # Print terminal summary
    risk = portfolio.get("risk_summary", {})
    positions = portfolio.get("top_positions", [])
    longs = [p for p in positions if p.get("direction") == "LONG_RISK"]
    shorts = [p for p in positions if p.get("direction") == "SHORT_RISK"]

    print(f"\n{'='*60}")
    print("PORTFOLIO CONSTRUCTION COMPLETE")
    print(f"{'='*60}")
    print(f"NAV:        ${portfolio.get('nav_millions', args.notional):.0f}M")
    print(f"Positions:  {len(positions)} ({len(longs)} longs, {len(shorts)} shorts)")
    print(f"Gross:      {risk.get('gross_exposure_pct', 0):.0f}%")
    print(f"Net:        {risk.get('net_exposure_pct', 0):+.0f}%")
    print(f"Carry:      {risk.get('estimated_carry_bps', 0):.0f}bps")
    print(f"Largest:    {risk.get('largest_position_pct', 0):.1f}%")

    # Net bias
    net_bias = portfolio.get("net_bias", {})
    print(f"\nBias:       {net_bias.get('direction', '?')}")
    print(f"Reasoning:  {net_bias.get('reasoning', '')}")

    # Sector allocation
    sectors = portfolio.get("sector_allocation", {})
    if sectors:
        print(f"\nSector Allocation:")
        for sector, pct in sorted(sectors.items(), key=lambda x: -x[1]):
            flag = " ** BREACH" if pct > 25 else ""
            print(f"  {sector}: {pct:.1f}%{flag}")

    # Rating buckets
    ratings = portfolio.get("rating_buckets", {})
    if ratings:
        print(f"\nRating Buckets:")
        for bucket, pct in sorted(ratings.items()):
            print(f"  {bucket}: {pct:.1f}%")

    # Top positions
    print(f"\nTop Positions:")
    for p in positions:
        dir_tag = "L" if p.get("direction") == "LONG_RISK" else "S"
        print(f"  #{p.get('rank', '?')} [{dir_tag}] {p['entity_name']}: "
              f"{abs(p.get('size_pct', 0)):.1f}% "
              f"(${abs(p.get('notional_millions', 0)):.1f}M) | "
              f"Conv {p.get('conviction', 0)}/5 | "
              f"{p.get('current_spread', 0):.0f}/{p.get('fair_spread', 0):.0f}bps | "
              f"{p.get('estimated_rating', '')}")

    # Stress scenarios
    stress = portfolio.get("stress_scenarios", [])
    if stress:
        print(f"\nStress Scenarios:")
        for s in stress:
            print(f"  {s.get('scenario', '')}: "
                  f"{s.get('estimated_pnl_bps', 0):+.0f}bps "
                  f"(${s.get('estimated_pnl_millions', 0):+.1f}M) -- "
                  f"{s.get('description', '')[:60]}")

    # Hedges
    hedges = portfolio.get("hedges", [])
    if hedges:
        print(f"\nHedges:")
        for h in hedges:
            print(f"  {h.get('instrument', '')} {h.get('direction', '')} "
                  f"${abs(h.get('notional_millions', 0)):.1f}M -- {h.get('rationale', '')}")

    # Key risks
    key_risks = portfolio.get("key_risks", [])
    if key_risks:
        print(f"\nKey Risks:")
        for i, r in enumerate(key_risks, 1):
            print(f"  {i}. {r}")

    # Commentary
    commentary = portfolio.get("commentary", "")
    if commentary:
        print(f"\nCommentary: {commentary}")
    print(f"{'='*60}")

    # --- Telegram ---
    if not args.no_telegram:
        tg_message = build_telegram_summary(portfolio)
        print(f"\nTELEGRAM PREVIEW:")
        print(f"{'-'*40}")
        import re
        plain = re.sub(r"<[^>]+>", "", tg_message)
        print(plain)
        print(f"{'-'*40}")

    # --- Excel ---
    if not args.no_excel:
        print("\nGenerating portfolio Excel...")
        xlsx_path = write_portfolio_excel(portfolio, args.notional)
        print(f"Excel saved: {xlsx_path}")

    # --- PDF ---
    if not args.no_pdf:
        print("\nGenerating portfolio PDF...")
        pdf_path = generate_portfolio_pdf(portfolio)
        print(f"PDF saved: {pdf_path}")

    # --- JSON (always save for downstream) ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    json_path = str(OUTPUT_DIR / f"portfolio_{date_str}.json")
    with open(json_path, "w") as f:
        json.dump(portfolio, f, indent=2)
    print(f"JSON saved: {json_path}")

    # Save RiskSnapshot
    snap_path = str(OUTPUT_DIR / f"risk_snapshot_{date_str}.json")
    with open(snap_path, "w") as f:
        f.write(snapshot.model_dump_json(indent=2))
    print(f"RiskSnapshot saved: {snap_path}")

    print("\nPortfolio construction complete.")


if __name__ == "__main__":
    main()

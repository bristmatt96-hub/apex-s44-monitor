"""
Trade Case Study Generator — Credit Catalyst

Generates a 1–2 page PDF documenting a single trade from thesis to outcome.
This is the "walk me through a trade" deliverable that allocators ask for.

Sections:
    1. SETUP        — Entity, date, starting spread, market context
    2. THESIS       — Why we took the position (analyst assessment)
    3. SIGNAL SOURCE — What triggered it (filing, RV screen, earnings, social)
    4. CATALYST     — The specific event we expected
    5. TRADE STRUCTURE — Instrument, sizing, entry spread, stop loss, hedge
    6. RISK METRICS — DV01, CS01, JTD at entry (from CDS pricer)
    7. OUTCOME      — What happened (or "OPEN — monitoring")
    8. POST-MORTEM  — Lessons learned (closed trades only)
    9. KEY TAKEAWAY — One sentence

Data sources:
    - Universe screen Excel (thesis, catalyst, spreads)
    - Trade journal SQLite (entry date, status, exit info)
    - CDS pricer (risk metrics)
    - Portfolio JSON (position sizing, hedges)
    - Social sentiment DB (social signals)
    - Filings DB (filing alerts)

Usage:
    python -m pitch.case_study "INEOS Quattro Finance 2 Plc"
    python -m pitch.case_study --top 5
    python -m pitch.case_study --all
    python -m pitch.case_study --list
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)

from analytics.cds_pricer import (
    cds_dv01,
    cds_cs01,
    jump_to_default,
    implied_default_probability,
    spread_to_upfront,
    _risky_annuity,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("outputs/case_studies")
TRADE_JOURNAL_DB = Path("data/trade_journal.db")
FILINGS_DB = Path("data/filings.db")
SOCIAL_DB = Path("data/social_sentiment.db")
NAV_MILLIONS = 500.0

# Colour palette (matches platform brand)
DARK_NAVY = colors.HexColor("#0D1B2A")
NAVY = colors.HexColor("#1B2838")
STEEL = colors.HexColor("#415A77")
LIGHT_STEEL = colors.HexColor("#778DA9")
OFF_WHITE = colors.HexColor("#F8F9FA")
WHITE = colors.white
LONG_GREEN = colors.HexColor("#28A745")
LONG_BG = colors.HexColor("#E8F5E9")
SHORT_RED = colors.HexColor("#DC3545")
SHORT_BG = colors.HexColor("#FFEBEE")
ACCENT = colors.HexColor("#1976D2")
DIVIDER = colors.HexColor("#DEE2E6")
SECTION_BG = colors.HexColor("#EDF2F7")
AMBER = colors.HexColor("#F59E0B")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CaseStudyData:
    """All data needed to build one case study PDF."""

    # 1. Setup
    entity_name: str = ""
    sector: str = ""
    estimated_rating: str = ""
    entry_date: str = ""
    entry_spread: float = 0.0
    current_spread: float = 0.0
    fair_spread: float = 0.0
    mispricing_bps: float = 0.0

    # 2. Thesis
    direction: str = ""           # LONG_RISK / SHORT_RISK
    conviction: int = 0
    thesis: str = ""

    # 3. Signal source
    signal_sources: list = field(default_factory=list)
    filing_alerts: list = field(default_factory=list)
    social_signals: list = field(default_factory=list)

    # 4. Catalyst
    catalyst: str = ""

    # 5. Trade structure
    notional_m: float = 0.0
    size_pct: float = 0.0
    stop_loss_spread: float = 0.0
    instrument: str = "5Y CDS (iTraxx Xover S44)"
    hedges: list = field(default_factory=list)

    # 6. Risk metrics at entry
    dv01: float = 0.0
    cs01: float = 0.0
    jtd: float = 0.0
    rpv01: float = 0.0
    points_upfront: float = 0.0
    pd_5y: float = 0.0
    annual_carry: float = 0.0

    # 7. Outcome
    status: str = "open"          # open / closed
    exit_spread: float = 0.0
    exit_date: str = ""
    pnl_bps: float = 0.0
    pnl_usd: float = 0.0

    # 8. Post-mortem
    post_mortem: str = ""
    key_risks: list = field(default_factory=list)

    # 9. Key takeaway (generated)
    key_takeaway: str = ""


# ---------------------------------------------------------------------------
# Data loading — pull from all sources
# ---------------------------------------------------------------------------

def _db_query(db_path: Path, sql: str, params: tuple = ()) -> list:
    """Safe SQLite query. Returns empty list if DB missing."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def find_latest_portfolio() -> dict | None:
    """Load the most recent portfolio JSON."""
    portfolio_dir = Path("outputs/portfolio")
    if not portfolio_dir.exists():
        return None
    candidates = sorted(
        portfolio_dir.glob("portfolio_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    with open(candidates[0]) as f:
        return json.load(f)


def find_trade_journal_entry(entity_name: str) -> dict | None:
    """Look up trade from trade journal DB (fuzzy match on name)."""
    rows = _db_query(
        TRADE_JOURNAL_DB,
        "SELECT * FROM trades WHERE entity_name = ? ORDER BY entry_date DESC LIMIT 1",
        (entity_name,),
    )
    if rows:
        return rows[0]
    # Fuzzy: try LIKE
    rows = _db_query(
        TRADE_JOURNAL_DB,
        "SELECT * FROM trades WHERE entity_name LIKE ? ORDER BY entry_date DESC LIMIT 1",
        (f"%{entity_name}%",),
    )
    return rows[0] if rows else None


def find_portfolio_position(portfolio: dict, entity_name: str) -> dict | None:
    """Find a position in the strategist portfolio."""
    for p in portfolio.get("top_positions", []):
        if p["entity_name"].lower() == entity_name.lower():
            return p
    # Fuzzy
    target = entity_name.lower()
    for p in portfolio.get("top_positions", []):
        if target in p["entity_name"].lower() or p["entity_name"].lower() in target:
            return p
    return None


def find_filing_alerts(entity_name: str) -> list[dict]:
    """Get recent filing alerts for entity from filings DB."""
    rows = _db_query(
        FILINGS_DB,
        """SELECT headline, filing_type, date, credit_impact, severity, credit_summary
           FROM filings
           WHERE matched_entity = ?
           ORDER BY date DESC LIMIT 5""",
        (entity_name,),
    )
    return rows


def find_social_signals(entity_name: str) -> list[dict]:
    """Get social sentiment signals for entity."""
    rows = _db_query(
        SOCIAL_DB,
        """SELECT sentiment, severity, claim_summary, author, posted_at, source_credibility
           FROM social_signals
           WHERE entity_name = ?
           ORDER BY severity DESC, posted_at DESC LIMIT 5""",
        (entity_name,),
    )
    return rows


def compute_risk_metrics(spread: float, notional_m: float, direction: str) -> dict:
    """Compute CDS risk metrics at entry."""
    notional = notional_m * 1_000_000
    is_prot_buyer = direction == "SHORT_RISK"

    if spread <= 0:
        return {"dv01": 0, "cs01": 0, "jtd": 0, "rpv01": 0,
                "pu": 0, "pd_5y": 0, "carry": 0}

    dv01 = cds_dv01(spread, notional=notional)
    cs01 = cds_cs01(spread, notional=notional)
    jtd = jump_to_default(spread, notional=notional, is_protection_buyer=is_prot_buyer)
    rpv01 = _risky_annuity(spread)
    pu = spread_to_upfront(spread)
    pd_5y = implied_default_probability(spread)
    carry = notional * spread / 10_000
    if is_prot_buyer:
        carry = -carry  # paying premium

    return {
        "dv01": dv01,
        "cs01": cs01,
        "jtd": jtd,
        "rpv01": rpv01,
        "pu": pu,
        "pd_5y": pd_5y,
        "carry": carry,
    }


def compute_stop_loss(entry_spread: float, direction: str, conviction: int) -> float:
    """Compute stop-loss spread based on direction and conviction.

    Higher conviction = tighter stop (more confidence in thesis).
    SHORT_RISK: stop if spreads tighten (loss on short protection)
    LONG_RISK: stop if spreads widen (loss on long credit)
    """
    # Stop distance scales inversely with conviction
    # Conv 5 = 30% stop distance, Conv 1 = 60%
    stop_pct = 0.30 + (5 - conviction) * 0.075

    if direction == "SHORT_RISK":
        # Protection buyer — loses if spreads tighten
        # Stop loss = entry * (1 - stop_pct) (spread tightens past stop)
        return max(10.0, entry_spread * (1.0 - stop_pct))
    else:
        # Protection seller — loses if spreads widen
        # Stop loss = entry * (1 + stop_pct)
        return entry_spread * (1.0 + stop_pct)


def generate_key_takeaway(data: CaseStudyData) -> str:
    """Generate a one-sentence takeaway."""
    dir_word = "short" if data.direction == "SHORT_RISK" else "long"
    mispricing = abs(data.mispricing_bps)

    if data.status == "open":
        return (
            f"{data.entity_name} {dir_word} at {data.entry_spread:.0f}bp "
            f"(conv {data.conviction}/5) — {mispricing:.0f}bp mispricing "
            f"with {data.catalyst.split(',')[0].strip() if data.catalyst else 'pending catalyst'} "
            f"as the trigger."
        )
    else:
        result = "profitable" if data.pnl_usd > 0 else "loss-making"
        return (
            f"{data.entity_name} {dir_word} closed at {data.exit_spread:.0f}bp "
            f"for {data.pnl_bps:+.0f}bp ({result}): "
            f"{data.post_mortem[:80] if data.post_mortem else 'thesis played out.'}"
        )


def build_case_study(entity_name: str) -> CaseStudyData | None:
    """Assemble all data for a single entity case study."""

    portfolio = find_latest_portfolio()
    trade = find_trade_journal_entry(entity_name)
    position = find_portfolio_position(portfolio, entity_name) if portfolio else None

    # Must have at least one source of data
    if not trade and not position:
        return None

    data = CaseStudyData()
    data.entity_name = entity_name

    # --- Trade journal data (primary source for entry info) ---
    if trade:
        data.entry_date = trade.get("entry_date", "")
        data.entry_spread = trade.get("entry_spread", 0)
        data.direction = trade.get("direction", "")
        data.conviction = trade.get("conviction", 0)
        data.thesis = trade.get("thesis", "")
        data.catalyst = trade.get("catalyst", "")
        data.status = trade.get("status", "open")
        data.exit_spread = trade.get("exit_spread") or 0.0
        data.exit_date = trade.get("exit_date") or ""
        data.pnl_bps = trade.get("pnl_bps") or 0.0
        data.post_mortem = trade.get("post_mortem") or ""
        data.fair_spread = trade.get("fair_spread") or 0.0
        data.mispricing_bps = trade.get("mispricing_bps") or 0.0

        # Parse signal sources and key risks
        ss = trade.get("signal_sources", "")
        data.signal_sources = [s.strip() for s in ss.split(",") if s.strip()] if ss else []
        kr = trade.get("key_risks", "")
        data.key_risks = [r.strip() for r in kr.split(";") if r.strip()] if kr else []

    # --- Portfolio data (sizing, hedges, sector) ---
    if position:
        data.sector = position.get("sector", data.sector or "")
        data.estimated_rating = position.get("estimated_rating", "")
        data.notional_m = position.get("notional_millions", 0)
        data.size_pct = position.get("size_pct", 0)
        data.current_spread = position.get("current_spread", data.entry_spread)
        # Fill in from portfolio if trade journal didn't have it
        if not data.fair_spread:
            data.fair_spread = position.get("fair_spread", 0)
        if not data.thesis:
            data.thesis = position.get("thesis", "")
        if not data.catalyst:
            data.catalyst = position.get("catalyst", "")
        if not data.direction:
            data.direction = position.get("direction", "")
        if not data.conviction:
            data.conviction = position.get("conviction", 0)
        if not data.mispricing_bps:
            data.mispricing_bps = data.fair_spread - data.current_spread
    else:
        data.current_spread = data.entry_spread

    if not data.entry_spread and data.current_spread:
        data.entry_spread = data.current_spread

    # Hedges from portfolio
    if portfolio:
        data.hedges = portfolio.get("hedges", [])

    # --- CDS risk metrics ---
    risk = compute_risk_metrics(
        data.entry_spread,
        data.notional_m if data.notional_m else 10.0,
        data.direction,
    )
    data.dv01 = risk["dv01"]
    data.cs01 = risk["cs01"]
    data.jtd = risk["jtd"]
    data.rpv01 = risk["rpv01"]
    data.points_upfront = risk["pu"]
    data.pd_5y = risk["pd_5y"]
    data.annual_carry = risk["carry"]

    # --- Stop loss ---
    data.stop_loss_spread = compute_stop_loss(
        data.entry_spread, data.direction, data.conviction
    )

    # --- P&L for open trades ---
    if data.status == "open" and data.current_spread and data.entry_spread:
        spread_delta = data.current_spread - data.entry_spread
        if data.direction == "SHORT_RISK":
            # Protection buyer profits on widening
            data.pnl_bps = spread_delta
        else:
            # Protection seller profits on tightening
            data.pnl_bps = -spread_delta
        notional = (data.notional_m if data.notional_m else 10.0) * 1_000_000
        data.pnl_usd = data.dv01 * data.pnl_bps if data.dv01 else 0

    # --- Filing alerts ---
    data.filing_alerts = find_filing_alerts(entity_name)

    # --- Social sentiment ---
    data.social_signals = find_social_signals(entity_name)

    # --- Key takeaway ---
    data.key_takeaway = generate_key_takeaway(data)

    return data


def list_all_entities() -> list[str]:
    """List all entities with trades or portfolio positions."""
    names = set()

    # From trade journal
    rows = _db_query(TRADE_JOURNAL_DB, "SELECT DISTINCT entity_name FROM trades")
    for r in rows:
        names.add(r["entity_name"])

    # From portfolio
    portfolio = find_latest_portfolio()
    if portfolio:
        for p in portfolio.get("top_positions", []):
            names.add(p["entity_name"])

    return sorted(names)


def top_n_entities(n: int) -> list[str]:
    """Return top N entities by conviction (from portfolio)."""
    portfolio = find_latest_portfolio()
    if not portfolio:
        return []
    positions = sorted(
        portfolio.get("top_positions", []),
        key=lambda p: (-p.get("conviction", 0), -abs(p.get("size_pct", 0))),
    )
    return [p["entity_name"] for p in positions[:n]]


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def get_styles() -> dict:
    """Build the paragraph style dictionary."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "cs_title", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=15,
            textColor=WHITE, leading=19,
        ),
        "subtitle": ParagraphStyle(
            "cs_subtitle", parent=base["Normal"],
            fontName="Helvetica", fontSize=9,
            textColor=LIGHT_STEEL, leading=12,
        ),
        "section": ParagraphStyle(
            "cs_section", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=10,
            textColor=DARK_NAVY, leading=13,
            spaceBefore=5, spaceAfter=2,
        ),
        "section_num": ParagraphStyle(
            "cs_section_num", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9,
            textColor=ACCENT, leading=12,
        ),
        "body": ParagraphStyle(
            "cs_body", parent=base["Normal"],
            fontName="Helvetica", fontSize=8.5,
            textColor=colors.HexColor("#212529"), leading=11,
        ),
        "body_small": ParagraphStyle(
            "cs_body_small", parent=base["Normal"],
            fontName="Helvetica", fontSize=7.5,
            textColor=STEEL, leading=10,
        ),
        "metric_label": ParagraphStyle(
            "cs_metric_label", parent=base["Normal"],
            fontName="Helvetica", fontSize=7,
            textColor=STEEL, leading=9, alignment=TA_CENTER,
        ),
        "metric_value": ParagraphStyle(
            "cs_metric_value", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=12,
            textColor=NAVY, leading=15, alignment=TA_CENTER,
        ),
        "bullet": ParagraphStyle(
            "cs_bullet", parent=base["Normal"],
            fontName="Helvetica", fontSize=8,
            textColor=colors.HexColor("#212529"),
            leftIndent=14, bulletIndent=2, leading=10,
            spaceBefore=1,
        ),
        "takeaway": ParagraphStyle(
            "cs_takeaway", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9,
            textColor=NAVY, leading=12,
            borderColor=ACCENT, borderWidth=1,
            borderPadding=4,
        ),
        "footer": ParagraphStyle(
            "cs_footer", parent=base["Normal"],
            fontName="Helvetica", fontSize=6.5,
            textColor=LIGHT_STEEL, alignment=TA_CENTER,
        ),
        "open_tag": ParagraphStyle(
            "cs_open", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9,
            textColor=AMBER, leading=12,
        ),
    }


def _metric_cell(value: str, label: str, styles: dict) -> Table:
    """Build a metric cell (value on top, label below)."""
    return Table(
        [
            [Paragraph(value, styles["metric_value"])],
            [Paragraph(label, styles["metric_label"])],
        ],
        colWidths=[3.5 * cm],
        rowHeights=[0.5 * cm, 0.3 * cm],
        style=TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]),
    )


def _section_header(num: int, title: str, styles: dict) -> Paragraph:
    """Render a numbered section header."""
    return Paragraph(
        f'<font color="#1976D2">{num}.</font>  {title}',
        styles["section"],
    )


def _draw_page_header(canvas, doc, data: CaseStudyData):
    """Draw the dark header bar with entity name and trade badge."""
    width, height = A4
    header_h = 58

    # Background
    canvas.setFillColor(DARK_NAVY)
    canvas.rect(0, height - header_h, width, header_h, fill=1, stroke=0)

    # Title
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(1.5 * cm, height - 23, f"Trade Case Study")

    # Entity name
    canvas.setFillColor(LIGHT_STEEL)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(
        1.5 * cm, height - 39,
        f"{data.entity_name}  |  {data.sector}  |  {data.entry_date}"
    )

    # Direction + conviction badge
    if data.direction == "SHORT_RISK":
        badge_color = SHORT_RED
        badge_text = f"SHORT  {'*' * data.conviction}"
    elif data.direction == "LONG_RISK":
        badge_color = LONG_GREEN
        badge_text = f"LONG  {'*' * data.conviction}"
    else:
        badge_color = STEEL
        badge_text = "FLAT"

    badge_w, badge_h = 90, 20
    badge_x = width - badge_w - 1.5 * cm
    badge_y = height - 42
    canvas.setFillColor(badge_color)
    canvas.roundRect(badge_x, badge_y, badge_w, badge_h, 3, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawCentredString(badge_x + badge_w / 2, badge_y + 6, badge_text)

    # Status badge
    if data.status == "open":
        status_color = AMBER
        status_text = "OPEN"
    else:
        status_color = LONG_GREEN if data.pnl_bps > 0 else SHORT_RED
        status_text = "CLOSED"

    sb_w, sb_h = 55, 16
    sb_x = width - sb_w - 1.5 * cm
    sb_y = height - 18
    canvas.setFillColor(status_color)
    canvas.roundRect(sb_x, sb_y, sb_w, sb_h, 3, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawCentredString(sb_x + sb_w / 2, sb_y + 4.5, status_text)


def _draw_footer(canvas, doc):
    """Draw the page footer."""
    width, _ = A4
    canvas.setFillColor(LIGHT_STEEL)
    canvas.setFont("Helvetica", 6.5)
    canvas.drawCentredString(
        width / 2, 15,
        "Credit Catalyst  |  Confidential — For Investor Discussion Only  |  "
        + datetime.now().strftime("%d %b %Y"),
    )


def _esc(text: str) -> str:
    """Escape XML-special characters for ReportLab Paragraphs."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def generate_pdf(data: CaseStudyData, filepath: str) -> None:
    """Build the 1–2 page A4 PDF."""

    styles = get_styles()
    width, height = A4
    content_width = width - 2.4 * cm

    doc = BaseDocTemplate(
        filepath,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=62,
        bottomMargin=28,
    )

    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        content_width, height - 62 - 28,
        id="main",
    )
    template = PageTemplate(
        "main", frames=[frame],
        onPage=lambda c, d: (
            _draw_page_header(c, d, data),
            _draw_footer(c, d),
        ),
    )
    doc.addPageTemplates([template])

    story = []

    # ── 1. SETUP ─────────────────────────────────────────────────────────
    story.append(_section_header(1, "SETUP", styles))

    dir_label = "Short Credit (Buy Protection)" if data.direction == "SHORT_RISK" else "Long Credit (Sell Protection)"
    mispricing = data.fair_spread - data.current_spread
    misp_label = f"{abs(mispricing):.0f}bp {'wide' if mispricing > 0 else 'tight'} of fair"

    setup_data = [
        ["Entity", _esc(data.entity_name), "Direction", dir_label],
        ["Sector", _esc(data.sector), "Conviction", f"{'*' * data.conviction} ({data.conviction}/5)"],
        ["Rating", _esc(data.estimated_rating), "Entry Date", data.entry_date or "—"],
        ["Entry Spread", f"{data.entry_spread:.0f} bp", "Fair Spread", f"{data.fair_spread:.0f} bp"],
        ["Mispricing", misp_label, "Current Spread", f"{data.current_spread:.0f} bp"],
    ]

    setup_table = Table(
        [[Paragraph(c, styles["body"]) for c in row] for row in setup_data],
        colWidths=[3 * cm, 5.5 * cm, 3 * cm, 5.5 * cm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), SECTION_BG),
            ("BACKGROUND", (2, 0), (2, -1), SECTION_BG),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, DIVIDER),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    )
    story.append(setup_table)
    story.append(Spacer(1, 4))

    # ── 2. THESIS ────────────────────────────────────────────────────────
    story.append(_section_header(2, "THESIS", styles))
    if data.thesis:
        story.append(Paragraph(_esc(data.thesis), styles["body"]))
    else:
        story.append(Paragraph("<i>No thesis recorded.</i>", styles["body_small"]))
    story.append(Spacer(1, 4))

    # ── 3. SIGNAL SOURCE ────────────────────────────────────────────────
    story.append(_section_header(3, "SIGNAL SOURCE", styles))

    source_items = []
    if data.signal_sources:
        source_items.append(f"<b>Analyst signals:</b> {_esc(', '.join(data.signal_sources))}")

    if data.filing_alerts:
        for f in data.filing_alerts[:3]:
            sev_stars = "*" * (f.get("severity") or 0)
            hl = _esc(f.get("headline", ""))
            ft = _esc(f.get("filing_type", ""))
            dt = f.get("date", "")
            source_items.append(
                f"<b>Filing [{ft}]</b> {dt}: {hl} "
                f"(severity {sev_stars})"
            )

    if data.social_signals:
        for s in data.social_signals[:3]:
            sev = s.get("severity", 0)
            sent = s.get("sentiment", "")
            summary = _esc(s.get("claim_summary", "")[:100])
            cred = s.get("source_credibility", "")
            source_items.append(
                f"<b>Social [{sent.upper()}]</b> sev={sev}/5 ({cred}): {summary}"
            )

    if not source_items:
        source_items.append("Universe screen + analyst assessment")

    for item in source_items:
        story.append(Paragraph(f"\u2022  {item}", styles["bullet"]))
    story.append(Spacer(1, 4))

    # ── 4. CATALYST ──────────────────────────────────────────────────────
    story.append(_section_header(4, "CATALYST", styles))
    if data.catalyst:
        story.append(Paragraph(_esc(data.catalyst), styles["body"]))
    else:
        story.append(Paragraph("<i>No specific catalyst identified.</i>", styles["body_small"]))
    story.append(Spacer(1, 4))

    # ── 5. TRADE STRUCTURE ───────────────────────────────────────────────
    story.append(_section_header(5, "TRADE STRUCTURE", styles))

    struct_data = [
        ["Instrument", _esc(data.instrument)],
        ["Notional", f"${data.notional_m:.1f}M" if data.notional_m else "—"],
        ["Size (% NAV)", f"{data.size_pct:.1f}%" if data.size_pct else "—"],
        ["Entry Spread", f"{data.entry_spread:.0f} bp"],
        ["Stop Loss", f"{data.stop_loss_spread:.0f} bp"],
    ]

    # Add hedge info
    if data.hedges:
        for h in data.hedges:
            h_dir = "Long" if h.get("direction") == "LONG_RISK" else "Short"
            h_name = h.get("instrument", "")
            h_not = h.get("notional_millions", 0)
            struct_data.append([
                f"Hedge: {_esc(h_name)}",
                f"{h_dir} ${h_not:.0f}M",
            ])

    struct_table = Table(
        [[Paragraph(c, styles["body"]) for c in row] for row in struct_data],
        colWidths=[4.5 * cm, 12.5 * cm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), SECTION_BG),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, DIVIDER),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    )
    story.append(struct_table)
    story.append(Spacer(1, 4))

    # ── 6. RISK METRICS AT ENTRY ─────────────────────────────────────────
    story.append(_section_header(6, "RISK METRICS AT ENTRY", styles))

    is_prot_buyer = data.direction == "SHORT_RISK"
    jtd_label = "JTD (prot buyer)" if is_prot_buyer else "JTD (prot seller)"

    risk_row = Table(
        [[
            _metric_cell(f"${data.dv01:,.0f}", "DV01", styles),
            _metric_cell(f"${data.cs01:,.0f}", "CS01", styles),
            _metric_cell(f"${data.jtd / 1000:,.0f}k", jtd_label, styles),
            _metric_cell(f"{data.rpv01:.2f}y", "RPV01", styles),
            _metric_cell(f"{data.pd_5y * 100:.1f}%", "5Y Default Prob", styles),
        ]],
        colWidths=[content_width / 5] * 5,
        style=TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.5, DIVIDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, DIVIDER),
            ("BACKGROUND", (0, 0), (-1, -1), OFF_WHITE),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]),
    )
    story.append(risk_row)

    # Additional risk detail
    carry_label = "Premium Cost" if is_prot_buyer else "Carry Income"
    carry_val = abs(data.annual_carry)
    pu_val = data.points_upfront

    risk_detail = Table(
        [
            [Paragraph(c, styles["body"]) for c in
             ["Points Upfront", f"{pu_val:+.2f}%",
              carry_label, f"${carry_val:,.0f}/yr"]],
        ],
        colWidths=[3.5 * cm, 5 * cm, 3.5 * cm, 5 * cm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), SECTION_BG),
            ("BACKGROUND", (2, 0), (2, -1), SECTION_BG),
            ("GRID", (0, 0), (-1, -1), 0.5, DIVIDER),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]),
    )
    story.append(risk_detail)
    story.append(Spacer(1, 4))

    # ── 7. OUTCOME ───────────────────────────────────────────────────────
    story.append(_section_header(7, "OUTCOME", styles))

    if data.status == "open":
        # Current unrealised P&L
        outcome_bg = LONG_BG if data.pnl_bps >= 0 else SHORT_BG
        pnl_color = LONG_GREEN if data.pnl_bps >= 0 else SHORT_RED

        outcome_data = [
            ["Status", "OPEN — Monitoring"],
            ["Current Spread", f"{data.current_spread:.0f} bp"],
            ["Unrealised P&L", f"{data.pnl_bps:+.0f} bp"],
            ["Stop Loss", f"{data.stop_loss_spread:.0f} bp"],
        ]

        outcome_table = Table(
            [[Paragraph(c, styles["body"]) for c in row] for row in outcome_data],
            colWidths=[4.5 * cm, 12.5 * cm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), SECTION_BG),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, DIVIDER),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (1, 0), (1, 0), SECTION_BG),
            ]),
        )
        story.append(outcome_table)
    else:
        outcome_data = [
            ["Status", "CLOSED"],
            ["Exit Date", data.exit_date or "—"],
            ["Exit Spread", f"{data.exit_spread:.0f} bp"],
            ["Realised P&L", f"{data.pnl_bps:+.0f} bp "
                             f"(${data.pnl_usd:+,.0f})"],
        ]
        outcome_table = Table(
            [[Paragraph(c, styles["body"]) for c in row] for row in outcome_data],
            colWidths=[4.5 * cm, 12.5 * cm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), SECTION_BG),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, DIVIDER),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ]),
        )
        story.append(outcome_table)
    story.append(Spacer(1, 4))

    # ── 8. POST-MORTEM / KEY RISKS ───────────────────────────────────────
    story.append(_section_header(8, "POST-MORTEM / KEY RISKS", styles))

    if data.status != "open" and data.post_mortem:
        story.append(Paragraph(
            f"<b>Post-Mortem:</b> {_esc(data.post_mortem)}", styles["body"],
        ))
        story.append(Spacer(1, 2))

    if data.key_risks:
        story.append(Paragraph("<b>Key Risks:</b>", styles["body"]))
        for risk in data.key_risks[:5]:
            story.append(Paragraph(f"\u2022  {_esc(risk)}", styles["bullet"]))
    else:
        story.append(Paragraph(
            "<i>No specific risks recorded. Standard CDS market risk applies.</i>",
            styles["body_small"],
        ))
    story.append(Spacer(1, 6))

    # ── 9. KEY TAKEAWAY ──────────────────────────────────────────────────
    story.append(_section_header(9, "KEY TAKEAWAY", styles))

    # Styled takeaway box
    takeaway_table = Table(
        [[Paragraph(_esc(data.key_takeaway), styles["takeaway"])]],
        colWidths=[content_width],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.5, ACCENT),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EBF5FB")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]),
    )
    story.append(takeaway_table)

    # ── Disclaimer ───────────────────────────────────────────────────────
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "<i>This case study is for discussion purposes only. "
        "CDS pricing uses a flat hazard rate model with 40% recovery. "
        "Actual execution may differ from entry levels shown.</i>",
        ParagraphStyle(
            "cs_disclaim", fontName="Helvetica", fontSize=6.5,
            textColor=STEEL, leading=9, alignment=TA_CENTER,
        ),
    ))

    doc.build(story)


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def print_case_study(data: CaseStudyData) -> None:
    """Pretty-print a case study summary to the terminal."""
    W = 72
    print()
    print("=" * W)
    dir_tag = "SHORT" if data.direction == "SHORT_RISK" else "LONG"
    stars = "*" * data.conviction
    print(f"  TRADE CASE STUDY: {data.entity_name}")
    print(f"  {dir_tag} {stars} ({data.conviction}/5)  |  "
          f"{data.sector}  |  {data.estimated_rating}  |  "
          f"{data.entry_date}")
    print("=" * W)

    print()
    print(f"  1. SETUP")
    print(f"     Entry Spread: {data.entry_spread:.0f} bp  |  "
          f"Fair: {data.fair_spread:.0f} bp  |  "
          f"Mispricing: {data.mispricing_bps:+.0f} bp")

    print(f"\n  2. THESIS")
    thesis = data.thesis or "N/A"
    for line in _wrap_text(thesis, 64):
        print(f"     {line}")

    print(f"\n  3. SIGNAL SOURCE")
    if data.signal_sources:
        print(f"     Analyst: {', '.join(data.signal_sources)}")
    if data.filing_alerts:
        for f in data.filing_alerts[:2]:
            print(f"     Filing: {f.get('headline', '')[:50]}  (sev={f.get('severity', '?')})")
    if data.social_signals:
        for s in data.social_signals[:2]:
            sent = s.get("sentiment", "?").upper()
            print(f"     Social [{sent}]: {s.get('claim_summary', '')[:50]}...")

    print(f"\n  4. CATALYST")
    print(f"     {data.catalyst or 'N/A'}")

    print(f"\n  5. TRADE STRUCTURE")
    print(f"     Instrument: {data.instrument}")
    print(f"     Notional: ${data.notional_m:.1f}M ({data.size_pct:.1f}% NAV)")
    print(f"     Entry: {data.entry_spread:.0f} bp  |  Stop: {data.stop_loss_spread:.0f} bp")
    if data.hedges:
        for h in data.hedges:
            hdir = "Long" if h.get("direction") == "LONG_RISK" else "Short"
            print(f"     Hedge: {hdir} {h.get('instrument', '')} "
                  f"${h.get('notional_millions', 0):.0f}M")

    print(f"\n  6. RISK METRICS AT ENTRY")
    print(f"     DV01: ${data.dv01:,.0f}  |  CS01: ${data.cs01:,.0f}  |  "
          f"JTD: ${data.jtd / 1000:,.0f}k")
    print(f"     RPV01: {data.rpv01:.2f}y  |  PU: {data.points_upfront:+.2f}%  |  "
          f"5Y PD: {data.pd_5y * 100:.1f}%")

    print(f"\n  7. OUTCOME")
    if data.status == "open":
        print(f"     Status: OPEN — Monitoring")
        print(f"     Current: {data.current_spread:.0f} bp  |  "
              f"Unrealised: {data.pnl_bps:+.0f} bp")
    else:
        print(f"     Status: CLOSED ({data.exit_date})")
        print(f"     Exit: {data.exit_spread:.0f} bp  |  "
              f"P&L: {data.pnl_bps:+.0f} bp (${data.pnl_usd:+,.0f})")

    print(f"\n  8. KEY RISKS")
    for r in data.key_risks[:3]:
        print(f"     - {r[:65]}")
    if not data.key_risks:
        print(f"     (no specific risks recorded)")

    print(f"\n  9. KEY TAKEAWAY")
    print(f"     {data.key_takeaway}")
    print()
    print("=" * W)


def _wrap_text(text: str, width: int) -> list[str]:
    """Simple word-wrap for terminal output."""
    words = text.split()
    lines = []
    current = ""
    for w in words:
        if current and len(current) + 1 + len(w) > width:
            lines.append(current)
            current = w
        else:
            current = current + " " + w if current else w
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Credit Catalyst — Trade Case Study Generator"
    )
    parser.add_argument("entity", nargs="?", default=None,
                        help="Entity name (or partial match)")
    parser.add_argument("--top", type=int, default=None,
                        help="Generate for top N positions by conviction")
    parser.add_argument("--all", action="store_true",
                        help="Generate for all portfolio positions")
    parser.add_argument("--list", action="store_true",
                        help="List all available entities")
    parser.add_argument("--no-pdf", action="store_true",
                        help="Skip PDF generation (terminal only)")
    args = parser.parse_args()

    # List mode
    if args.list:
        entities = list_all_entities()
        print(f"\n  Available entities ({len(entities)}):")
        print("  " + "-" * 50)
        for e in entities:
            print(f"    {e}")
        print()
        return

    # Determine which entities to generate
    targets: list[str] = []

    if args.top:
        targets = top_n_entities(args.top)
        if not targets:
            print("ERROR: No portfolio found. Run: python -m agents.strategist")
            sys.exit(1)
        print(f"Generating case studies for top {args.top} positions...")

    elif args.all:
        portfolio = find_latest_portfolio()
        if not portfolio:
            print("ERROR: No portfolio found. Run: python -m agents.strategist")
            sys.exit(1)
        targets = [p["entity_name"] for p in portfolio.get("top_positions", [])]
        print(f"Generating case studies for all {len(targets)} positions...")

    elif args.entity:
        # Try exact match first, then fuzzy
        all_entities = list_all_entities()
        exact = [e for e in all_entities if e.lower() == args.entity.lower()]
        if exact:
            targets = exact
        else:
            fuzzy = [e for e in all_entities if args.entity.lower() in e.lower()]
            if fuzzy:
                targets = fuzzy
                if len(fuzzy) > 1:
                    print(f"  Matched {len(fuzzy)} entities:")
                    for e in fuzzy:
                        print(f"    {e}")
            else:
                print(f"ERROR: No entity found matching '{args.entity}'")
                print(f"  Try: python -m pitch.case_study --list")
                sys.exit(1)

    else:
        parser.print_help()
        print("\nExamples:")
        print('  python -m pitch.case_study "INEOS Quattro Finance 2 Plc"')
        print("  python -m pitch.case_study --top 5")
        print("  python -m pitch.case_study --list")
        sys.exit(0)

    # Generate case studies
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    generated = 0

    for entity in targets:
        print(f"\n  Building case study: {entity}")
        data = build_case_study(entity)

        if not data:
            print(f"    SKIP — No data found for {entity}")
            continue

        # Terminal output
        print_case_study(data)

        # PDF output
        if not args.no_pdf:
            safe_name = re.sub(r'[^\w\-]', '_', entity)[:40]
            pdf_path = str(OUTPUT_DIR / f"{safe_name}_{date_str}.pdf")
            generate_pdf(data, pdf_path)
            print(f"    PDF: {pdf_path}")

        generated += 1

    if generated > 0:
        print(f"\n  Generated {generated} case study/studies in {OUTPUT_DIR}/")
    else:
        print("\n  No case studies generated.")


if __name__ == "__main__":
    main()

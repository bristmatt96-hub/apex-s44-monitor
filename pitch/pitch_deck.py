"""
Strategies in Credit Pitch Deck Generator

Auto-generates a 15-20 slide PowerPoint pitch deck from live system data:
- Latest universe screen (81 Xover names)
- Latest portfolio construction
- Filing monitor data
- RiskSnapshot

Output: outputs/pitch/strategies_in_credit_pitch_YYYYMMDD.pptx

Usage:
    python -m pitch.pitch_deck
    python -m pitch.pitch_deck --screen-file outputs/xover_screen_20260218.xlsx
    python -m pitch.pitch_deck --notional 250
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt, Emu

from agents.briefing import find_latest_screen, load_assessments_from_excel
from core.models import CreditAssessment, Direction

OUTPUT_DIR = Path("outputs/pitch")

# ---------------------------------------------------------------------------
# Colour palette (matches PDF/Excel scheme)
# ---------------------------------------------------------------------------
DARK_NAVY = RGBColor(0x0D, 0x1B, 0x2A)
NAVY = RGBColor(0x1B, 0x28, 0x38)
STEEL = RGBColor(0x41, 0x5A, 0x77)
LIGHT_STEEL = RGBColor(0x77, 0x8D, 0xA9)
OFF_WHITE = RGBColor(0xF8, 0xF9, 0xFA)
LONG_GREEN = RGBColor(0x28, 0xA7, 0x45)
SHORT_RED = RGBColor(0xDC, 0x35, 0x45)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BODY_GRAY = RGBColor(0x21, 0x25, 0x29)
AMBER = RGBColor(0xFF, 0xC1, 0x07)
DIVIDER_GRAY = RGBColor(0xDE, 0xE2, 0xE6)

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_slide_bg(slide, color):
    """Set slide background to a solid colour."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(slide, left, top, width, height, text, font_size=12,
                 bold=False, color=BODY_GRAY, alignment=PP_ALIGN.LEFT,
                 font_name="Calibri"):
    """Add a simple text box to a slide."""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.font.name = font_name
    p.alignment = alignment
    return txBox


def _add_paragraph(text_frame, text, font_size=12, bold=False,
                   color=BODY_GRAY, alignment=PP_ALIGN.LEFT,
                   space_before=0, space_after=0, font_name="Calibri"):
    """Add a paragraph to an existing text frame."""
    p = text_frame.add_paragraph()
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.font.name = font_name
    p.alignment = alignment
    p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    return p


def _add_title_bar(slide, title_text, subtitle_text=""):
    """Add a dark navy title bar across the top of a content slide."""
    # Title bar background
    left, top, w, h = Inches(0), Inches(0), SLIDE_WIDTH, Inches(1.2)
    shape = slide.shapes.add_shape(1, left, top, w, h)  # 1 = rectangle
    shape.fill.solid()
    shape.fill.fore_color.rgb = DARK_NAVY
    shape.line.fill.background()

    # Title text
    _add_textbox(slide, Inches(0.6), Inches(0.15), Inches(10), Inches(0.5),
                 title_text, font_size=24, bold=True, color=WHITE)

    if subtitle_text:
        _add_textbox(slide, Inches(0.6), Inches(0.65), Inches(10), Inches(0.4),
                     subtitle_text, font_size=13, color=LIGHT_STEEL)

    # Strategies in Credit badge right
    _add_textbox(slide, Inches(10.5), Inches(0.25), Inches(2.5), Inches(0.4),
                 "Strategies in Credit", font_size=11, bold=True, color=LIGHT_STEEL,
                 alignment=PP_ALIGN.RIGHT)


def _add_footer(slide, date_str):
    """Add confidential footer."""
    _add_textbox(slide, Inches(0.6), Inches(7.0), Inches(12), Inches(0.35),
                 f"Strategies in Credit  |  Confidential  |  Not Investment Advice  |  {date_str}",
                 font_size=8, color=LIGHT_STEEL, alignment=PP_ALIGN.CENTER)


def _add_metric_box(slide, left, top, width, height, label, value,
                    value_color=NAVY, bg_color=None):
    """Add a metric box with label above and large value below."""
    if bg_color:
        shape = slide.shapes.add_shape(1, left, top, width, height)
        shape.fill.solid()
        shape.fill.fore_color.rgb = bg_color
        shape.line.fill.background()

    _add_textbox(slide, left + Inches(0.1), top + Inches(0.05),
                 width - Inches(0.2), Inches(0.3),
                 label, font_size=9, color=STEEL, alignment=PP_ALIGN.CENTER)
    _add_textbox(slide, left + Inches(0.1), top + Inches(0.35),
                 width - Inches(0.2), Inches(0.5),
                 str(value), font_size=22, bold=True, color=value_color,
                 alignment=PP_ALIGN.CENTER)


def _add_table(slide, left, top, width, rows_data, col_widths,
               header=True):
    """Add a styled table to the slide."""
    n_rows = len(rows_data)
    n_cols = len(rows_data[0]) if rows_data else 0
    if n_rows == 0 or n_cols == 0:
        return None

    table_shape = slide.shapes.add_table(n_rows, n_cols, left, top,
                                          width, Inches(0.35 * n_rows))
    table = table_shape.table

    # Set column widths
    for i, w in enumerate(col_widths):
        table.columns[i].width = w

    for r, row_data in enumerate(rows_data):
        for c, cell_text in enumerate(row_data):
            cell = table.cell(r, c)
            cell.text = str(cell_text)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.font.size = Pt(9)
                paragraph.font.name = "Calibri"
                if r == 0 and header:
                    paragraph.font.bold = True
                    paragraph.font.color.rgb = WHITE
                    paragraph.font.size = Pt(10)
                else:
                    paragraph.font.color.rgb = BODY_GRAY

            if r == 0 and header:
                cell.fill.solid()
                cell.fill.fore_color.rgb = NAVY
            elif r % 2 == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = OFF_WHITE
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE

    return table_shape


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_portfolio(index: str = "xover") -> dict:
    """Load latest portfolio JSON from outputs/portfolio/."""
    pattern = os.path.join("outputs", "portfolio", "portfolio_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return {}
    with open(files[0]) as f:
        return json.load(f)


def load_risk_snapshot() -> dict:
    """Load latest risk snapshot JSON."""
    pattern = os.path.join("outputs", "portfolio", "risk_snapshot_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return {}
    with open(files[0]) as f:
        return json.load(f)


def load_recent_filings(days: int = 7) -> list[dict]:
    """Load recent classified filings from SQLite."""
    db_path = Path("data/filings.db")
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT matched_entity, source, filing_type, headline,
               date, credit_impact, severity, credit_summary
        FROM filings
        WHERE date >= ? AND classified = 1
        ORDER BY severity DESC, date DESC
        LIMIT 20
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_sector_mapping(index: str = "xover") -> dict[str, str]:
    """Load sector mapping from index JSON."""
    path = f"indices/{index}_s44.json"
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
# Slide builders
# ---------------------------------------------------------------------------

def slide_title(prs, date_str):
    """Slide 1: Title slide."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _set_slide_bg(slide, DARK_NAVY)

    _add_textbox(slide, Inches(1.5), Inches(1.8), Inches(10), Inches(1.0),
                 "Strategies in Credit", font_size=48, bold=True, color=WHITE)
    _add_textbox(slide, Inches(1.5), Inches(2.9), Inches(10), Inches(0.6),
                 "European Credit Relative Value", font_size=28, color=LIGHT_STEEL)
    _add_textbox(slide, Inches(1.5), Inches(3.7), Inches(10), Inches(0.5),
                 "iTraxx Crossover S44 | Single-Name CDS Alpha",
                 font_size=16, color=STEEL)

    # Date + confidential
    _add_textbox(slide, Inches(1.5), Inches(5.5), Inches(10), Inches(0.4),
                 date_str, font_size=14, color=LIGHT_STEEL)
    _add_textbox(slide, Inches(1.5), Inches(6.1), Inches(10), Inches(0.3),
                 "Confidential | For Qualified Investors Only",
                 font_size=10, color=STEEL)


def slide_executive_summary(prs, assessments, portfolio, date_str):
    """Slide 2: Executive Summary."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Executive Summary")
    _add_footer(slide, date_str)

    longs = [a for a in assessments if a.direction == Direction.LONG_RISK]
    shorts = [a for a in assessments if a.direction == Direction.SHORT_RISK]
    nav = portfolio.get("nav_millions", 500)

    bullets = [
        f"Strategy: AI-assisted fundamental credit analysis focused on European HY single-name CDS",
        f"Universe: {len(assessments)} names across iTraxx Crossover Series 44 (5 sectors)",
        f"Approach: Claude AI analyst processes 848 knowledge chunks + regulatory filings to generate real-time credit assessments",
        f"Signal: {len(longs)} names identified as LONG RISK (spreads too wide), {len(shorts)} as SHORT RISK (spreads too tight)",
        f"Portfolio: ${nav:.0f}M NAV, {portfolio.get('risk_summary', {}).get('position_count', 10)} core positions with index + tranche hedges",
        f"Edge: Filing speed (Companies House, Investegate within minutes), quantitative knowledge base, iTraxx roll dynamics",
    ]

    txBox = slide.shapes.add_textbox(Inches(0.8), Inches(1.6), Inches(11.5), Inches(5.0))
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, bullet in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = bullet
        p.font.size = Pt(14)
        p.font.color.rgb = BODY_GRAY
        p.font.name = "Calibri"
        p.space_after = Pt(10)
        p.level = 0


def slide_edge(prs, date_str):
    """Slide 3: Edge Description."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Competitive Edge", "Three distinct alpha sources")
    _add_footer(slide, date_str)

    edges = [
        ("INFORMATION", LONG_GREEN,
         "Filing Monitor Speed",
         [
             "Companies House, Investegate, EQS News scraped every 15 minutes",
             "Claude AI classifies filings by credit impact in real-time",
             "Material events (covenant breaches, LMEs, management changes) flagged before consensus",
             "Typical edge: 2-6 hours ahead of sell-side coverage",
         ]),
        ("ANALYTICAL", NAVY,
         "AI-Augmented Fundamental Analysis",
         [
             "848 knowledge chunks from 39 reference texts (Moyer, Natenberg, Schwager, etc.)",
             "Claude AI analyst processes each name with context from credit, options, and psychology research",
             "Conviction-weighted assessments with specific catalysts and fair-value targets",
             "Full universe re-screened in 25 minutes (81 API calls with knowledge retrieval)",
         ]),
        ("STRUCTURAL", STEEL,
         "CDS Market Microstructure",
         [
             "iTraxx roll dynamics: new series entry/exit creates predictable spread moves",
             "Tranche basis: 0-3% and 3-7% tranches provide convex hedging unavailable in bonds",
             "CLO demand cycles: AAA spread compression drives HY tightening with 2-week lead",
             "Index vs single-name basis: systematic mispricing in S44 constituents vs index",
         ]),
    ]

    for i, (title, color, subtitle, items) in enumerate(edges):
        left = Inches(0.5) + Inches(4.1) * i
        top = Inches(1.5)
        w = Inches(3.9)

        # Column header
        shape = slide.shapes.add_shape(1, left, top, w, Inches(0.5))
        shape.fill.solid()
        shape.fill.fore_color.rgb = color
        shape.line.fill.background()
        _add_textbox(slide, left + Inches(0.1), top + Inches(0.05),
                     w - Inches(0.2), Inches(0.4),
                     title, font_size=14, bold=True, color=WHITE,
                     alignment=PP_ALIGN.CENTER)

        # Subtitle
        _add_textbox(slide, left + Inches(0.1), top + Inches(0.6),
                     w - Inches(0.2), Inches(0.35),
                     subtitle, font_size=11, bold=True, color=color)

        # Bullet points
        txBox = slide.shapes.add_textbox(left + Inches(0.15), top + Inches(1.05),
                                          w - Inches(0.3), Inches(4.5))
        tf = txBox.text_frame
        tf.word_wrap = True
        for j, item in enumerate(items):
            p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
            p.text = item
            p.font.size = Pt(10)
            p.font.color.rgb = BODY_GRAY
            p.font.name = "Calibri"
            p.space_after = Pt(8)


def slide_investment_process(prs, date_str):
    """Slide 4: Investment Process."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Investment Process", "Four-stage systematic workflow")
    _add_footer(slide, date_str)

    stages = [
        ("1. SCREEN", "Analyst Agent",
         "Claude AI screens all 81 Xover constituents against knowledge base. "
         "Outputs: direction, conviction (1-5), fair spread, catalyst, key risks."),
        ("2. MONITOR", "Filing Monitor",
         "Companies House + Investegate + EQS scraped every 15min. "
         "Claude classifies each filing by credit impact and severity."),
        ("3. CONSTRUCT", "Strategist Agent",
         "PM agent builds optimal portfolio from 81 assessments. "
         "Enforces risk limits: 5% name, 25% sector, 7.5% hard stop."),
        ("4. EXECUTE", "Morning Brief + Alerts",
         "Daily brief (PDF + Telegram) with regime, top positions, filings. "
         "Real-time alerts on material events for position adjustment."),
    ]

    for i, (title, agent, desc) in enumerate(stages):
        left = Inches(0.5) + Inches(3.15) * i
        top = Inches(1.6)
        w = Inches(2.95)

        # Number circle
        shape = slide.shapes.add_shape(9, left + Inches(0.9), top, Inches(1.1), Inches(1.1))  # oval
        shape.fill.solid()
        shape.fill.fore_color.rgb = DARK_NAVY
        shape.line.fill.background()
        _add_textbox(slide, left + Inches(0.9), top + Inches(0.15),
                     Inches(1.1), Inches(0.7),
                     title.split(".")[0] + ".", font_size=28, bold=True,
                     color=WHITE, alignment=PP_ALIGN.CENTER)

        # Title + agent
        _add_textbox(slide, left, top + Inches(1.3), w, Inches(0.35),
                     title.split(". ")[1], font_size=14, bold=True,
                     color=NAVY, alignment=PP_ALIGN.CENTER)
        _add_textbox(slide, left, top + Inches(1.65), w, Inches(0.3),
                     agent, font_size=10, color=STEEL, alignment=PP_ALIGN.CENTER)

        # Description
        _add_textbox(slide, left + Inches(0.1), top + Inches(2.1),
                     w - Inches(0.2), Inches(2.5),
                     desc, font_size=10, color=BODY_GRAY)


def slide_universe_overview(prs, assessments, date_str):
    """Slide 5: Universe Overview."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Universe Overview",
                   f"iTraxx Crossover S44 -- {len(assessments)} names screened")
    _add_footer(slide, date_str)

    longs = [a for a in assessments if a.direction == Direction.LONG_RISK]
    shorts = [a for a in assessments if a.direction == Direction.SHORT_RISK]
    flats = [a for a in assessments if a.direction == Direction.FLAT]
    avg_conv = sum(a.conviction for a in assessments) / len(assessments) if assessments else 0
    avg_spread = sum(a.current_spread for a in assessments) / len(assessments) if assessments else 0

    # Metric boxes
    metrics = [
        ("Total Names", str(len(assessments))),
        ("Long Risk", str(len(longs))),
        ("Short Risk", str(len(shorts))),
        ("Flat", str(len(flats))),
        ("Avg Conviction", f"{avg_conv:.1f}/5"),
        ("Avg Spread", f"{avg_spread:.0f}bps"),
    ]
    for i, (label, value) in enumerate(metrics):
        left = Inches(0.5) + Inches(2.05) * i
        val_color = LONG_GREEN if "Long" in label else (SHORT_RED if "Short" in label else NAVY)
        _add_metric_box(slide, left, Inches(1.5), Inches(1.9), Inches(0.9),
                        label, value, value_color=val_color, bg_color=OFF_WHITE)

    # Conviction distribution
    conv_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for a in assessments:
        conv_counts[a.conviction] = conv_counts.get(a.conviction, 0) + 1

    _add_textbox(slide, Inches(0.8), Inches(2.8), Inches(5), Inches(0.4),
                 "Conviction Distribution", font_size=14, bold=True, color=NAVY)

    conv_data = [["Conviction", "Count", "% of Universe"]]
    for c in range(5, 0, -1):
        pct = conv_counts.get(c, 0) / len(assessments) * 100 if assessments else 0
        conv_data.append([f"{c}/5", str(conv_counts.get(c, 0)), f"{pct:.0f}%"])

    _add_table(slide, Inches(0.8), Inches(3.3), Inches(4.5), conv_data,
               [Inches(1.2), Inches(1.2), Inches(2.1)])

    # Sector breakdown
    sector_map = load_sector_mapping()
    sector_counts = {}
    for a in assessments:
        sector = sector_map.get(a.entity_name, "Other")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    _add_textbox(slide, Inches(6.5), Inches(2.8), Inches(6), Inches(0.4),
                 "Sector Breakdown", font_size=14, bold=True, color=NAVY)

    sec_data = [["Sector", "Names", "Longs", "Shorts"]]
    for sector in sorted(sector_counts.keys(), key=lambda s: -sector_counts[s]):
        sector_assessments = [a for a in assessments if sector_map.get(a.entity_name) == sector]
        n_l = sum(1 for a in sector_assessments if a.direction == Direction.LONG_RISK)
        n_s = sum(1 for a in sector_assessments if a.direction == Direction.SHORT_RISK)
        sec_data.append([sector, str(sector_counts[sector]), str(n_l), str(n_s)])

    _add_table(slide, Inches(6.5), Inches(3.3), Inches(6), sec_data,
               [Inches(2.5), Inches(1.0), Inches(1.0), Inches(1.0)])


def slide_top_longs(prs, assessments, date_str):
    """Slide 6: Top 5 Longs."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Top 5 Long Risk Ideas", "Spreads trading wide of fair value")
    _add_footer(slide, date_str)

    longs = sorted(
        [a for a in assessments if a.direction == Direction.LONG_RISK],
        key=lambda a: (a.conviction, abs(a.fair_spread - a.current_spread)),
        reverse=True)[:5]

    data = [["Entity", "Conv", "Current", "Fair", "Misprice", "Thesis", "Catalyst"]]
    for a in longs:
        mispricing = a.fair_spread - a.current_spread
        data.append([
            a.entity_name[:35],
            f"{a.conviction}/5",
            f"{a.current_spread:.0f}",
            f"{a.fair_spread:.0f}",
            f"{mispricing:+.0f}",
            a.thesis[:55] + "..." if len(a.thesis) > 55 else a.thesis,
            a.catalyst[:40] + "..." if len(a.catalyst) > 40 else a.catalyst,
        ])

    _add_table(slide, Inches(0.4), Inches(1.5), Inches(12.5), data,
               [Inches(2.8), Inches(0.7), Inches(0.9), Inches(0.9), Inches(0.9),
                Inches(3.5), Inches(2.8)])


def slide_top_shorts(prs, assessments, date_str):
    """Slide 7: Top 5 Shorts."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Top 5 Short Risk Ideas", "Spreads trading tight of fair value")
    _add_footer(slide, date_str)

    shorts = sorted(
        [a for a in assessments if a.direction == Direction.SHORT_RISK],
        key=lambda a: (a.conviction, abs(a.fair_spread - a.current_spread)),
        reverse=True)[:5]

    data = [["Entity", "Conv", "Current", "Fair", "Misprice", "Thesis", "Catalyst"]]
    for a in shorts:
        mispricing = a.fair_spread - a.current_spread
        data.append([
            a.entity_name[:35],
            f"{a.conviction}/5",
            f"{a.current_spread:.0f}",
            f"{a.fair_spread:.0f}",
            f"{mispricing:+.0f}",
            a.thesis[:55] + "..." if len(a.thesis) > 55 else a.thesis,
            a.catalyst[:40] + "..." if len(a.catalyst) > 40 else a.catalyst,
        ])

    _add_table(slide, Inches(0.4), Inches(1.5), Inches(12.5), data,
               [Inches(2.8), Inches(0.7), Inches(0.9), Inches(0.9), Inches(0.9),
                Inches(3.5), Inches(2.8)])


def slide_portfolio_construction(prs, portfolio, date_str):
    """Slide 8: Portfolio Construction."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    risk = portfolio.get("risk_summary", {})
    nav = portfolio.get("nav_millions", 500)
    _add_title_bar(slide, "Portfolio Construction",
                   f"${nav:.0f}M NAV | Top 10 Positions")
    _add_footer(slide, date_str)

    # Risk metrics
    metrics = [
        ("Gross", f'{risk.get("gross_exposure_pct", 0):.0f}%'),
        ("Net", f'{risk.get("net_exposure_pct", 0):+.0f}%'),
        ("Longs", f'{risk.get("long_exposure_pct", 0):.0f}%'),
        ("Shorts", f'{risk.get("short_exposure_pct", 0):.0f}%'),
        ("Positions", str(risk.get("position_count", 10))),
        ("Carry", f'{risk.get("estimated_carry_bps", 0):.0f}bp'),
    ]
    for i, (label, value) in enumerate(metrics):
        left = Inches(0.4) + Inches(2.1) * i
        _add_metric_box(slide, left, Inches(1.4), Inches(1.95), Inches(0.85),
                        label, value, bg_color=OFF_WHITE)

    # Positions table
    positions = portfolio.get("top_positions", [])
    data = [["#", "Entity", "Dir", "Size%", "Spread", "Fair", "Rating", "Thesis"]]
    for p in positions:
        dir_tag = "L" if p.get("direction") == "LONG_RISK" else "S"
        data.append([
            str(p.get("rank", "")),
            p.get("entity_name", "")[:30],
            dir_tag,
            f'{abs(p.get("size_pct", 0)):.1f}%',
            f'{p.get("current_spread", 0):.0f}',
            f'{p.get("fair_spread", 0):.0f}',
            p.get("estimated_rating", ""),
            p.get("thesis", "")[:50],
        ])

    _add_table(slide, Inches(0.3), Inches(2.6), Inches(12.7), data,
               [Inches(0.4), Inches(2.5), Inches(0.5), Inches(0.8),
                Inches(0.8), Inches(0.8), Inches(0.8), Inches(5.6)])


def slide_sector_allocation(prs, portfolio, date_str):
    """Slide 9: Sector & Rating Allocation."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Allocation", "Sector concentration and rating buckets")
    _add_footer(slide, date_str)

    # Sector table (left)
    _add_textbox(slide, Inches(0.8), Inches(1.5), Inches(5), Inches(0.4),
                 "Sector Allocation (% of Gross Exposure)", font_size=14,
                 bold=True, color=NAVY)

    sec_data = [["Sector", "Allocation", "Limit", "Headroom"]]
    for sector, pct in sorted(portfolio.get("sector_allocation", {}).items(),
                               key=lambda x: -x[1]):
        headroom = 25.0 - pct
        flag = " (!)" if headroom < 0 else ""
        sec_data.append([sector, f"{pct:.1f}%", "25.0%", f"{headroom:+.1f}%{flag}"])

    _add_table(slide, Inches(0.8), Inches(2.0), Inches(5.5), sec_data,
               [Inches(2.0), Inches(1.2), Inches(1.0), Inches(1.3)])

    # Rating buckets (right)
    _add_textbox(slide, Inches(7.0), Inches(1.5), Inches(5), Inches(0.4),
                 "Rating Bucket Allocation", font_size=14, bold=True, color=NAVY)

    rat_data = [["Rating", "Allocation"]]
    for bucket, pct in sorted(portfolio.get("rating_buckets", {}).items()):
        rat_data.append([bucket, f"{pct:.1f}%"])

    _add_table(slide, Inches(7.0), Inches(2.0), Inches(3.5), rat_data,
               [Inches(1.5), Inches(2.0)])

    # Net bias section
    net_bias = portfolio.get("net_bias", {})
    _add_textbox(slide, Inches(0.8), Inches(4.8), Inches(5), Inches(0.4),
                 "Directional Bias", font_size=14, bold=True, color=NAVY)
    _add_textbox(slide, Inches(0.8), Inches(5.3), Inches(11), Inches(0.4),
                 f'{net_bias.get("direction", "?")} | '
                 f'Net: {net_bias.get("net_exposure_pct", 0):+.0f}%',
                 font_size=13, bold=True, color=DARK_NAVY)
    _add_textbox(slide, Inches(0.8), Inches(5.8), Inches(11), Inches(0.8),
                 net_bias.get("reasoning", ""),
                 font_size=11, color=BODY_GRAY)


def slide_pair_trades(prs, portfolio, assessments, date_str):
    """Slide 10: Pair Trades -- RV-sourced from relative value screener."""
    from analytics.relative_value import run_full_analysis

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Pair Trades",
                   "Quantitative relative value -- sector z-score + rating z-score + momentum")
    _add_footer(slide, date_str)

    # Run full RV analysis to get scored pairs
    try:
        rv_names, rv_pairs = run_full_analysis()
    except Exception:
        rv_names, rv_pairs = [], []

    if rv_pairs:
        # Show top 5 RV-sourced pairs
        _add_textbox(slide, Inches(0.5), Inches(1.35), Inches(8), Inches(0.3),
                     "Top Relative Value Pair Trades (ranked by composite score differential)",
                     font_size=11, bold=True, color=NAVY)

        data = [["#", "Cheap Leg (Buy Prot)", "Score", "Rich Leg (Sell Prot)",
                 "Score", "Sector", "Spread Diff"]]
        for i, p in enumerate(rv_pairs[:5], 1):
            data.append([
                str(i),
                p.cheap_name[:28],
                f"{p.cheap_score:+.2f}",
                p.rich_name[:28],
                f"{p.rich_score:+.2f}",
                p.sector[:16],
                f"{p.spread_diff:+.0f}bp",
            ])

        _add_table(slide, Inches(0.5), Inches(1.7), Inches(12.3), data,
                   [Inches(0.4), Inches(2.8), Inches(0.8), Inches(2.8),
                    Inches(0.8), Inches(1.8), Inches(1.1)])

        # RV universe summary
        cheap_count = sum(1 for n in rv_names if "CHEAP" in n.rv_signal.upper())
        rich_count = sum(1 for n in rv_names if "RICH" in n.rv_signal.upper())
        fair_count = sum(1 for n in rv_names if n.rv_signal == "FAIR")

        summary_text = (
            f"Universe: {len(rv_names)} names scored  |  "
            f"{cheap_count} CHEAP  |  {rich_count} RICH  |  {fair_count} FAIR"
        )
        _add_textbox(slide, Inches(0.5), Inches(4.0), Inches(12.3), Inches(0.35),
                     summary_text, font_size=10, color=STEEL)

        # Key insight box
        if rv_pairs:
            top = rv_pairs[0]
            insight = (
                f"Strongest signal: {top.cheap_name[:25]} ({top.cheap_spread:.0f}bp) "
                f"vs {top.rich_name[:25]} ({top.rich_spread:.0f}bp) -- "
                f"composite differential {top.composite_diff:+.2f}"
            )
            box = slide.shapes.add_shape(
                1, Inches(0.5), Inches(4.5), Inches(12.3), Inches(0.6))
            box.fill.solid()
            box.fill.fore_color.rgb = RGBColor(0xE8, 0xF5, 0xE9)
            box.line.fill.background()
            _add_textbox(slide, Inches(0.7), Inches(4.55), Inches(11.9), Inches(0.45),
                         insight, font_size=11, bold=True, color=LONG_GREEN)

    else:
        # Fallback to strategist pairs
        pairs = portfolio.get("pair_trades", [])
        data = [["Long Leg", "Short Leg", "Spread Diff", "Rationale"]]
        for p in pairs:
            data.append([
                p.get("long_name", "")[:30],
                p.get("short_name", "")[:30],
                f'{p.get("spread_differential", 0):.0f}bps',
                p.get("rationale", "")[:70],
            ])
        if len(data) > 1:
            _add_table(slide, Inches(0.5), Inches(1.6), Inches(12.3), data,
                       [Inches(2.8), Inches(2.8), Inches(1.2), Inches(5.5)])


def slide_hedges(prs, portfolio, date_str):
    """Slide 11: Hedging Strategy."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Hedging Strategy", "Index, tranche, and single-name hedges")
    _add_footer(slide, date_str)

    hedges = portfolio.get("hedges", [])
    data = [["Instrument", "Direction", "Notional $M", "Rationale"]]
    for h in hedges:
        data.append([
            h.get("instrument", ""),
            h.get("direction", "").replace("_", " "),
            f'${abs(h.get("notional_millions", 0)):.1f}M',
            h.get("rationale", "")[:80],
        ])

    if len(data) > 1:
        _add_table(slide, Inches(0.5), Inches(1.6), Inches(12.3), data,
                   [Inches(2.5), Inches(1.5), Inches(1.5), Inches(6.8)])


def slide_tranche_analytics(prs, portfolio, assessments, date_str):
    """Slide 12: Tranche Analytics -- Convexity Edge."""
    from analytics.tranche_pricer import (
        price_tranche,
        tranche_strategy_analysis,
        STANDARD_TRANCHES,
    )
    from analytics.cds_pricer import _risky_annuity as cds_rpv01

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Tranche Analytics -- Convexity Edge",
                   "Gaussian copula pricing of standard iTraxx Xover tranches")
    _add_footer(slide, date_str)

    # Compute weighted average index spread from assessments
    total_spread = sum(a.current_spread for a in assessments if a.current_spread)
    count = sum(1 for a in assessments if a.current_spread)
    avg_spread = total_spread / count if count > 0 else 350.0

    # Base correlations (standard market levels)
    rho_eq, rho_mz, rho_sn = 0.25, 0.45, 0.65

    # Price all three tranches
    eq = price_tranche(0.00, 0.10, avg_spread, rho_eq, notional=10_000_000,
                       running_coupon_bps=500)
    mz = price_tranche(0.10, 0.25, avg_spread, rho_mz, notional=10_000_000)
    sn = price_tranche(0.25, 1.00, avg_spread, rho_sn, notional=10_000_000)

    # ---- Section 1: Tranche summary table ----
    _add_textbox(slide, Inches(0.5), Inches(1.35), Inches(6), Inches(0.35),
                 f"Standard Xover Tranches (Index @ {avg_spread:.0f}bps)",
                 font_size=12, bold=True, color=NAVY)

    tranche_data = [
        ["Tranche", "Attach", "EL%", "Fair Spread", "Upfront", "Delta", "Gamma", "Leverage"],
        ["0-10% Equity", "0-10%", f"{eq.expected_loss_pct:.1f}%",
         f"{eq.fair_spread_bps:.0f}bp", f"{eq.upfront_pct:.0f}%+500r",
         f"{eq.delta:.1f}", f"{eq.gamma:.2f}", f"{eq.leverage:.0f}x"],
        ["10-25% Mezz", "10-25%", f"{mz.expected_loss_pct:.1f}%",
         f"{mz.fair_spread_bps:.0f}bp", "--",
         f"{mz.delta:.1f}", f"{mz.gamma:.2f}", f"{mz.leverage:.0f}x"],
        ["25-100% Senior", "25-100%", f"{sn.expected_loss_pct:.1f}%",
         f"{sn.fair_spread_bps:.0f}bp", "--",
         f"{sn.delta:.1f}", f"{sn.gamma:.2f}", f"{sn.leverage:.0f}x"],
    ]
    _add_table(slide, Inches(0.5), Inches(1.75), Inches(8.0), tranche_data,
               [Inches(1.4), Inches(0.8), Inches(0.7), Inches(1.1),
                Inches(1.1), Inches(0.7), Inches(0.8), Inches(1.0)])

    # ---- Section 2: Convexity P&L grid ----
    _add_textbox(slide, Inches(0.5), Inches(3.35), Inches(6), Inches(0.35),
                 "Combined Hedge P&L -- Convexity Demonstration",
                 font_size=12, bold=True, color=NAVY)

    # Get hedge positions from portfolio
    hedges = portfolio.get("hedges", [])
    idx_notional = 0.0
    tranche_notional = 0.0
    tranche_name = "mezzanine"
    idx_is_long = True

    for h in hedges:
        inst = h.get("instrument", "").lower()
        if "tranche" in inst or "equity" in inst:
            tranche_notional = h["notional_millions"] * 1_000_000
            if "equity" in inst or "0-10" in inst:
                tranche_name = "equity"
            else:
                tranche_name = "mezzanine"
        elif "index" in inst:
            idx_notional = h["notional_millions"] * 1_000_000
            idx_is_long = h["direction"] == "LONG_RISK"

    # Default if no hedges
    if tranche_notional == 0:
        tranche_notional = 15_000_000
    if idx_notional == 0:
        idx_notional = 30_000_000

    # Compute P&L for each bump
    bumps = [-50, +50, +100, +200]
    tranche_def = STANDARD_TRANCHES[tranche_name]
    rho_map = {"equity": rho_eq, "mezzanine": rho_mz, "senior": rho_sn}
    rho = rho_map[tranche_name]
    running = tranche_def["coupon_bps"]
    att = tranche_def["attachment"]
    det = tranche_def["detachment"]

    base_analytics = price_tranche(att, det, avg_spread, rho,
                                   notional=tranche_notional,
                                   running_coupon_bps=running)
    base_mtm = base_analytics.mtm
    rpv01 = cds_rpv01(avg_spread)
    idx_dv01 = idx_notional * rpv01 / 10_000

    idx_pnl_row = ["Index hedge ($30M long)"]
    trn_pnl_row = [f"Tranche hedge (${tranche_notional/1e6:.0f}M {tranche_name})"]
    combined_row = ["COMBINED"]

    for bump in bumps:
        new_spread = max(1.0, avg_spread + bump)
        bumped = price_tranche(att, det, new_spread, rho,
                               notional=tranche_notional,
                               running_coupon_bps=running)
        t_pnl = bumped.mtm - base_mtm  # Protection buyer gains on widening
        i_pnl = idx_dv01 * bump * (-1 if idx_is_long else 1)
        c_pnl = t_pnl + i_pnl

        sign_t = "+" if t_pnl >= 0 else ""
        sign_i = "+" if i_pnl >= 0 else ""
        sign_c = "+" if c_pnl >= 0 else ""
        idx_pnl_row.append(f"${sign_i}{i_pnl/1000:.0f}k")
        trn_pnl_row.append(f"${sign_t}{t_pnl/1000:.0f}k")
        combined_row.append(f"${sign_c}{c_pnl/1000:.0f}k")

    bump_headers = ["Position"] + [f"{b:+d}bp" for b in bumps]
    pnl_data = [bump_headers, idx_pnl_row, trn_pnl_row, combined_row]
    _add_table(slide, Inches(0.5), Inches(3.75), Inches(8.0), pnl_data,
               [Inches(3.2), Inches(1.2), Inches(1.2), Inches(1.2), Inches(1.2)])

    # Highlight combined row with green/red
    # (handled by table styling - bold row label is sufficient)

    # ---- Section 3: Key delta/convexity metrics ----
    _add_textbox(slide, Inches(9.0), Inches(1.35), Inches(4), Inches(0.35),
                 "Key Risk Metrics", font_size=12, bold=True, color=NAVY)

    metrics = [
        ("Equity Delta", f"{eq.delta:.1f}x"),
        ("Equity Leverage", f"{eq.leverage:.0f}x"),
        ("Mezz Delta", f"{mz.delta:.1f}x"),
        ("Mezz Leverage", f"{mz.leverage:.0f}x"),
        ("Index Spread", f"{avg_spread:.0f}bps"),
        ("Portfolio Names", f"{count}"),
    ]
    for i, (label, val) in enumerate(metrics):
        row_y = Inches(1.8) + Inches(0.4) * i
        _add_textbox(slide, Inches(9.0), row_y, Inches(2.2), Inches(0.35),
                     label, font_size=10, bold=True, color=STEEL)
        _add_textbox(slide, Inches(11.2), row_y, Inches(1.8), Inches(0.35),
                     val, font_size=10, bold=True, color=DARK_NAVY)

    # ---- Section 4: Convexity callout ----
    # Compute convexity ratio
    bumped_50 = price_tranche(att, det, avg_spread + 50, rho,
                              notional=tranche_notional,
                              running_coupon_bps=running)
    bumped_100 = price_tranche(att, det, avg_spread + 100, rho,
                               notional=tranche_notional,
                               running_coupon_bps=running)
    pnl_50 = bumped_50.mtm - base_mtm
    pnl_100 = bumped_100.mtm - base_mtm
    convexity_ratio = pnl_100 / pnl_50 if pnl_50 != 0 else 0

    convexity_box = slide.shapes.add_shape(
        1, Inches(9.0), Inches(4.2), Inches(4.0), Inches(0.8))
    convexity_box.fill.solid()
    convexity_box.fill.fore_color.rgb = RGBColor(0xE8, 0xF5, 0xE9)
    convexity_box.line.fill.background()
    _add_textbox(slide, Inches(9.1), Inches(4.25), Inches(3.8), Inches(0.35),
                 f"Convexity: +100bp gains {convexity_ratio:.1f}x the +50bp gains",
                 font_size=11, bold=True, color=LONG_GREEN)
    _add_textbox(slide, Inches(9.1), Inches(4.6), Inches(3.8), Inches(0.3),
                 "Gains accelerate on widening",
                 font_size=10, color=STEEL)

    # ---- Key message at bottom ----
    msg_box = slide.shapes.add_shape(
        1, Inches(0.5), Inches(5.5), Inches(12.3), Inches(1.2))
    msg_box.fill.solid()
    msg_box.fill.fore_color.rgb = DARK_NAVY
    msg_box.line.fill.background()
    _add_textbox(slide, Inches(0.7), Inches(5.6), Inches(11.9), Inches(0.45),
                 "Tranches provide convex hedging unavailable in bonds",
                 font_size=14, bold=True, color=WHITE, alignment=PP_ALIGN.CENTER)
    _add_textbox(slide, Inches(0.7), Inches(6.1), Inches(11.9), Inches(0.45),
                 "Gains accelerate as spreads widen, providing asymmetric risk/reward "
                 "for tail scenarios. This is the core structural edge of the tranche franchise.",
                 font_size=11, color=LIGHT_STEEL, alignment=PP_ALIGN.CENTER)


def slide_stress_scenarios(prs, portfolio, date_str):
    """Slide 13: Stress Scenarios."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Stress Scenarios", "Three downside/upside scenarios with P&L impact")
    _add_footer(slide, date_str)

    stress = portfolio.get("stress_scenarios", [])
    for i, s in enumerate(stress):
        left = Inches(0.5) + Inches(4.1) * i
        top = Inches(1.6)
        w = Inches(3.9)

        pnl_bps = s.get("estimated_pnl_bps", 0)
        pnl_m = s.get("estimated_pnl_millions", 0)
        color = SHORT_RED if pnl_bps < 0 else LONG_GREEN

        # Header box
        shape = slide.shapes.add_shape(1, left, top, w, Inches(0.6))
        shape.fill.solid()
        shape.fill.fore_color.rgb = color
        shape.line.fill.background()
        _add_textbox(slide, left + Inches(0.1), top + Inches(0.1),
                     w - Inches(0.2), Inches(0.4),
                     s.get("scenario", ""), font_size=13, bold=True,
                     color=WHITE, alignment=PP_ALIGN.CENTER)

        # P&L metrics
        _add_textbox(slide, left, top + Inches(0.8), w, Inches(0.5),
                     f"{pnl_bps:+.0f} bps", font_size=28, bold=True,
                     color=color, alignment=PP_ALIGN.CENTER)
        _add_textbox(slide, left, top + Inches(1.4), w, Inches(0.4),
                     f"${pnl_m:+.1f}M", font_size=18, bold=True,
                     color=color, alignment=PP_ALIGN.CENTER)

        # Description
        _add_textbox(slide, left + Inches(0.15), top + Inches(2.0),
                     w - Inches(0.3), Inches(3.0),
                     s.get("description", ""), font_size=11, color=BODY_GRAY)


def slide_risk_limits(prs, portfolio, snapshot, date_str):
    """Slide 14: Risk Limits & Compliance."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Risk Limits & Compliance", "Hard constraints and current utilisation")
    _add_footer(slide, date_str)

    risk = portfolio.get("risk_summary", {})

    limits = [
        ("Max Single Name", "5.0%", f'{risk.get("largest_position_pct", 0):.1f}%',
         risk.get("largest_position_pct", 0) <= 5.0),
        ("Max Sector", "25.0%",
         f'{max(portfolio.get("sector_allocation", {}).values(), default=0):.1f}%',
         max(portfolio.get("sector_allocation", {}).values(), default=0) <= 25.0),
        ("Min Positions", "10", str(risk.get("position_count", 0)),
         risk.get("position_count", 0) >= 10),
        ("Gross Exposure", "80-200%", f'{risk.get("gross_exposure_pct", 0):.0f}%',
         80 <= risk.get("gross_exposure_pct", 0) <= 200),
        ("Net Exposure", "-30% to +50%", f'{risk.get("net_exposure_pct", 0):+.0f}%',
         -30 <= risk.get("net_exposure_pct", 0) <= 50),
        ("Review Trigger", "5% DD", f'{snapshot.get("current_drawdown", 0):.1f}%',
         snapshot.get("current_drawdown", 0) < 5.0),
        ("Hard Stop", "7.5% DD", f'{snapshot.get("current_drawdown", 0):.1f}%',
         snapshot.get("current_drawdown", 0) < 7.5),
    ]

    data = [["Risk Limit", "Limit", "Current", "Status"]]
    for name, limit_val, current_val, ok in limits:
        status = "PASS" if ok else "BREACH"
        data.append([name, limit_val, current_val, status])

    _add_table(slide, Inches(1.5), Inches(1.6), Inches(10), data,
               [Inches(2.5), Inches(2.0), Inches(2.0), Inches(2.0)])


def slide_key_risks(prs, portfolio, date_str):
    """Slide 15: Key Portfolio Risks."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Key Portfolio Risks")
    _add_footer(slide, date_str)

    key_risks = portfolio.get("key_risks", [])
    txBox = slide.shapes.add_textbox(Inches(0.8), Inches(1.6), Inches(11.5), Inches(5.0))
    tf = txBox.text_frame
    tf.word_wrap = True

    for i, risk_text in enumerate(key_risks):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"{i+1}. {risk_text}"
        p.font.size = Pt(14)
        p.font.color.rgb = BODY_GRAY
        p.font.name = "Calibri"
        p.space_after = Pt(14)


def slide_filing_monitor(prs, filings, date_str):
    """Slide 16: Recent Filing Activity."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Filing Monitor", "Recent regulatory events (last 7 days)")
    _add_footer(slide, date_str)

    if filings:
        data = [["Entity", "Source", "Impact", "Sev", "Summary"]]
        for f in filings[:10]:
            data.append([
                f.get("matched_entity", "")[:25],
                f.get("source", "")[:15],
                f.get("credit_impact", "?").upper(),
                str(f.get("severity", 0)),
                (f.get("credit_summary", "") or f.get("headline", ""))[:55],
            ])
        _add_table(slide, Inches(0.3), Inches(1.5), Inches(12.7), data,
                   [Inches(2.2), Inches(1.5), Inches(1.0), Inches(0.6), Inches(7.0)])
    else:
        _add_textbox(slide, Inches(2), Inches(3.5), Inches(9), Inches(1),
                     "No material filings detected in the last 7 days.",
                     font_size=18, color=STEEL, alignment=PP_ALIGN.CENTER)


def slide_knowledge_base(prs, date_str):
    """Slide 17: Knowledge Base."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Knowledge Base", "848 indexed chunks across 39 reference texts")
    _add_footer(slide, date_str)

    categories = [
        ("Credit Analysis", "19 documents", "Covenants, distressed exchanges, debt ranking, "
         "maturities, CLOs, coupons, valuations (Moyer), amendments, new issues, "
         "financial analysis, business trends, RV analysis"),
        ("Options & Technical", "3 documents", "Natenberg (volatility/pricing), "
         "Grimes (technical analysis), Coulling (volume-price)"),
        ("Trading Psychology", "4 documents", "Duke (probabilistic thinking), "
         "Schwager (Market Wizards), mindfulness-based trading, ideal mindset"),
        ("GenAI / Quant", "12 documents", "LLM sentiment analysis, deep generative models, "
         "flow models, GANs, efficient inference, no-code quant strategies"),
        ("System Design", "2 documents", "Narang (quantitative systems), "
         "Chan (quantitative trading & backtesting)"),
    ]

    for i, (title, count, desc) in enumerate(categories):
        top = Inches(1.5) + Inches(1.05) * i
        # Title
        _add_textbox(slide, Inches(0.8), top, Inches(3), Inches(0.35),
                     f"{title} ({count})", font_size=13, bold=True, color=NAVY)
        # Description
        _add_textbox(slide, Inches(4.0), top, Inches(8.5), Inches(0.9),
                     desc, font_size=10, color=BODY_GRAY)


def slide_technology_stack(prs, date_str):
    """Slide 18: Technology Stack."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Technology Stack")
    _add_footer(slide, date_str)

    components = [
        ("Claude Sonnet 4.5", "Core AI engine for credit analysis, filing classification, "
         "and portfolio construction"),
        ("Knowledge Retriever", "TF-IDF indexed 848 chunks with cosine similarity search "
         "(sklearn, bigram features)"),
        ("Filing Monitor", "Companies House API + Investegate + EQS scraper with SQLite "
         "dedup and Claude classification"),
        ("Pydantic Models", "Type-safe data flow: CreditAssessment -> TradeIdea -> "
         "RiskSnapshot -> TradeJournal"),
        ("Output Pipeline", "Excel (openpyxl), PDF (reportlab), PowerPoint (python-pptx), "
         "Telegram (aiohttp)"),
        ("Knowledge Base", "39 reference texts processed into 848 JSON chunks with "
         "topic tagging and metadata"),
    ]

    for i, (title, desc) in enumerate(components):
        top = Inches(1.5) + Inches(0.9) * i
        _add_textbox(slide, Inches(0.8), top, Inches(3.5), Inches(0.35),
                     title, font_size=13, bold=True, color=NAVY)
        _add_textbox(slide, Inches(4.5), top, Inches(8), Inches(0.8),
                     desc, font_size=11, color=BODY_GRAY)


def slide_commentary(prs, portfolio, date_str):
    """Slide 19: PM Commentary."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, DARK_NAVY)

    _add_textbox(slide, Inches(1.5), Inches(1.5), Inches(10), Inches(0.5),
                 "Portfolio Manager Commentary", font_size=14,
                 color=LIGHT_STEEL, bold=True)

    commentary = portfolio.get("commentary", "No commentary available.")
    _add_textbox(slide, Inches(1.5), Inches(2.3), Inches(10), Inches(3.0),
                 f'"{commentary}"', font_size=18, color=WHITE)

    net_bias = portfolio.get("net_bias", {})
    _add_textbox(slide, Inches(1.5), Inches(5.5), Inches(10), Inches(0.5),
                 f'Bias: {net_bias.get("direction", "?")} | '
                 f'Net: {net_bias.get("net_exposure_pct", 0):+.0f}%',
                 font_size=14, bold=True, color=AMBER)

    _add_textbox(slide, Inches(1.5), Inches(6.5), Inches(10), Inches(0.3),
                 f"Strategies in Credit | {date_str}",
                 font_size=10, color=STEEL)


def slide_portfolio_manager(prs, date_str):
    """Slide 20: Portfolio Manager Biography."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, WHITE)
    _add_title_bar(slide, "Portfolio Manager")
    _add_footer(slide, date_str)

    # Name
    _add_textbox(slide, Inches(0.8), Inches(1.5), Inches(11), Inches(0.6),
                 "Matt Bristow", font_size=28, bold=True, color=DARK_NAVY)

    # Experience headline
    _add_textbox(slide, Inches(0.8), Inches(2.2), Inches(11), Inches(0.4),
                 "28 Years Sell-Side Credit Trading", font_size=16,
                 bold=True, color=STEEL)

    # Career timeline
    career = [
        ("Bear Stearns", "Credit Trading",
         "Foundation in credit markets through Bear Stearns' proprietary credit trading desk"),
        ("Barclays Capital", "European Index Tranche Franchise Builder",
         "Built and ran the European index tranche business from scratch, combining fundamental "
         "credit analysis with quantitative structuring"),
        ("Bank of America Merrill Lynch", "Significant P&L Generation",
         "Senior credit trader delivering consistent alpha through single-name CDS and "
         "index tranche strategies across European high yield"),
    ]

    for i, (firm, role, desc) in enumerate(career):
        top = Inches(2.9) + Inches(1.15) * i

        # Firm name bar
        shape = slide.shapes.add_shape(1, Inches(0.8), top, Inches(3.5), Inches(0.4))
        shape.fill.solid()
        shape.fill.fore_color.rgb = DARK_NAVY
        shape.line.fill.background()
        _add_textbox(slide, Inches(0.9), top + Inches(0.02), Inches(3.3), Inches(0.35),
                     firm, font_size=13, bold=True, color=WHITE)

        # Role
        _add_textbox(slide, Inches(4.5), top, Inches(8), Inches(0.35),
                     role, font_size=13, bold=True, color=NAVY)

        # Description
        _add_textbox(slide, Inches(4.5), top + Inches(0.4), Inches(8), Inches(0.7),
                     desc, font_size=11, color=BODY_GRAY)

    # Expertise section
    _add_textbox(slide, Inches(0.8), Inches(6.0), Inches(3), Inches(0.4),
                 "Core Expertise", font_size=14, bold=True, color=NAVY)
    _add_textbox(slide, Inches(4.0), Inches(6.0), Inches(8.5), Inches(0.4),
                 "iTraxx indices  |  Single-name CDS  |  Index tranches  |  European HY credit",
                 font_size=12, color=BODY_GRAY)

    # Current focus
    _add_textbox(slide, Inches(0.8), Inches(6.5), Inches(3), Inches(0.4),
                 "Current Focus", font_size=14, bold=True, color=NAVY)
    _add_textbox(slide, Inches(4.0), Inches(6.5), Inches(8.5), Inches(0.4),
                 "Developing proprietary AI-assisted credit analysis technology targeting "
                 "multi-manager platforms",
                 font_size=12, color=BODY_GRAY)


def slide_disclaimer(prs, date_str):
    """Slide 21: Disclaimer."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, DARK_NAVY)

    _add_textbox(slide, Inches(1.5), Inches(1.5), Inches(10), Inches(0.5),
                 "Important Disclaimers", font_size=20, bold=True, color=WHITE)

    disclaimer_text = (
        "This document is strictly confidential and intended solely for the recipient. "
        "It does not constitute investment advice, a solicitation, or an offer to buy or sell "
        "any financial instruments. Past performance is not indicative of future results.\n\n"
        "All credit assessments are generated using AI-assisted analysis (Claude by Anthropic) "
        "augmented by a proprietary knowledge base. Spread estimates, fair values, and stress "
        "scenario P&L figures are model-derived and should not be relied upon as market prices.\n\n"
        "The strategy involves trading credit default swaps which carry significant risks including "
        "counterparty risk, basis risk, liquidity risk, and the potential for total loss of invested capital. "
        "CDS trading is only suitable for qualified institutional investors.\n\n"
        "Strategies in Credit is a research and portfolio analytics platform. It does not execute trades "
        "or manage client assets. All investment decisions remain the sole responsibility of the investor."
    )

    _add_textbox(slide, Inches(1.5), Inches(2.5), Inches(10), Inches(4.5),
                 disclaimer_text, font_size=11, color=LIGHT_STEEL)


def slide_contact(prs, date_str):
    """Slide 22: Contact / Back page."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, DARK_NAVY)

    _add_textbox(slide, Inches(1.5), Inches(2.5), Inches(10), Inches(1.0),
                 "Strategies in Credit", font_size=44, bold=True, color=WHITE,
                 alignment=PP_ALIGN.CENTER)
    _add_textbox(slide, Inches(1.5), Inches(3.7), Inches(10), Inches(0.5),
                 "European Credit Relative Value", font_size=20,
                 color=LIGHT_STEEL, alignment=PP_ALIGN.CENTER)
    _add_textbox(slide, Inches(1.5), Inches(5.0), Inches(10), Inches(0.4),
                 date_str, font_size=14, color=STEEL, alignment=PP_ALIGN.CENTER)
    _add_textbox(slide, Inches(1.5), Inches(5.8), Inches(10), Inches(0.3),
                 "Confidential | For Qualified Investors Only",
                 font_size=10, color=STEEL, alignment=PP_ALIGN.CENTER)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_pitch_deck(
    assessments: list[CreditAssessment],
    portfolio: dict,
    snapshot: dict,
    filings: list[dict],
) -> str:
    """Generate the full pitch deck PPTX. Returns filepath."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%d %B %Y")
    date_file = datetime.now().strftime("%Y%m%d")
    filepath = str(OUTPUT_DIR / f"strategies_in_credit_pitch_{date_file}.pptx")

    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT

    # Build all slides
    slide_title(prs, date_str)                                    # 1
    slide_executive_summary(prs, assessments, portfolio, date_str) # 2
    slide_edge(prs, date_str)                                     # 3
    slide_investment_process(prs, date_str)                       # 4
    slide_universe_overview(prs, assessments, date_str)           # 5
    slide_top_longs(prs, assessments, date_str)                   # 6
    slide_top_shorts(prs, assessments, date_str)                  # 7
    slide_portfolio_construction(prs, portfolio, date_str)        # 8
    slide_sector_allocation(prs, portfolio, date_str)             # 9
    slide_pair_trades(prs, portfolio, assessments, date_str)       # 10
    slide_hedges(prs, portfolio, date_str)                        # 11
    slide_tranche_analytics(prs, portfolio, assessments, date_str) # 12
    slide_stress_scenarios(prs, portfolio, date_str)              # 13
    slide_risk_limits(prs, portfolio, snapshot, date_str)         # 14
    slide_key_risks(prs, portfolio, date_str)                     # 15
    slide_filing_monitor(prs, filings, date_str)                  # 16
    slide_knowledge_base(prs, date_str)                           # 17
    slide_technology_stack(prs, date_str)                         # 18
    slide_commentary(prs, portfolio, date_str)                    # 19
    slide_portfolio_manager(prs, date_str)                        # 20
    slide_disclaimer(prs, date_str)                               # 21
    slide_contact(prs, date_str)                                  # 22

    prs.save(filepath)
    return filepath


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Strategies in Credit Pitch Deck Generator")
    parser.add_argument(
        "--index", type=str, choices=["xover", "main"], default="xover",
        help="Index to load screen for (default: xover)",
    )
    parser.add_argument(
        "--screen-file", type=str, default=None,
        help="Path to specific screen Excel file",
    )
    parser.add_argument(
        "--filing-days", type=int, default=7,
        help="Days of filings to include (default: 7)",
    )
    args = parser.parse_args()

    # Load screen
    if args.screen_file:
        screen_path = args.screen_file
    else:
        screen_path = find_latest_screen(args.index)

    if not screen_path or not os.path.exists(screen_path):
        print("Error: No screen file found. Run scripts/run_universe.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading screen: {screen_path}")
    assessments = load_assessments_from_excel(screen_path)
    print(f"Loaded {len(assessments)} assessments")

    # Load portfolio
    portfolio = load_portfolio(args.index)
    if not portfolio:
        print("Warning: No portfolio found. Run agents/strategist.py first.", file=sys.stderr)
        portfolio = {"risk_summary": {}, "top_positions": [], "sector_allocation": {},
                     "rating_buckets": {}, "net_bias": {}, "key_risks": [],
                     "hedges": [], "stress_scenarios": [], "pair_trades": [],
                     "commentary": "", "nav_millions": 500}

    # Load risk snapshot
    snapshot = load_risk_snapshot()
    if not snapshot:
        snapshot = {"current_drawdown": 0.0}

    # Load filings
    filings = load_recent_filings(days=args.filing_days)
    print(f"Loaded {len(filings)} filings from last {args.filing_days} days")

    # Generate deck
    print("\nGenerating pitch deck...")
    filepath = generate_pitch_deck(assessments, portfolio, snapshot, filings)
    print(f"Pitch deck saved: {filepath}")
    print(f"Slides: 22")
    print("\nDone.")


if __name__ == "__main__":
    main()

"""
Brummer & Partners Pitch Deck Generator

Generates a clean, institutional-grade PowerPoint pitch deck focused on:
1. The Edge — why this strategy works
2. The Process — Signal → Filter → Size → Execute → Manage → Exit
3. AI Augmentation — what the platform does, how it scales the PM
4. The Universe — iTraxx S44, 200 names, live spread data
5. Skills — how credits are analysed (standard + forensic + tone)
6. Risk Framework — limits, scenarios, stress testing
7. Trade Examples — real positions with real P&L
8. The Ask — $250m, solo PM

Output: outputs/pitch/brummer_pitch_YYYYMMDD.pptx

Usage:
    python -m pitch.brummer_pitch
    python -m pitch.brummer_pitch --notional 250
"""

import csv
import json
import os
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt, Emu

OUTPUT_DIR = Path("outputs/pitch")

# ---------------------------------------------------------------------------
# Colour palette — dark, institutional, clean
# ---------------------------------------------------------------------------
DARK_NAVY = RGBColor(0x0D, 0x1B, 0x2A)
NAVY = RGBColor(0x1B, 0x28, 0x38)
STEEL = RGBColor(0x41, 0x5A, 0x77)
LIGHT_STEEL = RGBColor(0x77, 0x8D, 0xA9)
OFF_WHITE = RGBColor(0xF8, 0xF9, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BODY_GRAY = RGBColor(0x21, 0x25, 0x29)
LONG_GREEN = RGBColor(0x28, 0xA7, 0x45)
SHORT_RED = RGBColor(0xDC, 0x35, 0x45)
AMBER = RGBColor(0xFF, 0xC1, 0x07)
DIVIDER_GRAY = RGBColor(0xDE, 0xE2, 0xE6)
ACCENT_BLUE = RGBColor(0x3B, 0x82, 0xF6)
MID_GRAY = RGBColor(0x6B, 0x72, 0x80)

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

# Margins
LEFT_MARGIN = Inches(0.8)
RIGHT_MARGIN = Inches(0.8)
CONTENT_WIDTH = Inches(11.733)  # 13.333 - 0.8 - 0.8

TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_FILE = datetime.now().strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_bg(slide, color):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(slide, left, top, width, height, text, font_size=12,
                 bold=False, color=BODY_GRAY, alignment=PP_ALIGN.LEFT,
                 font_name="Calibri"):
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


def _add_para(tf, text, font_size=12, bold=False, color=BODY_GRAY,
              alignment=PP_ALIGN.LEFT, space_before=0, space_after=0,
              font_name="Calibri"):
    p = tf.add_paragraph()
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.font.name = font_name
    p.alignment = alignment
    p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    return p


def _add_rect(slide, left, top, width, height, fill_color, line=False):
    shape = slide.shapes.add_shape(1, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    if not line:
        shape.line.fill.background()
    return shape


def _title_bar(slide, title, subtitle=""):
    """Dark navy title bar across the top."""
    _add_rect(slide, Inches(0), Inches(0), SLIDE_WIDTH, Inches(1.2), DARK_NAVY)
    _add_textbox(slide, LEFT_MARGIN, Inches(0.15), Inches(10), Inches(0.5),
                 title, font_size=24, bold=True, color=WHITE)
    if subtitle:
        _add_textbox(slide, LEFT_MARGIN, Inches(0.65), Inches(10), Inches(0.4),
                     subtitle, font_size=13, color=LIGHT_STEEL)
    # Badge right
    _add_textbox(slide, Inches(10.2), Inches(0.25), Inches(2.8), Inches(0.4),
                 "MACRO CREDIT MONITOR", font_size=11, bold=True,
                 color=ACCENT_BLUE, alignment=PP_ALIGN.RIGHT)
    # Footer
    _add_textbox(slide, LEFT_MARGIN, Inches(7.0), Inches(10), Inches(0.3),
                 f"BRUMMER & PARTNERS PITCH  |  CONFIDENTIAL  |  {TODAY}",
                 font_size=8, color=LIGHT_STEEL)


def _section_divider(slide, title, subtitle=""):
    """Full navy slide with large title — section break."""
    _set_bg(slide, DARK_NAVY)
    _add_textbox(slide, LEFT_MARGIN, Inches(2.8), CONTENT_WIDTH, Inches(1.0),
                 title, font_size=36, bold=True, color=WHITE,
                 alignment=PP_ALIGN.LEFT)
    if subtitle:
        _add_textbox(slide, LEFT_MARGIN, Inches(3.8), CONTENT_WIDTH, Inches(0.6),
                     subtitle, font_size=16, color=LIGHT_STEEL)
    _add_textbox(slide, LEFT_MARGIN, Inches(7.0), Inches(10), Inches(0.3),
                 f"BRUMMER & PARTNERS PITCH  |  CONFIDENTIAL  |  {TODAY}",
                 font_size=8, color=STEEL)


def _numbered_block(slide, num, title, body, left, top, width=Inches(5.2)):
    """Numbered content block (e.g. '01  Title / body')."""
    # Number
    _add_textbox(slide, left, top, Inches(0.5), Inches(0.4),
                 f"{num:02d}", font_size=28, bold=True, color=ACCENT_BLUE)
    # Title
    _add_textbox(slide, left + Inches(0.6), top, width - Inches(0.6), Inches(0.35),
                 title, font_size=14, bold=True, color=DARK_NAVY)
    # Body
    _add_textbox(slide, left + Inches(0.6), top + Inches(0.38), width - Inches(0.6), Inches(1.2),
                 body, font_size=11, color=STEEL)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_manifest():
    path = Path("deck/deck_manifest.json")
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def load_portfolio_risk():
    path = Path("outputs/portfolio_risk_metrics.csv")
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_tranche_scenarios():
    path = Path("outputs/tranche_scenario_table.csv")
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Slide builders
# ---------------------------------------------------------------------------

def slide_title(prs):
    """Slide 1: Title page."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
    _set_bg(slide, DARK_NAVY)

    # Thin accent line
    _add_rect(slide, Inches(0.8), Inches(1.5), Inches(2.0), Inches(0.04), ACCENT_BLUE)

    _add_textbox(slide, LEFT_MARGIN, Inches(1.7), CONTENT_WIDTH, Inches(0.6),
                 "EUROPEAN MACRO CREDIT TRADING STRATEGIES",
                 font_size=30, bold=True, color=WHITE)

    _add_textbox(slide, LEFT_MARGIN, Inches(2.5), CONTENT_WIDTH, Inches(0.4),
                 "CDS  |  Bonds  |  Single Names  |  Tranches  |  Credit Options",
                 font_size=16, color=ACCENT_BLUE)

    # Divider
    _add_rect(slide, Inches(0.8), Inches(3.3), Inches(4.0), Inches(0.02), STEEL)

    _add_textbox(slide, LEFT_MARGIN, Inches(3.6), CONTENT_WIDTH, Inches(0.4),
                 "Matt Bristow", font_size=22, bold=True, color=WHITE)

    _add_textbox(slide, LEFT_MARGIN, Inches(4.1), CONTENT_WIDTH, Inches(0.4),
                 "28 Years  |  Bear Stearns  |  Barclays Capital  |  Bank of America",
                 font_size=14, color=LIGHT_STEEL)

    # Bottom
    _add_textbox(slide, LEFT_MARGIN, Inches(6.2), CONTENT_WIDTH, Inches(0.3),
                 "C O N F I D E N T I A L", font_size=10, color=STEEL)
    _add_textbox(slide, LEFT_MARGIN, Inches(6.6), CONTENT_WIDTH, Inches(0.3),
                 f"Prepared for Brummer & Partners  |  {TODAY}",
                 font_size=10, color=STEEL)


def slide_edge(prs):
    """Slide 2: THE EDGE — why this works."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "THE EDGE", "Three structural advantages in European credit")

    blocks = [
        (1, "The Information Gap Is Structural",
         "Credit documentation is dense, complex, and under-analysed. "
         "Names trade at spreads that don't reflect their true covenant risk, "
         "leverage trajectory, or restructuring probability. Post-2020 bond documents "
         "are significantly more complex -- the analysis required to understand the "
         "real risk has grown. My AI engine scales this documentation analysis across "
         "200 names simultaneously, identifying mispricings that manual processes miss."),
        (2, "The Combination Is Rare",
         "Very few people combine deep fundamental credit analysis with derivatives "
         "structuring expertise. Credit analysts find the mispricing but don't know "
         "how to express it optimally. Derivatives traders can structure but lack the "
         "fundamental insight. I do both -- 28 years building and trading credit portfolios "
         "through every major cycle, from Bear Stearns through Bank of America."),
        (3, "AI Augments Experience, Not Replaces It",
         "The platform I've built monitors 200 iTraxx names 24/7 -- scrubbing regulatory "
         "filings, analysing management tone, flagging covenant triggers, and screening "
         "for relative value. It doesn't replace judgement. It ensures I see every signal, "
         "every day, across every name. The LLM qualifies each data point for credit "
         "relevance before it reaches me."),
    ]

    for i, (num, title, body) in enumerate(blocks):
        top = Inches(1.5) + Inches(i * 1.85)
        _numbered_block(slide, num, title, body, LEFT_MARGIN, top, width=CONTENT_WIDTH)


def slide_process(prs):
    """Slide 3: THE PROCESS — Signal > Filter > Size > Execute > Manage > Exit."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "THE PROCESS",
               "Signal  >  Filter  >  Size  >  Execute  >  Manage  >  Exit")

    steps = [
        ("SIGNAL", "Monitoring system scans 200 iTraxx names for deterioration: "
         "filing anomalies, covenant triggers, earnings misses, rating actions, "
         "liquidity stress. 24/7 automated surveillance with LLM-qualified alerts."),
        ("FILTER", "Is this a real catalyst or noise? Documentation engine confirms "
         "weak covenant package -- no restricted payments cap, no portability limits. "
         "Management comment analysis reveals creditor-hostile tone and behaviour."),
        ("SIZE", "Regime-aware CS01 budgeting. CS01 of ~$16,500/bp on a $250m book "
         "is ~2% of risk budget. Aggressive in high-conviction / low-correlation. "
         "Defensive when correlation rising."),
        ("EXECUTE", "Choose instrument: single-name CDS, cash bonds, basis trades, "
         "index tranches. Selection based on liquidity, carry profile, asymmetry, "
         "and documentation risk."),
        ("MANAGE", "Daily P&L attribution, scenario stress across 8 macro environments, "
         "correlation monitoring, basis tracking. Equity implied vol as early warning. "
         "Actively adjust hedges as thesis plays out."),
        ("EXIT", "Pre-defined targets and stops from day one. Example: CDS widens "
         "to 550bps on downgrade -- 200bp x $16.5k CS01 = $3.3m P&L plus convexity. "
         "Thesis realised -- close and redeploy."),
    ]

    col_width = Inches(3.7)
    h_gap = Inches(0.15)

    for i, (label, body) in enumerate(steps):
        col = i % 3
        row = i // 3
        left = LEFT_MARGIN + col * (col_width + h_gap)
        top = Inches(1.5) + row * Inches(2.8)

        # Step number + label
        num_box = _add_textbox(slide, left, top, Inches(0.35), Inches(0.35),
                               str(i + 1), font_size=18, bold=True, color=WHITE)
        # Circle behind number
        _add_rect(slide, left, top, Inches(0.35), Inches(0.35), ACCENT_BLUE)
        _add_textbox(slide, left, top, Inches(0.35), Inches(0.35),
                     str(i + 1), font_size=16, bold=True, color=WHITE,
                     alignment=PP_ALIGN.CENTER)

        _add_textbox(slide, left + Inches(0.45), top, Inches(2.0), Inches(0.35),
                     label, font_size=14, bold=True, color=DARK_NAVY)

        _add_textbox(slide, left, top + Inches(0.45), col_width, Inches(2.0),
                     body, font_size=10, color=STEEL)


def slide_ai_platform(prs):
    """Slide 4: AI AUGMENTATION — what the platform does."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "AI-AUGMENTED PLATFORM",
               "How AI scales my process across 200 names, 24 hours a day")

    capabilities = [
        (1, "Regulatory Filing Surveillance",
         "Monitors 4 European sources in real-time: Companies House (UK), "
         "Investegate/RNS (UK), EQS News/DGAP (Germany), and AMF (France). "
         "Every filing is automatically classified by the LLM for credit impact "
         "and severity (1-5). Only material signals reach me -- noise is filtered "
         "before I see it. SEC EDGAR covered for the 14 US-listed names."),
        (2, "Forensic Credit Analysis",
         "Standard credit analysis -- leverage trends, interest coverage erosion, "
         "cash burn trajectories, maturity walls -- but with an AI layer that "
         "forensically scrutinises results. The LLM reads earnings transcripts, "
         "identifies hedging language in management comments, detects tone shifts "
         "between quarters, and flags inconsistencies between reported numbers "
         "and management narrative."),
        (3, "24-Hour News & Sentiment Lookout",
         "Continuous monitoring of news flow, social sentiment, and market signals "
         "across the full iTraxx universe. The system correlates news events with "
         "spread movements and alerts when a name is moving on news that hasn't "
         "been priced into the CDS or bond market. Telegram alerts for immediate "
         "notification."),
        (4, "Documentation & Covenant Engine",
         "AI-powered analysis of credit agreements, indentures, and restricted "
         "payment baskets. Identifies weak covenant packages, portability clauses, "
         "J.Crew blockers, and dividend recap risk. Cross-references documentation "
         "quality with leverage trajectory and management behaviour to produce a "
         "covenant risk score for each name."),
    ]

    for i, (num, title, body) in enumerate(capabilities):
        col = i % 2
        row = i // 2
        left = LEFT_MARGIN + col * Inches(5.9)
        top = Inches(1.5) + row * Inches(2.7)
        _numbered_block(slide, num, title, body, left, top, width=Inches(5.4))


def slide_skills(prs):
    """Slide 5: SKILLS — how I analyse credits."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "CREDIT ANALYSIS SKILLS",
               "Standard analysis augmented by forensic AI scrutiny")

    # Left column: Standard
    _add_textbox(slide, LEFT_MARGIN, Inches(1.5), Inches(5.5), Inches(0.35),
                 "STANDARD CREDIT ANALYSIS", font_size=14, bold=True, color=DARK_NAVY)

    standard = [
        "Leverage trends (Net Debt / EBITDA, Secured / Unsecured split)",
        "Interest coverage erosion (EBITDA / Interest, Fixed Charge Coverage)",
        "Free cash flow trajectory and cash burn rate",
        "Maturity wall analysis and refinancing risk",
        "Capital structure waterfall (secured, unsecured, subordinated)",
        "Sector dynamics and competitive positioning",
        "Sponsor behaviour and management track record",
        "Rating agency methodology and migration probability",
    ]

    tb = _add_textbox(slide, LEFT_MARGIN, Inches(1.95), Inches(5.5), Inches(4.5),
                      "", font_size=11, color=STEEL)
    tf = tb.text_frame
    tf.paragraphs[0].text = ""
    for item in standard:
        _add_para(tf, f"   {item}", font_size=10, color=STEEL,
                  space_before=3, space_after=1)

    # Right column: Forensic AI
    _add_textbox(slide, Inches(6.8), Inches(1.5), Inches(5.5), Inches(0.35),
                 "FORENSIC AI AUGMENTATION", font_size=14, bold=True, color=ACCENT_BLUE)

    forensic = [
        "Management tone analysis -- LLM reads earnings transcripts and "
        "detects hedging language, confidence shifts between quarters, "
        "and inconsistencies vs. reported numbers",
        "Balance sheet forensics -- AI identifies off-balance-sheet "
        "obligations, factoring arrangements, pension underfunding, "
        "and lease adjustments that distort reported leverage",
        "Covenant document scrubbing -- automated extraction of restricted "
        "payment baskets, portability clauses, and builder basket "
        "accumulation across 200 names simultaneously",
        "Filing anomaly detection -- flags unusual regulatory filings "
        "(dividend recaps at high leverage, unexpected charge filings, "
        "covenant resets) that precede spread moves",
        "Cross-referencing -- AI correlates management claims with "
        "actual filings, cash flow statements, and peer comparisons "
        "to identify names where the story doesn't match the numbers",
    ]

    tb2 = _add_textbox(slide, Inches(6.8), Inches(1.95), Inches(5.5), Inches(4.8),
                       "", font_size=11, color=STEEL)
    tf2 = tb2.text_frame
    tf2.paragraphs[0].text = ""
    for item in forensic:
        _add_para(tf2, f"   {item}", font_size=10, color=STEEL,
                  space_before=4, space_after=2)


def slide_universe(prs, manifest):
    """Slide 6: THE UNIVERSE — iTraxx S44 spread data."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "THE UNIVERSE", "iTraxx Europe S44 -- 200 names")

    snap = manifest.get("spread_snapshot", {})
    main = snap.get("main", {})
    xover = snap.get("xover", {})

    # LEFT: Main
    _add_rect(slide, LEFT_MARGIN, Inches(1.5), Inches(5.5), Inches(0.4), NAVY)
    _add_textbox(slide, Inches(0.9), Inches(1.5), Inches(5.3), Inches(0.4),
                 f"iTraxx Main -- {main.get('count', 125)} names",
                 font_size=14, bold=True, color=WHITE)

    stats = (f"{main.get('avg_spread_bp', 53)}bp avg  |  "
             f"{main.get('median_spread_bp', 46)}bp median  |  "
             f"{main.get('min_spread_bp', 20)}-{main.get('max_spread_bp', 167)}bp range")
    _add_textbox(slide, LEFT_MARGIN, Inches(2.05), Inches(5.5), Inches(0.3),
                 stats, font_size=11, color=STEEL)

    _add_textbox(slide, LEFT_MARGIN, Inches(2.45), Inches(5.5), Inches(0.3),
                 "Widest spreads:", font_size=11, bold=True, color=DARK_NAVY)

    widest_main = main.get("widest_5", [])
    tb = _add_textbox(slide, LEFT_MARGIN, Inches(2.8), Inches(5.5), Inches(2.5),
                      "", font_size=11, color=STEEL)
    tf = tb.text_frame
    tf.paragraphs[0].text = ""
    for w in widest_main:
        _add_para(tf, f"   {w['name']:<35s} {w['spread']}bp",
                  font_size=11, color=STEEL, space_before=2, font_name="Consolas")

    # Spread distribution
    dist = main.get("distribution", {})
    _add_textbox(slide, LEFT_MARGIN, Inches(4.8), Inches(5.5), Inches(0.3),
                 "Distribution:", font_size=11, bold=True, color=DARK_NAVY)
    dist_text = "  |  ".join([f"{k}: {v}" for k, v in dist.items()])
    _add_textbox(slide, LEFT_MARGIN, Inches(5.15), Inches(5.5), Inches(0.4),
                 dist_text, font_size=9, color=MID_GRAY)

    # RIGHT: Crossover
    _add_rect(slide, Inches(6.8), Inches(1.5), Inches(5.5), Inches(0.4), SHORT_RED)
    _add_textbox(slide, Inches(6.9), Inches(1.5), Inches(5.3), Inches(0.4),
                 f"iTraxx Crossover -- {xover.get('count', 75)} names",
                 font_size=14, bold=True, color=WHITE)

    stats_x = (f"{xover.get('avg_spread_bp', 250)}bp avg  |  "
               f"{xover.get('median_spread_bp', 195)}bp median  |  "
               f"{xover.get('min_spread_bp', 50)}-{xover.get('max_spread_bp', 1224)}bp range")
    _add_textbox(slide, Inches(6.8), Inches(2.05), Inches(5.5), Inches(0.3),
                 stats_x, font_size=11, color=STEEL)

    _add_textbox(slide, Inches(6.8), Inches(2.45), Inches(5.5), Inches(0.3),
                 "Widest spreads:", font_size=11, bold=True, color=DARK_NAVY)

    widest_xover = xover.get("widest_5", [])
    tb2 = _add_textbox(slide, Inches(6.8), Inches(2.8), Inches(5.5), Inches(2.5),
                       "", font_size=11, color=STEEL)
    tf2 = tb2.text_frame
    tf2.paragraphs[0].text = ""
    for w in widest_xover:
        pts = f" ({w['pts_upfront']}pts)" if 'pts_upfront' in w else ""
        _add_para(tf2, f"   {w['name']:<35s} {w['spread']}bp{pts}",
                  font_size=11, color=STEEL, space_before=2, font_name="Consolas")

    upfront = xover.get("names_trading_upfront", 4)
    _add_textbox(slide, Inches(6.8), Inches(4.8), Inches(5.5), Inches(0.6),
                 f"{upfront} names trading points upfront -- distressed pricing. "
                 "These are the opportunities the monitoring system catches early.",
                 font_size=11, color=DARK_NAVY, bold=True)


def slide_portfolio(prs, positions):
    """Slide 7: PORTFOLIO EXAMPLE — real positions with risk."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "PORTFOLIO CONSTRUCTION",
               "Example portfolio on $250m book -- live positions with risk metrics")

    if not positions:
        _add_textbox(slide, LEFT_MARGIN, Inches(2.0), CONTENT_WIDTH, Inches(1.0),
                     "No portfolio data available.", font_size=14, color=STEEL)
        return

    # Table header
    headers = ["Name", "Dir", "Size %", "Notl $M", "Spread", "CS01", "JTD",
               "Carry p.a.", "Stress +100bp", "Stress +200bp"]
    col_widths = [Inches(1.8), Inches(0.7), Inches(0.7), Inches(0.8), Inches(0.7),
                  Inches(0.9), Inches(1.2), Inches(0.9), Inches(1.2), Inches(1.2)]
    n_cols = len(headers)
    n_rows = min(len(positions), 12)  # max 11 positions + total

    table_shape = slide.shapes.add_table(
        n_rows + 1, n_cols,
        LEFT_MARGIN, Inches(1.5),
        sum(w for w in col_widths), Inches(0.35) * (n_rows + 1)
    )
    table = table_shape.table

    # Style header
    for j, (header, width) in enumerate(zip(headers, col_widths)):
        table.columns[j].width = width
        cell = table.cell(0, j)
        cell.text = header
        for paragraph in cell.text_frame.paragraphs:
            paragraph.font.size = Pt(9)
            paragraph.font.bold = True
            paragraph.font.color.rgb = WHITE
            paragraph.font.name = "Calibri"
            paragraph.alignment = PP_ALIGN.CENTER
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_NAVY

    # Data rows
    for i, pos in enumerate(positions[:n_rows]):
        if pos.get("Name", "") == "PORTFOLIO TOTAL":
            row_color = NAVY
            font_color = WHITE
            bold = True
        else:
            row_color = OFF_WHITE if i % 2 == 0 else WHITE
            font_color = BODY_GRAY
            bold = False

        values = [
            pos.get("Name", ""),
            pos.get("Direction", ""),
            pos.get("Size_pct", ""),
            pos.get("Notional_M", ""),
            pos.get("Spread_bps", ""),
            pos.get("CS01", ""),
            pos.get("JTD", ""),
            pos.get("Carry_pa", ""),
            pos.get("StressPnL_+100bp", ""),
            pos.get("StressPnL_+200bp", ""),
        ]

        for j, val in enumerate(values):
            cell = table.cell(i + 1, j)
            cell.text = str(val)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.font.size = Pt(8)
                paragraph.font.bold = bold
                paragraph.font.name = "Consolas"
                paragraph.alignment = PP_ALIGN.CENTER if j > 0 else PP_ALIGN.LEFT
                # Colour code direction and P&L
                if j == 1:
                    paragraph.font.color.rgb = (SHORT_RED if val == "LONG"
                                                else LONG_GREEN if val == "SHORT"
                                                else font_color)
                elif "+" in str(val) and j >= 8:
                    paragraph.font.color.rgb = LONG_GREEN
                elif "-" in str(val) and j >= 8:
                    paragraph.font.color.rgb = SHORT_RED
                else:
                    paragraph.font.color.rgb = font_color
            cell.fill.solid()
            cell.fill.fore_color.rgb = row_color


def slide_risk_framework(prs):
    """Slide 8: RISK ARCHITECTURE — limits and actions."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "RISK ARCHITECTURE",
               "Hard limits, scenario tools, and worst-case gating")

    limits = [
        ("Daily Stop-Loss", "1.0%", "Flatten all positions; review before resuming"),
        ("Weekly Stop-Loss", "2.0%", "50% risk reduction; regime reassessment"),
        ("Monthly Drawdown", "3.5%", "Reduce to 25% risk; CIO approval to rebuild"),
        ("Max Peak-to-Trough", "5.0%", "Full de-risk; strategy review with risk committee"),
        ("Single-Name Conc.", "5%", "Hard limit -- no exceptions"),
        ("Liquidity Test", "90% in 5 days", "Ongoing monitoring -- portfolio must be liquidatable"),
    ]

    # Table
    table_shape = slide.shapes.add_table(
        len(limits) + 1, 3,
        LEFT_MARGIN, Inches(1.5),
        Inches(11.0), Inches(0.38) * (len(limits) + 1)
    )
    table = table_shape.table
    table.columns[0].width = Inches(2.2)
    table.columns[1].width = Inches(1.5)
    table.columns[2].width = Inches(7.3)

    # Header
    for j, header in enumerate(["Parameter", "Limit", "Action"]):
        cell = table.cell(0, j)
        cell.text = header
        for p in cell.text_frame.paragraphs:
            p.font.size = Pt(11)
            p.font.bold = True
            p.font.color.rgb = WHITE
            p.font.name = "Calibri"
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_NAVY

    for i, (param, limit, action) in enumerate(limits):
        for j, val in enumerate([param, limit, action]):
            cell = table.cell(i + 1, j)
            cell.text = val
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(10)
                p.font.color.rgb = BODY_GRAY
                p.font.name = "Calibri"
                if j == 1:
                    p.font.bold = True
                    p.alignment = PP_ALIGN.CENTER
            cell.fill.solid()
            cell.fill.fore_color.rgb = OFF_WHITE if i % 2 == 0 else WHITE

    # Scenario tools section below table
    _add_textbox(slide, LEFT_MARGIN, Inches(4.8), CONTENT_WIDTH, Inches(0.3),
                 "SCENARIO TOOLS", font_size=14, bold=True, color=DARK_NAVY)

    tools = [
        "8 macro scenario stress tests with non-uniform sector/rating shocks and exact CDS re-pricing",
        "Full tranche reprice with convexity -- not DV01 approximations",
        "Single-name blowout analysis with CS01 acceleration and JTD payoff",
        "Daily P&L attribution by direction, sector, rating bucket, and position type",
        "Parametric VaR (95/99) and CVaR with spread/correlation factor decomposition",
        "Hedge effectiveness tracking across all stress scenarios",
    ]

    tb = _add_textbox(slide, LEFT_MARGIN, Inches(5.2), CONTENT_WIDTH, Inches(2.0),
                      "", font_size=11, color=STEEL)
    tf = tb.text_frame
    tf.paragraphs[0].text = ""
    for tool in tools:
        _add_para(tf, f"   {tool}", font_size=10, color=STEEL, space_before=2)


def slide_scenarios(prs):
    """Slide 9: STRESS SCENARIOS — 8 macro environments."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "STRESS SCENARIOS",
               "8 macro environments -- full reprice P&L with exact CDS re-pricing")

    scenarios = [
        ("ECB Cuts 50bp", "Risk-on rally", "-30 to -50bp", "tighten"),
        ("ECB Hikes 25bp", "Hawkish surprise", "+20 to +40bp", "widen"),
        ("European Recession", "Deep widening", "+100 to +250bp", "widen"),
        ("China Credit Crisis", "Global contagion", "+50 to +100bp", "widen"),
        ("Sovereign Stress", "Italy/France crisis", "+50 to +100bp", "widen"),
        ("LME Wave", "Distressed restructurings", "Named: +250 to +400bp", "widen"),
        ("Fallen Angel Cascade", "BBB downgrades flood HY", "+30 to +60bp", "widen"),
        ("Risk-On Squeeze", "Short squeeze rally", "-40 to -60bp", "tighten"),
    ]

    table_shape = slide.shapes.add_table(
        len(scenarios) + 1, 4,
        LEFT_MARGIN, Inches(1.5),
        Inches(11.0), Inches(0.38) * (len(scenarios) + 1)
    )
    table = table_shape.table
    table.columns[0].width = Inches(2.5)
    table.columns[1].width = Inches(2.5)
    table.columns[2].width = Inches(3.0)
    table.columns[3].width = Inches(3.0)

    for j, header in enumerate(["Scenario", "Description", "Spread Shock", "Key Feature"]):
        cell = table.cell(0, j)
        cell.text = header
        for p in cell.text_frame.paragraphs:
            p.font.size = Pt(11)
            p.font.bold = True
            p.font.color.rgb = WHITE
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_NAVY

    features = [
        "CCC names rally hardest; Consumer/TMT benefit most",
        "CCC names hit hardest; Autos & Industrials widest",
        "Consumer discretionary and Autos hardest hit; CCC names gap wider",
        "Autos widest (+40% extra) due to China supply chain exposure",
        "Financials widest (+50%); sovereign-bank nexus drives contagion",
        "INEOS, Worldline, Sherwood named; contagion lifts B names +50bp",
        "BB names widest (+60bp) from new HY supply flooding index",
        "TMT/Consumers tightest; crowded short positioning unwinds",
    ]

    for i, ((name, desc, shock, direction), feature) in enumerate(
            zip(scenarios, features)):
        vals = [name, desc, shock, feature]
        for j, val in enumerate(vals):
            cell = table.cell(i + 1, j)
            cell.text = val
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(9)
                p.font.color.rgb = BODY_GRAY
                if j == 2:
                    p.font.color.rgb = (SHORT_RED if direction == "widen"
                                        else LONG_GREEN)
                    p.font.bold = True
            cell.fill.solid()
            cell.fill.fore_color.rgb = OFF_WHITE if i % 2 == 0 else WHITE

    # Note below
    _add_textbox(slide, LEFT_MARGIN, Inches(5.7), CONTENT_WIDTH, Inches(1.0),
                 "Each scenario applies non-uniform spread shocks by rating bucket, sector, "
                 "and individual name characteristics. P&L computed by exact CDS re-pricing "
                 "(not DV01 approximations) with sector heatmap and direction breakdown. "
                 "Hedge effectiveness tracked across all scenarios.",
                 font_size=10, color=MID_GRAY)


def slide_tranche_convexity(prs, tranche_data):
    """Slide 10: TRANCHE SCENARIOS — convexity payoff."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "TRANCHE SCENARIO ANALYSIS",
               "Full reprice P&L with convexity -- calibrated from live market")

    if not tranche_data:
        _add_textbox(slide, LEFT_MARGIN, Inches(2.0), CONTENT_WIDTH, Inches(1.0),
                     "No tranche scenario data available.",
                     font_size=14, color=STEEL)
        return

    # Build table from CSV data
    headers = ["Tranche", "Attach", "Detach", "Fair Spread", "CS01",
               "Delta", "Leverage", "-50bp", "+25bp", "+100bp", "+200bp"]
    n_rows = len(tranche_data)

    table_shape = slide.shapes.add_table(
        n_rows + 1, len(headers),
        LEFT_MARGIN, Inches(1.5),
        Inches(11.5), Inches(0.4) * (n_rows + 1)
    )
    table = table_shape.table

    col_w = [Inches(1.6), Inches(0.7), Inches(0.7), Inches(1.0), Inches(0.9),
             Inches(0.7), Inches(0.8), Inches(1.0), Inches(1.0), Inches(1.0), Inches(1.1)]
    for j, w in enumerate(col_w):
        table.columns[j].width = w

    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        for p in cell.text_frame.paragraphs:
            p.font.size = Pt(9)
            p.font.bold = True
            p.font.color.rgb = WHITE
            p.alignment = PP_ALIGN.CENTER
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_NAVY

    for i, row in enumerate(tranche_data):
        vals = [
            row.get("Tranche", ""),
            row.get("Attachment", ""),
            row.get("Detachment", ""),
            f"{float(row.get('FairSpread_bps', 0)):,.0f}bp",
            f"${float(row.get('CS01_usd', 0)):,.0f}",
            row.get("Delta", ""),
            f"{row.get('Leverage', '')}x",
            f"${float(row.get('PnL_-50bp_(203)', 0)):+,.0f}",
            f"${float(row.get('PnL_+25bp_(278)', 0)):+,.0f}",
            f"${float(row.get('PnL_+100bp_(353)', 0)):+,.0f}",
            f"${float(row.get('PnL_+200bp_(453)', 0)):+,.0f}",
        ]
        for j, val in enumerate(vals):
            cell = table.cell(i + 1, j)
            cell.text = str(val)
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(8)
                p.font.name = "Consolas"
                p.alignment = PP_ALIGN.CENTER if j > 0 else PP_ALIGN.LEFT
                # Colour P&L columns
                if j >= 7:
                    if "+" in str(val) and "$" in str(val):
                        p.font.color.rgb = LONG_GREEN
                    elif "-" in str(val):
                        p.font.color.rgb = SHORT_RED
                    else:
                        p.font.color.rgb = BODY_GRAY
                else:
                    p.font.color.rgb = BODY_GRAY
            cell.fill.solid()
            cell.fill.fore_color.rgb = OFF_WHITE if i % 2 == 0 else WHITE

    # Convexity note
    _add_textbox(slide, LEFT_MARGIN, Inches(4.2), CONTENT_WIDTH, Inches(2.5),
                 "KEY INSIGHT: Equity tranche (0-10%) has 75.7x leverage with negative gamma -- "
                 "P&L accelerates non-linearly as spreads widen. This is the payoff structure "
                 "you buy when you have a credit catalyst thesis. A +200bp move in the index "
                 "generates over $2.1m loss on the equity tranche vs $271k on the super senior -- "
                 "the protection buyer captures this asymmetry.\n\n"
                 "Single-name blowout convexity: if a stressed name widens +250bp, per-name CS01 "
                 "increases ~48% due to convexity acceleration. On a credit event with 33% recovery, "
                 "jump-to-default payout can reach +$1.8m per name.",
                 font_size=10, color=DARK_NAVY)


def slide_trade_example(prs):
    """Slide 11: TRADE EXAMPLE — concrete CDS trade."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "TRADE EXAMPLE",
               "Credit catalyst trade -- from signal to exit")

    # Trade setup
    _add_textbox(slide, LEFT_MARGIN, Inches(1.5), Inches(5.5), Inches(0.3),
                 "SIGNAL", font_size=14, bold=True, color=ACCENT_BLUE)
    _add_textbox(slide, LEFT_MARGIN, Inches(1.9), Inches(5.5), Inches(1.2),
                 "System flags unusual filing: Company X announces a 200m dividend recap "
                 "while leverage sits at 5.5x. Management history shows creditor-hostile "
                 "behaviour. Documentation engine confirms weak covenant package -- no "
                 "restricted payments cap, no portability limits.",
                 font_size=11, color=STEEL)

    _add_textbox(slide, LEFT_MARGIN, Inches(3.1), Inches(5.5), Inches(0.3),
                 "EXECUTION", font_size=14, bold=True, color=ACCENT_BLUE)
    _add_textbox(slide, LEFT_MARGIN, Inches(3.5), Inches(5.5), Inches(1.4),
                 "Buy 5yr CDS protection at 350bps\n"
                 "CS01: ~$16,500/bp (~2% of risk budget on $250m book)\n"
                 "Target: 550bps (downgrade catalyst)\n"
                 "Stop: 280bps (thesis invalidated)\n"
                 "Instrument choice: single-name CDS preferred over bond short "
                 "due to better liquidity and no borrow cost",
                 font_size=11, color=STEEL)

    # Right column: P&L
    _add_rect(slide, Inches(6.8), Inches(1.5), Inches(5.5), Inches(5.0), NAVY)

    _add_textbox(slide, Inches(7.0), Inches(1.7), Inches(5.0), Inches(0.3),
                 "P&L SCENARIOS", font_size=14, bold=True, color=WHITE)

    scenarios = [
        ("Target hit (350 > 550bp)", "+200bp x $16.5k = +$3.3m", "+ convexity", LONG_GREEN),
        ("Overshoot (350 > 700bp)", "+350bp x $16.5k = +$5.8m", "+ significant convexity", LONG_GREEN),
        ("Credit event (default)", "JTD payout ~$10m", "33% recovery assumed", LONG_GREEN),
        ("Stop hit (350 > 280bp)", "-70bp x $16.5k = -$1.2m", "R:R was 2.8:1 at entry", SHORT_RED),
        ("Thesis delayed (no move)", "Carry cost ~$350k/yr", "Time decay is the enemy", AMBER),
    ]

    y = Inches(2.2)
    for label, pnl, note, color in scenarios:
        _add_textbox(slide, Inches(7.0), y, Inches(5.0), Inches(0.25),
                     label, font_size=11, bold=True, color=color)
        _add_textbox(slide, Inches(7.0), y + Inches(0.25), Inches(3.0), Inches(0.2),
                     pnl, font_size=10, color=WHITE, font_name="Consolas")
        _add_textbox(slide, Inches(9.8), y + Inches(0.25), Inches(2.5), Inches(0.2),
                     note, font_size=9, color=LIGHT_STEEL)
        y += Inches(0.65)

    # Key takeaway
    _add_textbox(slide, Inches(7.0), Inches(5.7), Inches(5.0), Inches(0.6),
                 "Convexity means the upside accelerates as spreads widen. "
                 "The risk/reward is asymmetric by design -- this is the core "
                 "of the strategy.",
                 font_size=10, bold=True, color=ACCENT_BLUE)


def slide_onboarding(prs):
    """Slide 12: ONBOARDING PLAN — first 90 days."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, OFF_WHITE)
    _title_bar(slide, "ONBOARDING PLAN", "First 90 days -- from allocation to full deployment")

    phases = [
        ("DAYS 1-30", "SETUP & INITIAL DEPLOYMENT", [
            "Legal/compliance onboarding, ISDA agreements, broker setup",
            "Connect monitoring platform to Brummer infrastructure",
            "Initial $50m deployment in liquid single-name CDS (Main index names)",
            "Establish daily risk reporting and P&L attribution framework",
            "Deploy credit documentation analysis across priority Crossover names",
        ]),
        ("DAYS 31-60", "RAMP & DIVERSIFY", [
            "Scale to $150m -- add Crossover single-name positions and basis trades",
            "Initiate first tranche positions (equity/mezzanine dispersion trades)",
            "Full 8-scenario stress testing with live portfolio data",
            "Weekly strategy review with risk committee",
            "Calibrate stop-loss levels to observed portfolio volatility",
        ]),
        ("DAYS 61-90", "FULL DEPLOYMENT", [
            "Full $250m deployment across CDS, bonds, tranches, and credit options",
            "All instrument types active with full risk limit monitoring",
            "Automated daily briefing from monitoring platform live and operational",
            "First quarterly performance review and strategy assessment",
            "Demonstrate platform value: signals caught, trades executed, P&L generated",
        ]),
    ]

    for i, (period, title, items) in enumerate(phases):
        left = LEFT_MARGIN + i * Inches(3.9)
        # Period header
        _add_rect(slide, left, Inches(1.5), Inches(3.6), Inches(0.4), ACCENT_BLUE)
        _add_textbox(slide, left + Inches(0.1), Inches(1.5), Inches(3.4), Inches(0.4),
                     period, font_size=13, bold=True, color=WHITE)
        # Title
        _add_textbox(slide, left, Inches(2.0), Inches(3.6), Inches(0.35),
                     title, font_size=11, bold=True, color=DARK_NAVY)

        tb = _add_textbox(slide, left, Inches(2.45), Inches(3.6), Inches(4.0),
                          "", font_size=10, color=STEEL)
        tf = tb.text_frame
        tf.paragraphs[0].text = ""
        for item in items:
            _add_para(tf, f"   {item}", font_size=9, color=STEEL,
                      space_before=4, space_after=1)


def slide_ask(prs):
    """Slide 13: THE ASK."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, DARK_NAVY)

    _add_textbox(slide, LEFT_MARGIN, Inches(1.0), CONTENT_WIDTH, Inches(0.6),
                 "T H E   A S K", font_size=14, color=STEEL,
                 alignment=PP_ALIGN.LEFT)

    _add_rect(slide, LEFT_MARGIN, Inches(1.6), Inches(3.0), Inches(0.03), ACCENT_BLUE)

    _add_textbox(slide, LEFT_MARGIN, Inches(1.9), CONTENT_WIDTH, Inches(0.5),
                 "$250m capital allocation",
                 font_size=28, bold=True, color=WHITE)

    _add_textbox(slide, LEFT_MARGIN, Inches(2.6), CONTENT_WIDTH, Inches(0.4),
                 "Solo PM + proprietary AI technology stack",
                 font_size=18, color=ACCENT_BLUE)

    points = [
        "28-year track record in European credit with verifiable P&L",
        "Rare combination: fundamental credit analyst + derivatives structurer in one PM",
        "AI platform monitoring 200 names 24/7 -- filing surveillance, forensic analysis, "
        "management tone detection, covenant scrubbing",
        "Capital efficient: solo PM, no team overhead, immediate deployment",
        "Platform-compatible risk framework from day one (1% daily / 2% weekly / "
        "3.5% monthly / 5% max P2T)",
        "Strategy that is genuinely differentiated from existing BMS pods",
    ]

    tb = _add_textbox(slide, LEFT_MARGIN, Inches(3.5), Inches(9.0), Inches(3.0),
                      "", font_size=14, color=WHITE)
    tf = tb.text_frame
    tf.paragraphs[0].text = ""
    for point in points:
        _add_para(tf, f"   {point}", font_size=13, color=OFF_WHITE,
                  space_before=8, space_after=2)

    # Contact
    _add_rect(slide, LEFT_MARGIN, Inches(6.5), Inches(6.0), Inches(0.03), STEEL)
    _add_textbox(slide, LEFT_MARGIN, Inches(6.65), CONTENT_WIDTH, Inches(0.3),
                 "Matt Bristow  |  toget_mattbristow@hotmail.co.uk  |  +44 7809 158381",
                 font_size=11, color=LIGHT_STEEL)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_deck(notional_m: float = 250.0) -> str:
    """Generate the complete Brummer pitch deck."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT

    # Load data
    manifest = load_manifest()
    positions = load_portfolio_risk()
    tranche_data = load_tranche_scenarios()

    # Build slides
    slide_title(prs)                           # 1. Title
    slide_edge(prs)                            # 2. The Edge
    slide_process(prs)                         # 3. The Process

    # Section break
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _section_divider(s, "AI-AUGMENTED PLATFORM",
                     "How technology scales 28 years of experience across 200 names")

    slide_ai_platform(prs)                     # 4. AI Platform
    slide_skills(prs)                          # 5. Skills
    slide_universe(prs, manifest)              # 6. Universe

    # Section break
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _section_divider(s, "PORTFOLIO & RISK",
                     "How I structure trades and manage risk on a $250m book")

    slide_portfolio(prs, positions)            # 7. Portfolio
    slide_trade_example(prs)                   # 8. Trade Example
    slide_risk_framework(prs)                  # 9. Risk Framework
    slide_scenarios(prs)                       # 10. Stress Scenarios
    slide_tranche_convexity(prs, tranche_data) # 11. Tranche Convexity
    slide_onboarding(prs)                      # 12. Onboarding
    slide_ask(prs)                             # 13. The Ask

    # Save
    filepath = OUTPUT_DIR / f"brummer_pitch_{TODAY_FILE}.pptx"
    prs.save(str(filepath))
    return str(filepath)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate Brummer & Partners pitch deck"
    )
    parser.add_argument("--notional", type=float, default=250.0,
                        help="Book size in $M (default: 250)")
    args = parser.parse_args()

    print(f"\nGenerating Brummer & Partners pitch deck...")
    print(f"  Book size: ${args.notional:.0f}M")

    filepath = generate_deck(args.notional)

    print(f"\n  Deck saved: {filepath}")
    print(f"  Slides: 15 (including section dividers)")
    print(f"  Date: {TODAY}")
    print()


if __name__ == "__main__":
    main()

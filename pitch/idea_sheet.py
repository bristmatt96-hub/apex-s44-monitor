"""
Credit Idea Sheet — One-Page PDF Generator

Generates a professional one-page A4 PDF for a single credit assessment.
Designed as pitch material for multi-manager hedge fund platforms.

Usage:
    python -m pitch.idea_sheet "Ardagh Group" --index Xover
    python -m pitch.idea_sheet "Telecom Italia" --index Main
    python -m pitch.idea_sheet --from-excel outputs/xover_screen_20260218.xlsx --top 10
"""

import argparse
import os
import sys
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
)

from core.models import CreditAssessment, Direction

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

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
FLAT_GREY = colors.HexColor("#6C757D")
FLAT_BG = colors.HexColor("#F5F5F5")

ACCENT = colors.HexColor("#1976D2")
DIVIDER = colors.HexColor("#DEE2E6")

OUTPUT_DIR = Path("outputs/idea_sheets")

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def get_styles() -> dict:
    """Build all paragraph styles."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=18,
            textColor=WHITE, leading=22,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"],
            fontName="Helvetica", fontSize=10,
            textColor=LIGHT_STEEL, leading=14,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11,
            textColor=NAVY, leading=14,
            spaceBefore=8, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontName="Helvetica", fontSize=9.5,
            textColor=colors.HexColor("#212529"), leading=13,
        ),
        "body_bold": ParagraphStyle(
            "body_bold", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9.5,
            textColor=colors.HexColor("#212529"), leading=13,
        ),
        "metric_label": ParagraphStyle(
            "metric_label", parent=base["Normal"],
            fontName="Helvetica", fontSize=8.5,
            textColor=STEEL, leading=11, alignment=TA_CENTER,
        ),
        "metric_value": ParagraphStyle(
            "metric_value", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=14,
            textColor=NAVY, leading=18, alignment=TA_CENTER,
        ),
        "spread_big": ParagraphStyle(
            "spread_big", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=28,
            textColor=NAVY, leading=32, alignment=TA_CENTER,
        ),
        "spread_label": ParagraphStyle(
            "spread_label", parent=base["Normal"],
            fontName="Helvetica", fontSize=9,
            textColor=STEEL, leading=12, alignment=TA_CENTER,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"],
            fontName="Helvetica", fontSize=9,
            textColor=colors.HexColor("#212529"), leading=12,
            leftIndent=12, bulletIndent=0,
            spaceBefore=2,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"],
            fontName="Helvetica", fontSize=7,
            textColor=LIGHT_STEEL, alignment=TA_CENTER,
        ),
        "badge": ParagraphStyle(
            "badge", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11,
            leading=14, alignment=TA_CENTER,
        ),
    }


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def _draw_header(canvas, doc, assessment: CreditAssessment):
    """Draw the dark header bar with entity name and direction badge."""
    width, height = A4
    styles = get_styles()

    # Dark header background
    header_h = 58
    canvas.setFillColor(DARK_NAVY)
    canvas.rect(0, height - header_h, width, header_h, fill=1, stroke=0)

    # Entity name
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(1.8 * cm, height - 28, assessment.entity_name)

    # Subtitle line
    canvas.setFillColor(LIGHT_STEEL)
    canvas.setFont("Helvetica", 10)
    date_str = assessment.updated_at.strftime("%d %B %Y")
    canvas.drawString(1.8 * cm, height - 44,
                      f"iTraxx {assessment.itraxx_index.value}  |  {date_str}")

    # Direction badge (right side)
    if assessment.direction == Direction.LONG_RISK:
        badge_color = LONG_GREEN
        badge_text = "LONG RISK"
    elif assessment.direction == Direction.SHORT_RISK:
        badge_color = SHORT_RED
        badge_text = "SHORT RISK"
    else:
        badge_color = FLAT_GREY
        badge_text = "FLAT"

    badge_w = 90
    badge_h = 24
    badge_x = width - badge_w - 1.5 * cm
    badge_y = height - 42
    canvas.setFillColor(badge_color)
    canvas.roundRect(badge_x, badge_y, badge_w, badge_h, 4, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawCentredString(badge_x + badge_w / 2, badge_y + 7, badge_text)

    # Conviction stars
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(LIGHT_STEEL)
    star_x = badge_x
    star_y = height - 18
    filled = assessment.conviction
    stars = "\u2b24 " * filled + "\u25cb " * (5 - filled)
    canvas.drawString(star_x, star_y, f"Conviction: {stars.strip()}")

    # Footer
    canvas.setFillColor(DIVIDER)
    canvas.rect(0, 18, width, 0.5, fill=1, stroke=0)
    canvas.setFillColor(LIGHT_STEEL)
    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(width / 2, 8,
                             "Credit Catalyst  |  Confidential  |  Not Investment Advice")


def generate_idea_sheet(assessment: CreditAssessment) -> str:
    """Generate a one-page A4 PDF idea sheet. Returns the file path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = assessment.entity_name.replace(" ", "_").replace("/", "-")
    date_str = assessment.updated_at.strftime("%Y%m%d")
    filename = f"{safe_name}_{date_str}.pdf"
    filepath = str(OUTPUT_DIR / filename)

    styles = get_styles()
    width, height = A4

    # Build document with custom header
    def on_page(canvas, doc):
        _draw_header(canvas, doc, assessment)

    frame = Frame(
        1.8 * cm, 1.2 * cm,
        width - 3.6 * cm, height - 7.0 * cm,
        id="main",
    )
    doc = BaseDocTemplate(filepath, pagesize=A4,
                          leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                          topMargin=5.5 * cm, bottomMargin=1.2 * cm)
    doc.addPageTemplates([PageTemplate(id="idea", frames=[frame], onPage=on_page)])

    story = []

    # --- Spread comparison ---
    mispricing = assessment.fair_spread - assessment.current_spread
    mispricing_sign = "+" if mispricing >= 0 else ""
    arrow = "\u2191" if mispricing > 0 else ("\u2193" if mispricing < 0 else "\u2194")

    if assessment.direction == Direction.LONG_RISK:
        mispricing_color = LONG_GREEN
    elif assessment.direction == Direction.SHORT_RISK:
        mispricing_color = SHORT_RED
    else:
        mispricing_color = FLAT_GREY

    spread_data = [[
        [Paragraph(f"{assessment.current_spread:.0f}", styles["spread_big"]),
         Paragraph("Current Spread (bps)", styles["spread_label"])],
        [Paragraph(f'<font color="#{mispricing_color.hexval()[2:]}">{arrow}</font>',
                   ParagraphStyle("arrow", fontName="Helvetica-Bold", fontSize=24,
                                  alignment=TA_CENTER, textColor=mispricing_color))],
        [Paragraph(f"{assessment.fair_spread:.0f}", styles["spread_big"]),
         Paragraph("Fair Value (bps)", styles["spread_label"])],
        [Paragraph(f'<font color="#{mispricing_color.hexval()[2:]}">'
                   f'{mispricing_sign}{mispricing:.0f} bps</font>',
                   ParagraphStyle("misprice", fontName="Helvetica-Bold", fontSize=16,
                                  alignment=TA_CENTER, textColor=mispricing_color)),
         Paragraph("Mispricing", styles["spread_label"])],
    ]]

    spread_table = Table(spread_data, colWidths=[4.2 * cm, 1.8 * cm, 4.2 * cm, 4.2 * cm])
    spread_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, DIVIDER),
        ("LINEAFTER", (0, 0), (0, 0), 0.5, DIVIDER),
        ("LINEAFTER", (1, 0), (1, 0), 0.5, DIVIDER),
        ("LINEAFTER", (2, 0), (2, 0), 0.5, DIVIDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, -1), OFF_WHITE),
    ]))
    story.append(spread_table)
    story.append(Spacer(1, 10))

    # --- Thesis ---
    story.append(Paragraph("THESIS", styles["section"]))
    story.append(Paragraph(assessment.thesis, styles["body"]))
    story.append(Spacer(1, 6))

    # --- Catalyst ---
    story.append(Paragraph("CATALYST", styles["section"]))
    story.append(Paragraph(assessment.catalyst, styles["body"]))
    story.append(Spacer(1, 6))

    # --- Key Risks ---
    story.append(Paragraph("KEY RISKS", styles["section"]))
    for risk in assessment.key_risks:
        story.append(Paragraph(f"\u2022  {risk}", styles["bullet"]))
    story.append(Spacer(1, 6))

    # --- Fundamental Metrics ---
    story.append(Paragraph("FUNDAMENTAL METRICS", styles["section"]))
    metrics = assessment.fundamental_metrics
    metric_headers = []
    metric_values = []
    metric_map = {
        "leverage": ("Leverage", "x"),
        "coverage": ("Coverage", "x"),
        "fcf_yield": ("FCF Yield", "%"),
        "rating": ("Rating", ""),
        "ebitda_margin": ("EBITDA Margin", "%"),
        "net_debt_ebitda": ("Net Debt/EBITDA", "x"),
    }
    for key, (label, suffix) in metric_map.items():
        if key in metrics:
            val = metrics[key]
            if suffix == "%" and isinstance(val, (int, float)) and abs(val) < 1:
                formatted = f"{val * 100:.1f}%"
            elif suffix == "%":
                formatted = f"{val:.1f}%"
            elif suffix == "x":
                formatted = f"{val:.1f}x"
            else:
                formatted = str(val)
            metric_headers.append(Paragraph(label, styles["metric_label"]))
            metric_values.append(Paragraph(formatted, styles["metric_value"]))

    if metric_headers:
        n_cols = len(metric_headers)
        col_w = (width - 3.6 * cm) / n_cols
        metric_table = Table(
            [metric_headers, metric_values],
            colWidths=[col_w] * n_cols,
        )
        metric_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, -1), OFF_WHITE),
            ("BOX", (0, 0), (-1, -1), 0.5, DIVIDER),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, DIVIDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(metric_table)
        story.append(Spacer(1, 6))

    # --- Signal Sources ---
    story.append(Paragraph("SIGNAL SOURCES", styles["section"]))
    sources_text = "  |  ".join(assessment.signal_sources)
    story.append(Paragraph(sources_text, styles["body"]))

    # Build
    doc.build(story)
    return filepath


# ---------------------------------------------------------------------------
# Excel reader — reconstruct CreditAssessments from screen output
# ---------------------------------------------------------------------------

def load_from_excel(filepath: str) -> list[CreditAssessment]:
    """Read a universe screen Excel file and reconstruct CreditAssessment objects."""
    from openpyxl import load_workbook
    from core.models import ItraxxIndex

    wb = load_workbook(filepath, read_only=True)
    ws = wb["Screen Results"]

    assessments = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:  # skip empty rows
            continue

        entity_name = row[0]
        direction_str = row[1]
        conviction = int(row[2])
        current_spread = float(row[3])
        fair_spread = float(row[4])
        # row[5] = mispricing (derived)
        thesis = row[6] or ""
        catalyst = row[7] or ""
        key_risks_str = row[8] or ""
        signal_sources_str = row[9] or ""
        updated_str = row[10] or ""

        # Determine index from filename
        fname = os.path.basename(filepath).lower()
        itraxx_index = ItraxxIndex.XOVER if "xover" in fname else ItraxxIndex.MAIN

        # Parse direction
        direction = Direction(direction_str)

        # Parse updated_at
        if isinstance(updated_str, datetime):
            updated_at = updated_str
        elif updated_str:
            try:
                updated_at = datetime.strptime(str(updated_str), "%Y-%m-%d %H:%M")
            except ValueError:
                updated_at = datetime.now()
        else:
            updated_at = datetime.now()

        assessments.append(CreditAssessment(
            entity_name=entity_name,
            itraxx_index=itraxx_index,
            current_spread=current_spread,
            fair_spread=fair_spread,
            direction=direction,
            conviction=conviction,
            signal_sources=[s.strip() for s in signal_sources_str.split(",") if s.strip()],
            thesis=thesis,
            catalyst=catalyst,
            key_risks=[r.strip() for r in key_risks_str.split(";") if r.strip()],
            fundamental_metrics={},
            updated_at=updated_at,
        ))

    wb.close()
    return assessments


def select_top_names(
    assessments: list[CreditAssessment], top: int = 10
) -> list[CreditAssessment]:
    """Select top N names: top N/2 longs + top N/2 shorts by conviction then mispricing."""
    half = top // 2

    longs = [a for a in assessments if a.direction == Direction.LONG_RISK]
    shorts = [a for a in assessments if a.direction == Direction.SHORT_RISK]

    # Longs: highest conviction, then widest mispricing (fair > current = cheap for longs)
    top_longs = sorted(
        longs,
        key=lambda a: (a.conviction, abs(a.fair_spread - a.current_spread)),
        reverse=True,
    )[:half]

    # Shorts: highest conviction, then widest mispricing
    top_shorts = sorted(
        shorts,
        key=lambda a: (a.conviction, abs(a.fair_spread - a.current_spread)),
        reverse=True,
    )[:half]

    return top_longs + top_shorts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Credit Idea Sheet PDF")
    parser.add_argument("entity", type=str, nargs="?", default=None,
                        help="Company name (e.g. 'Ardagh Group')")
    parser.add_argument(
        "--index", type=str, choices=["Main", "Xover"], default="Main",
        help="iTraxx index (default: Main)",
    )
    parser.add_argument(
        "--from-excel", type=str, default=None,
        help="Path to universe screen Excel file",
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Number of top names to generate (half longs, half shorts). Default: 10",
    )
    args = parser.parse_args()

    if args.from_excel:
        # Batch mode: read Excel, pick top names, generate PDFs
        print(f"Loading assessments from {args.from_excel}...")
        assessments = load_from_excel(args.from_excel)
        print(f"Loaded {len(assessments)} assessments")

        selected = select_top_names(assessments, args.top)
        longs = [a for a in selected if a.direction == Direction.LONG_RISK]
        shorts = [a for a in selected if a.direction == Direction.SHORT_RISK]

        print(f"\nGenerating {len(selected)} idea sheets "
              f"({len(longs)} longs, {len(shorts)} shorts):\n")

        for i, assessment in enumerate(selected, 1):
            tag = "LONG" if assessment.direction == Direction.LONG_RISK else "SHORT"
            print(f"  [{i}/{len(selected)}] {assessment.entity_name} "
                  f"({tag}, conviction {assessment.conviction})...", end=" ")
            filepath = generate_idea_sheet(assessment)
            print(f"OK -> {os.path.basename(filepath)}")

        print(f"\nDone -- {len(selected)} PDFs saved to {OUTPUT_DIR}/")

    elif args.entity:
        # Single name mode
        print(f"Running analyst for {args.entity} (iTraxx {args.index})...")
        from agents.analyst import assess_credit
        assessment = assess_credit(args.entity, args.index)

        print(f"Generating idea sheet...")
        filepath = generate_idea_sheet(assessment)
        print(f"PDF saved: {filepath}")

    else:
        parser.error("Either provide an entity name or use --from-excel")


if __name__ == "__main__":
    main()

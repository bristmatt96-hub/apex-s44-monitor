"""
Morning Brief Agent

Generates a daily credit briefing from the latest universe screen and
recent regulatory filings. Outputs both a Telegram message and a
professional PDF saved to outputs/briefs/.

The brief reads from the latest Excel screen in outputs/ so it does
NOT re-run 81 analyst API calls. Only re-runs the analyst on specific
names if --refresh is provided (e.g. after a material filing).

Usage:
    python -m agents.briefing                           # Full brief from latest screen
    python -m agents.briefing --no-telegram             # PDF only
    python -m agents.briefing --no-pdf                  # Telegram only
    python -m agents.briefing --refresh "Ardagh Group"  # Re-run analyst on one name first
"""

import argparse
import asyncio
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from loguru import logger

from core.models import CreditAssessment, Direction, ItraxxIndex

load_dotenv(override=True)

OUTPUT_DIR = Path("outputs/briefs")


# ---------------------------------------------------------------------------
# Load latest screen from Excel
# ---------------------------------------------------------------------------

def find_latest_screen(index: str = "xover") -> Optional[str]:
    """Find the most recent screen Excel file in outputs/."""
    pattern = os.path.join("outputs", f"{index}_screen_*.xlsx")
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None


def load_assessments_from_excel(filepath: str) -> list[CreditAssessment]:
    """Read assessments from a universe screen Excel file."""
    from openpyxl import load_workbook

    wb = load_workbook(filepath, read_only=True)
    ws = wb["Screen Results"]

    # Determine index from filename
    fname = os.path.basename(filepath).lower()
    itraxx_index = ItraxxIndex.XOVER if "xover" in fname else ItraxxIndex.MAIN

    assessments = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue

        # Parse updated_at
        # Column layout: 0:Entity, 1:Direction, 2:Conviction, 3:Raw Conviction,
        # 4:Current Spread, 5:Fair Spread, 6:Mispricing, 7:Rel Mispricing%,
        # 8:Thesis, 9:Catalyst, 10:Risks, 11:Signal Sources, 12:Updated At
        updated_str = row[12] or ""
        if isinstance(updated_str, datetime):
            updated_at = updated_str
        elif updated_str:
            try:
                updated_at = datetime.strptime(str(updated_str), "%Y-%m-%d %H:%M")
            except ValueError:
                updated_at = datetime.now()
        else:
            updated_at = datetime.now()

        raw_conv = int(row[3]) if row[3] is not None else None

        assessments.append(CreditAssessment(
            entity_name=row[0],
            itraxx_index=itraxx_index,
            current_spread=float(row[4]),
            fair_spread=float(row[5]),
            direction=Direction(row[1]),
            conviction=int(row[2]),
            raw_conviction=raw_conv,
            signal_sources=[s.strip() for s in (row[11] or "").split(",") if s.strip()],
            thesis=row[8] or "",
            catalyst=row[9] or "",
            key_risks=[r.strip() for r in (row[10] or "").split(";") if r.strip()],
            fundamental_metrics={},
            updated_at=updated_at,
        ))

    wb.close()
    return assessments


# ---------------------------------------------------------------------------
# Load recent filings from SQLite
# ---------------------------------------------------------------------------

def load_recent_filings(days: int = 1) -> list[dict]:
    """Load recent classified filings from the European monitor database."""
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
    """, (cutoff,)).fetchall()
    conn.close()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Build the brief data structure
# ---------------------------------------------------------------------------

def build_brief(
    assessments: list[CreditAssessment],
    filings: list[dict],
    screen_date: str,
) -> dict:
    """Assemble all brief data from assessments and filings."""

    longs = [a for a in assessments if a.direction == Direction.LONG_RISK]
    shorts = [a for a in assessments if a.direction == Direction.SHORT_RISK]
    flats = [a for a in assessments if a.direction == Direction.FLAT]

    avg_conviction = (
        sum(a.conviction for a in assessments) / len(assessments)
        if assessments else 0
    )

    # Top 5 longs: highest conviction, then widest absolute mispricing
    top_longs = sorted(
        longs,
        key=lambda a: (a.conviction, abs(a.fair_spread - a.current_spread)),
        reverse=True,
    )[:5]

    # Top 5 shorts: highest conviction, then widest absolute mispricing
    top_shorts = sorted(
        shorts,
        key=lambda a: (a.conviction, abs(a.fair_spread - a.current_spread)),
        reverse=True,
    )[:5]

    # High-conviction watchlist (conviction >= 4 across both directions)
    watchlist = sorted(
        [a for a in assessments if a.conviction >= 4],
        key=lambda a: (a.conviction, abs(a.fair_spread - a.current_spread)),
        reverse=True,
    )

    # Material filings (severity >= 2)
    material_filings = [f for f in filings if f.get("severity", 0) >= 2]

    # Derive market regime from aggregate positioning
    if len(longs) > len(shorts) * 1.5:
        regime = "RISK-ON: Majority of names are cheap vs fair value"
    elif len(shorts) > len(longs) * 1.5:
        regime = "RISK-OFF: Majority of names are rich vs fair value"
    else:
        regime = "NEUTRAL: Mixed signals across the universe"

    avg_spread = (
        sum(a.current_spread for a in assessments) / len(assessments)
        if assessments else 0
    )

    return {
        "date": datetime.now().strftime("%d %B %Y"),
        "screen_date": screen_date,
        "total_names": len(assessments),
        "n_longs": len(longs),
        "n_shorts": len(shorts),
        "n_flats": len(flats),
        "avg_conviction": avg_conviction,
        "avg_spread": avg_spread,
        "regime": regime,
        "top_longs": top_longs,
        "top_shorts": top_shorts,
        "watchlist": watchlist,
        "material_filings": material_filings,
        "all_filings": filings,
    }


# ---------------------------------------------------------------------------
# Telegram message builder
# ---------------------------------------------------------------------------

def build_telegram_message(brief: dict) -> str:
    """Format the brief as a concise Telegram HTML message."""
    lines = []

    # Header
    lines.append(f"<b>MORNING BRIEF -- {brief['date']}</b>")
    lines.append(f"iTraxx Xover S44 | Screen: {brief['screen_date']}")
    lines.append("")

    # Regime
    lines.append(f"<b>REGIME:</b> {brief['regime']}")
    lines.append(
        f"Universe: {brief['total_names']} names | "
        f"L:{brief['n_longs']} S:{brief['n_shorts']} F:{brief['n_flats']} | "
        f"Avg conviction: {brief['avg_conviction']:.1f}/5 | "
        f"Avg spread: {brief['avg_spread']:.0f}bps"
    )
    lines.append("")

    # Top longs
    lines.append("<b>TOP 5 LONGS (spreads too wide):</b>")
    for a in brief["top_longs"]:
        mispricing = a.fair_spread - a.current_spread
        lines.append(
            f"  {a.entity_name} | "
            f"{a.current_spread:.0f}/{a.fair_spread:.0f}bps ({mispricing:+.0f}) | "
            f"Conv {a.conviction}/5"
        )
    lines.append("")

    # Top shorts
    lines.append("<b>TOP 5 SHORTS (spreads too tight):</b>")
    for a in brief["top_shorts"]:
        mispricing = a.fair_spread - a.current_spread
        lines.append(
            f"  {a.entity_name} | "
            f"{a.current_spread:.0f}/{a.fair_spread:.0f}bps ({mispricing:+.0f}) | "
            f"Conv {a.conviction}/5"
        )
    lines.append("")

    # Material filings
    if brief["material_filings"]:
        lines.append(f"<b>FILINGS ({len(brief['material_filings'])} material):</b>")
        for f in brief["material_filings"][:5]:
            impact = f.get("credit_impact", "?").upper()
            sev = f.get("severity", 0)
            entity = f.get("matched_entity", "Unknown")
            summary = f.get("credit_summary", f.get("headline", ""))[:80]
            lines.append(f"  [{impact} {sev}/5] {entity}: {summary}")
        lines.append("")
    else:
        lines.append("<b>FILINGS:</b> No material filings in last 24h")
        lines.append("")

    # Watchlist count
    lines.append(
        f"<b>WATCHLIST:</b> {len(brief['watchlist'])} names at conviction 4+"
    )

    lines.append("")
    lines.append(f"Strategies in Credit | {datetime.now().strftime('%H:%M')} UTC")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PDF brief generator
# ---------------------------------------------------------------------------

def generate_brief_pdf(brief: dict) -> str:
    """Generate a professional A4 PDF morning brief. Returns filepath."""
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
    filename = f"morning_brief_{date_str}.pdf"
    filepath = str(OUTPUT_DIR / filename)

    # Colours
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
            fontName="Helvetica-Bold", fontSize=12,
            textColor=NAVY, leading=16,
            spaceBefore=10, spaceAfter=4,
        ),
        "subsection": ParagraphStyle(
            "subsection", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=10,
            textColor=STEEL, leading=13,
            spaceBefore=6, spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontName="Helvetica", fontSize=9.5,
            textColor=BODY_COLOR, leading=13,
        ),
        "body_bold": ParagraphStyle(
            "body_bold", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9.5,
            textColor=BODY_COLOR, leading=13,
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
        "small": ParagraphStyle(
            "small", parent=base["Normal"],
            fontName="Helvetica", fontSize=8,
            textColor=STEEL, leading=10,
        ),
        "filing_neg": ParagraphStyle(
            "filing_neg", parent=base["Normal"],
            fontName="Helvetica", fontSize=9,
            textColor=SHORT_RED, leading=12,
        ),
        "filing_pos": ParagraphStyle(
            "filing_pos", parent=base["Normal"],
            fontName="Helvetica", fontSize=9,
            textColor=LONG_GREEN, leading=12,
        ),
        "filing_neutral": ParagraphStyle(
            "filing_neutral", parent=base["Normal"],
            fontName="Helvetica", fontSize=9,
            textColor=STEEL, leading=12,
        ),
    }

    width, height = A4

    def on_page(canvas, doc):
        # Header bar
        header_h = 50
        canvas.setFillColor(DARK_NAVY)
        canvas.rect(0, height - header_h, width, header_h, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(1.8 * cm, height - 24, f"Morning Brief -- {brief['date']}")
        canvas.setFillColor(LIGHT_STEEL)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(1.8 * cm, height - 40,
                          f"iTraxx Xover S44  |  Screen: {brief['screen_date']}  |  "
                          f"{brief['total_names']} names")
        # Regime badge (right side)
        regime_short = brief["regime"].split(":")[0]
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawRightString(width - 1.5 * cm, height - 24, regime_short)
        # Footer
        canvas.setFillColor(DIVIDER)
        canvas.rect(0, 18, width, 0.5, fill=1, stroke=0)
        canvas.setFillColor(LIGHT_STEEL)
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(width / 2, 8,
                                 "Strategies in Credit  |  Confidential  |  Not Investment Advice")

    frame = Frame(1.8 * cm, 1.2 * cm, width - 3.6 * cm, height - 6.0 * cm, id="main")
    doc = BaseDocTemplate(filepath, pagesize=A4,
                          leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                          topMargin=4.5 * cm, bottomMargin=1.2 * cm)
    doc.addPageTemplates([PageTemplate(id="brief", frames=[frame], onPage=on_page)])

    story = []

    # --- Overview metrics ---
    story.append(Paragraph("OVERVIEW", styles["section"]))
    overview_headers = [
        Paragraph("Total", styles["metric_label"]),
        Paragraph("Longs", styles["metric_label"]),
        Paragraph("Shorts", styles["metric_label"]),
        Paragraph("Flat", styles["metric_label"]),
        Paragraph("Avg Conv.", styles["metric_label"]),
        Paragraph("Avg Spread", styles["metric_label"]),
    ]
    overview_values = [
        Paragraph(str(brief["total_names"]), styles["metric_value"]),
        Paragraph(f'<font color="#28A745">{brief["n_longs"]}</font>', styles["metric_value"]),
        Paragraph(f'<font color="#DC3545">{brief["n_shorts"]}</font>', styles["metric_value"]),
        Paragraph(str(brief["n_flats"]), styles["metric_value"]),
        Paragraph(f'{brief["avg_conviction"]:.1f}', styles["metric_value"]),
        Paragraph(f'{brief["avg_spread"]:.0f}', styles["metric_value"]),
    ]
    col_w = (width - 3.6 * cm) / 6
    overview_table = Table([overview_headers, overview_values], colWidths=[col_w] * 6)
    overview_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), OFF_WHITE),
        ("BOX", (0, 0), (-1, -1), 0.5, DIVIDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, DIVIDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(overview_table)
    story.append(Spacer(1, 4))
    story.append(Paragraph(brief["regime"], styles["body"]))
    story.append(Spacer(1, 8))

    # --- Top 5 Longs ---
    story.append(Paragraph("TOP 5 LONGS -- Spreads Too Wide", styles["section"]))
    _add_top_table(story, brief["top_longs"], LONG_GREEN, styles, width, DIVIDER, OFF_WHITE)
    story.append(Spacer(1, 8))

    # --- Top 5 Shorts ---
    story.append(Paragraph("TOP 5 SHORTS -- Spreads Too Tight", styles["section"]))
    _add_top_table(story, brief["top_shorts"], SHORT_RED, styles, width, DIVIDER, OFF_WHITE)
    story.append(Spacer(1, 8))

    # --- Material Filings ---
    story.append(Paragraph("MATERIAL FILINGS (Last 24h)", styles["section"]))
    if brief["material_filings"]:
        for f in brief["material_filings"][:8]:
            impact = f.get("credit_impact", "neutral")
            sev = f.get("severity", 0)
            entity = f.get("matched_entity", "Unknown")
            summary = f.get("credit_summary", f.get("headline", ""))[:120]
            style_key = f"filing_{impact}" if f"filing_{impact}" in styles else "filing_neutral"
            story.append(Paragraph(
                f"<b>[{impact.upper()} {sev}/5]</b> <b>{entity}</b>: {summary}",
                styles[style_key],
            ))
    else:
        story.append(Paragraph("No material filings in the last 24 hours.", styles["body"]))
    story.append(Spacer(1, 8))

    # --- Watchlist ---
    story.append(Paragraph(
        f"WATCHLIST -- {len(brief['watchlist'])} Names at Conviction 4+",
        styles["section"],
    ))
    if brief["watchlist"]:
        watchlist_text = ", ".join(
            f"{a.entity_name} ({a.direction.value.split('_')[0]} {a.conviction}/5)"
            for a in brief["watchlist"][:20]
        )
        story.append(Paragraph(watchlist_text, styles["small"]))
    else:
        story.append(Paragraph("No names currently at conviction 4+.", styles["body"]))

    doc.build(story)
    return filepath


def _add_top_table(story, assessments, direction_color, styles, page_width, divider, bg):
    """Add a top-5 table for longs or shorts."""
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Table, TableStyle, Paragraph

    if not assessments:
        story.append(Paragraph("No names in this category.", styles["body"]))
        return

    headers = ["Entity", "Current", "Fair", "Misprice", "Conv", "Catalyst"]
    header_row = [Paragraph(f"<b>{h}</b>", styles["small"]) for h in headers]

    data_rows = []
    for a in assessments:
        mispricing = a.fair_spread - a.current_spread
        data_rows.append([
            Paragraph(a.entity_name[:35], styles["body"]),
            Paragraph(f"{a.current_spread:.0f}", styles["body"]),
            Paragraph(f"{a.fair_spread:.0f}", styles["body"]),
            Paragraph(f"{mispricing:+.0f}", styles["body_bold"]),
            Paragraph(f"{a.conviction}/5", styles["body"]),
            Paragraph(a.catalyst[:55] if a.catalyst else "", styles["small"]),
        ])

    table_data = [header_row] + data_rows
    col_widths = [5.0 * (page_width - 3.6 * 28.35) / 28.35 / 15,  # rough calc
                  None, None, None, None, None]
    # Simpler: use proportional widths
    usable = page_width - 3.6 * 28.35  # 28.35 pts per cm
    col_widths = [
        usable * 0.25,  # entity
        usable * 0.10,  # current
        usable * 0.10,  # fair
        usable * 0.10,  # misprice
        usable * 0.08,  # conv
        usable * 0.37,  # catalyst
    ]

    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (1, 0), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), bg),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, divider),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, divider),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        # Color the mispricing column
        ("TEXTCOLOR", (3, 1), (3, -1), direction_color),
    ]))
    story.append(table)


# ---------------------------------------------------------------------------
# Send via Telegram
# ---------------------------------------------------------------------------

async def send_brief_telegram(message: str) -> bool:
    """Send the morning brief via Telegram."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        logger.warning("Telegram not configured (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)")
        return False

    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            )
            if resp.status == 200:
                logger.info("Morning brief sent to Telegram")
                return True
            else:
                error = await resp.text()
                logger.error(f"Telegram error: {error}")
                return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Morning Brief Agent")
    parser.add_argument(
        "--index", type=str, choices=["xover", "main"], default="xover",
        help="Index to load screen for (default: xover)",
    )
    parser.add_argument(
        "--screen-file", type=str, default=None,
        help="Path to specific screen Excel file (default: latest in outputs/)",
    )
    parser.add_argument(
        "--refresh", type=str, nargs="*", default=None,
        help="Re-run analyst on specific names before brief (e.g. --refresh 'Ardagh Group')",
    )
    parser.add_argument(
        "--no-telegram", action="store_true",
        help="Skip sending Telegram message",
    )
    parser.add_argument(
        "--no-pdf", action="store_true",
        help="Skip PDF generation",
    )
    parser.add_argument(
        "--filing-days", type=int, default=1,
        help="Days of filings to include (default: 1)",
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

    screen_date = os.path.basename(screen_path).replace(f"{args.index}_screen_", "").replace(".xlsx", "")
    print(f"Loading screen: {screen_path} (date: {screen_date})")

    # Load assessments
    assessments = load_assessments_from_excel(screen_path)
    print(f"Loaded {len(assessments)} assessments")

    # Optional: refresh specific names
    if args.refresh:
        from agents.analyst import assess_credit
        index_label = "Xover" if args.index == "xover" else "Main"
        for name in args.refresh:
            print(f"Refreshing analyst for {name}...")
            try:
                fresh = assess_credit(name, index_label)
                # Replace in assessments list
                assessments = [a for a in assessments if a.entity_name != fresh.entity_name]
                assessments.append(fresh)
                print(f"  -> {fresh.direction.value}, conviction {fresh.conviction}")
            except Exception as e:
                print(f"  -> FAILED: {e}")

    # Load recent filings
    filings = load_recent_filings(days=args.filing_days)
    print(f"Loaded {len(filings)} filings from last {args.filing_days} day(s)")

    # Build brief
    brief = build_brief(assessments, filings, screen_date)

    # --- Telegram ---
    if not args.no_telegram:
        tg_message = build_telegram_message(brief)
        print(f"\n{'='*60}")
        print("TELEGRAM MESSAGE PREVIEW:")
        print(f"{'='*60}")
        # Print plain-text version (strip HTML tags for terminal)
        import re
        plain = re.sub(r"<[^>]+>", "", tg_message)
        print(plain)
        print(f"{'='*60}\n")

        sent = asyncio.run(send_brief_telegram(tg_message))
        if sent:
            print("Telegram: sent successfully")
        else:
            print("Telegram: not sent (check config or connectivity)")

    # --- PDF ---
    if not args.no_pdf:
        print("Generating PDF brief...")
        filepath = generate_brief_pdf(brief)
        print(f"PDF saved: {filepath}")

    print("\nMorning brief complete.")


if __name__ == "__main__":
    main()

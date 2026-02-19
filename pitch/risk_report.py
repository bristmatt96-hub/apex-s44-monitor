"""
Weekly Risk Report Generator

Generates a multi-sheet Excel workbook with CDS-pricer-derived risk metrics
for every position in the latest strategist portfolio.

Sheets:
    1. Portfolio Summary  — Gross/net, total DV01/CS01/JTD, carry
    2. Position Risk      — Per-position risk analytics (sorted by JTD)
    3. Sector Concentration — Sector-level gross/net, DV01, JTD
    4. Stress Scenarios   — Strategist scenarios + parallel bump P&L
    5. Risk Limits        — Current vs limit, traffic-light status

Usage:
    python -m pitch.risk_report                    # Latest portfolio
    python -m pitch.risk_report --portfolio path   # Specific portfolio JSON
    python -m pitch.risk_report --notional 250     # Override NAV
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# CDS pricer imports
from analytics.cds_pricer import (
    cds_dv01,
    cds_cs01,
    implied_default_probability,
    jump_to_default,
    spread_to_upfront,
    _risky_annuity,
    price_cds,
)

OUTPUT_DIR = Path("outputs/risk")

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
SECTION_FONT = Font(bold=True, size=12, color="1F4E79")
LABEL_FONT = Font(bold=True, size=10)
LONG_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
SHORT_FILL = PatternFill(start_color="FCE4EC", end_color="FCE4EC", fill_type="solid")
GREEN_FILL = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")
AMBER_FILL = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
RED_FILL = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
THIN_BORDER = Border(bottom=Side(style="thin", color="CCCCCC"))
GREEN_FONT = Font(bold=True, color="28A745")
RED_FONT = Font(bold=True, color="DC3545")
AMBER_FONT = Font(bold=True, color="FFC107")
NUMBER_FMT_2DP = "#,##0.00"
NUMBER_FMT_0DP = "#,##0"
PCT_FMT = "0.0%"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def find_latest_portfolio() -> str | None:
    """Find the most recent portfolio JSON in outputs/portfolio/."""
    portfolio_dir = Path("outputs/portfolio")
    if not portfolio_dir.exists():
        return None

    candidates = sorted(
        portfolio_dir.glob("portfolio_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def load_portfolio(path: str) -> dict:
    """Load portfolio JSON."""
    with open(path) as f:
        return json.load(f)


def load_sector_mapping() -> dict[str, str]:
    """Load entity -> sector from xover_s44.json."""
    path = "indices/xover_s44.json"
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
# Risk calculations
# ---------------------------------------------------------------------------

def compute_position_risk(position: dict, nav_millions: float) -> dict:
    """Compute full CDS risk metrics for a single position.

    Returns dict with all risk fields needed for the workbook.
    """
    entity = position.get("entity_name", "Unknown")
    direction = position.get("direction", "LONG_RISK")
    size_pct = abs(position.get("size_pct", 0))
    notional_m = abs(position.get("notional_millions", 0))
    notional = notional_m * 1_000_000
    spread = position.get("current_spread", 0)
    fair_spread = position.get("fair_spread", 0)
    sector = position.get("sector", "")
    rating = position.get("estimated_rating", "")
    conviction = position.get("conviction", 0)

    # Protection buyer = SHORT_RISK (buy protection = profit when widening)
    is_prot_buyer = direction == "SHORT_RISK"

    # CDS pricer calculations
    dv01 = cds_dv01(spread, notional=notional) if spread > 0 else 0.0
    cs01 = cds_cs01(spread, notional=notional) if spread > 0 else 0.0
    jtd = jump_to_default(spread, notional=notional, is_protection_buyer=is_prot_buyer) if spread > 0 else 0.0
    pd_5y = implied_default_probability(spread) if spread > 0 else 0.0
    pu = spread_to_upfront(spread) if spread > 0 else 0.0
    rpv01 = _risky_annuity(spread) if spread > 0 else 0.0

    # Carry: for SHORT_RISK (prot buyer), you pay the running premium
    # For LONG_RISK (prot seller), you receive the running premium
    # Quarterly carry = notional * spread/10000 * 0.25
    annual_carry = notional * spread / 10_000
    if is_prot_buyer:
        annual_carry = -annual_carry  # paying premium

    # Signed DV01: positive means gains when spreads widen
    # SHORT_RISK (prot buyer) → positive DV01 (gains on widening)
    # LONG_RISK (prot seller) → negative DV01 (loses on widening)
    signed_dv01 = dv01 if is_prot_buyer else -dv01

    return {
        "entity_name": entity,
        "direction": direction,
        "size_pct": size_pct,
        "notional_m": notional_m,
        "notional": notional,
        "spread": spread,
        "fair_spread": fair_spread,
        "sector": sector,
        "rating": rating,
        "conviction": conviction,
        "dv01": dv01,
        "signed_dv01": signed_dv01,
        "cs01": cs01,
        "jtd": jtd,
        "abs_jtd": abs(jtd),
        "pd_5y": pd_5y,
        "pu": pu,
        "rpv01": rpv01,
        "annual_carry": annual_carry,
        "is_prot_buyer": is_prot_buyer,
        "jtd_pct_nav": abs(jtd) / (nav_millions * 1_000_000) * 100 if nav_millions > 0 else 0,
    }


def compute_stress_pnl(
    positions: list[dict],
    bump_bps: float,
) -> float:
    """Compute portfolio P&L for a parallel spread bump.

    bump_bps > 0 = widening, bump_bps < 0 = tightening.

    For each position:
        P&L = signed_DV01 * bump_bps
    (DV01 is per 1bp; multiply by bump size)
    """
    total_pnl = 0.0
    for p in positions:
        total_pnl += p["signed_dv01"] * bump_bps
    return total_pnl


# ---------------------------------------------------------------------------
# Excel generation
# ---------------------------------------------------------------------------

def _apply_header(ws, row, headers, col_start=1):
    """Apply styled headers to a worksheet row."""
    for col, h in enumerate(headers, col_start):
        cell = ws.cell(row=row, column=col, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _set_col_widths(ws, widths):
    """Set column widths from a list."""
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def generate_risk_report(portfolio: dict, nav_override: float | None = None) -> str:
    """Generate the full risk report Excel workbook.

    Args:
        portfolio: Portfolio dict from strategist output
        nav_override: Override NAV in millions (uses portfolio value if None)

    Returns:
        Path to saved Excel file
    """
    nav_m = nav_override or portfolio.get("nav_millions", 500.0)
    nav = nav_m * 1_000_000
    positions_raw = portfolio.get("top_positions", [])
    hedges = portfolio.get("hedges", [])
    stress_scenarios = portfolio.get("stress_scenarios", [])
    risk_summary = portfolio.get("risk_summary", {})
    sector_mapping = load_sector_mapping()

    # Enrich positions with sectors from index if missing
    for p in positions_raw:
        if not p.get("sector"):
            p["sector"] = sector_mapping.get(p.get("entity_name", ""), "Other")

    # Compute risk metrics for each position
    positions = [compute_position_risk(p, nav_m) for p in positions_raw]

    # Sort by absolute JTD (largest risk first) for Position Risk sheet
    positions_by_jtd = sorted(positions, key=lambda p: p["abs_jtd"], reverse=True)

    # Aggregates
    total_dv01 = sum(p["signed_dv01"] for p in positions)
    total_abs_dv01 = sum(p["dv01"] for p in positions)
    total_cs01 = sum(p["cs01"] for p in positions)
    total_jtd_long = sum(p["jtd"] for p in positions if not p["is_prot_buyer"])
    total_jtd_short = sum(p["jtd"] for p in positions if p["is_prot_buyer"])
    total_abs_jtd = sum(p["abs_jtd"] for p in positions)
    total_carry = sum(p["annual_carry"] for p in positions)
    max_single_jtd_pct = max((p["jtd_pct_nav"] for p in positions), default=0)

    long_positions = [p for p in positions if not p["is_prot_buyer"]]
    short_positions = [p for p in positions if p["is_prot_buyer"]]
    gross_notional = sum(p["notional"] for p in positions)
    long_notional = sum(p["notional"] for p in long_positions)
    short_notional = sum(p["notional"] for p in short_positions)
    net_notional = long_notional - short_notional

    # Create workbook
    wb = Workbook()
    today = datetime.now().strftime("%Y-%m-%d")

    # ========================================================================
    # Sheet 1: Portfolio Summary
    # ========================================================================
    ws1 = wb.active
    ws1.title = "Portfolio Summary"

    ws1.cell(row=1, column=1, value="CREDIT CATALYST — WEEKLY RISK REPORT").font = Font(
        bold=True, size=14, color="1F4E79")
    ws1.merge_cells("A1:F1")
    ws1.cell(row=2, column=1, value=f"Report Date: {today}").font = Font(
        size=10, color="778DA9")
    ws1.merge_cells("A2:F2")

    # --- Exposure Summary ---
    row = 4
    ws1.cell(row=row, column=1, value="EXPOSURE SUMMARY").font = SECTION_FONT
    ws1.merge_cells(f"A{row}:F{row}")
    row += 1
    _apply_header(ws1, row, ["Metric", "Value", "", "Metric", "Value", ""])

    metrics_left = [
        ("NAV ($M)", f"${nav_m:,.0f}"),
        ("Gross Exposure ($M)", f"${gross_notional / 1e6:,.1f}"),
        ("Net Exposure ($M)", f"${net_notional / 1e6:,.1f}"),
        ("Long Exposure ($M)", f"${long_notional / 1e6:,.1f}"),
        ("Short Exposure ($M)", f"${short_notional / 1e6:,.1f}"),
        ("Gross Exposure (%)", f"{risk_summary.get('gross_exposure_pct', gross_notional / nav * 100):.1f}%"),
        ("Net Exposure (%)", f"{risk_summary.get('net_exposure_pct', net_notional / nav * 100):+.1f}%"),
        ("Number of Positions", str(len(positions))),
    ]
    metrics_right = [
        ("Total DV01 (net)", f"${total_dv01:,.0f}"),
        ("Total DV01 (gross)", f"${total_abs_dv01:,.0f}"),
        ("Total CS01 (gross)", f"${total_cs01:,.0f}"),
        ("Total JTD Exposure (gross)", f"${total_abs_jtd:,.0f}"),
        ("Max Single-Name JTD (% NAV)", f"{max_single_jtd_pct:.2f}%"),
        ("JTD Long-Risk Positions", f"${abs(total_jtd_long):,.0f}"),
        ("JTD Short-Risk Positions", f"${total_jtd_short:,.0f}"),
        ("Annual Carry (net)", f"${total_carry:,.0f}"),
    ]

    for i, ((l_label, l_val), (r_label, r_val)) in enumerate(
        zip(metrics_left, metrics_right)
    ):
        r = row + 1 + i
        ws1.cell(row=r, column=1, value=l_label).font = LABEL_FONT
        ws1.cell(row=r, column=2, value=l_val)
        ws1.cell(row=r, column=4, value=r_label).font = LABEL_FONT
        ws1.cell(row=r, column=5, value=r_val)
        for c in range(1, 7):
            ws1.cell(row=r, column=c).border = THIN_BORDER

    # --- Portfolio Weighted Metrics ---
    row = row + 1 + len(metrics_left) + 1
    ws1.cell(row=row, column=1, value="PORTFOLIO WEIGHTED METRICS").font = SECTION_FONT
    ws1.merge_cells(f"A{row}:F{row}")
    row += 1

    # Weighted average spread
    total_weighted_spread = sum(p["spread"] * p["notional"] for p in positions)
    wavg_spread = total_weighted_spread / gross_notional if gross_notional > 0 else 0

    # Weighted avg PD
    wavg_pd = sum(p["pd_5y"] * p["notional"] for p in positions) / gross_notional if gross_notional > 0 else 0

    # DV01 per $1M gross
    dv01_per_mm = total_abs_dv01 / (gross_notional / 1e6) if gross_notional > 0 else 0

    portfolio_metrics = [
        ("Weighted Avg Spread (bps)", f"{wavg_spread:.0f}"),
        ("Weighted Avg 5Y Default Prob", f"{wavg_pd:.1%}"),
        ("Spread Duration (bps)", f"{risk_summary.get('spread_duration', wavg_spread):.0f}"),
        ("DV01 per $1M Gross", f"${dv01_per_mm:,.0f}"),
        ("Carry per $1M NAV", f"${total_carry / nav_m:,.0f}"),
        ("Avg Conviction", f"{risk_summary.get('avg_conviction', 0):.1f}"),
    ]
    for i, (label, val) in enumerate(portfolio_metrics):
        r = row + i
        ws1.cell(row=r, column=1, value=label).font = LABEL_FONT
        ws1.cell(row=r, column=2, value=val)
        for c in range(1, 7):
            ws1.cell(row=r, column=c).border = THIN_BORDER

    _set_col_widths(ws1, [30, 20, 4, 32, 22, 4])
    ws1.freeze_panes = "A4"

    # ========================================================================
    # Sheet 2: Position Risk
    # ========================================================================
    ws2 = wb.create_sheet("Position Risk")

    ws2.cell(row=1, column=1, value="POSITION RISK DETAIL (sorted by JTD exposure)").font = SECTION_FONT
    ws2.merge_cells("A1:L1")

    headers2 = [
        "Entity", "Direction", "Size %", "Notional $M", "Spread",
        "DV01 ($)", "CS01 ($)", "JTD ($)", "JTD % NAV",
        "5Y Def Prob", "PU (%)", "Rating",
    ]
    _apply_header(ws2, 2, headers2)

    for i, p in enumerate(positions_by_jtd):
        r = 3 + i
        ws2.cell(row=r, column=1, value=p["entity_name"])
        dir_cell = ws2.cell(row=r, column=2, value=p["direction"])
        ws2.cell(row=r, column=3, value=p["size_pct"])
        ws2.cell(row=r, column=4, value=round(p["notional_m"], 1))
        ws2.cell(row=r, column=5, value=round(p["spread"], 1))
        ws2.cell(row=r, column=6, value=round(p["dv01"], 0)).number_format = NUMBER_FMT_0DP
        ws2.cell(row=r, column=7, value=round(p["cs01"], 0)).number_format = NUMBER_FMT_0DP
        ws2.cell(row=r, column=8, value=round(p["jtd"], 0)).number_format = NUMBER_FMT_0DP
        ws2.cell(row=r, column=9, value=round(p["jtd_pct_nav"], 2)).number_format = NUMBER_FMT_2DP
        ws2.cell(row=r, column=10, value=round(p["pd_5y"] * 100, 1))
        ws2.cell(row=r, column=11, value=round(p["pu"], 1))
        ws2.cell(row=r, column=12, value=p["rating"])

        # Colour direction
        if p["direction"] == "LONG_RISK":
            dir_cell.fill = LONG_FILL
        else:
            dir_cell.fill = SHORT_FILL

        # Highlight high JTD % NAV
        jtd_cell = ws2.cell(row=r, column=9)
        if p["jtd_pct_nav"] > 1.5:
            jtd_cell.font = RED_FONT
        elif p["jtd_pct_nav"] > 1.0:
            jtd_cell.font = AMBER_FONT

        for c in range(1, len(headers2) + 1):
            ws2.cell(row=r, column=c).border = THIN_BORDER

    # Totals row
    total_row = 3 + len(positions_by_jtd)
    ws2.cell(row=total_row, column=1, value="TOTAL").font = LABEL_FONT
    ws2.cell(row=total_row, column=4, value=round(sum(p["notional_m"] for p in positions), 1)).font = LABEL_FONT
    ws2.cell(row=total_row, column=6, value=round(total_abs_dv01, 0)).font = LABEL_FONT
    ws2.cell(row=total_row, column=6).number_format = NUMBER_FMT_0DP
    ws2.cell(row=total_row, column=7, value=round(total_cs01, 0)).font = LABEL_FONT
    ws2.cell(row=total_row, column=7).number_format = NUMBER_FMT_0DP
    ws2.cell(row=total_row, column=8, value=round(sum(p["jtd"] for p in positions), 0)).font = LABEL_FONT
    ws2.cell(row=total_row, column=8).number_format = NUMBER_FMT_0DP
    for c in range(1, len(headers2) + 1):
        ws2.cell(row=total_row, column=c).border = Border(
            top=Side(style="medium", color="1F4E79"),
            bottom=Side(style="medium", color="1F4E79"),
        )

    _set_col_widths(ws2, [35, 14, 8, 12, 10, 12, 12, 14, 10, 10, 8, 8])
    ws2.freeze_panes = "A3"

    # ========================================================================
    # Sheet 3: Sector Concentration
    # ========================================================================
    ws3 = wb.create_sheet("Sector Concentration")

    ws3.cell(row=1, column=1, value="SECTOR CONCENTRATION").font = SECTION_FONT
    ws3.merge_cells("A1:H1")

    headers3 = [
        "Sector", "Gross $M", "Long $M", "Short $M", "Net $M",
        "Gross DV01", "JTD Exposure", "% of Gross",
    ]
    _apply_header(ws3, 2, headers3)

    # Aggregate by sector
    sector_data: dict[str, dict] = {}
    for p in positions:
        sec = p["sector"] or "Other"
        if sec not in sector_data:
            sector_data[sec] = {
                "gross": 0, "long": 0, "short": 0,
                "dv01": 0, "jtd": 0,
            }
        sd = sector_data[sec]
        sd["gross"] += p["notional_m"]
        if not p["is_prot_buyer"]:
            sd["long"] += p["notional_m"]
        else:
            sd["short"] += p["notional_m"]
        sd["dv01"] += p["dv01"]
        sd["jtd"] += p["abs_jtd"]

    total_gross_m = sum(p["notional_m"] for p in positions)

    row = 3
    for sec, sd in sorted(sector_data.items(), key=lambda x: -x[1]["gross"]):
        net = sd["long"] - sd["short"]
        pct_gross = sd["gross"] / total_gross_m * 100 if total_gross_m > 0 else 0

        ws3.cell(row=row, column=1, value=sec)
        ws3.cell(row=row, column=2, value=round(sd["gross"], 1))
        ws3.cell(row=row, column=3, value=round(sd["long"], 1))
        ws3.cell(row=row, column=4, value=round(sd["short"], 1))
        net_cell = ws3.cell(row=row, column=5, value=round(net, 1))
        if net > 0:
            net_cell.font = GREEN_FONT
        elif net < 0:
            net_cell.font = RED_FONT
        ws3.cell(row=row, column=6, value=round(sd["dv01"], 0)).number_format = NUMBER_FMT_0DP
        ws3.cell(row=row, column=7, value=round(sd["jtd"], 0)).number_format = NUMBER_FMT_0DP
        pct_cell = ws3.cell(row=row, column=8, value=round(pct_gross, 1))
        if pct_gross > 25:
            pct_cell.font = RED_FONT
        for c in range(1, len(headers3) + 1):
            ws3.cell(row=row, column=c).border = THIN_BORDER
        row += 1

    # Totals
    ws3.cell(row=row, column=1, value="TOTAL").font = LABEL_FONT
    ws3.cell(row=row, column=2, value=round(total_gross_m, 1)).font = LABEL_FONT
    ws3.cell(row=row, column=3, value=round(sum(p["notional_m"] for p in long_positions), 1)).font = LABEL_FONT
    ws3.cell(row=row, column=4, value=round(sum(p["notional_m"] for p in short_positions), 1)).font = LABEL_FONT
    ws3.cell(row=row, column=6, value=round(total_abs_dv01, 0)).font = LABEL_FONT
    ws3.cell(row=row, column=6).number_format = NUMBER_FMT_0DP
    ws3.cell(row=row, column=7, value=round(total_abs_jtd, 0)).font = LABEL_FONT
    ws3.cell(row=row, column=7).number_format = NUMBER_FMT_0DP
    for c in range(1, len(headers3) + 1):
        ws3.cell(row=row, column=c).border = Border(
            top=Side(style="medium", color="1F4E79"),
            bottom=Side(style="medium", color="1F4E79"),
        )

    _set_col_widths(ws3, [22, 12, 12, 12, 12, 14, 16, 12])
    ws3.freeze_panes = "A3"

    # ========================================================================
    # Sheet 4: Stress Scenarios
    # ========================================================================
    ws4 = wb.create_sheet("Stress Scenarios")

    ws4.cell(row=1, column=1, value="STRESS SCENARIOS").font = SECTION_FONT
    ws4.merge_cells("A1:E1")

    headers4 = ["Scenario", "Description", "P&L ($)", "P&L (bps)", "P&L ($M)"]
    _apply_header(ws4, 2, headers4)

    row = 3

    # Strategist scenarios (3)
    ws4.cell(row=row, column=1, value="PM-DEFINED SCENARIOS").font = Font(
        bold=True, size=10, color="1F4E79", italic=True)
    ws4.merge_cells(f"A{row}:E{row}")
    row += 1

    for s in stress_scenarios:
        pnl_bps = s.get("estimated_pnl_bps", 0)
        pnl_m = s.get("estimated_pnl_millions", 0)
        pnl_dollars = pnl_m * 1_000_000

        ws4.cell(row=row, column=1, value=s.get("scenario", ""))
        ws4.cell(row=row, column=2, value=s.get("description", ""))
        ws4.cell(row=row, column=2).alignment = Alignment(wrap_text=True)

        for col, val in [(3, pnl_dollars), (4, pnl_bps), (5, pnl_m)]:
            cell = ws4.cell(row=row, column=col, value=round(val, 2))
            cell.number_format = NUMBER_FMT_2DP if col == 5 else NUMBER_FMT_0DP
            cell.font = RED_FONT if val < 0 else GREEN_FONT

        for c in range(1, len(headers4) + 1):
            ws4.cell(row=row, column=c).border = THIN_BORDER
        row += 1

    # DV01-based parallel bump scenarios
    row += 1
    ws4.cell(row=row, column=1, value="DV01-BASED PARALLEL SCENARIOS").font = Font(
        bold=True, size=10, color="1F4E79", italic=True)
    ws4.merge_cells(f"A{row}:E{row}")
    row += 1

    dv01_scenarios = [
        ("+100bp parallel widening", "All spreads widen 100bps simultaneously", 100),
        ("-50bp parallel tightening", "All spreads tighten 50bps simultaneously", -50),
        ("+200bp parallel widening", "Severe stress: all spreads widen 200bps", 200),
        ("+50bp parallel widening", "Mild stress: all spreads widen 50bps", 50),
    ]

    for name, desc, bump in dv01_scenarios:
        pnl = compute_stress_pnl(positions, bump)
        pnl_bps = pnl / nav * 10_000 if nav > 0 else 0
        pnl_m = pnl / 1_000_000

        ws4.cell(row=row, column=1, value=name)
        ws4.cell(row=row, column=2, value=desc)
        ws4.cell(row=row, column=2).alignment = Alignment(wrap_text=True)

        for col, val in [(3, pnl), (4, pnl_bps), (5, pnl_m)]:
            cell = ws4.cell(row=row, column=col, value=round(val, 2))
            cell.number_format = NUMBER_FMT_2DP if col == 5 else NUMBER_FMT_0DP
            cell.font = RED_FONT if val < 0 else GREEN_FONT

        for c in range(1, len(headers4) + 1):
            ws4.cell(row=row, column=c).border = THIN_BORDER
        row += 1

    # Per-position stress detail for +100bp
    row += 1
    ws4.cell(row=row, column=1, value="PER-POSITION P&L: +100bp Widening").font = Font(
        bold=True, size=10, color="1F4E79", italic=True)
    ws4.merge_cells(f"A{row}:E{row}")
    row += 1
    _apply_header(ws4, row, ["Entity", "Direction", "DV01", "P&L +100bp", "P&L % NAV"])
    row += 1

    for p in positions_by_jtd:
        pnl_100 = p["signed_dv01"] * 100
        pnl_pct_nav = pnl_100 / nav * 100 if nav > 0 else 0

        ws4.cell(row=row, column=1, value=p["entity_name"])
        ws4.cell(row=row, column=2, value=p["direction"])
        ws4.cell(row=row, column=3, value=round(p["signed_dv01"], 0)).number_format = NUMBER_FMT_0DP
        pnl_cell = ws4.cell(row=row, column=4, value=round(pnl_100, 0))
        pnl_cell.number_format = NUMBER_FMT_0DP
        pnl_cell.font = GREEN_FONT if pnl_100 >= 0 else RED_FONT
        pct_cell = ws4.cell(row=row, column=5, value=round(pnl_pct_nav, 3))
        pct_cell.font = GREEN_FONT if pnl_100 >= 0 else RED_FONT
        for c in range(1, 6):
            ws4.cell(row=row, column=c).border = THIN_BORDER
        row += 1

    _set_col_widths(ws4, [34, 50, 16, 14, 14])
    ws4.freeze_panes = "A3"

    # ========================================================================
    # Sheet 5: Risk Limits
    # ========================================================================
    ws5 = wb.create_sheet("Risk Limits")

    ws5.cell(row=1, column=1, value="RISK LIMITS — TRAFFIC LIGHT STATUS").font = SECTION_FONT
    ws5.merge_cells("A1:F1")

    headers5 = ["Constraint", "Current", "Limit", "Headroom", "Utilisation", "Status"]
    _apply_header(ws5, 2, headers5)

    # Define risk limits and current values
    gross_pct = risk_summary.get("gross_exposure_pct", gross_notional / nav * 100)
    net_pct = risk_summary.get("net_exposure_pct", net_notional / nav * 100)
    largest_pos = risk_summary.get("largest_position_pct", max(
        (p["size_pct"] for p in positions), default=0))

    # Sector concentration (worst sector)
    worst_sector_pct = max(
        (sd["gross"] / total_gross_m * 100 for sd in sector_data.values()),
        default=0,
    ) if total_gross_m > 0 else 0
    worst_sector_name = max(sector_data, key=lambda s: sector_data[s]["gross"]) if sector_data else "N/A"

    # Max JTD as % NAV
    max_jtd_name = max(positions, key=lambda p: p["jtd_pct_nav"])["entity_name"] if positions else "N/A"

    limits = [
        {
            "name": "Max Single-Name Exposure",
            "current": f"{largest_pos:.1f}%",
            "limit": "5.0%",
            "current_val": largest_pos,
            "limit_val": 5.0,
            "direction": "below",  # must be below limit
        },
        {
            "name": f"Sector Concentration ({worst_sector_name})",
            "current": f"{worst_sector_pct:.1f}%",
            "limit": "25.0%",
            "current_val": worst_sector_pct,
            "limit_val": 25.0,
            "direction": "below",
        },
        {
            "name": "Gross Exposure (upper)",
            "current": f"{gross_pct:.1f}%",
            "limit": "200.0%",
            "current_val": gross_pct,
            "limit_val": 200.0,
            "direction": "below",
        },
        {
            "name": "Gross Exposure (lower)",
            "current": f"{gross_pct:.1f}%",
            "limit": "80.0%",
            "current_val": gross_pct,
            "limit_val": 80.0,
            "direction": "above",  # must be above limit
        },
        {
            "name": "Net Exposure (upper)",
            "current": f"{net_pct:+.1f}%",
            "limit": "+50.0%",
            "current_val": net_pct,
            "limit_val": 50.0,
            "direction": "below",
        },
        {
            "name": "Net Exposure (lower)",
            "current": f"{net_pct:+.1f}%",
            "limit": "-30.0%",
            "current_val": net_pct,
            "limit_val": -30.0,
            "direction": "above",
        },
        {
            "name": "Minimum Positions",
            "current": str(len(positions)),
            "limit": "10",
            "current_val": float(len(positions)),
            "limit_val": 10.0,
            "direction": "above",
        },
        {
            "name": f"Max Single-Name JTD % NAV ({max_jtd_name[:20]})",
            "current": f"{max_single_jtd_pct:.2f}%",
            "limit": "2.0%",
            "current_val": max_single_jtd_pct,
            "limit_val": 2.0,
            "direction": "below",
        },
        {
            "name": "Drawdown Review Trigger",
            "current": f"{portfolio.get('risk_summary', {}).get('current_drawdown', 0.0):.1f}%",
            "limit": "5.0%",
            "current_val": 0.0,
            "limit_val": 5.0,
            "direction": "below",
        },
        {
            "name": "Drawdown Hard Stop",
            "current": f"{portfolio.get('risk_summary', {}).get('current_drawdown', 0.0):.1f}%",
            "limit": "7.5%",
            "current_val": 0.0,
            "limit_val": 7.5,
            "direction": "below",
        },
    ]

    row = 3
    for lim in limits:
        cur = lim["current_val"]
        limit_v = lim["limit_val"]
        direction = lim["direction"]

        # Calculate headroom and utilisation
        if direction == "below":
            headroom = limit_v - cur
            utilisation = cur / limit_v * 100 if limit_v != 0 else 0
        else:
            headroom = cur - limit_v
            utilisation = limit_v / cur * 100 if cur != 0 else 0

        # Traffic light
        if direction == "below":
            if cur > limit_v:
                status = "RED"
            elif cur > limit_v * 0.85:
                status = "AMBER"
            else:
                status = "GREEN"
        else:  # "above"
            if cur < limit_v:
                status = "RED"
            elif cur < limit_v * 1.15:
                status = "AMBER"
            else:
                status = "GREEN"

        ws5.cell(row=row, column=1, value=lim["name"])
        ws5.cell(row=row, column=2, value=lim["current"])
        ws5.cell(row=row, column=3, value=lim["limit"])
        ws5.cell(row=row, column=4, value=f"{headroom:+.1f}")
        ws5.cell(row=row, column=5, value=f"{utilisation:.0f}%")

        status_cell = ws5.cell(row=row, column=6, value=status)
        if status == "GREEN":
            status_cell.font = GREEN_FONT
            status_cell.fill = GREEN_FILL
        elif status == "AMBER":
            status_cell.font = AMBER_FONT
            status_cell.fill = AMBER_FILL
        else:
            status_cell.font = RED_FONT
            status_cell.fill = RED_FILL

        for c in range(1, len(headers5) + 1):
            ws5.cell(row=row, column=c).border = THIN_BORDER
        row += 1

    # Legend
    row += 2
    ws5.cell(row=row, column=1, value="LEGEND").font = SECTION_FONT
    row += 1
    ws5.cell(row=row, column=1, value="GREEN").font = GREEN_FONT
    ws5.cell(row=row, column=1).fill = GREEN_FILL
    ws5.cell(row=row, column=2, value="Within limits (< 85% utilisation)")
    row += 1
    ws5.cell(row=row, column=1, value="AMBER").font = AMBER_FONT
    ws5.cell(row=row, column=1).fill = AMBER_FILL
    ws5.cell(row=row, column=2, value="Approaching limit (85-100% utilisation)")
    row += 1
    ws5.cell(row=row, column=1, value="RED").font = RED_FONT
    ws5.cell(row=row, column=1).fill = RED_FILL
    ws5.cell(row=row, column=2, value="BREACH — limit exceeded (> 100% utilisation)")

    _set_col_widths(ws5, [38, 14, 14, 12, 12, 10])
    ws5.freeze_panes = "A3"

    # Save workbook
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filepath = str(OUTPUT_DIR / f"risk_report_{date_str}.xlsx")
    wb.save(filepath)

    return filepath


# ---------------------------------------------------------------------------
# Terminal summary
# ---------------------------------------------------------------------------

def print_summary(portfolio: dict, positions: list[dict], filepath: str, nav_m: float):
    """Print a concise terminal summary of the risk report."""
    nav = nav_m * 1_000_000

    total_dv01 = sum(p["signed_dv01"] for p in positions)
    total_abs_dv01 = sum(p["dv01"] for p in positions)
    total_cs01 = sum(p["cs01"] for p in positions)
    total_abs_jtd = sum(p["abs_jtd"] for p in positions)
    max_jtd_pct = max((p["jtd_pct_nav"] for p in positions), default=0)
    total_carry = sum(p["annual_carry"] for p in positions)

    # Stress P&L
    pnl_100 = compute_stress_pnl(positions, 100)
    pnl_neg50 = compute_stress_pnl(positions, -50)

    print(f"\n{'='*70}")
    print("  CREDIT CATALYST — WEEKLY RISK REPORT")
    print(f"{'='*70}")
    print(f"  NAV:                    ${nav_m:,.0f}M")
    print(f"  Positions:              {len(positions)}")
    print(f"  Total DV01 (net):       ${total_dv01:+,.0f}")
    print(f"  Total DV01 (gross):     ${total_abs_dv01:,.0f}")
    print(f"  Total CS01 (gross):     ${total_cs01:,.0f}")
    print(f"  Total JTD (gross):      ${total_abs_jtd:,.0f}")
    print(f"  Max Single JTD % NAV:   {max_jtd_pct:.2f}%")
    print(f"  Annual Carry (net):     ${total_carry:+,.0f}")
    print(f"  +100bp stress P&L:      ${pnl_100:+,.0f} ({pnl_100/nav*10000:+.1f}bps)")
    print(f"  -50bp stress P&L:       ${pnl_neg50:+,.0f} ({pnl_neg50/nav*10000:+.1f}bps)")
    print()

    # Top 5 by JTD
    print("  TOP 5 BY JTD EXPOSURE:")
    positions_by_jtd = sorted(positions, key=lambda p: p["abs_jtd"], reverse=True)
    for p in positions_by_jtd[:5]:
        tag = "S" if p["is_prot_buyer"] else "L"
        print(f"    [{tag}] {p['entity_name'][:30]:<32} "
              f"JTD=${p['abs_jtd']/1e6:.2f}M  "
              f"({p['jtd_pct_nav']:.2f}% NAV)  "
              f"DV01=${p['dv01']:,.0f}")

    print(f"\n  Report saved: {filepath}")
    print(f"{'='*70}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Weekly Risk Report Generator")
    parser.add_argument(
        "--portfolio", type=str, default=None,
        help="Path to portfolio JSON (default: latest in outputs/portfolio/)",
    )
    parser.add_argument(
        "--notional", type=float, default=None,
        help="Override NAV in millions (default: from portfolio JSON)",
    )
    args = parser.parse_args()

    # Find portfolio
    if args.portfolio:
        portfolio_path = args.portfolio
    else:
        portfolio_path = find_latest_portfolio()

    if not portfolio_path or not os.path.exists(portfolio_path):
        print("Error: No portfolio JSON found. Run agents/strategist.py first.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Loading portfolio: {portfolio_path}")
    portfolio = load_portfolio(portfolio_path)

    nav_m = args.notional or portfolio.get("nav_millions", 500.0)
    positions_raw = portfolio.get("top_positions", [])
    print(f"Found {len(positions_raw)} positions, NAV=${nav_m:.0f}M")

    # Compute risk
    print("Computing CDS risk metrics...")
    positions = [compute_position_risk(p, nav_m) for p in positions_raw]

    # Generate Excel
    print("Generating risk report Excel...")
    filepath = generate_risk_report(portfolio, nav_override=args.notional)

    # Print summary
    print_summary(portfolio, positions, filepath, nav_m)


if __name__ == "__main__":
    main()

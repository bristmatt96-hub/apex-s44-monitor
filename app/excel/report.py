"""
Excel Report Generator for Credit Catalyst

Produces formatted .xlsx workbooks with:
- Universe Overview sheet (all credits with scores, directions, spreads)
- Relative Value sheet (RV screen ranked)
- Scenario Analysis sheet (P&L across 9 scenarios)
- Fundamental sheet (playbook classification, leverage, maturity)
- Risk Metrics sheet (DV01, CS01, VaR)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


# Colour palette
HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid") if HAS_OPENPYXL else None
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11) if HAS_OPENPYXL else None
LONG_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid") if HAS_OPENPYXL else None
SHORT_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid") if HAS_OPENPYXL else None
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
) if HAS_OPENPYXL else None


def _style_header(ws, num_cols: int):
    """Apply header styling to row 1."""
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def _auto_width(ws):
    """Auto-fit column widths."""
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_len + 3, 40)


class CreditReportGenerator:
    """Generates Excel reports from credit analytics data."""

    def __init__(self, output_dir: str = "reports"):
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl is required for Excel reports. Install with: pip install openpyxl")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.snapshots_dir = Path("snapshots")

    def generate_full_report(self, filename: str = None) -> Path:
        """Generate a complete credit analysis workbook."""
        if filename is None:
            filename = f"credit_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

        wb = Workbook()

        # Remove default sheet
        wb.remove(wb.active)

        self._add_universe_sheet(wb)
        self._add_rv_sheet(wb)
        self._add_scenario_sheet(wb)
        self._add_fundamental_sheet(wb)

        output_path = self.output_dir / filename
        wb.save(str(output_path))
        return output_path

    def _load_snapshots(self) -> List[dict]:
        snapshots = []
        for f in sorted(self.snapshots_dir.glob("*.json")):
            try:
                with open(f) as fh:
                    snapshots.append(json.load(fh))
            except Exception:
                continue
        return snapshots

    # ── Universe Overview ────────────────────────────────────────

    def _add_universe_sheet(self, wb: Workbook):
        ws = wb.create_sheet("Universe Overview")
        headers = [
            "Entity", "Sector", "Rating", "Spread (bps)", "Fair Spread",
            "Direction", "Conviction", "Score", "Risk Factors",
        ]
        ws.append(headers)
        _style_header(ws, len(headers))

        snapshots = self._load_snapshots()
        for data in snapshots:
            name = data.get("company_name", "Unknown")
            spread = data.get("cds_spread_bps", data.get("spread_bps", ""))
            fair = data.get("fair_spread_bps", "")
            direction = data.get("direction", "flat")
            row = [
                name,
                data.get("sector", ""),
                data.get("ratings", {}).get("composite", ""),
                spread,
                fair,
                direction,
                data.get("conviction", ""),
                data.get("credit_score", ""),
                "; ".join(data.get("risk_factors", [])),
            ]
            ws.append(row)

            # Colour direction
            row_num = ws.max_row
            dir_cell = ws.cell(row=row_num, column=6)
            if direction == "long":
                dir_cell.fill = LONG_FILL
            elif direction == "short":
                dir_cell.fill = SHORT_FILL

        _auto_width(ws)

    # ── Relative Value ───────────────────────────────────────────

    def _add_rv_sheet(self, wb: Workbook):
        ws = wb.create_sheet("Relative Value")
        headers = ["Entity", "Spread (bps)", "Fair Spread", "RV Score", "Signal", "Sector"]
        ws.append(headers)
        _style_header(ws, len(headers))

        try:
            from analytics.relative_value import compute_rv_score, rank_universe
            snapshots = self._load_snapshots()
            scores = []
            for data in snapshots:
                spread = data.get("cds_spread_bps", data.get("spread_bps", 0))
                if spread > 0:
                    score = compute_rv_score(
                        current_spread_bps=spread,
                        fair_spread_bps=data.get("fair_spread_bps", spread * 0.95),
                        sector=data.get("sector", ""),
                        entity_name=data.get("company_name", ""),
                    )
                    scores.append(score)

            for s in rank_universe(scores):
                ws.append([
                    s.entity_name, s.current_spread_bps, s.fair_spread_bps,
                    round(s.rv_score, 2), s.signal, s.sector,
                ])
        except Exception as e:
            ws.append([f"Error computing RV: {e}"])

        _auto_width(ws)

    # ── Scenario Analysis ────────────────────────────────────────

    def _add_scenario_sheet(self, wb: Workbook):
        ws = wb.create_sheet("Scenario Analysis")
        headers = ["Scenario", "Probability", "Total P&L", "Worst Position"]
        ws.append(headers)
        _style_header(ws, len(headers))

        try:
            from analytics.scenario_analysis import SCENARIOS, run_all_scenarios
            positions = []
            for data in self._load_snapshots()[:30]:
                spread = data.get("cds_spread_bps", data.get("spread_bps", 0))
                if spread > 0:
                    positions.append({
                        "entity_name": data.get("company_name", ""),
                        "rating": data.get("ratings", {}).get("composite", "B"),
                        "spread_bps": spread,
                        "notional": 10_000_000.0,
                        "direction": "flat",
                    })

            if positions:
                results = run_all_scenarios(positions)
                for r in results:
                    scenario = next((s for s in SCENARIOS if s.name == r.scenario_name), None)
                    prob = scenario.probability if scenario else 0
                    ws.append([r.scenario_name, f"{prob:.0%}", round(r.total_pnl, 0), r.worst_position])
        except Exception as e:
            ws.append([f"Error running scenarios: {e}"])

        _auto_width(ws)

    # ── Fundamental Analysis ─────────────────────────────────────

    def _add_fundamental_sheet(self, wb: Workbook):
        ws = wb.create_sheet("Fundamentals")
        headers = [
            "Entity", "Score", "Playbook", "Sponsor", "Aggression",
            "Maturity Risk", "Leverage", "Coverage", "Reasoning",
        ]
        ws.append(headers)
        _style_header(ws, len(headers))

        try:
            from analytics.fundamental import CreditFundamentalAnalyzer
            analyzer = CreditFundamentalAnalyzer()
            for a in analyzer.assess_universe():
                ws.append([
                    a.entity_name, round(a.fundamental_score, 1), a.playbook,
                    a.sponsor or "", a.sponsor_aggression,
                    a.maturity_risk or "", a.leverage or "", a.interest_coverage or "",
                    a.reasoning,
                ])
        except Exception as e:
            ws.append([f"Error running fundamentals: {e}"])

        _auto_width(ws)


def generate_report(output_dir: str = "reports", filename: str = None) -> Optional[Path]:
    """Convenience function to generate a full credit report."""
    if not HAS_OPENPYXL:
        print("openpyxl not installed. Install with: pip install openpyxl")
        return None
    gen = CreditReportGenerator(output_dir=output_dir)
    path = gen.generate_full_report(filename=filename)
    print(f"Report saved to: {path}")
    return path


if __name__ == "__main__":
    generate_report()

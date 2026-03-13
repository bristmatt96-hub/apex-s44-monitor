"""
Credit Fundamental Analyzer

Combines sponsor analysis, maturity wall risk, leverage metrics,
and sector positioning into a unified fundamental assessment
for iTraxx Main and Crossover constituents.
"""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal

PlaybookType = Literal["A", "B", "MIXED", "MONITOR", "LOW_RISK", "UNKNOWN"]


@dataclass
class FundamentalAssessment:
    """Output of fundamental credit analysis."""
    entity_name: str
    timestamp: str
    # Sponsor analysis
    sponsor: Optional[str] = None
    sponsor_aggression: int = 0
    # Maturity risk
    maturity_risk: Optional[str] = None
    maturity_notes: Optional[str] = None
    # Leverage & coverage (from snapshot)
    leverage: Optional[float] = None          # Net Debt / EBITDA
    interest_coverage: Optional[float] = None  # EBITDA / Interest
    free_cash_flow_yield: Optional[float] = None
    # Sector
    sector: Optional[str] = None
    rating: Optional[str] = None
    # Playbook classification
    playbook: PlaybookType = "UNKNOWN"
    reasoning: str = ""
    # Composite fundamental score 0-100
    fundamental_score: float = 50.0
    risk_factors: List[str] = field(default_factory=list)


class CreditFundamentalAnalyzer:
    """
    Analyses fundamental credit quality by combining:
    - Sponsor aggression (PE overlay risk)
    - Maturity wall pressure
    - Leverage and coverage ratios from snapshots
    - Sector-relative positioning
    """

    def __init__(self, data_path: str = None):
        if data_path is None:
            data_path = Path(__file__).parent.parent / "data"
        else:
            data_path = Path(data_path)

        self.data_path = data_path
        self.sponsors_path = data_path / "sponsors.json"
        self.maturity_path = data_path / "maturity_wall.json"
        self.xover_path = data_path.parent / "indices" / "xover_s44.json"
        self.snapshots_dir = data_path.parent / "snapshots"

        self.sponsors_data = self._load_json(self.sponsors_path)
        self.maturity_data = self._load_json(self.maturity_path)
        self.xover_data = self._load_json(self.xover_path)

    def _load_json(self, path: Path) -> dict:
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    def _load_snapshot(self, company: str) -> Optional[dict]:
        """Load the snapshot JSON for a company if it exists."""
        if not self.snapshots_dir.exists():
            return None
        company_lower = company.lower()
        for f in self.snapshots_dir.glob("*.json"):
            if company_lower in f.stem.lower():
                with open(f) as fh:
                    return json.load(fh)
            try:
                with open(f) as fh:
                    data = json.load(fh)
                if data.get("company_name", "").lower() == company_lower:
                    return data
            except Exception:
                continue
        return None

    # ── Sponsor Analysis ─────────────────────────────────────────

    def get_sponsor_aggression(self, company: str) -> tuple:
        """Return (sponsor_name, aggression_score) or (None, 0)."""
        xo_mapping = self.sponsors_data.get("xo_s44_sponsor_mapping", {})
        company_lower = company.lower()

        for risk_level in ["high_risk", "medium_risk", "lower_risk_pe",
                           "public_companies", "stressed_real_estate"]:
            for entry in xo_mapping.get(risk_level, []):
                entry_company = entry.get("company", "") if isinstance(entry, dict) else ""
                if company_lower in entry_company.lower():
                    return entry.get("sponsor", "Unknown"), entry.get("aggression_score", 5)
        return None, 0

    # ── Maturity Wall ────────────────────────────────────────────

    def get_maturity_risk(self, company: str) -> tuple:
        """Return (risk_level, notes) or (None, None)."""
        maturity_profiles = self.maturity_data.get("xo_s44_maturity_profiles", {})
        company_lower = company.lower()

        for period in ["2025_2026_critical", "2027_maturities", "2028_maturities"]:
            for entry in maturity_profiles.get(period, []):
                if company_lower in entry.get("company", "").lower():
                    return entry.get("refinancing_risk", "unknown"), entry.get("concern", "")

        for entry in maturity_profiles.get("maturities_addressed", []):
            if company_lower in entry.get("company", "").lower():
                return entry.get("refinancing_risk", "low"), entry.get("notes", "Maturities addressed")

        for entry in maturity_profiles.get("no_near_term_concerns", []):
            if company_lower in entry.get("company", "").lower():
                return entry.get("refinancing_risk", "low"), entry.get("notes", "No near-term concerns")

        for entry in self.maturity_data.get("watch_list_priority", []):
            if company_lower in entry.get("company", "").lower():
                return "high", entry.get("reason", "")

        return None, None

    # ── Leverage & Coverage ──────────────────────────────────────

    def _extract_financials(self, snapshot: dict) -> dict:
        """Pull leverage metrics from a snapshot."""
        financials = snapshot.get("financials", snapshot.get("financial_metrics", {}))
        return {
            "leverage": financials.get("net_debt_ebitda", financials.get("leverage")),
            "interest_coverage": financials.get("interest_coverage"),
            "fcf_yield": financials.get("free_cash_flow_yield", financials.get("fcf_yield")),
            "revenue_growth": financials.get("revenue_growth"),
        }

    # ── Scoring ──────────────────────────────────────────────────

    def _score_leverage(self, leverage: Optional[float]) -> float:
        """Score leverage 0-100 (higher = healthier)."""
        if leverage is None:
            return 50.0
        if leverage <= 2.0:
            return 90.0
        if leverage <= 4.0:
            return 70.0
        if leverage <= 6.0:
            return 45.0
        if leverage <= 8.0:
            return 25.0
        return 10.0

    def _score_coverage(self, coverage: Optional[float]) -> float:
        if coverage is None:
            return 50.0
        if coverage >= 5.0:
            return 90.0
        if coverage >= 3.0:
            return 70.0
        if coverage >= 1.5:
            return 45.0
        if coverage >= 1.0:
            return 25.0
        return 10.0

    def _score_maturity(self, risk: Optional[str]) -> float:
        mapping = {"low": 85.0, "medium": 55.0, "high": 25.0, "very_high": 10.0}
        return mapping.get(risk, 50.0)

    def _score_sponsor(self, aggression: int) -> float:
        if aggression == 0:
            return 60.0  # no sponsor data
        return max(10.0, 100.0 - aggression * 10)

    # ── Classification ───────────────────────────────────────────

    def _classify_playbook(self, aggression: int, maturity_risk: Optional[str],
                           sponsor: Optional[str]) -> tuple:
        """Return (playbook, reasoning) using the original Playbook A/B logic."""
        if aggression >= 7:
            return "A", (
                f"High aggression sponsor ({sponsor}, score {aggression}/10). "
                "Timing treacherous — equity may spike before collapse."
            )
        if maturity_risk in ("high", "very_high"):
            return "B", (
                f"Maturity wall stress ({maturity_risk}). "
                "More predictable deterioration path."
            )
        if aggression >= 5 and maturity_risk in ("medium", "high"):
            return "MIXED", (
                f"Moderate sponsor aggression ({aggression}/10) + "
                f"maturity pressure ({maturity_risk})."
            )
        if sponsor and aggression <= 4:
            if maturity_risk in ("high", "very_high"):
                return "B", f"Low aggression sponsor + high maturity pressure ({maturity_risk})."
            if maturity_risk == "medium":
                return "MONITOR", f"Low aggression sponsor with medium maturity risk."
            return "LOW_RISK", "Low aggression sponsor, low maturity risk."
        return "UNKNOWN", "Insufficient data to classify."

    # ── Public API ───────────────────────────────────────────────

    def assess(self, company: str) -> FundamentalAssessment:
        """Run full fundamental assessment for a single name."""
        sponsor, aggression = self.get_sponsor_aggression(company)
        maturity_risk, maturity_notes = self.get_maturity_risk(company)
        snapshot = self._load_snapshot(company)

        financials = self._extract_financials(snapshot) if snapshot else {}
        leverage = financials.get("leverage")
        coverage = financials.get("interest_coverage")
        fcf_yield = financials.get("fcf_yield")

        sector = (snapshot or {}).get("sector", "")
        rating = (snapshot or {}).get("ratings", {}).get("composite", "")

        playbook, reasoning = self._classify_playbook(aggression, maturity_risk, sponsor)

        # Composite score: weighted average of sub-scores
        lev_score = self._score_leverage(leverage)
        cov_score = self._score_coverage(coverage)
        mat_score = self._score_maturity(maturity_risk)
        spo_score = self._score_sponsor(aggression)

        fundamental_score = (
            0.30 * lev_score +
            0.25 * cov_score +
            0.25 * mat_score +
            0.20 * spo_score
        )

        risk_factors = []
        if leverage is not None and leverage > 6.0:
            risk_factors.append(f"High leverage ({leverage:.1f}x)")
        if coverage is not None and coverage < 2.0:
            risk_factors.append(f"Weak interest coverage ({coverage:.1f}x)")
        if maturity_risk in ("high", "very_high"):
            risk_factors.append(f"Maturity wall pressure ({maturity_risk})")
        if aggression >= 7:
            risk_factors.append(f"Aggressive sponsor ({sponsor}, {aggression}/10)")

        return FundamentalAssessment(
            entity_name=company,
            timestamp=datetime.now().isoformat(),
            sponsor=sponsor,
            sponsor_aggression=aggression,
            maturity_risk=maturity_risk,
            maturity_notes=maturity_notes,
            leverage=leverage,
            interest_coverage=coverage,
            free_cash_flow_yield=fcf_yield,
            sector=sector,
            rating=rating,
            playbook=playbook,
            reasoning=reasoning,
            fundamental_score=fundamental_score,
            risk_factors=risk_factors,
        )

    def assess_universe(self) -> List[FundamentalAssessment]:
        """Assess all iTraxx Crossover S44 constituents."""
        results = []
        if not self.xover_data:
            return results
        sectors = self.xover_data.get("sectors", {})
        for sector, companies in sectors.items():
            for company in companies:
                assessment = self.assess(company)
                if not assessment.sector:
                    assessment.sector = sector
                results.append(assessment)
        return results

    def get_summary(self) -> Dict:
        """Summarise universe by playbook bucket."""
        all_assessed = self.assess_universe()
        summary: Dict[str, list] = {
            "A": [], "B": [], "MIXED": [], "MONITOR": [], "LOW_RISK": [], "UNKNOWN": []
        }
        for item in all_assessed:
            summary.setdefault(item.playbook, []).append({
                "company": item.entity_name,
                "sector": item.sector,
                "sponsor": item.sponsor,
                "aggression": item.sponsor_aggression,
                "maturity_risk": item.maturity_risk,
                "fundamental_score": item.fundamental_score,
            })
        return summary


def main():
    """Run fundamental analysis on test companies."""
    analyzer = CreditFundamentalAnalyzer()

    test_companies = [
        "INEOS Finance plc",
        "Grifols, S.A.",
        "Telecom Italia S.p.A.",
        "Nokia Oyj",
    ]

    print("=" * 70)
    print("CREDIT FUNDAMENTAL ANALYSIS")
    print("=" * 70)

    for company in test_companies:
        a = analyzer.assess(company)
        print(f"\n{a.entity_name}")
        print(f"  Score:        {a.fundamental_score:.0f}/100")
        print(f"  Playbook:     {a.playbook}")
        print(f"  Sponsor:      {a.sponsor or 'N/A'} (aggression: {a.sponsor_aggression}/10)")
        print(f"  Maturity:     {a.maturity_risk or 'N/A'}")
        print(f"  Leverage:     {a.leverage or 'N/A'}")
        print(f"  Coverage:     {a.interest_coverage or 'N/A'}")
        print(f"  Reasoning:    {a.reasoning}")
        if a.risk_factors:
            for rf in a.risk_factors:
                print(f"  Risk Factor:  {rf}")

    print("\n" + "=" * 70)
    print("UNIVERSE SUMMARY")
    print("=" * 70)
    summary = analyzer.get_summary()
    for playbook, companies in summary.items():
        if companies:
            print(f"\n  Playbook {playbook}: {len(companies)} names")
            for c in companies[:5]:
                print(f"    - {c['company']} (score: {c['fundamental_score']:.0f})")
            if len(companies) > 5:
                print(f"    ... and {len(companies) - 5} more")


if __name__ == "__main__":
    main()

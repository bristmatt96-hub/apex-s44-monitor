"""
Situation Classifier for Credit Catalyst

Classifies companies into:
- Playbook A: Aggressive Sponsor (timing treacherous, equity may spike before collapse)
- Playbook B: Maturity Wall (more predictable deterioration, puts likely work)

Based on sponsor aggression score and maturity pressure.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Literal

PlaybookType = Literal["A", "B", "MIXED", "UNKNOWN"]


class SituationClassifier:
    def __init__(self, data_path: str = None):
        if data_path is None:
            data_path = Path(__file__).parent.parent / "data"
        else:
            data_path = Path(data_path)

        self.sponsors_path = data_path / "sponsors.json"
        self.maturity_path = data_path / "maturity_wall.json"
        self.xover_path = data_path.parent / "indices" / "xover_s44.json"

        self.sponsors_data = self._load_json(self.sponsors_path)
        self.maturity_data = self._load_json(self.maturity_path)
        self.xover_data = self._load_json(self.xover_path)

    def _load_json(self, path: Path) -> dict:
        """Load JSON file if exists, return empty dict otherwise."""
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    def get_sponsor_aggression(self, company: str) -> tuple[str, int]:
        """
        Get sponsor name and aggression score for a company.
        Returns (sponsor_name, aggression_score) or (None, 0) if not found.
        """
        xo_mapping = self.sponsors_data.get("xo_s44_sponsor_mapping", {})
        company_lower = company.lower()

        # Check all risk categories
        for risk_level in ["high_risk", "medium_risk", "lower_risk_pe", "public_companies", "stressed_real_estate"]:
            for entry in xo_mapping.get(risk_level, []):
                entry_company = entry.get("company", "") if isinstance(entry, dict) else ""
                if company_lower in entry_company.lower():
                    return entry.get("sponsor", "Unknown"), entry.get("aggression_score", 5)

        return None, 0

    def get_maturity_risk(self, company: str) -> tuple[str, str]:
        """
        Get maturity risk level and notes for a company.
        Returns (risk_level, notes) or (None, None) if not found.
        """
        maturity_profiles = self.maturity_data.get("xo_s44_maturity_profiles", {})
        company_lower = company.lower()

        # Check all maturity categories
        for period in ["2025_2026_critical", "2027_maturities", "2028_maturities"]:
            for entry in maturity_profiles.get(period, []):
                if company_lower in entry.get("company", "").lower():
                    return entry.get("refinancing_risk", "unknown"), entry.get("concern", "")

        # Check maturities addressed (low risk)
        for entry in maturity_profiles.get("maturities_addressed", []):
            if company_lower in entry.get("company", "").lower():
                return entry.get("refinancing_risk", "low"), entry.get("notes", "Maturities addressed")

        # Check no near term concerns
        for entry in maturity_profiles.get("no_near_term_concerns", []):
            if company_lower in entry.get("company", "").lower():
                return entry.get("refinancing_risk", "low"), entry.get("notes", "No near-term concerns")

        # Check watch list
        for entry in self.maturity_data.get("watch_list_priority", []):
            if company_lower in entry.get("company", "").lower():
                return "high", entry.get("reason", "")

        return None, None

    def classify(self, company: str) -> Dict:
        """
        Classify a company into Playbook A or B.

        Returns dict with:
        - playbook: "A", "B", "MIXED", or "UNKNOWN"
        - sponsor: sponsor name if applicable
        - sponsor_aggression: 1-10 score
        - maturity_risk: risk level
        - reasoning: explanation
        - trading_implications: how to trade this
        """
        sponsor, aggression = self.get_sponsor_aggression(company)
        maturity_risk, maturity_notes = self.get_maturity_risk(company)

        result = {
            "company": company,
            "timestamp": datetime.now().isoformat(),
            "sponsor": sponsor,
            "sponsor_aggression": aggression,
            "maturity_risk": maturity_risk,
            "maturity_notes": maturity_notes,
        }

        # Classification logic
        if aggression >= 7:
            # High aggression sponsor = Playbook A
            result["playbook"] = "A"
            result["reasoning"] = f"High aggression sponsor ({sponsor}, score {aggression}/10). Timing treacherous - equity may spike before collapse."
            result["trading_implications"] = {
                "strategy": "CAUTION",
                "notes": [
                    "Puts alone may not work - timing is treacherous",
                    "Consider straddles for binary outcomes",
                    "Watch for asset stripping news (potential calls)",
                    "May be better to avoid entirely"
                ],
                "options_approach": "straddle_or_avoid"
            }
        elif maturity_risk in ["high", "very_high"]:
            # High maturity risk, no aggressive sponsor = Playbook B
            result["playbook"] = "B"
            result["reasoning"] = f"Maturity wall stress ({maturity_risk}): {maturity_notes}. More predictable deterioration path."
            result["trading_implications"] = {
                "strategy": "PUTS_LIKELY_WORK",
                "notes": [
                    "Puts are likely the right strategy",
                    "Timing tied to maturity schedule, rating actions, covenant breaches",
                    "Theta cost acceptable if catalyst timeline is clear",
                    "System can identify entry points"
                ],
                "options_approach": "puts"
            }
        elif aggression >= 5 and maturity_risk in ["medium", "high"]:
            # Mixed situation
            result["playbook"] = "MIXED"
            result["reasoning"] = f"Mixed signals: moderate sponsor aggression ({aggression}/10) + maturity pressure ({maturity_risk})."
            result["trading_implications"] = {
                "strategy": "SELECTIVE",
                "notes": [
                    "Requires careful analysis of specific situation",
                    "Monitor for sponsor behavior signals",
                    "May lean toward Playbook B if no asset stripping signs"
                ],
                "options_approach": "case_by_case"
            }
        elif sponsor and aggression <= 4:
            # Low aggression sponsor (public company or conservative PE)
            if maturity_risk in ["high", "very_high"]:
                result["playbook"] = "B"
                result["reasoning"] = f"Low aggression sponsor ({sponsor}, {aggression}/10) + maturity pressure ({maturity_risk}). More predictable."
                result["trading_implications"] = {
                    "strategy": "PUTS_LIKELY_WORK",
                    "notes": ["Puts likely work", "Timing tied to maturity/rating actions"],
                    "options_approach": "puts"
                }
            elif maturity_risk == "medium":
                result["playbook"] = "MONITOR"
                result["reasoning"] = f"Low aggression sponsor ({sponsor}) with medium maturity risk. Monitor for deterioration."
                result["trading_implications"] = {
                    "strategy": "MONITOR",
                    "notes": ["Watch for credit deterioration", "May become Playbook B opportunity"],
                    "options_approach": "wait_for_signal"
                }
            elif maturity_risk == "low":
                result["playbook"] = "LOW_RISK"
                result["reasoning"] = f"Low aggression sponsor ({sponsor}), low maturity risk. Not a current opportunity."
                result["trading_implications"] = {
                    "strategy": "NO_ACTION",
                    "notes": ["Low risk profile", "Monitor for changes"],
                    "options_approach": "none"
                }
            else:
                result["playbook"] = "UNKNOWN"
                result["reasoning"] = f"Low aggression sponsor ({sponsor}), no immediate stress signals detected."
                result["trading_implications"] = {
                    "strategy": "MONITOR",
                    "notes": ["Monitor for credit deterioration signals"],
                    "options_approach": "wait_for_signal"
                }
        else:
            result["playbook"] = "UNKNOWN"
            result["reasoning"] = "Insufficient data to classify. Need more research."
            result["trading_implications"] = {
                "strategy": "RESEARCH_NEEDED",
                "notes": ["Gather more data on sponsor and maturity profile"],
                "options_approach": "none"
            }

        return result

    def classify_all_xover(self) -> List[Dict]:
        """Classify all XO S44 constituents."""
        results = []

        if not self.xover_data:
            return results

        sectors = self.xover_data.get("sectors", {})
        for sector, companies in sectors.items():
            for company in companies:
                classification = self.classify(company)
                classification["sector"] = sector
                results.append(classification)

        return results

    def get_playbook_summary(self) -> Dict:
        """Get summary of all classifications by playbook."""
        all_classified = self.classify_all_xover()

        summary = {
            "A": [],
            "B": [],
            "MIXED": [],
            "MONITOR": [],
            "LOW_RISK": [],
            "UNKNOWN": []
        }

        for item in all_classified:
            playbook = item.get("playbook", "UNKNOWN")
            summary[playbook].append({
                "company": item["company"],
                "sector": item.get("sector"),
                "sponsor": item.get("sponsor"),
                "aggression": item.get("sponsor_aggression"),
                "maturity_risk": item.get("maturity_risk")
            })

        return summary


def main():
    """Test the classifier."""
    classifier = SituationClassifier()

    # Test specific companies
    test_companies = [
        "INEOS Finance plc",
        "Grifols, S.A.",
        "Telecom Italia S.p.A.",
        "Nokia Oyj"
    ]

    print("=" * 60)
    print("SITUATION CLASSIFIER - TEST RESULTS")
    print("=" * 60)

    for company in test_companies:
        result = classifier.classify(company)
        print(f"\n{company}")
        print(f"  Playbook: {result['playbook']}")
        print(f"  Sponsor: {result['sponsor']} (aggression: {result['sponsor_aggression']}/10)")
        print(f"  Maturity Risk: {result['maturity_risk']}")
        print(f"  Strategy: {result['trading_implications']['strategy']}")
        print(f"  Reasoning: {result['reasoning']}")

    # Summary
    print("\n" + "=" * 60)
    print("PLAYBOOK SUMMARY")
    print("=" * 60)

    summary = classifier.get_playbook_summary()
    for playbook, companies in summary.items():
        if companies:
            print(f"\nPlaybook {playbook}: {len(companies)} companies")
            for c in companies[:5]:  # Show first 5
                print(f"  - {c['company']}")
            if len(companies) > 5:
                print(f"  ... and {len(companies) - 5} more")


if __name__ == "__main__":
    main()

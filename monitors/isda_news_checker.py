# News-to-ISDA Credit Event Checker
# Automatically flags potential credit events and pulls relevant ISDA sections

"""
This module monitors news headlines for ISDA-relevant keywords and:
1. Flags potential credit events
2. Pulls relevant ISDA sections for review
3. Generates checklists of questions to answer
4. Tracks grace periods and key dates

IMPORTANT: This is a FLAGGING system, not an ADJUDICATION system.
Legal interpretation requires human judgment - see Ardagh/Tresidor dispute.
"""

import re
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# ============== ISDA KEYWORD TAXONOMY ==============

# Keywords that suggest potential credit events
ISDA_KEYWORDS = {
    "bankruptcy": {
        "terms": [
            "bankruptcy", "chapter 11", "chapter 15", "insolvency",
            "administration", "liquidation", "receivership", "winding up",
            "creditor protection", "sauvegarde", "redressement judiciaire"
        ],
        "isda_section": "4.2",
        "credit_event_type": "Bankruptcy",
        "urgency": "CRITICAL"
    },
    "failure_to_pay": {
        "terms": [
            "missed payment", "failed to pay", "payment default",
            "coupon missed", "interest not paid", "principal not paid",
            "grace period", "payment holiday"
        ],
        "isda_section": "4.5",
        "credit_event_type": "Failure to Pay",
        "urgency": "CRITICAL"
    },
    "restructuring": {
        "terms": [
            "restructuring", "consent solicitation", "exchange offer",
            "maturity extension", "coupon reduction", "principal haircut",
            "debt for equity", "equitization", "amendment", "waiver",
            "covenant holiday", "PIK toggle", "amend and extend"
        ],
        "isda_section": "4.7",
        "credit_event_type": "Restructuring",
        "urgency": "HIGH"
    },
    "binding_mechanisms": {
        "terms": [
            "scheme of arrangement", "WHOA", "StaRUG", "chapter 11 cramdown",
            "collective action clause", "CAC", "exit consent", "drag along",
            "majority consent", "supermajority"
        ],
        "isda_section": "4.7 + binding analysis",
        "credit_event_type": "Potentially Binding Restructuring",
        "urgency": "HIGH"
    },
    "advisor_engagement": {
        "terms": [
            "houlihan lokey", "PJT", "moelis", "lazard", "rothschild",
            "evercore", "perella weinberg", "ducera", "restructuring advisor",
            "financial advisor", "legal advisor", "kirkland", "weil gotshal",
            "milbank", "akin gump", "paul weiss"
        ],
        "isda_section": "N/A - Early Warning",
        "credit_event_type": "Potential Future Event",
        "urgency": "WATCH"
    },
    "cds_specific": {
        "terms": [
            "credit event", "determinations committee", "DC referral",
            "CDS auction", "deliverable obligations", "reference entity",
            "successor", "OPB", "outstanding principal balance"
        ],
        "isda_section": "Multiple",
        "credit_event_type": "Direct CDS Relevance",
        "urgency": "CRITICAL"
    }
}

# ============== ISDA SECTION REFERENCE ==============

ISDA_SECTIONS = {
    "4.2": {
        "title": "Bankruptcy",
        "summary": "Reference Entity files for bankruptcy, insolvency, or has receiver appointed",
        "key_triggers": [
            "Voluntary bankruptcy filing",
            "Involuntary petition (not dismissed within 30 days)",
            "General assignment for benefit of creditors",
            "Receiver/administrator appointed"
        ],
        "NOT_triggered_by": [
            "Out-of-court restructuring",
            "Scheme of Arrangement (usually - context dependent)",
            "Consensual exchange offer"
        ]
    },
    "4.5": {
        "title": "Failure to Pay",
        "summary": "Reference Entity fails to make payment when due after grace period",
        "key_conditions": [
            "Payment must be due and payable",
            "Grace period must have expired (typically 30 days for interest)",
            "Amount must meet Payment Requirement (typically USD 1m)",
            "Must be on Borrowed Money"
        ],
        "grace_period_note": "Check specific indenture for grace period terms"
    },
    "4.7": {
        "title": "Restructuring",
        "summary": "Binding change to terms of Borrowed Money resulting from credit deterioration",
        "triggering_events": [
            "Reduction in interest rate or amount",
            "Reduction in principal amount",
            "Postponement/deferral of payment",
            "Change in ranking (subordination)",
            "Change to non-permitted currency"
        ],
        "CRITICAL_conditions": [
            "Must result from deterioration in creditworthiness",
            "Must BIND ALL HOLDERS",
            "Must apply to Multiple Holder Obligation"
        ],
        "NOT_triggered_by": [
            "Voluntary exchange (can keep old bonds)",
            "Changes pursuant to original terms (e.g., PIK toggle)",
            "Changes not resulting from credit deterioration"
        ]
    },
    "3.11(b)": {
        "title": "Permitted Contingency Exception",
        "summary": "Reductions in OPB from holder-controlled actions are excluded",
        "application": "If bondholders negotiate, agree, and vote for restructuring, principal changes from collective action may be ignored when determining OPB",
        "ardagh_relevance": "Tresidor argues this preserves SUN deliverability despite TSA agreement"
    },
    "article_iii": {
        "title": "Deliverable Obligations",
        "summary": "Governs WHAT can be delivered into CDS auction",
        "key_point": "SEPARATE from Article IV (credit events)",
        "ardagh_lesson": "Credit event timing (Article IV) does NOT automatically resolve deliverables (Article III)"
    },
    "article_iv": {
        "title": "Credit Events",
        "summary": "Governs WHEN a credit event occurs",
        "key_point": "SEPARATE from Article III (deliverables)",
        "ardagh_lesson": "A determination of credit event timing is a 'narrow question' - does not resolve OPB"
    }
}

# ============== CHECKLIST GENERATOR ==============

def generate_credit_event_checklist(event_type: str, headline: str) -> Dict:
    """
    Generate a checklist of questions to answer for a potential credit event

    Args:
        event_type: Type of event (bankruptcy, failure_to_pay, restructuring)
        headline: The news headline that triggered the flag

    Returns:
        Checklist dictionary with questions and guidance
    """

    base_questions = [
        "What is the Reference Entity for CDS purposes?",
        "What contract type trades on this name (Mod-Mod-R typical for European HY)?",
        "What is current CDS spread / price?",
        "Who are the major CDS counterparties (if known)?"
    ]

    checklists = {
        "bankruptcy": {
            "questions": base_questions + [
                "Is this a voluntary or involuntary filing?",
                "What jurisdiction - US Chapter 11, UK Administration, other?",
                "Has 30-day period for involuntary petition expired?",
                "What is the expected recovery for different tranches?",
                "Is DIP financing being sought?",
                "What are the key next steps in the process?"
            ],
            "isda_reference": "Section 4.2",
            "typical_outcome": "Bankruptcy = DEFINITE Credit Event",
            "cds_implication": "Auction will be held, protection sellers pay out"
        },
        "failure_to_pay": {
            "questions": base_questions + [
                "What payment was missed (interest vs principal)?",
                "What is the contractual grace period?",
                "Has the grace period expired or is it running?",
                "What is the amount missed vs Payment Requirement threshold?",
                "Is this on Borrowed Money (bonds/loans)?",
                "Is cure likely before grace period expires?"
            ],
            "isda_reference": "Section 4.5",
            "typical_outcome": "Depends on grace period and cure",
            "cds_implication": "If grace expires without cure = Credit Event"
        },
        "restructuring": {
            "questions": base_questions + [
                "What terms are being changed (coupon, maturity, principal)?",
                "Is this VOLUNTARY (exchange offer) or BINDING (consent solicitation)?",
                "What voting threshold is required for approval?",
                "Are exit consents being used to strip protections?",
                "Does this result from credit deterioration (not original terms)?",
                "Will amendment bind ALL holders including dissenters?",
                "Is this a Scheme of Arrangement, WHOA, or similar binding mechanism?"
            ],
            "isda_reference": "Section 4.7",
            "typical_outcome": "DEPENDS on binding nature - key question",
            "cds_implication": "Voluntary = usually NO event. Binding = usually YES event."
        },
        "cds_specific": {
            "questions": base_questions + [
                "Has DC referral been made?",
                "What question is being asked of DC?",
                "What is timeline for DC decision?",
                "Are there competing views (like Ardagh Arini/Tresidor)?",
                "What obligations are being disputed as deliverables?",
                "Is there Article III vs Article IV complexity?"
            ],
            "isda_reference": "Multiple sections",
            "typical_outcome": "DC will rule",
            "cds_implication": "Watch DC announcement closely"
        }
    }

    checklist = checklists.get(event_type, {
        "questions": base_questions + ["Determine specific event type for detailed checklist"],
        "isda_reference": "TBD",
        "typical_outcome": "Requires analysis",
        "cds_implication": "Requires analysis"
    })

    return {
        "headline": headline,
        "event_type": event_type,
        "generated_at": datetime.now().isoformat(),
        "checklist": checklist,
        "status": "PENDING_ANALYSIS",
        "analyst_notes": None,
        "conclusion": None
    }


# ============== NEWS SCANNER ==============

def scan_headline(headline: str, company: str = None) -> List[Dict]:
    """
    Scan a news headline for ISDA-relevant keywords

    Args:
        headline: The news headline to scan
        company: Optional company name for context

    Returns:
        List of matches with keyword category, ISDA section, and urgency
    """
    headline_lower = headline.lower()
    matches = []

    for category, data in ISDA_KEYWORDS.items():
        for term in data["terms"]:
            if term.lower() in headline_lower:
                matches.append({
                    "category": category,
                    "term_matched": term,
                    "isda_section": data["isda_section"],
                    "credit_event_type": data["credit_event_type"],
                    "urgency": data["urgency"],
                    "company": company,
                    "headline": headline,
                    "scanned_at": datetime.now().isoformat()
                })
                break  # One match per category is enough

    return matches


def scan_headlines_batch(headlines: List[Dict]) -> Dict:
    """
    Scan multiple headlines and group by urgency

    Args:
        headlines: List of {"headline": str, "company": str} dicts

    Returns:
        Results grouped by urgency level
    """
    results = {
        "CRITICAL": [],
        "HIGH": [],
        "WATCH": [],
        "total_scanned": len(headlines),
        "total_flagged": 0
    }

    for item in headlines:
        matches = scan_headline(item.get("headline", ""), item.get("company"))
        for match in matches:
            urgency = match["urgency"]
            results[urgency].append(match)
            results["total_flagged"] += 1

    return results


# ============== GRACE PERIOD TRACKER ==============

class GracePeriodTracker:
    """Track grace periods for potential Failure to Pay events"""

    def __init__(self, storage_path: str = None):
        if storage_path is None:
            storage_path = Path(__file__).parent.parent / "database" / "grace_periods.json"
        self.storage_path = Path(storage_path)
        self.periods = []
        self._load()

    def _load(self):
        if self.storage_path.exists():
            with open(self.storage_path, 'r') as f:
                self.periods = json.load(f)

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, 'w') as f:
            json.dump(self.periods, f, indent=2)

    def add_grace_period(self, company: str, payment_type: str,
                         missed_date: str, grace_days: int, notes: str = None):
        """Track a new grace period"""
        missed = datetime.fromisoformat(missed_date)
        expiry = missed + timedelta(days=grace_days)

        entry = {
            "company": company,
            "payment_type": payment_type,
            "missed_date": missed_date,
            "grace_days": grace_days,
            "expiry_date": expiry.isoformat()[:10],
            "notes": notes,
            "status": "RUNNING",
            "added_at": datetime.now().isoformat()
        }

        self.periods.append(entry)
        self._save()
        return entry

    def get_expiring_soon(self, days: int = 7) -> List[Dict]:
        """Get grace periods expiring within N days"""
        cutoff = datetime.now() + timedelta(days=days)
        expiring = []

        for p in self.periods:
            if p["status"] != "RUNNING":
                continue
            expiry = datetime.fromisoformat(p["expiry_date"])
            if expiry <= cutoff:
                days_left = (expiry - datetime.now()).days
                expiring.append({**p, "days_until_expiry": days_left})

        return sorted(expiring, key=lambda x: x["days_until_expiry"])

    def mark_cured(self, company: str):
        """Mark a grace period as cured (payment made)"""
        for p in self.periods:
            if p["company"].lower() == company.lower() and p["status"] == "RUNNING":
                p["status"] = "CURED"
                p["cured_at"] = datetime.now().isoformat()
        self._save()

    def mark_expired(self, company: str):
        """Mark a grace period as expired (Credit Event triggered)"""
        for p in self.periods:
            if p["company"].lower() == company.lower() and p["status"] == "RUNNING":
                p["status"] = "EXPIRED_CREDIT_EVENT"
                p["expired_at"] = datetime.now().isoformat()
        self._save()


# ============== RAPID RESPONSE FRAMEWORK ==============

def rapid_response_analysis(headline: str, company: str) -> Dict:
    """
    60-second rapid response analysis for a breaking news headline

    Args:
        headline: The news headline
        company: Company name

    Returns:
        Structured rapid analysis with immediate actions
    """
    # Scan for keywords
    matches = scan_headline(headline, company)

    if not matches:
        return {
            "company": company,
            "headline": headline,
            "isda_relevance": "LOW",
            "immediate_action": "Monitor - no ISDA keywords detected",
            "analysis": None
        }

    # Get highest urgency match
    urgency_order = {"CRITICAL": 0, "HIGH": 1, "WATCH": 2}
    matches.sort(key=lambda x: urgency_order.get(x["urgency"], 3))
    primary_match = matches[0]

    # Generate checklist
    event_type = primary_match["category"]
    checklist = generate_credit_event_checklist(event_type, headline)

    # Get ISDA section reference
    section = primary_match["isda_section"]
    section_info = ISDA_SECTIONS.get(section, {"summary": "See ISDA 2014 definitions"})

    return {
        "company": company,
        "headline": headline,
        "analyzed_at": datetime.now().isoformat(),
        "isda_relevance": primary_match["urgency"],
        "primary_event_type": primary_match["credit_event_type"],
        "isda_section": section,
        "section_summary": section_info.get("summary"),
        "immediate_actions": [
            f"Check CDS spread on {company}",
            f"Review ISDA Section {section}" if section != "N/A - Early Warning" else "Monitor for escalation",
            "Check if DC referral has been made",
            "Identify reference entity"
        ],
        "checklist": checklist,
        "all_matches": matches,
        "human_review_required": True,
        "disclaimer": "This is automated flagging - legal interpretation requires human judgment"
    }


# ============== MAIN INTERFACE ==============

def analyze_news_for_isda(headlines: List[str], companies: List[str] = None) -> Dict:
    """
    Main interface: Analyze list of headlines for ISDA implications

    Args:
        headlines: List of news headlines
        companies: Optional list of company names (same order as headlines)

    Returns:
        Full analysis with prioritized flags and checklists
    """
    if companies is None:
        companies = [None] * len(headlines)

    items = [{"headline": h, "company": c} for h, c in zip(headlines, companies)]
    scan_results = scan_headlines_batch(items)

    # Generate detailed analysis for critical items
    detailed = []
    for match in scan_results["CRITICAL"] + scan_results["HIGH"]:
        analysis = rapid_response_analysis(match["headline"], match["company"])
        detailed.append(analysis)

    return {
        "summary": {
            "total_headlines": len(headlines),
            "critical_flags": len(scan_results["CRITICAL"]),
            "high_flags": len(scan_results["HIGH"]),
            "watch_flags": len(scan_results["WATCH"])
        },
        "scan_results": scan_results,
        "detailed_analysis": detailed,
        "generated_at": datetime.now().isoformat()
    }


# ============== USAGE EXAMPLE ==============

if __name__ == "__main__":
    # Example headlines to test
    test_headlines = [
        "Ardagh Group files Chapter 15 for ARD Finance SA",
        "Tresidor challenges Arini on CDS deliverables in Ardagh dispute",
        "Stonegate Pub announces consent solicitation for maturity extension",
        "INEOS hires Houlihan Lokey as financial advisor",
        "Altice France proposes exchange offer for senior secured notes",
        "Casino Group enters safeguard proceedings in France",
        "Thames Water misses interest payment, 30-day grace period begins"
    ]

    test_companies = [
        "Ardagh", "Ardagh", "Stonegate", "INEOS",
        "Altice France", "Casino", "Thames Water"
    ]

    print("=" * 60)
    print("NEWS-TO-ISDA CREDIT EVENT CHECKER")
    print("=" * 60)

    results = analyze_news_for_isda(test_headlines, test_companies)

    print(f"\nSummary:")
    print(f"  Headlines scanned: {results['summary']['total_headlines']}")
    print(f"  CRITICAL flags: {results['summary']['critical_flags']}")
    print(f"  HIGH flags: {results['summary']['high_flags']}")
    print(f"  WATCH flags: {results['summary']['watch_flags']}")

    print("\n" + "=" * 60)
    print("CRITICAL & HIGH PRIORITY ITEMS")
    print("=" * 60)

    for analysis in results["detailed_analysis"]:
        print(f"\n[{analysis['isda_relevance']}] {analysis['company']}")
        print(f"  Headline: {analysis['headline'][:60]}...")
        print(f"  Event Type: {analysis['primary_event_type']}")
        print(f"  ISDA Section: {analysis['isda_section']}")
        print(f"  Immediate Actions:")
        for action in analysis["immediate_actions"]:
            print(f"    - {action}")

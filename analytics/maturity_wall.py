"""
Maturity Wall Analyser

Loads maturity wall data from data/maturity_wall.json, cross-references
with real CDS spreads from data/market_data_loader.py, and identifies
names where the spread doesn't adequately reflect refinancing risk.

Output: Ranked list of entities by refinancing risk, with spread context.

Usage:
    python -m analytics.maturity_wall
    python -m analytics.maturity_wall --horizon 24   # 24-month window (default)
    python -m analytics.maturity_wall --min-risk 3    # only show risk >= 3
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from data.market_data_loader import load_market_data, get_spread_context


MATURITY_DATA_PATH = Path("data/maturity_wall.json")

# Refinancing risk text -> numeric score
RISK_SCORES = {
    "very_high": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "very_low": 1,
}

# Typical spread levels where refinancing becomes genuinely difficult
# (market effectively shut for issuer at these levels)
REFI_STRESS_THRESHOLDS = {
    5: 800,   # very_high risk: if spread < 800, market may be underpricing
    4: 500,   # high risk: if spread < 500, market may be underpricing
    3: 350,   # medium risk: if spread < 350, market may be underpricing
    2: 250,   # low risk: generally fine
    1: 150,   # very_low risk: no concern
}

# Name mapping from maturity_wall.json company names to market data names
NAME_MAP = {
    "Samhallsbyggnadsbolaget i Norden AB (SBB)": "Samhallsbyggnadsbolaget i Norden AB",
    "Telecom Italia S.p.A.": "Telecom Italia SpA/Milano",
    "INEOS Quattro": "INEOS Quattro Finance 2 Plc",
    "Grifols, S.A.": "Grifols SA",
    "Jaguar Land Rover": "Jaguar Land Rover Automotive PLC",
    "Intrum Justitia": None,  # Not in Xover S44
    "ELO (Auchan)": "ELO SACA",
    "CPI Property Group": "CPI Property Group SA",
    "Virgin Media Finance": "Virgin Media Finance PLC",
    "Schaeffler AG": "Schaeffler AG",
    "Nissan (via Renault exposure)": "Renault SA",
    "Bellis Acquisition (Asda)": "Bellis Acquisition Co PLC",
    "VodafoneZiggo (Liberty Global)": "Ziggo Bond Co BV",
    "Verisure": "Verisure Midholding AB",
    "Motion Bondco (Merlin)": "Motion Bondco DAC",
    "Nokia Oyj": "Nokia Oyj",
    "Renault": "Renault SA",
    "INEOS Finance plc": "INEOS Finance PLC",
    "INEOS Quattro Finance 2 plc": "INEOS Quattro Finance 2 Plc",
    "Grifols": "Grifols SA",
    "SBB (Samhallsbyggnadsbolaget)": "Samhallsbyggnadsbolaget i Norden AB",
    "Telecom Italia": "Telecom Italia SpA/Milano",
    "CPI Property": "CPI Property Group SA",
    "INEOS entities": "INEOS Finance PLC",
}


def load_maturity_data() -> dict:
    """Load maturity wall JSON data."""
    if not MATURITY_DATA_PATH.exists():
        print(f"Error: {MATURITY_DATA_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    with open(MATURITY_DATA_PATH) as f:
        return json.load(f)


def resolve_market_name(company_name: str) -> str | None:
    """Resolve a maturity wall company name to the market data name."""
    if company_name in NAME_MAP:
        return NAME_MAP[company_name]
    # Try direct match
    return company_name


def extract_maturity_entries(data: dict) -> list[dict]:
    """Extract all maturity entries from the JSON structure into a flat list.

    Each entry gets: company, maturities, risk_score, risk_label, category,
    maturity_window, notes, concern, leverage, rating, playbook.
    """
    entries = []
    profiles = data.get("xo_s44_maturity_profiles", {})

    # 2025-2026 critical
    for item in profiles.get("2025_2026_critical", []):
        entries.append({
            "company": item["company"],
            "maturities": item.get("key_maturities", []),
            "risk_label": item.get("refinancing_risk", "medium"),
            "risk_score": RISK_SCORES.get(item.get("refinancing_risk", "medium"), 3),
            "category": "2025-2026 Critical",
            "maturity_window": "0-12 months",
            "notes": item.get("notes", ""),
            "concern": item.get("concern", ""),
            "leverage": item.get("leverage", ""),
            "rating": item.get("rating", ""),
            "playbook": item.get("playbook", ""),
        })

    # 2027 maturities
    for item in profiles.get("2027_maturities", []):
        entries.append({
            "company": item["company"],
            "maturities": item.get("key_maturities", []),
            "risk_label": item.get("refinancing_risk", "medium"),
            "risk_score": RISK_SCORES.get(item.get("refinancing_risk", "medium"), 3),
            "category": "2027 Maturities",
            "maturity_window": "12-24 months",
            "notes": item.get("notes", ""),
            "concern": item.get("concern", ""),
            "leverage": item.get("leverage", ""),
            "rating": item.get("rating", ""),
            "playbook": item.get("playbook", ""),
        })

    # 2028 maturities
    for item in profiles.get("2028_maturities", []):
        entries.append({
            "company": item["company"],
            "maturities": item.get("key_maturities", []),
            "risk_label": item.get("refinancing_risk", "medium"),
            "risk_score": RISK_SCORES.get(item.get("refinancing_risk", "medium"), 3),
            "category": "2028 Maturities",
            "maturity_window": "24-36 months",
            "notes": item.get("notes", ""),
            "concern": item.get("concern", ""),
            "leverage": item.get("leverage", ""),
            "rating": item.get("rating", ""),
            "playbook": item.get("playbook", ""),
        })

    # Addressed (low risk now)
    for item in profiles.get("maturities_addressed", []):
        entries.append({
            "company": item["company"],
            "maturities": item.get("original_maturities", []),
            "risk_label": item.get("refinancing_risk", "low"),
            "risk_score": RISK_SCORES.get(item.get("refinancing_risk", "low"), 2),
            "category": "Addressed",
            "maturity_window": "Addressed",
            "notes": item.get("notes", "") + f" Status: {item.get('status', '')}",
            "concern": "",
            "leverage": item.get("leverage", ""),
            "rating": item.get("rating", ""),
            "playbook": "",
        })

    # No near-term concerns
    for item in profiles.get("no_near_term_concerns", []):
        entries.append({
            "company": item["company"],
            "maturities": [item.get("next_maturity", "N/A")],
            "risk_label": item.get("refinancing_risk", "low"),
            "risk_score": RISK_SCORES.get(item.get("refinancing_risk", "low"), 2),
            "category": "No Near-Term Concern",
            "maturity_window": "36+ months",
            "notes": item.get("notes", ""),
            "concern": "",
            "leverage": "",
            "rating": "",
            "playbook": "",
        })

    return entries


def compute_spread_adequacy(
    risk_score: int, current_spread: float | None
) -> dict:
    """Assess whether the current spread adequately reflects refinancing risk.

    Returns dict with:
        - adequate: bool
        - threshold: the minimum spread expected for this risk level
        - gap: spread - threshold (negative = underpriced risk)
        - assessment: text summary
    """
    threshold = REFI_STRESS_THRESHOLDS.get(risk_score, 200)

    if current_spread is None:
        return {
            "adequate": None,
            "threshold": threshold,
            "gap": None,
            "assessment": "No market data — cannot assess",
        }

    gap = current_spread - threshold
    adequate = gap >= 0

    if gap >= 100:
        assessment = "Spread adequately prices refinancing risk"
    elif gap >= 0:
        assessment = "Spread marginally prices risk — watch closely"
    elif gap >= -100:
        assessment = "UNDERPRICED — spread does not reflect refinancing risk"
    else:
        assessment = "SIGNIFICANTLY UNDERPRICED — spread ignores refinancing wall"

    return {
        "adequate": adequate,
        "threshold": threshold,
        "gap": gap,
        "assessment": assessment,
    }


def enrich_with_market_data(
    entries: list[dict], market_data: dict
) -> list[dict]:
    """Cross-reference maturity entries with real CDS spreads."""
    for entry in entries:
        market_name = resolve_market_name(entry["company"])
        mkt = market_data.get(market_name, {}) if market_name else {}

        entry["market_name"] = market_name
        entry["current_spread"] = mkt.get("spread")
        entry["convention"] = mkt.get("convention", "")
        entry["points_upfront"] = mkt.get("points_upfront")
        entry["ticker"] = mkt.get("ticker")

        # Compute spread adequacy
        adequacy = compute_spread_adequacy(entry["risk_score"], entry["current_spread"])
        entry.update(adequacy)

    return entries


def get_watch_list(data: dict) -> list[dict]:
    """Extract priority watch list."""
    return data.get("watch_list_priority", [])


def print_report(entries: list[dict], watch_list: list[dict], min_risk: int = 1):
    """Print formatted maturity wall report to terminal."""
    today = datetime.now().strftime("%d %B %Y")

    print("=" * 110)
    print(f"  CREDIT CATALYST — MATURITY WALL ANALYSIS")
    print(f"  {today}")
    print("=" * 110)

    # Filter and sort by risk score desc, then by spread gap (most underpriced first)
    filtered = [e for e in entries if e["risk_score"] >= min_risk]
    filtered.sort(key=lambda e: (
        -e["risk_score"],
        e.get("gap") if e.get("gap") is not None else 999,
    ))

    # Summary stats
    high_risk = [e for e in filtered if e["risk_score"] >= 4]
    underpriced = [e for e in filtered if e.get("adequate") is False]
    print(f"\n  Names with maturity data: {len(filtered)}")
    print(f"  High/Very High risk (4-5): {len(high_risk)}")
    print(f"  Spread underpricing refi risk: {len(underpriced)}")

    # Ranked table
    print("\n" + "-" * 110)
    print(f"  {'#':<3} {'Entity':<42} {'Window':<14} {'Risk':>5} {'Spread':>8} "
          f"{'Thresh':>8} {'Gap':>8} {'Assessment'}")
    print("-" * 110)

    for i, e in enumerate(filtered, 1):
        spread_str = f"{e['current_spread']:.0f}" if e['current_spread'] else "N/A"
        gap_str = f"{e['gap']:+.0f}" if e.get('gap') is not None else "N/A"
        risk_bar = "#" * e["risk_score"] + "." * (5 - e["risk_score"])

        # Color indicators
        if e.get("adequate") is False:
            flag = "!!"
        elif e.get("adequate") is True:
            flag = "OK"
        else:
            flag = "??"

        print(f"  {i:<3} {e['company'][:40]:<42} {e['maturity_window']:<14} "
              f"{risk_bar:>5} {spread_str:>8} {e['threshold']:>8} {gap_str:>8}  "
              f"{flag} {e['assessment']}")

    # Detail on underpriced names
    if underpriced:
        print("\n" + "=" * 110)
        print("  !!  NAMES WHERE SPREAD UNDERPRICES REFINANCING RISK")
        print("=" * 110)
        for e in underpriced:
            print(f"\n  {e['company']}")
            print(f"    Spread: {e['current_spread']:.0f}bps | "
                  f"Risk threshold: {e['threshold']}bps | "
                  f"Gap: {e['gap']:+.0f}bps")
            print(f"    Risk: {e['risk_label']} ({e['risk_score']}/5) | "
                  f"Window: {e['maturity_window']} | "
                  f"Playbook: {e['playbook'] or 'N/A'}")
            if e["maturities"]:
                print(f"    Maturities: {', '.join(e['maturities'])}")
            if e["concern"]:
                print(f"    Concern: {e['concern']}")
            if e["notes"]:
                print(f"    Notes: {e['notes']}")

    # Watch list
    if watch_list:
        print("\n" + "=" * 110)
        print("  PRIORITY WATCH LIST")
        print("=" * 110)
        for w in watch_list:
            print(f"  P{w['priority']}: {w['company']:<30} {w['reason']}")
            print(f"       Catalyst: {w['catalyst']}")

    # Key stats from overview
    print("\n" + "-" * 110)
    print("  Source: data/maturity_wall.json | Market data: data/market_data/")
    print("-" * 110)


def main():
    parser = argparse.ArgumentParser(description="Maturity Wall Analyser")
    parser.add_argument(
        "--horizon", type=int, default=36,
        help="Maturity horizon in months to include (default: 36)",
    )
    parser.add_argument(
        "--min-risk", type=int, default=1, choices=[1, 2, 3, 4, 5],
        help="Minimum risk score to display (default: 1 = all)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of formatted report",
    )
    args = parser.parse_args()

    # Load data
    maturity_data = load_maturity_data()
    market_data = load_market_data(index="xover")

    if not market_data:
        print("Warning: No market data found. Spread analysis unavailable.",
              file=sys.stderr)

    # Extract and enrich
    entries = extract_maturity_entries(maturity_data)
    entries = enrich_with_market_data(entries, market_data)
    watch_list = get_watch_list(maturity_data)

    if args.json:
        output = {
            "generated_at": datetime.now().isoformat(),
            "entries": entries,
            "watch_list": watch_list,
            "summary": {
                "total_entries": len(entries),
                "high_risk": len([e for e in entries if e["risk_score"] >= 4]),
                "underpriced": len([e for e in entries if e.get("adequate") is False]),
            },
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print_report(entries, watch_list, min_risk=args.min_risk)


if __name__ == "__main__":
    main()

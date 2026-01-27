"""
LME Risk Calculator
Scores credits for Liability Management Exercise risk based on:
- Documentation quality (cov-lite, blockers)
- Maturity proximity
- Leverage / Liquidity
- Ownership structure
- Market signals (bond prices, yields)

Purpose: Identify names approaching 2027/28 maturity wall most likely to pursue LME
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import streamlit as st


@dataclass
class LMERiskScore:
    """LME Risk assessment result"""
    total_score: int  # 0-100
    risk_level: str  # LOW, MODERATE, ELEVATED, HIGH, CRITICAL
    doc_score: int
    maturity_score: int
    leverage_score: int
    liquidity_score: int
    market_score: int
    ownership_score: int
    flags: List[str]
    likely_path: str  # Voluntary Exchange, Uptier, Dropdown, Court Process, etc.


# ============== SCORING WEIGHTS ==============

WEIGHTS = {
    "doc_quality": 20,      # Cov-lite, lack of blockers
    "maturity": 20,         # How close to maturity wall
    "leverage": 20,         # Debt/EBITDA
    "liquidity": 15,        # Cash + revolver vs near-term maturities
    "market_signals": 15,   # Bond prices, yields, CDS
    "ownership": 10,        # PE-backed, sponsor aggression history
}


def calculate_doc_score(snapshot: Dict) -> Tuple[int, List[str]]:
    """Score documentation quality risk (0-100)"""
    score = 0
    flags = []

    lme_risk = snapshot.get("lme_risk", snapshot.get("lme_risk_proxy", {}))
    doc_info = lme_risk.get("doc_quality", {})

    # Cov-lite = major risk factor
    if doc_info.get("cov_lite") or lme_risk.get("cov_lite"):
        score += 40
        flags.append("COV-LITE docs")

    # Check for blockers (absence = risk)
    has_j_crew = doc_info.get("j_crew_blocker", False)
    has_serta = doc_info.get("serta_blocker", False)
    has_chewy = doc_info.get("chewy_blocker", False)

    if not has_j_crew and not has_serta and not has_chewy:
        score += 30
        flags.append("No LME blockers in docs")
    elif not has_serta:
        score += 15
        flags.append("No Serta blocker")

    # Doc vintage - older = weaker
    vintage = doc_info.get("vintage", lme_risk.get("doc_vintage", ""))
    if vintage:
        try:
            # Extract year from vintage string
            years = [int(y) for y in vintage.replace("-", " ").split() if y.isdigit() and len(y) == 4]
            if years:
                oldest = min(years)
                if oldest <= 2018:
                    score += 20
                    flags.append(f"Legacy docs ({vintage})")
                elif oldest <= 2020:
                    score += 10
                    flags.append(f"Pre-blocker era docs ({vintage})")
        except Exception:
            pass

    # Complex structure = more LME tools available
    if lme_risk.get("complex_structure") or lme_risk.get("structure", {}).get("complex_structure"):
        score += 10
        flags.append("Complex corporate structure")

    if lme_risk.get("multi_entity_issuer") or lme_risk.get("structure", {}).get("multi_entity_issuer"):
        score += 10
        flags.append("Multi-entity issuer")

    # Unrestricted subs = dropdown risk
    if lme_risk.get("structure", {}).get("unrestricted_subs"):
        score += 15
        flags.append("Has unrestricted subsidiaries")

    return min(100, score), flags


def calculate_maturity_score(snapshot: Dict) -> Tuple[int, List[str]]:
    """Score maturity wall risk (0-100)"""
    score = 0
    flags = []

    current_year = datetime.now().year

    # Check maturity schedule
    mat_schedule = snapshot.get("maturity_schedule", {})
    debt_cap = snapshot.get("debt_capitalization", [])

    near_term_debt = 0
    wall_2027_28 = 0

    # From maturity schedule
    if mat_schedule:
        near_term_debt = (mat_schedule.get("year_1") or 0) + (mat_schedule.get("year_2") or 0)
        # Estimate 2027/28 from year_3, year_4 depending on current year
        wall_2027_28 = (mat_schedule.get("year_3") or 0) + (mat_schedule.get("year_4") or 0)

    # From debt cap table - look for 2026, 2027, 2028 maturities
    for debt in debt_cap:
        maturity = str(debt.get("maturity", ""))
        amount = debt.get("amount") or 0

        if "2026" in maturity:
            near_term_debt += amount
            score += 20
            flags.append(f"2026 maturity: {debt.get('instrument', 'Debt')}")
        elif "2027" in maturity:
            wall_2027_28 += amount
            score += 15
            flags.append(f"2027 maturity: {debt.get('instrument', 'Debt')}")
        elif "2028" in maturity:
            wall_2027_28 += amount
            score += 10
            flags.append(f"2028 maturity: {debt.get('instrument', 'Debt')}")

    # Large near-term maturities relative to total debt
    total_debt = snapshot.get("quick_assessment", {}).get("total_debt") or 0
    if total_debt > 0 and near_term_debt > 0:
        pct_near_term = (near_term_debt / total_debt) * 100
        if pct_near_term > 30:
            score += 25
            flags.append(f"{pct_near_term:.0f}% debt due in 2 years")
        elif pct_near_term > 15:
            score += 15
            flags.append(f"{pct_near_term:.0f}% debt due in 2 years")

    return min(100, score), flags


def calculate_leverage_score(snapshot: Dict) -> Tuple[int, List[str]]:
    """Score leverage risk (0-100)"""
    score = 0
    flags = []

    ratios = snapshot.get("key_ratios", {})
    quick = snapshot.get("quick_assessment", {})

    # Debt/EBITDA
    leverage = ratios.get("debt_to_ebitda") or ratios.get("net_debt_to_ebitda")
    if leverage:
        if leverage >= 8:
            score += 50
            flags.append(f"CRITICAL leverage: {leverage:.1f}x")
        elif leverage >= 6:
            score += 35
            flags.append(f"High leverage: {leverage:.1f}x")
        elif leverage >= 5:
            score += 20
            flags.append(f"Elevated leverage: {leverage:.1f}x")
        elif leverage >= 4:
            score += 10
            flags.append(f"Moderate leverage: {leverage:.1f}x")

    # Negative equity
    equity = quick.get("equity")
    if equity is not None and equity < 0:
        score += 30
        flags.append(f"NEGATIVE equity: {equity}")

    # Negative net income
    net_income = quick.get("net_income")
    if net_income is not None and net_income < 0:
        score += 15
        flags.append("Net income negative")

    return min(100, score), flags


def calculate_liquidity_score(snapshot: Dict) -> Tuple[int, List[str]]:
    """Score liquidity risk (0-100)"""
    score = 0
    flags = []

    quick = snapshot.get("quick_assessment", {})
    mat = snapshot.get("maturity_schedule", {})

    cash = quick.get("cash_on_hand") or 0
    revolver = quick.get("revolver_available") or 0
    total_liquidity = cash + revolver

    debt_due_1y = quick.get("debt_due_one_year") or mat.get("year_1") or 0

    # Liquidity coverage ratio
    if debt_due_1y > 0:
        coverage = total_liquidity / debt_due_1y if debt_due_1y > 0 else float('inf')
        if coverage < 0.5:
            score += 50
            flags.append(f"CRITICAL: Liquidity covers only {coverage:.0%} of near-term debt")
        elif coverage < 1.0:
            score += 35
            flags.append(f"Liquidity gap: {coverage:.0%} coverage of near-term debt")
        elif coverage < 1.5:
            score += 20
            flags.append(f"Tight liquidity: {coverage:.1f}x coverage")

    # Absolute liquidity check
    if total_liquidity > 0 and total_liquidity < 100:  # Assume millions
        score += 20
        flags.append(f"Limited liquidity: ${total_liquidity}M")

    # Interest coverage
    ratios = snapshot.get("key_ratios", {})
    int_coverage = ratios.get("ebitda_minus_capex_to_interest")
    if int_coverage is not None and int_coverage < 1.5:
        score += 25
        flags.append(f"Weak interest coverage: {int_coverage:.1f}x")

    return min(100, score), flags


def calculate_market_score(snapshot: Dict) -> Tuple[int, List[str]]:
    """Score market signals (0-100)"""
    score = 0
    flags = []

    lme_risk = snapshot.get("lme_risk", snapshot.get("lme_risk_proxy", {}))
    distress = snapshot.get("distress_indicators", {})
    debt_cap = snapshot.get("debt_capitalization", [])

    # Bonds trading below par
    if lme_risk.get("bonds_below_80") or lme_risk.get("distress_signals", {}).get("bonds_below_80"):
        score += 40
        flags.append("Bonds trading <80")
    elif lme_risk.get("bonds_below_90") or lme_risk.get("distress_signals", {}).get("bonds_below_90"):
        score += 25
        flags.append("Bonds trading <90")

    # Check debt cap for prices
    for debt in debt_cap:
        price = debt.get("price") or debt.get("price_range")
        if price:
            # Handle price ranges like "94-95"
            if isinstance(price, str) and "-" in price:
                try:
                    low = float(price.split("-")[0])
                    if low < 80:
                        score += 30
                        flags.append(f"{debt.get('instrument', 'Bond')} at {price}")
                    elif low < 90:
                        score += 15
                except Exception:
                    pass
            elif isinstance(price, (int, float)) and price < 90:
                score += 15
                flags.append(f"{debt.get('instrument', 'Bond')} at {price}")

    # High yields
    if lme_risk.get("yields_above_15pct") or lme_risk.get("distress_signals", {}).get("yields_above_12pct"):
        score += 25
        flags.append("Yields >12%")

    # Distress score
    distress_score = distress.get("debtwire_distress_score") or lme_risk.get("distress_score")
    if distress_score:
        if distress_score >= 40:
            score += 30
            flags.append(f"Distress score: {distress_score}")
        elif distress_score >= 25:
            score += 15
            flags.append(f"Distress score: {distress_score}")

    # Advisor hired
    if lme_risk.get("advisor_hired") or lme_risk.get("distress_signals", {}).get("advisor_hired"):
        score += 25
        advisor = lme_risk.get("advisor") or lme_risk.get("distress_signals", {}).get("advisor", "")
        flags.append(f"Advisor hired: {advisor}" if advisor else "Restructuring advisor hired")

    return min(100, score), flags


def calculate_ownership_score(snapshot: Dict) -> Tuple[int, List[str]]:
    """Score ownership risk factors (0-100)"""
    score = 0
    flags = []

    lme_risk = snapshot.get("lme_risk", snapshot.get("lme_risk_proxy", {}))
    overview = snapshot.get("overview", {})

    ownership_info = lme_risk.get("ownership", {})

    # PE-backed = higher LME risk (sponsors protect equity)
    if ownership_info.get("pe_backed") or lme_risk.get("pe_backed"):
        score += 35
        sponsor = ownership_info.get("sponsor") or lme_risk.get("sponsor", "")
        flags.append(f"PE-backed: {sponsor}" if sponsor else "PE-backed")

    # Dividend recap history
    if ownership_info.get("dividend_recap_history") or lme_risk.get("dividend_recap_history"):
        score += 25
        flags.append("History of dividend recaps")

    # Founder controlled (can be aggressive)
    if ownership_info.get("founder_controlled") or "founder" in overview.get("ownership", "").lower():
        score += 15
        flags.append("Founder controlled")

    # Recent restructuring = knows the playbook
    if lme_risk.get("recent_restructuring"):
        score += 20
        flags.append("Recent restructuring history")

    return min(100, score), flags


def determine_likely_path(score: LMERiskScore, snapshot: Dict) -> str:
    """Determine most likely restructuring path based on flags and jurisdiction"""

    lme_risk = snapshot.get("lme_risk", snapshot.get("lme_risk_proxy", {}))
    jurisdiction = lme_risk.get("jurisdiction", snapshot.get("geography", ""))

    # Already in restructuring
    if lme_risk.get("lme_status") == "ACTIVE RESTRUCTURING" or lme_risk.get("recent_restructuring"):
        return "ACTIVE RESTRUCTURING"

    # Score-based path prediction
    if score.total_score < 25:
        return "Refinancing likely"
    elif score.total_score < 40:
        return "Amend & Extend possible"
    elif score.total_score < 55:
        return "Voluntary Exchange likely"
    elif score.total_score < 70:
        # Check for uptier/dropdown risk factors
        if "No LME blockers" in str(score.flags) or "unrestricted" in str(score.flags).lower():
            return "Uptier/Dropdown risk"
        return "Coercive Exchange likely"
    else:
        # High distress - court process likely
        if "france" in jurisdiction.lower():
            return "French Safeguard/Accélérée path"
        elif "uk" in jurisdiction.lower() or "united kingdom" in jurisdiction.lower():
            return "UK Scheme of Arrangement"
        elif "us" in jurisdiction.lower() or "delaware" in jurisdiction.lower():
            return "Chapter 11 likely"
        else:
            return "Court-supervised restructuring likely"


def calculate_lme_risk(snapshot: Dict) -> LMERiskScore:
    """
    Calculate comprehensive LME risk score for a credit.
    Returns score 0-100 with breakdown and flags.
    """

    # Calculate component scores
    doc_score, doc_flags = calculate_doc_score(snapshot)
    mat_score, mat_flags = calculate_maturity_score(snapshot)
    lev_score, lev_flags = calculate_leverage_score(snapshot)
    liq_score, liq_flags = calculate_liquidity_score(snapshot)
    mkt_score, mkt_flags = calculate_market_score(snapshot)
    own_score, own_flags = calculate_ownership_score(snapshot)

    # Weighted total
    total = (
        doc_score * WEIGHTS["doc_quality"] / 100 +
        mat_score * WEIGHTS["maturity"] / 100 +
        lev_score * WEIGHTS["leverage"] / 100 +
        liq_score * WEIGHTS["liquidity"] / 100 +
        mkt_score * WEIGHTS["market_signals"] / 100 +
        own_score * WEIGHTS["ownership"] / 100
    )

    total = min(100, int(total))

    # Determine risk level
    if total >= 70:
        risk_level = "CRITICAL"
    elif total >= 55:
        risk_level = "HIGH"
    elif total >= 40:
        risk_level = "ELEVATED"
    elif total >= 25:
        risk_level = "MODERATE"
    else:
        risk_level = "LOW"

    # Combine flags
    all_flags = doc_flags + mat_flags + lev_flags + liq_flags + mkt_flags + own_flags

    result = LMERiskScore(
        total_score=total,
        risk_level=risk_level,
        doc_score=doc_score,
        maturity_score=mat_score,
        leverage_score=lev_score,
        liquidity_score=liq_score,
        market_score=mkt_score,
        ownership_score=own_score,
        flags=all_flags,
        likely_path=""
    )

    # Determine likely restructuring path
    result.likely_path = determine_likely_path(result, snapshot)

    return result


def load_all_snapshots() -> Dict[str, Dict]:
    """Load all snapshot files"""
    snapshots = {}
    snapshot_dir = Path(__file__).parent.parent / "snapshots"

    for f in snapshot_dir.glob("*.json"):
        if f.name == "template.json":
            continue
        try:
            with open(f, "r") as file:
                data = json.load(file)
                name = data.get("company_name", f.stem)
                snapshots[name] = data
        except Exception:
            continue

    return snapshots


def rank_portfolio_by_lme_risk() -> List[Tuple[str, LMERiskScore]]:
    """Rank entire portfolio by LME risk score"""
    snapshots = load_all_snapshots()
    rankings = []

    for name, snapshot in snapshots.items():
        score = calculate_lme_risk(snapshot)
        rankings.append((name, score))

    # Sort by total score descending
    rankings.sort(key=lambda x: x[1].total_score, reverse=True)

    return rankings


# ============== STREAMLIT UI ==============

def render_lme_risk_dashboard():
    """Render LME Risk Dashboard in Streamlit"""

    st.subheader("LME Risk Dashboard")
    st.caption("Identify credits most likely to pursue Liability Management Exercises")

    # Load and rank
    with st.spinner("Calculating LME risk scores..."):
        rankings = rank_portfolio_by_lme_risk()

    if not rankings:
        st.warning("No snapshot data available. Add company snapshots to enable LME risk scoring.")
        return

    # Summary stats
    critical = sum(1 for _, s in rankings if s.risk_level == "CRITICAL")
    high = sum(1 for _, s in rankings if s.risk_level == "HIGH")
    elevated = sum(1 for _, s in rankings if s.risk_level == "ELEVATED")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Credits", len(rankings))
    with col2:
        st.metric("CRITICAL Risk", critical, delta=None)
    with col3:
        st.metric("HIGH Risk", high)
    with col4:
        st.metric("ELEVATED Risk", elevated)

    st.markdown("---")

    # Filter by risk level
    risk_filter = st.multiselect(
        "Filter by Risk Level",
        ["CRITICAL", "HIGH", "ELEVATED", "MODERATE", "LOW"],
        default=["CRITICAL", "HIGH", "ELEVATED"]
    )

    filtered = [(n, s) for n, s in rankings if s.risk_level in risk_filter]

    # Display rankings
    for name, score in filtered[:30]:  # Top 30
        render_lme_risk_card(name, score)


def render_lme_risk_card(name: str, score: LMERiskScore):
    """Render a single credit's LME risk card"""

    # Color by risk level
    colors = {
        "CRITICAL": "red",
        "HIGH": "orange",
        "ELEVATED": "yellow",
        "MODERATE": "blue",
        "LOW": "green"
    }

    with st.expander(f"**{name}** - Score: {score.total_score}/100 ({score.risk_level})"):
        # Score breakdown
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Score Breakdown:**")
            st.markdown(f"- Docs: {score.doc_score}/100")
            st.markdown(f"- Maturity: {score.maturity_score}/100")
            st.markdown(f"- Leverage: {score.leverage_score}/100")

        with col2:
            st.markdown("**&nbsp;**")
            st.markdown(f"- Liquidity: {score.liquidity_score}/100")
            st.markdown(f"- Market: {score.market_score}/100")
            st.markdown(f"- Ownership: {score.ownership_score}/100")

        with col3:
            st.markdown("**Likely Path:**")
            st.markdown(f"**{score.likely_path}**")

        # Risk flags
        if score.flags:
            st.markdown("**Risk Flags:**")
            cols = st.columns(2)
            for i, flag in enumerate(score.flags[:8]):
                cols[i % 2].markdown(f"- {flag}")

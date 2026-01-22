"""
Trade Workbench - Professional EUR HY Trading Tools
- Catalyst Calendar
- Liquidity Runway Dashboard
- Trade Memo Template
"""

import streamlit as st
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

SNAPSHOTS_DIR = Path(__file__).parent.parent / "snapshots"
CONFIG_DIR = Path(__file__).parent.parent / "config"
CATALYSTS_FILE = CONFIG_DIR / "catalysts.json"
TRADE_MEMOS_FILE = CONFIG_DIR / "trade_memos.json"


# ============== DATA LOADING ==============

def load_all_snapshots() -> List[Dict]:
    """Load all snapshot JSON files"""
    snapshots = []
    if not SNAPSHOTS_DIR.exists():
        return snapshots

    for f in SNAPSHOTS_DIR.glob("*.json"):
        if f.stem == "template":
            continue
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
                data["_filename"] = f.stem
                snapshots.append(data)
        except:
            continue
    return snapshots


def load_catalysts() -> Dict:
    """Load catalyst calendar data"""
    if CATALYSTS_FILE.exists():
        try:
            with open(CATALYSTS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"events": []}


def save_catalysts(data: Dict):
    """Save catalyst calendar data"""
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(CATALYSTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_trade_memos() -> List[Dict]:
    """Load saved trade memos"""
    if TRADE_MEMOS_FILE.exists():
        try:
            with open(TRADE_MEMOS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return []


def save_trade_memos(memos: List[Dict]):
    """Save trade memos"""
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(TRADE_MEMOS_FILE, "w") as f:
        json.dump(memos, f, indent=2)


# ============== CATALYST CALENDAR ==============

CATALYST_TYPES = [
    "Maturity/Refi",
    "Covenant Test",
    "Earnings",
    "Rating Review",
    "M&A Event",
    "Asset Sale",
    "Call Date",
    "Court/Legal",
    "Sponsor Decision",
    "Other"
]


def extract_maturities_from_snapshots(snapshots: List[Dict]) -> List[Dict]:
    """Extract maturity dates from debt capitalization tables"""
    events = []
    today = datetime.now()

    for snap in snapshots:
        company = snap.get("company_name", "Unknown")
        debt_cap = snap.get("debt_capitalization", [])

        for instrument in debt_cap:
            maturity_str = instrument.get("maturity", "")
            if not maturity_str:
                continue

            # Try to parse maturity date (format: YYYY or MM/YYYY or YYYY-MM-DD)
            try:
                if len(maturity_str) == 4:  # Just year
                    mat_date = datetime(int(maturity_str), 12, 31)
                elif "/" in maturity_str:
                    parts = maturity_str.split("/")
                    if len(parts) == 2:
                        mat_date = datetime(int(parts[1]), int(parts[0]), 1)
                    else:
                        continue
                elif "-" in maturity_str:
                    mat_date = datetime.strptime(maturity_str[:10], "%Y-%m-%d")
                else:
                    continue

                # Only include if within next 3 years
                if mat_date > today and mat_date < today + timedelta(days=1095):
                    amount = instrument.get("amount", 0) or 0
                    events.append({
                        "company": company,
                        "type": "Maturity/Refi",
                        "date": mat_date.strftime("%Y-%m-%d"),
                        "description": f"{instrument.get('instrument', 'Debt')} - ${amount}m",
                        "amount": amount,
                        "source": "auto"
                    })
            except:
                continue

    return events


def render_catalyst_calendar():
    """Render the catalyst calendar UI"""
    st.subheader("Catalyst Calendar")
    st.caption("Track refi dates, covenant tests, earnings, rating reviews")

    # Load data
    snapshots = load_all_snapshots()
    catalysts_data = load_catalysts()
    manual_events = catalysts_data.get("events", [])

    # Extract maturities from snapshots
    auto_events = extract_maturities_from_snapshots(snapshots)

    # Combine events
    all_events = auto_events + [e for e in manual_events if e.get("source") == "manual"]

    # Filter and sort
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        time_filter = st.selectbox(
            "Time horizon",
            ["Next 30 days", "Next 90 days", "Next 180 days", "Next 12 months", "All"],
            index=2
        )

    with col2:
        type_filter = st.multiselect(
            "Event types",
            CATALYST_TYPES,
            default=["Maturity/Refi", "Covenant Test", "Rating Review"]
        )

    with col3:
        company_list = sorted(set(snap.get("company_name", "") for snap in snapshots))
        company_filter = st.multiselect("Companies", company_list, default=[])

    # Apply time filter
    today = datetime.now()
    if time_filter == "Next 30 days":
        cutoff = today + timedelta(days=30)
    elif time_filter == "Next 90 days":
        cutoff = today + timedelta(days=90)
    elif time_filter == "Next 180 days":
        cutoff = today + timedelta(days=180)
    elif time_filter == "Next 12 months":
        cutoff = today + timedelta(days=365)
    else:
        cutoff = today + timedelta(days=3650)

    # Filter events
    filtered = []
    for event in all_events:
        try:
            event_date = datetime.strptime(event["date"], "%Y-%m-%d")
            if event_date < today or event_date > cutoff:
                continue
            if type_filter and event.get("type") not in type_filter:
                continue
            if company_filter and event.get("company") not in company_filter:
                continue
            event["_date_obj"] = event_date
            event["_days_away"] = (event_date - today).days
            filtered.append(event)
        except:
            continue

    # Sort by date
    filtered.sort(key=lambda x: x["_date_obj"])

    st.markdown("---")

    # Display calendar
    if filtered:
        st.markdown(f"**{len(filtered)} events** in selected period")

        # Group by urgency
        urgent = [e for e in filtered if e["_days_away"] <= 30]
        upcoming = [e for e in filtered if 30 < e["_days_away"] <= 90]
        later = [e for e in filtered if e["_days_away"] > 90]

        if urgent:
            st.markdown("### Next 30 Days")
            for event in urgent:
                render_catalyst_event(event, "urgent")

        if upcoming:
            st.markdown("### 30-90 Days")
            for event in upcoming:
                render_catalyst_event(event, "upcoming")

        if later:
            st.markdown("### 90+ Days")
            for event in later:
                render_catalyst_event(event, "later")
    else:
        st.info("No events match your filters")

    # Add new event form
    st.markdown("---")
    st.markdown("### Add Catalyst Event")

    with st.form("add_catalyst"):
        col1, col2 = st.columns(2)
        with col1:
            new_company = st.selectbox("Company", [""] + company_list)
            new_type = st.selectbox("Event Type", CATALYST_TYPES)
        with col2:
            new_date = st.date_input("Date", min_value=datetime.now().date())
            new_desc = st.text_input("Description")

        if st.form_submit_button("Add Event"):
            if new_company and new_desc:
                manual_events.append({
                    "company": new_company,
                    "type": new_type,
                    "date": new_date.strftime("%Y-%m-%d"),
                    "description": new_desc,
                    "source": "manual"
                })
                catalysts_data["events"] = manual_events
                save_catalysts(catalysts_data)
                st.success(f"Added event for {new_company}")
                st.rerun()
            else:
                st.warning("Please fill in company and description")


def render_catalyst_event(event: Dict, urgency: str):
    """Render a single catalyst event"""
    if urgency == "urgent":
        icon = "🔴"
    elif urgency == "upcoming":
        icon = "🟡"
    else:
        icon = "🟢"

    days = event["_days_away"]
    date_str = event["date"]

    col1, col2, col3, col4 = st.columns([1, 2, 2, 1])
    with col1:
        st.markdown(f"{icon} **{days}d**")
    with col2:
        st.markdown(f"**{event['company']}**")
    with col3:
        st.markdown(f"{event['type']}: {event['description']}")
    with col4:
        st.caption(date_str)


# ============== LIQUIDITY RUNWAY DASHBOARD ==============

def calculate_runway(snapshot: Dict) -> Dict:
    """Calculate liquidity runway metrics for a company"""
    qa = snapshot.get("quick_assessment", {})

    cash = qa.get("cash_on_hand", 0) or 0
    revolver = qa.get("revolver_available", 0) or 0
    debt_due = qa.get("debt_due_one_year", 0) or 0

    total_liquidity = cash + revolver

    # Get annual cash burn/generation from FCF
    ratios = snapshot.get("key_ratios", {})
    total_debt = qa.get("total_debt", 0) or 0
    fcf_to_debt = ratios.get("fcf_to_debt")

    # Estimate annual FCF
    if fcf_to_debt and total_debt:
        annual_fcf = fcf_to_debt * total_debt
    else:
        # Try from trend analysis
        trend = snapshot.get("trend_analysis", {})
        fcf_list = trend.get("simple_fcf", [])
        annual_fcf = fcf_list[-1] if fcf_list else 0

    # Calculate months of runway
    if debt_due > 0:
        coverage_ratio = total_liquidity / debt_due
    else:
        coverage_ratio = float('inf') if total_liquidity > 0 else 0

    # Months of runway (simplified: liquidity / monthly cash needs)
    if annual_fcf < 0:  # Cash burning
        monthly_burn = abs(annual_fcf) / 12
        if monthly_burn > 0:
            months_runway = total_liquidity / monthly_burn
        else:
            months_runway = float('inf')
    else:
        months_runway = float('inf')  # FCF positive = no liquidity pressure from ops

    # Risk score (0-100, higher = more risk)
    risk_score = 0

    # Near-term maturity risk
    if debt_due > 0:
        if coverage_ratio < 1.0:
            risk_score += 40
        elif coverage_ratio < 1.5:
            risk_score += 25
        elif coverage_ratio < 2.0:
            risk_score += 10

    # Cash burn risk
    if annual_fcf < 0:
        if months_runway < 12:
            risk_score += 40
        elif months_runway < 18:
            risk_score += 25
        elif months_runway < 24:
            risk_score += 15

    # Absolute liquidity
    if total_liquidity < 100:
        risk_score += 20
    elif total_liquidity < 250:
        risk_score += 10

    return {
        "company": snapshot.get("company_name", "Unknown"),
        "sector": snapshot.get("sector", "Unknown"),
        "cash": cash,
        "revolver": revolver,
        "total_liquidity": total_liquidity,
        "debt_due_12m": debt_due,
        "coverage_ratio": coverage_ratio,
        "annual_fcf": annual_fcf,
        "months_runway": months_runway,
        "risk_score": risk_score
    }


def render_liquidity_runway():
    """Render the liquidity runway dashboard"""
    st.subheader("Liquidity Runway Dashboard")
    st.caption("Cash + revolver vs near-term maturities | Who's got problems?")

    # Load all snapshots
    snapshots = load_all_snapshots()

    if not snapshots:
        st.warning("No snapshots available")
        return

    # Calculate runway for all companies
    runway_data = []
    for snap in snapshots:
        runway = calculate_runway(snap)
        runway_data.append(runway)

    # Sort by risk score (highest risk first)
    runway_data.sort(key=lambda x: x["risk_score"], reverse=True)

    # Summary stats
    high_risk = [r for r in runway_data if r["risk_score"] >= 50]
    medium_risk = [r for r in runway_data if 25 <= r["risk_score"] < 50]
    low_risk = [r for r in runway_data if r["risk_score"] < 25]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("High Risk", len(high_risk), help="Risk score >= 50")
    with col2:
        st.metric("Medium Risk", len(medium_risk), help="Risk score 25-50")
    with col3:
        st.metric("Low Risk", len(low_risk), help="Risk score < 25")
    with col4:
        st.metric("Total Analyzed", len(runway_data))

    st.markdown("---")

    # High risk names (detailed)
    if high_risk:
        st.markdown("### High Risk Names")
        st.caption("Coverage < 1.0x or runway < 12 months")

        for r in high_risk:
            render_runway_card(r, "high")

    # Medium risk names
    if medium_risk:
        st.markdown("### Medium Risk Names")

        for r in medium_risk:
            render_runway_card(r, "medium")

    # Full table
    st.markdown("---")
    st.markdown("### All Companies")

    df = pd.DataFrame([{
        "Company": r["company"],
        "Sector": r["sector"],
        "Cash ($m)": r["cash"],
        "Revolver ($m)": r["revolver"],
        "Liquidity ($m)": r["total_liquidity"],
        "12m Maturities ($m)": r["debt_due_12m"],
        "Coverage": f"{r['coverage_ratio']:.1f}x" if r["coverage_ratio"] != float('inf') else "N/A",
        "FCF ($m)": f"{r['annual_fcf']:.0f}" if r["annual_fcf"] else "N/A",
        "Risk Score": r["risk_score"]
    } for r in runway_data])

    st.dataframe(df, hide_index=True, use_container_width=True)


def render_runway_card(runway: Dict, severity: str):
    """Render a liquidity runway card"""
    if severity == "high":
        st.error(f"**{runway['company']}** ({runway['sector']}) - Risk Score: {runway['risk_score']}")
    else:
        st.warning(f"**{runway['company']}** ({runway['sector']}) - Risk Score: {runway['risk_score']}")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Liquidity", f"${runway['total_liquidity']:.0f}m")
    with col2:
        st.metric("12m Maturities", f"${runway['debt_due_12m']:.0f}m")
    with col3:
        cov = runway['coverage_ratio']
        st.metric("Coverage", f"{cov:.1f}x" if cov != float('inf') else "Ample")
    with col4:
        fcf = runway['annual_fcf']
        if fcf:
            st.metric("Annual FCF", f"${fcf:.0f}m", delta="Burning" if fcf < 0 else "Generating")
        else:
            st.metric("Annual FCF", "N/A")


# ============== TRADE MEMO TEMPLATE ==============

TRADE_TYPES = [
    "Quality Carry Long + Beta Hedge",
    "Broken Credit Short",
    "Capital Structure RV",
    "Event-Driven (M&A/LBO/Asset Sale)",
    "Fallen Angel / Rising Star",
    "Technical Dislocation",
    "Basis/Curve Trade"
]


def render_trade_memo():
    """Render the trade memo template"""
    st.subheader("Trade Memo")
    st.caption("Structured format: claim, timeline, downside, variant perception, kill-switch")

    # Load existing memos
    memos = load_trade_memos()
    snapshots = load_all_snapshots()
    company_list = sorted(set(snap.get("company_name", "") for snap in snapshots))

    tab1, tab2 = st.tabs(["New Memo", "Saved Memos"])

    with tab1:
        render_new_memo_form(company_list, memos)

    with tab2:
        render_saved_memos(memos)


def render_new_memo_form(company_list: List[str], memos: List[Dict]):
    """Render form for creating new trade memo"""

    st.markdown("### The Claim")

    col1, col2, col3 = st.columns(3)
    with col1:
        company = st.selectbox("Company", [""] + company_list, key="memo_company")
    with col2:
        trade_type = st.selectbox("Trade Type", TRADE_TYPES, key="memo_type")
    with col3:
        direction = st.selectbox("Direction", ["Long", "Short"], key="memo_direction")

    col1, col2 = st.columns(2)
    with col1:
        instrument = st.text_input("Instrument", placeholder="e.g., 6.5% 2028 Senior Secured, 5Y CDS", key="memo_instrument")
    with col2:
        entry_level = st.text_input("Entry Level", placeholder="e.g., 450bps, 85 price", key="memo_entry")

    thesis = st.text_area(
        "Why is this mispriced? (The core thesis)",
        placeholder="Market thinks X, but actually Y because...",
        height=100,
        key="memo_thesis"
    )

    st.markdown("### The Timeline")
    st.caption("Explicit 30/90/180-day catalyst map")

    col1, col2, col3 = st.columns(3)
    with col1:
        catalyst_30d = st.text_area("30-Day Catalysts", placeholder="What happens in next 30 days?", height=80, key="memo_30d")
    with col2:
        catalyst_90d = st.text_area("90-Day Catalysts", placeholder="What happens in 30-90 days?", height=80, key="memo_90d")
    with col3:
        catalyst_180d = st.text_area("180-Day Catalysts", placeholder="What happens in 90-180 days?", height=80, key="memo_180d")

    st.markdown("### Downside Map")
    st.caption("What happens in stress; recovery framing; legal path")

    downside = st.text_area(
        "Downside Scenario",
        placeholder="If wrong, what's the loss? Recovery value? Where does value go in a restructuring?",
        height=100,
        key="memo_downside"
    )

    col1, col2 = st.columns(2)
    with col1:
        recovery_estimate = st.text_input("Recovery Estimate (if default)", placeholder="e.g., 40-50 cents", key="memo_recovery")
    with col2:
        max_loss = st.text_input("Max Loss Estimate", placeholder="e.g., -15 points, -200bps", key="memo_maxloss")

    st.markdown("### Variant Perception")
    st.caption("What the market thinks vs what you think is wrong")

    col1, col2 = st.columns(2)
    with col1:
        market_view = st.text_area("Market Consensus", placeholder="What does the market think?", height=80, key="memo_market")
    with col2:
        variant_view = st.text_area("Your Variant View", placeholder="Why is the market wrong?", height=80, key="memo_variant")

    st.markdown("### Hedge & Sizing")

    col1, col2, col3 = st.columns(3)
    with col1:
        hedge = st.text_input("Hedge", placeholder="e.g., Short Xover, Short sector basket", key="memo_hedge")
    with col2:
        position_size = st.text_input("Position Size", placeholder="e.g., 2% NAV, €5m notional", key="memo_size")
    with col3:
        target = st.text_input("Target Level", placeholder="e.g., 350bps, 95 price", key="memo_target")

    st.markdown("### Kill Switch")
    st.caption("What would disprove the thesis, and at what price/time?")

    col1, col2 = st.columns(2)
    with col1:
        kill_price = st.text_input("Stop Loss Level", placeholder="e.g., 550bps, 78 price", key="memo_stop")
    with col2:
        kill_time = st.text_input("Time Stop", placeholder="e.g., Exit if no catalyst by June", key="memo_timestop")

    kill_thesis = st.text_area(
        "Thesis Invalidation",
        placeholder="What would prove you wrong? What would make you exit regardless of P&L?",
        height=80,
        key="memo_killthesis"
    )

    st.markdown("---")

    if st.button("Save Trade Memo", type="primary"):
        if company and thesis:
            new_memo = {
                "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "company": company,
                "trade_type": trade_type,
                "direction": direction,
                "instrument": instrument,
                "entry_level": entry_level,
                "thesis": thesis,
                "catalyst_30d": catalyst_30d,
                "catalyst_90d": catalyst_90d,
                "catalyst_180d": catalyst_180d,
                "downside": downside,
                "recovery_estimate": recovery_estimate,
                "max_loss": max_loss,
                "market_view": market_view,
                "variant_view": variant_view,
                "hedge": hedge,
                "position_size": position_size,
                "target": target,
                "kill_price": kill_price,
                "kill_time": kill_time,
                "kill_thesis": kill_thesis,
                "status": "Active"
            }
            memos.append(new_memo)
            save_trade_memos(memos)
            st.success(f"Saved memo for {company}")
            st.rerun()
        else:
            st.warning("Please fill in at least Company and Thesis")


def render_saved_memos(memos: List[Dict]):
    """Render list of saved trade memos"""

    if not memos:
        st.info("No saved memos. Create one in the 'New Memo' tab.")
        return

    # Filter by status
    status_filter = st.selectbox("Filter by status", ["All", "Active", "Closed", "Stopped Out"])

    filtered = memos if status_filter == "All" else [m for m in memos if m.get("status") == status_filter]

    st.markdown(f"**{len(filtered)} memos**")

    for memo in reversed(filtered):  # Most recent first
        with st.expander(f"**{memo['company']}** - {memo['direction']} {memo['trade_type']} ({memo['created']})"):

            # Header
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(f"**Instrument:** {memo.get('instrument', 'N/A')}")
            with col2:
                st.markdown(f"**Entry:** {memo.get('entry_level', 'N/A')}")
            with col3:
                st.markdown(f"**Target:** {memo.get('target', 'N/A')}")
            with col4:
                st.markdown(f"**Stop:** {memo.get('kill_price', 'N/A')}")

            # Thesis
            st.markdown("**Thesis:**")
            st.markdown(memo.get("thesis", ""))

            # Variant
            if memo.get("variant_view"):
                st.markdown("**Variant View:**")
                st.markdown(memo.get("variant_view", ""))

            # Catalysts
            col1, col2, col3 = st.columns(3)
            with col1:
                if memo.get("catalyst_30d"):
                    st.markdown("**30d:**")
                    st.caption(memo["catalyst_30d"])
            with col2:
                if memo.get("catalyst_90d"):
                    st.markdown("**90d:**")
                    st.caption(memo["catalyst_90d"])
            with col3:
                if memo.get("catalyst_180d"):
                    st.markdown("**180d:**")
                    st.caption(memo["catalyst_180d"])

            # Status update
            st.markdown("---")
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                new_status = st.selectbox(
                    "Update Status",
                    ["Active", "Closed - Won", "Closed - Lost", "Stopped Out"],
                    key=f"status_{memo['id']}"
                )
            with col2:
                if st.button("Update", key=f"update_{memo['id']}"):
                    memo["status"] = new_status
                    save_trade_memos(memos)
                    st.rerun()
            with col3:
                if st.button("Delete", key=f"delete_{memo['id']}"):
                    memos.remove(memo)
                    save_trade_memos(memos)
                    st.rerun()


# ============== MAIN RENDER ==============

def render_trade_workbench():
    """Main render function for trade workbench"""

    tool = st.radio(
        "Select Tool",
        ["Catalyst Calendar", "Liquidity Runway", "Trade Memo"],
        horizontal=True
    )

    st.markdown("---")

    if tool == "Catalyst Calendar":
        render_catalyst_calendar()
    elif tool == "Liquidity Runway":
        render_liquidity_runway()
    elif tool == "Trade Memo":
        render_trade_memo()

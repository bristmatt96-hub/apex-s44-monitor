"""
Trading Tools for XO S44 Credit Monitor
- LME Risk Dashboard
- Earnings Sentiment Analyzer
- What-If Stress Calculator
- Maturity Wall Visualizer
- Data Freshness Tracker
- Position Tracker with P&L
"""

import streamlit as st
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

SNAPSHOTS_DIR = Path(__file__).parent.parent / "snapshots"


def load_all_snapshots() -> List[Dict]:
    """Load all snapshot JSON files"""
    snapshots = []
    if not SNAPSHOTS_DIR.exists():
        return snapshots

    for f in SNAPSHOTS_DIR.glob("*.json"):
        if f.name == "template.json":
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                data["_filename"] = f.name
                data["_filepath"] = str(f)
                snapshots.append(data)
        except Exception as e:
            pass

    return sorted(snapshots, key=lambda x: x.get("company_name", ""))


# ============== WHAT-IF STRESS CALCULATOR ==============

def render_whatif_calculator():
    """Render the What-If stress testing calculator"""
    st.subheader("📊 What-If Stress Calculator")
    st.caption("Test how credit metrics change under stress scenarios")

    snapshots = load_all_snapshots()
    if not snapshots:
        st.warning("No snapshots available")
        return

    # Company selector
    company_names = [s.get("company_name", "Unknown") for s in snapshots]
    selected_name = st.selectbox("Select Company", company_names, key="whatif_company")

    # Get selected snapshot
    snapshot = next((s for s in snapshots if s.get("company_name") == selected_name), None)
    if not snapshot:
        st.error("Snapshot not found")
        return

    # Extract current metrics
    ratios = snapshot.get("key_ratios", {})
    quick = snapshot.get("quick_assessment", {})

    current_ebitda = quick.get("ebitda") or 0
    current_debt = quick.get("total_debt") or 0
    current_interest = quick.get("interest_expense") or 0
    current_revenue = quick.get("revenue") or 0

    # Calculate current ratios
    current_leverage = ratios.get("net_debt_to_ebitda") or ratios.get("debt_to_ebitda") or 0
    current_margin = ratios.get("ebitda_margin") or 0

    if current_ebitda == 0:
        st.warning(f"No EBITDA data for {selected_name}")
        return

    st.markdown("---")

    # Create two columns
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Current State")
        st.metric("EBITDA", f"${current_ebitda:,.0f}m")
        st.metric("Total Debt", f"${current_debt:,.0f}m")
        st.metric("Leverage", f"{current_leverage:.1f}x")
        if current_margin:
            st.metric("EBITDA Margin", f"{current_margin:.1f}%")

    with col2:
        st.markdown("### Stress Scenario")

        # Sliders for stress
        ebitda_shock = st.slider(
            "EBITDA Change %",
            min_value=-50,
            max_value=20,
            value=0,
            step=5,
            help="Simulate EBITDA decline/growth"
        )

        rate_shock = st.slider(
            "Interest Rate Change (bps)",
            min_value=0,
            max_value=400,
            value=0,
            step=25,
            help="Simulate interest rate increase"
        )

        debt_change = st.slider(
            "Debt Change %",
            min_value=-20,
            max_value=30,
            value=0,
            step=5,
            help="Simulate debt paydown or increase"
        )

    # Calculate stressed metrics
    stressed_ebitda = current_ebitda * (1 + ebitda_shock / 100)
    stressed_debt = current_debt * (1 + debt_change / 100)

    # Estimate interest expense increase (rough: assume average debt cost ~5%)
    additional_interest = current_debt * (rate_shock / 10000)  # bps to decimal
    stressed_interest = (current_interest or current_debt * 0.05) + additional_interest

    # Calculate stressed ratios
    stressed_leverage = stressed_debt / stressed_ebitda if stressed_ebitda > 0 else float('inf')
    stressed_coverage = stressed_ebitda / stressed_interest if stressed_interest > 0 else float('inf')

    st.markdown("---")
    st.markdown("### Stressed Metrics")

    col3, col4, col5 = st.columns(3)

    with col3:
        leverage_delta = stressed_leverage - current_leverage
        color = "🔴" if leverage_delta > 1 else "🟡" if leverage_delta > 0.5 else "🟢"
        st.metric(
            "Stressed Leverage",
            f"{stressed_leverage:.1f}x",
            delta=f"{leverage_delta:+.1f}x",
            delta_color="inverse"
        )
        st.caption(f"{color} {'DANGER' if leverage_delta > 1 else 'CAUTION' if leverage_delta > 0.5 else 'OK'}")

    with col4:
        st.metric(
            "Stressed EBITDA",
            f"${stressed_ebitda:,.0f}m",
            delta=f"{ebitda_shock:+.0f}%"
        )

    with col5:
        if stressed_coverage < float('inf'):
            coverage_status = "🔴 DISTRESS" if stressed_coverage < 1.5 else "🟡 TIGHT" if stressed_coverage < 2.5 else "🟢 OK"
            st.metric(
                "Interest Coverage",
                f"{stressed_coverage:.1f}x",
            )
            st.caption(coverage_status)

    # Rating implications
    st.markdown("---")
    st.markdown("### Rating Implications")

    if stressed_leverage > 7:
        st.error("⚠️ Leverage >7x typically implies CCC category - HIGH DEFAULT RISK")
    elif stressed_leverage > 5:
        st.warning("⚠️ Leverage 5-7x typically implies B category - SPECULATIVE")
    elif stressed_leverage > 4:
        st.info("Leverage 4-5x typically implies BB category - NON-INVESTMENT GRADE")
    elif stressed_leverage > 3:
        st.success("Leverage 3-4x typically implies BBB category - INVESTMENT GRADE")
    else:
        st.success("Leverage <3x typically implies A category or better")


# ============== MATURITY WALL VISUALIZER ==============

def render_maturity_wall():
    """Render the maturity wall visualization"""
    st.subheader("🧱 Maturity Wall")
    st.caption("Debt maturities across all XO S44 names")

    snapshots = load_all_snapshots()
    if not snapshots:
        st.warning("No snapshots available")
        return

    # Collect all maturities
    maturities = []

    for snap in snapshots:
        company = snap.get("company_name", "Unknown")
        schedule = snap.get("maturity_schedule", {})
        debt_cap = snap.get("debt_capitalization", [])

        # From maturity_schedule
        for year, amount in schedule.items():
            if year and str(year).isdigit() and amount:
                maturities.append({
                    "company": company,
                    "year": int(year),
                    "amount": amount,
                    "source": "schedule"
                })

        # From debt_capitalization (if not in schedule)
        for inst in debt_cap:
            mat_str = inst.get("maturity", "")
            amount = inst.get("amount", 0)
            if not mat_str or not amount:
                continue

            # Try to extract year
            year = None
            if mat_str.isdigit() and len(mat_str) == 4:
                year = int(mat_str)
            else:
                # Try to find 4-digit year in string
                import re
                match = re.search(r'20\d{2}', mat_str)
                if match:
                    year = int(match.group())

            if year and year >= 2025 and year <= 2035:
                # Check if not already in schedule
                existing = [m for m in maturities if m["company"] == company and m["year"] == year]
                if not existing:
                    maturities.append({
                        "company": company,
                        "year": year,
                        "amount": amount,
                        "source": "debt_cap"
                    })

    if not maturities:
        st.warning("No maturity data available")
        return

    # Create DataFrame
    df = pd.DataFrame(maturities)

    # Aggregate by year
    yearly = df.groupby("year")["amount"].sum().reset_index()
    yearly.columns = ["Year", "Amount ($m)"]

    # Display chart
    st.markdown("### Total Maturities by Year")
    st.bar_chart(yearly.set_index("Year"))

    # Show near-term details
    st.markdown("---")
    current_year = datetime.now().year

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"### {current_year} Maturities")
        this_year = df[df["year"] == current_year].sort_values("amount", ascending=False)
        if len(this_year) > 0:
            for _, row in this_year.head(10).iterrows():
                st.write(f"• **{row['company']}**: ${row['amount']:,.0f}m")
        else:
            st.write("None")

    with col2:
        st.markdown(f"### {current_year + 1} Maturities")
        next_year = df[df["year"] == current_year + 1].sort_values("amount", ascending=False)
        if len(next_year) > 0:
            for _, row in next_year.head(10).iterrows():
                st.write(f"• **{row['company']}**: ${row['amount']:,.0f}m")
        else:
            st.write("None")

    # Summary table
    st.markdown("---")
    st.markdown("### Full Maturity Schedule")

    # Pivot by company and year
    pivot = df.pivot_table(
        index="company",
        columns="year",
        values="amount",
        aggfunc="sum",
        fill_value=0
    )

    # Sort by total debt
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)

    st.dataframe(pivot.head(20), use_container_width=True)


# ============== DATA FRESHNESS TRACKER ==============

def render_freshness_tracker():
    """Track how fresh/stale the snapshot data is"""
    st.subheader("📅 Data Freshness")
    st.caption("Monitor when snapshots were last updated")

    snapshots = load_all_snapshots()
    if not snapshots:
        st.warning("No snapshots available")
        return

    today = datetime.now()

    freshness_data = []

    for snap in snapshots:
        company = snap.get("company_name", "Unknown")
        last_updated = snap.get("last_updated", "")
        period_end = snap.get("quick_assessment", {}).get("period_end", "")

        # Parse last_updated
        update_date = None
        if last_updated:
            try:
                update_date = datetime.strptime(last_updated, "%Y-%m-%d")
            except:
                pass

        # Calculate staleness
        days_old = None
        if update_date:
            days_old = (today - update_date).days

        # Determine status
        if days_old is None:
            status = "❓ Unknown"
            status_order = 4
        elif days_old <= 7:
            status = "🟢 Fresh"
            status_order = 1
        elif days_old <= 30:
            status = "🟡 Recent"
            status_order = 2
        elif days_old <= 90:
            status = "🟠 Aging"
            status_order = 3
        else:
            status = "🔴 Stale"
            status_order = 5

        freshness_data.append({
            "Company": company,
            "Last Updated": last_updated or "Unknown",
            "Period End": period_end or "Unknown",
            "Days Old": days_old if days_old else "N/A",
            "Status": status,
            "_order": status_order
        })

    # Create DataFrame
    df = pd.DataFrame(freshness_data)
    df = df.sort_values("_order")

    # Summary stats
    col1, col2, col3, col4 = st.columns(4)

    fresh = len([d for d in freshness_data if d["Status"] == "🟢 Fresh"])
    recent = len([d for d in freshness_data if d["Status"] == "🟡 Recent"])
    aging = len([d for d in freshness_data if d["Status"] == "🟠 Aging"])
    stale = len([d for d in freshness_data if "Stale" in d["Status"] or "Unknown" in d["Status"]])

    col1.metric("🟢 Fresh (<7d)", fresh)
    col2.metric("🟡 Recent (<30d)", recent)
    col3.metric("🟠 Aging (<90d)", aging)
    col4.metric("🔴 Stale/Unknown", stale)

    # Show stale ones first
    st.markdown("---")
    st.markdown("### Snapshots Needing Update")
    stale_df = df[df["_order"] >= 3][["Company", "Last Updated", "Period End", "Status"]]
    if len(stale_df) > 0:
        st.dataframe(stale_df, use_container_width=True, hide_index=True)
    else:
        st.success("All snapshots are fresh!")

    # Full table
    st.markdown("---")
    with st.expander("All Snapshots"):
        st.dataframe(df[["Company", "Last Updated", "Period End", "Days Old", "Status"]],
                    use_container_width=True, hide_index=True)


# ============== POSITION TRACKER ==============

def render_position_tracker():
    """Track positions and estimate P&L from spread moves"""
    st.subheader("💰 Position Tracker")
    st.caption("Track your positions and estimate P&L from spread changes")

    # Initialize session state for positions
    if "positions" not in st.session_state:
        st.session_state.positions = []

    snapshots = load_all_snapshots()
    company_names = [""] + [s.get("company_name", "Unknown") for s in snapshots]

    # Add position form
    st.markdown("### Add Position")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        new_company = st.selectbox("Company", company_names, key="pos_company")
    with col2:
        new_notional = st.number_input("Notional ($m)", min_value=0.0, value=1.0, step=0.5, key="pos_notional")
    with col3:
        new_direction = st.selectbox("Direction", ["Long Protection", "Short Protection", "Long Bond", "Short Bond"], key="pos_direction")
    with col4:
        new_entry = st.number_input("Entry Spread (bps)", min_value=0, value=300, step=25, key="pos_entry")

    if st.button("Add Position") and new_company:
        st.session_state.positions.append({
            "company": new_company,
            "notional": new_notional,
            "direction": new_direction,
            "entry_spread": new_entry,
            "current_spread": new_entry
        })
        st.success(f"Added {new_direction} on {new_company}")
        st.rerun()

    if not st.session_state.positions:
        st.info("No positions tracked. Add positions above.")
        return

    # Display positions
    st.markdown("---")
    st.markdown("### Current Positions")

    # Simulate spread changes
    spread_move = st.slider(
        "Simulate Market-Wide Spread Move (bps)",
        min_value=-200,
        max_value=200,
        value=0,
        step=10,
        help="Simulate parallel shift in spreads"
    )

    total_pnl = 0
    position_data = []

    for i, pos in enumerate(st.session_state.positions):
        current_spread = pos["entry_spread"] + spread_move

        # Rough P&L calculation
        # For CDS: Long protection profits when spreads widen
        # DV01 rough estimate: ~4.5 per 1bp per $1m notional (5yr CDS)
        dv01 = 4.5 * pos["notional"]  # $ per bp
        spread_change = current_spread - pos["entry_spread"]

        if "Long Protection" in pos["direction"]:
            pnl = spread_change * dv01 / 1000  # in $k
        elif "Short Protection" in pos["direction"]:
            pnl = -spread_change * dv01 / 1000
        elif "Long Bond" in pos["direction"]:
            pnl = -spread_change * dv01 / 1000  # bonds lose when spreads widen
        else:  # Short Bond
            pnl = spread_change * dv01 / 1000

        total_pnl += pnl

        position_data.append({
            "Company": pos["company"],
            "Direction": pos["direction"],
            "Notional": f"${pos['notional']:.1f}m",
            "Entry": f"{pos['entry_spread']}bps",
            "Current": f"{current_spread}bps",
            "P&L": f"${pnl:+,.0f}k",
            "_pnl": pnl,
            "_idx": i
        })

    # Show as table
    df = pd.DataFrame(position_data)

    # Color code P&L
    st.dataframe(
        df[["Company", "Direction", "Notional", "Entry", "Current", "P&L"]],
        use_container_width=True,
        hide_index=True
    )

    # Total P&L
    col1, col2, col3 = st.columns(3)
    with col2:
        pnl_color = "green" if total_pnl >= 0 else "red"
        st.markdown(f"### Total P&L: <span style='color:{pnl_color}'>${total_pnl:+,.0f}k</span>", unsafe_allow_html=True)

    # Clear positions button
    st.markdown("---")
    if st.button("Clear All Positions"):
        st.session_state.positions = []
        st.rerun()


# ============== LME RISK DASHBOARD ==============

def render_lme_risk_dashboard_wrapper():
    """Wrapper to import and render LME Risk Dashboard"""
    try:
        from monitors.lme_risk_calculator import render_lme_risk_dashboard
        render_lme_risk_dashboard()
    except ImportError as e:
        st.error(f"Could not load LME Risk Calculator: {e}")
    except Exception as e:
        st.error(f"Error rendering LME Risk Dashboard: {e}")


# ============== EARNINGS SENTIMENT ANALYZER ==============

def render_earnings_sentiment_wrapper():
    """Wrapper to import and render Earnings Sentiment Analyzer"""
    try:
        from monitors.earnings_sentiment import render_earnings_analyzer
        render_earnings_analyzer()
    except ImportError as e:
        st.error(f"Could not load Earnings Sentiment Analyzer: {e}")
    except Exception as e:
        st.error(f"Error rendering Earnings Sentiment Analyzer: {e}")


# ============== MAIN RENDER FUNCTION ==============

def render_trading_tools():
    """Main render function for trading tools tab"""

    tool = st.radio(
        "Select Tool",
        ["LME Risk Dashboard", "Earnings Sentiment", "What-If Calculator", "Maturity Wall", "Data Freshness", "Position Tracker"],
        horizontal=True
    )

    st.markdown("---")

    if tool == "LME Risk Dashboard":
        render_lme_risk_dashboard_wrapper()
    elif tool == "Earnings Sentiment":
        render_earnings_sentiment_wrapper()
    elif tool == "What-If Calculator":
        render_whatif_calculator()
    elif tool == "Maturity Wall":
        render_maturity_wall()
    elif tool == "Data Freshness":
        render_freshness_tracker()
    elif tool == "Position Tracker":
        render_position_tracker()

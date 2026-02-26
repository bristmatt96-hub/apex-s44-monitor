"""
Agent Trading Dashboard
Professional Portfolio Management Interface

Features:
- Passcode authentication for security
- Kill switch to disable all systems
- Full portfolio management

Run: streamlit run dashboard/app.py
"""
import streamlit as st
import pandas as pd
import asyncio
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
import sys
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from portfolio.position_tracker import get_position_tracker, Position, PositionType
from portfolio.trade_journal import get_trade_journal, TradeEntry
from portfolio.stop_monitor import get_stop_monitor
from portfolio.earnings_calendar import get_earnings_calendar
from portfolio.options_greeks import get_options_greeks
from portfolio.performance_analytics import get_performance_analytics

import numpy as np
from scipy.stats import norm as scipy_norm
from analytics.tranche_constituent_risk import (
    S44_MARKET,
    generate_main_curves,
    calibrate_s44_base_correlation,
    compute_per_name_jtd,
    compute_per_name_cs01,
    compute_bc01,
    _build_vectors,
    _tranche_mtm,
    _parallel_shift_curves,
    _fast_total_cs01,
)
from analytics.tranche_pricer import (
    MAIN_TRANCHES,
    CROSSOVER_TRANCHES,
    ISDA_RECOVERY,
    MATURITY_YEARS,
    N_QUADRATURE,
    _parametric_base_correlation,
    _gauss_hermite_nodes_weights,
    hazard_rate_from_spread,
    risky_duration_approx,
    default_probability,
    generate_synthetic_cds_curves,
)

# Page config
st.set_page_config(
    page_title="Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================
# SECURITY CONFIGURATION
# ============================================
# Change this passcode to your own secure code
# For production, use environment variables or secrets management
DEFAULT_PASSCODE = "catalyst2024"  # Change this!

def get_master_reset_code():
    """Get master reset code from Streamlit secrets"""
    try:
        return st.secrets.get("MASTER_RESET_CODE", None)
    except:
        return None

def verify_master_reset(code: str) -> bool:
    """Verify master reset code"""
    master_code = get_master_reset_code()
    if master_code and code == master_code:
        return True
    return False

def get_passcode_hash():
    """Get stored passcode hash or create default"""
    config_file = Path("dashboard/security.json")
    if config_file.exists():
        with open(config_file, 'r') as f:
            data = json.load(f)
            return data.get('passcode_hash')
    # Create default
    default_hash = hashlib.sha256(DEFAULT_PASSCODE.encode()).hexdigest()
    config_file.parent.mkdir(exist_ok=True)
    with open(config_file, 'w') as f:
        json.dump({'passcode_hash': default_hash}, f)
    return default_hash

def verify_passcode(entered_code: str) -> bool:
    """Verify entered passcode"""
    entered_hash = hashlib.sha256(entered_code.encode()).hexdigest()
    return entered_hash == get_passcode_hash()

def change_passcode(new_code: str):
    """Change the passcode"""
    config_file = Path("dashboard/security.json")
    new_hash = hashlib.sha256(new_code.encode()).hexdigest()
    config_file.parent.mkdir(exist_ok=True)
    with open(config_file, 'w') as f:
        json.dump({'passcode_hash': new_hash}, f)

def reset_to_default():
    """Reset passcode to default"""
    change_passcode(DEFAULT_PASSCODE)

# ============================================
# LOGIN PAGE
# ============================================
def render_login_page():
    """Render the login page"""
    st.markdown("""
    <style>
        .login-container {
            max-width: 400px;
            margin: 100px auto;
            padding: 40px;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .login-title {
            text-align: center;
            font-size: 2.5rem;
            margin-bottom: 10px;
        }
        .login-subtitle {
            text-align: center;
            color: #888;
            margin-bottom: 30px;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("# 📈 Agent Trading")
        st.markdown("#### Secure Access Required")
        st.markdown("---")

        # Check if showing forgot password form
        if st.session_state.get('show_forgot_password', False):
            st.markdown("### 🔑 Password Recovery")
            st.info("Answer your security question to reset your password.")

            master_code = st.text_input(
                "What is your mother's maiden name?",
                type="password",
                placeholder="Enter answer",
                key="master_reset_input"
            )

            new_password = st.text_input(
                "New Password",
                type="password",
                placeholder="Enter new password",
                key="new_password_reset"
            )

            confirm_password = st.text_input(
                "Confirm New Password",
                type="password",
                placeholder="Confirm new password",
                key="confirm_password_reset"
            )

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔓 Reset Password", type="primary", use_container_width=True):
                    if verify_master_reset(master_code):
                        if new_password and new_password == confirm_password:
                            if len(new_password) >= 4:
                                change_passcode(new_password)
                                st.success("✅ Password reset! You can now login.")
                                st.session_state.show_forgot_password = False
                                st.rerun()
                            else:
                                st.error("Password must be at least 4 characters")
                        else:
                            st.error("Passwords don't match")
                    else:
                        st.error("❌ Invalid master reset code")

            with col_b:
                if st.button("◀ Back to Login", use_container_width=True):
                    st.session_state.show_forgot_password = False
                    st.rerun()

        else:
            # Normal login form
            passcode = st.text_input(
                "Enter Passcode",
                type="password",
                placeholder="Enter your access code",
                key="login_passcode"
            )

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔓 Login", type="primary", use_container_width=True):
                    if verify_passcode(passcode):
                        st.session_state.authenticated = True
                        st.session_state.login_time = datetime.now().isoformat()
                        st.rerun()
                    else:
                        st.error("❌ Invalid passcode")

            with col_b:
                if st.button("🔄 Reset", use_container_width=True):
                    st.rerun()

            # Forgot password link
            if get_master_reset_code():
                st.markdown("---")
                if st.button("🔑 Forgot Password?", use_container_width=True):
                    st.session_state.show_forgot_password = True
                    st.rerun()

# ============================================
# KILL SWITCH PAGE
# ============================================
def render_killed_page():
    """Render page when system is killed"""
    st.markdown("""
    <style>
        .killed-container {
            text-align: center;
            margin-top: 100px;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("# 🛑 SYSTEM OFFLINE")
        st.markdown("### All trading systems have been disabled")
        st.markdown("---")

        st.warning("""
        **Kill Switch Activated**

        All systems are currently disabled:
        - ❌ Market Brain Scanner
        - ❌ Stop Loss Monitor
        - ❌ Telegram Notifications
        - ❌ Trade Entry
        - ❌ Position Management
        """)

        st.markdown("---")

        reactivate_code = st.text_input(
            "Enter Passcode to Reactivate",
            type="password",
            key="reactivate_code"
        )

        if st.button("🔓 Reactivate Systems", type="primary"):
            if verify_passcode(reactivate_code):
                st.session_state.system_state['killed'] = False
                save_system_state(st.session_state.system_state)
                st.success("✅ Systems reactivated!")
                st.rerun()
            else:
                st.error("❌ Invalid passcode")

# Custom CSS for professional look
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-top: 0;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
    }
    .profit {
        color: #00c853;
        font-weight: bold;
    }
    .loss {
        color: #ff1744;
        font-weight: bold;
    }
    .warning-box {
        background-color: #fff3cd;
        border: 1px solid #ffc107;
        border-radius: 5px;
        padding: 10px;
        margin: 10px 0;
    }
    .danger-box {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 5px;
        padding: 10px;
        margin: 10px 0;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 5px;
        padding: 10px;
        margin: 10px 0;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }
    .kill-switch {
        background-color: #dc3545;
        color: white;
        padding: 10px;
        border-radius: 5px;
        text-align: center;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)


def run_async(coro):
    """Run async function in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def load_system_state():
    """Load system state from file"""
    state_file = Path("dashboard/state.json")
    if state_file.exists():
        with open(state_file, 'r') as f:
            return json.load(f)
    return {
        "brain_active": False,
        "stop_monitor_active": False,
        "telegram_active": True,
        "total_capital": 100000.0,
        "risk_per_trade_pct": 1.0,
        "killed": False
    }


def save_system_state(state):
    """Save system state to file"""
    state_file = Path("dashboard/state.json")
    state_file.parent.mkdir(exist_ok=True)
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def main():
    # Check authentication
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        render_login_page()
        return

    # Initialize system state
    if 'system_state' not in st.session_state:
        st.session_state.system_state = load_system_state()

    # Check kill switch
    if st.session_state.system_state.get('killed', False):
        render_killed_page()
        return

    # Header
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown('<p class="main-header">📈 Trading Dashboard</p>', unsafe_allow_html=True)
    with col2:
        st.metric("Total Capital", f"${st.session_state.system_state['total_capital']:,.0f}")
    with col3:
        current_time = datetime.now().strftime("%H:%M:%S")
        st.metric("Last Update", current_time)
        if st.button("🔄 Refresh"):
            st.rerun()

    st.divider()

    # Sidebar - System Controls
    with st.sidebar:
        st.header("⚙️ System Controls")

        # User info
        st.caption(f"🔐 Logged in since: {st.session_state.get('login_time', 'Unknown')[:16]}")

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

        st.divider()

        # ============================================
        # KILL SWITCH
        # ============================================
        st.subheader("🛑 Emergency Controls")

        st.markdown("""
        <div style='background-color: #2d2d2d; padding: 10px; border-radius: 5px; border: 1px solid #dc3545;'>
        <p style='color: #dc3545; margin: 0; font-weight: bold;'>⚠️ KILL SWITCH</p>
        <p style='color: #888; margin: 5px 0 0 0; font-size: 0.8rem;'>Immediately stops all systems</p>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🛑 KILL ALL SYSTEMS", type="primary", use_container_width=True):
            st.session_state.show_kill_confirm = True

        if st.session_state.get('show_kill_confirm', False):
            st.warning("⚠️ Are you sure? This will disable ALL trading systems!")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Confirm", use_container_width=True):
                    st.session_state.system_state['killed'] = True
                    st.session_state.system_state['brain_active'] = False
                    st.session_state.system_state['stop_monitor_active'] = False
                    st.session_state.system_state['telegram_active'] = False
                    save_system_state(st.session_state.system_state)
                    st.session_state.show_kill_confirm = False
                    st.rerun()
            with col2:
                if st.button("❌ Cancel", use_container_width=True):
                    st.session_state.show_kill_confirm = False
                    st.rerun()

        st.divider()

        # Capital settings
        st.subheader("💰 Capital Settings")
        new_capital = st.number_input(
            "Total Capital ($)",
            value=st.session_state.system_state['total_capital'],
            step=1000.0,
            format="%.0f"
        )
        if new_capital != st.session_state.system_state['total_capital']:
            st.session_state.system_state['total_capital'] = new_capital
            save_system_state(st.session_state.system_state)
            # Update position tracker
            tracker = get_position_tracker()
            tracker.set_portfolio_value(new_capital)

        risk_pct = st.slider(
            "Risk Per Trade (%)",
            min_value=0.5,
            max_value=5.0,
            value=st.session_state.system_state['risk_per_trade_pct'],
            step=0.5
        )
        if risk_pct != st.session_state.system_state['risk_per_trade_pct']:
            st.session_state.system_state['risk_per_trade_pct'] = risk_pct
            save_system_state(st.session_state.system_state)

        max_risk_amount = new_capital * (risk_pct / 100)
        st.info(f"Max risk per trade: ${max_risk_amount:,.0f}")

        st.divider()

        # System toggles
        st.subheader("🎛️ System Toggles")

        brain_active = st.toggle(
            "Market Brain Scanner",
            value=st.session_state.system_state.get('brain_active', False),
            help="Enable market inefficiency detection"
        )
        st.session_state.system_state['brain_active'] = brain_active

        stop_monitor = st.toggle(
            "Stop Loss Monitor",
            value=st.session_state.system_state.get('stop_monitor_active', False),
            help="Monitor positions for stop loss proximity"
        )
        st.session_state.system_state['stop_monitor_active'] = stop_monitor

        telegram_active = st.toggle(
            "Telegram Notifications",
            value=st.session_state.system_state.get('telegram_active', True),
            help="Send alerts to Telegram"
        )
        st.session_state.system_state['telegram_active'] = telegram_active

        save_system_state(st.session_state.system_state)

        st.divider()

        # Quick stats
        st.subheader("📊 Quick Stats")
        analytics = get_performance_analytics()
        metrics = analytics.get_metrics(days=30)

        if metrics.total_trades > 0:
            st.metric("Win Rate (30d)", f"{metrics.win_rate:.0f}%")
            pnl_color = "profit" if metrics.total_pnl >= 0 else "loss"
            st.metric("P&L (30d)", f"${metrics.total_pnl:+,.0f}")
            st.metric("Expectancy", f"${metrics.expectancy:+.2f}/trade")
        else:
            st.info("No trades in last 30 days")

        st.divider()

        # Change passcode section
        with st.expander("🔐 Security Settings"):
            st.caption("Change Access Passcode")
            current_pass = st.text_input("Current Passcode", type="password", key="current_pass")
            new_pass = st.text_input("New Passcode", type="password", key="new_pass")
            confirm_pass = st.text_input("Confirm New Passcode", type="password", key="confirm_pass")

            if st.button("Change Passcode"):
                if not verify_passcode(current_pass):
                    st.error("Current passcode is incorrect")
                elif new_pass != confirm_pass:
                    st.error("New passcodes don't match")
                elif len(new_pass) < 4:
                    st.error("Passcode must be at least 4 characters")
                else:
                    change_passcode(new_pass)
                    st.success("✅ Passcode changed successfully!")

    # Main content tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Portfolio", "📝 New Trade", "📜 Trade History",
        "📈 Analytics", "🧠 Market Brain", "🔬 Tranche Risk"
    ])

    # TAB 1: Portfolio Overview
    with tab1:
        render_portfolio_tab()

    # TAB 2: New Trade Entry
    with tab2:
        render_new_trade_tab()

    # TAB 3: Trade History
    with tab3:
        render_trade_history_tab()

    # TAB 4: Analytics
    with tab4:
        render_analytics_tab()

    # TAB 5: Market Brain
    with tab5:
        render_brain_tab()

    # TAB 6: Tranche Risk
    with tab6:
        render_tranche_risk_tab()


def render_portfolio_tab():
    """Render portfolio overview tab"""
    tracker = get_position_tracker()

    # Refresh prices
    run_async(tracker.refresh_prices())

    col1, col2, col3, col4 = st.columns(4)

    # Calculate totals
    positions = list(tracker.positions.values())
    total_value = sum(p.market_value for p in positions)
    total_cost = sum(p.cost_basis for p in positions)
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    with col1:
        st.metric(
            "Positions",
            len(positions),
            help="Number of open positions"
        )

    with col2:
        st.metric(
            "Market Value",
            f"${total_value:,.2f}",
            help="Total current market value"
        )

    with col3:
        delta_color = "normal" if total_pnl >= 0 else "inverse"
        st.metric(
            "Unrealized P&L",
            f"${total_pnl:+,.2f}",
            delta=f"{total_pnl_pct:+.1f}%",
            delta_color=delta_color
        )

    with col4:
        heat = tracker.get_portfolio_heat()
        heat_status = "🟢" if heat < 5 else "🟡" if heat < 10 else "🔴"
        st.metric(
            "Portfolio Heat",
            f"{heat:.1f}%",
            help="Percentage of portfolio at risk"
        )

    st.divider()

    # Warnings section
    stop_monitor = get_stop_monitor()
    run_async(stop_monitor.check_all_positions())

    correlation_warns = tracker.get_correlation_warnings()
    stop_warns = stop_monitor.get_stop_summary()

    if stop_warns['critical_alerts'] > 0 or stop_warns['breached_alerts'] > 0:
        st.error(f"🚨 **STOP ALERT**: {stop_warns['critical_alerts']} critical, {stop_warns['breached_alerts']} breached!")

    if correlation_warns:
        st.warning("⚠️ **Correlation Warning**: " + "; ".join(correlation_warns))

    # Positions table
    st.subheader("📋 Open Positions")

    if positions:
        pos_data = []
        for p in sorted(positions, key=lambda x: -abs(x.unrealized_pnl)):
            pos_data.append({
                "Symbol": p.symbol,
                "Type": p.position_type.value,
                "Qty": p.quantity,
                "Entry": f"${p.entry_price:.2f}",
                "Current": f"${p.current_price:.2f}",
                "P&L": f"${p.unrealized_pnl:+,.2f}",
                "P&L %": f"{p.unrealized_pnl_pct:+.1f}%",
                "Stop": f"${p.stop_loss:.2f}" if p.stop_loss else "None",
                "Target": f"${p.target:.2f}" if p.target else "None"
            })

        df = pd.DataFrame(pos_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Position management
        st.subheader("🔧 Position Management")
        col1, col2 = st.columns(2)

        with col1:
            selected_symbol = st.selectbox(
                "Select Position to Close",
                options=[p.symbol for p in positions]
            )

        with col2:
            exit_price = st.number_input("Exit Price", min_value=0.01, step=0.01)

        if st.button("Close Position", type="primary"):
            if selected_symbol and exit_price > 0:
                result = tracker.close_position(selected_symbol, exit_price)
                if result:
                    # Log to journal
                    journal = get_trade_journal()
                    # Find the open trade and close it
                    st.success(f"Closed {selected_symbol} at ${exit_price:.2f} - P&L: ${result['pnl']:+.2f}")
                    st.rerun()
    else:
        st.info("No open positions. Add a new trade to get started!")


def render_new_trade_tab():
    """Render new trade entry form"""
    st.subheader("📝 Log New Trade")

    col1, col2 = st.columns(2)

    with col1:
        symbol = st.text_input("Symbol", placeholder="AAPL").upper()
        side = st.selectbox("Side", ["Long", "Short"])
        market_type = st.selectbox("Market Type", ["Stock", "Options", "ETF"])

        entry_price = st.number_input("Entry Price ($)", min_value=0.01, step=0.01)
        quantity = st.number_input("Quantity", min_value=1, step=1)

    with col2:
        stop_loss = st.number_input("Stop Loss ($)", min_value=0.0, step=0.01)
        target = st.number_input("Target Price ($)", min_value=0.0, step=0.01)

        strategy = st.selectbox("Strategy", [
            "Momentum Breakout",
            "Mean Reversion",
            "Panic Buy (Buffett)",
            "Euphoria Sell",
            "Earnings Play",
            "Technical Setup",
            "News Catalyst",
            "Other"
        ])

        emotional_state = st.selectbox("Emotional State", [
            "Calm",
            "Confident",
            "Neutral",
            "Anxious",
            "FOMO",
            "Revenge",
            "Greedy"
        ])

    # Options specific fields
    if market_type == "Options":
        st.subheader("Options Details")
        opt_col1, opt_col2, opt_col3 = st.columns(3)
        with opt_col1:
            option_type = st.selectbox("Option Type", ["CALL", "PUT"])
        with opt_col2:
            strike = st.number_input("Strike Price ($)", min_value=0.01, step=1.0)
        with opt_col3:
            expiry = st.date_input("Expiration Date")
    else:
        option_type = None
        strike = None
        expiry = None

    rationale = st.text_area(
        "Trade Rationale",
        placeholder="Why are you taking this trade? What's your edge?"
    )

    # Risk calculation
    if entry_price > 0 and stop_loss > 0 and quantity > 0:
        risk_per_share = abs(entry_price - stop_loss)
        total_risk = risk_per_share * quantity
        if market_type == "Options":
            total_risk *= 100

        capital = st.session_state.system_state['total_capital']
        risk_pct = (total_risk / capital) * 100

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Risk Amount", f"${total_risk:,.2f}")
        with col2:
            st.metric("Risk % of Capital", f"{risk_pct:.2f}%")
        with col3:
            if target > 0:
                reward = abs(target - entry_price) * quantity
                if market_type == "Options":
                    reward *= 100
                rr = reward / total_risk if total_risk > 0 else 0
                st.metric("Risk:Reward", f"1:{rr:.1f}")

        if risk_pct > 2:
            st.warning(f"⚠️ Risk is {risk_pct:.1f}% of capital - consider reducing position size")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📝 Log Trade Entry", type="primary", use_container_width=True):
            if symbol and entry_price > 0 and quantity > 0:
                # Add to position tracker
                tracker = get_position_tracker()

                pos_type = PositionType.STOCK
                if market_type == "Options":
                    pos_type = PositionType.OPTIONS_CALL if option_type == "CALL" else PositionType.OPTIONS_PUT
                elif market_type == "ETF":
                    pos_type = PositionType.ETF

                tracker.add_position(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=entry_price,
                    position_type=pos_type,
                    stop_loss=stop_loss if stop_loss > 0 else None,
                    target=target if target > 0 else None,
                    strategy=strategy,
                    rationale=rationale,
                    strike=strike,
                    expiry=str(expiry) if expiry else None,
                    option_type=option_type
                )

                # Log to journal
                journal = get_trade_journal()
                journal.log_entry(
                    symbol=symbol,
                    side=side.lower(),
                    entry_price=entry_price,
                    quantity=quantity,
                    strategy=strategy,
                    entry_rationale=rationale,
                    market_type=market_type.lower(),
                    initial_stop=stop_loss if stop_loss > 0 else None,
                    initial_target=target if target > 0 else None,
                    emotional_state=emotional_state.lower(),
                    strike=strike,
                    expiry=str(expiry) if expiry else None,
                    option_type=option_type
                )

                st.success(f"✅ Logged {side} position: {symbol} x{quantity} @ ${entry_price}")
                st.balloons()
            else:
                st.error("Please fill in all required fields")

    with col2:
        if st.button("🧹 Clear Form", use_container_width=True):
            st.rerun()


def render_trade_history_tab():
    """Render trade history tab"""
    journal = get_trade_journal()

    col1, col2 = st.columns([1, 3])
    with col1:
        days_filter = st.selectbox("Period", [7, 14, 30, 90, 365], index=2)

    # Get trades
    closed_trades = journal.get_closed_trades(days=days_filter)
    open_trades = journal.get_open_trades()

    st.subheader(f"📜 Trade History (Last {days_filter} days)")

    # Summary metrics
    if closed_trades:
        wins = [t for t in closed_trades if t.outcome == 'win']
        losses = [t for t in closed_trades if t.outcome == 'loss']
        total_pnl = sum(t.pnl or 0 for t in closed_trades)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Trades", len(closed_trades))
        with col2:
            win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
            st.metric("Win Rate", f"{win_rate:.0f}%")
        with col3:
            st.metric("Total P&L", f"${total_pnl:+,.2f}")
        with col4:
            avg_r = sum(t.r_multiple or 0 for t in closed_trades) / len(closed_trades) if closed_trades else 0
            st.metric("Avg R", f"{avg_r:+.2f}R")

    # Open trades
    if open_trades:
        st.subheader("🔓 Open Trades")
        open_data = []
        for t in open_trades:
            open_data.append({
                "ID": t.id,
                "Symbol": t.symbol,
                "Side": t.side.upper(),
                "Entry": f"${t.entry_price:.2f}",
                "Qty": t.quantity,
                "Strategy": t.strategy,
                "Date": t.entry_date[:10]
            })
        st.dataframe(pd.DataFrame(open_data), use_container_width=True, hide_index=True)

    # Closed trades
    if closed_trades:
        st.subheader("✅ Closed Trades")
        trade_data = []
        for t in closed_trades[:50]:  # Limit to 50
            trade_data.append({
                "ID": t.id,
                "Symbol": t.symbol,
                "Side": t.side.upper(),
                "Entry": f"${t.entry_price:.2f}",
                "Exit": f"${t.exit_price:.2f}" if t.exit_price else "-",
                "P&L": f"${t.pnl:+,.2f}" if t.pnl else "-",
                "R": f"{t.r_multiple:+.2f}R" if t.r_multiple else "-",
                "Result": t.outcome.upper(),
                "Strategy": t.strategy,
                "Exit Reason": t.exit_reason or "-"
            })

        df = pd.DataFrame(trade_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No closed trades in this period")


def render_analytics_tab():
    """Render analytics tab"""
    analytics = get_performance_analytics()

    col1, col2 = st.columns([1, 3])
    with col1:
        period = st.selectbox("Analysis Period", [7, 14, 30, 90, 365, None], index=2,
                             format_func=lambda x: "All Time" if x is None else f"Last {x} days")

    metrics = analytics.get_metrics(days=period)

    if metrics.total_trades == 0:
        st.info("No trades to analyze for this period")
        return

    # Key metrics
    st.subheader("📊 Performance Metrics")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Trades", metrics.total_trades)
        st.metric("Win Rate", f"{metrics.win_rate:.1f}%")

    with col2:
        st.metric("Total P&L", f"${metrics.total_pnl:+,.2f}")
        st.metric("Expectancy", f"${metrics.expectancy:+.2f}/trade")

    with col3:
        pf = f"{metrics.profit_factor:.2f}" if metrics.profit_factor != float('inf') else "∞"
        st.metric("Profit Factor", pf)
        st.metric("Avg R", f"{metrics.avg_r_multiple:+.2f}R")

    with col4:
        st.metric("Avg Win", f"${metrics.avg_win:,.2f}")
        st.metric("Avg Loss", f"${metrics.avg_loss:,.2f}")

    st.divider()

    # Win/Loss breakdown
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🎯 Win/Loss Breakdown")
        win_loss_data = pd.DataFrame({
            'Outcome': ['Wins', 'Losses', 'Breakeven'],
            'Count': [metrics.wins, metrics.losses, metrics.breakeven]
        })
        st.bar_chart(win_loss_data.set_index('Outcome'))

    with col2:
        st.subheader("📈 Edge Assessment")
        edge = analytics.get_edge_assessment()

        if edge['has_edge']:
            st.success(f"✅ **Edge Confirmed** (Confidence: {edge['confidence']})")
        else:
            st.warning(f"⚠️ **No Confirmed Edge** (Confidence: {edge['confidence']})")

        if edge['strengths']:
            st.write("**Strengths:**")
            for s in edge['strengths']:
                st.write(f"  ✓ {s}")

        if edge['issues']:
            st.write("**Issues:**")
            for i in edge['issues']:
                st.write(f"  ⚠ {i}")

    # Strategy breakdown
    st.subheader("📋 Strategy Performance")
    strat_analysis = analytics.journal.get_strategy_analysis()

    if strat_analysis:
        strat_data = []
        for strat, stats in strat_analysis.items():
            strat_data.append({
                "Strategy": strat,
                "Trades": stats['trades'],
                "Win Rate": f"{stats['win_rate']:.0f}%",
                "Total P&L": f"${stats['total_pnl']:+,.2f}",
                "Avg R": f"{stats['avg_r']:+.2f}R"
            })
        st.dataframe(pd.DataFrame(strat_data), use_container_width=True, hide_index=True)

    # Streaks and drawdown
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🔥 Streak Info")
        streak = analytics.get_streak_info()
        streak_emoji = "🔥" if streak['streak_type'] == 'win' else "❄️" if streak['streak_type'] == 'loss' else ""
        st.metric("Current Streak", f"{streak['current_streak']} {streak['streak_type']} {streak_emoji}")
        st.metric("Max Win Streak", streak['max_win_streak'])
        st.metric("Max Loss Streak", streak['max_loss_streak'])

    with col2:
        st.subheader("📉 Drawdown Analysis")
        dd = analytics.get_drawdown_analysis()
        st.metric("Max Drawdown", f"${dd['max_drawdown']:,.2f}")
        st.metric("Current Drawdown", f"${dd['current_drawdown']:,.2f}")


def render_brain_tab():
    """Render Market Brain tab"""
    st.subheader("🧠 Market Brain Status")

    if st.session_state.system_state.get('brain_active'):
        st.success("Market Brain Scanner is **ACTIVE**")

        st.info("""
        **Active Scanners:**
        - 👥 Retail Crowding Scanner
        - 📊 Volatility Mispricing Scanner
        - ⏰ Time Zone Gap Scanner
        - 💧 Liquidity Pattern Scanner
        - 💥 Exogenous Shock Scanner
        - 🎰 Euphoria Detector
        - 🔍 Product Discovery Scanner
        - 📰 Geopolitical News Scanner
        """)

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📅 Upcoming Earnings")
            calendar = get_earnings_calendar()
            # Note: Would need async refresh
            upcoming = calendar.get_this_week_earnings()
            if upcoming:
                for e in upcoming[:5]:
                    days_str = "TODAY" if e.days_until == 0 else f"in {e.days_until}d"
                    st.write(f"• **{e.symbol}** - {days_str}")
            else:
                st.write("No earnings this week for watched symbols")

        with col2:
            st.subheader("⚠️ Current Alerts")
            st.write("• VIX: Monitor for panic/euphoria signals")
            st.write("• News: Scanning for geopolitical risks")
            st.write("• Products: Watching for behavioral edge opportunities")

    else:
        st.warning("Market Brain Scanner is **INACTIVE**")
        st.write("Enable it in the sidebar to start scanning for opportunities")

    st.divider()

    # Philosophy reminder
    st.subheader("📖 Trading Philosophy")
    st.markdown("""
    > *"Be fearful when others are greedy, and greedy when others are fearful."* - Warren Buffett

    **Core Principles:**
    1. **Capital Preservation** - Rule #1 is don't lose money. Rule #2 is don't forget Rule #1.
    2. **Behavioral Edge** - Fish where retail emotion creates patterns
    3. **Disciplined Execution** - A stop is a rule, not a suggestion
    4. **Know Your Edge** - If you don't know why you're in a trade, get out
    """)


def _compute_tranche_analysis(index_name, tranche_label, notional_mm, spread_override):
    """Compute all tranche risk metrics. Returns dict of results or None."""
    notional = notional_mm * 1_000_000

    # Tranche definition
    tranches = MAIN_TRANCHES if index_name == "Main" else CROSSOVER_TRANCHES
    tranche_def = next((t for t in tranches if t["label"] == tranche_label), None)
    if not tranche_def:
        return None

    attach = tranche_def["attach"]
    detach = tranche_def["detach"]
    width = detach - attach
    is_equity = attach == 0.0

    # Reference spread
    if spread_override and spread_override > 0:
        ref_spread = spread_override
    elif index_name == "Main":
        ref_spread = S44_MARKET["ref_spread_bps"]
    else:
        ref_spread = 300.0

    # Running coupon
    if index_name == "Main":
        running_coupon = S44_MARKET["running_coupon_bps"]
    else:
        running_coupon = 500.0 if is_equity else 0.0

    # Calibrate base correlation
    if index_name == "Main" and tranche_label in S44_MARKET["tranches"]:
        corr = calibrate_s44_base_correlation(
            tranche_label, ref_spread, running_coupon, verbose=False
        )
        if corr is None:
            corr = _parametric_base_correlation(detach, index_name)
    else:
        corr = _parametric_base_correlation(detach, index_name)

    # Generate CDS curves
    if index_name == "Main":
        n_names = 125
        curves = generate_main_curves(n_names, ref_spread, 25)
    else:
        n_names = 75
        curves = generate_synthetic_cds_curves("Crossover", n_names, ref_spread, 150, 0.35)

    avg_spread = float(np.mean([c.spread_5y_bps for c in curves]))
    recoveries = [c.recovery_rate for c in curves]

    # ── Core risk metrics ──
    jtd_results = compute_per_name_jtd(curves, attach, detach, notional)
    cs01_results, total_cs01 = compute_per_name_cs01(
        curves, attach, detach, corr, notional, running_coupon
    )
    bc01 = compute_bc01(curves, attach, detach, corr, notional, running_coupon)

    # Delta validation
    avg_hr = hazard_rate_from_spread(avg_spread, ISDA_RECOVERY)
    index_rpv01 = risky_duration_approx(avg_hr)
    index_cs01 = index_rpv01 * (1.0 / 10_000) * notional
    model_delta = total_cs01 / index_cs01 if index_cs01 > 0 else 0.0
    mkt_delta = None
    if index_name == "Main" and tranche_label in S44_MARKET["tranches"]:
        mkt_delta = S44_MARKET["tranches"][tranche_label]["delta"]

    # Sector CS01 aggregation
    sector_cs01 = {}
    for r in cs01_results:
        sector_cs01[r["sector"]] = sector_cs01.get(r["sector"], 0.0) + r["cs01_eur"]

    # ── Scenario analysis (parallel shifts) ──
    scenario_shifts = [-10, -5, +5, +10, +25, +50]
    pd_base, lgd_base, w_base = _build_vectors(curves)
    mtm_base = _tranche_mtm(
        attach, detach, pd_base, lgd_base, w_base, corr, notional, running_coupon
    )
    cs01_parallel = _fast_total_cs01(curves, attach, detach, corr, notional, running_coupon)

    scenarios = []
    for shift in scenario_shifts:
        curves_scen = _parallel_shift_curves(curves, shift)
        pd_s, lgd_s, w_s = _build_vectors(curves_scen)
        mtm_s = _tranche_mtm(
            attach, detach, pd_s, lgd_s, w_s, corr, notional, running_coupon
        )
        pnl_full = mtm_s - mtm_base
        pnl_linear = cs01_parallel * shift
        scenarios.append({
            "shift": shift,
            "index_spread": ref_spread + shift,
            "mtm": mtm_s,
            "pnl_full": pnl_full,
            "pnl_linear": pnl_linear,
            "convexity": pnl_full - pnl_linear,
        })

    # ── Single-name blowout ──
    nodes, weights = _gauss_hermite_nodes_weights(N_QUADRATURE)
    sqrt_rho = np.sqrt(max(0.001, corr))
    sqrt_1mr = np.sqrt(max(0.001, 1.0 - corr))
    thresholds = np.array([
        scipy_norm.ppf(max(1e-10, min(1 - 1e-10, c.default_prob_5y)))
        for c in curves
    ])

    def _fast_el(thresh_vec):
        total = 0.0
        for k in range(len(nodes)):
            M = nodes[k]
            cond_pds = scipy_norm.cdf((thresh_vec - sqrt_rho * M) / sqrt_1mr)
            cond_loss = np.sum(w_base * lgd_base * cond_pds)
            tl = (min(cond_loss, detach) - min(cond_loss, attach)) / width
            total += weights[k] * tl
        return max(0.0, total)

    el_base = _fast_el(thresholds)

    blowouts = {}
    for bump in [100, 250, 500]:
        all_pnl = []
        for i, c in enumerate(curves):
            new_spd = max(1.0, c.spread_5y_bps + bump)
            new_hr = hazard_rate_from_spread(new_spd, c.recovery_rate)
            new_pd = default_probability(new_hr, MATURITY_YEARS)
            new_th = scipy_norm.ppf(max(1e-10, min(1 - 1e-10, new_pd)))

            th_bumped = thresholds.copy()
            th_bumped[i] = new_th
            pnl = (_fast_el(th_bumped) - el_base) * notional

            # JTD for comparison
            w_i = 1.0 / n_names
            lgd_i = 1.0 - c.recovery_rate
            port_loss = w_i * lgd_i
            tranche_hit = (min(port_loss, detach) - min(port_loss, attach)) / width
            jtd = tranche_hit * notional

            all_pnl.append({
                "Name": c.name, "Sector": c.sector, "Rating": c.rating,
                "Base Spread": c.spread_5y_bps, "Shocked": new_spd,
                "P&L": pnl, "JTD": jtd,
                "vs JTD %": pnl / jtd * 100 if jtd > 0 else 0,
            })

        all_pnl.sort(key=lambda x: x["P&L"], reverse=True)
        blowouts[bump] = all_pnl

    return {
        "index_name": index_name,
        "tranche_label": tranche_label,
        "notional": notional,
        "notional_mm": notional_mm,
        "n_names": n_names,
        "attach": attach,
        "detach": detach,
        "correlation": corr,
        "running_coupon": running_coupon,
        "ref_spread": ref_spread,
        "avg_spread": avg_spread,
        "recovery_range": (min(recoveries), max(recoveries), float(np.mean(recoveries))),
        "jtd_results": jtd_results,
        "cs01_results": cs01_results,
        "total_cs01": total_cs01,
        "bc01": bc01,
        "model_delta": model_delta,
        "mkt_delta": mkt_delta,
        "index_cs01": index_cs01,
        "mtm_base": mtm_base,
        "sector_cs01": sector_cs01,
        "scenarios": scenarios,
        "blowouts": blowouts,
    }


def render_tranche_risk_tab():
    """Render tranche constituent risk analysis tab."""
    st.subheader("Tranche Constituent Risk")

    # ── Configuration ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        index_name = st.selectbox("Index", ["Main", "Crossover"], key="tr_index")
    with col2:
        tranche_labels = [
            t["label"] for t in
            (MAIN_TRANCHES if index_name == "Main" else CROSSOVER_TRANCHES)
        ]
        tranche_label = st.selectbox("Tranche", tranche_labels, key="tr_tranche")
    with col3:
        notional_mm = st.number_input(
            "Notional (EUR mm)", min_value=1.0, value=10.0, step=1.0, key="tr_notional"
        )
    with col4:
        spread_override = st.number_input(
            "Spread Override (bps)", min_value=0.0, value=0.0, step=1.0,
            key="tr_spread", help="0 = use S44 market default"
        )

    if st.button("Run Analysis", type="primary", key="tr_run"):
        with st.spinner("Computing tranche risk (JTD, CS01, BC01, scenarios, blowouts)..."):
            results = _compute_tranche_analysis(
                index_name, tranche_label, notional_mm, spread_override
            )
            if results:
                st.session_state.tranche_results = results
            else:
                st.error(f"Tranche {tranche_label} not found for {index_name}")
                return

    if "tranche_results" not in st.session_state:
        st.info("Configure parameters above and click **Run Analysis**.")
        return

    res = st.session_state.tranche_results

    # Stale results warning
    if (res["index_name"] != index_name or res["tranche_label"] != tranche_label
            or res["notional_mm"] != notional_mm):
        st.warning("Configuration changed since last run. Click **Run Analysis** to update.")

    # ── Header ──
    rec_lo, rec_hi, rec_avg = res["recovery_range"]
    st.caption(
        f"iTraxx {res['index_name']} S44 {res['tranche_label']} "
        f"({res['attach']*100:.0f}%-{res['detach']*100:.0f}%) | "
        f"EUR {res['notional']:,.0f} | {res['n_names']} names | "
        f"Avg spread {res['avg_spread']:.0f}bps | "
        f"Corr {res['correlation']:.1%} | "
        f"Recovery {rec_lo:.0%}-{rec_hi:.0%} (avg {rec_avg:.0%}) | "
        f"Coupon {res['running_coupon']:.0f}bps"
    )

    # ── Key Metrics ──
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Base Correlation", f"{res['correlation']:.1%}")
    with col2:
        st.metric("Total CS01", f"EUR {res['total_cs01']:,.0f}")
    with col3:
        delta_str = f"{res['model_delta']:.2f}x"
        if res["mkt_delta"]:
            st.metric("Model Delta", delta_str,
                      delta=f"Mkt {res['mkt_delta']:.2f}x")
        else:
            st.metric("Model Delta", delta_str)
    with col4:
        st.metric("BC01", f"EUR {res['bc01']['bc01_eur']:,.0f}")
    with col5:
        worst_jtd = res["jtd_results"][0]
        st.metric("Worst JTD", f"EUR {worst_jtd['jtd_eur']:,.0f}",
                  delta=f"{worst_jtd['jtd_pct_of_tranche']:.1f}% of tranche")

    st.divider()

    # ── JTD ──
    st.subheader("Jump-to-Default (JTD)")
    st.caption("Loss to tranche if a single name defaults immediately")

    jtd_top = pd.DataFrame(res["jtd_results"][:20])
    jtd_top.index = range(1, len(jtd_top) + 1)
    jtd_show = jtd_top[["name", "sector", "rating", "spread_bps", "recovery",
                         "jtd_pct_of_tranche", "jtd_eur"]].copy()
    jtd_show.columns = ["Name", "Sector", "Rating", "Spread", "Recovery",
                         "JTD (% tranche)", "JTD (EUR)"]
    jtd_show["Spread"] = jtd_show["Spread"].apply(lambda x: f"{x:.0f}bp")
    jtd_show["Recovery"] = jtd_show["Recovery"].apply(lambda x: f"{x:.0%}")
    jtd_show["JTD (% tranche)"] = jtd_show["JTD (% tranche)"].apply(lambda x: f"{x:.2f}%")
    jtd_show["JTD (EUR)"] = jtd_show["JTD (EUR)"].apply(lambda x: f"{x:,.0f}")
    st.dataframe(jtd_show, use_container_width=True)

    total_jtd = sum(r["jtd_eur"] for r in res["jtd_results"])
    st.caption(f"Avg JTD per name: EUR {total_jtd / res['n_names']:,.0f}")

    with st.expander(f"All {res['n_names']} constituents"):
        full_jtd = pd.DataFrame(res["jtd_results"])
        full_jtd.index = range(1, len(full_jtd) + 1)
        full_show = full_jtd[["name", "sector", "rating", "spread_bps", "recovery",
                               "jtd_pct_of_tranche", "jtd_eur"]].copy()
        full_show.columns = ["Name", "Sector", "Rating", "Spread", "Recovery",
                              "JTD (% tranche)", "JTD (EUR)"]
        full_show["Spread"] = full_show["Spread"].apply(lambda x: f"{x:.0f}bp")
        full_show["Recovery"] = full_show["Recovery"].apply(lambda x: f"{x:.0%}")
        full_show["JTD (% tranche)"] = full_show["JTD (% tranche)"].apply(lambda x: f"{x:.2f}%")
        full_show["JTD (EUR)"] = full_show["JTD (EUR)"].apply(lambda x: f"{x:,.0f}")
        st.dataframe(full_show, use_container_width=True)

    st.divider()

    # ── CS01 ──
    st.subheader("Per-Name CS01")
    st.caption("MTM change for +1bp widening in each name's CDS spread")

    col1, col2 = st.columns([3, 2])
    with col1:
        cs01_top = pd.DataFrame(res["cs01_results"][:20])
        cs01_top.index = range(1, len(cs01_top) + 1)
        cs01_show = cs01_top[["name", "sector", "rating", "spread_bps", "cs01_eur"]].copy()
        cs01_show.columns = ["Name", "Sector", "Rating", "Spread", "CS01 (EUR)"]
        cs01_show["Spread"] = cs01_show["Spread"].apply(lambda x: f"{x:.0f}bp")
        cs01_show["CS01 (EUR)"] = cs01_show["CS01 (EUR)"].apply(lambda x: f"{x:,.2f}")
        st.dataframe(cs01_show, use_container_width=True)

    with col2:
        st.markdown("**CS01 by Sector**")
        sector_data = pd.DataFrame([
            {"Sector": s, "CS01": abs(v)}
            for s, v in sorted(
                res["sector_cs01"].items(), key=lambda x: abs(x[1]), reverse=True
            )
        ])
        st.bar_chart(sector_data.set_index("Sector"))

    st.caption(
        f"Total CS01: EUR {res['total_cs01']:,.2f} | "
        f"CS01 per EUR 1mm: EUR {res['total_cs01'] / res['notional_mm']:,.2f}"
    )

    st.divider()

    # ── BC01 ──
    st.subheader("Base Correlation Sensitivity (BC01)")
    bc = res["bc01"]
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("BC01", f"EUR {bc['bc01_eur']:,.0f}")
        st.metric("BC01 (% notional)", f"{bc['bc01_pct_notional']:.4f}%")
    with col2:
        st.metric("MTM (base)", f"EUR {bc['mtm_base']:,.0f}")
        st.metric("MTM (corr +1%)", f"EUR {bc['mtm_corr_up']:,.0f}")
    with col3:
        st.metric("MTM (corr -1%)", f"EUR {bc['mtm_corr_dn']:,.0f}")
        st.metric("BC01 per EUR 1mm", f"EUR {bc['bc01_eur'] / res['notional_mm']:,.0f}")

    st.divider()

    # ── Scenario Analysis ──
    st.subheader("Scenario Analysis (Parallel Shift)")
    st.caption(
        f"Correlation held fixed at {res['correlation']:.1%}. "
        f"Protection buyer perspective."
    )

    scen_df = pd.DataFrame(res["scenarios"])
    scen_show = pd.DataFrame({
        "Scenario": scen_df["shift"].apply(lambda x: f"{'+'if x > 0 else ''}{x}bp"),
        "Index (bps)": scen_df["index_spread"].apply(lambda x: f"{x:.0f}"),
        "MTM (EUR)": scen_df["mtm"].apply(lambda x: f"{x:,.0f}"),
        "P&L Full": scen_df["pnl_full"].apply(lambda x: f"{x:+,.0f}"),
        "P&L Linear": scen_df["pnl_linear"].apply(lambda x: f"{x:+,.0f}"),
        "Convexity": scen_df["convexity"].apply(lambda x: f"{x:+,.0f}"),
    })
    st.dataframe(scen_show, use_container_width=True, hide_index=True)

    # P&L chart
    chart_data = pd.DataFrame({
        "Shift (bp)": [s["shift"] for s in res["scenarios"]],
        "Full Reprice": [s["pnl_full"] for s in res["scenarios"]],
        "Linear": [s["pnl_linear"] for s in res["scenarios"]],
    }).set_index("Shift (bp)")
    st.line_chart(chart_data)

    st.divider()

    # ── Single-Name Blowout ──
    st.subheader("Single-Name Blowout Stress Test")
    st.caption("One name widens, rest unchanged. Top 5 most impactful names per bump.")

    for bump, data in res["blowouts"].items():
        st.markdown(f"**+{bump}bp single-name shock**")
        top5 = data[:5]
        blow_df = pd.DataFrame(top5)
        blow_df.index = range(1, len(blow_df) + 1)
        blow_show = pd.DataFrame({
            "Name": blow_df["Name"],
            "Sector": blow_df["Sector"],
            "Rating": blow_df["Rating"],
            "Base": blow_df["Base Spread"].apply(lambda x: f"{x:.0f}bp"),
            "Shocked": blow_df["Shocked"].apply(lambda x: f"{x:.0f}bp"),
            "P&L (EUR)": blow_df["P&L"].apply(lambda x: f"{x:+,.0f}"),
            "JTD (EUR)": blow_df["JTD"].apply(lambda x: f"{x:,.0f}"),
            "vs JTD": blow_df["vs JTD %"].apply(lambda x: f"{x:.1f}%"),
        })
        st.dataframe(blow_show, use_container_width=True)

        avg_pnl = np.mean([r["P&L"] for r in data])
        worst = data[0]
        st.caption(
            f"Worst: EUR {worst['P&L']:+,.0f} ({worst['Name']}) | "
            f"Avg across {res['n_names']} names: EUR {avg_pnl:+,.0f}"
        )


if __name__ == "__main__":
    main()

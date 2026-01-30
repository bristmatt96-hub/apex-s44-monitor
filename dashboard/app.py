"""
APEX Trading Dashboard
Professional Portfolio Management Interface

Run: streamlit run dashboard/app.py
"""
import streamlit as st
import pandas as pd
import asyncio
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

# Page config
st.set_page_config(
    page_title="APEX Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
        "risk_per_trade_pct": 1.0
    }


def save_system_state(state):
    """Save system state to file"""
    state_file = Path("dashboard/state.json")
    state_file.parent.mkdir(exist_ok=True)
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def main():
    # Initialize state
    if 'system_state' not in st.session_state:
        st.session_state.system_state = load_system_state()

    # Header
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown('<p class="main-header">📈 APEX Trading Dashboard</p>', unsafe_allow_html=True)
        st.markdown('<p class="sub-header">Capital Preservation • Behavioral Edge • Disciplined Execution</p>', unsafe_allow_html=True)
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

    # Main content tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Portfolio", "📝 New Trade", "📜 Trade History", "📈 Analytics", "🧠 Market Brain"
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


if __name__ == "__main__":
    main()

"""
Equity Price Monitor for Apex Credit Monitor
Monitors equity prices for XO S44 credits - equity moves often lead credit by 1-2 days

Supports:
1. TradingView webhook alerts
2. Yahoo Finance API (free fallback)
3. Manual price entry
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import requests

# Try to import yfinance for price data
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


def load_ticker_config() -> Dict:
    """Load equity ticker configuration"""
    config_path = Path(__file__).parent.parent / "config" / "equity_tickers.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"ticker_map": {}}


def get_ticker_for_company(company_name: str) -> Optional[Dict]:
    """Get ticker info for a company"""
    config = load_ticker_config()
    ticker_map = config.get("ticker_map", {})
    return ticker_map.get(company_name)


def get_all_public_tickers() -> List[Dict]:
    """Get all publicly traded tickers"""
    config = load_ticker_config()
    ticker_map = config.get("ticker_map", {})

    public = []
    for company, info in ticker_map.items():
        if info.get("ticker") and info["ticker"] != "Private":
            public.append({
                "company": company,
                "ticker": info["ticker"],
                "exchange": info.get("exchange"),
                "currency": info.get("currency")
            })
    return public


def fetch_price_yfinance(ticker: str) -> Optional[Dict]:
    """Fetch current price and metrics from Yahoo Finance"""
    if not YFINANCE_AVAILABLE:
        return None

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")

        if hist.empty:
            return None

        current_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
        daily_change = ((current_price - prev_close) / prev_close) * 100

        # Get 52-week data for context
        hist_52w = stock.history(period="1y")
        high_52w = hist_52w['High'].max() if not hist_52w.empty else None
        low_52w = hist_52w['Low'].min() if not hist_52w.empty else None

        return {
            "ticker": ticker,
            "price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "daily_change_pct": round(daily_change, 2),
            "high_52w": round(high_52w, 2) if high_52w else None,
            "low_52w": round(low_52w, 2) if low_52w else None,
            "pct_from_52w_high": round(((current_price - high_52w) / high_52w) * 100, 1) if high_52w else None,
            "pct_from_52w_low": round(((current_price - low_52w) / low_52w) * 100, 1) if low_52w else None,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None


def calculate_equity_signal(price_data: Dict) -> Dict:
    """
    Calculate trading signal based on equity price action

    Large equity declines typically precede credit spread widening by 1-2 days
    """
    if not price_data:
        return {"signal": "NO_DATA", "score": 0, "reasons": []}

    signal_score = 0
    reasons = []

    daily_change = price_data.get("daily_change_pct", 0)
    pct_from_high = price_data.get("pct_from_52w_high", 0)
    pct_from_low = price_data.get("pct_from_52w_low", 0)

    # Daily move signals
    if daily_change <= -5:
        signal_score -= 30
        reasons.append(f"Large daily decline ({daily_change:.1f}%) - HIGH ALERT")
    elif daily_change <= -3:
        signal_score -= 15
        reasons.append(f"Notable daily decline ({daily_change:.1f}%)")
    elif daily_change >= 5:
        signal_score += 15
        reasons.append(f"Large daily gain ({daily_change:.1f}%)")
    elif daily_change >= 3:
        signal_score += 10
        reasons.append(f"Notable daily gain ({daily_change:.1f}%)")

    # 52-week context
    if pct_from_high and pct_from_high <= -50:
        signal_score -= 25
        reasons.append(f"Trading {abs(pct_from_high):.0f}% below 52w high - significant stress")
    elif pct_from_high and pct_from_high <= -30:
        signal_score -= 15
        reasons.append(f"Trading {abs(pct_from_high):.0f}% below 52w high")

    if pct_from_low and pct_from_low <= 5:
        signal_score -= 20
        reasons.append("Near 52-week low - credit stress signal")

    # Determine signal
    if signal_score <= -30:
        signal = "BEARISH"
    elif signal_score <= -10:
        signal = "CAUTIOUS"
    elif signal_score >= 20:
        signal = "BULLISH"
    elif signal_score >= 10:
        signal = "POSITIVE"
    else:
        signal = "NEUTRAL"

    return {
        "signal": signal,
        "score": signal_score,
        "reasons": reasons,
        "price_data": price_data
    }


def scan_all_equities() -> List[Dict]:
    """Scan all public equities and generate signals"""
    tickers = get_all_public_tickers()
    results = []

    for ticker_info in tickers:
        ticker = ticker_info["ticker"]
        company = ticker_info["company"]

        price_data = fetch_price_yfinance(ticker)
        signal_data = calculate_equity_signal(price_data)

        results.append({
            "company": company,
            "ticker": ticker,
            "exchange": ticker_info.get("exchange"),
            **signal_data
        })

    # Sort by signal score (most negative first - these are alerts)
    results.sort(key=lambda x: x.get("score", 0))

    return results


def get_movers(threshold_pct: float = 3.0) -> Dict[str, List[Dict]]:
    """Get significant movers (gainers and losers)"""
    all_signals = scan_all_equities()

    gainers = [s for s in all_signals if s.get("price_data", {}).get("daily_change_pct", 0) >= threshold_pct]
    losers = [s for s in all_signals if s.get("price_data", {}).get("daily_change_pct", 0) <= -threshold_pct]

    return {
        "gainers": sorted(gainers, key=lambda x: x.get("price_data", {}).get("daily_change_pct", 0), reverse=True),
        "losers": sorted(losers, key=lambda x: x.get("price_data", {}).get("daily_change_pct", 0)),
        "scan_time": datetime.now().isoformat()
    }


# ============== TRADINGVIEW WEBHOOK HANDLER ==============

class TradingViewWebhookHandler:
    """
    Handler for TradingView webhook alerts

    Configure in TradingView:
    1. Create alert on your chart
    2. Set webhook URL to your server endpoint
    3. Use JSON message format:
       {
         "ticker": "{{ticker}}",
         "price": {{close}},
         "change_pct": {{change}},
         "alert_type": "price_alert",
         "message": "{{strategy.order.alert_message}}"
       }
    """

    def __init__(self):
        self.alerts = []
        self.config = load_ticker_config()

    def process_webhook(self, payload: Dict) -> Dict:
        """Process incoming TradingView webhook"""
        ticker = payload.get("ticker", "")
        price = payload.get("price")
        change_pct = payload.get("change_pct")
        alert_type = payload.get("alert_type", "unknown")
        message = payload.get("message", "")

        # Find company for this ticker
        company = self._find_company_by_ticker(ticker)

        alert = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "company": company,
            "price": price,
            "change_pct": change_pct,
            "alert_type": alert_type,
            "message": message,
            "credit_implication": self._assess_credit_implication(change_pct, alert_type)
        }

        self.alerts.append(alert)

        # Keep only last 100 alerts
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]

        return alert

    def _find_company_by_ticker(self, ticker: str) -> Optional[str]:
        """Find company name by ticker"""
        ticker_map = self.config.get("ticker_map", {})
        for company, info in ticker_map.items():
            if info.get("ticker") == ticker:
                return company
        return None

    def _assess_credit_implication(self, change_pct: float, alert_type: str) -> str:
        """Assess what equity move means for credit"""
        if change_pct is None:
            return "Unable to assess"

        if change_pct <= -10:
            return "SEVERE: Expect significant spread widening (20-50bps+)"
        elif change_pct <= -5:
            return "HIGH: Expect spread widening (10-20bps)"
        elif change_pct <= -3:
            return "MODERATE: Monitor for spread pressure"
        elif change_pct >= 5:
            return "POSITIVE: Potential spread tightening"
        else:
            return "NEUTRAL: Limited credit impact expected"

    def get_recent_alerts(self, hours: int = 24) -> List[Dict]:
        """Get alerts from the last N hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            a for a in self.alerts
            if datetime.fromisoformat(a["timestamp"]) > cutoff
        ]


# ============== STREAMLIT INTEGRATION ==============

def render_equity_dashboard(st):
    """Render equity monitoring dashboard in Streamlit"""
    import pandas as pd

    st.markdown("### Equity Price Monitor")
    st.caption("Equity moves often lead credit by 1-2 days")

    if not YFINANCE_AVAILABLE:
        st.warning("Install yfinance for live prices: `pip install yfinance`")
        st.info("You can still use TradingView webhook alerts without yfinance")
        return

    # Scan button
    if st.button("Scan All Equities"):
        with st.spinner("Fetching prices..."):
            movers = get_movers(threshold_pct=2.0)

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Losers (Credit Risk)")
            if movers["losers"]:
                for m in movers["losers"][:10]:
                    price_data = m.get("price_data", {})
                    change = price_data.get("daily_change_pct", 0)
                    st.error(f"**{m['company']}** ({m['ticker']}): {change:.1f}%")
                    for reason in m.get("reasons", []):
                        st.caption(f"  • {reason}")
            else:
                st.info("No significant losers today")

        with col2:
            st.markdown("#### Gainers")
            if movers["gainers"]:
                for m in movers["gainers"][:10]:
                    price_data = m.get("price_data", {})
                    change = price_data.get("daily_change_pct", 0)
                    st.success(f"**{m['company']}** ({m['ticker']}): +{change:.1f}%")
            else:
                st.info("No significant gainers today")

    # Individual company lookup
    st.markdown("---")
    st.markdown("#### Company Lookup")

    tickers = get_all_public_tickers()
    company_names = [t["company"] for t in tickers]

    selected = st.selectbox("Select Company", company_names, key="equity_lookup")

    if st.button("Get Price", key="get_price"):
        ticker_info = get_ticker_for_company(selected)
        if ticker_info and ticker_info.get("ticker") != "Private":
            with st.spinner(f"Fetching {ticker_info['ticker']}..."):
                price_data = fetch_price_yfinance(ticker_info["ticker"])
                signal = calculate_equity_signal(price_data)

            if price_data:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Price", f"{price_data['price']}", f"{price_data['daily_change_pct']:.1f}%")
                with col2:
                    st.metric("52w High", f"{price_data['high_52w']}", f"{price_data['pct_from_52w_high']:.0f}%")
                with col3:
                    st.metric("52w Low", f"{price_data['low_52w']}", f"+{price_data['pct_from_52w_low']:.0f}%")

                st.markdown(f"**Equity Signal:** {signal['signal']} (Score: {signal['score']})")
                for reason in signal.get("reasons", []):
                    st.markdown(f"• {reason}")
            else:
                st.error("Could not fetch price data")
        else:
            st.warning(f"{selected} is privately held - no public equity data")


if __name__ == "__main__":
    # Test the module
    print("Testing Equity Monitor...")

    if YFINANCE_AVAILABLE:
        # Test single ticker
        print("\nTesting ThyssenKrupp (TKA.DE):")
        price = fetch_price_yfinance("TKA.DE")
        if price:
            print(f"  Price: {price['price']}")
            print(f"  Daily Change: {price['daily_change_pct']}%")
            signal = calculate_equity_signal(price)
            print(f"  Signal: {signal['signal']} (Score: {signal['score']})")

        # Test movers
        print("\nScanning for movers...")
        movers = get_movers(threshold_pct=2.0)
        print(f"  Gainers: {len(movers['gainers'])}")
        print(f"  Losers: {len(movers['losers'])}")
    else:
        print("yfinance not installed - install with: pip install yfinance")

    # Show ticker coverage
    tickers = get_all_public_tickers()
    print(f"\nPublic tickers mapped: {len(tickers)}")

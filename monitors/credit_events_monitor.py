"""
Credit Events Monitor for Apex Credit Monitor
Tracks earnings, covenants, and maturities for alpha generation

Features:
1. Earnings Impact Analyzer - Alert on earnings, auto-analyze credit impact
2. Covenant Breach Predictor - Track leverage vs covenant thresholds
3. Maturity Wall Scanner - Track refinancing risk
"""

import json
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Try to import yfinance
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# Try to import knowledge base
try:
    from knowledge.pdf_processor import KnowledgeBase
    _kb = KnowledgeBase()
    KB_AVAILABLE = True
except Exception:
    _kb = None
    KB_AVAILABLE = False


# ============== CONFIGURATION ==============

def load_secrets():
    """Load secrets from .streamlit/secrets.toml"""
    secrets = {}
    secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        try:
            with open(secrets_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        secrets[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            pass
    return secrets

_secrets = load_secrets()
XAI_API_KEY = _secrets.get("XAI_API_KEY") or os.environ.get("XAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = _secrets.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _secrets.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")


# ============== DATA STORAGE ==============

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

COVENANT_FILE = DATA_DIR / "covenant_data.json"
MATURITY_FILE = DATA_DIR / "maturity_data.json"
EARNINGS_ALERTS_FILE = DATA_DIR / "earnings_alerts.json"


def load_covenant_data() -> Dict:
    """Load covenant thresholds for companies"""
    if COVENANT_FILE.exists():
        with open(COVENANT_FILE, "r") as f:
            return json.load(f)
    return {}


def save_covenant_data(data: Dict):
    """Save covenant data"""
    with open(COVENANT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_maturity_data() -> Dict:
    """Load maturity schedules"""
    if MATURITY_FILE.exists():
        with open(MATURITY_FILE, "r") as f:
            return json.load(f)
    return {}


def save_maturity_data(data: Dict):
    """Save maturity data"""
    with open(MATURITY_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ============== 1. EARNINGS IMPACT ANALYZER ==============

def get_earnings_calendar(tickers: List[str]) -> List[Dict]:
    """
    Fetch upcoming earnings dates for tickers
    Returns list of companies with earnings in next 30 days
    """
    if not YFINANCE_AVAILABLE:
        return []

    upcoming = []
    today = datetime.now()
    cutoff = today + timedelta(days=30)

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            calendar = stock.calendar

            if calendar is not None and not calendar.empty:
                # Get earnings date
                if 'Earnings Date' in calendar.index:
                    earnings_dates = calendar.loc['Earnings Date']
                    if hasattr(earnings_dates, '__iter__'):
                        for ed in earnings_dates:
                            if ed and today <= ed <= cutoff:
                                upcoming.append({
                                    'ticker': ticker,
                                    'earnings_date': ed.strftime('%Y-%m-%d'),
                                    'days_until': (ed - today).days
                                })
                                break
                    elif earnings_dates and today <= earnings_dates <= cutoff:
                        upcoming.append({
                            'ticker': ticker,
                            'earnings_date': earnings_dates.strftime('%Y-%m-%d'),
                            'days_until': (earnings_dates - today).days
                        })
        except Exception as e:
            continue

    # Sort by date
    upcoming.sort(key=lambda x: x['days_until'])
    return upcoming


def analyze_earnings_for_credit(company_name: str, ticker: str) -> Dict:
    """
    Use Grok to analyze recent earnings and credit impact
    Call this after earnings are released
    """
    if not XAI_API_KEY:
        return {"error": "No API key configured"}

    # Get KB context about earnings analysis
    kb_context = ""
    if KB_AVAILABLE and _kb:
        results = _kb.search("earnings analysis credit impact leverage EBITDA guidance", top_k=2)
        if results:
            kb_context = "\n\n".join([r['text'][:400] for r in results])

    prompt = f"""You are a credit analyst. {company_name} ({ticker}) just reported earnings.

Search Twitter/X for posts about {company_name} earnings and tell me:
1. Key financial metrics (Revenue, EBITDA, margins vs expectations)
2. Any guidance changes
3. Leverage implications (did debt/EBITDA improve or worsen?)
4. Credit market reaction (any mention of bonds, CDS, spreads)
5. Overall credit impact: POSITIVE / NEGATIVE / NEUTRAL

Focus on accounts like @DeItaone, @FirstSquawk, @9finHQ, @Creditflux.
Be specific with numbers. If you can't find recent earnings, say so."""

    if kb_context:
        prompt += f"\n\nREFERENCE - How to analyze earnings for credit:\n{kb_context}"

    try:
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "grok-4-1-fast-reasoning",
                "messages": [
                    {"role": "system", "content": "You are a credit analyst focused on high-yield bonds. Analyze earnings for credit implications."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3
            },
            timeout=60
        )

        if response.status_code == 200:
            data = response.json()
            analysis = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "company": company_name,
                "ticker": ticker,
                "analysis": analysis,
                "analyzed_at": datetime.now().isoformat()
            }
        else:
            return {"error": f"API error: {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


# ============== 2. COVENANT BREACH PREDICTOR ==============

# Default covenant thresholds (typical HY)
DEFAULT_COVENANTS = {
    "max_leverage": 6.5,  # Max Debt/EBITDA
    "min_coverage": 2.0,  # Min EBITDA/Interest
    "max_secured_leverage": 4.0,  # Max Secured Debt/EBITDA
}


def set_covenant_levels(company_name: str, covenants: Dict):
    """
    Set covenant levels for a company

    Example:
    set_covenant_levels("ThyssenKrupp", {
        "max_leverage": 5.5,
        "min_coverage": 2.0,
        "test_date": "Q4 2024"
    })
    """
    data = load_covenant_data()
    data[company_name] = {
        **covenants,
        "updated_at": datetime.now().isoformat()
    }
    save_covenant_data(data)
    return data[company_name]


def check_covenant_headroom(company_name: str, current_leverage: float,
                            current_coverage: float = None) -> Dict:
    """
    Check how close a company is to breaching covenants

    Returns headroom analysis and alerts
    """
    data = load_covenant_data()
    covenants = data.get(company_name, DEFAULT_COVENANTS)

    max_leverage = covenants.get("max_leverage", DEFAULT_COVENANTS["max_leverage"])
    min_coverage = covenants.get("min_coverage", DEFAULT_COVENANTS["min_coverage"])

    result = {
        "company": company_name,
        "current_leverage": current_leverage,
        "covenant_leverage": max_leverage,
        "leverage_headroom": max_leverage - current_leverage,
        "leverage_headroom_pct": ((max_leverage - current_leverage) / max_leverage) * 100,
        "alerts": []
    }

    # Leverage alerts
    if current_leverage >= max_leverage:
        result["alerts"].append({
            "level": "CRITICAL",
            "message": f"COVENANT BREACH: Leverage {current_leverage:.1f}x exceeds covenant {max_leverage:.1f}x"
        })
    elif current_leverage >= max_leverage - 0.5:
        result["alerts"].append({
            "level": "HIGH",
            "message": f"WARNING: Within 0.5x of leverage covenant ({current_leverage:.1f}x vs {max_leverage:.1f}x)"
        })
    elif current_leverage >= max_leverage - 1.0:
        result["alerts"].append({
            "level": "MEDIUM",
            "message": f"WATCH: Within 1.0x of leverage covenant ({current_leverage:.1f}x vs {max_leverage:.1f}x)"
        })

    # Coverage alerts
    if current_coverage:
        result["current_coverage"] = current_coverage
        result["covenant_coverage"] = min_coverage
        result["coverage_headroom"] = current_coverage - min_coverage

        if current_coverage <= min_coverage:
            result["alerts"].append({
                "level": "CRITICAL",
                "message": f"COVENANT BREACH: Coverage {current_coverage:.1f}x below minimum {min_coverage:.1f}x"
            })
        elif current_coverage <= min_coverage + 0.3:
            result["alerts"].append({
                "level": "HIGH",
                "message": f"WARNING: Coverage {current_coverage:.1f}x near minimum {min_coverage:.1f}x"
            })

    return result


def scan_all_covenants(company_metrics: Dict[str, Dict]) -> List[Dict]:
    """
    Scan all companies for covenant issues

    Args:
        company_metrics: Dict of company_name -> {"leverage": x, "coverage": y}

    Returns:
        List of companies with covenant concerns
    """
    alerts = []

    for company, metrics in company_metrics.items():
        leverage = metrics.get("leverage")
        coverage = metrics.get("coverage")

        if leverage:
            result = check_covenant_headroom(company, leverage, coverage)
            if result["alerts"]:
                alerts.append(result)

    # Sort by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    alerts.sort(key=lambda x: min(severity_order.get(a["level"], 99) for a in x["alerts"]))

    return alerts


# ============== 3. MATURITY WALL SCANNER ==============

def set_maturity_schedule(company_name: str, maturities: Dict, liquidity: Dict = None):
    """
    Set maturity schedule for a company

    Example:
    set_maturity_schedule("ThyssenKrupp", {
        "2025": 500,  # $500m maturing in 2025
        "2026": 750,
        "2027": 1200,
        "2028": 0,
        "thereafter": 2000
    }, {
        "cash": 800,
        "revolver_available": 500,
        "revolver_total": 1000
    })
    """
    data = load_maturity_data()
    data[company_name] = {
        "maturities": maturities,
        "liquidity": liquidity or {},
        "updated_at": datetime.now().isoformat()
    }
    save_maturity_data(data)
    return data[company_name]


def analyze_maturity_wall(company_name: str) -> Dict:
    """
    Analyze refinancing risk for a company
    """
    data = load_maturity_data()
    company_data = data.get(company_name)

    if not company_data:
        return {"company": company_name, "error": "No maturity data available"}

    maturities = company_data.get("maturities", {})
    liquidity = company_data.get("liquidity", {})

    cash = liquidity.get("cash", 0)
    revolver = liquidity.get("revolver_available", 0)
    total_liquidity = cash + revolver

    current_year = datetime.now().year

    result = {
        "company": company_name,
        "total_liquidity": total_liquidity,
        "cash": cash,
        "revolver_available": revolver,
        "maturities": maturities,
        "alerts": [],
        "annual_analysis": []
    }

    # Analyze each year
    for year in range(current_year, current_year + 4):
        year_str = str(year)
        maturing = maturities.get(year_str, 0)

        if maturing > 0:
            coverage_ratio = total_liquidity / maturing if maturing else float('inf')

            year_analysis = {
                "year": year,
                "maturing": maturing,
                "coverage_ratio": round(coverage_ratio, 2),
                "risk_level": "LOW"
            }

            if coverage_ratio < 1.0:
                year_analysis["risk_level"] = "CRITICAL"
                result["alerts"].append({
                    "level": "CRITICAL",
                    "message": f"REFINANCING RISK: ${maturing}m maturing in {year}, only ${total_liquidity}m liquidity ({coverage_ratio:.1f}x coverage)"
                })
            elif coverage_ratio < 1.5:
                year_analysis["risk_level"] = "HIGH"
                result["alerts"].append({
                    "level": "HIGH",
                    "message": f"TIGHT LIQUIDITY: ${maturing}m maturing in {year}, ${total_liquidity}m liquidity ({coverage_ratio:.1f}x coverage)"
                })
            elif coverage_ratio < 2.0:
                year_analysis["risk_level"] = "MEDIUM"
                result["alerts"].append({
                    "level": "MEDIUM",
                    "message": f"WATCH: ${maturing}m maturing in {year} ({coverage_ratio:.1f}x coverage)"
                })

            result["annual_analysis"].append(year_analysis)

    # Total debt wall (next 3 years)
    total_3yr = sum(maturities.get(str(y), 0) for y in range(current_year, current_year + 3))
    result["total_3yr_maturities"] = total_3yr
    result["total_3yr_coverage"] = round(total_liquidity / total_3yr, 2) if total_3yr else None

    return result


def scan_all_maturities() -> List[Dict]:
    """
    Scan all companies for maturity wall issues
    """
    data = load_maturity_data()
    alerts = []

    for company in data.keys():
        result = analyze_maturity_wall(company)
        if result.get("alerts"):
            alerts.append(result)

    # Sort by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    alerts.sort(key=lambda x: min(severity_order.get(a["level"], 99) for a in x.get("alerts", [{"level": "LOW"}])))

    return alerts


# ============== TELEGRAM ALERTS ==============

def send_credit_alert(alert_type: str, company: str, message: str, level: str = "HIGH"):
    """Send credit event alert to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[ALERT] {alert_type}: {company} - {message}")
        return False

    emoji = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "📊", "LOW": "📌"}.get(level, "📌")

    text = f"""
{emoji} <b>Credit Alert: {alert_type}</b>

<b>Company:</b> {company}
<b>Level:</b> {level}

{message}

<i>{datetime.now().strftime('%Y-%m-%d %H:%M')}</i>
"""

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text.strip(),
                "parse_mode": "HTML"
            },
            timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


# ============== STREAMLIT INTEGRATION ==============

def render_credit_events_dashboard(st):
    """Render credit events dashboard in Streamlit"""
    st.markdown("### Credit Events Monitor")
    st.caption("Earnings, Covenants, and Maturity Analysis")

    tab1, tab2, tab3 = st.tabs(["📅 Earnings Calendar", "📊 Covenant Monitor", "📆 Maturity Wall"])

    # Load ticker config
    config_path = Path(__file__).parent.parent / "config" / "equity_tickers.json"
    tickers = []
    ticker_to_company = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)
            for company, info in config.get("ticker_map", {}).items():
                if info.get("ticker") and info["ticker"] != "Private":
                    tickers.append(info["ticker"])
                    ticker_to_company[info["ticker"]] = company

    with tab1:
        st.markdown("#### Upcoming Earnings")
        st.caption("Earnings dates for XO S44 credits - analyze for credit impact")

        if st.button("Fetch Earnings Calendar", key="fetch_earnings"):
            if YFINANCE_AVAILABLE:
                with st.spinner("Fetching earnings dates..."):
                    upcoming = get_earnings_calendar(tickers[:20])  # Limit to avoid timeout

                if upcoming:
                    for item in upcoming:
                        company = ticker_to_company.get(item['ticker'], item['ticker'])
                        days = item['days_until']

                        if days <= 3:
                            st.error(f"**{company}** ({item['ticker']}) - **{item['earnings_date']}** ({days} days)")
                        elif days <= 7:
                            st.warning(f"**{company}** ({item['ticker']}) - {item['earnings_date']} ({days} days)")
                        else:
                            st.info(f"**{company}** ({item['ticker']}) - {item['earnings_date']} ({days} days)")

                        if st.button(f"Analyze {company} Earnings", key=f"analyze_{item['ticker']}"):
                            with st.spinner("Analyzing with Grok..."):
                                result = analyze_earnings_for_credit(company, item['ticker'])
                                if result.get("analysis"):
                                    st.markdown(result["analysis"])
                                else:
                                    st.error(result.get("error", "Analysis failed"))
                else:
                    st.info("No earnings found in next 30 days for tracked companies")
            else:
                st.warning("yfinance not installed")

    with tab2:
        st.markdown("#### Covenant Monitor")
        st.caption("Track leverage vs covenant thresholds")

        # Add covenant data
        with st.expander("Add/Edit Covenant Data"):
            company = st.selectbox("Company", list(ticker_to_company.values()), key="cov_company")
            col1, col2 = st.columns(2)
            with col1:
                max_lev = st.number_input("Max Leverage Covenant", value=6.5, step=0.5, key="max_lev")
            with col2:
                min_cov = st.number_input("Min Coverage Covenant", value=2.0, step=0.25, key="min_cov")

            if st.button("Save Covenant", key="save_cov"):
                set_covenant_levels(company, {"max_leverage": max_lev, "min_coverage": min_cov})
                st.success(f"Saved covenants for {company}")

        # Check covenants
        st.markdown("---")
        covenant_data = load_covenant_data()

        if covenant_data:
            st.markdown("**Companies with covenant data:**")
            for comp, covs in covenant_data.items():
                st.markdown(f"- {comp}: Max {covs.get('max_leverage', 'N/A')}x leverage, Min {covs.get('min_coverage', 'N/A')}x coverage")

            with st.expander("Check Covenant Headroom"):
                check_company = st.selectbox("Select Company", list(covenant_data.keys()), key="check_cov")
                current_lev = st.number_input("Current Leverage (Debt/EBITDA)", value=5.0, step=0.1, key="curr_lev")
                current_cov = st.number_input("Current Coverage (EBITDA/Interest)", value=3.0, step=0.1, key="curr_cov")

                if st.button("Check Headroom", key="check_head"):
                    result = check_covenant_headroom(check_company, current_lev, current_cov)

                    st.metric("Leverage Headroom", f"{result['leverage_headroom']:.1f}x",
                              f"{result['leverage_headroom_pct']:.0f}% cushion")

                    for alert in result.get("alerts", []):
                        if alert["level"] == "CRITICAL":
                            st.error(alert["message"])
                        elif alert["level"] == "HIGH":
                            st.warning(alert["message"])
                        else:
                            st.info(alert["message"])
        else:
            st.info("No covenant data yet. Add covenants above.")

    with tab3:
        st.markdown("#### Maturity Wall Scanner")
        st.caption("Track refinancing risk by year")

        # Add maturity data
        with st.expander("Add/Edit Maturity Schedule"):
            mat_company = st.selectbox("Company", list(ticker_to_company.values()), key="mat_company")

            st.markdown("**Debt Maturities ($m)**")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                mat_2025 = st.number_input("2025", value=0, key="mat_2025")
            with col2:
                mat_2026 = st.number_input("2026", value=0, key="mat_2026")
            with col3:
                mat_2027 = st.number_input("2027", value=0, key="mat_2027")
            with col4:
                mat_2028 = st.number_input("2028+", value=0, key="mat_2028")

            st.markdown("**Liquidity ($m)**")
            col1, col2 = st.columns(2)
            with col1:
                cash = st.number_input("Cash", value=0, key="liq_cash")
            with col2:
                revolver = st.number_input("Revolver Available", value=0, key="liq_rev")

            if st.button("Save Maturity Data", key="save_mat"):
                set_maturity_schedule(mat_company, {
                    "2025": mat_2025, "2026": mat_2026,
                    "2027": mat_2027, "2028": mat_2028
                }, {"cash": cash, "revolver_available": revolver})
                st.success(f"Saved maturity data for {mat_company}")

        # Scan maturities
        st.markdown("---")
        if st.button("Scan All Maturities", key="scan_mat"):
            alerts = scan_all_maturities()

            if alerts:
                for result in alerts:
                    st.markdown(f"### {result['company']}")
                    st.markdown(f"**Liquidity:** ${result['total_liquidity']}m (Cash: ${result['cash']}m + Revolver: ${result['revolver_available']}m)")

                    for alert in result.get("alerts", []):
                        if alert["level"] == "CRITICAL":
                            st.error(alert["message"])
                        elif alert["level"] == "HIGH":
                            st.warning(alert["message"])
                        else:
                            st.info(alert["message"])

                    st.markdown("---")
            else:
                st.info("No maturity concerns found (or no data entered)")


if __name__ == "__main__":
    print("Credit Events Monitor")
    print("=" * 50)

    # Test earnings calendar
    if YFINANCE_AVAILABLE:
        print("\nFetching earnings for sample tickers...")
        upcoming = get_earnings_calendar(["TKA.DE", "AF.PA", "WIZZAIR.HU"])
        for item in upcoming:
            print(f"  {item['ticker']}: {item['earnings_date']} ({item['days_until']} days)")

    # Test covenant check
    print("\nTesting covenant check...")
    result = check_covenant_headroom("Test Company", 5.8, 2.2)
    print(f"  Leverage headroom: {result['leverage_headroom']:.1f}x")
    for alert in result.get("alerts", []):
        print(f"  [{alert['level']}] {alert['message']}")

    print("\nDone.")

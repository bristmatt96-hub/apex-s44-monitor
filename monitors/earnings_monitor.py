"""
Earnings Release Monitor
Tracks SEC filings and company announcements for XO S44 names
Alerts when earnings/results are filed so you can analyze before Debtwire publishes transcripts
"""

import streamlit as st
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import json
from pathlib import Path
import re

# SEC EDGAR base URL
SEC_EDGAR_BASE = "https://www.sec.gov"
SEC_EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
SEC_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"

# Filing types relevant for earnings
EARNINGS_FILING_TYPES = [
    "6-K",      # Foreign private issuer current report (earnings for EU HY names)
    "8-K",      # Current report (US companies)
    "10-Q",     # Quarterly report
    "10-K",     # Annual report
    "20-F",     # Foreign private issuer annual report
]

@dataclass
class EarningsAlert:
    company: str
    ticker: str
    filing_type: str
    filing_date: str
    description: str
    url: str
    source: str

# XO S44 names with SEC CIKs (foreign private issuers file 6-Ks)
# This is a subset - would need to be expanded for full coverage
XO_S44_SEC_CIKS = {
    "Ardagh": {
        "cik": "0001689574",  # Ardagh Packaging Finance plc
        "ticker": "ARD",
        "aliases": ["Ardagh Group", "Ardagh Packaging", "ARD"]
    },
    "Altice France": {
        "cik": None,  # Not SEC registered - uses French filings
        "ticker": "ALTICE",
        "aliases": ["SFR", "Altice"]
    },
    "Intrum": {
        "cik": None,  # Swedish - uses local filings
        "ticker": "INTRUM",
        "aliases": ["Intrum AB", "Intrum Justitia"]
    },
    "Telecom Italia": {
        "cik": "0001114856",
        "ticker": "TI",
        "aliases": ["TIM", "Telecom Italia"]
    },
    "Casino": {
        "cik": None,  # French - uses AMF filings
        "ticker": "CO",
        "aliases": ["Casino Guichard", "Casino"]
    },
    "Iliad": {
        "cik": None,
        "ticker": "ILD",
        "aliases": ["Iliad", "Free"]
    },
    "Lumen": {
        "cik": "0000018926",
        "ticker": "LUMN",
        "aliases": ["Lumen Technologies", "CenturyLink"]
    },
    "Dish Network": {
        "cik": "0001001082",
        "ticker": "DISH",
        "aliases": ["DISH", "EchoStar"]
    },
    # Add more as needed...
}

# Press release sources to monitor
PRESS_RELEASE_SOURCES = [
    "Business Wire",
    "PR Newswire",
    "GlobeNewswire",
    "Company IR page",
]


def fetch_sec_filings(cik: str, filing_types: List[str] = None, days_back: int = 30) -> List[Dict]:
    """
    Fetch recent SEC filings for a given CIK.
    Uses SEC EDGAR API.
    """
    if not cik:
        return []

    if filing_types is None:
        filing_types = EARNINGS_FILING_TYPES

    try:
        # SEC requires user-agent header
        headers = {
            "User-Agent": "XO-S44-Monitor/1.0 (credit-research@example.com)",
            "Accept": "application/json"
        }

        # Fetch company submissions
        url = f"{SEC_EDGAR_SUBMISSIONS}/CIK{cik.zfill(10)}.json"
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()

        # Parse recent filings
        filings = []
        recent_filings = data.get("filings", {}).get("recent", {})

        forms = recent_filings.get("form", [])
        dates = recent_filings.get("filingDate", [])
        accessions = recent_filings.get("accessionNumber", [])
        descriptions = recent_filings.get("primaryDocument", [])

        cutoff_date = datetime.now() - timedelta(days=days_back)

        for i in range(min(len(forms), 50)):  # Check last 50 filings
            form = forms[i]
            date_str = dates[i]

            # Filter by form type
            if form not in filing_types:
                continue

            # Filter by date
            try:
                filing_date = datetime.strptime(date_str, "%Y-%m-%d")
                if filing_date < cutoff_date:
                    continue
            except Exception:
                continue

            # Build filing URL
            accession = accessions[i].replace("-", "")
            doc = descriptions[i]
            filing_url = f"{SEC_EDGAR_BASE}/Archives/edgar/data/{cik}/{accession}/{doc}"

            filings.append({
                "form": form,
                "date": date_str,
                "url": filing_url,
                "description": doc
            })

        return filings

    except Exception as e:
        st.error(f"SEC fetch error: {e}")
        return []


def check_for_earnings_keywords(text: str) -> bool:
    """Check if filing description suggests earnings release."""
    earnings_keywords = [
        "results", "earnings", "quarterly", "annual",
        "financial", "revenue", "ebitda", "guidance",
        "q1", "q2", "q3", "q4", "fy", "1h", "2h",
        "9m", "6m", "3m", "full year", "half year"
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in earnings_keywords)


def get_all_earnings_alerts(days_back: int = 14) -> List[EarningsAlert]:
    """
    Check all XO S44 names for recent earnings filings.
    Returns list of alerts.
    """
    alerts = []

    for company, info in XO_S44_SEC_CIKS.items():
        cik = info.get("cik")
        ticker = info.get("ticker", "")

        if not cik:
            continue  # Skip non-SEC registered companies

        filings = fetch_sec_filings(cik, days_back=days_back)

        for filing in filings:
            # Check if this looks like earnings
            is_earnings = (
                filing["form"] in ["6-K", "8-K", "10-Q", "10-K", "20-F"] and
                check_for_earnings_keywords(filing.get("description", ""))
            )

            alert = EarningsAlert(
                company=company,
                ticker=ticker,
                filing_type=filing["form"],
                filing_date=filing["date"],
                description=filing.get("description", ""),
                url=filing["url"],
                source="SEC EDGAR"
            )
            alerts.append(alert)

    # Sort by date descending
    alerts.sort(key=lambda x: x.filing_date, reverse=True)

    return alerts


def estimate_transcript_timing(filing_date: str) -> str:
    """
    Estimate when Debtwire/transcript will be available.
    Typically 5-10 days after filing.
    """
    try:
        date = datetime.strptime(filing_date, "%Y-%m-%d")
        earliest = date + timedelta(days=3)
        latest = date + timedelta(days=10)
        return f"{earliest.strftime('%d %b')} - {latest.strftime('%d %b')}"
    except Exception:
        return "Unknown"


# ============================================================================
# STREAMLIT UI
# ============================================================================

def render_earnings_monitor():
    """Render the earnings monitor dashboard."""
    st.header("📅 Earnings Release Monitor")
    st.caption("Track SEC filings to catch earnings BEFORE Debtwire transcripts")

    # Controls
    col1, col2 = st.columns([2, 1])

    with col1:
        days_back = st.slider("Days to look back:", 7, 60, 14)

    with col2:
        if st.button("🔄 Refresh", type="primary"):
            st.rerun()

    st.markdown("---")

    # Alpha timing explanation
    with st.expander("ℹ️ Why this matters for Alpha"):
        st.markdown("""
        **The Information Timeline:**

        ```
        Day 0:  Company files 6-K/8-K with SEC (or local exchange)
                → YOU CAN ACCESS RAW FILING IMMEDIATELY
                → Run sentiment analysis on management commentary

        Day 1-3: Earnings call happens (if not same day)
                → Call usually within 24-48hrs of filing
                → Some transcription services have same-day

        Day 5-10: Debtwire publishes formatted transcript
                → This is what you received for Ardagh (9 days lag)
                → By now, fast money has already traded
        ```

        **The Gap:** Debtwire transcripts are convenient but LAGGING indicators.
        The raw SEC filing and press release are available immediately.

        **Your Edge:** Monitor filings → Read raw → Run sentiment → Trade
        """)

    # Fetch alerts
    with st.spinner("Checking SEC EDGAR for recent filings..."):
        alerts = get_all_earnings_alerts(days_back=days_back)

    if not alerts:
        st.info("No recent earnings filings found for monitored names.")
        st.caption("Note: Many EUR HY names are not SEC-registered. See 'Coverage Gaps' below.")
    else:
        st.success(f"Found {len(alerts)} recent filings")

        for alert in alerts:
            with st.container():
                col1, col2, col3 = st.columns([2, 1, 1])

                with col1:
                    st.markdown(f"### {alert.company} ({alert.ticker})")
                    st.caption(f"{alert.filing_type} - {alert.description}")

                with col2:
                    st.markdown(f"**Filed:** {alert.filing_date}")
                    st.caption(f"Transcript est: {estimate_transcript_timing(alert.filing_date)}")

                with col3:
                    st.link_button("📄 View Filing", alert.url)

                st.markdown("---")

    # Coverage gaps
    st.markdown("### Coverage Gaps")
    st.caption("These XO S44 names are NOT SEC-registered - need alternative sources")

    non_sec = [name for name, info in XO_S44_SEC_CIKS.items() if not info.get("cik")]

    if non_sec:
        cols = st.columns(3)
        for i, name in enumerate(non_sec):
            with cols[i % 3]:
                st.write(f"• {name}")

    st.markdown("""
    **Alternative sources for non-SEC names:**
    - 🇫🇷 French: AMF database (autorité des marchés financiers)
    - 🇩🇪 German: Bundesanzeiger
    - 🇳🇱 Dutch: AFM
    - 🇬🇧 UK: Companies House, FCA RNS
    - 🇸🇪 Swedish: Finansinspektionen
    - 🇮🇪 Irish: CRO / ISE

    Consider: Bloomberg SRCH, Capital IQ, or Debtwire alerts for non-SEC coverage
    """)

    # Manual add section
    st.markdown("---")
    st.markdown("### Add Company to Monitor")

    col1, col2, col3 = st.columns(3)

    with col1:
        new_company = st.text_input("Company Name:", placeholder="e.g., Telecom Italia")
    with col2:
        new_cik = st.text_input("SEC CIK:", placeholder="e.g., 0001114856")
    with col3:
        new_ticker = st.text_input("Ticker:", placeholder="e.g., TI")

    st.caption("Find CIKs at: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany")

    if st.button("Add Company"):
        if new_company and new_cik:
            st.success(f"Added {new_company} (CIK: {new_cik}) to monitor")
            st.info("Note: In production, this would persist to config file")


# ============================================================================
# ARDAGH SPECIFIC ANALYSIS
# ============================================================================

def analyze_ardagh_timeline():
    """
    Specific analysis of Ardagh 9M25 information timeline.
    Shows what was available when.
    """
    st.markdown("### Ardagh 9M25 Timeline Analysis")

    timeline = [
        ("25 Nov 2025", "6-K Filed", "SEC EDGAR", "🟢 PUBLIC - Raw filing available"),
        ("25 Nov 2025", "Press Release", "Business Wire", "🟢 PUBLIC - Key metrics in headline"),
        ("25-26 Nov", "Earnings Call", "Company IR", "🟡 LIVE - Need dial-in or webcast"),
        ("26-28 Nov", "Sell-side Notes", "Banks", "🟡 RESTRICTED - Client distribution"),
        ("04 Dec 2025", "Transcript", "Debtwire", "🟢 PUBLIC - Full Q&A, 9 days late"),
    ]

    for date, event, source, status in timeline:
        col1, col2, col3, col4 = st.columns([1, 1.5, 1, 2])
        with col1:
            st.write(date)
        with col2:
            st.write(f"**{event}**")
        with col3:
            st.write(source)
        with col4:
            st.write(status)

    st.markdown("---")
    st.markdown("""
    **Alpha Assessment:**

    | If you had... | Your edge was... |
    |--------------|------------------|
    | SEC monitor | **9 days** vs Debtwire |
    | Press release alert | **9 days** vs Debtwire |
    | Earnings call dial-in | **8 days** vs Debtwire |
    | Sell-side relationship | **7 days** vs Debtwire |
    | Debtwire only | **0 days** - you ARE the lagging indicator |

    **Conclusion:** The Debtwire transcript is a convenience product, not an alpha source.
    The raw information was public 9 days earlier.
    """)


if __name__ == "__main__":
    # Test SEC fetch
    print("Testing Ardagh SEC fetch...")
    filings = fetch_sec_filings("0001689574", days_back=60)
    for f in filings[:5]:
        print(f"  {f['date']} - {f['form']} - {f['description']}")

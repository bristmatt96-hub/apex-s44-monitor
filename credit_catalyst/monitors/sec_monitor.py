"""
SEC EDGAR Filing Monitor

Monitors SEC EDGAR for credit-relevant filings:
- 8-K: Material events (covenant violations, liquidity issues, going concern)
- 10-Q/10-K: Quarterly/annual with amendments
- NT filings: Late filing notifications (red flag)
- Form 4: Insider selling patterns
"""

import requests
import feedparser
import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# SEC filing types relevant to credit deterioration
CREDIT_RELEVANT_FILINGS = [
    '8-K',      # Material events
    '8-K/A',    # Amended 8-K
    '10-Q',     # Quarterly report
    '10-Q/A',   # Amended quarterly
    '10-K',     # Annual report
    '10-K/A',   # Amended annual
    'NT 10-Q',  # Late quarterly (red flag)
    'NT 10-K',  # Late annual (red flag)
    '4',        # Insider transactions
]

# 8-K items indicating credit stress
CREDIT_STRESS_8K_ITEMS = [
    '1.03',  # Bankruptcy or receivership
    '2.04',  # Triggering events (defaults, accelerations)
    '2.06',  # Material impairments
    '3.01',  # Delisting notice
    '4.02',  # Non-reliance on prior financials
    '5.02',  # Departure of principal officers (CFO, CEO)
    '7.01',  # Regulation FD Disclosure (guidance cuts)
]


class SECFilingMonitor:
    """Monitor SEC EDGAR for credit-relevant filings."""

    BASE_URL = "https://www.sec.gov"
    EDGAR_RSS = "https://www.sec.gov/cgi-bin/browse-edgar"

    def __init__(self, watchlist_ciks: List[str]):
        """
        Initialize SEC filing monitor.

        Args:
            watchlist_ciks: List of CIK numbers to monitor
        """
        self.watchlist_ciks = watchlist_ciks
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'CreditCatalyst/0.1 (credit-monitoring@example.com)'
        })

    def get_recent_filings(self, cik: str, filing_types: Optional[List[str]] = None) -> List[Dict]:
        """
        Fetch recent filings for a company.

        Args:
            cik: Company CIK number
            filing_types: Optional list of filing types to filter

        Returns:
            List of filing dictionaries
        """
        if filing_types is None:
            filing_types = CREDIT_RELEVANT_FILINGS

        filings = []

        # Use SEC EDGAR RSS feed
        for filing_type in filing_types:
            try:
                url = f"{self.EDGAR_RSS}?action=getcompany&CIK={cik}&type={filing_type}&dateb=&owner=include&count=10&output=atom"
                response = self.session.get(url, timeout=30)

                if response.status_code == 200:
                    feed = feedparser.parse(response.text)
                    for entry in feed.entries:
                        filings.append({
                            'cik': cik,
                            'filing_type': filing_type,
                            'title': entry.get('title', ''),
                            'link': entry.get('link', ''),
                            'filed_date': entry.get('updated', ''),
                            'summary': entry.get('summary', ''),
                        })
            except Exception as e:
                logger.error(f"Error fetching {filing_type} for CIK {cik}: {e}")

        return filings

    def check_all_watchlist(self) -> List[Dict]:
        """Check all companies in watchlist for new filings."""
        all_filings = []
        for cik in self.watchlist_ciks:
            filings = self.get_recent_filings(cik)
            all_filings.extend(filings)
        return all_filings

    def is_credit_stress_8k(self, filing_text: str) -> bool:
        """
        Check if 8-K filing indicates credit stress.

        Args:
            filing_text: Raw text of 8-K filing

        Returns:
            True if filing contains credit stress indicators
        """
        for item in CREDIT_STRESS_8K_ITEMS:
            if f"Item {item}" in filing_text:
                return True
        return False

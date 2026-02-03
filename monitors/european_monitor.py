"""
European Monitor for Credit Catalyst

Monitors European companies that don't file with SEC:
- UK: Companies House API + RNS (Regulatory News Service)
- EU: ESMA OAM links (fragmented by country, ESAP coming July 2027)

Sources:
- Companies House API: https://developer.company-information.service.gov.uk/
- RNS: https://www.lse.co.uk/rns/
- ESMA OAMs: https://www.esma.europa.eu/access-regulated-information
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class RegulatoryFiling:
    """Represents a regulatory filing/announcement."""
    company_name: str
    company_id: str
    filing_type: str
    headline: str
    date: str
    source: str  # 'companies_house', 'rns', 'esma'
    url: Optional[str] = None
    content_summary: Optional[str] = None
    credit_relevant: bool = False
    priority: str = "low"  # low, medium, high


class CompaniesHouseMonitor:
    """
    Monitor UK company filings via Companies House API.

    Free API with 600 requests per 5 minutes (2/sec).
    Docs: https://developer.company-information.service.gov.uk/
    """

    BASE_URL = "https://api.company-information.service.gov.uk"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("COMPANIES_HOUSE_API_KEY")
        if not self.api_key:
            logger.warning("No Companies House API key set. Get one at: https://developer.company-information.service.gov.uk/")
        self.session = requests.Session()
        if self.api_key:
            self.session.auth = (self.api_key, "")  # API key as username, blank password

    def search_company(self, query: str) -> List[Dict]:
        """Search for companies by name."""
        if not self.api_key:
            return []

        url = f"{self.BASE_URL}/search/companies"
        params = {"q": query, "items_per_page": 10}

        try:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            return resp.json().get("items", [])
        except Exception as e:
            logger.error(f"Companies House search error: {e}")
            return []

    def get_company_profile(self, company_number: str) -> Optional[Dict]:
        """Get company profile by company number."""
        if not self.api_key:
            return None

        url = f"{self.BASE_URL}/company/{company_number}"

        try:
            resp = self.session.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Companies House profile error: {e}")
            return None

    def get_filing_history(self, company_number: str, items: int = 25) -> List[Dict]:
        """Get recent filing history for a company."""
        if not self.api_key:
            return []

        url = f"{self.BASE_URL}/company/{company_number}/filing-history"
        params = {"items_per_page": items}

        try:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            return resp.json().get("items", [])
        except Exception as e:
            logger.error(f"Companies House filing history error: {e}")
            return []

    def check_new_filings(self, company_number: str, since_days: int = 7) -> List[RegulatoryFiling]:
        """Check for new filings in the last N days."""
        filings = self.get_filing_history(company_number)
        cutoff = datetime.now() - timedelta(days=since_days)
        new_filings = []

        for filing in filings:
            filing_date = datetime.strptime(filing.get("date", ""), "%Y-%m-%d")
            if filing_date >= cutoff:
                rf = RegulatoryFiling(
                    company_name=filing.get("description", "Unknown"),
                    company_id=company_number,
                    filing_type=filing.get("type", "unknown"),
                    headline=filing.get("description", ""),
                    date=filing.get("date", ""),
                    source="companies_house",
                    url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/filing-history",
                    credit_relevant=self._is_credit_relevant(filing)
                )
                new_filings.append(rf)

        return new_filings

    def _is_credit_relevant(self, filing: Dict) -> bool:
        """Determine if a filing is credit-relevant."""
        credit_types = [
            "accounts", "annual-return", "charge", "mortgage",
            "resolution", "change-of-name", "liquidation",
            "administration", "voluntary-arrangement"
        ]
        filing_type = filing.get("type", "").lower()
        return any(ct in filing_type for ct in credit_types)


class RNSMonitor:
    """
    Monitor UK Regulatory News Service announcements.

    Scrapes public RNS feed from LSE website.
    For official API access, contact rns@lseg.com
    """

    RNS_URL = "https://www.lse.co.uk/rns/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; CreditCatalyst/1.0)"
        })

    def get_recent_announcements(self, limit: int = 50) -> List[Dict]:
        """
        Scrape recent RNS announcements from LSE website.
        Note: For production, use official LSEG API.
        """
        try:
            resp = self.session.get(self.RNS_URL, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            announcements = []
            # Parse RNS table - structure may change
            table = soup.find("table", class_="rns-table")
            if table:
                rows = table.find_all("tr")[1:limit+1]  # Skip header
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 4:
                        announcements.append({
                            "time": cols[0].get_text(strip=True),
                            "company": cols[1].get_text(strip=True),
                            "headline": cols[2].get_text(strip=True),
                            "type": cols[3].get_text(strip=True) if len(cols) > 3 else ""
                        })

            return announcements
        except Exception as e:
            logger.error(f"RNS scraping error: {e}")
            return []

    def search_company_announcements(self, company_name: str, days: int = 30) -> List[RegulatoryFiling]:
        """
        Search for company-specific announcements.
        Note: Limited without official API access.
        """
        # For now, return empty - would need official API for search
        logger.info(f"RNS search for {company_name} requires official API access")
        return []

    def filter_credit_relevant(self, announcements: List[Dict]) -> List[Dict]:
        """Filter announcements for credit-relevant keywords."""
        credit_keywords = [
            "debt", "bond", "loan", "credit", "covenant", "refinanc",
            "restructur", "default", "downgrade", "upgrade", "rating",
            "maturity", "dividend", "capital", "liquidity", "leverage",
            "earnings", "profit warning", "trading update", "results"
        ]

        relevant = []
        for ann in announcements:
            headline = ann.get("headline", "").lower()
            if any(kw in headline for kw in credit_keywords):
                ann["credit_relevant"] = True
                relevant.append(ann)

        return relevant


class EuropeanMonitor:
    """
    Combined European regulatory monitor.

    Aggregates:
    - UK: Companies House + RNS
    - EU: ESMA OAM links (manual for now, ESAP coming July 2027)
    """

    # ESMA OAM links by country
    ESMA_OAMS = {
        "UK": "https://data.fca.org.uk/#/nsm/nationalstoragemechanism",
        "Germany": "https://www.bundesanzeiger.de/",
        "France": "https://www.info-financiere.fr/",
        "Italy": "https://www.1info.it/",
        "Spain": "https://www.cnmv.es/portal/home.aspx",
        "Netherlands": "https://www.afm.nl/en/professionals/registers",
        "Sweden": "https://marknadssok.fi.se/",
        "Luxembourg": "https://www.cssf.lu/en/",
        "Ireland": "https://www.centralbank.ie/regulation",
    }

    def __init__(self, companies_house_key: str = None):
        self.ch_monitor = CompaniesHouseMonitor(companies_house_key)
        self.rns_monitor = RNSMonitor()
        self.watchlist = self._load_watchlist()

    def _load_watchlist(self) -> Dict:
        """Load XO S44 watchlist with UK company numbers."""
        # Map of company names to UK Companies House numbers (where applicable)
        # These need to be populated with actual company numbers
        return {
            "INEOS Finance plc": {"ch_number": "10040243", "country": "UK"},
            "INEOS Quattro Finance 2 plc": {"ch_number": "12809822", "country": "UK"},
            "Virgin Media Finance plc": {"ch_number": "08aborad", "country": "UK"},
            "Jaguar Land Rover Automotive plc": {"ch_number": "06477691", "country": "UK"},
            "Bellis Acquisition Company plc": {"ch_number": "13035608", "country": "UK"},
            "Stonegate Pub Company Financing plc": {"ch_number": "11532037", "country": "UK"},
            "Iceland Bondco plc": {"ch_number": "10314498", "country": "UK"},
            "Premier Foods Finance plc": {"ch_number": "05765669", "country": "UK"},
            "Playtech plc": {"ch_number": None, "country": "Isle of Man"},
            # Add more as needed...
        }

    def check_uk_filings(self, since_days: int = 7) -> List[RegulatoryFiling]:
        """Check Companies House filings for UK watchlist companies."""
        all_filings = []

        for company, info in self.watchlist.items():
            if info.get("country") == "UK" and info.get("ch_number"):
                logger.info(f"Checking Companies House for {company}")
                filings = self.ch_monitor.check_new_filings(
                    info["ch_number"],
                    since_days=since_days
                )
                for f in filings:
                    f.company_name = company
                all_filings.extend(filings)
                time.sleep(0.5)  # Rate limiting

        return all_filings

    def check_rns_announcements(self) -> List[Dict]:
        """Check recent RNS announcements and filter for watchlist."""
        announcements = self.rns_monitor.get_recent_announcements(limit=100)

        # Filter for watchlist companies
        watchlist_names = [name.lower() for name in self.watchlist.keys()]
        relevant = []

        for ann in announcements:
            company = ann.get("company", "").lower()
            if any(wl in company for wl in watchlist_names):
                relevant.append(ann)

        # Also filter for credit-relevant keywords
        credit_relevant = self.rns_monitor.filter_credit_relevant(announcements)

        return {
            "watchlist_matches": relevant,
            "credit_relevant": credit_relevant
        }

    def get_oam_links(self, country: str) -> Optional[str]:
        """Get ESMA OAM link for a country."""
        return self.ESMA_OAMS.get(country)

    def run_scan(self) -> Dict:
        """Run full European regulatory scan."""
        logger.info("Starting European regulatory scan...")

        results = {
            "timestamp": datetime.now().isoformat(),
            "uk_filings": [],
            "rns_announcements": {},
            "alerts": []
        }

        # Check UK Companies House
        if self.ch_monitor.api_key:
            results["uk_filings"] = [asdict(f) for f in self.check_uk_filings()]
            logger.info(f"Found {len(results['uk_filings'])} UK filings")
        else:
            logger.warning("Skipping Companies House - no API key")

        # Check RNS
        results["rns_announcements"] = self.check_rns_announcements()
        logger.info(f"Found {len(results['rns_announcements'].get('watchlist_matches', []))} RNS matches")

        # Generate alerts for credit-relevant items
        for filing in results["uk_filings"]:
            if filing.get("credit_relevant"):
                results["alerts"].append({
                    "type": "uk_filing",
                    "company": filing["company_name"],
                    "headline": filing["headline"],
                    "priority": "medium"
                })

        return results


def main():
    """Test the European monitor."""
    print("=" * 60)
    print("EUROPEAN REGULATORY MONITOR - TEST")
    print("=" * 60)

    monitor = EuropeanMonitor()

    # Test RNS scraping
    print("\n--- Recent RNS Announcements ---")
    rns = monitor.rns_monitor.get_recent_announcements(limit=10)
    for ann in rns[:5]:
        print(f"  {ann.get('time')} | {ann.get('company')} | {ann.get('headline')[:50]}...")

    # Test credit-relevant filter
    print("\n--- Credit-Relevant RNS ---")
    credit_rns = monitor.rns_monitor.filter_credit_relevant(rns)
    for ann in credit_rns[:5]:
        print(f"  {ann.get('company')} | {ann.get('headline')[:60]}...")

    # Show ESMA OAM links
    print("\n--- ESMA OAM Links (EU National Databases) ---")
    for country, url in monitor.ESMA_OAMS.items():
        print(f"  {country}: {url}")

    print("\n--- Companies House Status ---")
    if monitor.ch_monitor.api_key:
        print("  API key configured - ready to monitor UK filings")
    else:
        print("  No API key - get free key at:")
        print("  https://developer.company-information.service.gov.uk/")


if __name__ == "__main__":
    main()

"""
SEC EDGAR Insider Trading Scanner
Monitors Form 4 filings for insider buying activity.

Insider buying is one of the strongest bullish signals:
- Officers/directors buying with their own money
- Must report within 2 business days (Form 4)
- Buying is more meaningful than selling (many reasons to sell, only one to buy)

Data source: SEC EDGAR (free, no API key needed)
Rate limit: 10 requests/second with User-Agent header
"""
import asyncio
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import pandas as pd
from loguru import logger

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from core.base_agent import BaseAgent, AgentMessage
from core.models import Signal, MarketType, SignalType


# SEC requires User-Agent with name and email
EDGAR_HEADERS = {
    'User-Agent': 'ApexTrader trading-bot@example.com',
    'Accept': 'application/json'
}

# Rate limit: max 10 requests/second
EDGAR_RATE_LIMIT = 0.15  # seconds between requests


@dataclass
class InsiderTransaction:
    """A single insider transaction from Form 4"""
    symbol: str
    insider_name: str
    insider_title: str  # CEO, CFO, Director, etc.
    transaction_type: str  # P=Purchase, S=Sale, A=Award
    shares: float
    price: float
    total_value: float
    date_filed: datetime
    ownership_type: str  # D=Direct, I=Indirect


# CIK lookup for our watchlist (SEC uses CIK numbers, not tickers)
# Pre-mapped for speed - EDGAR ticker search is slow
TICKER_TO_CIK = {
    'AAPL': '0000320193', 'MSFT': '0000789019', 'GOOGL': '0001652044',
    'AMZN': '0001018724', 'META': '0001326801', 'TSLA': '0001318605',
    'NVDA': '0001045810', 'AMD': '0000002488', 'NFLX': '0001065280',
    'COIN': '0001679788', 'SPY': '0000884394', 'QQQ': '0001067839',
    'GME': '0001326380', 'AMC': '0001411579', 'PLTR': '0001321655',
    'SOFI': '0001818874', 'HOOD': '0001783879', 'RIVN': '0001874178',
    'LCID': '0001811210', 'MARA': '0001507605', 'RIOT': '0001167419',
    'DKNG': '0001883685', 'JOBY': '0001819848', 'IONQ': '0001812364',
    'RKLB': '0001819994', 'IWM': '0000714310', 'ARKK': '0001697855',
    'XLE': '0001064642', 'XLF': '0001064641', 'GLD': '0001222333',
    'BB': '0001070235', 'DNA': '0001899287', 'OPEN': '0001801169',
}


class EdgarInsiderScanner(BaseAgent):
    """
    Scans SEC EDGAR for insider buying activity.

    Flow:
    1. Fetches recent Form 4 filings for watchlist companies
    2. Parses insider transactions
    3. Filters for significant purchases
    4. Generates buy signals with insider context
    5. Sends to coordinator for ranking

    Scan frequency: Every 30 minutes (EDGAR updates ~15min delay)
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("EdgarInsiderScanner", config)
        self.scan_interval = 1800  # 30 minutes
        self.last_scan: Optional[datetime] = None
        self.seen_filings: set = set()  # Track already-processed filings
        self.min_purchase_value = 10_000  # Minimum $10k purchase to signal
        self.insider_cache: Dict[str, List[InsiderTransaction]] = {}
        self.signals_generated: List[Signal] = []

        # Watchlist from our backtest-proven symbols
        self.watchlist = list(TICKER_TO_CIK.keys())

    async def process(self) -> None:
        """Main scanning loop"""
        if not REQUESTS_AVAILABLE:
            logger.warning("[EdgarInsider] requests library not available")
            await asyncio.sleep(60)
            return

        # Check if it's time to scan
        if self.last_scan:
            elapsed = (datetime.now() - self.last_scan).seconds
            if elapsed < self.scan_interval:
                await asyncio.sleep(5)
                return

        logger.info("[EdgarInsider] Scanning SEC EDGAR for insider buying...")

        signals_found = 0

        for symbol in self.watchlist:
            cik = TICKER_TO_CIK.get(symbol)
            if not cik:
                continue

            try:
                transactions = await self._fetch_insider_transactions(symbol, cik)

                # Filter for recent significant purchases
                recent_buys = [
                    t for t in transactions
                    if t.transaction_type == 'P'
                    and t.total_value >= self.min_purchase_value
                    and t.date_filed >= datetime.now() - timedelta(days=7)
                    and t.insider_name not in self.seen_filings
                ]

                if recent_buys:
                    signal = self._generate_signal(symbol, recent_buys)
                    if signal:
                        signals_found += 1
                        self.signals_generated.append(signal)
                        await self._broadcast_signal(signal)

                        # Mark as seen
                        for t in recent_buys:
                            self.seen_filings.add(f"{t.insider_name}_{t.date_filed.date()}")

                # Rate limit
                await asyncio.sleep(EDGAR_RATE_LIMIT)

            except Exception as e:
                logger.debug(f"[EdgarInsider] Error scanning {symbol}: {e}")
                continue

        self.last_scan = datetime.now()
        logger.info(f"[EdgarInsider] Scan complete. Insider buy signals: {signals_found}")

    async def _fetch_insider_transactions(self, symbol: str, cik: str) -> List[InsiderTransaction]:
        """Fetch recent insider transactions from EDGAR"""
        transactions = []

        try:
            # EDGAR company submissions endpoint
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            response = requests.get(url, headers=EDGAR_HEADERS, timeout=10)

            if response.status_code != 200:
                return transactions

            data = response.json()

            # Get recent filings
            recent_filings = data.get('filings', {}).get('recent', {})
            forms = recent_filings.get('form', [])
            dates = recent_filings.get('filingDate', [])
            accessions = recent_filings.get('accessionNumber', [])
            primary_docs = recent_filings.get('primaryDocument', [])

            # Find Form 4 filings (insider transactions)
            for i, form in enumerate(forms):
                if form != '4' or i >= len(dates):
                    continue

                filing_date = datetime.strptime(dates[i], '%Y-%m-%d')

                # Only look at filings from last 14 days
                if filing_date < datetime.now() - timedelta(days=14):
                    continue

                # Fetch the actual Form 4 data
                accession = accessions[i].replace('-', '')
                doc = primary_docs[i] if i < len(primary_docs) else ''

                if doc.endswith('.xml'):
                    txns = await self._parse_form4(symbol, cik, accession, doc, filing_date)
                    transactions.extend(txns)

                await asyncio.sleep(EDGAR_RATE_LIMIT)

        except Exception as e:
            logger.debug(f"[EdgarInsider] Fetch error for {symbol}: {e}")

        return transactions

    async def _parse_form4(
        self, symbol: str, cik: str, accession: str, doc: str, filing_date: datetime
    ) -> List[InsiderTransaction]:
        """Parse a Form 4 XML filing for transaction details"""
        transactions = []

        try:
            # Form 4 XML endpoint
            url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{doc}"
            response = requests.get(url, headers=EDGAR_HEADERS, timeout=10)

            if response.status_code != 200:
                return transactions

            # Parse XML - using simple string parsing to avoid lxml dependency
            content = response.text

            # Extract reporter name
            insider_name = self._extract_xml_value(content, 'rptOwnerName')
            insider_title = self._extract_xml_value(content, 'officerTitle') or 'Director'

            # Look for non-derivative transactions
            # Transaction code: P=Purchase, S=Sale, A=Award/Grant
            tx_code = self._extract_xml_value(content, 'transactionCode')
            shares_str = self._extract_xml_value(content, 'transactionShares', 'value')
            price_str = self._extract_xml_value(content, 'transactionPricePerShare', 'value')
            ownership = self._extract_xml_value(content, 'directOrIndirectOwnership', 'value')

            if tx_code and shares_str and price_str:
                try:
                    shares = float(shares_str)
                    price = float(price_str)
                    total_value = shares * price

                    transactions.append(InsiderTransaction(
                        symbol=symbol,
                        insider_name=insider_name or 'Unknown',
                        insider_title=insider_title or 'Officer',
                        transaction_type=tx_code,
                        shares=shares,
                        price=price,
                        total_value=total_value,
                        date_filed=filing_date,
                        ownership_type=ownership or 'D'
                    ))
                except (ValueError, TypeError):
                    pass

        except Exception as e:
            logger.debug(f"[EdgarInsider] Parse error: {e}")

        return transactions

    def _extract_xml_value(self, xml: str, tag: str, subtag: str = None) -> Optional[str]:
        """Simple XML value extraction without lxml dependency"""
        try:
            if subtag:
                # Look for <tag><subtag>value</subtag></tag>
                start = xml.find(f'<{tag}>')
                if start == -1:
                    return None
                end = xml.find(f'</{tag}>', start)
                block = xml[start:end]
                inner_start = block.find(f'<{subtag}>') + len(f'<{subtag}>')
                inner_end = block.find(f'</{subtag}>')
                if inner_start > len(f'<{subtag}>') - 1 and inner_end > inner_start:
                    return block[inner_start:inner_end].strip()
            else:
                start = xml.find(f'<{tag}>') + len(f'<{tag}>')
                end = xml.find(f'</{tag}>')
                if start > len(f'<{tag}>') - 1 and end > start:
                    return xml[start:end].strip()
        except Exception:
            pass
        return None

    def _generate_signal(self, symbol: str, purchases: List[InsiderTransaction]) -> Optional[Signal]:
        """Generate a buy signal from insider purchases"""
        if not purchases:
            return None

        # Aggregate purchase data
        total_value = sum(t.total_value for t in purchases)
        total_shares = sum(t.shares for t in purchases)
        avg_price = total_value / total_shares if total_shares > 0 else 0
        num_insiders = len(set(t.insider_name for t in purchases))

        # Score the insider buying
        # Higher value = more conviction
        # Multiple insiders = even stronger
        # C-suite buying = strongest signal
        confidence = 0.60

        if total_value > 100_000:
            confidence += 0.05
        if total_value > 500_000:
            confidence += 0.05
        if total_value > 1_000_000:
            confidence += 0.05
        if num_insiders > 1:
            confidence += 0.05  # Multiple insiders buying = cluster
        if num_insiders > 3:
            confidence += 0.05

        # C-suite titles get bonus
        c_suite_titles = ['CEO', 'CFO', 'COO', 'CTO', 'President', 'Chairman']
        has_csuite = any(
            any(title.lower() in t.insider_title.lower() for title in c_suite_titles)
            for t in purchases
        )
        if has_csuite:
            confidence += 0.08

        confidence = min(confidence, 0.92)

        # Build insider details for the signal
        insider_details = []
        for t in purchases[:5]:  # Top 5
            insider_details.append(
                f"{t.insider_name} ({t.insider_title}): "
                f"{t.shares:,.0f} shares @ ${t.price:.2f} = ${t.total_value:,.0f}"
            )

        # Use average purchase price as reference
        entry = avg_price
        # Conservative targets for insider-driven trades
        stop_loss = entry * 0.92  # 8% stop
        target = entry * 1.20  # 20% target (insiders typically see 6-12 month horizon)

        rr_ratio = (target - entry) / (entry - stop_loss) if entry > stop_loss else 0

        return Signal(
            symbol=symbol,
            market_type=MarketType.EQUITY,
            signal_type=SignalType.BUY,
            confidence=confidence,
            entry_price=entry,
            target_price=target,
            stop_loss=stop_loss,
            risk_reward_ratio=rr_ratio,
            source="edgar_insider_buying",
            metadata={
                'strategy': 'insider_buying',
                'total_purchase_value': total_value,
                'total_shares': total_shares,
                'num_insiders': num_insiders,
                'has_csuite': has_csuite,
                'insider_details': insider_details,
                'filing_dates': [t.date_filed.isoformat() for t in purchases]
            }
        )

    async def _broadcast_signal(self, signal: Signal) -> None:
        """Send signal to coordinator"""
        await self.send_message(
            target='coordinator',
            msg_type='new_signal',
            payload={
                'symbol': signal.symbol,
                'market_type': signal.market_type.value,
                'signal_type': signal.signal_type.value,
                'confidence': signal.confidence,
                'entry_price': signal.entry_price,
                'target_price': signal.target_price,
                'stop_loss': signal.stop_loss,
                'risk_reward_ratio': signal.risk_reward_ratio,
                'source': signal.source,
                'timestamp': signal.timestamp.isoformat(),
                'metadata': signal.metadata
            },
            priority=2  # High priority - insider buying is actionable
        )

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming messages"""
        if message.msg_type == 'update_watchlist':
            new_symbols = message.payload.get('symbols', [])
            self.watchlist = [s for s in new_symbols if s in TICKER_TO_CIK]
            logger.info(f"[EdgarInsider] Watchlist updated: {len(self.watchlist)} symbols")

        elif message.msg_type == 'force_scan':
            self.last_scan = None

    def get_status(self) -> Dict[str, Any]:
        """Get scanner status"""
        return {
            'name': self.name,
            'state': self.state.value,
            'last_scan': self.last_scan.isoformat() if self.last_scan else None,
            'watchlist_size': len(self.watchlist),
            'filings_processed': len(self.seen_filings),
            'metrics': self.metrics
        }

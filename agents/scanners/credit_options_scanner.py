"""
Credit Options Scanner for Credit Catalyst

Maps credit deterioration signals to tradeable options positions.
Integrates with situation classifier to select appropriate strategy:
- Playbook A (aggressive sponsor): Straddles or avoid
- Playbook B (maturity wall): Puts likely work

Focus on XO S44 names with liquid equity options.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import pandas as pd
import numpy as np
from pathlib import Path
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not installed - options data limited")

from core.data_cache import get_data_cache
from .base_scanner import BaseScanner
from core.models import Signal, MarketType, SignalType
from analyzers.situation_classifier import SituationClassifier


@dataclass
class OptionsOpportunity:
    """Represents a credit-driven options opportunity."""
    company: str
    ticker: str
    exchange: str
    playbook: str
    strategy: str  # 'puts', 'straddle', 'avoid', 'monitor'

    # Credit context
    sponsor: Optional[str]
    sponsor_aggression: int
    maturity_risk: str
    catalyst: str

    # Options data (when available)
    stock_price: Optional[float] = None
    iv_percentile: Optional[float] = None
    iv_rank: Optional[float] = None
    atm_iv: Optional[float] = None

    # Recommended trade
    recommended_strike: Optional[float] = None
    recommended_expiry: Optional[str] = None
    recommended_premium: Optional[float] = None
    max_position_size: Optional[float] = None

    # Scoring
    edge_score: float = 0.0
    timing_score: float = 0.0
    conviction: str = "low"  # low, medium, high

    notes: List[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class CreditOptionsScanner(BaseScanner):
    """
    Scans credit situations for options opportunities.

    Maps XO S44 companies to tradeable tickers and identifies
    optimal options strategies based on playbook classification.

    THE EDGE: Credit signals precede equity repricing by weeks/months.
    """

    # XO S44 companies with tradeable equity options
    # Format: company_name -> {ticker, exchange, options_liquidity}
    TRADEABLE_TICKERS = {
        # US-listed with liquid options
        "Nokia Oyj": {"ticker": "NOK", "exchange": "NYSE", "liquidity": "high"},
        "Grifols, S.A.": {"ticker": "GRFS", "exchange": "NASDAQ", "liquidity": "medium"},
        "SoftBank Group Corp.": {"ticker": "SFTBY", "exchange": "OTC", "liquidity": "low"},

        # European listed - need IBKR for options
        "Renault": {"ticker": "RNO.PA", "exchange": "Euronext Paris", "liquidity": "high"},
        "Air France - KLM": {"ticker": "AF.PA", "exchange": "Euronext Paris", "liquidity": "medium"},
        "Telecom Italia S.p.A.": {"ticker": "TIT.MI", "exchange": "Borsa Italiana", "liquidity": "medium"},
        "ThyssenKrupp AG": {"ticker": "TKA.DE", "exchange": "Xetra", "liquidity": "medium"},
        "Volvo Car AB": {"ticker": "VOLCAR-B.ST", "exchange": "Nasdaq Stockholm", "liquidity": "medium"},
        "Schaeffler AG": {"ticker": "SHA.DE", "exchange": "Xetra", "liquidity": "medium"},
        "LANXESS Aktiengesellschaft": {"ticker": "LXS.DE", "exchange": "Xetra", "liquidity": "medium"},
        "Valeo": {"ticker": "FR.PA", "exchange": "Euronext Paris", "liquidity": "medium"},
        "Forvia": {"ticker": "FRVIA.PA", "exchange": "Euronext Paris", "liquidity": "medium"},
        "Worldline": {"ticker": "WLN.PA", "exchange": "Euronext Paris", "liquidity": "medium"},
        "Nexi S.p.A.": {"ticker": "NEXI.MI", "exchange": "Borsa Italiana", "liquidity": "medium"},
        "Lagardère S.A.": {"ticker": "MMB.PA", "exchange": "Euronext Paris", "liquidity": "low"},
        "Eutelsat S.A.": {"ticker": "ETL.PA", "exchange": "Euronext Paris", "liquidity": "low"},
        "CMA CGM": {"ticker": "CMA.PA", "exchange": "Euronext Paris", "liquidity": "low"},
        "Hapag-Lloyd Aktiengesellschaft": {"ticker": "HLAG.DE", "exchange": "Xetra", "liquidity": "low"},
        "Rexel": {"ticker": "RXL.PA", "exchange": "Euronext Paris", "liquidity": "low"},

        # Swedish - Nasdaq Stockholm
        "Samhallsbyggnadsbolaget i Norden AB (SBB)": {"ticker": "SBB-B.ST", "exchange": "Nasdaq Stockholm", "liquidity": "medium"},
        "Verisure Midholding AB": {"ticker": "VERIS.ST", "exchange": "Nasdaq Stockholm", "liquidity": "medium"},

        # UK listed
        "Playtech plc": {"ticker": "PTEC.L", "exchange": "LSE", "liquidity": "low"},
        "International Game Technology plc": {"ticker": "IGT", "exchange": "NYSE", "liquidity": "medium"},

        # Czech
        "CPI Property Group": {"ticker": "CPI.PR", "exchange": "Prague", "liquidity": "low"},
    }

    # Credit-relevant catalysts to watch
    CATALYST_KEYWORDS = {
        "earnings": ["Q1", "Q2", "Q3", "Q4", "results", "earnings", "guidance"],
        "refinancing": ["refinanc", "maturity", "extension", "amendment"],
        "rating": ["downgrade", "upgrade", "outlook", "review", "watch"],
        "restructuring": ["restructur", "covenant", "waiver", "default"],
        "m&a": ["acquisition", "merger", "takeover", "bid", "offer"],
        "sponsor": ["dividend", "distribution", "recap", "transfer"],
    }

    def __init__(self, data_path: str = None):
        super().__init__(
            name="CreditOptionsScanner",
            market_type=MarketType.OPTIONS,
            config={'scan_interval': 300}  # 5 minutes - credit moves slowly
        )
        self.classifier = SituationClassifier(data_path)
        self.iv_history: Dict[str, List[float]] = {}  # Cache for IV percentile calc

    async def get_universe(self) -> List[str]:
        """Get list of tickers to scan - XO S44 companies with tradeable options"""
        return [info["ticker"] for info in self.TRADEABLE_TICKERS.values()]

    async def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Not used - this scanner uses scan_all_opportunities() for credit-driven logic"""
        return None

    async def analyze(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Not used - this scanner generates OptionsOpportunity objects instead"""
        return None

    def get_tradeable_companies(self) -> List[Dict]:
        """Get list of XO S44 companies with tradeable options."""
        tradeable = []
        for company, info in self.TRADEABLE_TICKERS.items():
            classification = self.classifier.classify(company)
            tradeable.append({
                "company": company,
                "ticker": info["ticker"],
                "exchange": info["exchange"],
                "liquidity": info["liquidity"],
                "playbook": classification.get("playbook"),
                "strategy": classification.get("trading_implications", {}).get("options_approach"),
                "sponsor": classification.get("sponsor"),
                "aggression": classification.get("sponsor_aggression"),
                "maturity_risk": classification.get("maturity_risk"),
            })
        return tradeable

    async def get_iv_data(self, ticker: str) -> Dict[str, float]:
        """
        Get implied volatility data for a ticker.
        Returns IV percentile, IV rank, and current ATM IV.
        """
        if not YFINANCE_AVAILABLE:
            return {"iv_percentile": None, "iv_rank": None, "atm_iv": None}

        try:
            # Get current price via shared cache
            cache = get_data_cache()
            hist = await cache.get_history(ticker, 'equity', '5d', '1d')

            # Use yf.Ticker for options chain access (not cached)
            stock = yf.Ticker(ticker)

            # Get options chain for nearest expiry
            expirations = stock.options
            if not expirations:
                return {"iv_percentile": None, "iv_rank": None, "atm_iv": None}

            # Find expiry 30-45 days out
            today = datetime.now().date()
            target_expiry = None
            for exp in expirations:
                exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
                days_to_exp = (exp_date - today).days
                if 20 <= days_to_exp <= 60:
                    target_expiry = exp
                    break

            if not target_expiry:
                target_expiry = expirations[0]

            chain = stock.option_chain(target_expiry)

            # Get current price from cached data (fetched above)
            if hist is None or hist.empty:
                return {"iv_percentile": None, "iv_rank": None, "atm_iv": None}
            current_price = hist['close'].iloc[-1]

            # Get ATM options
            calls = chain.calls
            puts = chain.puts

            # Find ATM strike
            atm_strike = calls.iloc[(calls['strike'] - current_price).abs().argmin()]['strike']

            # Get ATM IV (average of call and put)
            atm_call_iv = calls[calls['strike'] == atm_strike]['impliedVolatility'].values
            atm_put_iv = puts[puts['strike'] == atm_strike]['impliedVolatility'].values

            if len(atm_call_iv) > 0 and len(atm_put_iv) > 0:
                atm_iv = (atm_call_iv[0] + atm_put_iv[0]) / 2 * 100
            elif len(atm_call_iv) > 0:
                atm_iv = atm_call_iv[0] * 100
            elif len(atm_put_iv) > 0:
                atm_iv = atm_put_iv[0] * 100
            else:
                atm_iv = None

            # Calculate IV percentile using historical IV from cache (1y data)
            hist_1y = await cache.get_history(ticker, 'equity', '1y', '1d')
            if hist_1y is not None and len(hist_1y) > 20:
                # Estimate historical volatility as proxy
                returns = hist_1y['close'].pct_change().dropna()
                hv_20 = returns[-20:].std() * np.sqrt(252) * 100
                hv_60 = returns[-60:].std() * np.sqrt(252) * 100 if len(returns) >= 60 else hv_20
                hv_252 = returns.std() * np.sqrt(252) * 100

                # Store for IV percentile calculation
                if ticker not in self.iv_history:
                    self.iv_history[ticker] = []

                if atm_iv:
                    self.iv_history[ticker].append(atm_iv)
                    # Keep last 252 values
                    self.iv_history[ticker] = self.iv_history[ticker][-252:]

                    iv_values = self.iv_history[ticker]
                    if len(iv_values) > 20:
                        iv_percentile = (sum(1 for v in iv_values if v < atm_iv) / len(iv_values)) * 100
                        iv_min = min(iv_values)
                        iv_max = max(iv_values)
                        iv_rank = ((atm_iv - iv_min) / (iv_max - iv_min) * 100) if iv_max > iv_min else 50
                    else:
                        # Use HV comparison as fallback
                        iv_percentile = 50 if not atm_iv else min(100, max(0, (atm_iv / hv_252) * 50))
                        iv_rank = iv_percentile
                else:
                    iv_percentile = None
                    iv_rank = None
            else:
                iv_percentile = None
                iv_rank = None

            return {
                "iv_percentile": round(iv_percentile, 1) if iv_percentile else None,
                "iv_rank": round(iv_rank, 1) if iv_rank else None,
                "atm_iv": round(atm_iv, 1) if atm_iv else None,
                "stock_price": round(current_price, 2),
            }

        except (ConnectionError, ValueError, KeyError, IndexError) as e:
            logger.debug(f"Error getting IV data for {ticker}: {e}")
            return {"iv_percentile": None, "iv_rank": None, "atm_iv": None}

    def calculate_edge_score(
        self,
        playbook: str,
        maturity_risk: str,
        sponsor_aggression: int,
        iv_percentile: Optional[float],
        catalyst_present: bool
    ) -> float:
        """
        Calculate edge score for an options opportunity.

        Higher score = higher conviction opportunity.
        Range: 0-100
        """
        score = 0.0

        # Playbook contribution (0-30)
        if playbook == "B":
            score += 25  # Maturity wall = more predictable
        elif playbook == "A":
            score += 10  # Aggressive sponsor = harder to time
        elif playbook == "MIXED":
            score += 15

        # Maturity risk (0-25)
        maturity_scores = {
            "very_high": 25,
            "high": 20,
            "medium": 10,
            "low": 0
        }
        score += maturity_scores.get(maturity_risk, 5)

        # Sponsor aggression - inverse for puts (0-15)
        # Low aggression = more predictable deterioration
        if sponsor_aggression:
            if playbook == "B":
                score += max(0, 15 - sponsor_aggression)  # Lower aggression better for puts
            else:
                score += sponsor_aggression  # Higher aggression = more binary

        # IV percentile contribution (0-20)
        # For puts: low IV = cheap options = good
        # For straddles: low IV = cheap vol = good
        if iv_percentile is not None:
            if iv_percentile < 25:
                score += 20  # Very cheap vol
            elif iv_percentile < 50:
                score += 15
            elif iv_percentile < 75:
                score += 5
            # High IV = expensive, reduce score
            else:
                score -= 5

        # Catalyst presence (0-10)
        if catalyst_present:
            score += 10

        return min(100, max(0, score))

    def get_timing_score(
        self,
        iv_percentile: Optional[float],
        days_to_catalyst: Optional[int]
    ) -> float:
        """
        Calculate timing score - is now the right time to enter?

        Range: 0-100
        """
        score = 50.0  # Neutral starting point

        # IV timing
        if iv_percentile is not None:
            if iv_percentile < 20:
                score += 30  # Great time - vol is cheap
            elif iv_percentile < 35:
                score += 20
            elif iv_percentile < 50:
                score += 10
            elif iv_percentile > 80:
                score -= 20  # Bad time - vol expensive
            elif iv_percentile > 65:
                score -= 10

        # Catalyst timing
        if days_to_catalyst is not None:
            if 14 <= days_to_catalyst <= 45:
                score += 20  # Sweet spot
            elif 7 <= days_to_catalyst <= 60:
                score += 10
            elif days_to_catalyst < 7:
                score -= 10  # Too close - theta burn

        return min(100, max(0, score))

    async def scan_opportunities(self) -> List[OptionsOpportunity]:
        """
        Scan all tradeable XO S44 companies for options opportunities.
        Returns list sorted by edge score.
        """
        opportunities = []

        tradeable = self.get_tradeable_companies()

        for company_info in tradeable:
            company = company_info["company"]
            ticker = company_info["ticker"]
            playbook = company_info["playbook"]

            # Skip low-risk and unknown
            if playbook in ["LOW_RISK", "UNKNOWN"]:
                continue

            # Get IV data for US tickers (yfinance supports these)
            iv_data = {}
            if company_info["exchange"] in ["NYSE", "NASDAQ"]:
                iv_data = await self.get_iv_data(ticker)

            # Determine strategy based on playbook
            if playbook == "A":
                strategy = "straddle"
                notes = [
                    "Aggressive sponsor - timing treacherous",
                    "Consider straddle for binary outcome",
                    "May be better to avoid"
                ]
            elif playbook == "B":
                strategy = "puts"
                notes = [
                    "Maturity wall stress - puts likely work",
                    "Timing tied to maturity/rating actions",
                    "Look for catalyst timeline"
                ]
            elif playbook == "MIXED":
                strategy = "monitor"
                notes = [
                    "Mixed signals - requires careful analysis",
                    "Monitor for clearer signals"
                ]
            elif playbook == "MONITOR":
                strategy = "monitor"
                notes = ["Watch for deterioration signals"]
            else:
                strategy = "avoid"
                notes = ["Insufficient data"]

            # Get catalyst info
            classification = self.classifier.classify(company)
            maturity_notes = classification.get("maturity_notes", "")
            catalyst = maturity_notes if maturity_notes else "Monitor for announcements"

            # Calculate scores
            edge_score = self.calculate_edge_score(
                playbook=playbook,
                maturity_risk=company_info["maturity_risk"],
                sponsor_aggression=company_info["aggression"] or 0,
                iv_percentile=iv_data.get("iv_percentile"),
                catalyst_present=bool(maturity_notes)
            )

            timing_score = self.get_timing_score(
                iv_percentile=iv_data.get("iv_percentile"),
                days_to_catalyst=None  # Would need calendar integration
            )

            # Determine conviction
            if edge_score >= 70 and timing_score >= 60:
                conviction = "high"
            elif edge_score >= 50 and timing_score >= 40:
                conviction = "medium"
            else:
                conviction = "low"

            opportunity = OptionsOpportunity(
                company=company,
                ticker=ticker,
                exchange=company_info["exchange"],
                playbook=playbook,
                strategy=strategy,
                sponsor=company_info["sponsor"],
                sponsor_aggression=company_info["aggression"] or 0,
                maturity_risk=company_info["maturity_risk"] or "unknown",
                catalyst=catalyst,
                stock_price=iv_data.get("stock_price"),
                iv_percentile=iv_data.get("iv_percentile"),
                iv_rank=iv_data.get("iv_rank"),
                atm_iv=iv_data.get("atm_iv"),
                edge_score=edge_score,
                timing_score=timing_score,
                conviction=conviction,
                notes=notes
            )

            opportunities.append(opportunity)

        # Sort by edge score descending
        opportunities.sort(key=lambda x: x.edge_score, reverse=True)

        return opportunities

    def get_high_conviction_opportunities(
        self,
        opportunities: List[OptionsOpportunity],
        min_edge: float = 60,
        min_timing: float = 50
    ) -> List[OptionsOpportunity]:
        """Filter for high conviction opportunities."""
        return [
            opp for opp in opportunities
            if opp.edge_score >= min_edge
            and opp.timing_score >= min_timing
            and opp.strategy in ["puts", "straddle"]
        ]

    def format_opportunity(self, opp: OptionsOpportunity) -> str:
        """Format opportunity for display."""
        lines = [
            f"\n{'='*60}",
            f"Company: {opp.company}",
            f"Ticker: {opp.ticker} ({opp.exchange})",
            f"Playbook: {opp.playbook} | Strategy: {opp.strategy.upper()}",
            f"{'='*60}",
            f"",
            f"CREDIT CONTEXT:",
            f"  Sponsor: {opp.sponsor or 'N/A'} (aggression: {opp.sponsor_aggression}/10)",
            f"  Maturity Risk: {opp.maturity_risk}",
            f"  Catalyst: {opp.catalyst}",
            f"",
        ]

        if opp.stock_price:
            lines.extend([
                f"OPTIONS DATA:",
                f"  Stock Price: ${opp.stock_price:.2f}",
                f"  IV Percentile: {opp.iv_percentile:.1f}%" if opp.iv_percentile else "  IV Percentile: N/A",
                f"  IV Rank: {opp.iv_rank:.1f}%" if opp.iv_rank else "  IV Rank: N/A",
                f"  ATM IV: {opp.atm_iv:.1f}%" if opp.atm_iv else "  ATM IV: N/A",
                f"",
            ])

        lines.extend([
            f"SCORING:",
            f"  Edge Score: {opp.edge_score:.0f}/100",
            f"  Timing Score: {opp.timing_score:.0f}/100",
            f"  Conviction: {opp.conviction.upper()}",
            f"",
            f"NOTES:",
        ])

        for note in opp.notes:
            lines.append(f"  - {note}")

        return "\n".join(lines)


async def main():
    """Test the credit options scanner."""
    print("=" * 60)
    print("CREDIT OPTIONS SCANNER - TEST")
    print("=" * 60)

    scanner = CreditOptionsScanner()

    # Get tradeable companies
    print("\n--- Tradeable XO S44 Companies ---")
    tradeable = scanner.get_tradeable_companies()
    for t in tradeable[:10]:
        print(f"  {t['ticker']:12} | {t['playbook']:8} | {t['strategy']:12} | {t['company'][:30]}")
    print(f"  ... and {len(tradeable) - 10} more")

    # Scan opportunities
    print("\n--- Scanning for Opportunities ---")
    opportunities = await scanner.scan_opportunities()

    # Show top opportunities
    print("\n--- Top Opportunities by Edge Score ---")
    for opp in opportunities[:5]:
        print(scanner.format_opportunity(opp))

    # High conviction only
    print("\n--- High Conviction Opportunities ---")
    high_conv = scanner.get_high_conviction_opportunities(opportunities)
    if high_conv:
        for opp in high_conv:
            print(f"  {opp.ticker}: {opp.strategy} | Edge: {opp.edge_score:.0f} | Timing: {opp.timing_score:.0f}")
    else:
        print("  No high conviction opportunities currently")

    # Summary
    print("\n--- Summary ---")
    by_strategy = {}
    for opp in opportunities:
        by_strategy[opp.strategy] = by_strategy.get(opp.strategy, 0) + 1

    for strategy, count in by_strategy.items():
        print(f"  {strategy}: {count} companies")


if __name__ == "__main__":
    asyncio.run(main())

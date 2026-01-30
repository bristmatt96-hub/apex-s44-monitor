"""
Product Discovery Scanner

Scans the market to discover NEW instruments that fit our trading philosophy.

OUR EDGE: Behavioral inefficiencies where algorithms CAN'T compete

WHAT WE'RE LOOKING FOR:
1. HIGH RETAIL ACTIVITY - Stocks retail traders love (options volume, social buzz)
2. EMOTIONAL SECTORS - Biotech, meme stocks, speculative names
3. OVERREACTION PRONE - Stocks that move 5-10% on news then revert
4. INSTITUTIONAL BLIND SPOTS - Smaller caps where big algos can't play
5. HIGH OPTIONS ACTIVITY - Where sentiment can be measured via put/call

WHAT WE AVOID:
- Low volatility / boring stocks (no edge)
- Heavily arbitraged ETFs (SPY, QQQ internals)
- Stocks with no options (can't measure sentiment)
- Mega-caps dominated by quants (AAPL, MSFT during normal times)

PHILOSOPHY:
"Fish where the fish are" - find instruments where retail emotion creates
predictable patterns we can exploit.
"""
from dataclasses import dataclass
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta
from loguru import logger
import asyncio

try:
    import yfinance as yf
    import numpy as np
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from agents.brain.market_brain import (
    Inefficiency, InefficiencyType, EdgeReason
)

# Try to import Telegram notifier
try:
    from utils.telegram_notifier import get_notifier
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


@dataclass
class ProductCandidate:
    """A potential product that fits our trading style"""
    symbol: str
    name: str
    sector: str

    # Suitability scores (0-1)
    retail_activity_score: float  # How much retail trades this
    volatility_score: float       # Does it move enough?
    options_liquidity_score: float  # Can we measure sentiment?
    overreaction_score: float     # Does it overreact to news?
    institutional_blind_spot: float  # Are big algos absent?

    # Overall fit score
    edge_fit_score: float

    # Reasoning
    why_suitable: List[str]
    why_not: List[str]

    # Market data
    avg_volume: float
    options_volume: float
    volatility_30d: float
    market_cap: float


@dataclass
class SectorOpportunity:
    """A sector showing behavioral patterns"""
    sector: str
    opportunity_type: str  # "PANIC", "EUPHORIA", "ROTATION"
    top_candidates: List[str]
    reasoning: str


class ProductDiscoveryScanner:
    """
    Discovers new products that match our behavioral edge philosophy.

    Key insight: We want to trade where RETAIL EMOTION creates patterns,
    not where sophisticated algorithms dominate.
    """

    # Sectors we like (emotional, retail-heavy)
    FAVORABLE_SECTORS = {
        'biotech': 1.2,      # High emotion, FDA binary events
        'cannabis': 1.1,     # Retail favorites
        'ev': 1.1,           # Retail speculation
        'tech_growth': 1.0,  # Retail loves growth stories
        'meme': 1.3,         # Pure retail emotion
        'spac': 1.0,         # Speculation plays
        'crypto_adjacent': 0.9,  # MSTR, COIN etc
        'retail_favorites': 1.2,  # What WSB loves
        'retail_macro': 1.15,    # Gold/leveraged ETFs - fear/greed trades
    }

    # Sectors we avoid (algo-dominated or boring)
    UNFAVORABLE_SECTORS = {
        'utilities': 0.3,    # Too boring
        'reits': 0.4,        # Income focused
        'consumer_staples': 0.5,  # Low vol
        'mega_cap_tech': 0.6,  # Too efficient
    }

    # BLACKLIST - Only things with NO behavioral edge
    # Keep it minimal - many "macro" products actually have retail patterns
    BLACKLIST = {
        # Bonds / Fixed income - truly Fed/rates driven, no retail emotion
        'TLT', 'TBT', 'IEF', 'SHY', 'BND', 'AGG', 'LQD', 'HYG', 'JNK',
        # Currencies / Forex - algo dominated, no retail edge
        'UUP', 'FXE', 'FXY', 'FXB',
        # VIX products - we use VIX as indicator, dangerous to trade directly
        'VXX', 'UVXY', 'SVXY', 'VIXY',
        # Agriculture - truly commodity/weather driven
        'DBA', 'CORN', 'WEAT', 'SOYB',
    }

    # RETAIL FAVORITES - Products that LOOK macro but are actually retail-heavy
    # These DO have behavioral edges despite being ETFs
    RETAIL_MACRO_PLAYS = {
        # Gold/Silver - retail piles in during fear (emotional "safe haven")
        'GLD', 'SLV', 'GDX', 'GDXJ',
        # Leveraged ETFs - pure retail speculation, institutions don't hold these
        'TQQQ', 'SQQQ', 'SPXU', 'SPXS', 'SOXL', 'SOXS',
        # Oil - retail trades this on geopolitical headlines
        'USO', 'UCO',
    }

    # Universe to scan (expand this as needed)
    SCAN_UNIVERSE = {
        # High retail interest stocks
        'retail_favorites': [
            'PLTR', 'SOFI', 'HOOD', 'RIVN', 'LCID', 'NIO', 'PLUG', 'SPCE',
            'DKNG', 'PENN', 'CHPT', 'CLOV', 'WISH', 'BB', 'NOK', 'BBBY',
            'AMC', 'GME', 'MULN', 'FFIE', 'SNDL', 'TLRY', 'ACB', 'CGC'
        ],
        # Biotech (FDA catalysts)
        'biotech': [
            'MRNA', 'BNTX', 'NVAX', 'SAVA', 'SRPT', 'BMRN', 'ALNY',
            'CRSP', 'EDIT', 'NTLA', 'BEAM', 'IONS', 'RARE', 'REGN'
        ],
        # Growth tech (narrative driven)
        'growth_tech': [
            'SNOW', 'NET', 'DDOG', 'MDB', 'CRWD', 'ZS', 'OKTA',
            'DOCN', 'PATH', 'AI', 'PLTR', 'U', 'RBLX', 'ABNB'
        ],
        # EV / Clean energy (retail speculation)
        'ev_clean': [
            'TSLA', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'FSR',
            'PLUG', 'FCEL', 'BE', 'ENPH', 'SEDG', 'RUN', 'NOVA'
        ],
        # Crypto adjacent
        'crypto_adjacent': [
            'MSTR', 'COIN', 'MARA', 'RIOT', 'HUT', 'BITF', 'CLSK'
        ],
        # Recent IPOs / SPACs (narrative plays)
        'recent_ipos': [
            'ARM', 'BIRK', 'CART', 'KVYO', 'TOST', 'DOCS', 'DUOL'
        ],
        # Options-heavy names (high put/call volume)
        'options_heavy': [
            'SPY', 'QQQ', 'IWM', 'NVDA', 'AMD', 'AAPL', 'TSLA',
            'META', 'AMZN', 'GOOGL', 'MSFT', 'NFLX'
        ],
        # Retail macro plays - LOOK like macro but retail-heavy
        # Gold/silver = fear trade, leveraged ETFs = pure speculation
        'retail_macro': [
            'GLD', 'SLV', 'GDX', 'GDXJ',  # Precious metals (fear trade)
            'TQQQ', 'SQQQ',  # Leveraged Nasdaq (retail day trading)
            'SPXU', 'SPXS',  # Leveraged S&P (retail speculation)
            'SOXL', 'SOXS',  # Leveraged semiconductors
            'USO',  # Oil (geopolitical headlines)
        ]
    }

    def __init__(self, send_telegram: bool = True):
        self.discovered_products: Dict[str, ProductCandidate] = {}
        self.sector_opportunities: List[SectorOpportunity] = []
        self.last_full_scan = None
        self.send_telegram = send_telegram

        # Already tracked symbols (don't re-recommend)
        self.already_tracked: Set[str] = set()

        # Track what we've already notified about (avoid spam)
        self.notified_symbols: Set[str] = set()

    async def scan(self) -> List[Inefficiency]:
        """
        Scan for new products that fit our edge.
        Returns inefficiencies representing discovery opportunities.
        """
        if not YFINANCE_AVAILABLE:
            return []

        inefficiencies = []

        # Only do full scan periodically (expensive)
        if self._should_full_scan():
            await self._run_full_discovery()

        # Convert top discoveries to inefficiencies
        top_candidates = self._get_top_candidates(limit=5)

        for candidate in top_candidates:
            ineff = self._create_discovery_inefficiency(candidate)
            if ineff:
                inefficiencies.append(ineff)

        # Also add sector opportunities
        for sector_opp in self.sector_opportunities[:3]:
            ineff = self._create_sector_inefficiency(sector_opp)
            if ineff:
                inefficiencies.append(ineff)

        return inefficiencies

    def _should_full_scan(self) -> bool:
        """Full scan is expensive - only do every few hours"""
        if self.last_full_scan is None:
            return True
        hours_since = (datetime.now() - self.last_full_scan).total_seconds() / 3600
        return hours_since > 4  # Every 4 hours

    async def _run_full_discovery(self) -> None:
        """Run full product discovery scan"""
        logger.info("🔍 Running full product discovery scan...")

        self.discovered_products.clear()
        self.sector_opportunities.clear()

        # Scan each category
        for category, symbols in self.SCAN_UNIVERSE.items():
            for symbol in symbols:
                if symbol in self.already_tracked:
                    continue

                try:
                    candidate = await self._analyze_product(symbol, category)
                    if candidate and candidate.edge_fit_score > 0.5:
                        self.discovered_products[symbol] = candidate
                except Exception as e:
                    logger.debug(f"Error analyzing {symbol}: {e}")

            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)

        # Identify sector opportunities
        self._identify_sector_opportunities()

        self.last_full_scan = datetime.now()
        logger.info(f"🔍 Discovery complete: {len(self.discovered_products)} candidates found")

        # Send Telegram notification for top discoveries
        if self.send_telegram and self.discovered_products:
            await self._send_telegram_discovery()

    async def _analyze_product(self, symbol: str, category: str) -> Optional[ProductCandidate]:
        """Analyze a single product for edge suitability"""
        # Skip blacklisted symbols (commodities, bonds, macro - no behavioral edge)
        if symbol in self.BLACKLIST:
            logger.debug(f"Skipping {symbol} - blacklisted (no behavioral edge)")
            return None

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            hist = ticker.history(period="3mo")

            if len(hist) < 20:
                return None

            # Get basic info
            name = info.get('shortName', symbol)
            sector = info.get('sector', category)
            market_cap = info.get('marketCap', 0)
            avg_volume = info.get('averageVolume', 0)

            # Calculate volatility
            returns = hist['Close'].pct_change().dropna()
            volatility = returns.std() * np.sqrt(252) if len(returns) > 0 else 0

            # Get options data
            options_volume = 0
            options_liquidity = 0
            try:
                expirations = ticker.options
                if expirations:
                    chain = ticker.option_chain(expirations[0])
                    options_volume = chain.calls['volume'].sum() + chain.puts['volume'].sum()
                    options_liquidity = min(1.0, options_volume / 10000)  # Normalize
            except Exception:
                pass

            # Score components
            retail_score = self._score_retail_activity(symbol, avg_volume, options_volume, category)
            vol_score = self._score_volatility(volatility)
            options_score = options_liquidity
            overreaction_score = self._score_overreaction(hist)
            blind_spot_score = self._score_institutional_blind_spot(market_cap, avg_volume)

            # Category bonus
            category_multiplier = self.FAVORABLE_SECTORS.get(category, 1.0)

            # Combined score
            edge_fit = (
                retail_score * 0.25 +
                vol_score * 0.20 +
                options_score * 0.20 +
                overreaction_score * 0.20 +
                blind_spot_score * 0.15
            ) * category_multiplier

            # Build reasoning
            why_suitable = []
            why_not = []

            if retail_score > 0.7:
                why_suitable.append("High retail activity")
            if vol_score > 0.7:
                why_suitable.append(f"Good volatility ({volatility:.0%} annualized)")
            if options_score > 0.7:
                why_suitable.append("Liquid options market")
            if overreaction_score > 0.7:
                why_suitable.append("Tends to overreact (reversion opportunity)")
            if blind_spot_score > 0.7:
                why_suitable.append("Institutional blind spot")

            if vol_score < 0.3:
                why_not.append("Too low volatility")
            if options_score < 0.3:
                why_not.append("Poor options liquidity")
            if market_cap > 500e9:
                why_not.append("Mega-cap (too efficient)")

            return ProductCandidate(
                symbol=symbol,
                name=name,
                sector=sector,
                retail_activity_score=retail_score,
                volatility_score=vol_score,
                options_liquidity_score=options_score,
                overreaction_score=overreaction_score,
                institutional_blind_spot=blind_spot_score,
                edge_fit_score=edge_fit,
                why_suitable=why_suitable,
                why_not=why_not,
                avg_volume=avg_volume,
                options_volume=options_volume,
                volatility_30d=volatility,
                market_cap=market_cap
            )

        except Exception as e:
            logger.debug(f"Error analyzing {symbol}: {e}")
            return None

    def _score_retail_activity(
        self,
        symbol: str,
        avg_volume: float,
        options_volume: float,
        category: str
    ) -> float:
        """Score how much retail trades this stock"""
        score = 0.0

        # Known retail favorites get bonus
        if symbol in ['GME', 'AMC', 'PLTR', 'SOFI', 'HOOD', 'RIVN', 'NIO']:
            score += 0.4

        # High options volume relative to stock volume = retail
        if avg_volume > 0:
            options_ratio = options_volume / avg_volume
            if options_ratio > 0.5:
                score += 0.3
            elif options_ratio > 0.2:
                score += 0.2

        # Category bonus
        if category in ['retail_favorites', 'meme', 'ev_clean']:
            score += 0.3

        return min(1.0, score)

    def _score_volatility(self, volatility: float) -> float:
        """Score volatility (we want 30-80% annualized)"""
        if volatility < 0.15:
            return 0.2  # Too boring
        elif volatility < 0.30:
            return 0.5  # Acceptable
        elif volatility < 0.50:
            return 0.9  # Sweet spot
        elif volatility < 0.80:
            return 1.0  # High but tradeable
        else:
            return 0.7  # Very high - risky but opportunity

    def _score_overreaction(self, hist) -> float:
        """Score tendency to overreact (mean reversion opportunity)"""
        try:
            returns = hist['Close'].pct_change().dropna()

            # Count big moves (>3%) that reversed next day
            big_moves = returns[abs(returns) > 0.03]
            if len(big_moves) < 3:
                return 0.5  # Not enough data

            reversals = 0
            for i, (idx, ret) in enumerate(big_moves.items()):
                # Get next day return
                pos = returns.index.get_loc(idx)
                if pos + 1 < len(returns):
                    next_ret = returns.iloc[pos + 1]
                    # Reversal = opposite sign
                    if (ret > 0 and next_ret < 0) or (ret < 0 and next_ret > 0):
                        reversals += 1

            reversal_rate = reversals / len(big_moves)
            return min(1.0, reversal_rate * 1.5)  # Scale up

        except Exception:
            return 0.5

    def _score_institutional_blind_spot(self, market_cap: float, avg_volume: float) -> float:
        """Score whether institutions/algos are absent"""
        # Mega caps = heavily traded by algos
        if market_cap > 200e9:
            return 0.2
        elif market_cap > 50e9:
            return 0.4
        elif market_cap > 10e9:
            return 0.6
        elif market_cap > 2e9:
            return 0.8  # Sweet spot - liquid enough but not algo dominated
        elif market_cap > 500e6:
            return 0.9  # Small cap - less algo activity
        else:
            return 0.7  # Micro cap - might be too illiquid

    def _identify_sector_opportunities(self) -> None:
        """Identify sectors showing behavioral patterns"""
        # Group candidates by sector
        sector_candidates: Dict[str, List[ProductCandidate]] = {}
        for symbol, candidate in self.discovered_products.items():
            sector = candidate.sector
            if sector not in sector_candidates:
                sector_candidates[sector] = []
            sector_candidates[sector].append(candidate)

        # Look for sector-wide patterns
        for sector, candidates in sector_candidates.items():
            if len(candidates) < 2:
                continue

            # Average scores
            avg_retail = np.mean([c.retail_activity_score for c in candidates])
            avg_overreaction = np.mean([c.overreaction_score for c in candidates])

            # High retail + overreaction = opportunity
            if avg_retail > 0.6 and avg_overreaction > 0.6:
                top_symbols = [c.symbol for c in sorted(candidates, key=lambda x: x.edge_fit_score, reverse=True)[:5]]
                self.sector_opportunities.append(SectorOpportunity(
                    sector=sector,
                    opportunity_type="BEHAVIORAL_EDGE",
                    top_candidates=top_symbols,
                    reasoning=f"High retail activity ({avg_retail:.0%}) + overreaction tendency ({avg_overreaction:.0%})"
                ))

    def _get_top_candidates(self, limit: int = 10) -> List[ProductCandidate]:
        """Get top candidates by edge fit score"""
        sorted_candidates = sorted(
            self.discovered_products.values(),
            key=lambda x: x.edge_fit_score,
            reverse=True
        )
        return sorted_candidates[:limit]

    async def _send_telegram_discovery(self) -> None:
        """Send Telegram notification about discovered products"""
        if not TELEGRAM_AVAILABLE:
            logger.debug("Telegram not available for discovery notifications")
            return

        try:
            notifier = get_notifier()

            # Get top candidates we haven't notified about yet
            top = self._get_top_candidates(5)
            new_discoveries = [
                c for c in top
                if c.symbol not in self.notified_symbols and c.edge_fit_score > 0.6
            ]

            if not new_discoveries:
                return

            # Build message
            lines = ["🔍 *PRODUCT DISCOVERY*\n"]
            lines.append("New instruments matching our edge:\n")

            for candidate in new_discoveries:
                # Score bar
                score_pct = int(candidate.edge_fit_score * 100)

                lines.append(f"*{candidate.symbol}* - {candidate.name}")
                lines.append(f"  Edge Fit: {score_pct}%")

                # Top reasons (the key info)
                if candidate.why_suitable:
                    reasons = candidate.why_suitable[:3]
                    for reason in reasons:
                        lines.append(f"  ✓ {reason}")

                # Key stats
                if candidate.volatility_30d > 0:
                    lines.append(f"  📊 Vol: {candidate.volatility_30d:.0%} ann.")

                lines.append("")  # Spacing

                # Mark as notified
                self.notified_symbols.add(candidate.symbol)

            # Add philosophy reminder
            lines.append("_Fish where retail emotion creates patterns_")

            message = "\n".join(lines)

            await notifier.send_message(message)
            logger.info(f"📱 Sent Telegram: {len(new_discoveries)} product discoveries")

        except Exception as e:
            logger.debug(f"Error sending discovery Telegram: {e}")

    def format_telegram_message(self) -> str:
        """Format discovery results for Telegram (manual send)"""
        top = self._get_top_candidates(5)

        if not top:
            return "🔍 No products discovered yet"

        lines = ["🔍 *PRODUCT DISCOVERY REPORT*\n"]

        for i, c in enumerate(top, 1):
            lines.append(f"{i}. *{c.symbol}* ({c.edge_fit_score:.0%} fit)")
            if c.why_suitable:
                lines.append(f"   {c.why_suitable[0]}")

        return "\n".join(lines)

    def _create_discovery_inefficiency(self, candidate: ProductCandidate) -> Optional[Inefficiency]:
        """Convert product candidate to inefficiency"""
        try:
            description = (
                f"DISCOVERED: {candidate.symbol} ({candidate.name}) - "
                f"Edge fit: {candidate.edge_fit_score:.0%}\n"
                f"Reasons: {', '.join(candidate.why_suitable[:3])}"
            )

            return Inefficiency(
                id=f"DISCOVER_{candidate.symbol}_{datetime.now().strftime('%Y%m%d')}",
                type=InefficiencyType.STRUCTURAL,
                symbol=candidate.symbol,
                score=candidate.edge_fit_score,
                edge_reason=EdgeReason.RETAIL_FOMO,
                description=description,
                entry_trigger="Add to watchlist for behavioral patterns",
                time_sensitivity="weeks",
                expires_at=datetime.now() + timedelta(days=30),
                metadata={
                    'discovery_type': 'product',
                    'retail_score': candidate.retail_activity_score,
                    'volatility': candidate.volatility_30d,
                    'options_volume': candidate.options_volume,
                    'why_suitable': candidate.why_suitable,
                    'why_not': candidate.why_not
                }
            )
        except Exception as e:
            logger.debug(f"Error creating discovery inefficiency: {e}")
            return None

    def _create_sector_inefficiency(self, sector_opp: SectorOpportunity) -> Optional[Inefficiency]:
        """Convert sector opportunity to inefficiency"""
        try:
            return Inefficiency(
                id=f"SECTOR_{sector_opp.sector}_{datetime.now().strftime('%Y%m%d')}",
                type=InefficiencyType.STRUCTURAL,
                symbol=sector_opp.sector.upper(),
                score=0.6,
                edge_reason=EdgeReason.RETAIL_FOMO,
                description=f"SECTOR OPPORTUNITY: {sector_opp.sector} - {sector_opp.reasoning}",
                entry_trigger=f"Top plays: {', '.join(sector_opp.top_candidates[:3])}",
                time_sensitivity="weeks",
                expires_at=datetime.now() + timedelta(days=14),
                metadata={
                    'discovery_type': 'sector',
                    'opportunity_type': sector_opp.opportunity_type,
                    'top_candidates': sector_opp.top_candidates
                }
            )
        except Exception as e:
            logger.debug(f"Error creating sector inefficiency: {e}")
            return None

    def add_to_tracked(self, symbol: str) -> None:
        """Mark symbol as already tracked (don't re-recommend)"""
        self.already_tracked.add(symbol)

    def get_discovery_summary(self) -> str:
        """Get summary of discovered products"""
        if not self.discovered_products:
            return "No products discovered yet. Run a scan first."

        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║              PRODUCT DISCOVERY RESULTS                       ║",
            "╠══════════════════════════════════════════════════════════════╣"
        ]

        top = self._get_top_candidates(10)
        for i, candidate in enumerate(top, 1):
            score_bar = "█" * int(candidate.edge_fit_score * 10)
            lines.append(
                f"║  {i:2}. {candidate.symbol:<6} {score_bar:<10} {candidate.edge_fit_score:.0%}  ║"
            )
            if candidate.why_suitable:
                lines.append(f"║      └─ {candidate.why_suitable[0]:<45} ║")

        lines.append("╠══════════════════════════════════════════════════════════════╣")
        lines.append("║  WHAT WE LOOK FOR:                                          ║")
        lines.append("║  • High retail activity (emotional trading)                 ║")
        lines.append("║  • Volatile enough to create opportunities                  ║")
        lines.append("║  • Liquid options (to measure sentiment)                    ║")
        lines.append("║  • Tends to overreact (reversion plays)                    ║")
        lines.append("║  • NOT dominated by sophisticated algos                     ║")
        lines.append("╚══════════════════════════════════════════════════════════════╝")

        return "\n".join(lines)

"""
Market Brain - Inefficiency Detection Engine

The core philosophy: Find edges where algorithms CAN'T compete.

WHY ALGOS LOSE IN THESE AREAS:
1. Behavioral inefficiencies - Algos can't model human panic/greed well
2. Small-cap/illiquid - Too small for institutional algos
3. Event interpretation - Earnings context, sentiment nuance
4. Time-based patterns - Retail predictability (lunch dip, Monday fear)
5. Options complexity - Multi-leg mispricings in low-volume strikes

WHERE WE DON'T COMPETE:
- Large-cap spread capture (HFT dominates)
- Sub-second arbitrage (latency game)
- Index rebalancing (quants front-run)
- Statistical arbitrage on liquid pairs (overcrowded)

This brain continuously scans for exploitable inefficiencies
and produces a ranked list updated every 30 seconds.
"""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
from loguru import logger
import json
from pathlib import Path


class InefficiencyType(Enum):
    """Types of market inefficiencies we hunt"""
    RETAIL_CROWDING = "retail_crowding"      # Retail piling in = fade opportunity
    VOLATILITY_MISPRICING = "vol_mispricing"  # IV vs realized divergence
    TIME_ZONE_GAP = "time_zone_gap"          # Overnight/pre-market gaps
    OPTIONS_SKEW = "options_skew"            # Put/call imbalance
    EARNINGS_DRIFT = "earnings_drift"        # Post-earnings momentum
    LIQUIDITY_WINDOW = "liquidity_window"    # Spread patterns intraday
    SENTIMENT_EXTREME = "sentiment_extreme"  # Fear/greed at extremes
    INSIDER_SIGNAL = "insider_signal"        # Smart money moving


class EdgeReason(Enum):
    """Why we have edge (not algos)"""
    BEHAVIORAL = "behavioral"        # Human emotion patterns
    COMPLEXITY = "complexity"        # Too complex for simple algos
    ILLIQUIDITY = "illiquidity"      # Too small for big players
    TIME_HORIZON = "time_horizon"    # Multi-day holds (algos are fast)
    CONTEXT = "context"              # Requires understanding, not just data


@dataclass
class Inefficiency:
    """A detected market inefficiency"""
    id: str
    type: InefficiencyType
    symbol: str
    score: float                     # 0-1, higher = more exploitable
    edge_reason: EdgeReason          # Why WE have edge

    # Trade idea
    direction: str                   # 'long', 'short', 'neutral'
    suggested_action: str            # Human-readable action
    entry_zone: tuple                # (low, high) price range
    target: float                    # Target price
    stop: float                      # Stop loss
    risk_reward: float               # R:R ratio

    # Context
    explanation: str                 # Why this is an inefficiency
    data_points: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0          # 0-1
    time_sensitivity: str = "hours"  # 'minutes', 'hours', 'days'

    # Metadata
    detected_at: str = ""
    expires_at: str = ""             # When this becomes stale

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = datetime.now().isoformat()
        if not self.expires_at:
            # Default expiry based on time sensitivity
            hours = {"minutes": 1, "hours": 4, "days": 24}.get(self.time_sensitivity, 4)
            self.expires_at = (datetime.now() + timedelta(hours=hours)).isoformat()

    def is_expired(self) -> bool:
        return datetime.now() > datetime.fromisoformat(self.expires_at)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['type'] = self.type.value
        d['edge_reason'] = self.edge_reason.value
        return d


class MarketBrain:
    """
    The Market Brain - continuously hunts for exploitable inefficiencies.

    Philosophy:
    - We don't compete with algos on speed
    - We exploit HUMAN behavior patterns
    - We find complexity that algos miss
    - We trade where big money CAN'T (too small)

    Output:
    - Live ranked list of current inefficiencies
    - Each with clear action, R:R, and reasoning
    - Auto-expires stale opportunities
    """

    def __init__(self):
        self.inefficiencies: Dict[str, Inefficiency] = {}
        self.scanners: List[Any] = []
        self.running = False
        self.scan_interval = 30  # seconds

        # History for learning
        self.history_file = Path("data/brain_history.json")
        self.history: List[Dict] = self._load_history()

        # Performance tracking
        self.ideas_generated = 0
        self.ideas_acted_on = 0
        self.ideas_profitable = 0

        logger.info("Market Brain initialized - hunting inefficiencies")

    def _load_history(self) -> List[Dict]:
        """Load historical inefficiency detections"""
        if self.history_file.exists():
            with open(self.history_file, 'r') as f:
                return json.load(f)
        return []

    def _save_history(self) -> None:
        """Save history (keep last 1000)"""
        self.history = self.history[-1000:]
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, 'w') as f:
            json.dump(self.history, f, indent=2, default=str)

    def register_scanner(self, scanner) -> None:
        """Register an inefficiency scanner"""
        self.scanners.append(scanner)
        logger.info(f"Registered scanner: {scanner.__class__.__name__}")

    async def start(self) -> None:
        """Start the brain's continuous scanning"""
        self.running = True
        logger.info("Market Brain starting - continuous inefficiency detection")

        while self.running:
            try:
                await self._scan_cycle()
                await asyncio.sleep(self.scan_interval)
            except Exception as e:
                logger.error(f"Brain scan error: {e}")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the brain"""
        self.running = False
        self._save_history()
        logger.info("Market Brain stopped")

    async def _scan_cycle(self) -> None:
        """Run one scan cycle across all scanners"""
        # Clean expired inefficiencies
        self._cleanup_expired()

        # Run all scanners
        for scanner in self.scanners:
            try:
                new_inefficiencies = await scanner.scan()
                for ineff in new_inefficiencies:
                    self._add_inefficiency(ineff)
            except Exception as e:
                logger.error(f"Scanner {scanner.__class__.__name__} error: {e}")

        # Log status
        active_count = len(self.inefficiencies)
        if active_count > 0:
            top = self.get_top_inefficiencies(1)[0]
            logger.info(
                f"Brain: {active_count} active inefficiencies | "
                f"Top: {top.symbol} ({top.type.value}) Score: {top.score:.2f}"
            )

    def _add_inefficiency(self, ineff: Inefficiency) -> None:
        """Add or update an inefficiency"""
        # Use symbol + type as key (can have multiple types per symbol)
        key = f"{ineff.symbol}_{ineff.type.value}"

        # Only add if better than existing or new
        existing = self.inefficiencies.get(key)
        if not existing or ineff.score > existing.score:
            self.inefficiencies[key] = ineff
            self.ideas_generated += 1

            # Record in history
            self.history.append({
                'detected_at': ineff.detected_at,
                'symbol': ineff.symbol,
                'type': ineff.type.value,
                'score': ineff.score,
                'direction': ineff.direction
            })

    def _cleanup_expired(self) -> None:
        """Remove expired inefficiencies"""
        expired_keys = [
            k for k, v in self.inefficiencies.items()
            if v.is_expired()
        ]
        for k in expired_keys:
            del self.inefficiencies[k]

    def get_top_inefficiencies(self, n: int = 10) -> List[Inefficiency]:
        """Get top N inefficiencies by score"""
        sorted_ineff = sorted(
            self.inefficiencies.values(),
            key=lambda x: x.score,
            reverse=True
        )
        return sorted_ineff[:n]

    def get_by_type(self, ineff_type: InefficiencyType) -> List[Inefficiency]:
        """Get all inefficiencies of a specific type"""
        return [
            v for v in self.inefficiencies.values()
            if v.type == ineff_type
        ]

    def get_by_symbol(self, symbol: str) -> List[Inefficiency]:
        """Get all inefficiencies for a symbol"""
        return [
            v for v in self.inefficiencies.values()
            if v.symbol == symbol
        ]

    def format_dashboard(self) -> str:
        """Format current inefficiencies as a text dashboard"""
        top = self.get_top_inefficiencies(8)

        if not top:
            return "No active inefficiencies detected."

        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            f"║  MARKET INEFFICIENCIES (Live)           {datetime.now().strftime('%H:%M:%S')}     ║",
            "╠══════════════════════════════════════════════════════════════╣"
        ]

        for i, ineff in enumerate(top, 1):
            type_short = {
                InefficiencyType.RETAIL_CROWDING: "CROWD",
                InefficiencyType.VOLATILITY_MISPRICING: "VOL",
                InefficiencyType.TIME_ZONE_GAP: "GAP",
                InefficiencyType.OPTIONS_SKEW: "SKEW",
                InefficiencyType.EARNINGS_DRIFT: "EARN",
                InefficiencyType.LIQUIDITY_WINDOW: "LIQ",
                InefficiencyType.SENTIMENT_EXTREME: "SENT",
                InefficiencyType.INSIDER_SIGNAL: "INSIDER"
            }.get(ineff.type, "???")

            direction_emoji = {"long": "🟢", "short": "🔴", "neutral": "⚪"}.get(ineff.direction, "⚪")

            lines.append(f"║  #{i}  {type_short:8} {ineff.symbol:6} {direction_emoji} Score: {ineff.score:.2f}  R:R {ineff.risk_reward:.1f}  ║")
            lines.append(f"║      → {ineff.suggested_action[:50]:50} ║")
            lines.append("║                                                              ║")

        lines.append("╚══════════════════════════════════════════════════════════════╝")

        return "\n".join(lines)

    def get_telegram_message(self) -> str:
        """Format for Telegram notification"""
        top = self.get_top_inefficiencies(5)

        if not top:
            return "🧠 *Market Brain*\n\nNo active inefficiencies."

        lines = [f"🧠 *Market Brain* - {datetime.now().strftime('%H:%M')}\n"]

        for i, ineff in enumerate(top, 1):
            emoji = {"long": "🟢", "short": "🔴", "neutral": "⚪"}.get(ineff.direction, "⚪")
            lines.append(
                f"{i}. {emoji} *{ineff.symbol}* ({ineff.type.value})\n"
                f"   Score: {ineff.score:.0%} | R:R: {ineff.risk_reward:.1f}\n"
                f"   _{ineff.suggested_action}_\n"
            )

        return "\n".join(lines)

    def get_status(self) -> Dict:
        """Get brain status"""
        return {
            'active_inefficiencies': len(self.inefficiencies),
            'scanners_registered': len(self.scanners),
            'ideas_generated': self.ideas_generated,
            'running': self.running,
            'top_opportunity': self.get_top_inefficiencies(1)[0].to_dict() if self.inefficiencies else None
        }


# Singleton instance
_brain_instance: Optional[MarketBrain] = None


def get_market_brain() -> MarketBrain:
    """Get or create the market brain instance"""
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = MarketBrain()
    return _brain_instance

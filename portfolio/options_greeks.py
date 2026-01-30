"""
Options Greeks Dashboard

Monitor options positions for theta decay, delta exposure, and DTE warnings.

"Time decay is the silent killer of options positions."
"""
import asyncio
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from portfolio.position_tracker import get_position_tracker, Position, PositionType

# Try to import Telegram notifier
try:
    from utils.telegram_notifier import get_notifier
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


@dataclass
class OptionsGreeksSnapshot:
    """Greeks snapshot for an options position"""
    symbol: str
    option_type: str  # "CALL" or "PUT"
    strike: float
    expiry: str
    days_to_expiry: int
    quantity: int

    # Current values
    underlying_price: float
    option_price: float

    # Greeks (estimated if not available from API)
    delta: float
    gamma: float
    theta: float  # Daily decay in dollars
    vega: float
    iv: float  # Implied volatility

    # Derived metrics
    theta_decay_daily: float  # Total daily decay for position
    delta_exposure: float  # Equivalent shares exposure
    is_itm: bool
    moneyness: float  # How far in/out of the money (%)

    # Warnings
    warnings: List[str]


class OptionsGreeksDashboard:
    """
    Tracks Greeks for all options positions.

    Key metrics:
    - Theta: How much you're losing to time decay daily
    - Delta: Your directional exposure (equivalent shares)
    - DTE: Days to expiration (danger zone < 7 days)
    - IV Rank: Is volatility high or low historically?

    Rules:
    - Know your theta - it's real cost
    - Don't hold low-DTE options without a reason
    - Delta tells you how much you're really betting
    """

    # DTE thresholds
    DTE_DANGER = 7      # Danger zone
    DTE_WARNING = 14    # Getting close
    DTE_CRITICAL = 3    # Emergency

    # Theta warning threshold (daily decay as % of position value)
    THETA_WARNING_PCT = 2.0  # Warn if losing >2% per day to theta

    def __init__(self):
        self.tracker = get_position_tracker()
        self.greeks_cache: Dict[str, OptionsGreeksSnapshot] = {}
        self.last_update: Optional[datetime] = None

    def _get_options_positions(self) -> List[Position]:
        """Get all options positions"""
        return [
            pos for pos in self.tracker.positions.values()
            if pos.position_type in [PositionType.OPTIONS_CALL, PositionType.OPTIONS_PUT]
        ]

    def _calculate_days_to_expiry(self, expiry: str) -> int:
        """Calculate days until expiration"""
        try:
            exp_date = datetime.strptime(expiry, "%Y-%m-%d")
            delta = exp_date - datetime.now()
            return max(0, delta.days)
        except:
            return 0

    def _estimate_greeks(
        self,
        underlying_price: float,
        strike: float,
        dte: int,
        option_type: str,
        option_price: float,
        iv: float = 0.30  # Default 30% IV
    ) -> Dict:
        """
        Estimate Greeks using Black-Scholes approximations.
        Note: This is simplified - real trading should use actual Greeks from broker.
        """
        # Time to expiration in years
        T = dte / 365.0
        if T <= 0:
            T = 0.001  # Avoid division by zero

        # Risk-free rate assumption
        r = 0.05

        # Standard normal CDF approximation
        def norm_cdf(x):
            return 0.5 * (1 + math.erf(x / math.sqrt(2)))

        # Standard normal PDF
        def norm_pdf(x):
            return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

        try:
            # d1 and d2
            d1 = (math.log(underlying_price / strike) + (r + 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
            d2 = d1 - iv * math.sqrt(T)

            # Delta
            if option_type.upper() == "CALL":
                delta = norm_cdf(d1)
            else:
                delta = norm_cdf(d1) - 1

            # Gamma
            gamma = norm_pdf(d1) / (underlying_price * iv * math.sqrt(T))

            # Theta (per day)
            theta_term1 = -(underlying_price * norm_pdf(d1) * iv) / (2 * math.sqrt(T))
            if option_type.upper() == "CALL":
                theta_term2 = -r * strike * math.exp(-r * T) * norm_cdf(d2)
            else:
                theta_term2 = r * strike * math.exp(-r * T) * norm_cdf(-d2)
            theta = (theta_term1 + theta_term2) / 365  # Convert to daily

            # Vega (per 1% IV change)
            vega = underlying_price * math.sqrt(T) * norm_pdf(d1) / 100

            return {
                'delta': round(delta, 4),
                'gamma': round(gamma, 6),
                'theta': round(theta, 4),
                'vega': round(vega, 4),
                'iv': iv
            }

        except Exception as e:
            logger.debug(f"Error calculating greeks: {e}")
            # Return sensible defaults
            return {
                'delta': 0.5 if option_type.upper() == "CALL" else -0.5,
                'gamma': 0.01,
                'theta': -0.05,
                'vega': 0.10,
                'iv': iv
            }

    async def refresh_greeks(self) -> int:
        """Refresh Greeks for all options positions"""
        # Refresh underlying prices first
        await self.tracker.refresh_prices()

        options_positions = self._get_options_positions()
        if not options_positions:
            return 0

        updated = 0

        for pos in options_positions:
            try:
                snapshot = await self._calculate_position_greeks(pos)
                if snapshot:
                    key = f"{pos.symbol}_{pos.strike}_{pos.expiry}"
                    self.greeks_cache[key] = snapshot
                    updated += 1
            except Exception as e:
                logger.debug(f"Error calculating greeks for {pos.symbol}: {e}")

        self.last_update = datetime.now()
        return updated

    async def _calculate_position_greeks(self, pos: Position) -> Optional[OptionsGreeksSnapshot]:
        """Calculate Greeks for a single options position"""
        if not pos.strike or not pos.expiry:
            return None

        dte = self._calculate_days_to_expiry(pos.expiry)
        underlying_price = pos.current_price

        # For options, we need underlying price, not option price
        # Try to get it from yfinance if current_price seems like option premium
        if YFINANCE_AVAILABLE and underlying_price < 10:  # Likely option premium, not underlying
            try:
                ticker = yf.Ticker(pos.symbol)
                underlying_price = ticker.info.get('regularMarketPrice', pos.current_price)
            except:
                pass

        option_type = pos.option_type or ("CALL" if pos.position_type == PositionType.OPTIONS_CALL else "PUT")

        # Estimate Greeks
        greeks = self._estimate_greeks(
            underlying_price=underlying_price,
            strike=pos.strike,
            dte=dte,
            option_type=option_type,
            option_price=pos.entry_price  # Use entry as approximation
        )

        # Calculate derived metrics
        is_itm = (underlying_price > pos.strike) if option_type == "CALL" else (underlying_price < pos.strike)
        moneyness = ((underlying_price - pos.strike) / pos.strike) * 100

        # Position-level metrics
        theta_decay_daily = abs(greeks['theta']) * pos.quantity * 100  # Options are 100 shares
        delta_exposure = greeks['delta'] * pos.quantity * 100  # Equivalent shares

        # Generate warnings
        warnings = []

        if dte <= self.DTE_CRITICAL:
            warnings.append(f"CRITICAL: Only {dte} DTE - extreme theta decay")
        elif dte <= self.DTE_DANGER:
            warnings.append(f"DANGER: Only {dte} DTE - high theta decay zone")
        elif dte <= self.DTE_WARNING:
            warnings.append(f"WARNING: {dte} DTE - approaching theta danger zone")

        # Theta warning
        position_value = pos.entry_price * pos.quantity * 100
        if position_value > 0:
            theta_pct = (theta_decay_daily / position_value) * 100
            if theta_pct > self.THETA_WARNING_PCT:
                warnings.append(f"HIGH THETA: Losing ${theta_decay_daily:.2f}/day ({theta_pct:.1f}%)")

        # OTM warning close to expiry
        if not is_itm and dte <= 7:
            warnings.append("OTM with low DTE - consider exit")

        return OptionsGreeksSnapshot(
            symbol=pos.symbol,
            option_type=option_type,
            strike=pos.strike,
            expiry=pos.expiry,
            days_to_expiry=dte,
            quantity=int(pos.quantity),
            underlying_price=underlying_price,
            option_price=pos.entry_price,
            delta=greeks['delta'],
            gamma=greeks['gamma'],
            theta=greeks['theta'],
            vega=greeks['vega'],
            iv=greeks['iv'],
            theta_decay_daily=theta_decay_daily,
            delta_exposure=delta_exposure,
            is_itm=is_itm,
            moneyness=moneyness,
            warnings=warnings
        )

    def get_portfolio_greeks_summary(self) -> Dict:
        """Get aggregate Greeks for entire options portfolio"""
        snapshots = list(self.greeks_cache.values())

        if not snapshots:
            return {
                'total_positions': 0,
                'total_delta_exposure': 0,
                'total_theta_daily': 0,
                'avg_dte': 0,
                'positions_in_danger_zone': 0
            }

        total_delta = sum(s.delta_exposure for s in snapshots)
        total_theta = sum(s.theta_decay_daily for s in snapshots)
        avg_dte = sum(s.days_to_expiry for s in snapshots) / len(snapshots)
        danger_zone = len([s for s in snapshots if s.days_to_expiry <= self.DTE_DANGER])

        return {
            'total_positions': len(snapshots),
            'total_delta_exposure': total_delta,
            'total_theta_daily': total_theta,
            'avg_dte': avg_dte,
            'positions_in_danger_zone': danger_zone,
            'all_warnings': [w for s in snapshots for w in s.warnings]
        }

    async def send_dte_alerts(self) -> int:
        """Send Telegram alerts for low DTE positions"""
        if not TELEGRAM_AVAILABLE:
            return 0

        critical = [s for s in self.greeks_cache.values() if s.days_to_expiry <= self.DTE_DANGER]

        if not critical:
            return 0

        try:
            notifier = get_notifier()
            if not notifier:
                return 0

            lines = ["⏰ <b>OPTIONS DTE ALERT</b>\n"]
            lines.append("Low DTE positions require attention:\n")

            for snap in sorted(critical, key=lambda s: s.days_to_expiry):
                itm_str = "ITM" if snap.is_itm else "OTM"
                lines.append(f"<b>{snap.symbol}</b> ${snap.strike} {snap.option_type}")
                lines.append(f"  DTE: {snap.days_to_expiry} | {itm_str}")
                lines.append(f"  Theta: -${snap.theta_decay_daily:.2f}/day")
                lines.append("")

            lines.append("<i>⚠️ Time decay accelerates in final week</i>")

            await notifier.send_message("\n".join(lines))
            return len(critical)

        except Exception as e:
            logger.error(f"Error sending DTE alerts: {e}")
            return 0

    def format_greeks_dashboard(self) -> str:
        """Format Greeks dashboard for display"""
        lines = []
        lines.append("=" * 60)
        lines.append("            OPTIONS GREEKS DASHBOARD")
        lines.append("=" * 60)

        snapshots = list(self.greeks_cache.values())

        if not snapshots:
            lines.append("\n  No options positions to display")
            lines.append("")
            return "\n".join(lines)

        # Portfolio summary
        summary = self.get_portfolio_greeks_summary()

        lines.append(f"\n  PORTFOLIO SUMMARY:")
        lines.append(f"  Total Options Positions: {summary['total_positions']}")
        lines.append(f"  Net Delta Exposure: {summary['total_delta_exposure']:+.0f} shares equivalent")
        lines.append(f"  Total Theta (daily): -${summary['total_theta_daily']:.2f}")
        lines.append(f"  Average DTE: {summary['avg_dte']:.1f} days")

        if summary['positions_in_danger_zone'] > 0:
            lines.append(f"  ⚠️  In Danger Zone (≤{self.DTE_DANGER} DTE): {summary['positions_in_danger_zone']}")

        # Individual positions
        lines.append("\n  POSITIONS:")
        lines.append("  " + "-" * 56)
        lines.append(f"  {'Symbol':<8} {'Strike':>8} {'Type':>5} {'DTE':>5} {'Delta':>7} {'Theta':>8}")
        lines.append("  " + "-" * 56)

        for snap in sorted(snapshots, key=lambda s: s.days_to_expiry):
            dte_warning = "⚠️" if snap.days_to_expiry <= self.DTE_DANGER else "  "
            lines.append(
                f"  {snap.symbol:<8} ${snap.strike:>7.0f} {snap.option_type:>5} "
                f"{snap.days_to_expiry:>4}d {snap.delta:>+6.2f} -${snap.theta_decay_daily:>6.2f} {dte_warning}"
            )

        lines.append("  " + "-" * 56)

        # Warnings section
        all_warnings = summary.get('all_warnings', [])
        if all_warnings:
            lines.append("\n  ⚠️  WARNINGS:")
            for warning in all_warnings[:5]:  # Show top 5
                lines.append(f"    • {warning}")

        # Legend
        lines.append("\n  GREEKS LEGEND:")
        lines.append("    Delta: Directional exposure (1.0 = 100 shares)")
        lines.append("    Theta: Daily time decay cost ($)")
        lines.append("    DTE: Days to expiration")

        lines.append("")
        return "\n".join(lines)


# Singleton
_greeks_instance: Optional[OptionsGreeksDashboard] = None

def get_options_greeks() -> OptionsGreeksDashboard:
    """Get or create options greeks dashboard instance"""
    global _greeks_instance
    if _greeks_instance is None:
        _greeks_instance = OptionsGreeksDashboard()
    return _greeks_instance


async def run_greeks_dashboard():
    """Run Greeks dashboard update and display"""
    dashboard = get_options_greeks()

    print("Calculating options Greeks...")
    await dashboard.refresh_greeks()

    print(dashboard.format_greeks_dashboard())


if __name__ == "__main__":
    asyncio.run(run_greeks_dashboard())

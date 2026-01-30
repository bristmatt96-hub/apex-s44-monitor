"""
Position Tracker & Portfolio Heat Monitor

Tracks open positions, calculates exposure, and monitors portfolio risk.
Capital preservation is #1 - know your risk at all times.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


class PositionType(Enum):
    STOCK = "stock"
    OPTIONS_CALL = "options_call"
    OPTIONS_PUT = "options_put"
    ETF = "etf"


@dataclass
class Position:
    """A single position in the portfolio"""
    symbol: str
    position_type: PositionType
    quantity: float
    entry_price: float
    entry_date: str
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    strategy: str = ""
    rationale: str = ""

    # Options-specific
    strike: Optional[float] = None
    expiry: Optional[str] = None
    option_type: Optional[str] = None  # CALL or PUT

    # Live data (updated on refresh)
    current_price: float = 0.0
    last_updated: str = ""

    @property
    def market_value(self) -> float:
        """Current market value of position"""
        if self.position_type in [PositionType.OPTIONS_CALL, PositionType.OPTIONS_PUT]:
            return self.current_price * self.quantity * 100  # Options are 100 shares
        return self.current_price * self.quantity

    @property
    def cost_basis(self) -> float:
        """Original cost of position"""
        if self.position_type in [PositionType.OPTIONS_CALL, PositionType.OPTIONS_PUT]:
            return self.entry_price * self.quantity * 100
        return self.entry_price * self.quantity

    @property
    def unrealized_pnl(self) -> float:
        """Unrealized P&L"""
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        """Unrealized P&L as percentage"""
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100

    @property
    def risk_amount(self) -> float:
        """Amount at risk (to stop loss or zero)"""
        if self.stop_loss:
            if self.position_type in [PositionType.OPTIONS_CALL, PositionType.OPTIONS_PUT]:
                return (self.current_price - self.stop_loss) * self.quantity * 100
            return (self.current_price - self.stop_loss) * self.quantity
        # If no stop, assume max loss is entry price (for long positions)
        return self.cost_basis

    @property
    def distance_to_stop_pct(self) -> Optional[float]:
        """How far price is from stop loss (percentage)"""
        if not self.stop_loss or self.current_price == 0:
            return None
        return ((self.current_price - self.stop_loss) / self.current_price) * 100

    @property
    def r_multiple(self) -> Optional[float]:
        """Current R-multiple (how many R's of profit/loss)"""
        if not self.stop_loss:
            return None
        risk_per_unit = abs(self.entry_price - self.stop_loss)
        if risk_per_unit == 0:
            return None
        current_profit = self.current_price - self.entry_price
        return current_profit / risk_per_unit


@dataclass
class PortfolioSnapshot:
    """Point-in-time snapshot of portfolio state"""
    timestamp: str
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float
    positions_count: int
    portfolio_heat: float  # % of portfolio at risk
    largest_position_pct: float
    cash: float


class PositionTracker:
    """
    Tracks all open positions and portfolio risk metrics.

    Key metrics:
    - Portfolio Heat: Total % of portfolio at risk (sum of position risks / total portfolio)
    - Position Concentration: Largest position as % of portfolio
    - Correlation Risk: When multiple positions move together
    """

    # Risk thresholds
    MAX_PORTFOLIO_HEAT = 0.10  # Max 10% of portfolio at risk at any time
    MAX_POSITION_SIZE = 0.20   # Max 20% in single position
    STOP_WARNING_THRESHOLD = 0.03  # Warn when within 3% of stop

    # Sector correlations (simplified - positions in same sector are correlated)
    SECTOR_MAP = {
        'AAPL': 'tech', 'MSFT': 'tech', 'GOOGL': 'tech', 'META': 'tech', 'NVDA': 'tech', 'AMD': 'tech',
        'TSLA': 'ev', 'RIVN': 'ev', 'LCID': 'ev', 'NIO': 'ev',
        'SPY': 'index', 'QQQ': 'index', 'IWM': 'index',
        'GLD': 'precious', 'SLV': 'precious', 'GDX': 'precious',
        'XLE': 'energy', 'USO': 'energy', 'UCO': 'energy',
        'TQQQ': 'leveraged_tech', 'SQQQ': 'leveraged_tech',
    }

    def __init__(self, data_path: str = "portfolio/data"):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.positions_file = self.data_path / "positions.json"
        self.history_file = self.data_path / "portfolio_history.json"

        self.positions: Dict[str, Position] = {}
        self.portfolio_value: float = 0.0
        self.cash: float = 0.0

        self._load_positions()

    def _load_positions(self) -> None:
        """Load positions from file"""
        if self.positions_file.exists():
            try:
                with open(self.positions_file, 'r') as f:
                    data = json.load(f)
                    self.cash = data.get('cash', 0.0)
                    self.portfolio_value = data.get('portfolio_value', 0.0)
                    for pos_data in data.get('positions', []):
                        pos_data['position_type'] = PositionType(pos_data['position_type'])
                        pos = Position(**pos_data)
                        self.positions[self._position_key(pos)] = pos
                logger.info(f"Loaded {len(self.positions)} positions")
            except Exception as e:
                logger.error(f"Error loading positions: {e}")

    def _save_positions(self) -> None:
        """Save positions to file"""
        try:
            data = {
                'cash': self.cash,
                'portfolio_value': self.portfolio_value,
                'last_updated': datetime.now().isoformat(),
                'positions': []
            }
            for pos in self.positions.values():
                pos_dict = asdict(pos)
                pos_dict['position_type'] = pos.position_type.value
                data['positions'].append(pos_dict)

            with open(self.positions_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving positions: {e}")

    def _position_key(self, pos: Position) -> str:
        """Generate unique key for position"""
        if pos.position_type in [PositionType.OPTIONS_CALL, PositionType.OPTIONS_PUT]:
            return f"{pos.symbol}_{pos.strike}_{pos.expiry}_{pos.option_type}"
        return pos.symbol

    def set_cash(self, amount: float) -> None:
        """Set cash balance"""
        self.cash = amount
        self._save_positions()
        logger.info(f"Cash set to ${amount:,.2f}")

    def set_portfolio_value(self, value: float) -> None:
        """Set total portfolio value (for heat calculations)"""
        self.portfolio_value = value
        self._save_positions()
        logger.info(f"Portfolio value set to ${value:,.2f}")

    def add_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        position_type: PositionType = PositionType.STOCK,
        stop_loss: Optional[float] = None,
        target: Optional[float] = None,
        strategy: str = "",
        rationale: str = "",
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        option_type: Optional[str] = None
    ) -> Position:
        """Add a new position"""
        pos = Position(
            symbol=symbol.upper(),
            position_type=position_type,
            quantity=quantity,
            entry_price=entry_price,
            entry_date=datetime.now().isoformat(),
            stop_loss=stop_loss,
            target=target,
            strategy=strategy,
            rationale=rationale,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            current_price=entry_price,
            last_updated=datetime.now().isoformat()
        )

        key = self._position_key(pos)
        self.positions[key] = pos
        self._save_positions()

        logger.info(f"Added position: {symbol} x{quantity} @ ${entry_price}")
        return pos

    def close_position(self, symbol: str, exit_price: float,
                       strike: Optional[float] = None,
                       expiry: Optional[str] = None) -> Optional[Dict]:
        """Close a position and return trade result"""
        # Build key
        if strike and expiry:
            key = f"{symbol.upper()}_{strike}_{expiry}_CALL"
            if key not in self.positions:
                key = f"{symbol.upper()}_{strike}_{expiry}_PUT"
        else:
            key = symbol.upper()

        if key not in self.positions:
            logger.warning(f"Position not found: {key}")
            return None

        pos = self.positions[key]

        # Calculate final P&L
        if pos.position_type in [PositionType.OPTIONS_CALL, PositionType.OPTIONS_PUT]:
            pnl = (exit_price - pos.entry_price) * pos.quantity * 100
        else:
            pnl = (exit_price - pos.entry_price) * pos.quantity

        pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100

        result = {
            'symbol': pos.symbol,
            'entry_price': pos.entry_price,
            'exit_price': exit_price,
            'quantity': pos.quantity,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'r_multiple': pos.r_multiple,
            'hold_time': self._calculate_hold_time(pos.entry_date),
            'strategy': pos.strategy,
            'closed_at': datetime.now().isoformat()
        }

        del self.positions[key]
        self._save_positions()

        logger.info(f"Closed {symbol}: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
        return result

    def _calculate_hold_time(self, entry_date: str) -> str:
        """Calculate human-readable hold time"""
        try:
            entry = datetime.fromisoformat(entry_date)
            delta = datetime.now() - entry

            if delta.days > 0:
                return f"{delta.days}d {delta.seconds // 3600}h"
            elif delta.seconds >= 3600:
                return f"{delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
            else:
                return f"{delta.seconds // 60}m"
        except:
            return "unknown"

    async def refresh_prices(self) -> None:
        """Update current prices for all positions"""
        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available for price refresh")
            return

        symbols = list(set(pos.symbol for pos in self.positions.values()))
        if not symbols:
            return

        try:
            # Batch fetch
            tickers = yf.Tickers(" ".join(symbols))

            for symbol in symbols:
                try:
                    ticker = tickers.tickers.get(symbol)
                    if ticker:
                        info = ticker.info
                        price = info.get('regularMarketPrice') or info.get('currentPrice', 0)

                        # Update all positions for this symbol
                        for key, pos in self.positions.items():
                            if pos.symbol == symbol:
                                pos.current_price = price
                                pos.last_updated = datetime.now().isoformat()
                except Exception as e:
                    logger.debug(f"Error fetching {symbol}: {e}")

            self._save_positions()
            logger.info(f"Refreshed prices for {len(symbols)} symbols")

        except Exception as e:
            logger.error(f"Error refreshing prices: {e}")

    def get_portfolio_heat(self) -> float:
        """
        Calculate portfolio heat (% of portfolio at risk).

        Heat = Sum of (distance to stop * position size) / portfolio value
        """
        if self.portfolio_value <= 0:
            return 0.0

        total_risk = sum(pos.risk_amount for pos in self.positions.values())
        return (total_risk / self.portfolio_value) * 100

    def get_position_concentration(self) -> Tuple[str, float]:
        """Get largest position and its % of portfolio"""
        if not self.positions or self.portfolio_value <= 0:
            return ("", 0.0)

        largest = max(self.positions.values(), key=lambda p: p.market_value)
        concentration = (largest.market_value / self.portfolio_value) * 100
        return (largest.symbol, concentration)

    def get_sector_exposure(self) -> Dict[str, float]:
        """Get exposure by sector"""
        exposure = {}
        for pos in self.positions.values():
            sector = self.SECTOR_MAP.get(pos.symbol, 'other')
            exposure[sector] = exposure.get(sector, 0) + pos.market_value
        return exposure

    def get_correlation_warnings(self) -> List[str]:
        """Check for correlated positions (concentration risk)"""
        warnings = []
        sector_exposure = self.get_sector_exposure()

        if self.portfolio_value <= 0:
            return warnings

        for sector, value in sector_exposure.items():
            pct = (value / self.portfolio_value) * 100
            if pct > 40:
                warnings.append(f"HIGH: {sector} sector at {pct:.1f}% of portfolio")
            elif pct > 25:
                warnings.append(f"WARN: {sector} sector at {pct:.1f}% of portfolio")

        return warnings

    def get_stop_warnings(self) -> List[Tuple[Position, float]]:
        """Get positions approaching stop loss"""
        warnings = []
        for pos in self.positions.values():
            dist = pos.distance_to_stop_pct
            if dist is not None and dist < self.STOP_WARNING_THRESHOLD * 100:
                warnings.append((pos, dist))

        return sorted(warnings, key=lambda x: x[1])

    def get_summary(self) -> Dict:
        """Get portfolio summary"""
        total_value = sum(pos.market_value for pos in self.positions.values())
        total_cost = sum(pos.cost_basis for pos in self.positions.values())
        total_pnl = total_value - total_cost

        symbol, concentration = self.get_position_concentration()

        return {
            'positions_count': len(self.positions),
            'total_market_value': total_value,
            'total_cost_basis': total_cost,
            'total_unrealized_pnl': total_pnl,
            'total_unrealized_pnl_pct': (total_pnl / total_cost * 100) if total_cost > 0 else 0,
            'portfolio_heat': self.get_portfolio_heat(),
            'cash': self.cash,
            'largest_position': symbol,
            'largest_position_pct': concentration,
            'correlation_warnings': self.get_correlation_warnings(),
            'stop_warnings': len(self.get_stop_warnings())
        }

    def format_dashboard(self) -> str:
        """Format portfolio dashboard for display"""
        lines = []
        lines.append("=" * 60)
        lines.append("           PORTFOLIO POSITION TRACKER")
        lines.append("=" * 60)

        if not self.positions:
            lines.append("\n  No open positions\n")
            return "\n".join(lines)

        summary = self.get_summary()

        # Overview
        lines.append(f"\n  Total Positions: {summary['positions_count']}")
        lines.append(f"  Market Value:    ${summary['total_market_value']:,.2f}")
        lines.append(f"  Unrealized P&L:  ${summary['total_unrealized_pnl']:+,.2f} ({summary['total_unrealized_pnl_pct']:+.1f}%)")
        lines.append(f"  Cash:            ${self.cash:,.2f}")

        # Risk metrics
        heat = summary['portfolio_heat']
        heat_status = "OK" if heat < self.MAX_PORTFOLIO_HEAT * 100 else "HIGH"
        lines.append(f"\n  Portfolio Heat:  {heat:.1f}% [{heat_status}]")
        lines.append(f"  Largest Pos:     {summary['largest_position']} ({summary['largest_position_pct']:.1f}%)")

        # Warnings
        if summary['correlation_warnings']:
            lines.append("\n  CORRELATION WARNINGS:")
            for warn in summary['correlation_warnings']:
                lines.append(f"    {warn}")

        stop_warns = self.get_stop_warnings()
        if stop_warns:
            lines.append("\n  STOP LOSS WARNINGS:")
            for pos, dist in stop_warns[:5]:
                lines.append(f"    {pos.symbol}: {dist:.1f}% from stop")

        # Positions table
        lines.append("\n  OPEN POSITIONS:")
        lines.append("  " + "-" * 56)
        lines.append(f"  {'Symbol':<8} {'Type':<8} {'Qty':>8} {'Entry':>10} {'Current':>10} {'P&L':>12}")
        lines.append("  " + "-" * 56)

        for pos in sorted(self.positions.values(), key=lambda p: -abs(p.unrealized_pnl)):
            ptype = pos.position_type.value[:6]
            pnl_str = f"${pos.unrealized_pnl:+,.0f} ({pos.unrealized_pnl_pct:+.1f}%)"
            lines.append(f"  {pos.symbol:<8} {ptype:<8} {pos.quantity:>8.0f} ${pos.entry_price:>9.2f} ${pos.current_price:>9.2f} {pnl_str:>12}")

        lines.append("  " + "-" * 56)
        lines.append("")

        return "\n".join(lines)


# Singleton
_tracker_instance: Optional[PositionTracker] = None

def get_position_tracker() -> PositionTracker:
    """Get or create position tracker instance"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = PositionTracker()
    return _tracker_instance

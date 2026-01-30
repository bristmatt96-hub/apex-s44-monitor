"""
Earnings Calendar

Track upcoming earnings for watched symbols.
Earnings = binary events = retail overreaction = opportunity.

"Don't get caught holding through earnings unless that's your strategy."
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# Try to import Telegram notifier
try:
    from utils.telegram_notifier import get_notifier
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


@dataclass
class EarningsEvent:
    """Earnings event for a symbol"""
    symbol: str
    name: str
    earnings_date: str
    time_of_day: str  # "BMO" (before market open), "AMC" (after market close), "Unknown"
    days_until: int
    eps_estimate: Optional[float] = None
    revenue_estimate: Optional[float] = None
    prev_eps_surprise_pct: Optional[float] = None

    # Context
    implied_move: Optional[float] = None  # From options if available
    historical_avg_move: Optional[float] = None
    is_in_portfolio: bool = False


class EarningsCalendar:
    """
    Tracks earnings dates for watched symbols.

    Use cases:
    - Know when positions have earnings (binary event risk)
    - Find earnings plays (post-earnings overreaction)
    - Avoid holding options through earnings (IV crush)

    Strategy notes:
    - Retail often overreacts to earnings (both ways)
    - Post-earnings drift is real for surprises
    - IV typically peaks right before earnings (sell premium opportunity)
    """

    # Default watchlist (common retail favorites)
    DEFAULT_WATCHLIST = [
        # Mega cap tech
        'AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN', 'NVDA', 'TSLA', 'NFLX',
        # Retail favorites
        'AMD', 'PLTR', 'SOFI', 'HOOD', 'COIN', 'GME', 'AMC',
        # High vol names
        'ROKU', 'SNAP', 'PINS', 'UBER', 'LYFT', 'DASH', 'ABNB',
        # ETFs (these don't have earnings but track sector reports)
        # 'SPY', 'QQQ', 'IWM',
    ]

    # Days to look ahead for alerts
    ALERT_DAYS = 7

    def __init__(self, data_path: str = "portfolio/data"):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.watchlist_file = self.data_path / "earnings_watchlist.json"
        self.cache_file = self.data_path / "earnings_cache.json"

        self.watchlist: Set[str] = set()
        self.earnings_events: Dict[str, EarningsEvent] = {}
        self.portfolio_symbols: Set[str] = set()

        self._load_watchlist()
        self._load_cache()

    def _load_watchlist(self) -> None:
        """Load watchlist from file"""
        if self.watchlist_file.exists():
            try:
                with open(self.watchlist_file, 'r') as f:
                    data = json.load(f)
                    self.watchlist = set(data.get('symbols', []))
            except Exception as e:
                logger.error(f"Error loading watchlist: {e}")

        if not self.watchlist:
            self.watchlist = set(self.DEFAULT_WATCHLIST)
            self._save_watchlist()

    def _save_watchlist(self) -> None:
        """Save watchlist to file"""
        try:
            with open(self.watchlist_file, 'w') as f:
                json.dump({'symbols': list(self.watchlist)}, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving watchlist: {e}")

    def _load_cache(self) -> None:
        """Load cached earnings data"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    cache_date = data.get('cache_date', '')

                    # Check if cache is still valid (less than 1 day old)
                    if cache_date:
                        cache_dt = datetime.fromisoformat(cache_date)
                        if (datetime.now() - cache_dt).days < 1:
                            for event_data in data.get('events', []):
                                event = EarningsEvent(**event_data)
                                self.earnings_events[event.symbol] = event
                            logger.info(f"Loaded {len(self.earnings_events)} cached earnings events")
            except Exception as e:
                logger.debug(f"Error loading earnings cache: {e}")

    def _save_cache(self) -> None:
        """Save earnings data to cache"""
        try:
            data = {
                'cache_date': datetime.now().isoformat(),
                'events': [asdict(e) for e in self.earnings_events.values()]
            }
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving earnings cache: {e}")

    def add_to_watchlist(self, symbol: str) -> None:
        """Add symbol to watchlist"""
        self.watchlist.add(symbol.upper())
        self._save_watchlist()
        logger.info(f"Added {symbol} to earnings watchlist")

    def remove_from_watchlist(self, symbol: str) -> None:
        """Remove symbol from watchlist"""
        self.watchlist.discard(symbol.upper())
        self._save_watchlist()
        logger.info(f"Removed {symbol} from earnings watchlist")

    def set_portfolio_symbols(self, symbols: List[str]) -> None:
        """Set current portfolio symbols (for highlighting)"""
        self.portfolio_symbols = set(s.upper() for s in symbols)

    async def refresh_earnings(self) -> int:
        """Fetch latest earnings dates for watchlist"""
        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available")
            return 0

        logger.info(f"Refreshing earnings for {len(self.watchlist)} symbols...")
        updated = 0

        for symbol in self.watchlist:
            try:
                event = await self._fetch_earnings(symbol)
                if event:
                    self.earnings_events[symbol] = event
                    updated += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.debug(f"Error fetching {symbol}: {e}")

        self._save_cache()
        logger.info(f"Updated earnings for {updated} symbols")
        return updated

    async def _fetch_earnings(self, symbol: str) -> Optional[EarningsEvent]:
        """Fetch earnings info for a single symbol"""
        try:
            ticker = yf.Ticker(symbol)
            calendar = ticker.calendar

            if calendar is None or calendar.empty:
                return None

            # Get earnings date
            earnings_date = None
            if 'Earnings Date' in calendar.index:
                earnings_dates = calendar.loc['Earnings Date']
                if hasattr(earnings_dates, 'iloc') and len(earnings_dates) > 0:
                    earnings_date = earnings_dates.iloc[0]
                elif isinstance(earnings_dates, (datetime,)):
                    earnings_date = earnings_dates

            if earnings_date is None:
                return None

            # Convert to string if needed
            if hasattr(earnings_date, 'strftime'):
                earnings_date_str = earnings_date.strftime('%Y-%m-%d')
                earnings_dt = earnings_date
            else:
                earnings_date_str = str(earnings_date)[:10]
                earnings_dt = datetime.fromisoformat(earnings_date_str)

            # Calculate days until
            days_until = (earnings_dt - datetime.now()).days

            # Get estimates if available
            eps_estimate = None
            revenue_estimate = None
            if 'Earnings Average' in calendar.index:
                eps_estimate = float(calendar.loc['Earnings Average'].iloc[0]) if not calendar.loc['Earnings Average'].empty else None
            if 'Revenue Average' in calendar.index:
                revenue_estimate = float(calendar.loc['Revenue Average'].iloc[0]) if not calendar.loc['Revenue Average'].empty else None

            # Get company name
            info = ticker.info
            name = info.get('shortName', info.get('longName', symbol))

            # Determine time of day (rough heuristic)
            time_of_day = "Unknown"
            # Some APIs provide this, otherwise we'd need to look it up

            return EarningsEvent(
                symbol=symbol,
                name=name[:30] if name else symbol,  # Truncate long names
                earnings_date=earnings_date_str,
                time_of_day=time_of_day,
                days_until=days_until,
                eps_estimate=eps_estimate,
                revenue_estimate=revenue_estimate,
                is_in_portfolio=symbol in self.portfolio_symbols
            )

        except Exception as e:
            logger.debug(f"Error fetching earnings for {symbol}: {e}")
            return None

    def get_upcoming_earnings(self, days: int = 14) -> List[EarningsEvent]:
        """Get earnings events in the next N days"""
        upcoming = []
        for event in self.earnings_events.values():
            if 0 <= event.days_until <= days:
                event.is_in_portfolio = event.symbol in self.portfolio_symbols
                upcoming.append(event)

        return sorted(upcoming, key=lambda e: e.days_until)

    def get_portfolio_earnings(self) -> List[EarningsEvent]:
        """Get earnings for symbols currently in portfolio"""
        return [
            e for e in self.earnings_events.values()
            if e.symbol in self.portfolio_symbols and e.days_until >= 0
        ]

    def get_this_week_earnings(self) -> List[EarningsEvent]:
        """Get earnings happening this week"""
        return self.get_upcoming_earnings(days=7)

    async def send_earnings_alert(self) -> bool:
        """Send Telegram alert for imminent earnings"""
        if not TELEGRAM_AVAILABLE:
            return False

        portfolio_earnings = [e for e in self.get_portfolio_earnings() if e.days_until <= 2]
        if not portfolio_earnings:
            return False

        try:
            notifier = get_notifier()
            if not notifier:
                return False

            lines = ["📊 <b>EARNINGS ALERT</b>\n"]
            lines.append("You have positions with upcoming earnings:\n")

            for event in portfolio_earnings:
                days_str = "TODAY" if event.days_until == 0 else f"in {event.days_until} days"
                lines.append(f"<b>{event.symbol}</b> - {days_str}")
                lines.append(f"  {event.name}")
                if event.eps_estimate:
                    lines.append(f"  EPS Est: ${event.eps_estimate:.2f}")
                lines.append("")

            lines.append("<i>⚠️ Consider your position size for binary events</i>")

            await notifier.send_message("\n".join(lines))
            return True

        except Exception as e:
            logger.error(f"Error sending earnings alert: {e}")
            return False

    def format_calendar_display(self, days: int = 14) -> str:
        """Format earnings calendar for display"""
        lines = []
        lines.append("=" * 60)
        lines.append("            EARNINGS CALENDAR")
        lines.append("=" * 60)

        upcoming = self.get_upcoming_earnings(days)

        if not upcoming:
            lines.append(f"\n  No earnings in next {days} days for watched symbols")
            lines.append(f"  Watchlist: {len(self.watchlist)} symbols")
            lines.append("")
            return "\n".join(lines)

        # Group by days
        today = [e for e in upcoming if e.days_until == 0]
        tomorrow = [e for e in upcoming if e.days_until == 1]
        this_week = [e for e in upcoming if 2 <= e.days_until <= 7]
        later = [e for e in upcoming if e.days_until > 7]

        if today:
            lines.append("\n  📅 TODAY:")
            for e in today:
                portfolio_marker = " [IN PORTFOLIO]" if e.is_in_portfolio else ""
                lines.append(f"    • {e.symbol:<6} {e.name[:25]:<25}{portfolio_marker}")

        if tomorrow:
            lines.append("\n  📅 TOMORROW:")
            for e in tomorrow:
                portfolio_marker = " [IN PORTFOLIO]" if e.is_in_portfolio else ""
                lines.append(f"    • {e.symbol:<6} {e.name[:25]:<25}{portfolio_marker}")

        if this_week:
            lines.append("\n  📅 THIS WEEK:")
            for e in this_week:
                portfolio_marker = " [PORT]" if e.is_in_portfolio else ""
                lines.append(f"    • {e.symbol:<6} {e.earnings_date[5:]} ({e.days_until}d){portfolio_marker}")

        if later:
            lines.append(f"\n  📅 NEXT WEEK+ ({len(later)} events):")
            for e in later[:5]:  # Show first 5
                lines.append(f"    • {e.symbol:<6} {e.earnings_date[5:]} ({e.days_until}d)")
            if len(later) > 5:
                lines.append(f"    ... and {len(later) - 5} more")

        # Portfolio warnings
        portfolio_soon = [e for e in self.get_portfolio_earnings() if e.days_until <= 3]
        if portfolio_soon:
            lines.append("\n  ⚠️  PORTFOLIO EARNINGS SOON:")
            for e in portfolio_soon:
                lines.append(f"    🚨 {e.symbol} in {e.days_until} days")

        lines.append(f"\n  Watching: {len(self.watchlist)} symbols")
        lines.append("")

        return "\n".join(lines)


# Singleton
_calendar_instance: Optional[EarningsCalendar] = None

def get_earnings_calendar() -> EarningsCalendar:
    """Get or create earnings calendar instance"""
    global _calendar_instance
    if _calendar_instance is None:
        _calendar_instance = EarningsCalendar()
    return _calendar_instance


async def run_earnings_monitor():
    """Run earnings calendar update and display"""
    calendar = get_earnings_calendar()

    print("Fetching earnings data...")
    await calendar.refresh_earnings()

    print(calendar.format_calendar_display())


if __name__ == "__main__":
    asyncio.run(run_earnings_monitor())

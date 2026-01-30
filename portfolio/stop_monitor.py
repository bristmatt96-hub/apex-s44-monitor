"""
Stop Loss Monitor

Monitors positions approaching stop losses and sends alerts.
Capital preservation rule #1: Never let winners turn into losers.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger

from portfolio.position_tracker import get_position_tracker, Position

# Try to import Telegram notifier
try:
    from utils.telegram_notifier import get_notifier
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


@dataclass
class StopAlert:
    """A stop loss alert"""
    symbol: str
    current_price: float
    stop_price: float
    distance_pct: float
    alert_level: str  # "WARNING", "CRITICAL", "BREACHED"
    timestamp: str
    position_value: float
    potential_loss: float


class StopLossMonitor:
    """
    Monitors all positions for stop loss proximity.

    Alert levels:
    - WARNING: Within 5% of stop
    - CRITICAL: Within 2% of stop
    - BREACHED: Price has crossed stop

    Rules:
    - A stop is not a suggestion, it's a rule
    - Don't move stops to avoid taking losses
    - When in doubt, reduce position size
    """

    # Alert thresholds (as percentage from stop)
    WARNING_THRESHOLD = 5.0   # 5% from stop
    CRITICAL_THRESHOLD = 2.0  # 2% from stop

    # Cooldown to prevent alert spam (seconds)
    ALERT_COOLDOWN = 300  # 5 minutes

    def __init__(self):
        self.tracker = get_position_tracker()
        self.alerts: List[StopAlert] = []
        self._last_alert_time: Dict[str, datetime] = {}

    async def check_all_positions(self) -> List[StopAlert]:
        """Check all positions for stop proximity"""
        # Refresh prices first
        await self.tracker.refresh_prices()

        alerts = []

        for pos in self.tracker.positions.values():
            alert = self._check_position(pos)
            if alert:
                alerts.append(alert)

        self.alerts = alerts
        return alerts

    def _check_position(self, pos: Position) -> Optional[StopAlert]:
        """Check single position for stop proximity"""
        if not pos.stop_loss or pos.current_price <= 0:
            return None

        # Calculate distance to stop (as percentage)
        distance_pct = ((pos.current_price - pos.stop_loss) / pos.current_price) * 100

        # For short positions, logic is reversed
        # (but for simplicity, we assume long positions here)

        # Determine alert level
        if distance_pct <= 0:
            alert_level = "BREACHED"
        elif distance_pct <= self.CRITICAL_THRESHOLD:
            alert_level = "CRITICAL"
        elif distance_pct <= self.WARNING_THRESHOLD:
            alert_level = "WARNING"
        else:
            return None  # No alert needed

        # Calculate potential loss if stop is hit
        potential_loss = (pos.current_price - pos.stop_loss) * pos.quantity
        if pos.position_type.value.startswith("options"):
            potential_loss *= 100

        return StopAlert(
            symbol=pos.symbol,
            current_price=pos.current_price,
            stop_price=pos.stop_loss,
            distance_pct=distance_pct,
            alert_level=alert_level,
            timestamp=datetime.now().isoformat(),
            position_value=pos.market_value,
            potential_loss=potential_loss
        )

    def _should_send_alert(self, symbol: str) -> bool:
        """Check if we should send alert (cooldown check)"""
        last_time = self._last_alert_time.get(symbol)
        if not last_time:
            return True

        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed >= self.ALERT_COOLDOWN

    async def send_telegram_alerts(self) -> int:
        """Send Telegram alerts for critical stops"""
        if not TELEGRAM_AVAILABLE:
            return 0

        try:
            notifier = get_notifier()
            if not notifier:
                return 0

            sent = 0
            for alert in self.alerts:
                if alert.alert_level in ["CRITICAL", "BREACHED"]:
                    if self._should_send_alert(alert.symbol):
                        message = self._format_alert_message(alert)
                        await notifier.send_message(message)
                        self._last_alert_time[alert.symbol] = datetime.now()
                        sent += 1

            return sent

        except Exception as e:
            logger.error(f"Error sending stop alerts: {e}")
            return 0

    def _format_alert_message(self, alert: StopAlert) -> str:
        """Format alert for Telegram"""
        if alert.alert_level == "BREACHED":
            emoji = "🚨🚨🚨"
            header = "STOP BREACHED"
        elif alert.alert_level == "CRITICAL":
            emoji = "🚨"
            header = "CRITICAL - NEAR STOP"
        else:
            emoji = "⚠️"
            header = "APPROACHING STOP"

        return f"""
{emoji} <b>{header}</b> {emoji}

<b>Symbol:</b> {alert.symbol}
<b>Current:</b> ${alert.current_price:.2f}
<b>Stop:</b> ${alert.stop_price:.2f}
<b>Distance:</b> {alert.distance_pct:.1f}%

<b>Potential Loss:</b> ${alert.potential_loss:.2f}

⚡ <i>A stop is a rule, not a suggestion</i>

⏰ {datetime.now().strftime('%H:%M:%S')}
"""

    def get_stop_summary(self) -> Dict:
        """Get summary of stop status across all positions"""
        total_positions = len(self.tracker.positions)
        with_stops = sum(1 for p in self.tracker.positions.values() if p.stop_loss)
        without_stops = total_positions - with_stops

        warning_count = len([a for a in self.alerts if a.alert_level == "WARNING"])
        critical_count = len([a for a in self.alerts if a.alert_level == "CRITICAL"])
        breached_count = len([a for a in self.alerts if a.alert_level == "BREACHED"])

        total_at_risk = sum(a.potential_loss for a in self.alerts)

        return {
            'total_positions': total_positions,
            'positions_with_stops': with_stops,
            'positions_without_stops': without_stops,
            'warning_alerts': warning_count,
            'critical_alerts': critical_count,
            'breached_alerts': breached_count,
            'total_at_risk': total_at_risk
        }

    def format_monitor_display(self) -> str:
        """Format stop monitor dashboard"""
        lines = []
        lines.append("=" * 60)
        lines.append("             STOP LOSS MONITOR")
        lines.append("=" * 60)

        summary = self.get_stop_summary()

        # Status overview
        lines.append(f"\n  Positions: {summary['total_positions']}")
        lines.append(f"  With Stops: {summary['positions_with_stops']}")

        if summary['positions_without_stops'] > 0:
            lines.append(f"  WITHOUT STOPS: {summary['positions_without_stops']} ⚠️")

        # Alert status
        lines.append("\n  ALERT STATUS:")
        if summary['breached_alerts'] > 0:
            lines.append(f"    🚨 BREACHED: {summary['breached_alerts']}")
        if summary['critical_alerts'] > 0:
            lines.append(f"    🚨 CRITICAL: {summary['critical_alerts']}")
        if summary['warning_alerts'] > 0:
            lines.append(f"    ⚠️  WARNING: {summary['warning_alerts']}")

        if not self.alerts:
            lines.append("    ✅ All positions safe")

        # At risk amount
        if summary['total_at_risk'] > 0:
            lines.append(f"\n  Total at risk: ${summary['total_at_risk']:,.2f}")

        # Position details
        if self.alerts:
            lines.append("\n  POSITIONS NEAR STOP:")
            lines.append("  " + "-" * 56)

            for alert in sorted(self.alerts, key=lambda a: a.distance_pct):
                status_emoji = "🚨" if alert.alert_level in ["CRITICAL", "BREACHED"] else "⚠️"
                lines.append(
                    f"  {status_emoji} {alert.symbol:<8} "
                    f"${alert.current_price:>8.2f} → ${alert.stop_price:.2f} "
                    f"({alert.distance_pct:+.1f}%)"
                )

            lines.append("  " + "-" * 56)

        # Capital preservation reminder
        lines.append("\n  💡 \"Protect your capital - it's the only thing you can't replace\"")
        lines.append("")

        return "\n".join(lines)


async def run_stop_monitor(interval: int = 60, telegram: bool = True):
    """Run continuous stop monitoring"""
    monitor = StopLossMonitor()

    logger.info("Starting Stop Loss Monitor...")

    while True:
        try:
            # Check positions
            alerts = await monitor.check_all_positions()

            # Display
            print("\033[2J\033[H")  # Clear screen
            print(monitor.format_monitor_display())

            # Send Telegram for critical alerts
            if telegram and alerts:
                sent = await monitor.send_telegram_alerts()
                if sent > 0:
                    logger.info(f"Sent {sent} stop alerts to Telegram")

            await asyncio.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Stop monitor stopped")
            break
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            await asyncio.sleep(interval)


# Singleton
_monitor_instance: Optional[StopLossMonitor] = None

def get_stop_monitor() -> StopLossMonitor:
    """Get or create stop monitor instance"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = StopLossMonitor()
    return _monitor_instance


if __name__ == "__main__":
    asyncio.run(run_stop_monitor())

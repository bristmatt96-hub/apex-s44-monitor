"""
Credit Catalyst - Alerts Layer

Notification delivery:
- Telegram bot for real-time alerts and morning briefs
"""

from alerts.telegram import TelegramNotifier, get_notifier

__all__ = ["TelegramNotifier", "get_notifier"]

"""
Telegram Notifications for Credit Catalyst

Sends credit alerts, morning briefs, and event notifications.
Refactored from utils/telegram_notifier.py for credit-focused use.
"""

import asyncio
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
from loguru import logger

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


class TelegramNotifier:
    """
    Sends credit notifications to Telegram.

    Setup:
    1. Create a new bot via @BotFather on Telegram
    2. Get your bot token
    3. Create a channel/group and add the bot as admin
    4. Get the chat ID
    """

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.debug("Telegram notifications disabled - missing bot_token or chat_id")

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        if not self.enabled or not AIOHTTP_AVAILABLE:
            return False

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                }
                async with session.post(
                    f"{self.base_url}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        return True
                    error = await response.text()
                    logger.error("Telegram error: {}", error)
                    return False
        except Exception as e:
            logger.error("Failed to send Telegram message: {}", e)
            return False

    async def notify_credit_event(
        self,
        company: str,
        event_type: str,
        headline: str,
        source: str = "",
        priority: str = "medium",
        action_required: bool = False,
    ) -> bool:
        """Send credit event notification."""
        emoji = {"high": "🚨", "medium": "⚠️", "low": "ℹ️"}.get(priority, "ℹ️")

        message = (
            f"{emoji} <b>CREDIT EVENT: {event_type}</b>\n\n"
            f"<b>{company}</b>\n"
            f"{headline}\n\n"
            f"<i>Source: {source}</i>\n"
        )
        if action_required:
            message += "🎯 <b>ACTION REQUIRED</b>\n"
        message += f"⏰ {datetime.now().strftime('%H:%M:%S %d-%b-%Y')}"

        return await self.send_message(message)

    async def notify_rating_action(
        self,
        company: str,
        agency: str,
        action: str,
        old_rating: str = "",
        new_rating: str = "",
        outlook: str = "",
    ) -> bool:
        """Send rating action notification."""
        message = (
            f"📊 <b>RATING ACTION</b>\n\n"
            f"<b>{company}</b>\n"
            f"<b>Agency:</b> {agency}\n"
            f"<b>Action:</b> {action}\n"
        )
        if old_rating and new_rating:
            message += f"<b>Rating:</b> {old_rating} → {new_rating}\n"
        if outlook:
            message += f"<b>Outlook:</b> {outlook}\n"
        message += f"\n⏰ {datetime.now().strftime('%H:%M:%S %d-%b-%Y')}"

        return await self.send_message(message)

    async def notify_morning_brief(
        self,
        brief_text: str,
    ) -> bool:
        """Send the morning brief."""
        return await self.send_message(brief_text)

    async def notify_filing(
        self,
        company: str,
        filing_type: str,
        headline: str,
        source: str = "",
        credit_relevant: bool = True,
    ) -> bool:
        """Send regulatory filing notification."""
        emoji = "📄" if credit_relevant else "📋"
        message = (
            f"{emoji} <b>FILING: {filing_type}</b>\n\n"
            f"<b>{company}</b>\n"
            f"{headline}\n\n"
            f"<i>Source: {source}</i>\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S %d-%b-%Y')}"
        )
        return await self.send_message(message)

    async def notify_spread_alert(
        self,
        company: str,
        current_spread: float,
        change_bps: float,
        direction: str = "",
    ) -> bool:
        """Send CDS spread movement alert."""
        emoji = "📈" if change_bps > 0 else "📉"
        message = (
            f"{emoji} <b>SPREAD ALERT</b>\n\n"
            f"<b>{company}</b>\n"
            f"<b>Spread:</b> {current_spread:.0f}bps ({change_bps:+.0f}bps)\n"
        )
        if direction:
            message += f"<b>Recommendation:</b> {direction}\n"
        message += f"⏰ {datetime.now().strftime('%H:%M:%S %d-%b-%Y')}"

        return await self.send_message(message)


# Singleton instance
_notifier_instance: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    """Get or create the Telegram notifier instance."""
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = TelegramNotifier()
    return _notifier_instance

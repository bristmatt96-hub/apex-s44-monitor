"""
Telegram Notifications for Trading System
Sends alerts for trade entries and exits
"""
import asyncio
import aiohttp
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger


class TelegramNotifier:
    """
    Sends trade notifications to Telegram.

    Setup:
    1. Create a new bot via @BotFather on Telegram
    2. Get your bot token
    3. Create a channel/group and add the bot as admin
    4. Get the chat ID (send a message, then check:
       https://api.telegram.org/bot<TOKEN>/getUpdates)
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.enabled = bool(bot_token and chat_id)

        if not self.enabled:
            logger.warning("Telegram notifications disabled - missing bot_token or chat_id")

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat"""
        if not self.enabled:
            return False

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True
                }

                async with session.post(
                    f"{self.base_url}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return True
                    else:
                        error = await response.text()
                        logger.error(f"Telegram error: {error}")
                        return False

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def notify_trade_entry(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        market_type: str,
        strategy: str,
        risk_reward: float,
        confidence: float,
        rationale: str,
        stop_loss: Optional[float] = None,
        target: Optional[float] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Send trade entry notification"""

        # Emoji based on side
        emoji = "🟢" if side.lower() == "buy" else "🔴"
        direction = "LONG" if side.lower() == "buy" else "SHORT"

        # Format message
        message = f"""
{emoji} <b>TRADE ENTRY</b> {emoji}

<b>Symbol:</b> {symbol}
<b>Direction:</b> {direction}
<b>Quantity:</b> {quantity}
<b>Entry Price:</b> ${entry_price:.4f}
<b>Market:</b> {market_type.upper()}

<b>Strategy:</b> {strategy}
<b>Risk/Reward:</b> {risk_reward:.1f}:1
<b>Confidence:</b> {confidence:.0%}
"""

        if stop_loss:
            message += f"<b>Stop Loss:</b> ${stop_loss:.4f}\n"
        if target:
            message += f"<b>Target:</b> ${target:.4f}\n"

        message += f"""
<b>Rationale:</b>
<i>{rationale}</i>

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""

        return await self.send_message(message)

    async def notify_trade_exit(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        exit_price: float,
        market_type: str,
        pnl: float,
        pnl_pct: float,
        hold_time: str,
        exit_reason: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Send trade exit notification"""

        # Emoji based on P&L
        if pnl > 0:
            emoji = "💰"
            result = "WIN"
        elif pnl < 0:
            emoji = "📉"
            result = "LOSS"
        else:
            emoji = "➖"
            result = "BREAKEVEN"

        direction = "LONG" if side.lower() == "buy" else "SHORT"

        message = f"""
{emoji} <b>TRADE EXIT - {result}</b> {emoji}

<b>Symbol:</b> {symbol}
<b>Direction:</b> {direction}
<b>Quantity:</b> {quantity}

<b>Entry:</b> ${entry_price:.4f}
<b>Exit:</b> ${exit_price:.4f}

<b>P&L:</b> ${pnl:+.2f} ({pnl_pct:+.2f}%)
<b>Hold Time:</b> {hold_time}

<b>Exit Reason:</b> {exit_reason}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""

        return await self.send_message(message)

    async def notify_daily_summary(
        self,
        total_trades: int,
        winners: int,
        losers: int,
        total_pnl: float,
        total_pnl_pct: float,
        best_trade: Optional[Dict] = None,
        worst_trade: Optional[Dict] = None
    ) -> bool:
        """Send daily trading summary"""

        win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
        emoji = "📈" if total_pnl >= 0 else "📉"

        message = f"""
{emoji} <b>DAILY SUMMARY</b> {emoji}

<b>Total Trades:</b> {total_trades}
<b>Winners:</b> {winners} ✅
<b>Losers:</b> {losers} ❌
<b>Win Rate:</b> {win_rate:.1f}%

<b>Daily P&L:</b> ${total_pnl:+.2f} ({total_pnl_pct:+.2f}%)
"""

        if best_trade:
            message += f"\n<b>Best Trade:</b> {best_trade['symbol']} (+${best_trade['pnl']:.2f})"
        if worst_trade:
            message += f"\n<b>Worst Trade:</b> {worst_trade['symbol']} (${worst_trade['pnl']:.2f})"

        message += f"\n\n📅 {datetime.now().strftime('%Y-%m-%d')}"

        return await self.send_message(message)

    async def notify_alert(
        self,
        alert_type: str,
        message_text: str,
        severity: str = "info"
    ) -> bool:
        """Send general alert"""

        emojis = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "🚨",
            "success": "✅"
        }

        emoji = emojis.get(severity, "ℹ️")

        message = f"""
{emoji} <b>{alert_type.upper()}</b>

{message_text}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""

        return await self.send_message(message)

    # =============================================
    # CREDIT CATALYST SPECIFIC NOTIFICATIONS
    # =============================================

    async def notify_edge_score(
        self,
        company: str,
        ticker: str,
        total_score: float,
        recommendation: str,
        aggression: float,
        direction: str,
        components: Dict[str, float],
        thesis: str
    ) -> bool:
        """Send edge score notification for credit opportunity"""

        # Emoji based on score
        if total_score >= 8:
            emoji = "🔥"
        elif total_score >= 7:
            emoji = "📊"
        elif total_score >= 6:
            emoji = "📈"
        else:
            emoji = "👀"

        message = f"""
{emoji} <b>EDGE SCORE: {company}</b>

<b>Ticker:</b> {ticker}
<b>Total Score:</b> {total_score}/10
<b>Recommendation:</b> {recommendation}
<b>Aggression:</b> {aggression}x

<b>COMPONENTS:</b>
• Credit Signal: {components.get('credit', 0)}/10
• Psychology: {components.get('psychology', 0)}/10
• Options: {components.get('options', 0)}/10
• Catalyst: {components.get('catalyst', 0)}/10
• Pattern: {components.get('pattern', 0)}/10

<b>TRADE:</b> {direction}
<b>Size:</b> {aggression}x standard

<b>THESIS:</b>
<i>{thesis}</i>

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""
        return await self.send_message(message)

    async def notify_credit_event(
        self,
        company: str,
        event_type: str,
        headline: str,
        source: str,
        priority: str = "medium",
        playbook: str = None,
        action_required: bool = False
    ) -> bool:
        """Send credit event notification"""

        priority_emojis = {
            "high": "🚨",
            "medium": "⚠️",
            "low": "ℹ️"
        }
        emoji = priority_emojis.get(priority, "ℹ️")

        message = f"""
{emoji} <b>CREDIT EVENT</b>

<b>Company:</b> {company}
<b>Event:</b> {event_type}
<b>Priority:</b> {priority.upper()}
"""
        if playbook:
            message += f"<b>Playbook:</b> {playbook}\n"

        message += f"""
<b>Headline:</b>
{headline}

<b>Source:</b> {source}
"""
        if action_required:
            message += "\n🎯 <b>ACTION REQUIRED</b> - Review opportunity"

        message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC"

        return await self.send_message(message)

    async def notify_options_trade(
        self,
        company: str,
        ticker: str,
        direction: str,
        strike: float,
        expiry: str,
        contracts: int,
        premium: float,
        total_cost: float,
        edge_score: float,
        components: Dict[str, float],
        thesis: str,
        max_loss: float
    ) -> bool:
        """Send options trade notification with full edge breakdown"""

        emoji = "📈" if "CALL" in direction else "📉"

        message = f"""
{emoji} <b>TRADE OPENED</b> {emoji}

<b>Ticker:</b> {ticker} ({company})
<b>Direction:</b> {direction}
<b>Strike:</b> ${strike:.2f}
<b>Expiry:</b> {expiry}
<b>Size:</b> {contracts} contracts
<b>Cost:</b> ${total_cost:.2f}

<b>EDGE SCORE: {edge_score}/10</b>

Credit signal: {components.get('credit', 0)}/10
Psychology: {components.get('psychology', 0)}/10
Options: {components.get('options', 0)}/10
Catalyst: {components.get('catalyst', 0)}/10
Pattern: {components.get('pattern', 0)}/10

<b>THESIS:</b>
<i>{thesis}</i>

<b>Max Loss:</b> ${max_loss:.2f}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""
        return await self.send_message(message)

    async def notify_risk_breach(
        self,
        violation_type: str,
        current_value: float,
        limit_value: float,
        action_taken: str
    ) -> bool:
        """Send risk limit breach notification"""

        message = f"""
🚨 <b>RISK LIMIT BREACH</b> 🚨

<b>Violation:</b> {violation_type}
<b>Current:</b> {current_value}
<b>Limit:</b> {limit_value}

<b>Action Taken:</b> {action_taken}

⚠️ Trading may be suspended until limits are restored.

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""
        return await self.send_message(message)

    async def notify_morning_brief(
        self,
        date: str,
        watchlist_count: int,
        high_priority: List[Dict],
        upcoming_catalysts: List[Dict],
        market_conditions: str
    ) -> bool:
        """Send morning briefing with credit watchlist status"""

        message = f"""
☀️ <b>MORNING BRIEF - {date}</b>

<b>Watchlist:</b> {watchlist_count} names
<b>Market:</b> {market_conditions}

<b>HIGH PRIORITY:</b>
"""
        for item in high_priority[:5]:
            message += f"• {item['company']}: {item['note']}\n"

        if upcoming_catalysts:
            message += "\n<b>UPCOMING CATALYSTS:</b>\n"
            for cat in upcoming_catalysts[:5]:
                message += f"• {cat['company']}: {cat['event']} ({cat['date']})\n"

        message += f"\n⏰ {datetime.now().strftime('%H:%M')} UTC"

        return await self.send_message(message)


# Singleton instance
_notifier_instance: Optional[TelegramNotifier] = None


def get_notifier() -> Optional[TelegramNotifier]:
    """Get or create the Telegram notifier instance"""
    global _notifier_instance

    if _notifier_instance is None:
        # Load from environment
        import os
        from dotenv import load_dotenv
        load_dotenv()

        bot_token = os.getenv("TELEGRAM_TRADE_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_TRADE_CHAT_ID", "")

        if bot_token and chat_id:
            _notifier_instance = TelegramNotifier(bot_token, chat_id)
        else:
            logger.warning("Telegram trade notifications not configured")
            return None

    return _notifier_instance


def init_notifier(bot_token: str, chat_id: str) -> TelegramNotifier:
    """Initialize notifier with specific credentials"""
    global _notifier_instance
    _notifier_instance = TelegramNotifier(bot_token, chat_id)
    return _notifier_instance


# Test function
async def test_notifications():
    """Test the notification system"""
    import os
    from dotenv import load_dotenv
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_TRADE_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_TRADE_CHAT_ID")

    if not bot_token or not chat_id:
        print("Set TELEGRAM_TRADE_BOT_TOKEN and TELEGRAM_TRADE_CHAT_ID in .env")
        return

    notifier = TelegramNotifier(bot_token, chat_id)

    # Test entry
    await notifier.notify_trade_entry(
        symbol="AAPL",
        side="buy",
        quantity=10,
        entry_price=185.50,
        market_type="equity",
        strategy="momentum_breakout",
        risk_reward=3.2,
        confidence=0.72,
        rationale="Breaking out of 20-day range with volume surge. RSI at 62 showing momentum without being overbought. Strong tech sector today.",
        stop_loss=182.00,
        target=196.00
    )

    await asyncio.sleep(2)

    # Test exit
    await notifier.notify_trade_exit(
        symbol="AAPL",
        side="buy",
        quantity=10,
        entry_price=185.50,
        exit_price=193.25,
        market_type="equity",
        pnl=77.50,
        pnl_pct=4.18,
        hold_time="2d 4h",
        exit_reason="Target reached"
    )

    print("Test notifications sent!")


if __name__ == "__main__":
    asyncio.run(test_notifications())

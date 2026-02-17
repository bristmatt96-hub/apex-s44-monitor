"""
Briefing Agent

Generates daily morning briefs, real-time alerts on material changes,
and weekly strategy summaries. Formats output for Telegram and web dashboard.

Based on monitors/morning_brief.py, enhanced with Claude API integration.
"""

import os
import json
import requests
import feedparser
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from core.config import settings


class BriefingAgent:
    """
    Generates structured briefings from credit data and events.

    Outputs:
    - Morning brief: market overview + top 5 ideas + regime assessment
    - Real-time alerts: filing detected → analysed → recommendation
    - Weekly digest: strategy summary + performance review
    """

    RSS_FEEDS = [
        ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
        ("FT Markets", "https://www.ft.com/markets?format=rss"),
    ]

    def __init__(self):
        self.snapshots_path = Path("snapshots")
        self._client = None
        self._telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    def _get_client(self):
        """Lazy-init Anthropic client."""
        if self._client is None and ANTHROPIC_AVAILABLE:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def _send_telegram(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send message via Telegram."""
        if not self._telegram_token or not self._telegram_chat_id:
            logger.debug("Telegram not configured")
            return False

        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
        payload = {
            "chat_id": self._telegram_chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.error("Telegram send failed: {}", e)
            return False

    def _fetch_headlines(self, max_per_feed: int = 5) -> List[Dict]:
        """Fetch recent headlines from RSS feeds."""
        headlines = []
        for feed_name, feed_url in self.RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:max_per_feed]:
                    headlines.append({
                        "source": feed_name,
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                    })
            except Exception as e:
                logger.debug("Failed to fetch {}: {}", feed_name, e)
        return headlines

    def _load_snapshots_summary(self) -> List[Dict]:
        """Load brief summary of all snapshots."""
        summaries = []
        if not self.snapshots_path.exists():
            return summaries
        for f in sorted(self.snapshots_path.glob("*.json")):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                    summaries.append({
                        "name": data.get("company_name", f.stem),
                        "sector": data.get("sector", ""),
                        "rating": data.get("ratings", {}).get("composite", "NR"),
                    })
            except Exception:
                continue
        return summaries

    async def generate_morning_brief(
        self,
        assessments: Optional[List] = None,
        macro_data: Optional[Dict] = None,
    ) -> str:
        """
        Generate the daily morning brief.

        Includes:
        - Market overview (spreads, volumes, key moves)
        - Top 5 credit ideas with conviction
        - Regime assessment
        - Key events today
        """
        headlines = self._fetch_headlines()
        snapshots = self._load_snapshots_summary()
        client = self._get_client()

        # Build the brief
        now = datetime.now()
        brief_parts = [
            f"<b>Credit Catalyst Morning Brief</b>",
            f"<i>{now.strftime('%A %d %B %Y')}</i>",
            "",
        ]

        if client and headlines:
            # Use Claude to summarise headlines
            try:
                headline_text = "\n".join(
                    f"- {h['title']} ({h['source']})" for h in headlines[:15]
                )
                response = client.messages.create(
                    model=settings.llm.model,
                    max_tokens=512,
                    system=(
                        "You are a credit market strategist. Summarise these "
                        "headlines in 3-4 bullet points focusing on implications "
                        "for European credit markets (iTraxx, CDS, HY bonds)."
                    ),
                    messages=[{
                        "role": "user",
                        "content": f"Headlines:\n{headline_text}",
                    }],
                )
                brief_parts.append("<b>Market Overview:</b>")
                brief_parts.append(response.content[0].text)
                brief_parts.append("")
            except Exception as e:
                logger.error("Claude brief generation failed: {}", e)
        else:
            # Fallback: just list headlines
            brief_parts.append("<b>Headlines:</b>")
            for h in headlines[:5]:
                brief_parts.append(f"• {h['title']}")
            brief_parts.append("")

        if assessments:
            brief_parts.append("<b>Top Credit Ideas:</b>")
            sorted_ideas = sorted(assessments, key=lambda a: a.conviction, reverse=True)
            for i, a in enumerate(sorted_ideas[:5], 1):
                direction_emoji = {"long": "🟢", "short": "🔴", "flat": "⚪"}.get(a.direction, "⚪")
                brief_parts.append(
                    f"{i}. {direction_emoji} <b>{a.entity_name}</b> — "
                    f"{a.direction.upper()} (conviction {a.conviction}/5) "
                    f"| Fair spread: {a.fair_spread_bps:.0f}bps"
                )
            brief_parts.append("")

        brief_parts.append(f"<i>Universe: {len(snapshots)} names tracked</i>")

        return "\n".join(brief_parts)

    async def send_morning_brief(self, **kwargs) -> bool:
        """Generate and send morning brief via Telegram."""
        brief = await self.generate_morning_brief(**kwargs)
        return self._send_telegram(brief)

    async def send_alert(
        self,
        entity_name: str,
        alert_type: str,
        detail: str,
        priority: str = "medium",
    ) -> bool:
        """
        Send a real-time credit alert.

        Args:
            entity_name: Company name
            alert_type: e.g. "RATING_ACTION", "FILING", "CREDIT_EVENT"
            detail: Alert details
            priority: low / medium / high
        """
        priority_icon = {"high": "🚨", "medium": "⚠️", "low": "ℹ️"}.get(priority, "ℹ️")
        message = (
            f"{priority_icon} <b>CREDIT ALERT: {alert_type}</b>\n"
            f"<b>{entity_name}</b>\n\n"
            f"{detail}\n\n"
            f"<i>{datetime.now().strftime('%H:%M:%S %d-%b-%Y')}</i>"
        )
        return self._send_telegram(message)

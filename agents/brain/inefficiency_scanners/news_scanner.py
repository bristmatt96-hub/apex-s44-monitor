"""
Geopolitical & Market News Scanner

Monitors news for events that impact risk positions:
- China/US tensions, tariffs, trade war
- War, conflict, military action
- Fed/central bank surprises
- Political instability
- Black swan events

PHILOSOPHY:
When geopolitical risk rises → REDUCE LONG RISK POSITIONS
Headlines move markets before fundamentals catch up.

NEWS SOURCES:
- RSS feeds from major financial news
- Can integrate with NewsAPI, Alpha Vantage News, etc.
"""
import asyncio
import os
import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta
from loguru import logger

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

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
class NewsAlert:
    """A news item that may impact markets"""
    headline: str
    source: str
    timestamp: datetime
    risk_type: str  # "GEOPOLITICAL", "FED", "WAR", "TRADE", "POLITICAL"
    risk_level: str  # "HIGH", "MEDIUM", "LOW"
    impact: str  # "RISK_OFF", "RISK_ON", "SECTOR_SPECIFIC"
    affected_sectors: List[str]
    action: str  # What to do


class GeopoliticalNewsScanner:
    """
    Scans news feeds for geopolitical and market-moving events.

    When risk headlines detected:
    1. Alert via Telegram immediately
    2. Suggest reducing long risk positions
    3. Flag specific sectors at risk
    """

    # RSS feeds to monitor (free, no API key needed)
    NEWS_FEEDS = [
        # Reuters
        'https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best',
        # MarketWatch
        'https://feeds.marketwatch.com/marketwatch/topstories/',
        'https://feeds.marketwatch.com/marketwatch/marketpulse/',
        # CNBC
        'https://www.cnbc.com/id/100003114/device/rss/rss.html',  # Top News
        'https://www.cnbc.com/id/10001147/device/rss/rss.html',   # World
        # Yahoo Finance
        'https://finance.yahoo.com/news/rssindex',
        # Seeking Alpha
        'https://seekingalpha.com/market_currents.xml',
    ]

    # HIGH RISK keywords - immediate action needed
    HIGH_RISK_KEYWORDS = {
        # China/US tensions
        'china tariff', 'trade war', 'china sanction', 'taiwan invasion',
        'taiwan strait', 'china military', 'us china tension', 'decoupling',
        'china retaliation', 'rare earth ban',
        # War/Conflict
        'war declared', 'military strike', 'invasion', 'nuclear', 'missile launch',
        'war escalat', 'troops deploy', 'air strike', 'bomb', 'attack',
        # Financial crisis
        'bank run', 'bank collapse', 'lehman', 'credit freeze', 'liquidity crisis',
        'margin call', 'forced selling', 'circuit breaker',
        # Fed surprises
        'emergency rate', 'surprise hike', 'emergency cut', 'fed intervene',
        'qe end', 'qt accelerat',
        # Black swan
        'pandemic', 'outbreak', 'lockdown', 'shutdown', 'default', 'debt ceiling',
    }

    # MEDIUM RISK keywords - monitor closely
    MEDIUM_RISK_KEYWORDS = {
        # Trade tensions
        'tariff', 'trade tension', 'export ban', 'import restriction',
        'trade dispute', 'wto', 'dumping',
        # Geopolitical
        'sanction', 'embargo', 'diplomatic', 'tension', 'escalat',
        'protest', 'unrest', 'crisis',
        # Economic
        'recession', 'slowdown', 'contraction', 'layoff', 'job cut',
        'earnings miss', 'guidance cut', 'profit warning',
        # Fed/rates
        'rate hike', 'hawkish', 'inflation surge', 'cpi higher',
        'yield spike', 'bond selloff',
    }

    # RISK-ON keywords (positive for long positions)
    RISK_ON_KEYWORDS = {
        'trade deal', 'peace talk', 'ceasefire', 'rate cut', 'stimulus',
        'dovish', 'qe', 'bailout', 'rescue package', 'agreement reached',
        'tension ease', 'de-escalat',
    }

    # Sector-specific risk mapping
    SECTOR_RISKS = {
        'china': ['AAPL', 'NVDA', 'TSLA', 'NIO', 'BABA', 'PDD', 'JD', 'BIDU', 'FXI'],
        'semiconductor': ['NVDA', 'AMD', 'INTC', 'TSM', 'ASML', 'AVGO', 'QCOM', 'SMH', 'SOXL'],
        'oil': ['XOM', 'CVX', 'OXY', 'USO', 'XLE', 'SLB', 'HAL'],
        'defense': ['LMT', 'RTX', 'NOC', 'GD', 'BA', 'ITA'],
        'financials': ['JPM', 'BAC', 'GS', 'MS', 'C', 'XLF'],
        'tech': ['AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN', 'QQQ', 'XLK'],
        'gold': ['GLD', 'GDX', 'GDXJ', 'NEM', 'GOLD'],  # Usually RISK-OFF beneficiary
    }

    def __init__(self, send_telegram: bool = True):
        self.send_telegram = send_telegram
        self.last_scan = None
        self.seen_headlines: Set[str] = set()  # Avoid duplicate alerts
        self.active_alerts: List[NewsAlert] = []
        self.current_risk_level = "NORMAL"

        # NewsAPI key (optional, for enhanced coverage)
        self.newsapi_key = os.getenv("NEWSAPI_KEY", "")

    async def scan(self) -> List[Inefficiency]:
        """Main scan - check news feeds for risk events"""
        inefficiencies = []

        if not FEEDPARSER_AVAILABLE:
            logger.debug("feedparser not available - install with: pip install feedparser")
            return []

        # Scan RSS feeds
        alerts = await self._scan_rss_feeds()

        # If we have NewsAPI key, also check that
        if self.newsapi_key and AIOHTTP_AVAILABLE:
            api_alerts = await self._scan_newsapi()
            alerts.extend(api_alerts)

        # Filter to new alerts only
        new_alerts = [a for a in alerts if a.headline not in self.seen_headlines]

        if not new_alerts:
            return []

        # Process new alerts
        for alert in new_alerts:
            self.seen_headlines.add(alert.headline)
            self.active_alerts.append(alert)

            # Log the alert
            logger.warning(
                f"🚨 NEWS ALERT [{alert.risk_level}]: {alert.headline[:80]}... "
                f"({alert.risk_type} - {alert.impact})"
            )

            # Send Telegram for HIGH risk
            if alert.risk_level == "HIGH" and self.send_telegram:
                await self._send_telegram_alert(alert)

            # Create inefficiency
            ineff = self._create_news_inefficiency(alert)
            if ineff:
                inefficiencies.append(ineff)

        # Update overall risk level
        self._update_risk_level()

        self.last_scan = datetime.now()
        return inefficiencies

    async def _scan_rss_feeds(self) -> List[NewsAlert]:
        """Scan RSS feeds for news"""
        alerts = []

        for feed_url in self.NEWS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:10]:  # Check last 10 items
                    headline = entry.get('title', '')
                    summary = entry.get('summary', '')
                    text = f"{headline} {summary}".lower()

                    # Check for risk keywords
                    alert = self._analyze_headline(headline, text, feed_url)
                    if alert:
                        alerts.append(alert)

            except Exception as e:
                logger.debug(f"Error parsing feed {feed_url}: {e}")

        return alerts

    async def _scan_newsapi(self) -> List[NewsAlert]:
        """Scan NewsAPI for news (requires API key)"""
        if not self.newsapi_key:
            return []

        alerts = []

        try:
            async with aiohttp.ClientSession() as session:
                # Search for geopolitical news
                queries = ['china us tariff', 'war conflict', 'fed rate decision']

                for query in queries:
                    url = (
                        f"https://newsapi.org/v2/everything?"
                        f"q={query}&language=en&sortBy=publishedAt&pageSize=5"
                        f"&apiKey={self.newsapi_key}"
                    )

                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for article in data.get('articles', []):
                                headline = article.get('title', '')
                                text = f"{headline} {article.get('description', '')}".lower()

                                alert = self._analyze_headline(headline, text, 'NewsAPI')
                                if alert:
                                    alerts.append(alert)

        except Exception as e:
            logger.debug(f"NewsAPI error: {e}")

        return alerts

    def _analyze_headline(self, headline: str, text: str, source: str) -> Optional[NewsAlert]:
        """Analyze a headline for risk signals"""
        text_lower = text.lower()
        headline_lower = headline.lower()

        # Skip if already seen
        if headline in self.seen_headlines:
            return None

        # Check HIGH RISK keywords
        for keyword in self.HIGH_RISK_KEYWORDS:
            if keyword in text_lower:
                return NewsAlert(
                    headline=headline,
                    source=source,
                    timestamp=datetime.now(),
                    risk_type=self._categorize_risk(keyword),
                    risk_level="HIGH",
                    impact="RISK_OFF",
                    affected_sectors=self._get_affected_sectors(text_lower),
                    action="REDUCE LONG RISK POSITIONS IMMEDIATELY"
                )

        # Check MEDIUM RISK keywords
        for keyword in self.MEDIUM_RISK_KEYWORDS:
            if keyword in text_lower:
                return NewsAlert(
                    headline=headline,
                    source=source,
                    timestamp=datetime.now(),
                    risk_type=self._categorize_risk(keyword),
                    risk_level="MEDIUM",
                    impact="RISK_OFF",
                    affected_sectors=self._get_affected_sectors(text_lower),
                    action="Monitor closely, consider tightening stops"
                )

        # Check RISK-ON keywords
        for keyword in self.RISK_ON_KEYWORDS:
            if keyword in text_lower:
                return NewsAlert(
                    headline=headline,
                    source=source,
                    timestamp=datetime.now(),
                    risk_type=self._categorize_risk(keyword),
                    risk_level="LOW",
                    impact="RISK_ON",
                    affected_sectors=self._get_affected_sectors(text_lower),
                    action="Positive for risk assets"
                )

        return None

    def _categorize_risk(self, keyword: str) -> str:
        """Categorize the type of risk"""
        keyword = keyword.lower()

        if any(k in keyword for k in ['china', 'taiwan', 'tariff', 'trade']):
            return "GEOPOLITICAL"
        elif any(k in keyword for k in ['war', 'invasion', 'military', 'strike', 'missile']):
            return "WAR"
        elif any(k in keyword for k in ['fed', 'rate', 'qe', 'qt', 'hawkish', 'dovish']):
            return "FED"
        elif any(k in keyword for k in ['bank', 'credit', 'liquidity', 'lehman']):
            return "FINANCIAL"
        elif any(k in keyword for k in ['pandemic', 'outbreak', 'lockdown']):
            return "HEALTH"
        else:
            return "OTHER"

    def _get_affected_sectors(self, text: str) -> List[str]:
        """Identify which sectors are affected by this news"""
        affected = []

        if any(k in text for k in ['china', 'taiwan', 'beijing', 'xi']):
            affected.extend(self.SECTOR_RISKS.get('china', []))

        if any(k in text for k in ['chip', 'semiconductor', 'nvidia', 'amd']):
            affected.extend(self.SECTOR_RISKS.get('semiconductor', []))

        if any(k in text for k in ['oil', 'crude', 'opec', 'energy']):
            affected.extend(self.SECTOR_RISKS.get('oil', []))

        if any(k in text for k in ['bank', 'financial', 'credit']):
            affected.extend(self.SECTOR_RISKS.get('financials', []))

        if any(k in text for k in ['tech', 'apple', 'google', 'microsoft']):
            affected.extend(self.SECTOR_RISKS.get('tech', []))

        # Remove duplicates
        return list(set(affected))

    def _update_risk_level(self) -> None:
        """Update overall risk level based on recent alerts"""
        # Look at alerts from last hour
        cutoff = datetime.now() - timedelta(hours=1)
        recent = [a for a in self.active_alerts if a.timestamp > cutoff]

        high_count = sum(1 for a in recent if a.risk_level == "HIGH")
        medium_count = sum(1 for a in recent if a.risk_level == "MEDIUM")

        if high_count >= 2:
            self.current_risk_level = "EXTREME"
        elif high_count >= 1:
            self.current_risk_level = "HIGH"
        elif medium_count >= 3:
            self.current_risk_level = "ELEVATED"
        elif medium_count >= 1:
            self.current_risk_level = "MODERATE"
        else:
            self.current_risk_level = "NORMAL"

    async def _send_telegram_alert(self, alert: NewsAlert) -> None:
        """Send Telegram alert for high-risk news"""
        if not TELEGRAM_AVAILABLE:
            return

        try:
            notifier = get_notifier()
            if not notifier:
                return

            # Format message
            emoji = "🚨" if alert.risk_level == "HIGH" else "⚠️"

            message = f"""
{emoji} <b>NEWS ALERT - {alert.risk_type}</b> {emoji}

<b>Headline:</b>
{alert.headline}

<b>Risk Level:</b> {alert.risk_level}
<b>Impact:</b> {alert.impact}

<b>ACTION:</b> {alert.action}
"""

            if alert.affected_sectors:
                sectors = ", ".join(alert.affected_sectors[:8])
                message += f"\n<b>At-Risk Positions:</b> {sectors}"

            message += f"\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            await notifier.send_message(message)
            logger.info(f"📱 Sent Telegram: News alert - {alert.headline[:50]}...")

        except Exception as e:
            logger.debug(f"Error sending news Telegram: {e}")

    def _create_news_inefficiency(self, alert: NewsAlert) -> Optional[Inefficiency]:
        """Convert news alert to inefficiency"""
        try:
            score = 0.9 if alert.risk_level == "HIGH" else 0.6 if alert.risk_level == "MEDIUM" else 0.4

            return Inefficiency(
                id=f"NEWS_{alert.risk_type}_{datetime.now().strftime('%Y%m%d%H%M')}",
                type=InefficiencyType.EXOGENOUS,
                symbol="MARKET",
                score=score,
                edge_reason=EdgeReason.CRISIS_ALPHA,
                description=f"NEWS: {alert.headline[:100]}",
                entry_trigger=alert.action,
                time_sensitivity="hours",
                expires_at=datetime.now() + timedelta(hours=24),
                metadata={
                    'risk_type': alert.risk_type,
                    'risk_level': alert.risk_level,
                    'impact': alert.impact,
                    'affected_sectors': alert.affected_sectors
                }
            )
        except Exception as e:
            logger.debug(f"Error creating news inefficiency: {e}")
            return None

    def get_risk_status(self) -> Dict:
        """Get current news risk status"""
        cutoff = datetime.now() - timedelta(hours=4)
        recent = [a for a in self.active_alerts if a.timestamp > cutoff]

        return {
            'risk_level': self.current_risk_level,
            'recent_alerts': len(recent),
            'high_risk_count': sum(1 for a in recent if a.risk_level == "HIGH"),
            'last_scan': self.last_scan.strftime('%H:%M:%S') if self.last_scan else 'Never',
            'action': self._get_recommended_action()
        }

    def _get_recommended_action(self) -> str:
        """Get recommended action based on risk level"""
        actions = {
            'EXTREME': "REDUCE ALL LONG RISK - Multiple high-risk events",
            'HIGH': "REDUCE LONG EXPOSURE - High-risk event detected",
            'ELEVATED': "TIGHTEN STOPS - Elevated risk",
            'MODERATE': "MONITOR CLOSELY - Risk events detected",
            'NORMAL': "Normal operations"
        }
        return actions.get(self.current_risk_level, "Normal operations")

    def format_risk_dashboard(self) -> str:
        """Format current risk status for display"""
        status = self.get_risk_status()

        risk_emoji = {
            'EXTREME': '🔴🔴🔴',
            'HIGH': '🔴🔴',
            'ELEVATED': '🟠',
            'MODERATE': '🟡',
            'NORMAL': '🟢'
        }

        return f"""
╔══════════════════════════════════════════════════════════════╗
║              GEOPOLITICAL RISK MONITOR                       ║
╠══════════════════════════════════════════════════════════════╣
║  Risk Level:     {status['risk_level']:<10} {risk_emoji.get(status['risk_level'], '')}                  ║
║  Recent Alerts:  {status['recent_alerts']} (last 4h)                              ║
║  High-Risk:      {status['high_risk_count']}                                            ║
║  Last Scan:      {status['last_scan']}                                   ║
╠══════════════════════════════════════════════════════════════╣
║  ACTION: {status['action']:<45} ║
╠══════════════════════════════════════════════════════════════╣
║  MONITORS: China/US, War/Conflict, Fed, Financial Crisis    ║
║  Headlines move markets before fundamentals catch up         ║
╚══════════════════════════════════════════════════════════════╝
"""

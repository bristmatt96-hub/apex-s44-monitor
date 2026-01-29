"""
Substack Research Digest Scanner
Fetches and summarizes posts from subscribed Substacks.

Edge: Curated independent research often ahead of Wall Street.
- Le Shrub: Options flow, volatility, market structure
- Capital Flows: Institutional positioning, fund flows, macro

Uses RSS feeds (free, no API key needed).
"""
import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from loguru import logger

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

from core.base_agent import BaseAgent, AgentMessage


@dataclass
class SubstackPost:
    """A Substack article"""
    title: str
    author: str
    substack_name: str
    url: str
    published: datetime
    summary: str
    key_points: List[str]
    tickers_mentioned: List[str]


# Substack RSS feeds
SUBSTACKS = {
    'le_shrub': {
        'name': 'Le Shrub',
        'feed_url': 'https://www.shrubstack.com/feed',
        'focus': 'macro trades, thematic plays, contrarian investing'
    },
    'capital_flows': {
        'name': 'Capital Flows',
        'feed_url': 'https://www.capitalflowsresearch.com/feed',
        'focus': 'macro flows, rates, FX, institutional positioning'
    }
}

# Common stock tickers to detect in posts
COMMON_TICKERS = {
    'SPY', 'SPX', 'QQQ', 'IWM', 'DIA', 'VIX', 'UVXY', 'VXX',
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA',
    'AMD', 'NFLX', 'COIN', 'GME', 'AMC', 'PLTR', 'SOFI', 'HOOD',
    'TLT', 'GLD', 'SLV', 'USO', 'XLE', 'XLF', 'XLK', 'ARKK',
    'BTC', 'ETH', 'BITCOIN', 'ETHEREUM',
    'ES', 'NQ', 'CL', 'GC',  # Futures
}


class SubstackScanner(BaseAgent):
    """
    Scans Substack RSS feeds for new research posts.

    Flow:
    1. Fetches RSS feeds from subscribed Substacks
    2. Parses new posts (last 24-48 hours)
    3. Extracts key points and mentioned tickers
    4. Sends digest to Telegram

    Scan frequency: Every 4 hours (or on-demand morning digest)
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("SubstackScanner", config)
        self.scan_interval = 14400  # 4 hours
        self.last_scan: Optional[datetime] = None
        self.seen_posts: set = set()  # Track already-processed posts by URL hash
        self.recent_posts: List[SubstackPost] = []
        self.substacks = SUBSTACKS.copy()

        # Load any additional substacks from config
        if config and 'substacks' in config:
            for key, val in config['substacks'].items():
                self.substacks[key] = val

    async def process(self) -> None:
        """Main scanning loop"""
        if not REQUESTS_AVAILABLE:
            logger.warning("[Substack] requests library not available")
            await asyncio.sleep(300)
            return

        # Check if it's time to scan
        if self.last_scan:
            elapsed = (datetime.now() - self.last_scan).seconds
            if elapsed < self.scan_interval:
                await asyncio.sleep(30)
                return

        logger.info("[Substack] Scanning Substack feeds for new research...")

        new_posts = []

        for substack_id, substack_info in self.substacks.items():
            try:
                posts = await self._fetch_substack(substack_id, substack_info)

                for post in posts:
                    post_hash = hashlib.md5(post.url.encode()).hexdigest()
                    if post_hash not in self.seen_posts:
                        new_posts.append(post)
                        self.seen_posts.add(post_hash)
                        self.recent_posts.append(post)

                await asyncio.sleep(1)  # Rate limit between substacks

            except Exception as e:
                logger.debug(f"[Substack] Error fetching {substack_info['name']}: {e}")
                continue

        # Trim recent posts to last 50
        self.recent_posts = self.recent_posts[-50:]

        # Broadcast new posts
        if new_posts:
            await self._broadcast_digest(new_posts)

        self.last_scan = datetime.now()
        logger.info(f"[Substack] Scan complete. New posts: {len(new_posts)}")

    async def _fetch_substack(self, substack_id: str, info: Dict) -> List[SubstackPost]:
        """Fetch posts from a Substack RSS feed"""
        posts = []

        try:
            response = requests.get(info['feed_url'], timeout=15, headers={
                'User-Agent': 'ApexTrader/1.0'
            })

            if response.status_code != 200:
                logger.debug(f"[Substack] Failed to fetch {info['name']}: {response.status_code}")
                return posts

            # Parse RSS XML
            root = ET.fromstring(response.content)

            # Find all items (RSS uses <item> tags)
            channel = root.find('channel')
            if channel is None:
                return posts

            items = channel.findall('item')

            for item in items[:5]:  # Last 5 posts
                try:
                    title = item.findtext('title', '')
                    link = item.findtext('link', '')
                    pub_date_str = item.findtext('pubDate', '')
                    description = item.findtext('description', '')

                    # Also check for content:encoded (full content)
                    content_encoded = item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded', '')
                    content = content_encoded if content_encoded else description

                    # Parse published date (RFC 2822 format)
                    published = datetime.now()
                    if pub_date_str:
                        try:
                            # Handle format like "Tue, 28 Jan 2026 10:00:00 GMT"
                            from email.utils import parsedate_to_datetime
                            published = parsedate_to_datetime(pub_date_str)
                            published = published.replace(tzinfo=None)
                        except Exception:
                            pass

                    # Only posts from last 48 hours
                    if published < datetime.now() - timedelta(hours=48):
                        continue

                    # Clean HTML and extract text
                    summary = self._clean_html(content)

                    # Extract key points
                    key_points = self._extract_key_points(summary)

                    # Find mentioned tickers
                    tickers = self._extract_tickers(title + ' ' + summary)

                    posts.append(SubstackPost(
                        title=title,
                        author=info['name'],
                        substack_name=substack_id,
                        url=link,
                        published=published,
                        summary=summary[:500] + '...' if len(summary) > 500 else summary,
                        key_points=key_points,
                        tickers_mentioned=tickers
                    ))

                except Exception as e:
                    logger.debug(f"[Substack] Error parsing entry: {e}")
                    continue

        except Exception as e:
            logger.debug(f"[Substack] Feed parse error for {info['name']}: {e}")

        return posts

    def _clean_html(self, html: str) -> str:
        """Remove HTML tags and clean text"""
        if BS4_AVAILABLE:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                return soup.get_text(separator=' ', strip=True)
            except Exception:
                pass

        # Basic cleanup without BeautifulSoup
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _extract_key_points(self, text: str) -> List[str]:
        """Extract key points from text"""
        points = []

        # Split into sentences
        sentences = re.split(r'[.!?]\s+', text)

        # Take first 3 meaningful sentences (> 30 chars)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 30 and len(points) < 3:
                # Clean up
                if not sentence.endswith(('.', '!', '?')):
                    sentence += '.'
                points.append(sentence)

        return points

    def _extract_tickers(self, text: str) -> List[str]:
        """Find stock tickers mentioned in text"""
        found = []
        text_upper = text.upper()

        # Look for $TICKER pattern
        dollar_tickers = re.findall(r'\$([A-Z]{1,5})\b', text_upper)
        found.extend(dollar_tickers)

        # Look for known tickers
        for ticker in COMMON_TICKERS:
            # Match whole word
            if re.search(rf'\b{ticker}\b', text_upper):
                if ticker not in found:
                    found.append(ticker)

        return found[:10]  # Max 10 tickers

    async def _broadcast_digest(self, posts: List[SubstackPost]) -> None:
        """Send digest to coordinator/Telegram"""
        # Build digest message
        digest_parts = []

        for post in posts:
            tickers_str = ', '.join(post.tickers_mentioned) if post.tickers_mentioned else 'None'

            part = {
                'title': post.title,
                'author': post.author,
                'url': post.url,
                'published': post.published.isoformat(),
                'key_points': post.key_points,
                'tickers': post.tickers_mentioned,
                'summary': post.summary[:300]
            }
            digest_parts.append(part)

        await self.send_message(
            target='coordinator',
            msg_type='substack_digest',
            payload={
                'posts': digest_parts,
                'scan_time': datetime.now().isoformat()
            },
            priority=1  # Medium priority
        )

        # Also send directly to Telegram
        await self._send_telegram_digest(posts)

    async def _send_telegram_digest(self, posts: List[SubstackPost]) -> None:
        """Send formatted digest to Telegram"""
        try:
            from utils.telegram_notifier import send_telegram_message

            lines = ["📚 <b>Substack Research Digest</b>\n"]

            for post in posts:
                tickers_str = ' '.join([f"${t}" for t in post.tickers_mentioned[:5]]) if post.tickers_mentioned else ''

                lines.append(f"<b>{post.author}</b>: <a href=\"{post.url}\">{post.title}</a>")

                if post.key_points:
                    lines.append(f"<i>→ {post.key_points[0][:150]}</i>")

                if tickers_str:
                    lines.append(f"Tickers: {tickers_str}")

                lines.append("")  # Blank line between posts

            message = '\n'.join(lines)
            await send_telegram_message(message)

        except Exception as e:
            logger.debug(f"[Substack] Telegram send error: {e}")

    async def get_morning_digest(self) -> List[SubstackPost]:
        """Get posts from last 24 hours for morning briefing"""
        cutoff = datetime.now() - timedelta(hours=24)
        return [p for p in self.recent_posts if p.published >= cutoff]

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming messages"""
        if message.msg_type == 'request_digest':
            # Force a scan and send digest
            self.last_scan = None

        elif message.msg_type == 'add_substack':
            # Add a new substack to monitor
            name = message.payload.get('name')
            feed_url = message.payload.get('feed_url')
            focus = message.payload.get('focus', '')

            if name and feed_url:
                key = name.lower().replace(' ', '_')
                self.substacks[key] = {
                    'name': name,
                    'feed_url': feed_url,
                    'focus': focus
                }
                logger.info(f"[Substack] Added {name} to monitored substacks")

    def get_status(self) -> Dict[str, Any]:
        """Get scanner status"""
        return {
            'name': self.name,
            'state': self.state.value,
            'last_scan': self.last_scan.isoformat() if self.last_scan else None,
            'substacks_monitored': list(self.substacks.keys()),
            'posts_cached': len(self.recent_posts),
            'metrics': self.metrics
        }

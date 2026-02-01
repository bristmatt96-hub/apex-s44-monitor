"""
Credit Ratings Monitor

Monitors credit rating agency actions:
- Moody's, S&P, Fitch rating changes
- Outlook changes (negative outlook often precedes downgrade)
- Watch placements (CreditWatch, Review for Downgrade)

Rating agencies often act BEFORE equity markets price in credit risk,
creating options opportunities.
"""

import requests
import feedparser
import logging
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class RatingAgency(Enum):
    MOODYS = "moodys"
    SP = "sp"
    FITCH = "fitch"


class RatingAction(Enum):
    DOWNGRADE = "downgrade"
    UPGRADE = "upgrade"
    OUTLOOK_NEGATIVE = "outlook_negative"
    OUTLOOK_POSITIVE = "outlook_positive"
    WATCH_NEGATIVE = "watch_negative"
    WATCH_POSITIVE = "watch_positive"
    AFFIRMED = "affirmed"


# Rating scales for normalization
MOODYS_SCALE = ['Aaa', 'Aa1', 'Aa2', 'Aa3', 'A1', 'A2', 'A3',
                'Baa1', 'Baa2', 'Baa3',  # Investment grade above
                'Ba1', 'Ba2', 'Ba3', 'B1', 'B2', 'B3',  # High yield
                'Caa1', 'Caa2', 'Caa3', 'Ca', 'C']  # Distressed

SP_SCALE = ['AAA', 'AA+', 'AA', 'AA-', 'A+', 'A', 'A-',
            'BBB+', 'BBB', 'BBB-',  # Investment grade above
            'BB+', 'BB', 'BB-', 'B+', 'B', 'B-',  # High yield
            'CCC+', 'CCC', 'CCC-', 'CC', 'C', 'D']  # Distressed


class RatingsMonitor:
    """Monitor credit rating agency actions."""

    # RSS feeds for rating actions (placeholder URLs - would need actual feeds)
    RATING_FEEDS = {
        RatingAgency.MOODYS: "https://www.moodys.com/rss/ratings.xml",
        RatingAgency.SP: "https://www.spglobal.com/ratings/rss/ratings.xml",
        RatingAgency.FITCH: "https://www.fitchratings.com/rss/ratings.xml",
    }

    def __init__(self, watchlist_tickers: List[str]):
        """
        Initialize ratings monitor.

        Args:
            watchlist_tickers: List of stock tickers to monitor
        """
        self.watchlist_tickers = [t.upper() for t in watchlist_tickers]
        self.session = requests.Session()

    def get_rating_actions(self, agency: RatingAgency) -> List[Dict]:
        """
        Fetch recent rating actions from an agency.

        Args:
            agency: Rating agency to check

        Returns:
            List of rating action dictionaries
        """
        actions = []
        # Implementation would parse actual rating agency feeds
        # This is a stub for the initial structure
        logger.info(f"Checking {agency.value} for rating actions")
        return actions

    def is_fallen_angel(self, old_rating: str, new_rating: str) -> bool:
        """
        Check if rating action is a 'fallen angel' (IG to HY downgrade).

        Fallen angels create forced selling from IG-only mandates,
        often overshooting fair value - good put opportunity.

        Args:
            old_rating: Previous rating
            new_rating: New rating

        Returns:
            True if this is a fallen angel event
        """
        # S&P scale: BBB- is lowest investment grade
        ig_ratings = {'AAA', 'AA+', 'AA', 'AA-', 'A+', 'A', 'A-',
                      'BBB+', 'BBB', 'BBB-'}

        old_is_ig = old_rating in ig_ratings
        new_is_ig = new_rating in ig_ratings

        return old_is_ig and not new_is_ig

    def calculate_notches_moved(self, old_rating: str, new_rating: str) -> int:
        """
        Calculate number of notches moved in rating change.

        Multi-notch downgrades are more severe and typically
        cause larger equity repricing.

        Args:
            old_rating: Previous rating
            new_rating: New rating

        Returns:
            Number of notches (negative for downgrades)
        """
        try:
            old_idx = SP_SCALE.index(old_rating)
            new_idx = SP_SCALE.index(new_rating)
            return old_idx - new_idx  # Positive = upgrade, negative = downgrade
        except ValueError:
            return 0

    def check_all_agencies(self) -> List[Dict]:
        """Check all rating agencies for actions on watchlist companies."""
        all_actions = []
        for agency in RatingAgency:
            actions = self.get_rating_actions(agency)
            # Filter for watchlist companies
            for action in actions:
                if action.get('ticker', '').upper() in self.watchlist_tickers:
                    all_actions.append(action)
        return all_actions

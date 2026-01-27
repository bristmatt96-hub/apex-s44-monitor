"""
P9: Tests for RSS feed parsing functions from apex_monitor.py.

Covers fetch_rss_feed() and search_rss_for_company() with mocked feedparser.
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from time import struct_time

from apex_monitor import fetch_rss_feed, search_rss_for_company


def _make_entry(title, link="https://example.com", summary="Summary text",
                published_parsed=None):
    """Create a mock RSS entry."""
    entry = MagicMock()
    entry.get = lambda key, default="": {
        "title": title,
        "link": link,
        "summary": summary,
        "published_parsed": published_parsed,
        "updated_parsed": None,
    }.get(key, default)
    return entry


def _make_feed(entries, feed_title="Test Feed"):
    """Create a mock feedparser result."""
    feed = MagicMock()
    feed.entries = entries
    feed.feed.get = lambda key, default="": {
        "title": feed_title,
    }.get(key, default)
    return feed


# ============================================================
# fetch_rss_feed
# ============================================================


class TestFetchRSSFeed:
    @patch("apex_monitor.feedparser")
    def test_returns_articles(self, mock_feedparser):
        pub_time = (2025, 1, 15, 10, 0, 0)
        entries = [
            _make_entry("Article 1", published_parsed=pub_time),
            _make_entry("Article 2", published_parsed=pub_time),
        ]
        mock_feedparser.parse.return_value = _make_feed(entries)

        result = fetch_rss_feed("https://example.com/rss")
        assert len(result) == 2
        assert result[0]["title"] == "Article 1"
        assert result[1]["title"] == "Article 2"

    @patch("apex_monitor.feedparser")
    def test_article_structure(self, mock_feedparser):
        pub_time = (2025, 1, 15, 10, 0, 0)
        entries = [_make_entry("Test", published_parsed=pub_time)]
        mock_feedparser.parse.return_value = _make_feed(entries)

        result = fetch_rss_feed("https://example.com/rss")
        article = result[0]
        assert "title" in article
        assert "link" in article
        assert "summary" in article
        assert "published" in article
        assert "source" in article

    @patch("apex_monitor.feedparser")
    def test_max_items_limit(self, mock_feedparser):
        entries = [_make_entry(f"Article {i}") for i in range(20)]
        mock_feedparser.parse.return_value = _make_feed(entries)

        result = fetch_rss_feed("https://example.com/rss", max_items=5)
        assert len(result) == 5

    @patch("apex_monitor.feedparser")
    def test_empty_feed(self, mock_feedparser):
        mock_feedparser.parse.return_value = _make_feed([])

        result = fetch_rss_feed("https://example.com/rss")
        assert result == []

    @patch("apex_monitor.feedparser")
    def test_missing_published_date_uses_now(self, mock_feedparser):
        entries = [_make_entry("No date", published_parsed=None)]
        mock_feedparser.parse.return_value = _make_feed(entries)

        result = fetch_rss_feed("https://example.com/rss")
        assert result[0]["published"] is not None

    @patch("apex_monitor.feedparser")
    def test_summary_truncated_at_200(self, mock_feedparser):
        long_summary = "x" * 500
        entries = [_make_entry("Title", summary=long_summary)]
        mock_feedparser.parse.return_value = _make_feed(entries)

        result = fetch_rss_feed("https://example.com/rss")
        assert len(result[0]["summary"]) <= 200

    @patch("apex_monitor.feedparser")
    def test_exception_returns_empty(self, mock_feedparser):
        mock_feedparser.parse.side_effect = Exception("Network error")

        result = fetch_rss_feed("https://example.com/rss")
        assert result == []


# ============================================================
# search_rss_for_company
# ============================================================


class TestSearchRSSForCompany:
    @patch("apex_monitor.fetch_rss_feed")
    def test_finds_company_in_title(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Ardagh Group announces bond issue",
                "link": "https://example.com/1",
                "summary": "",
                "published": datetime(2025, 1, 15),
                "source": "Reuters",
            }
        ]

        feeds = [{"url": "https://example.com/rss", "name": "Reuters", "region": "EU"}]
        result = search_rss_for_company("Ardagh Group", ["Ardagh"], feeds)
        assert len(result) == 1
        assert result[0]["title"] == "Ardagh Group announces bond issue"

    @patch("apex_monitor.fetch_rss_feed")
    def test_finds_company_by_alias(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Ardagh restructuring talks continue",
                "link": "https://example.com/1",
                "summary": "",
                "published": datetime(2025, 1, 15),
                "source": "Reuters",
            }
        ]

        feeds = [{"url": "https://example.com/rss", "name": "Reuters"}]
        result = search_rss_for_company("Ardagh Group SA", ["Ardagh"], feeds)
        assert len(result) == 1

    @patch("apex_monitor.fetch_rss_feed")
    def test_no_matches(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Amazon reports Q3 earnings",
                "link": "https://example.com/1",
                "summary": "",
                "published": datetime(2025, 1, 15),
                "source": "Reuters",
            }
        ]

        feeds = [{"url": "https://example.com/rss", "name": "Reuters"}]
        result = search_rss_for_company("Ardagh Group", ["Ardagh"], feeds)
        assert len(result) == 0

    @patch("apex_monitor.fetch_rss_feed")
    def test_max_10_results(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": f"Ardagh news {i}",
                "link": f"https://example.com/{i}",
                "summary": "",
                "published": datetime(2025, 1, i + 1),
                "source": "Reuters",
            }
            for i in range(15)
        ]

        feeds = [{"url": "https://example.com/rss", "name": "Reuters"}]
        result = search_rss_for_company("Ardagh", [], feeds)
        assert len(result) <= 10

    @patch("apex_monitor.fetch_rss_feed")
    def test_sorted_by_date_descending(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Old Ardagh news",
                "link": "https://example.com/old",
                "summary": "",
                "published": datetime(2025, 1, 1),
                "source": "Reuters",
            },
            {
                "title": "New Ardagh news",
                "link": "https://example.com/new",
                "summary": "",
                "published": datetime(2025, 1, 15),
                "source": "Reuters",
            },
        ]

        feeds = [{"url": "https://example.com/rss", "name": "Reuters"}]
        result = search_rss_for_company("Ardagh", [], feeds)
        assert result[0]["title"] == "New Ardagh news"

    @patch("apex_monitor.fetch_rss_feed")
    def test_adds_feed_metadata(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Ardagh news",
                "link": "https://example.com/1",
                "summary": "",
                "published": datetime(2025, 1, 15),
                "source": "Reuters",
            }
        ]

        feeds = [
            {"url": "https://example.com/rss", "name": "Reuters", "region": "EU"}
        ]
        result = search_rss_for_company("Ardagh", [], feeds)
        assert result[0]["feed_name"] == "Reuters"
        assert result[0]["region"] == "EU"

    @patch("apex_monitor.fetch_rss_feed")
    def test_empty_feeds_list(self, mock_fetch):
        result = search_rss_for_company("Ardagh", [], [])
        mock_fetch.assert_not_called()
        assert result == []

    @patch("apex_monitor.fetch_rss_feed")
    def test_case_insensitive_search(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "ARDAGH GROUP TO RESTRUCTURE",
                "link": "https://example.com/1",
                "summary": "",
                "published": datetime(2025, 1, 15),
                "source": "Reuters",
            }
        ]

        feeds = [{"url": "https://example.com/rss", "name": "Reuters"}]
        result = search_rss_for_company("Ardagh Group", ["Ardagh"], feeds)
        assert len(result) == 1

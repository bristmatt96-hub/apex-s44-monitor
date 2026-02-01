"""
Bond Spreads Monitor

Monitors bond spread movements for credit stress signals:
- Corporate bond spreads (OAS, Z-spread)
- CDS spreads (if available)
- Relative value vs sector peers

Bond markets often lead equity markets in pricing credit risk.
Widening spreads can signal equity options opportunities.
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SpreadData:
    """Bond spread data point."""
    ticker: str
    cusip: Optional[str]
    spread_bps: float  # Spread in basis points
    spread_change_1d: float  # 1-day change
    spread_change_5d: float  # 5-day change
    spread_change_20d: float  # 20-day change
    timestamp: datetime
    source: str


class BondSpreadsMonitor:
    """Monitor corporate bond spreads for credit stress signals."""

    # Spread widening thresholds (basis points)
    ALERT_THRESHOLDS = {
        'minor': 25,      # 25bp widening - watch
        'moderate': 50,   # 50bp widening - concern
        'severe': 100,    # 100bp widening - likely equity impact
        'crisis': 200,    # 200bp widening - significant stress
    }

    def __init__(self, watchlist_tickers: List[str]):
        """
        Initialize bond spreads monitor.

        Args:
            watchlist_tickers: List of stock tickers to monitor
        """
        self.watchlist_tickers = [t.upper() for t in watchlist_tickers]
        self.session = requests.Session()
        self.spread_history: Dict[str, List[SpreadData]] = {}

    def get_current_spread(self, ticker: str) -> Optional[SpreadData]:
        """
        Get current bond spread for a company.

        Args:
            ticker: Stock ticker

        Returns:
            SpreadData object or None if unavailable
        """
        # Implementation would fetch from bond data provider
        # (e.g., FINRA TRACE, Bloomberg, ICE)
        logger.info(f"Fetching spread data for {ticker}")
        return None

    def calculate_z_score(self, ticker: str, current_spread: float, lookback_days: int = 90) -> float:
        """
        Calculate z-score of current spread vs historical.

        High z-scores indicate unusual spread widening.

        Args:
            ticker: Stock ticker
            current_spread: Current spread in bps
            lookback_days: Historical period for comparison

        Returns:
            Z-score of current spread
        """
        history = self.spread_history.get(ticker, [])
        if len(history) < 20:
            return 0.0

        spreads = [s.spread_bps for s in history[-lookback_days:]]
        mean = sum(spreads) / len(spreads)
        variance = sum((s - mean) ** 2 for s in spreads) / len(spreads)
        std = variance ** 0.5

        if std == 0:
            return 0.0

        return (current_spread - mean) / std

    def detect_spread_breakout(self, ticker: str) -> Optional[Dict]:
        """
        Detect significant spread widening breakouts.

        Args:
            ticker: Stock ticker

        Returns:
            Alert dictionary if breakout detected, else None
        """
        spread_data = self.get_current_spread(ticker)
        if not spread_data:
            return None

        # Check against thresholds
        severity = None
        if spread_data.spread_change_5d >= self.ALERT_THRESHOLDS['crisis']:
            severity = 'crisis'
        elif spread_data.spread_change_5d >= self.ALERT_THRESHOLDS['severe']:
            severity = 'severe'
        elif spread_data.spread_change_5d >= self.ALERT_THRESHOLDS['moderate']:
            severity = 'moderate'
        elif spread_data.spread_change_5d >= self.ALERT_THRESHOLDS['minor']:
            severity = 'minor'

        if severity:
            z_score = self.calculate_z_score(ticker, spread_data.spread_bps)
            return {
                'ticker': ticker,
                'severity': severity,
                'spread_bps': spread_data.spread_bps,
                'spread_change_5d': spread_data.spread_change_5d,
                'z_score': z_score,
                'timestamp': spread_data.timestamp,
            }

        return None

    def check_all_watchlist(self) -> List[Dict]:
        """Check all watchlist companies for spread breakouts."""
        alerts = []
        for ticker in self.watchlist_tickers:
            alert = self.detect_spread_breakout(ticker)
            if alert:
                alerts.append(alert)
        return alerts

    def get_sector_comparison(self, ticker: str, sector_tickers: List[str]) -> Dict:
        """
        Compare company spread to sector peers.

        Relative widening vs peers can indicate company-specific issues.

        Args:
            ticker: Target company ticker
            sector_tickers: List of sector peer tickers

        Returns:
            Comparison dictionary
        """
        target_spread = self.get_current_spread(ticker)
        if not target_spread:
            return {}

        peer_spreads = []
        for peer in sector_tickers:
            if peer != ticker:
                spread = self.get_current_spread(peer)
                if spread:
                    peer_spreads.append(spread.spread_bps)

        if not peer_spreads:
            return {}

        sector_avg = sum(peer_spreads) / len(peer_spreads)

        return {
            'ticker': ticker,
            'spread_bps': target_spread.spread_bps,
            'sector_avg_bps': sector_avg,
            'vs_sector_bps': target_spread.spread_bps - sector_avg,
            'vs_sector_pct': ((target_spread.spread_bps / sector_avg) - 1) * 100,
        }

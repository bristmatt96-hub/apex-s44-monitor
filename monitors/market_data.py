"""
Market Data Monitor — CDS Spread Ingestion

Polls external sources for CDS spread data and updates
the local snapshot cache. Designed to run on a schedule
(e.g. every 15 minutes during market hours).

Data sources (in priority order):
1. Bloomberg B-PIPE / EMSX (requires terminal)
2. ICE Data Services CDS API
3. IHS Markit / S&P Global CDS pricing
4. Web scraping fallback (CBONDS, CMA)

This module provides the interface; actual API keys and
endpoints are configured via environment variables.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from loguru import logger


@dataclass
class CDSQuote:
    """A single CDS spread observation."""
    entity_name: str
    ticker: str
    spread_bps: float
    spread_change_bps: float
    tenor: str  # "5Y" typically
    currency: str  # "EUR" for iTraxx
    recovery_rate: float
    timestamp: str
    source: str


@dataclass
class IndexQuote:
    """iTraxx index-level quote."""
    index_name: str    # "iTraxx Main", "iTraxx Crossover"
    series: int
    spread_bps: float
    spread_change_bps: float
    timestamp: str
    source: str


class MarketDataMonitor:
    """
    Ingests CDS spread data from configured sources and
    updates the local snapshots directory.
    """

    def __init__(self):
        self.snapshots_dir = Path("snapshots")
        self.indices_dir = Path("indices")
        self.data_dir = Path("data")
        self.snapshots_dir.mkdir(exist_ok=True)

        # API configuration from environment
        self.ice_api_key = os.environ.get("ICE_CDS_API_KEY", "")
        self.markit_api_key = os.environ.get("MARKIT_API_KEY", "")
        self.bbg_host = os.environ.get("BLOOMBERG_HOST", "")

        # Cache of latest quotes
        self._quotes: Dict[str, CDSQuote] = {}
        self._index_quotes: Dict[str, IndexQuote] = {}

        # Load universe
        self.universe = self._load_universe()

    def _load_universe(self) -> List[dict]:
        """Load XO S44 constituents."""
        xover_path = self.indices_dir / "xover_s44.json"
        if not xover_path.exists():
            return []
        with open(xover_path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            names = []
            for sector, companies in data.get("sectors", {}).items():
                for company in companies:
                    names.append({"name": company, "sector": sector})
            return names
        return []

    # ── Data Fetching ────────────────────────────────────────────

    async def fetch_spreads(self) -> List[CDSQuote]:
        """
        Fetch latest CDS spreads from available sources.
        Tries sources in priority order, falls back gracefully.
        """
        quotes = []

        if self.ice_api_key:
            quotes = await self._fetch_ice()
        elif self.markit_api_key:
            quotes = await self._fetch_markit()

        if not quotes:
            logger.info("[MarketData] No live data sources configured — using snapshot data")
            quotes = self._load_from_snapshots()

        for q in quotes:
            self._quotes[q.entity_name] = q

        return quotes

    async def fetch_index_levels(self) -> List[IndexQuote]:
        """Fetch iTraxx Main and Crossover index levels."""
        # Placeholder — real implementation would hit Bloomberg or ICE
        logger.debug("[MarketData] Index level fetch not yet connected to live source")
        return list(self._index_quotes.values())

    async def _fetch_ice(self) -> List[CDSQuote]:
        """Fetch from ICE Data Services CDS API."""
        # Requires ICE_CDS_API_KEY and ICE_CDS_ENDPOINT
        endpoint = os.environ.get("ICE_CDS_ENDPOINT", "")
        if not endpoint:
            return []

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.ice_api_key}"}
                async with session.get(endpoint, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._parse_ice_response(data)
                    else:
                        logger.warning(f"[MarketData] ICE API returned {resp.status}")
        except ImportError:
            logger.warning("[MarketData] aiohttp not installed, cannot fetch from ICE")
        except Exception as e:
            logger.error(f"[MarketData] ICE fetch error: {e}")

        return []

    async def _fetch_markit(self) -> List[CDSQuote]:
        """Fetch from S&P Global / IHS Markit."""
        endpoint = os.environ.get("MARKIT_CDS_ENDPOINT", "")
        if not endpoint:
            return []

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                headers = {"X-API-Key": self.markit_api_key}
                async with session.get(endpoint, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._parse_markit_response(data)
        except Exception as e:
            logger.error(f"[MarketData] Markit fetch error: {e}")

        return []

    def _parse_ice_response(self, data: dict) -> List[CDSQuote]:
        """Parse ICE CDS API response into CDSQuote objects."""
        quotes = []
        for item in data.get("quotes", data.get("data", [])):
            quotes.append(CDSQuote(
                entity_name=item.get("entity", item.get("name", "")),
                ticker=item.get("ticker", ""),
                spread_bps=item.get("spread", item.get("mid_spread", 0)),
                spread_change_bps=item.get("change", 0),
                tenor=item.get("tenor", "5Y"),
                currency=item.get("currency", "EUR"),
                recovery_rate=item.get("recovery", 0.4),
                timestamp=datetime.now().isoformat(),
                source="ICE",
            ))
        return quotes

    def _parse_markit_response(self, data: dict) -> List[CDSQuote]:
        """Parse Markit CDS response."""
        quotes = []
        for item in data.get("entities", []):
            quotes.append(CDSQuote(
                entity_name=item.get("entityName", ""),
                ticker=item.get("ticker", ""),
                spread_bps=item.get("spread5Y", 0),
                spread_change_bps=item.get("spreadChange", 0),
                tenor="5Y",
                currency="EUR",
                recovery_rate=item.get("recoveryRate", 0.4),
                timestamp=datetime.now().isoformat(),
                source="Markit",
            ))
        return quotes

    def _load_from_snapshots(self) -> List[CDSQuote]:
        """Fallback: load spread data from existing snapshots."""
        quotes = []
        for f in self.snapshots_dir.glob("*.json"):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                spread = data.get("cds_spread_bps", data.get("spread_bps", 0))
                if spread > 0:
                    quotes.append(CDSQuote(
                        entity_name=data.get("company_name", f.stem),
                        ticker=data.get("ticker", ""),
                        spread_bps=spread,
                        spread_change_bps=0.0,
                        tenor="5Y",
                        currency="EUR",
                        recovery_rate=data.get("recovery_rate", 0.4),
                        timestamp=data.get("last_updated", datetime.now().isoformat()),
                        source="snapshot",
                    ))
            except Exception:
                continue
        return quotes

    # ── Snapshot Updates ─────────────────────────────────────────

    def update_snapshots(self, quotes: List[CDSQuote]):
        """Write new spread data back into snapshot files."""
        for q in quotes:
            if q.source == "snapshot":
                continue  # Don't re-write stale data

            name_lower = q.entity_name.lower()
            for f in self.snapshots_dir.glob("*.json"):
                if name_lower in f.stem.lower():
                    try:
                        with open(f) as fh:
                            data = json.load(fh)
                        data["cds_spread_bps"] = q.spread_bps
                        data["spread_change_bps"] = q.spread_change_bps
                        data["last_updated"] = q.timestamp
                        data["data_source"] = q.source
                        with open(f, "w") as fh:
                            json.dump(data, fh, indent=2)
                        logger.debug(f"[MarketData] Updated {q.entity_name}: {q.spread_bps}bps")
                    except Exception as e:
                        logger.warning(f"[MarketData] Failed to update {f}: {e}")
                    break

    # ── Alert Detection ──────────────────────────────────────────

    def detect_spread_alerts(self, quotes: List[CDSQuote],
                              threshold_bps: float = 20.0) -> List[CDSQuote]:
        """Flag quotes with significant spread moves."""
        alerts = []
        for q in quotes:
            if abs(q.spread_change_bps) >= threshold_bps:
                alerts.append(q)
                logger.info(
                    f"[MarketData] ALERT: {q.entity_name} spread "
                    f"{'widened' if q.spread_change_bps > 0 else 'tightened'} "
                    f"{abs(q.spread_change_bps):.0f}bps to {q.spread_bps:.0f}bps"
                )
        return alerts

    # ── Scheduled Run ────────────────────────────────────────────

    async def run_once(self) -> Dict:
        """Execute a single data refresh cycle."""
        logger.info("[MarketData] Starting data refresh...")

        quotes = await self.fetch_spreads()
        index_quotes = await self.fetch_index_levels()

        self.update_snapshots(quotes)
        alerts = self.detect_spread_alerts(quotes)

        summary = {
            "timestamp": datetime.now().isoformat(),
            "quotes_received": len(quotes),
            "index_quotes": len(index_quotes),
            "alerts": len(alerts),
            "sources": list({q.source for q in quotes}),
        }

        logger.info(
            f"[MarketData] Refresh complete: {len(quotes)} quotes, "
            f"{len(alerts)} alerts from {summary['sources']}"
        )
        return summary

    async def run_loop(self, interval_minutes: int = 15):
        """Run continuous data refresh loop during market hours."""
        logger.info(f"[MarketData] Starting loop (every {interval_minutes}min)")
        while True:
            now = datetime.now().time()
            # European market hours: 07:00 - 17:30 CET (approximate)
            market_open = time(7, 0)
            market_close = time(17, 30)

            if market_open <= now <= market_close:
                await self.run_once()
            else:
                logger.debug("[MarketData] Outside market hours, skipping")

            await asyncio.sleep(interval_minutes * 60)

    # ── Accessors ────────────────────────────────────────────────

    def get_latest_spread(self, entity_name: str) -> Optional[CDSQuote]:
        return self._quotes.get(entity_name)

    def get_all_spreads(self) -> Dict[str, CDSQuote]:
        return dict(self._quotes)

    def get_index_quote(self, index_name: str) -> Optional[IndexQuote]:
        return self._index_quotes.get(index_name)


async def main():
    """Test the market data monitor."""
    monitor = MarketDataMonitor()
    summary = await monitor.run_once()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

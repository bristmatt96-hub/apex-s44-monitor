"""
Synth API Scanner (Bittensor SN50)
Fetches liquidation probability and price predictions from Synth API
https://synthdata.co - Bittensor Subnet 50
"""
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import httpx
import pandas as pd
from loguru import logger

from .base_scanner import BaseScanner
from core.models import Signal, MarketType, SignalType


class SynthScanner(BaseScanner):
    """
    Scanner for Bittensor SN50 Synth API.

    Provides:
    - Liquidation probability predictions (6, 12, 18, 24 hours)
    - Price path forecasts from top miners
    - Meta-leaderboard data

    Supported assets: BTC, ETH, XAU, SOL, SPYX, NVDAX, TSLAX, AAPLX, GOOGLX
    """

    def __init__(self, use_testnet: bool = True):
        super().__init__(
            name="SynthScanner",
            market_type=MarketType.CRYPTO,
            scan_interval=60  # 1 minute - respect rate limits
        )

        # API endpoints
        self.base_url = "https://api-testnet.synthdata.co" if use_testnet else "https://api.synthdata.co"

        # Supported assets
        self.crypto_assets = ["BTC", "ETH", "SOL"]
        self.equity_assets = ["SPYX", "NVDAX", "TSLAX", "AAPLX", "GOOGLX"]
        self.commodity_assets = ["XAU"]

        # All assets to scan
        self.assets = self.crypto_assets + self.equity_assets + self.commodity_assets

        # HTTP client
        self.client: Optional[httpx.AsyncClient] = None

        # Cache for predictions
        self.predictions_cache: Dict[str, Dict] = {}

    async def get_universe(self) -> List[str]:
        """Get list of assets to scan - required by BaseScanner"""
        return self.assets

    async def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Not used - SynthScanner uses its own scan() method with API calls"""
        return None

    async def analyze(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Not used - SynthScanner uses _analyze_liquidation_insight instead"""
        return None

    async def start(self):
        """Initialize HTTP client"""
        self.client = httpx.AsyncClient(timeout=30.0)
        await super().start()
        logger.info(f"[SynthScanner] Started - API: {self.base_url}")

    async def stop(self):
        """Cleanup HTTP client"""
        if self.client:
            await self.client.aclose()
        await super().stop()

    async def get_liquidation_insight(
        self,
        asset: str,
        days: int = 14,
        limit: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Get liquidation probability insight for an asset.

        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            days: Number of days to aggregate for meta-leaderboard
            limit: Number of top miners to use

        Returns:
            Dict with liquidation probabilities for 6, 12, 18, 24 hours
        """
        try:
            response = await self.client.get(
                f"{self.base_url}/insight/liquidation",
                params={
                    "asset": asset,
                    "days": days,
                    "limit": limit
                }
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"[SynthScanner] Liquidation API returned {response.status_code} for {asset}")
                return None

        except Exception as e:
            logger.error(f"[SynthScanner] Error fetching liquidation insight for {asset}: {e}")
            return None

    async def get_predictions(
        self,
        asset: str,
        days: int = 14
    ) -> Optional[Dict[str, Any]]:
        """
        Get latest price predictions for an asset.

        Args:
            asset: Asset symbol
            days: Number of days for leaderboard aggregation

        Returns:
            Dict with prediction data
        """
        try:
            response = await self.client.get(
                f"{self.base_url}/predictions/latest",
                params={
                    "asset": asset,
                    "days": days
                }
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"[SynthScanner] Predictions API returned {response.status_code} for {asset}")
                return None

        except Exception as e:
            logger.error(f"[SynthScanner] Error fetching predictions for {asset}: {e}")
            return None

    async def get_leaderboard(self, days: int = 14) -> Optional[Dict[str, Any]]:
        """
        Get the current miner leaderboard.

        Args:
            days: Number of days to aggregate

        Returns:
            Dict with leaderboard data
        """
        try:
            response = await self.client.get(
                f"{self.base_url}/leaderboard",
                params={"days": days}
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"[SynthScanner] Leaderboard API returned {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"[SynthScanner] Error fetching leaderboard: {e}")
            return None

    async def scan(self) -> List[Signal]:
        """
        Scan Synth API for trading signals based on liquidation probabilities.

        High liquidation probability at certain price levels can indicate:
        - Potential support/resistance zones
        - Possible cascade liquidation events
        - Risk levels for position sizing
        """
        signals = []

        for asset in self.assets:
            try:
                # Get liquidation insight
                insight = await self.get_liquidation_insight(asset)

                if not insight:
                    continue

                # Cache the prediction
                self.predictions_cache[asset] = {
                    "insight": insight,
                    "timestamp": datetime.now()
                }

                # Analyze liquidation data for trading signals
                signal = self._analyze_liquidation_insight(asset, insight)
                if signal:
                    signals.append(signal)

                # Rate limiting - small delay between requests
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"[SynthScanner] Error scanning {asset}: {e}")
                continue

        if signals:
            logger.info(f"[SynthScanner] Generated {len(signals)} signals from Synth API")

        return signals

    def _analyze_liquidation_insight(
        self,
        asset: str,
        insight: Dict[str, Any]
    ) -> Optional[Signal]:
        """
        Analyze liquidation insight data to generate trading signals.

        Strategy:
        - High short liquidation probability above current price = potential squeeze (bullish)
        - High long liquidation probability below current price = potential dump (bearish)
        - Extreme imbalance = potential reversal signal
        """
        try:
            # Extract liquidation probabilities
            liq_6h = insight.get("liquidation_6h", {})
            liq_12h = insight.get("liquidation_12h", {})
            liq_24h = insight.get("liquidation_24h", {})

            current_price = insight.get("current_price", 0)

            # Calculate aggregate liquidation risk
            short_liq_prob = 0
            long_liq_prob = 0

            for timeframe in [liq_6h, liq_12h, liq_24h]:
                short_liq_prob += timeframe.get("short_liquidation_prob", 0)
                long_liq_prob += timeframe.get("long_liquidation_prob", 0)

            short_liq_prob /= 3
            long_liq_prob /= 3

            # Determine signal based on liquidation imbalance
            liq_imbalance = short_liq_prob - long_liq_prob

            # Threshold for generating signal (>20% imbalance)
            if abs(liq_imbalance) < 0.20:
                return None

            # Determine market type
            if asset in self.crypto_assets:
                market_type = MarketType.CRYPTO
                symbol = f"{asset}/USD"
            elif asset in self.equity_assets:
                market_type = MarketType.EQUITY
                # Convert synthetic to real ticker
                symbol_map = {
                    "SPYX": "SPY",
                    "NVDAX": "NVDA",
                    "TSLAX": "TSLA",
                    "AAPLX": "AAPL",
                    "GOOGLX": "GOOGL"
                }
                symbol = symbol_map.get(asset, asset)
            else:
                market_type = MarketType.COMMODITY
                symbol = asset

            # Generate signal
            if liq_imbalance > 0.20:
                # More shorts likely to be liquidated = bullish
                signal_type = SignalType.LONG
                confidence = min(0.5 + liq_imbalance, 0.85)

                return Signal(
                    symbol=symbol,
                    signal_type=signal_type,
                    market_type=market_type,
                    price=current_price,
                    confidence=confidence,
                    source="SynthScanner",
                    strategy="liquidation_squeeze",
                    metadata={
                        "synth_asset": asset,
                        "short_liq_prob": short_liq_prob,
                        "long_liq_prob": long_liq_prob,
                        "liq_imbalance": liq_imbalance,
                        "liq_6h": liq_6h,
                        "liq_12h": liq_12h,
                        "liq_24h": liq_24h,
                        "source_api": "bittensor_sn50"
                    },
                    timestamp=datetime.now()
                )

            elif liq_imbalance < -0.20:
                # More longs likely to be liquidated = bearish
                signal_type = SignalType.SHORT
                confidence = min(0.5 + abs(liq_imbalance), 0.85)

                return Signal(
                    symbol=symbol,
                    signal_type=signal_type,
                    market_type=market_type,
                    price=current_price,
                    confidence=confidence,
                    source="SynthScanner",
                    strategy="liquidation_cascade",
                    metadata={
                        "synth_asset": asset,
                        "short_liq_prob": short_liq_prob,
                        "long_liq_prob": long_liq_prob,
                        "liq_imbalance": liq_imbalance,
                        "liq_6h": liq_6h,
                        "liq_12h": liq_12h,
                        "liq_24h": liq_24h,
                        "source_api": "bittensor_sn50"
                    },
                    timestamp=datetime.now()
                )

            return None

        except Exception as e:
            logger.error(f"[SynthScanner] Error analyzing insight for {asset}: {e}")
            return None

    def get_cached_prediction(self, asset: str) -> Optional[Dict]:
        """Get cached prediction for an asset"""
        return self.predictions_cache.get(asset)


# CLI for testing
if __name__ == "__main__":
    async def test_scanner():
        scanner = SynthScanner(use_testnet=True)
        await scanner.start()

        # Test liquidation insight
        print("\n=== Testing Liquidation Insight ===")
        insight = await scanner.get_liquidation_insight("BTC")
        print(f"BTC Insight: {insight}")

        # Test leaderboard
        print("\n=== Testing Leaderboard ===")
        leaderboard = await scanner.get_leaderboard()
        print(f"Leaderboard: {leaderboard}")

        # Run full scan
        print("\n=== Running Full Scan ===")
        signals = await scanner.scan()
        for signal in signals:
            print(f"Signal: {signal.symbol} - {signal.signal_type} - Confidence: {signal.confidence:.2f}")

        await scanner.stop()

    asyncio.run(test_scanner())

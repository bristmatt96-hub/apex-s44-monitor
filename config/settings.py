"""
Trading System Configuration
"""
from pydantic import BaseModel
from typing import Optional, Dict
import os
from dotenv import load_dotenv

load_dotenv()


class IBConfig(BaseModel):
    """Interactive Brokers Configuration"""
    host: str = "127.0.0.1"
    port: int = 7497  # 7497 for TWS paper, 7496 for TWS live, 4001/4002 for Gateway
    client_id: int = 1
    account: Optional[str] = None


class CryptoConfig(BaseModel):
    """Crypto Exchange Configuration"""
    exchange: str = "binance"
    api_key: str = os.getenv("CRYPTO_API_KEY", "")
    api_secret: str = os.getenv("CRYPTO_API_SECRET", "")
    testnet: bool = False


class RiskConfig(BaseModel):
    """Risk Management Configuration"""
    max_position_pct: float = 0.05  # 5% max per position
    max_daily_loss_pct: float = 0.10  # 10% max daily loss
    max_positions: int = 10
    starting_capital: float = 3000.0


class SignalConfig(BaseModel):
    """Signal Generation Configuration"""
    min_risk_reward: float = 2.0  # Minimum 2:1 risk/reward
    min_confidence: float = 0.65  # 65% minimum confidence
    lookback_periods: int = 100


class MarketWeights(BaseModel):
    """
    Market priority weights and capital allocation.

    Weights determine:
    - Scanner priority (higher = scanned more frequently)
    - Ranker bonus (higher weight = boosted score)
    - Capital allocation (% of total capital for that market)

    These are INITIAL weights. The adaptive system will
    adjust them based on actual trading performance.
    """
    # Priority weights (0.0 - 1.0, higher = more priority)
    options: float = 0.95       # Highest - best R:R for $3k
    crypto: float = 0.85        # High - no PDT, 24/7
    equities: float = 0.60      # Medium - PDT restricted, swing only
    forex: float = 0.55         # Medium - slower moves
    spacs: float = 0.0          # Disabled

    # Capital allocation (must sum to ~1.0)
    options_capital_pct: float = 0.40   # $1,200
    crypto_capital_pct: float = 0.25    # $750
    equities_capital_pct: float = 0.15  # $450
    forex_capital_pct: float = 0.15     # $450
    spacs_capital_pct: float = 0.0      # $0
    reserve_pct: float = 0.05           # $150 cash reserve

    # Scan intervals (seconds) - lower = more frequent
    options_scan_interval: int = 30     # Every 30s
    crypto_scan_interval: int = 30      # Every 30s
    equities_scan_interval: int = 60    # Every 60s
    forex_scan_interval: int = 60       # Every 60s

    # Adaptive learning
    adaptive_enabled: bool = True
    adapt_interval_hours: int = 24      # Re-evaluate weights daily
    min_trades_to_adapt: int = 10       # Need 10 trades before adapting
    max_weight_shift: float = 0.15      # Max 15% shift per adaptation

    def get_weight(self, market_type: str) -> float:
        """Get weight for a market type"""
        weights = {
            'options': self.options,
            'crypto': self.crypto,
            'equity': self.equities,
            'forex': self.forex,
            'spac': self.spacs
        }
        return weights.get(market_type, 0.5)

    def get_capital_allocation(self, market_type: str, total_capital: float) -> float:
        """Get capital allocated to a market"""
        allocations = {
            'options': self.options_capital_pct,
            'crypto': self.crypto_capital_pct,
            'equity': self.equities_capital_pct,
            'forex': self.forex_capital_pct,
            'spac': self.spacs_capital_pct
        }
        pct = allocations.get(market_type, 0.0)
        return total_capital * pct

    def get_scan_interval(self, market_type: str) -> int:
        """Get scan interval for a market"""
        intervals = {
            'options': self.options_scan_interval,
            'crypto': self.crypto_scan_interval,
            'equity': self.equities_scan_interval,
            'forex': self.forex_scan_interval
        }
        return intervals.get(market_type, 60)


class ScannerConfig(BaseModel):
    """Market Scanner Configuration"""
    scan_interval_seconds: int = 60
    equities_enabled: bool = True
    crypto_enabled: bool = True
    forex_enabled: bool = True
    options_enabled: bool = True
    spacs_enabled: bool = False  # Disabled by default


class TradingConfig(BaseModel):
    """Main Trading Configuration"""
    ib: IBConfig = IBConfig()
    crypto: CryptoConfig = CryptoConfig()
    risk: RiskConfig = RiskConfig()
    signals: SignalConfig = SignalConfig()
    scanner: ScannerConfig = ScannerConfig()
    market_weights: MarketWeights = MarketWeights()

    # PDT Rule - limited day trades for accounts under $25k
    pdt_restricted: bool = True
    day_trades_remaining: int = 3

    # Environment
    live_trading: bool = True
    log_level: str = "INFO"


# Global config instance
config = TradingConfig()

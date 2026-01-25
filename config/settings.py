"""
Trading System Configuration
"""
from pydantic import BaseModel
from typing import Optional
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


class ScannerConfig(BaseModel):
    """Market Scanner Configuration"""
    scan_interval_seconds: int = 60
    equities_enabled: bool = True
    crypto_enabled: bool = True
    forex_enabled: bool = True
    options_enabled: bool = True
    spacs_enabled: bool = True


class TradingConfig(BaseModel):
    """Main Trading Configuration"""
    ib: IBConfig = IBConfig()
    crypto: CryptoConfig = CryptoConfig()
    risk: RiskConfig = RiskConfig()
    signals: SignalConfig = SignalConfig()
    scanner: ScannerConfig = ScannerConfig()

    # PDT Rule - limited day trades for accounts under $25k
    pdt_restricted: bool = True
    day_trades_remaining: int = 3

    # Environment
    live_trading: bool = True
    log_level: str = "INFO"


# Global config instance
config = TradingConfig()

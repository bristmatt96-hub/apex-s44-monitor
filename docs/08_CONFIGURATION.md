# Configuration Reference

## Overview

All APEX configuration lives in `config/settings.py` as Pydantic models. This provides type safety, validation, and clear documentation for all settings.

**Location**: `config/settings.py`

---

## Configuration Structure

```python
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from enum import Enum

class Settings(BaseModel):
    risk: RiskConfig
    signals: SignalConfig
    markets: MarketConfig
    strategies: StrategyConfig
    learning: LearningConfig
    broker: BrokerConfig
    notifications: NotificationConfig
```

---

## RiskConfig

Controls position sizing, exposure limits, and risk management.

```python
class RiskConfig(BaseModel):
    # Capital and position sizing
    capital: float = 3000.0                    # Total trading capital
    max_position_pct: float = 0.05             # Max 5% of capital per position
    max_risk_pct: float = 0.01                 # Max 1% risk per trade
    max_positions: int = 10                    # Maximum concurrent positions

    # Daily limits
    max_daily_loss_pct: float = 0.10           # 10% daily loss limit
    max_daily_trades: int = 20                 # Maximum trades per day

    # PDT compliance
    pdt_enabled: bool = True                   # Enable PDT tracking
    day_trade_limit: int = 3                   # Max day trades (under $25k)

    # Position management
    auto_stop_loss: bool = True                # Auto-place stop losses
    trailing_stop_pct: Optional[float] = None  # Optional trailing stop
```

### Position Sizing Formula

```
shares = min(
    (capital × max_risk_pct) / risk_per_share,
    (capital × max_position_pct) / entry_price
)
```

**Example** with defaults:
- Capital: $3,000
- Entry: $50, Stop: $48 (risk = $2/share)
- Risk sizing: ($3,000 × 0.01) / $2 = 15 shares
- Capital sizing: ($3,000 × 0.05) / $50 = 3 shares
- **Result**: 3 shares ($150 position)

---

## SignalConfig

Minimum thresholds for signal validation.

```python
class SignalConfig(BaseModel):
    # Minimum thresholds
    min_risk_reward: float = 2.0               # Minimum 2:1 R:R
    min_confidence: float = 0.65               # Minimum 65% confidence
    min_ta_composite: float = 0.50             # Minimum TA score
    min_trend_score: float = 0.40              # Minimum trend score

    # Signal expiry
    signal_ttl_minutes: int = 30               # Signals expire after 30 min
    max_pending_signals: int = 100             # Max signals in queue

    # Validation settings
    require_ta_validation: bool = True         # Must pass TA
    require_ml_validation: bool = True         # Must pass ML
    require_volume_confirmation: bool = False  # Optional volume check
```

### Validation Flow

```
Signal passes if:
  1. risk_reward_ratio >= min_risk_reward (2.0)
  2. confidence >= min_confidence (0.65)
  3. ta_composite > min_ta_composite (0.50)
  4. trend_score > min_trend_score (0.40)
```

---

## MarketConfig

Market-type weights and trading hours.

```python
class MarketConfig(BaseModel):
    # Initial market weights (adjusted by AdaptiveWeights)
    weights: Dict[str, float] = {
        'crypto': 0.85,
        'options': 0.80,
        'equity': 0.70,
        'forex': 0.60
    }

    # Trading hours (24hr format, ET timezone)
    trading_hours: Dict[str, Dict] = {
        'equity': {'start': 9.5, 'end': 16.0},    # 9:30 AM - 4:00 PM
        'options': {'start': 9.5, 'end': 16.0},
        'forex': {'start': 0, 'end': 24},          # 24/5
        'crypto': {'start': 0, 'end': 24}          # 24/7
    }

    # Market-specific settings
    equity_min_volume: int = 1_000_000
    equity_min_price: float = 1.0
    equity_max_price: float = 500.0

    options_max_contract_price: float = 200.0
    options_min_dte: int = 5
    options_max_dte: int = 45

    crypto_min_volume_usd: float = 1_000_000
```

---

## StrategyConfig

Strategy-specific settings and performance multipliers.

```python
class StrategyConfig(BaseModel):
    # Strategy multipliers (from backtest profit factors)
    multipliers: Dict[str, float] = {
        'volume_spike_reversal': 1.25,    # PF 1.99-14.42
        'mean_reversion': 1.20,           # PF 1.43-5.29
        'momentum_breakout': 1.15,        # PF 1.87-1.96
        'insider_buying': 1.15,
        'options_flow': 1.10,
        'trend_following': 1.05,
        'breakout': 1.00,
        'gap_play': 0.90,
        'unknown': 0.85
    }

    # Strategy-specific thresholds
    mean_reversion_rsi_threshold: float = 30.0
    momentum_volume_ratio: float = 1.5
    volume_spike_ratio: float = 2.5
    breakout_buffer_pct: float = 0.01

    # ATR multipliers for stops/targets
    stop_atr_multiplier: float = 2.0
    target_atr_multiplier: float = 4.0
```

### Strategy Performance Reference

| Strategy | Markets | Backtest PF | Win Rate |
|----------|---------|-------------|----------|
| Volume Spike Reversal | Crypto, Meme | 1.99-14.42 | 52-86% |
| Mean Reversion | All | 1.43-5.29 | 45-65% |
| Momentum Breakout | Options, ETF | 1.87-1.96 | 48-55% |
| Trend Following | Forex | 1.2-1.5 | 40-50% |

---

## LearningConfig

Controls for adaptive learning systems.

```python
class LearningConfig(BaseModel):
    # Adaptive weights
    weight_learning_rate: float = 0.05         # 5% adjustment per update
    weight_min: float = 0.40                   # Minimum market weight
    weight_max: float = 1.30                   # Maximum market weight
    weight_decay_days: int = 30                # Days before decay

    # Edge component learning
    edge_min_trades: int = 20                  # Min trades before adapting
    edge_adaptation_hours: int = 24            # Hours between adaptations
    edge_max_shift: float = 0.15               # Max 15% shift per cycle
    edge_component_min: float = 0.05           # Min component weight
    edge_component_max: float = 0.40           # Max component weight

    # ML model management
    ml_retrain_days: int = 7                   # Retrain weekly
    ml_min_accuracy: float = 0.55              # Retrain if below 55%
    ml_min_training_samples: int = 200         # Minimum training samples
    ml_rolling_window: int = 100               # Predictions for accuracy calc

    # Pattern learning
    pattern_min_similarity: float = 0.70       # Min pattern match similarity
    pattern_max_age_days: int = 90             # Pattern expiry
```

### Learning Safeguards

| Parameter | Value | Purpose |
|-----------|-------|---------|
| weight_min | 0.40 | Prevent markets from being ignored |
| weight_max | 1.30 | Prevent over-concentration |
| edge_max_shift | 0.15 | Gradual adaptation only |
| ml_min_accuracy | 0.55 | Trigger retrain before too much damage |

---

## BrokerConfig

Interactive Brokers connection settings.

```python
class BrokerConfig(BaseModel):
    # Connection
    ib_host: str = '127.0.0.1'
    ib_port: int = 7497                        # TWS Paper: 7497, Live: 7496
    ib_client_id: int = 1

    # Mode
    simulation_mode: bool = True               # Use simulated execution
    paper_trading: bool = True                 # Connect to paper account

    # Order settings
    default_order_type: str = 'MARKET'
    timeout_seconds: int = 30
    max_retry_attempts: int = 3

    # Account
    account_id: Optional[str] = None           # IB account ID

    # Position sync
    sync_interval_seconds: int = 60            # Sync positions every 60s
    reconcile_on_startup: bool = True
```

### Connection Ports

| Mode | Port | Description |
|------|------|-------------|
| TWS Paper | 7497 | Paper trading via TWS |
| TWS Live | 7496 | Live trading via TWS |
| Gateway Paper | 4002 | Paper trading via IB Gateway |
| Gateway Live | 4001 | Live trading via IB Gateway |

---

## NotificationConfig

Telegram and alerting settings.

```python
class NotificationConfig(BaseModel):
    # Telegram
    telegram_enabled: bool = True
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Alert types
    alert_on_entry: bool = True
    alert_on_exit: bool = True
    alert_on_opportunity: bool = True
    alert_on_error: bool = True
    send_daily_summary: bool = True
    daily_summary_hour: int = 17               # 5 PM ET

    # Rate limiting
    min_alert_interval_seconds: int = 5
    max_alerts_per_hour: int = 60

    # Formatting
    include_charts: bool = False               # Not implemented yet
    include_reasoning: bool = True
```

---

## Environment Variables

Sensitive configuration loaded from environment:

```bash
# .env file
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

IB_ACCOUNT_ID=your_account_id

# Optional
LOG_LEVEL=INFO
SIMULATION_MODE=true
```

### Loading Environment Config

```python
from dotenv import load_dotenv
import os

load_dotenv()

settings = Settings(
    notifications=NotificationConfig(
        telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
        telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID')
    ),
    broker=BrokerConfig(
        account_id=os.getenv('IB_ACCOUNT_ID'),
        simulation_mode=os.getenv('SIMULATION_MODE', 'true').lower() == 'true'
    )
)
```

---

## Scanner-Specific Config

Each scanner can have custom configuration:

```python
class EquityScannerConfig(BaseModel):
    scan_interval: int = 60                    # Seconds between scans
    watchlist: List[str] = [
        'SPY', 'QQQ', 'TSLA', 'AAPL', 'NVDA', 'AMD', 'META',
        # ... full list
    ]
    min_volume: int = 1_000_000
    min_price: float = 1.0
    max_price: float = 500.0

class CryptoScannerConfig(BaseModel):
    scan_interval: int = 30
    pairs: List[str] = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT'
    ]
    exchange: str = 'binance'

class ForexScannerConfig(BaseModel):
    scan_interval: int = 60
    pairs: List[str] = [
        'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF'
    ]
    use_hourly_data: bool = True
```

---

## Complete Configuration Example

```python
# config/settings.py

settings = Settings(
    risk=RiskConfig(
        capital=3000.0,
        max_position_pct=0.05,
        max_risk_pct=0.01,
        max_positions=10,
        max_daily_loss_pct=0.10
    ),

    signals=SignalConfig(
        min_risk_reward=2.0,
        min_confidence=0.65,
        min_ta_composite=0.50
    ),

    markets=MarketConfig(
        weights={
            'crypto': 0.85,
            'options': 0.80,
            'equity': 0.70,
            'forex': 0.60
        }
    ),

    strategies=StrategyConfig(
        multipliers={
            'volume_spike_reversal': 1.25,
            'mean_reversion': 1.20,
            'momentum_breakout': 1.15
        }
    ),

    learning=LearningConfig(
        weight_learning_rate=0.05,
        edge_adaptation_hours=24,
        ml_retrain_days=7
    ),

    broker=BrokerConfig(
        simulation_mode=True,
        ib_port=7497
    ),

    notifications=NotificationConfig(
        telegram_enabled=True,
        alert_on_entry=True,
        alert_on_exit=True
    )
)
```

---

## Accessing Configuration

```python
from config.settings import settings

# Risk settings
max_shares = (settings.risk.capital * settings.risk.max_position_pct) / entry_price

# Market weights
weight = settings.markets.weights.get(market_type, 0.70)

# Strategy multiplier
multiplier = settings.strategies.multipliers.get(strategy, 0.85)

# Learning parameters
if len(trades) >= settings.learning.edge_min_trades:
    # OK to adapt
```

---

## Configuration Validation

Pydantic validates all configuration at startup:

```python
class RiskConfig(BaseModel):
    capital: float = Field(ge=100, description="Must be at least $100")
    max_position_pct: float = Field(ge=0.01, le=0.25, description="1-25%")
    max_risk_pct: float = Field(ge=0.005, le=0.05, description="0.5-5%")
    max_positions: int = Field(ge=1, le=50, description="1-50 positions")

    @validator('max_position_pct')
    def position_pct_reasonable(cls, v, values):
        if 'capital' in values and values['capital'] < 1000 and v > 0.10:
            raise ValueError('Small accounts should use smaller position sizes')
        return v
```

---

## Runtime Configuration Updates

Some settings can be updated at runtime:

```python
class ConfigManager:
    def __init__(self):
        self.settings = load_settings()

    def update_risk_capital(self, new_capital: float) -> None:
        """Update capital (e.g., after deposit/withdrawal)"""
        self.settings.risk.capital = new_capital
        self._notify_agents('capital_updated', new_capital)

    def toggle_auto_execute(self, enabled: bool) -> None:
        """Toggle auto-execution mode"""
        self.settings.execution.auto_execute = enabled
        logger.info(f"Auto-execute: {enabled}")

    def update_market_weight(self, market: str, weight: float) -> None:
        """Manual weight override"""
        self.settings.markets.weights[market] = weight
```

---

## Configuration Files

| File | Purpose |
|------|---------|
| `config/settings.py` | Main configuration definitions |
| `.env` | Environment-specific secrets |
| `data/adaptive_weights.json` | Learned market weights |
| `data/edge_components.json` | Learned edge component weights |
| `data/executor_state.json` | Trade/position state |

---

## Recommended Settings by Account Size

### Small Account ($1,000 - $5,000)

```python
RiskConfig(
    capital=3000,
    max_position_pct=0.05,     # $150 max position
    max_risk_pct=0.01,         # $30 max risk
    max_positions=5,           # Focus on fewer positions
    pdt_enabled=True
)
```

### Medium Account ($10,000 - $25,000)

```python
RiskConfig(
    capital=15000,
    max_position_pct=0.08,     # $1,200 max position
    max_risk_pct=0.015,        # $225 max risk
    max_positions=10,
    pdt_enabled=True
)
```

### Large Account ($25,000+)

```python
RiskConfig(
    capital=50000,
    max_position_pct=0.10,     # $5,000 max position
    max_risk_pct=0.02,         # $1,000 max risk
    max_positions=15,
    pdt_enabled=False          # No PDT restrictions
)
```

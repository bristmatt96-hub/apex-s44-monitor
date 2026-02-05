# Layer 1: Scanning (Market Discovery)

## Overview

The scanning layer is the entry point of the APEX trading system. It continuously monitors multiple markets for trading opportunities using eight specialized scanners. Each scanner watches a defined universe of symbols, fetches market data, applies strategy-specific analysis, and emits signals when trading criteria are met.

All scanners inherit from `BaseScanner` and run independently on configurable intervals. This architecture allows the system to monitor equities, options, forex, and crypto markets simultaneously without blocking.

---

## Architecture

```
                                    ┌─────────────────┐
                                    │   BaseScanner   │
                                    │    (Abstract)   │
                                    └────────┬────────┘
                                             │
            ┌────────────────┬───────────────┼───────────────┬────────────────┐
            │                │               │               │                │
    ┌───────▼──────┐ ┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐ ┌───────▼──────┐
    │EquityScanner │ │CryptoScanner │ │ForexScanner │ │OptionsScanner│ │OptionsFlow  │
    └──────────────┘ └──────────────┘ └─────────────┘ └──────────────┘ │  Scanner    │
                                                                        └──────────────┘
            ┌────────────────┬───────────────┐
            │                │               │
    ┌───────▼──────┐ ┌───────▼──────┐ ┌──────▼──────┐
    │ EdgarInsider │ │CreditOptions │ │ SynthScanner│
    │   Scanner    │ │   Scanner    │ │ (Bittensor) │
    └──────────────┘ └──────────────┘ └─────────────┘
```

---

## BaseScanner Class

**Location**: `agents/scanners/base_scanner.py`

The abstract base class that all scanners inherit from. It provides:

### Core Methods

| Method | Description |
|--------|-------------|
| `get_universe()` | Abstract. Returns list of symbols to scan. |
| `fetch_data(symbol)` | Abstract. Fetches OHLCV data for a symbol. |
| `analyze(symbol, data)` | Abstract. Runs strategy logic, returns Signal or None. |
| `scan()` | Iterates universe, calls fetch_data and analyze for each symbol. |
| `calculate_risk_reward(entry, target, stop)` | Helper to compute R:R ratio. |
| `emit_signal(signal)` | Sends signal to coordinator via message bus. |

### Scan Loop

```python
async def scan(self):
    """Main scan loop - runs on configured interval"""
    universe = await self.get_universe()

    for symbol in universe:
        try:
            data = await self.fetch_data(symbol)
            if data is not None and len(data) >= self.min_bars:
                signal = await self.analyze(symbol, data)
                if signal:
                    await self.emit_signal(signal)
        except Exception as e:
            logger.debug(f"Scan error for {symbol}: {e}")
```

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `scan_interval` | 60s | Seconds between scans |
| `min_bars` | 20 | Minimum data bars required |
| `market_type` | Varies | EQUITY, CRYPTO, FOREX, or OPTIONS |

---

## Scanner Details

### 1. EquityScanner

**Location**: `agents/scanners/equity_scanner.py`

**Purpose**: Scans US equities and ETFs for high risk/reward setups.

**Universe**: 57 symbols optimized from backtest results (Jan 2026)

```python
# High retail options volume (proven edge across 4 strategies)
'SPY', 'QQQ', 'TSLA', 'AAPL', 'NVDA', 'AMD', 'META', 'AMZN', 'MSFT', 'GOOGL', 'NFLX', 'COIN'

# Meme/retail stocks (mean reversion + volume spike edge)
'GME', 'AMC', 'PLTR', 'SOFI', 'BB', 'HOOD', 'RIVN', 'LCID', 'MARA', 'RIOT', 'DKNG'

# Small cap momentum
'JOBY', 'IONQ', 'RKLB', 'DNA', 'OPEN'

# Retail ETFs
'IWM', 'ARKK', 'TQQQ', 'GLD', 'SLV', 'XLE', 'XLF', 'TLT', 'USO'
```

**Strategies** (ordered by backtest performance):

#### Strategy 1: Mean Reversion (PF 1.43-5.29)
- RSI < 30 (oversold)
- Price at/below lower Bollinger Band
- Reversal candle pattern (red to green)
- Entry: Current close
- Stop: Below 5-day low minus 0.5 ATR
- Target: Entry + 3 ATR

#### Strategy 2: Volume Spike Reversal (PF 1.99-14.42)
- Volume > 2.5x 20-day average
- Red candle with > 2% drop (retail panic)
- Smart money absorbs selling
- Entry: Current close
- Stop: Below panic low minus 0.5 ATR
- Target: Entry + 3 ATR
- Win rate: 52-86% across markets

#### Strategy 3: Momentum Breakout (PF 1.87-1.96)
- Price breaks 20-day high
- EMA20 > EMA50 (trend confirmation)
- Volume > 1.5x average
- RSI between 40-75 (not overbought)
- Entry: Breakout price
- Stop: Entry - 2 ATR
- Target: Entry + 4 ATR

#### Strategy 4: Volume Surge
- Volume > 3x 20-day average
- Price change > 2% (bullish)
- Entry: Current close
- Stop: Current low - 0.5 ATR
- Target: Entry + 3 ATR

**Filters**:
- Minimum volume: 1,000,000 daily
- Price range: $1.00 - $500.00

---

### 2. CryptoScanner

**Location**: `agents/scanners/crypto_scanner.py`

**Purpose**: Scans major cryptocurrencies 24/7. No PDT restrictions.

**Universe**: 7 pairs
```python
'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT', 'MATIC/USDT', 'LINK/USDT', 'ATOM/USDT'
```

**Scan Interval**: 30 seconds (faster due to 24/7 market)

**Strategies**: Same as EquityScanner but tuned for crypto volatility:
- Mean Reversion
- Volume Spike Reversal
- Momentum Breakout

**Data Source**: CCXT library connecting to Binance/other exchanges

**Advantages**:
- No pattern day trader (PDT) rule
- 24/7 trading
- High volatility = more opportunities
- Backtest showed Volume Spike Reversal achieved PF 14.42 on crypto

---

### 3. ForexScanner

**Location**: `agents/scanners/forex_scanner.py`

**Purpose**: Scans FX pairs for trend and mean reversion setups.

**Universe**: 25 pairs across majors, crosses, and exotics

```python
# Majors
'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD'

# Crosses
'EURGBP', 'EURJPY', 'GBPJPY', 'AUDJPY', 'EURAUD', 'GBPAUD', 'EURCHF', 'GBPCHF'

# Exotics (higher volatility)
'USDZAR', 'USDMXN', 'USDTRY', 'USDSEK', 'USDNOK'
```

**Strategies**:

#### Trend Following
- EMA20 > EMA50 (uptrend)
- Price above EMA20
- RSI 40-70 (not extreme)
- MACD above signal
- Entry on pullback to EMA20
- Stop: EMA50 - 0.5 ATR
- Target: 2:1 R:R

#### Range Breakout
- Price breaks 48-hour range high
- Entry: Breakout price
- Stop: Just below range high
- Target: Measured move (range size)

#### Mean Reversion
- RSI < 30
- Price at lower Bollinger Band
- Reversal candle
- Target: Middle Bollinger Band

**Pip Values**:
- JPY pairs: 0.01
- All others: 0.0001

---

### 4. OptionsScanner

**Location**: `agents/scanners/options_scanner.py`

**Purpose**: Finds high R:R options plays on momentum stocks.

**Universe**: 32 liquid options underlyings
```python
'SPY', 'QQQ', 'IWM', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'AMD', 'TSLA', 'NFLX',
'GME', 'AMC', 'PLTR', 'SOFI', 'RIVN', 'LCID', 'MRNA', 'BNTX',
'JPM', 'BAC', 'GS', 'MS', 'XOM', 'CVX', 'OXY',
'XLF', 'XLE', 'XLK', 'GLD', 'SLV', 'USO'
```

**Constraints**:
- Max option price: $200 per contract
- Days to expiry: 5-45 days
- Focus on defined-risk plays

**Strategies**:

#### Momentum Call
- Strong uptrend (EMA20 > EMA50)
- RSI 55-75 (strong momentum, not overbought)
- Volume > 1.2x average
- Buy slightly OTM call (2-10% OTM)
- Max loss: Premium paid
- Target: 2:1 on premium

#### Breakout Call
- Price near 20-day range high
- Buy ATM or slightly OTM call
- Target: Measured move

#### Oversold Bounce Call
- RSI < 30
- Price at lower Bollinger Band
- Buy ATM or slightly ITM call
- Target: Mean reversion to middle band

---

### 5. OptionsFlowScanner

**Location**: `agents/scanners/options_flow_scanner.py`

**Purpose**: Detects unusual options activity indicating institutional positioning.

**Universe**: 27 high-volume options symbols

**Scan Interval**: 15 minutes

**Detection Methods**:

| Metric | Threshold | Meaning |
|--------|-----------|---------|
| Volume/OI Ratio | > 2.0 | Fresh positioning, not rolling |
| Call/Put Skew | Extreme | Directional bet |
| Strike Concentration | High | Targeted price level |
| OTM Volume | Unusual | Aggressive entry (sweep) |
| Near-term Heavy Volume | High | Event-driven positioning |

**Flow Types Detected**:
- `bullish_sweep`: Large OTM call volume with low OI
- `bearish_sweep`: Large OTM put volume with low OI
- `call_surge`: Unusual call volume across strikes
- `put_surge`: Unusual put volume across strikes
- `straddle`: Equal call/put activity at same strike

**Why This Works**:
- Smart money uses options for leverage before catalysts
- Unusual flow often precedes 3-10 day moves
- Combining with technical signals creates confluence

**Output**: `UnusualFlow` dataclass with:
```python
symbol: str
flow_type: str           # 'bullish_sweep', etc.
strike: float
expiry: str
days_to_expiry: int
option_type: str         # 'call' or 'put'
volume: int
open_interest: int
voi_ratio: float         # Volume / Open Interest
implied_premium: float   # Total premium spent
stock_price: float
otm_pct: float           # How far OTM
```

---

### 6. EdgarInsiderScanner

**Location**: `agents/scanners/edgar_insider_scanner.py`

**Purpose**: Monitors SEC Form 4 filings for insider purchases.

**Universe**: 30+ tickers with known insider activity

**Scan Interval**: Periodic (hourly during market hours)

**What It Looks For**:
- Open market purchases (not grants/exercises)
- Purchase size relative to insider's holdings
- Cluster buying (multiple insiders)
- C-suite purchases (CEO, CFO, Directors)

**Signal Strength Factors**:
- Larger purchases = higher confidence
- C-suite > other insiders
- Cluster buying > single insider
- First purchase in 12+ months = notable

**Data Source**: SEC EDGAR API

---

### 7. CreditOptionsScanner

**Location**: `agents/scanners/credit_options_scanner.py`

**Purpose**: Maps credit deterioration signals to tradeable options positions.

**Universe**: 24 XO S44 (distressed credit) names with liquid equity options

**Integration**: Works with `SituationClassifier` to select appropriate strategy:

| Playbook | Situation | Recommended Strategy |
|----------|-----------|---------------------|
| A | Aggressive sponsor likely to support | Straddles or avoid |
| B | Maturity wall, no support | Puts likely work |

**Data Points Analyzed**:
- Sponsor aggression score
- Maturity risk level
- Catalyst timing
- IV percentile and rank
- ATM implied volatility

**Output**: `OptionsOpportunity` with:
- Recommended strategy (puts, straddle, avoid, monitor)
- Strike and expiry recommendations
- Max position size based on premium
- Edge score and conviction level

---

### 8. SynthScanner

**Location**: `agents/scanners/synth_scanner.py`

**Purpose**: Ingests predictions from Bittensor Subnet 50 (liquidation predictions).

**Universe**: 9 symbols
```python
'BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'LINK', 'ATOM', 'DOT', 'NEAR'
```

**How It Works**:
- Bittensor SN50 miners predict upcoming liquidation cascades
- Scanner fetches predictions via API
- Converts to trading signals with confidence based on miner consensus

**Signal Types**:
- Long liquidation cascade predicted → Bearish signal
- Short liquidation cascade predicted → Bullish signal

---

## Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Scanner   │────▶│  DataCache   │────▶│  yfinance/  │
│             │     │  (Shared)    │     │  CCXT/API   │
└──────┬──────┘     └──────────────┘     └─────────────┘
       │
       ▼
┌─────────────┐
│   Signal    │
│   Object    │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌──────────────┐
│  Message    │────▶│  Coordinator │
│    Bus      │     │              │
└─────────────┘     └──────────────┘
```

---

## Signal Object

When a scanner finds a valid setup, it emits a `Signal` object:

```python
@dataclass
class Signal:
    symbol: str                    # 'AAPL', 'BTC/USDT', 'EURUSD'
    market_type: MarketType        # EQUITY, CRYPTO, FOREX, OPTIONS
    signal_type: SignalType        # BUY, SELL, LONG_CALL, LONG_PUT, etc.
    confidence: float              # 0.0 - 1.0
    entry_price: float             # Suggested entry
    target_price: float            # Take profit level
    stop_loss: float               # Stop loss level
    risk_reward_ratio: float       # Calculated R:R
    source: str                    # 'equity_momentum_breakout', etc.
    metadata: Dict[str, Any]       # Strategy-specific data
    timestamp: datetime            # When signal was generated
```

**Metadata Examples**:
```python
# Equity momentum breakout
{
    'strategy': 'momentum_breakout',
    'rsi': 62.5,
    'volume_ratio': 2.3,
    'atr': 1.45
}

# Options momentum call
{
    'strategy': 'momentum_call',
    'option_type': 'call',
    'strike': 150.0,
    'expiry': '2026-02-21',
    'days_to_expiry': 16,
    'stock_price': 145.50,
    'premium': 3.20,
    'contract_cost': 320.0
}

# Unusual options flow
{
    'flow_type': 'bullish_sweep',
    'voi_ratio': 4.5,
    'total_premium': 1250000,
    'otm_pct': 5.2
}
```

---

## Performance Considerations

### Shared Data Cache

As of commit `9a20185`, all scanners use a shared `DataCache` singleton to prevent redundant API calls:

```python
from core.data_cache import get_data_cache

async def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
    cache = get_data_cache()
    return await cache.get_history(symbol, 'equity', '3mo', '1d')
```

**Cache Configuration**:
- Intraday data: 60 second TTL
- Daily data: 5 minute TTL
- Rate limiting: 0.5 second minimum between API calls

### Scan Intervals

| Scanner | Interval | Rationale |
|---------|----------|-----------|
| Equity | 60s | Daily bars, moderate frequency |
| Crypto | 30s | 24/7 market, higher volatility |
| Forex | 60s | Hourly bars, session-based |
| Options | 30s | Option chains change rapidly |
| Flow | 15min | Aggregated flow data |
| Insider | Hourly | SEC filings are periodic |
| Credit | Periodic | Event-driven |
| Synth | 60s | Bittensor prediction updates |

---

## Error Handling

Each scanner wraps individual symbol processing in try/except to prevent one failure from stopping the entire scan:

```python
for symbol in universe:
    try:
        data = await self.fetch_data(symbol)
        # ... analysis ...
    except (ConnectionError, ValueError, KeyError) as e:
        logger.debug(f"Scan error for {symbol}: {e}")
        continue  # Move to next symbol
```

**Common Failure Modes**:
- API rate limiting (yfinance, exchanges)
- Missing data for thinly traded symbols
- Network timeouts
- Invalid option chains (expired, no volume)

All failures are logged at DEBUG level to avoid log spam, while still maintaining visibility for troubleshooting.

---

## Future Improvements

1. **Priority Queue**: Add backpressure between scanners and validation layer
2. **Circuit Breaker**: Stop calling failing APIs for N minutes after M failures
3. **Symbol Scoring**: Prioritize symbols with historical edge
4. **Dynamic Intervals**: Increase scan frequency during high-volatility periods

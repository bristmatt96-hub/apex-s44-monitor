# Layer 2: Technical Validation

## Overview

The Technical Validation layer acts as the first quality gate in the signal pipeline. Every raw signal emitted by scanners passes through the `TechnicalAnalyzer` agent, which scores the signal across four dimensions: trend, momentum, volume, and volatility.

Signals that fail validation are dropped. Signals that pass receive an adjusted confidence score that reflects the technical picture.

**Location**: `agents/signals/technical_analyzer.py`

---

## Architecture

```
┌─────────────┐     ┌───────────────────┐     ┌─────────────┐
│   Scanner   │────▶│ TechnicalAnalyzer │────▶│ MLPredictor │
│   Signal    │     │                   │     │             │
└─────────────┘     └───────────────────┘     └─────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Validation     │
                    │  Decision       │
                    │                 │
                    │  composite > 0.5│
                    │  AND            │
                    │  trend > 0.4    │
                    └─────────────────┘
```

---

## TechnicalAnalyzer Class

### Initialization

```python
class TechnicalAnalyzer(BaseAgent):
    def __init__(self, config: Optional[Dict] = None):
        super().__init__("TechnicalAnalyzer", config)
        self.pending_signals: List[Dict] = []
        self.analyzed_signals: List[Dict] = []
```

### Message Handling

The analyzer listens for `analyze_signal` messages from the coordinator:

```python
async def handle_message(self, message: AgentMessage) -> None:
    if message.msg_type == 'analyze_signal':
        self.pending_signals.append(message.payload)
        logger.debug(f"Received signal to analyze: {message.payload.get('symbol')}")
```

### Process Loop

```python
async def process(self) -> None:
    if not self.pending_signals:
        await asyncio.sleep(1)
        return

    while self.pending_signals:
        signal_data = self.pending_signals.pop(0)
        analysis = await self.analyze_signal(signal_data)

        if analysis['validated']:
            self.analyzed_signals.append(analysis)
            await self._send_analysis(analysis)
```

---

## Scoring Dimensions

The analyzer scores each signal on four dimensions, each with a defined weight:

| Dimension | Weight | What It Measures |
|-----------|--------|------------------|
| Trend | 30% | Direction and strength of the trend |
| Momentum | 30% | Speed and persistence of price movement |
| Volume | 20% | Confirmation from trading activity |
| Volatility | 20% | Risk level (lower = better) |

### Composite Score Formula

```python
composite_score = (
    trend_score * 0.30 +
    momentum_score * 0.30 +
    volume_score * 0.20 +
    (1 - volatility_analysis['risk_score']) * 0.20  # Lower volatility = better
)
```

---

## Trend Analysis

**Method**: `_analyze_trend(data: pd.DataFrame) -> float`

**Indicators Used**:
- EMA 20 (short-term trend)
- EMA 50 (medium-term trend)
- SMA 200 (long-term trend) — falls back to SMA 100 if insufficient data
- ADX 14 (trend strength)

**Scoring Logic**:

| Condition | Points |
|-----------|--------|
| Price > EMA20 | +0.20 |
| Price > EMA50 | +0.20 |
| Price > SMA200 | +0.20 |
| EMA20 > EMA50 (aligned) | +0.15 |
| EMA50 > SMA200 (aligned) | +0.15 |
| ADX strength (0-50 normalized) | +0.00 to +0.30 |

**Maximum Score**: 1.0

**Code Example**:

```python
# Price vs EMAs
if price > ema20.iloc[-1]:
    scores.append(0.2)
if price > ema50.iloc[-1]:
    scores.append(0.2)
if price > sma200.iloc[-1]:
    scores.append(0.2)

# EMA alignment
if ema20.iloc[-1] > ema50.iloc[-1]:
    scores.append(0.15)
if ema50.iloc[-1] > sma200.iloc[-1]:
    scores.append(0.15)

# ADX strength (0-50 scale, normalized to 0.3 max)
adx_score = min(adx / 50, 1.0) * 0.3
scores.append(adx_score)

return min(sum(scores), 1.0)
```

**Interpretation**:

| Score | Meaning |
|-------|---------|
| 0.8-1.0 | Strong uptrend, all EMAs aligned, high ADX |
| 0.6-0.8 | Moderate uptrend, most conditions met |
| 0.4-0.6 | Mixed trend, some conditions met |
| 0.2-0.4 | Weak or no trend |
| 0.0-0.2 | Downtrend or very weak conditions |

---

## Momentum Analysis

**Method**: `_analyze_momentum(data: pd.DataFrame) -> float`

**Indicators Used**:
- RSI 14 (Relative Strength Index)
- MACD 12/26/9 (Moving Average Convergence Divergence)
- Stochastic 14/3/3 (Stochastic Oscillator)
- ROC 10 (Rate of Change)

**Scoring Logic**:

| Condition | Points |
|-----------|--------|
| RSI 40-60 (optimal) | +0.30 |
| RSI 30-70 (acceptable) | +0.20 |
| RSI extreme (<30 or >70) | +0.10 |
| MACD > Signal | +0.20 |
| MACD Histogram > 0 | +0.15 |
| Stoch %K > %D | +0.15 |
| Stoch 20-80 (not extreme) | +0.10 |
| ROC > 0 (positive momentum) | +0.10 |

**Maximum Score**: 1.0

**Code Example**:

```python
# RSI score (optimal range 40-60)
if 40 < rsi_val < 60:
    scores.append(0.3)
elif 30 < rsi_val < 70:
    scores.append(0.2)
else:
    scores.append(0.1)

# MACD score
if macd > macd_signal:
    scores.append(0.2)
if macd_hist > 0:
    scores.append(0.15)

# Stochastic score
if stoch_k > stoch_d:
    scores.append(0.15)
if 20 < stoch_k < 80:
    scores.append(0.1)

# Momentum (rate of change)
roc = ta.roc(close, length=10)
if roc is not None and roc.iloc[-1] > 0:
    scores.append(0.1)
```

**Why RSI 40-60 is Optimal**:
- Avoids overbought (>70) conditions where reversals are likely
- Avoids oversold (<30) conditions that may continue falling
- Middle range indicates sustainable momentum without exhaustion

---

## Volatility Analysis

**Method**: `_analyze_volatility(data: pd.DataFrame) -> Dict`

**Indicators Used**:
- ATR 14 (Average True Range)
- Bollinger Band Width (20-period, 2 std dev)
- Historical Volatility (annualized)

**Output**: Returns a dictionary with multiple metrics:

```python
{
    'atr': 2.45,              # Absolute ATR value
    'atr_pct': 0.018,         # ATR as percentage of price
    'bb_width': 0.085,        # Bollinger Band width as percentage
    'hist_volatility': 0.32,  # Annualized historical volatility
    'risk_score': 0.45        # Composite risk score (0-1)
}
```

**Risk Score Formula**:

```python
risk_score = min((atr_pct * 20 + bb_width * 10 + hist_vol) / 3, 1.0)
```

**Interpretation**:

| Risk Score | Volatility Level | Impact on Composite |
|------------|------------------|---------------------|
| 0.0-0.3 | Low | +0.14 to +0.20 contribution |
| 0.3-0.5 | Moderate | +0.10 to +0.14 contribution |
| 0.5-0.7 | High | +0.06 to +0.10 contribution |
| 0.7-1.0 | Very High | +0.00 to +0.06 contribution |

**Note**: Volatility is inverted in the composite score (`1 - risk_score`) because lower volatility is generally more favorable for trade execution.

---

## Volume Analysis

**Method**: `_analyze_volume(data: pd.DataFrame) -> float`

**Metrics Analyzed**:
- Current volume vs 20-day average
- Volume trend (recent 5 days vs prior 15 days)
- Price-volume correlation (up days should have higher volume)
- Absolute liquidity check

**Scoring Logic**:

| Condition | Points |
|-----------|--------|
| Volume ratio > 1.5x average | +0.30 |
| Volume ratio > 1.0x average | +0.20 |
| Volume ratio < 1.0x average | +0.10 |
| Volume trend > 1.2x | +0.25 |
| Volume trend > 1.0x | +0.15 |
| Positive volume > Negative volume (1.5x) | +0.25 |
| Positive volume > Negative volume (1.0x) | +0.15 |
| Current volume > 100,000 (liquidity) | +0.20 |

**Maximum Score**: 1.0

**Code Example**:

```python
# Volume ratio score
if volume_ratio > 1.5:
    scores.append(0.3)
elif volume_ratio > 1.0:
    scores.append(0.2)
else:
    scores.append(0.1)

# Volume trend score
if volume_trend > 1.2:
    scores.append(0.25)
elif volume_trend > 1.0:
    scores.append(0.15)

# Price-volume correlation
positive_volume = sum(v for p, v in last_5_days if p > 0)
negative_volume = sum(v for p, v in last_5_days if p < 0)
pv_ratio = positive_volume / negative_volume if negative_volume > 0 else 2

if pv_ratio > 1.5:
    scores.append(0.25)
elif pv_ratio > 1.0:
    scores.append(0.15)

# Adequate liquidity
if current_volume > 100000:
    scores.append(0.2)
```

**Why Price-Volume Correlation Matters**:
- Healthy uptrends have higher volume on up days
- Distribution (smart money selling) shows high volume on down days
- Accumulation (smart money buying) shows low volume on down days, high on up

---

## Support and Resistance Analysis

**Method**: `_find_support_resistance(data: pd.DataFrame) -> Dict`

**Calculation Methods**:

### 1. Pivot Points (Floor Trader Method)

```python
pivot = (high + low + close) / 3
r1 = 2 * pivot - low      # Resistance 1
r2 = pivot + (high - low) # Resistance 2
s1 = 2 * pivot - high     # Support 1
s2 = pivot - (high - low) # Support 2
```

### 2. Swing High/Low Detection

```python
for i in range(2, len(data) - 2):
    # Swing high: higher than 2 bars before and after
    if (high[i] > high[i-1] and high[i] > high[i-2] and
        high[i] > high[i+1] and high[i] > high[i+2]):
        swing_highs.append(high[i])

    # Swing low: lower than 2 bars before and after
    if (low[i] < low[i-1] and low[i] < low[i-2] and
        low[i] < low[i+1] and low[i] < low[i+2]):
        swing_lows.append(low[i])
```

**Output**:

```python
{
    'pivot': 152.50,
    'resistance_1': 155.20,
    'resistance_2': 158.00,
    'support_1': 149.80,
    'support_2': 147.00,
    'nearest_resistance': 155.20,
    'nearest_support': 149.80,
    'distance_to_resistance_pct': 1.8,
    'distance_to_support_pct': 1.5
}
```

**Usage in Validation**:
- S/R levels are included in the analysis output
- Not currently used in scoring, but available for:
  - Stop loss placement validation
  - Target price reasonableness checks
  - Risk/reward verification

---

## Validation Decision

A signal passes validation if:

```python
validated = composite_score > 0.5 and trend_score > 0.4
```

**Why These Thresholds**:

| Threshold | Rationale |
|-----------|-----------|
| Composite > 0.5 | Overall technical picture is net positive |
| Trend > 0.4 | Minimum trend structure exists (not fighting the trend) |

**Examples**:

| Trend | Momentum | Volume | Volatility | Composite | Valid? |
|-------|----------|--------|------------|-----------|--------|
| 0.80 | 0.70 | 0.60 | 0.30 | 0.71 | ✅ Yes |
| 0.45 | 0.65 | 0.55 | 0.40 | 0.53 | ✅ Yes |
| 0.35 | 0.80 | 0.70 | 0.25 | 0.59 | ❌ No (trend < 0.4) |
| 0.50 | 0.40 | 0.40 | 0.70 | 0.43 | ❌ No (composite < 0.5) |

---

## Confidence Adjustment

For validated signals, the analyzer adjusts the original confidence:

```python
original_confidence = signal_data.get('confidence', 0.5)
adjusted_confidence = (original_confidence + composite_score) / 2
```

**Examples**:

| Scanner Confidence | TA Composite | Adjusted Confidence |
|--------------------|--------------|---------------------|
| 0.72 | 0.75 | 0.735 |
| 0.65 | 0.60 | 0.625 |
| 0.80 | 0.55 | 0.675 |

This creates a blended confidence that incorporates both the scanner's strategy-specific assessment and the broader technical picture.

---

## Output Format

The analyzer returns an enriched signal with TA scores:

```python
{
    # Original signal fields
    'symbol': 'AAPL',
    'market_type': 'equity',
    'signal_type': 'BUY',
    'entry_price': 178.50,
    'stop_loss': 175.00,
    'target_price': 185.00,
    'confidence': 0.72,  # Original

    # Validation result
    'validated': True,

    # TA scores
    'ta_scores': {
        'trend': 0.75,
        'momentum': 0.68,
        'volume': 0.55,
        'volatility': {
            'atr': 2.45,
            'atr_pct': 0.014,
            'bb_width': 0.065,
            'hist_volatility': 0.28,
            'risk_score': 0.38
        },
        'composite': 0.69
    },

    # Support/Resistance levels
    'support_resistance': {
        'pivot': 178.00,
        'resistance_1': 181.00,
        'resistance_2': 184.00,
        'support_1': 175.50,
        'support_2': 172.00,
        'nearest_resistance': 181.00,
        'nearest_support': 175.50,
        'distance_to_resistance_pct': 1.4,
        'distance_to_support_pct': 1.7
    },

    # Adjusted confidence
    'adjusted_confidence': 0.705,  # (0.72 + 0.69) / 2

    # Timestamp
    'ta_timestamp': '2026-02-05T14:32:15.123456'
}
```

---

## Data Fetching

The analyzer uses the shared data cache for market data:

```python
async def _fetch_data(self, symbol: str, market_type: str) -> Optional[pd.DataFrame]:
    cache = get_data_cache()
    return await cache.get_history(symbol, market_type, '3mo', '1d')
```

**Data Requirements**:
- Minimum 50 bars for analysis
- Columns: open, high, low, close, volume
- 200+ bars ideal for SMA200 calculation

---

## Error Handling

Each analysis method has specific exception handling:

```python
async def _analyze_trend(self, data: pd.DataFrame) -> float:
    if not PANDAS_TA_AVAILABLE:
        return 0.5  # Neutral score if library unavailable

    try:
        # ... analysis logic ...
        return min(sum(scores), 1.0)

    except (ValueError, TypeError, KeyError) as e:
        logger.debug(f"Trend analysis error: {e}")
        return 0.5  # Fall back to neutral
```

**Fallback Behavior**:
- If pandas_ta is unavailable: return 0.5 (neutral)
- If any indicator fails: return 0.5 for that dimension
- Individual dimension failures don't crash the entire analysis

---

## Null Safety

After the fix in commit `e86e059`, the analyzer guards against None returns from pandas_ta:

```python
# Moving averages
ema20 = ta.ema(close, length=20)
ema50 = ta.ema(close, length=50)
sma200 = ta.sma(close, length=200) if len(data) >= 200 else ta.sma(close, length=100)

if ema20 is None or ema50 is None or sma200 is None:
    return 0.5

# ADX
adx_data = ta.adx(high, low, close, length=14)
adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None else 20
```

**Why This Matters**:
- pandas_ta returns `None` when data is insufficient for the indicator
- Without guards, `.iloc[-1]` on `None` causes `AttributeError`
- Neutral fallback (0.5) allows analysis to continue

---

## Performance Considerations

### Caching
- Uses shared DataCache to avoid redundant yfinance calls
- Same symbol data reused across multiple signals

### Async Processing
- Signals processed one at a time from queue
- Non-blocking sleep when queue is empty
- Allows other agents to run concurrently

### Indicator Calculations
- pandas_ta is vectorized (fast on DataFrames)
- Calculations done once per signal, not per bar
- Only latest values extracted for scoring

---

## Future Improvements

1. **Weighted Scoring by Market Type**: Crypto might weight momentum higher, forex might weight trend higher

2. **Dynamic Thresholds**: Adjust validation thresholds based on market conditions (VIX level, etc.)

3. **Pattern Recognition**: Add candlestick pattern detection (engulfing, doji, etc.)

4. **Multi-Timeframe Analysis**: Confirm signals across daily, 4H, and 1H charts

5. **S/R Score Integration**: Use distance to S/R in composite score (closer to support = higher score for longs)

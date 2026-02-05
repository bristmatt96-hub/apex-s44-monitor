# Layer 3: ML Prediction

## Overview

The ML Prediction layer uses machine learning models to predict price direction and estimate probabilities. It receives signals that have passed technical validation and adds a probabilistic assessment of whether the predicted move will occur.

The system uses two models:
1. **RandomForest** for direction classification (up/down)
2. **XGBoost** (or GradientBoosting fallback) for probability estimation

**Location**: `agents/signals/ml_predictor.py`

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌───────────────────┐
│ TechnicalAnalyzer│────▶│   MLPredictor   │────▶│ OpportunityRanker │
│     Signal      │     │                 │     │                   │
└─────────────────┘     └────────┬────────┘     └───────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │      ML Models         │
                    │  ┌──────────────────┐  │
                    │  │  RandomForest    │  │
                    │  │  (Direction)     │  │
                    │  └──────────────────┘  │
                    │  ┌──────────────────┐  │
                    │  │  XGBoost         │  │
                    │  │  (Probability)   │  │
                    │  └──────────────────┘  │
                    └────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │     ModelManager       │
                    │  - Version control     │
                    │  - Accuracy tracking   │
                    │  - Auto-retrain        │
                    └────────────────────────┘
```

---

## MLPredictor Class

### Initialization

```python
class MLPredictor(BaseAgent):
    def __init__(self, config: Optional[Dict] = None):
        super().__init__("MLPredictor", config)

        self.models: Dict[str, Any] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.model_dir = config.get('model_dir', 'models/') if config else 'models/'
        self.pending_predictions: List[Dict] = []
        self.min_training_samples = 200

        # Model manager for persistence and staleness detection
        self.model_manager = get_model_manager()

        # Try loading persisted models first
        loaded = self.model_manager.load_models()
        if loaded:
            self.models = loaded["models"]
            self.scalers = loaded["scalers"]
            logger.info("Loaded persisted ML models from disk")
        else:
            self._init_models()
```

### Model Configuration

```python
def _init_models(self):
    # Direction classifier (Random Forest)
    self.models['direction'] = RandomForestClassifier(
        n_estimators=100,      # Number of trees
        max_depth=10,          # Limit tree depth to prevent overfitting
        min_samples_split=5,   # Minimum samples to split a node
        random_state=42,       # Reproducibility
        n_jobs=-1              # Use all CPU cores
    )

    # Probability estimator (XGBoost preferred, GradientBoosting fallback)
    if XGB_AVAILABLE:
        self.models['probability'] = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=42
        )
    else:
        self.models['probability'] = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=42
        )

    self.scalers['default'] = StandardScaler()
```

---

## Feature Engineering

The predictor extracts 31 technical features from price data:

### Price Features (4)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `returns_1d` | 1-day price change % | Short-term momentum |
| `returns_5d` | 5-day price change % | Weekly momentum |
| `returns_10d` | 10-day price change % | Bi-weekly momentum |
| `returns_20d` | 20-day price change % | Monthly momentum |

### Volatility Features (2)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `volatility_10d` | 10-day rolling std of returns | Short-term volatility |
| `volatility_20d` | 20-day rolling std of returns | Medium-term volatility |

### Moving Average Features (5)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `price_sma10_ratio` | Price / SMA10 | Position relative to short MA |
| `price_sma20_ratio` | Price / SMA20 | Position relative to medium MA |
| `price_sma50_ratio` | Price / SMA50 | Position relative to long MA |
| `sma10_sma20_ratio` | SMA10 / SMA20 | Short-term trend |
| `sma20_sma50_ratio` | SMA20 / SMA50 | Medium-term trend |

### Momentum Indicators (8)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `rsi_14` | RSI 14-period | Standard RSI |
| `rsi_7` | RSI 7-period | Fast RSI |
| `macd` | MACD line | Trend momentum |
| `macd_signal` | MACD signal line | Trend confirmation |
| `macd_hist` | MACD histogram | Momentum acceleration |
| `stoch_k` | Stochastic %K | Fast stochastic |
| `stoch_d` | Stochastic %D | Slow stochastic |

### Volatility Indicators (4)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `bb_width` | (BBU - BBL) / BBM | Bollinger Band width |
| `bb_position` | (Price - BBL) / (BBU - BBL) | Position within bands |
| `atr_14` | ATR 14-period | Absolute volatility |
| `atr_pct` | ATR / Price | Relative volatility |

### Trend Strength (3)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `adx` | ADX 14-period | Trend strength |
| `di_plus` | +DI 14-period | Bullish pressure |
| `di_minus` | -DI 14-period | Bearish pressure |

### Volume Features (1)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `volume_ratio` | Volume / 20-day avg volume | Relative volume |

### Candlestick Features (3)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `body_pct` | (Close - Open) / Open | Candle body size |
| `high_low_range` | (High - Low) / Close | Daily range |
| `close_position` | (Close - Low) / (High - Low) | Close within range |

### Lag Features (3)

| Feature | Calculation | Purpose |
|---------|-------------|---------|
| `rsi_lag1` | RSI(t-1) | Previous RSI |
| `macd_lag1` | MACD(t-1) | Previous MACD |
| `volume_ratio_lag1` | Volume ratio(t-1) | Previous volume |

---

## Feature Extraction Code

```python
async def _extract_features(self, data: pd.DataFrame) -> Optional[pd.DataFrame]:
    df = data.copy()
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']

    # Price features
    df['returns_1d'] = close.pct_change(1)
    df['returns_5d'] = close.pct_change(5)
    df['returns_10d'] = close.pct_change(10)
    df['returns_20d'] = close.pct_change(20)

    # Volatility features
    df['volatility_10d'] = df['returns_1d'].rolling(10).std()
    df['volatility_20d'] = df['returns_1d'].rolling(20).std()

    # Moving averages and ratios
    df['sma_10'] = ta.sma(close, length=10)
    df['sma_20'] = ta.sma(close, length=20)
    df['sma_50'] = ta.sma(close, length=50)
    df['price_sma10_ratio'] = close / df['sma_10']
    df['price_sma20_ratio'] = close / df['sma_20']
    df['price_sma50_ratio'] = close / df['sma_50']

    # RSI
    df['rsi_14'] = ta.rsi(close, length=14)
    df['rsi_7'] = ta.rsi(close, length=7)

    # MACD
    macd = ta.macd(close)
    df['macd'] = macd['MACD_12_26_9']
    df['macd_signal'] = macd['MACDs_12_26_9']
    df['macd_hist'] = macd['MACDh_12_26_9']

    # Bollinger Bands
    bb = ta.bbands(close, length=20)
    df['bb_width'] = (bb['BBU_20_2.0'] - bb['BBL_20_2.0']) / bb['BBM_20_2.0']
    df['bb_position'] = (close - bb['BBL_20_2.0']) / (bb['BBU_20_2.0'] - bb['BBL_20_2.0'])

    # ATR
    df['atr_14'] = ta.atr(high, low, close, length=14)
    df['atr_pct'] = df['atr_14'] / close

    # ADX
    adx = ta.adx(high, low, close, length=14)
    df['adx'] = adx['ADX_14']
    df['di_plus'] = adx['DMP_14']
    df['di_minus'] = adx['DMN_14']

    # Stochastic
    stoch = ta.stoch(high, low, close)
    df['stoch_k'] = stoch['STOCHk_14_3_3']
    df['stoch_d'] = stoch['STOCHd_14_3_3']

    # Volume
    df['volume_sma'] = volume.rolling(20).mean()
    df['volume_ratio'] = volume / df['volume_sma']

    # Candlestick
    df['body'] = close - df['open']
    df['body_pct'] = df['body'] / df['open']
    df['high_low_range'] = (high - low) / close
    df['close_position'] = (close - low) / (high - low)

    # Lag features
    df['rsi_lag1'] = df['rsi_14'].shift(1)
    df['macd_lag1'] = df['macd'].shift(1)
    df['volume_ratio_lag1'] = df['volume_ratio'].shift(1)

    # Select and clean features
    feature_cols = [
        'returns_1d', 'returns_5d', 'returns_10d', 'returns_20d',
        'volatility_10d', 'volatility_20d',
        'price_sma10_ratio', 'price_sma20_ratio', 'price_sma50_ratio',
        'sma10_sma20_ratio', 'sma20_sma50_ratio',
        'rsi_14', 'rsi_7',
        'macd', 'macd_signal', 'macd_hist',
        'bb_width', 'bb_position',
        'atr_pct',
        'adx', 'di_plus', 'di_minus',
        'stoch_k', 'stoch_d',
        'volume_ratio',
        'body_pct', 'high_low_range', 'close_position',
        'rsi_lag1', 'macd_lag1', 'volume_ratio_lag1'
    ]

    features = df[feature_cols].copy()
    features = features.replace([np.inf, -np.inf], np.nan)
    features = features.dropna()

    return features if not features.empty else None
```

---

## Prediction Flow

### 1. Receive Prediction Request

```python
async def handle_message(self, message: AgentMessage) -> None:
    if message.msg_type == 'predict':
        self.pending_predictions.append(message.payload)
```

### 2. Fetch Data and Extract Features

```python
async def predict(self, request: Dict) -> Optional[Dict]:
    symbol = request.get('symbol')
    market_type = request.get('market_type')

    # Fetch via shared cache
    data = await self._fetch_data(symbol, market_type)
    if data is None or len(data) < 50:
        return None

    features = await self._extract_features(data)
    if features is None:
        return None
```

### 3. Scale Features

```python
    # Get latest features
    X = features.iloc[-1:].values

    # Scale features
    scaler = self.scalers['default']
    if hasattr(scaler, 'mean_') and scaler.mean_ is not None:
        X_scaled = scaler.transform(features.values)
    else:
        X_scaled = scaler.fit_transform(features.values)
    X_current = X_scaled[-1:]
```

### 4. Run Predictions

```python
    predictions = {}

    # Direction prediction
    if 'direction' in self.models:
        try:
            direction = self.models['direction'].predict(X_current)[0]
            direction_proba = self.models['direction'].predict_proba(X_current)[0]
            predictions['direction'] = 'up' if direction == 1 else 'down'
            predictions['direction_confidence'] = float(max(direction_proba))
        except (ValueError, AttributeError):
            # Model not fitted - trigger training
            await self._train_on_history(features, data)
            predictions['direction'] = 'unknown'
            predictions['direction_confidence'] = 0.5

    # Probability estimation
    if 'probability' in self.models:
        try:
            proba = self.models['probability'].predict_proba(X_current)[0]
            predictions['up_probability'] = float(proba[1]) if len(proba) > 1 else 0.5
        except (ValueError, AttributeError):
            predictions['up_probability'] = 0.5
```

### 5. Adjust Confidence and Return

```python
    # Blend original and ML confidence
    original_confidence = request.get('confidence', 0.5)
    ml_confidence = predictions.get('direction_confidence', 0.5)
    adjusted_confidence = (original_confidence + ml_confidence) / 2

    return {
        **request,
        'ml_predictions': predictions,
        'ml_adjusted_confidence': adjusted_confidence,
        'ml_timestamp': datetime.now().isoformat()
    }
```

---

## Training

### Training Target

The models predict next-day price direction:

```python
# Target: 1 if price goes up next day, 0 if down
y = (data['close'].shift(-1) > data['close']).astype(int)
```

### Aggregated Training (Fixed in commit 9a20185)

Previously, training on each symbol overwrote the model. Now training aggregates data from all symbols:

```python
async def _train_on_aggregated(
    self,
    all_features: List[pd.DataFrame],
    all_targets: List[pd.Series],
    symbols_used: List[str]
) -> None:
    # Concatenate all data
    X = pd.concat(all_features, axis=0, ignore_index=True)
    y = pd.concat(all_targets, axis=0, ignore_index=True)

    logger.info(f"Training on aggregated data: {len(X)} samples from {len(symbols_used)} symbols")

    # Train/test split (80/20, no shuffle to preserve time order)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )

    # Scale
    X_train_scaled = self.scalers['default'].fit_transform(X_train)
    X_test_scaled = self.scalers['default'].transform(X_test)

    # Train both models
    self.models['direction'].fit(X_train_scaled, y_train)
    self.models['probability'].fit(X_train_scaled, y_train)

    # Evaluate
    train_acc = self.models['direction'].score(X_train_scaled, y_train)
    test_acc = self.models['direction'].score(X_test_scaled, y_test)

    logger.info(f"Aggregated training complete - Train: {train_acc:.2%}, Test: {test_acc:.2%}")

    # Save with versioning
    self.model_manager.save_models(
        models=self.models,
        scalers=self.scalers,
        train_accuracy=train_acc,
        test_accuracy=test_acc,
        training_samples=len(X_train),
        feature_count=X_train.shape[1],
        symbols=symbols_used
    )
```

### Training Symbols

Auto-retrain uses a diverse set of liquid symbols:

```python
training_symbols = {
    'equity': ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA'],
    'crypto': ['BTC-USD', 'ETH-USD'],
}
```

---

## Model Manager

**Location**: `core/model_manager.py`

The ModelManager handles:
- Model persistence with versioning
- Rolling accuracy tracking
- Staleness detection
- Automatic retraining triggers

### Staleness Detection

```python
def should_retrain(self) -> Dict:
    # Time-based: retrain weekly
    if self.last_trained is None:
        return {"should_retrain": True, "reason": "never_trained"}

    days_since = (datetime.now() - self.last_trained).days
    if days_since >= 7:
        return {"should_retrain": True, "reason": "stale_model"}

    # Accuracy-based: retrain if accuracy drops below 55%
    accuracy = self.get_rolling_accuracy()
    if accuracy is not None and accuracy < 0.55:
        return {"should_retrain": True, "reason": "low_accuracy"}

    return {"should_retrain": False, "reason": None}
```

### Rolling Accuracy Tracking

```python
def record_prediction(self, symbol: str, predicted_direction: str, confidence: float):
    self.predictions.append({
        'symbol': symbol,
        'direction': predicted_direction,
        'confidence': confidence,
        'timestamp': datetime.now()
    })

def record_outcome(self, symbol: str, actual_direction: str):
    # Match with recent prediction and track accuracy
    for pred in reversed(self.predictions):
        if pred['symbol'] == symbol and not pred.get('resolved'):
            pred['actual'] = actual_direction
            pred['correct'] = (pred['direction'] == actual_direction)
            pred['resolved'] = True
            break

def get_rolling_accuracy(self, window: int = 100) -> Optional[float]:
    resolved = [p for p in self.predictions if p.get('resolved')]
    if len(resolved) < 20:  # Minimum sample size
        return None
    recent = resolved[-window:]
    return sum(p['correct'] for p in recent) / len(recent)
```

### Model Rollback

If a newly trained model performs worse than random:

```python
async def _auto_retrain(self, reason: str) -> None:
    # ... training logic ...

    # Check if new model is better
    accuracy = self.model_manager.get_rolling_accuracy()
    if accuracy is not None and accuracy < 0.50:
        logger.warning("New model worse than random - rolling back")
        self.model_manager.rollback()
        loaded = self.model_manager.load_models()
        if loaded:
            self.models = loaded["models"]
            self.scalers = loaded["scalers"]
```

---

## Output Format

```python
{
    # Original signal fields preserved
    'symbol': 'AAPL',
    'market_type': 'equity',
    'signal_type': 'BUY',
    'entry_price': 178.50,
    'confidence': 0.72,

    # ML predictions added
    'ml_predictions': {
        'direction': 'up',
        'direction_confidence': 0.68,
        'up_probability': 0.71
    },

    # Adjusted confidence (blend of original and ML)
    'ml_adjusted_confidence': 0.70,  # (0.72 + 0.68) / 2

    # Timestamp
    'ml_timestamp': '2026-02-05T14:35:22.456789'
}
```

---

## Model Performance Expectations

### Realistic Accuracy Range

| Metric | Poor | Acceptable | Good |
|--------|------|------------|------|
| Train Accuracy | < 55% | 55-65% | 65-75% |
| Test Accuracy | < 52% | 52-58% | 58-65% |
| Rolling Accuracy | < 50% | 50-55% | 55-60% |

**Note**: Stock price direction is inherently difficult to predict. A model with 55% accuracy is actually useful because:
- Combined with other signals, it adds edge
- Even small edge compounds over many trades
- The system uses multiple confirmation layers

### Why Not Higher?

- Markets are mostly efficient (easy patterns are arbitraged)
- Regime changes invalidate learned patterns
- Black swan events are unpredictable
- 60% accuracy would be exceptional for daily direction

---

## Data Flow Summary

```
┌─────────────┐
│   Signal    │
│  (from TA)  │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌──────────────┐
│ Fetch Data  │────▶│  DataCache   │
│  (1 year)   │     │  (Shared)    │
└──────┬──────┘     └──────────────┘
       │
       ▼
┌─────────────┐
│  Extract    │
│  Features   │
│  (31 cols)  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Scale     │
│ (StandardScaler)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────┐
│         Predict             │
│  ┌───────────┐ ┌──────────┐ │
│  │ Direction │ │Probability│ │
│  │ (RF)      │ │(XGBoost) │ │
│  └───────────┘ └──────────┘ │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│      Blend Confidence       │
│ (original + ML) / 2         │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   Track Prediction          │
│   (ModelManager)            │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────┐
│   Output    │
│  (to Ranker)│
└─────────────┘
```

---

## Future Improvements

1. **Symbol Encoding**: Add symbol_id or sector feature so model can learn symbol-specific patterns while sharing common features

2. **Multi-Timeframe Features**: Include weekly and monthly indicators

3. **Ensemble Methods**: Combine multiple model predictions with voting

4. **Deep Learning**: Experiment with LSTM for sequence patterns

5. **Feature Selection**: Use feature importance to prune low-value features

6. **Cross-Validation**: Use time-series cross-validation for more robust evaluation

7. **Confidence Calibration**: Calibrate predicted probabilities to match actual hit rates

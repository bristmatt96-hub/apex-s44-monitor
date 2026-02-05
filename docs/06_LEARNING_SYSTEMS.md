# Layer 6: Learning Systems

## Overview

The Learning Systems layer closes the feedback loop in APEX. When trades close, the outcome data feeds into four learning systems that gradually adjust the system's behavior over time.

This creates an adaptive system that:
- Weights profitable markets higher
- Adjusts edge component weights based on what predicts winners
- Builds a pattern database for future matching
- Tracks ML model accuracy for staleness detection

**Key Principle**: All learning is gradual (max 15% shift per 24hr cycle) with safety floors and caps to prevent runaway adaptation.

---

## Architecture

```
┌─────────────────┐
│  Trade Closed   │
│   (Outcome)     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                      Coordinator                             │
│                   (Fans out to all learners)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ AdaptiveWeights │ │EdgeComponent    │ │ PatternLearner  │ │  ModelManager   │
│                 │ │   Learner       │ │                 │ │                 │
│ Market-type     │ │ Edge score      │ │ Pattern         │ │ Prediction      │
│ weights         │ │ component       │ │ database for    │ │ accuracy        │
│                 │ │ weights         │ │ matching        │ │ tracking        │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
```

---

## 1. AdaptiveWeights

**Location**: `core/adaptive_weights.py`

### Purpose

Adjusts market-type weights based on which markets are actually profitable. If crypto trades are consistently profitable and forex trades are losing, the system will weight crypto signals higher over time.

### Initial Weights

```python
DEFAULT_WEIGHTS = {
    'crypto': 0.85,
    'options': 0.80,
    'equity': 0.70,
    'forex': 0.60
}
```

### Configuration

```python
class AdaptiveWeights:
    def __init__(self, config: Optional[Dict] = None):
        self.weights = self._load_weights() or DEFAULT_WEIGHTS.copy()

        # Learning parameters
        self.learning_rate = 0.05      # 5% adjustment per update
        self.min_weight = 0.40         # Floor - never go below 40%
        self.max_weight = 1.30         # Cap - never exceed 130%
        self.min_trades = 10           # Minimum trades before adjusting
        self.decay_period = 30         # Days before weights decay toward default

        # Trade tracking
        self.trade_outcomes: Dict[str, List] = defaultdict(list)
```

### Weight Update Logic

```python
def record_outcome(self, market_type: str, pnl: float, pnl_pct: float) -> None:
    """Record a trade outcome for learning"""
    self.trade_outcomes[market_type].append({
        'pnl': pnl,
        'pnl_pct': pnl_pct,
        'timestamp': datetime.now()
    })

    # Keep only recent outcomes (90 days)
    cutoff = datetime.now() - timedelta(days=90)
    self.trade_outcomes[market_type] = [
        o for o in self.trade_outcomes[market_type]
        if o['timestamp'] > cutoff
    ]

def update_weights(self) -> Dict[str, float]:
    """Update weights based on recent performance"""
    for market_type, outcomes in self.trade_outcomes.items():
        if len(outcomes) < self.min_trades:
            continue

        # Calculate win rate
        winners = sum(1 for o in outcomes if o['pnl'] > 0)
        win_rate = winners / len(outcomes)

        # Calculate average P&L
        avg_pnl_pct = sum(o['pnl_pct'] for o in outcomes) / len(outcomes)

        # Performance score (blend of win rate and avg P&L)
        performance = (win_rate * 0.6) + (min(avg_pnl_pct / 10, 0.4))

        # Current weight
        current = self.weights.get(market_type, 0.70)

        # Target weight based on performance
        if performance > 0.6:  # Good performance
            target = min(current * 1.1, self.max_weight)
        elif performance < 0.4:  # Poor performance
            target = max(current * 0.9, self.min_weight)
        else:
            target = current  # No change

        # Gradual adjustment (learning rate)
        adjustment = (target - current) * self.learning_rate
        new_weight = current + adjustment

        # Apply bounds
        new_weight = max(self.min_weight, min(self.max_weight, new_weight))

        self.weights[market_type] = new_weight

    self._save_weights()
    return self.weights
```

### Decay Toward Default

Weights gradually decay toward default if no recent trades:

```python
def apply_decay(self) -> None:
    """Decay weights toward default if no recent activity"""
    for market_type, default in DEFAULT_WEIGHTS.items():
        outcomes = self.trade_outcomes.get(market_type, [])

        if not outcomes:
            continue

        # Check last trade date
        last_trade = max(o['timestamp'] for o in outcomes)
        days_inactive = (datetime.now() - last_trade).days

        if days_inactive > self.decay_period:
            current = self.weights.get(market_type, default)
            # Decay 10% toward default per inactive period
            decay_rate = 0.10 * (days_inactive // self.decay_period)
            decay_rate = min(decay_rate, 0.50)  # Cap at 50% decay

            new_weight = current + (default - current) * decay_rate
            self.weights[market_type] = new_weight
```

### Persistence

```python
def _save_weights(self) -> None:
    state = {
        'weights': self.weights,
        'trade_outcomes': {
            k: [{'pnl': o['pnl'], 'pnl_pct': o['pnl_pct'],
                 'timestamp': o['timestamp'].isoformat()}
                for o in v]
            for k, v in self.trade_outcomes.items()
        },
        'updated_at': datetime.now().isoformat()
    }

    with open('data/adaptive_weights.json', 'w') as f:
        json.dump(state, f, indent=2)

def _load_weights(self) -> Optional[Dict]:
    try:
        with open('data/adaptive_weights.json', 'r') as f:
            state = json.load(f)

        self.weights = state['weights']
        self.trade_outcomes = {
            k: [{'pnl': o['pnl'], 'pnl_pct': o['pnl_pct'],
                 'timestamp': datetime.fromisoformat(o['timestamp'])}
                for o in v]
            for k, v in state.get('trade_outcomes', {}).items()
        }

        return self.weights
    except (FileNotFoundError, json.JSONDecodeError):
        return None
```

---

## 2. EdgeComponentLearner

**Location**: `core/edge_component_learner.py`

### Purpose

Adjusts the weights of edge score components based on which components predict winning trades. If trades with high "confluence" scores are winning more often, that component's weight increases.

### Edge Score Components

| Component | Initial Weight | Description |
|-----------|----------------|-------------|
| risk_reward | 0.30 | Risk/reward ratio |
| confidence | 0.25 | Signal confidence |
| timing | 0.15 | Session/market timing |
| liquidity | 0.15 | Volume and spread |
| confluence | 0.15 | Signal alignment |

### Configuration

```python
class EdgeComponentLearner:
    def __init__(self, config: Optional[Dict] = None):
        self.component_weights = {
            'risk_reward': 0.30,
            'confidence': 0.25,
            'timing': 0.15,
            'liquidity': 0.15,
            'confluence': 0.15
        }

        # Learning parameters
        self.min_trades = 20           # Minimum before adapting
        self.adaptation_cycle = 86400  # 24 hours between adaptations
        self.max_shift = 0.15          # Max 15% shift per cycle
        self.min_weight = 0.05         # Floor for any component
        self.max_weight = 0.40         # Cap for any component

        # Trade records
        self.trade_records: List[Dict] = []
        self.last_adaptation: Optional[datetime] = None
```

### Recording Trade Data

```python
def record_trade(
    self,
    trade: Trade,
    component_scores: Dict[str, float],
    outcome: str  # 'win' or 'loss'
) -> None:
    """Record a trade with its component scores for learning"""
    self.trade_records.append({
        'timestamp': datetime.now(),
        'symbol': trade.symbol,
        'market_type': trade.market_type,
        'component_scores': component_scores,
        'outcome': outcome,
        'pnl': trade.pnl,
        'pnl_pct': trade.pnl_pct
    })

    # Keep only recent records (90 days)
    cutoff = datetime.now() - timedelta(days=90)
    self.trade_records = [r for r in self.trade_records if r['timestamp'] > cutoff]
```

### Adaptation Logic

```python
def should_adapt(self) -> bool:
    """Check if it's time to adapt"""
    if len(self.trade_records) < self.min_trades:
        return False

    if self.last_adaptation is None:
        return True

    elapsed = (datetime.now() - self.last_adaptation).total_seconds()
    return elapsed >= self.adaptation_cycle

def adapt(self) -> Optional[Dict]:
    """Adapt component weights based on trade outcomes"""
    if not self.should_adapt():
        return None

    # Separate winners and losers
    winners = [r for r in self.trade_records if r['outcome'] == 'win']
    losers = [r for r in self.trade_records if r['outcome'] == 'loss']

    if len(winners) < 5 or len(losers) < 5:
        return None

    adjustments = {}

    for component in self.component_weights.keys():
        # Average score for winners vs losers
        winner_avg = sum(
            r['component_scores'].get(component, 0)
            for r in winners
        ) / len(winners)

        loser_avg = sum(
            r['component_scores'].get(component, 0)
            for r in losers
        ) / len(losers)

        # Differential: how much higher is the component for winners?
        diff = winner_avg - loser_avg

        # Adjust weight based on predictive power
        current = self.component_weights[component]

        if diff > 0.1:  # Component predicts winners
            adjustment = min(current * 0.1, self.max_shift)
            new_weight = current + adjustment
        elif diff < -0.1:  # Component predicts losers (inverse signal)
            adjustment = min(current * 0.1, self.max_shift)
            new_weight = current - adjustment
        else:
            new_weight = current

        # Apply bounds
        new_weight = max(self.min_weight, min(self.max_weight, new_weight))
        self.component_weights[component] = new_weight

        adjustments[component] = {
            'old': current,
            'new': new_weight,
            'winner_avg': winner_avg,
            'loser_avg': loser_avg,
            'differential': diff
        }

    # Normalize weights to sum to 1.0
    total = sum(self.component_weights.values())
    self.component_weights = {k: v/total for k, v in self.component_weights.items()}

    self.last_adaptation = datetime.now()
    self._save_state()

    return adjustments
```

---

## 3. PatternLearner

**Location**: `core/pattern_learner.py`

### Purpose

Builds a database of trade patterns for future matching. When a new signal comes in, the system can check if similar patterns have historically been profitable.

### Pattern Structure

```python
@dataclass
class TradePattern:
    pattern_id: str
    symbol: str
    market_type: str
    strategy: str

    # Technical conditions at entry
    trend_score: float
    momentum_score: float
    volume_score: float
    volatility_score: float

    # Signal characteristics
    risk_reward: float
    confidence: float

    # Outcome
    outcome: str  # 'win' or 'loss'
    pnl_pct: float
    hold_time_hours: float

    # Metadata
    timestamp: datetime
    tags: List[str]
```

### Learning Process

```python
class PatternLearner:
    def __init__(self):
        self.patterns: List[TradePattern] = []
        self.pattern_clusters: Dict[str, List[TradePattern]] = {}
        self._load_patterns()

    def record_pattern(self, trade: Trade, signal: Dict, outcome: str) -> None:
        """Extract and store pattern from closed trade"""
        pattern = TradePattern(
            pattern_id=f"PAT-{datetime.now().timestamp()}",
            symbol=trade.symbol,
            market_type=trade.market_type,
            strategy=signal.get('metadata', {}).get('strategy', 'unknown'),

            # TA scores
            trend_score=signal.get('ta_scores', {}).get('trend', 0.5),
            momentum_score=signal.get('ta_scores', {}).get('momentum', 0.5),
            volume_score=signal.get('ta_scores', {}).get('volume', 0.5),
            volatility_score=signal.get('ta_scores', {}).get('volatility', {}).get('risk_score', 0.5),

            # Signal characteristics
            risk_reward=signal.get('risk_reward_ratio', 2.0),
            confidence=signal.get('ml_adjusted_confidence', 0.5),

            # Outcome
            outcome=outcome,
            pnl_pct=trade.pnl_pct,
            hold_time_hours=(trade.exit_time - trade.entry_time).total_seconds() / 3600,

            # Metadata
            timestamp=datetime.now(),
            tags=self._generate_tags(signal)
        )

        self.patterns.append(pattern)
        self._update_clusters(pattern)
        self._save_patterns()

    def _generate_tags(self, signal: Dict) -> List[str]:
        """Generate searchable tags for pattern"""
        tags = []

        # Market condition tags
        ta = signal.get('ta_scores', {})
        if ta.get('trend', 0) > 0.7:
            tags.append('strong_trend')
        if ta.get('momentum', 0) > 0.7:
            tags.append('high_momentum')
        if ta.get('volume', 0) > 0.7:
            tags.append('high_volume')

        # Strategy tags
        strategy = signal.get('metadata', {}).get('strategy', '')
        tags.append(f"strategy:{strategy}")

        # Signal type tags
        signal_type = signal.get('signal_type', '')
        tags.append(f"signal:{signal_type}")

        return tags
```

### Pattern Matching

```python
def find_similar_patterns(
    self,
    signal: Dict,
    min_similarity: float = 0.7,
    max_results: int = 10
) -> List[Tuple[TradePattern, float]]:
    """Find historical patterns similar to current signal"""
    matches = []

    current_vector = self._signal_to_vector(signal)

    for pattern in self.patterns:
        pattern_vector = self._pattern_to_vector(pattern)

        # Cosine similarity
        similarity = self._cosine_similarity(current_vector, pattern_vector)

        if similarity >= min_similarity:
            matches.append((pattern, similarity))

    # Sort by similarity
    matches.sort(key=lambda x: x[1], reverse=True)

    return matches[:max_results]

def get_pattern_edge(self, signal: Dict) -> Dict:
    """Calculate edge based on similar historical patterns"""
    similar = self.find_similar_patterns(signal)

    if len(similar) < 5:
        return {'has_edge': False, 'reason': 'insufficient_patterns'}

    winners = sum(1 for p, s in similar if p.outcome == 'win')
    win_rate = winners / len(similar)

    avg_pnl = sum(p.pnl_pct for p, s in similar) / len(similar)

    return {
        'has_edge': win_rate > 0.55,
        'pattern_count': len(similar),
        'win_rate': win_rate,
        'avg_pnl_pct': avg_pnl,
        'similar_patterns': [(p.pattern_id, s) for p, s in similar[:5]]
    }
```

---

## 4. ModelManager

**Location**: `core/model_manager.py`

### Purpose

Tracks ML model accuracy over time and triggers retraining when models become stale or underperform.

### Prediction Tracking

```python
class ModelManager:
    def __init__(self):
        self.predictions: List[Dict] = []
        self.model_versions: List[Dict] = []
        self.current_version: Optional[str] = None
        self.last_trained: Optional[datetime] = None

    def record_prediction(
        self,
        symbol: str,
        predicted_direction: str,
        confidence: float
    ) -> None:
        """Record a prediction for accuracy tracking"""
        self.predictions.append({
            'id': f"PRED-{datetime.now().timestamp()}",
            'symbol': symbol,
            'direction': predicted_direction,
            'confidence': confidence,
            'timestamp': datetime.now(),
            'resolved': False,
            'correct': None
        })

        # Keep only recent predictions
        cutoff = datetime.now() - timedelta(days=30)
        self.predictions = [p for p in self.predictions if p['timestamp'] > cutoff]

    def record_outcome(self, symbol: str, actual_direction: str) -> None:
        """Record the actual outcome for a prediction"""
        # Find most recent unresolved prediction for this symbol
        for pred in reversed(self.predictions):
            if pred['symbol'] == symbol and not pred['resolved']:
                pred['actual'] = actual_direction
                pred['correct'] = (pred['direction'] == actual_direction)
                pred['resolved'] = True
                pred['resolved_at'] = datetime.now()
                break
```

### Accuracy Calculation

```python
def get_rolling_accuracy(self, window: int = 100) -> Optional[float]:
    """Calculate rolling accuracy over recent predictions"""
    resolved = [p for p in self.predictions if p['resolved']]

    if len(resolved) < 20:  # Minimum sample size
        return None

    recent = resolved[-window:]
    correct = sum(1 for p in recent if p['correct'])

    return correct / len(recent)

def get_accuracy_by_market(self) -> Dict[str, float]:
    """Get accuracy broken down by market type"""
    by_market = defaultdict(list)

    for pred in self.predictions:
        if pred['resolved']:
            market = pred.get('market_type', 'unknown')
            by_market[market].append(pred['correct'])

    return {
        market: sum(outcomes) / len(outcomes)
        for market, outcomes in by_market.items()
        if len(outcomes) >= 10
    }
```

### Staleness Detection

```python
def should_retrain(self) -> Dict:
    """Determine if models need retraining"""
    # Never trained
    if self.last_trained is None:
        return {'should_retrain': True, 'reason': 'never_trained'}

    # Time-based staleness (7 days)
    days_since = (datetime.now() - self.last_trained).days
    if days_since >= 7:
        return {'should_retrain': True, 'reason': 'stale_model'}

    # Accuracy-based trigger
    accuracy = self.get_rolling_accuracy()
    if accuracy is not None and accuracy < 0.55:
        return {'should_retrain': True, 'reason': 'low_accuracy'}

    # Accuracy declining
    if self._is_accuracy_declining():
        return {'should_retrain': True, 'reason': 'declining_accuracy'}

    return {'should_retrain': False, 'reason': None}

def _is_accuracy_declining(self) -> bool:
    """Check if accuracy has been declining over time"""
    resolved = [p for p in self.predictions if p['resolved']]

    if len(resolved) < 50:
        return False

    # Compare first half vs second half
    mid = len(resolved) // 2
    first_half = resolved[:mid]
    second_half = resolved[mid:]

    first_acc = sum(p['correct'] for p in first_half) / len(first_half)
    second_acc = sum(p['correct'] for p in second_half) / len(second_half)

    # Declining if second half is 10%+ worse
    return (first_acc - second_acc) > 0.10
```

### Model Versioning

```python
def save_models(
    self,
    models: Dict,
    scalers: Dict,
    train_accuracy: float,
    test_accuracy: float,
    training_samples: int,
    feature_count: int,
    symbols: List[str]
) -> str:
    """Save models with version metadata"""
    version = f"v{len(self.model_versions) + 1}-{datetime.now().strftime('%Y%m%d')}"

    # Save model files
    model_dir = Path(f"models/{version}")
    model_dir.mkdir(parents=True, exist_ok=True)

    for name, model in models.items():
        with open(model_dir / f"{name}.pkl", 'wb') as f:
            pickle.dump(model, f)

    for name, scaler in scalers.items():
        with open(model_dir / f"{name}_scaler.pkl", 'wb') as f:
            pickle.dump(scaler, f)

    # Record version metadata
    version_info = {
        'version': version,
        'created_at': datetime.now().isoformat(),
        'train_accuracy': train_accuracy,
        'test_accuracy': test_accuracy,
        'training_samples': training_samples,
        'feature_count': feature_count,
        'symbols': symbols
    }

    self.model_versions.append(version_info)
    self.current_version = version
    self.last_trained = datetime.now()

    self._save_metadata()

    return version

def rollback(self) -> bool:
    """Rollback to previous model version"""
    if len(self.model_versions) < 2:
        return False

    # Remove current version
    self.model_versions.pop()

    # Set previous as current
    self.current_version = self.model_versions[-1]['version']

    self._save_metadata()
    return True
```

---

## Learning Safeguards

### 1. Minimum Sample Sizes

All learners require minimum trade counts before adjusting:

| Learner | Minimum |
|---------|---------|
| AdaptiveWeights | 10 trades per market |
| EdgeComponentLearner | 20 trades total |
| PatternLearner | 5 similar patterns |
| ModelManager | 20 predictions |

### 2. Rate Limiting

Maximum change per adaptation cycle:

| Learner | Max Change | Cycle |
|---------|------------|-------|
| AdaptiveWeights | 5% per update | On each trade |
| EdgeComponentLearner | 15% per component | 24 hours |
| ModelManager | Full retrain | 7 days or accuracy trigger |

### 3. Bounds

Hard limits prevent runaway adaptation:

| Parameter | Min | Max |
|-----------|-----|-----|
| Market weight | 0.40 | 1.30 |
| Component weight | 0.05 | 0.40 |
| ML accuracy trigger | 0.55 | N/A |

### 4. Decay

Weights decay toward defaults during inactivity:

- After 30 days of no trades: 10% decay toward default
- Maximum decay: 50% toward default

---

## Data Flow Summary

```
┌─────────────┐
│ Trade Closes│
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│    Coordinator      │
│  _notify_trade_closed()
└──────┬──────────────┘
       │
       ├───────────────────────────────────────────┐
       │                                           │
       ▼                                           ▼
┌─────────────────┐                       ┌─────────────────┐
│ AdaptiveWeights │                       │EdgeComponent    │
│ record_outcome()│                       │   Learner       │
│ update_weights()│                       │ record_trade()  │
└─────────────────┘                       │ adapt()         │
                                          └─────────────────┘
       │                                           │
       ├───────────────────────────────────────────┤
       │                                           │
       ▼                                           ▼
┌─────────────────┐                       ┌─────────────────┐
│ PatternLearner  │                       │  ModelManager   │
│ record_pattern()│                       │ record_outcome()│
│                 │                       │                 │
└─────────────────┘                       └─────────────────┘
```

---

## Future Improvements

1. **Ensemble Learning**: Combine multiple learning systems' signals

2. **Regime Detection**: Detect market regime changes and adjust faster

3. **A/B Testing**: Test weight changes on paper before applying to live

4. **Feature Importance**: Track which ML features predict best

5. **Correlation Analysis**: Detect when patterns become less predictive

6. **Backtest Validation**: Validate weight changes against historical data

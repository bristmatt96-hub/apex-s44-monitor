# Layer 4: Opportunity Ranking

## Overview

The Opportunity Ranking layer scores and prioritizes all validated signals using a multi-factor scoring system. It combines risk/reward metrics, confidence levels, timing factors, liquidity, and diversification considerations into a single composite score.

The ranker also applies multipliers based on:
- Adaptive market weights (learned from trade outcomes)
- Strategy performance bonuses (from backtests)
- Signal confluence (insider buying + technical, options flow + technical)
- Knowledge base psychology adjustments

**Location**: `core/opportunity_ranker.py`

---

## Architecture

```
┌─────────────┐     ┌─────────────────────┐     ┌─────────────┐
│ MLPredictor │────▶│ OpportunityRanker   │────▶│ Coordinator │
│   Signal    │     │                     │     │  (Decision) │
└─────────────┘     └──────────┬──────────┘     └─────────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
        ┌───────────┐  ┌───────────┐  ┌───────────┐
        │  Base     │  │ Multipliers│  │ Confluence │
        │  Scoring  │  │           │  │ Detection  │
        └───────────┘  └───────────┘  └───────────┘
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                    ┌─────────────────┐
                    │  Final Score    │
                    │  (0-1 range)    │
                    └─────────────────┘
```

---

## Base Scoring Components

The ranker scores signals on five dimensions:

| Component | Weight | Description |
|-----------|--------|-------------|
| Risk/Reward | 30% | Higher R:R = higher score |
| Confidence | 25% | Blended signal confidence |
| Timing | 20% | Market session, strategy timing |
| Liquidity | 15% | Volume and spread considerations |
| Diversification | 10% | Portfolio balance impact |

### 1. Risk/Reward Score (30%)

```python
def _score_risk_reward(self, signal: Dict) -> float:
    rr_ratio = signal.get('risk_reward_ratio', 1.0)

    # 5:1 R:R = perfect score
    # Linear interpolation from 1:1 (0.2) to 5:1 (1.0)
    if rr_ratio >= 5.0:
        return 1.0
    elif rr_ratio <= 1.0:
        return 0.2
    else:
        return 0.2 + (rr_ratio - 1.0) * 0.2  # 0.2 per R:R increment
```

**Score Table**:

| R:R Ratio | Score |
|-----------|-------|
| 1:1 | 0.20 |
| 2:1 | 0.40 |
| 3:1 | 0.60 |
| 4:1 | 0.80 |
| 5:1+ | 1.00 |

### 2. Confidence Score (25%)

Blends multiple confidence sources:

```python
def _score_confidence(self, signal: Dict) -> float:
    # Original scanner confidence
    base_confidence = signal.get('confidence', 0.5)

    # Technical analysis confidence
    ta_confidence = signal.get('adjusted_confidence', base_confidence)

    # ML confidence
    ml_confidence = signal.get('ml_adjusted_confidence', ta_confidence)

    # Weighted blend
    blended = (
        base_confidence * 0.3 +
        ta_confidence * 0.35 +
        ml_confidence * 0.35
    )

    return min(blended, 1.0)
```

### 3. Timing Score (20%)

Considers market session and strategy-specific timing:

```python
def _score_timing(self, signal: Dict) -> float:
    score = 0.5  # Baseline

    market_type = signal.get('market_type')
    strategy = signal.get('metadata', {}).get('strategy', '')

    # Market hours bonus
    now = datetime.now()
    hour = now.hour

    if market_type == 'equity':
        # US market hours (9:30 AM - 4:00 PM ET)
        if 9 <= hour <= 16:
            score += 0.2
        # First and last hour (higher volatility)
        if hour in [9, 10, 15, 16]:
            score += 0.1

    elif market_type == 'crypto':
        # 24/7 - always tradeable
        score += 0.15

    elif market_type == 'forex':
        # Major sessions
        if 8 <= hour <= 12:  # London
            score += 0.2
        elif 13 <= hour <= 17:  # NY overlap
            score += 0.25

    # Strategy-specific timing
    if 'mean_reversion' in strategy:
        # Best after extended moves
        score += 0.1
    elif 'momentum' in strategy:
        # Best with fresh breakouts
        if hour in [10, 11]:  # After open consolidation
            score += 0.1

    return min(score, 1.0)
```

### 4. Liquidity Score (15%)

```python
def _score_liquidity(self, signal: Dict) -> float:
    volume = signal.get('metadata', {}).get('volume', 0)
    avg_volume = signal.get('metadata', {}).get('avg_volume', 1)
    volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

    score = 0.3  # Baseline

    # Volume ratio scoring
    if volume_ratio > 2.0:
        score += 0.4
    elif volume_ratio > 1.5:
        score += 0.3
    elif volume_ratio > 1.0:
        score += 0.2

    # Absolute volume check (for equities)
    if volume > 1_000_000:
        score += 0.2
    elif volume > 500_000:
        score += 0.1

    return min(score, 1.0)
```

### 5. Diversification Score (10%)

Penalizes concentration in single symbol/sector:

```python
def _score_diversification(self, signal: Dict, current_positions: List) -> float:
    symbol = signal.get('symbol')
    market_type = signal.get('market_type')

    score = 1.0  # Start perfect

    # Check existing positions
    same_symbol = sum(1 for p in current_positions if p.symbol == symbol)
    same_market = sum(1 for p in current_positions if p.market_type == market_type)

    # Penalize duplicate symbols heavily
    if same_symbol > 0:
        score -= 0.4 * same_symbol

    # Penalize market concentration
    if same_market > 3:
        score -= 0.1 * (same_market - 3)

    return max(score, 0.1)  # Floor at 0.1
```

---

## Composite Score Calculation

```python
def calculate_base_score(self, signal: Dict, positions: List) -> float:
    rr_score = self._score_risk_reward(signal)
    conf_score = self._score_confidence(signal)
    timing_score = self._score_timing(signal)
    liquidity_score = self._score_liquidity(signal)
    diversification_score = self._score_diversification(signal, positions)

    composite = (
        rr_score * 0.30 +
        conf_score * 0.25 +
        timing_score * 0.20 +
        liquidity_score * 0.15 +
        diversification_score * 0.10
    )

    return composite
```

---

## Multipliers

After base scoring, the ranker applies multipliers:

### 1. Adaptive Market Weight (0.7x - 1.3x)

Learned from trade outcomes. Markets that have been profitable get weighted higher:

```python
# From adaptive_weights.py
market_weights = {
    'crypto': 0.95,   # Recent winner
    'options': 0.90,
    'equity': 0.70,
    'forex': 0.45     # Recent underperformer
}

multiplier = market_weights.get(market_type, 0.70)
```

These weights adjust over time based on the EdgeComponentLearner's analysis of closed trades.

### 2. Strategy Bonus (0.85x - 1.25x)

Based on backtest profit factors:

```python
strategy_multipliers = {
    # High-edge strategies (backtest PF > 2.0)
    'volume_spike_reversal': 1.25,
    'mean_reversion': 1.20,

    # Proven strategies (backtest PF 1.5-2.0)
    'momentum_breakout': 1.15,
    'insider_buying': 1.15,

    # Standard strategies
    'trend_following': 1.05,
    'breakout': 1.00,

    # Lower-edge strategies
    'gap_play': 0.90,
    'unknown': 0.85
}
```

### 3. Technical Confirmation (1.1x)

Applied when TA composite score is strong:

```python
ta_composite = signal.get('ta_scores', {}).get('composite', 0.5)
if ta_composite > 0.7:
    multiplier *= 1.10
```

### 4. ML Confirmation (1.08x)

Applied when ML prediction aligns with signal direction:

```python
ml_direction = signal.get('ml_predictions', {}).get('direction')
signal_direction = 'up' if signal.get('signal_type') == 'BUY' else 'down'

if ml_direction == signal_direction:
    ml_confidence = signal.get('ml_predictions', {}).get('direction_confidence', 0.5)
    if ml_confidence > 0.6:
        multiplier *= 1.08
```

### 5. Insider Confluence (1.15x)

Applied when technical signal aligns with recent insider buying:

```python
def _check_insider_confluence(self, signal: Dict) -> bool:
    symbol = signal.get('symbol')

    # Check for insider buying signals in last 7 days
    insider_signals = [
        s for s in self.recent_signals
        if s.get('source') == 'edgar_insider'
        and s.get('symbol') == symbol
        and s.get('signal_type') == 'BUY'
        and (datetime.now() - s.get('timestamp')).days <= 7
    ]

    return len(insider_signals) > 0
```

### 6. Options Flow Confluence (1.12x)

Applied when unusual options activity supports the signal:

```python
def _check_flow_confluence(self, signal: Dict) -> bool:
    symbol = signal.get('symbol')
    signal_type = signal.get('signal_type')

    # Check for matching flow in last 3 days
    flow_signals = [
        s for s in self.recent_signals
        if s.get('source') == 'options_flow'
        and s.get('symbol') == symbol
        and (datetime.now() - s.get('timestamp')).days <= 3
    ]

    for flow in flow_signals:
        flow_type = flow.get('metadata', {}).get('flow_type', '')
        if signal_type == 'BUY' and 'bullish' in flow_type:
            return True
        if signal_type == 'SELL' and 'bearish' in flow_type:
            return True

    return False
```

### 7. Knowledge Base Psychology (0.92x - 1.05x)

Queries the knowledge retriever for psychological patterns:

```python
def _apply_psychology_adjustment(self, signal: Dict) -> float:
    retriever = KnowledgeRetriever()

    # Check for greed traps
    query = f"greed trap {signal.get('strategy')} overbought"
    greed_matches = retriever.search(query)
    if greed_matches and signal.get('ta_scores', {}).get('momentum', 0) > 0.8:
        return 0.92  # Penalize potential greed trap

    # Check for disciplined setups
    query = f"disciplined entry {signal.get('strategy')} patience"
    discipline_matches = retriever.search(query)
    if discipline_matches:
        return 1.05  # Reward disciplined setup

    return 1.0  # Neutral
```

---

## Final Score Formula

```python
def rank(self, signal: Dict, positions: List) -> float:
    # Base score (0-1)
    base_score = self.calculate_base_score(signal, positions)

    # Start with base multiplier
    multiplier = 1.0

    # Apply market weight
    market_type = signal.get('market_type')
    multiplier *= self.adaptive_weights.get_weight(market_type)

    # Apply strategy bonus
    strategy = signal.get('metadata', {}).get('strategy', 'unknown')
    multiplier *= self.strategy_multipliers.get(strategy, 0.85)

    # Apply confirmations
    if signal.get('ta_scores', {}).get('composite', 0) > 0.7:
        multiplier *= 1.10

    if self._check_ml_confirmation(signal):
        multiplier *= 1.08

    if self._check_insider_confluence(signal):
        multiplier *= 1.15

    if self._check_flow_confluence(signal):
        multiplier *= 1.12

    # Apply psychology adjustment
    multiplier *= self._apply_psychology_adjustment(signal)

    # Final score
    final_score = base_score * multiplier

    # Cap at 1.0
    return min(final_score, 1.0)
```

---

## Minimum Thresholds

Signals must meet minimum criteria to be considered:

```python
MIN_RISK_REWARD = 2.0   # Minimum 2:1 R:R
MIN_CONFIDENCE = 0.65   # Minimum 65% blended confidence

def is_tradeable(self, signal: Dict) -> bool:
    rr = signal.get('risk_reward_ratio', 0)
    confidence = signal.get('ml_adjusted_confidence',
                           signal.get('adjusted_confidence',
                                      signal.get('confidence', 0)))

    if rr < MIN_RISK_REWARD:
        return False

    if confidence < MIN_CONFIDENCE:
        return False

    return True
```

---

## Ranking Multiple Signals

When multiple signals pass validation simultaneously:

```python
def rank_all(self, signals: List[Dict], positions: List) -> List[Dict]:
    # Filter tradeable signals
    tradeable = [s for s in signals if self.is_tradeable(s)]

    # Score each signal
    scored = []
    for signal in tradeable:
        score = self.rank(signal, positions)
        scored.append({
            **signal,
            'opportunity_score': score
        })

    # Sort by score (highest first)
    scored.sort(key=lambda s: s['opportunity_score'], reverse=True)

    return scored
```

---

## Output Format

```python
{
    # Original signal fields
    'symbol': 'AAPL',
    'market_type': 'equity',
    'signal_type': 'BUY',
    'entry_price': 178.50,
    'stop_loss': 175.00,
    'target_price': 185.00,
    'risk_reward_ratio': 2.1,

    # Previous layer scores
    'confidence': 0.72,
    'ta_scores': { ... },
    'ml_predictions': { ... },
    'ml_adjusted_confidence': 0.70,

    # Ranking scores
    'opportunity_score': 0.82,
    'score_breakdown': {
        'risk_reward': 0.42,
        'confidence': 0.67,
        'timing': 0.75,
        'liquidity': 0.80,
        'diversification': 0.90,
        'base_score': 0.62
    },
    'multipliers_applied': {
        'market_weight': 0.70,
        'strategy_bonus': 1.20,
        'ta_confirmation': 1.10,
        'ml_confirmation': 1.08,
        'insider_confluence': False,
        'flow_confluence': False,
        'psychology': 1.0,
        'total_multiplier': 0.997
    },

    # Ranking timestamp
    'ranked_at': '2026-02-05T14:38:45.123456'
}
```

---

## Score Interpretation

| Final Score | Interpretation | Action |
|-------------|----------------|--------|
| 0.85 - 1.00 | Exceptional opportunity | High priority execution |
| 0.70 - 0.85 | Strong opportunity | Standard execution |
| 0.55 - 0.70 | Moderate opportunity | Consider with caution |
| 0.40 - 0.55 | Weak opportunity | Usually skip |
| < 0.40 | Poor opportunity | Always skip |

---

## Example Scoring Walkthrough

**Signal**: TSLA mean reversion buy

**Base Scores**:
- R:R: 3.2:1 → 0.64 × 0.30 = 0.192
- Confidence: 0.75 → 0.75 × 0.25 = 0.188
- Timing: Market hours + strategy timing → 0.70 × 0.20 = 0.140
- Liquidity: High volume → 0.85 × 0.15 = 0.128
- Diversification: No TSLA positions → 0.95 × 0.10 = 0.095

**Base Score**: 0.743

**Multipliers**:
- Market (equity): 0.70
- Strategy (mean_reversion): 1.20
- TA confirmation (composite 0.72): 1.10
- ML confirmation (aligned, 0.65 conf): 1.08
- Insider: No → 1.0
- Flow: No → 1.0
- Psychology: Neutral → 1.0

**Total Multiplier**: 0.70 × 1.20 × 1.10 × 1.08 = 0.997

**Final Score**: 0.743 × 0.997 = **0.741**

**Result**: Strong opportunity, standard execution priority.

---

## Future Improvements

1. **Dynamic Thresholds**: Adjust minimums based on market conditions (raise during volatility)

2. **Sector Diversification**: Track and balance sector exposure, not just market type

3. **Time Decay**: Reduce score for signals that have been pending too long

4. **Correlation Penalties**: Reduce score for highly correlated positions

5. **Capital Efficiency**: Factor in capital requirements for options vs equity

6. **Event Calendar**: Boost/penalize based on upcoming events (earnings, FOMC)

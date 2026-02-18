# APEX Trading System — Architecture & Recommendations

## How It Works (Top to Bottom)

### The Big Picture

APEX is a multi-agent trading system. Eight scanners watch markets 24/7, looking for opportunities. When one finds something, the signal passes through three validation stages — technical analysis, ML prediction, and multi-factor ranking — before landing on a decision: execute or reject. Closed trades feed back into four learning systems that adjust the system's behaviour over time.

Everything runs as async Python tasks coordinated by a central message bus.

```
Scanners (8)  →  TechnicalAnalyzer  →  MLPredictor  →  OpportunityRanker  →  Coordinator  →  TradeExecutor  →  IB
     ↑                                                                                              |
     └──────────────────── Learning Systems (4) ◄───────────────── trade_closed ◄───────────────────┘
```

---

### Layer 1: Scanning (Market Discovery)

Eight scanners inherit from `BaseScanner` and run on independent intervals. Each watches a universe of symbols, fetches OHLCV data (via yfinance or CCXT), runs strategy-specific logic, and emits `new_signal` messages when criteria are met.

| Scanner | Symbols | Interval | What It Looks For |
|---------|---------|----------|-------------------|
| EquityScanner | 57 stocks/ETFs | 60s | Mean reversion, volume spikes, momentum breakouts |
| CryptoScanner | 7 pairs | 30s | Same strategies, 24/7, no PDT |
| ForexScanner | Currency pairs | 60s | Momentum and mean reversion |
| OptionsScanner | Options chains | 30s | IV-based opportunities |
| OptionsFlowScanner | 27 symbols | 15min | Unusual V/OI, sweeps, straddle detection |
| EdgarInsiderScanner | 30+ tickers | Periodic | SEC Form 4 insider purchases |
| CreditOptionsScanner | 24 XO S44 names | Periodic | Credit deterioration → equity put trades |
| SynthScanner | 9 symbols | 60s | Bittensor SN50 liquidation predictions |

**Output**: A `Signal` dict with symbol, market_type, entry_price, stop_loss, target_price, confidence, risk_reward_ratio, strategy name, and reasoning.

### Layer 2: Technical Validation

`TechnicalAnalyzer` receives each raw signal and scores it across four dimensions:

- **Trend** (30%): EMA20/50, SMA200, ADX
- **Momentum** (30%): RSI, MACD, Stochastic, ROC
- **Volume** (20%): Current vs 20-day average, trend
- **Volatility** (20%): ATR, Bollinger width

If composite > 0.5 and trend > 0.4, the signal passes through with an adjusted confidence score. Otherwise it's dropped.

### Layer 3: ML Prediction

`MLPredictor` runs two models (RandomForest + XGBoost/GradientBoosting) on 31 technical features to predict next-day direction. It outputs a directional probability that later gets blended with the signal's original confidence.

Models auto-retrain weekly or when rolling accuracy drops below 55%. The `ModelManager` tracks prediction accuracy over a rolling window and handles versioned model persistence.

### Layer 4: Ranking

`OpportunityRanker` scores every validated signal on a 0–1 composite scale:

- Risk/Reward (30%) — 5:1 = perfect score
- Confidence (25%) — blended original + TA + ML
- Timing (20%) — session, strategy timing
- Liquidity (15%) — volume ratio
- Diversification (10%) — portfolio spread

Then applies multipliers: adaptive market weight (0.7–1.3x), strategy bonus (0.85–1.25x from backtest data), TA confirmation (1.1x), ML confirmation (1.08x), insider confluence (1.15x), options flow confluence (1.12x), and knowledge-base psychology adjustment (0.92–1.05x).

Minimum thresholds: 2:1 R:R and 65% confidence.

### Layer 5: Decision & Execution

The Coordinator receives ranked opportunities and either:
- **Auto-execute** (if enabled) — sends directly to TradeExecutor
- **Queue for manual approval** — sends Telegram notification, waits for human

`TradeExecutor` connects to Interactive Brokers (live or sim mode). It:
- Sizes positions: min(1% capital risk / risk-per-share, 5% capital / price)
- Places market orders with stop losses
- Tracks PDT compliance (3 day trades for accounts under $25k)
- On position close: calculates P&L, emits `trade_closed` with full edge score snapshot

### Layer 6: Learning

When a trade closes, the Coordinator fans the outcome to four systems:

1. **AdaptiveWeights** — adjusts market-type weights (crypto, options, equity, forex) based on which markets are actually profitable
2. **EdgeComponentLearner** — adjusts the 5 edge score component weights based on which components predict winners
3. **PatternLearner** — adds the trade to the pattern database for future matching
4. **ModelManager** — records whether the ML prediction was correct

All learning is gradual (max 15% shift per 24hr cycle) with safety floors and caps.

### Supporting Systems

**Knowledge Retriever**: TF-IDF search over ingested trading books (Natenberg, Market Wizards, etc.). The ranker queries it to apply psychology-based score adjustments — penalising greed traps, rewarding disciplined setups.

**Telegram Notifier**: Entry/exit alerts, daily summaries, risk limit warnings, opportunity notifications for manual approval.

**Web Dashboard**: Next.js frontend on Vercel + FastAPI backend on VPS. Shows P&L, positions, opportunities, trade history.

---

## Configuration

All config lives in `config/settings.py` as Pydantic models:

| Config | Key Settings |
|--------|-------------|
| RiskConfig | $3,000 capital, 5% max position, 10% daily loss cap, 10 max positions |
| SignalConfig | 2:1 min R:R, 65% min confidence |
| MarketWeights | Crypto 0.95, Options 0.90, Equity 0.70, Forex 0.45 (adaptive) |
| StrategyConfig | 6 proven strategies with backtest PF and win rates |
| EdgeLearningConfig | 20-trade min, 24hr cycle, 5–40% weight bounds |

---

## What I Would Change (and Why)

### High Priority

**1. The scaler bug pattern is systemic — bare `except` clauses hide real errors**

The MLPredictor had `except:` (bare) on lines 176 and 188 that silently swallow any exception during prediction. The `except Exception as e` on line 212 catches everything else and just logs it. This meant the empty-features bug ran for weeks without anyone noticing the root cause.

*Fix*: Replace bare `except:` with specific exception types. Add structured error context (which symbol, what shape) to log messages. Consider a dead-letter queue for failed predictions so they can be inspected.

**2. TradeExecutor assumes all positions are long**

`_close_position()` hardcodes `side = 'buy'` on line 446. For a credit-focused system that recommends `LONG_PUT` and `STRADDLE`, this means short positions would have their P&L calculated backwards. The Telegram exit notification also hardcodes `side='buy'`.

*Fix*: Store the original trade side in the Position or look it up from the matching active trade. Use it for P&L calculation and notifications.

**3. No persistence of active trades or positions across restarts**

`active_trades`, `positions`, and `pending_orders` are all in-memory lists. If the system restarts (which it does — systemd), all tracking state is lost. The broker sync only helps for live-mode positions, not simulation.

*Fix*: Persist `active_trades` to a JSON file (same pattern as adaptive_weights). On startup, reload and reconcile with broker positions.

**4. Coordinator's `process()` loop runs learning checks every second**

`edge_learner.should_adapt()` is called on every iteration of the main loop (every 1 second). While it's cheap today, it reads config and checks timestamps on every call. As more learning systems are added, this accumulates.

*Fix*: Check adaptation on a timer (e.g. every 5 minutes) rather than every loop iteration. Or cache the `should_adapt()` result with a TTL.

### Medium Priority

**5. The signal pipeline has no backpressure**

Scanners emit signals independently. If 8 scanners each find 5 signals in a cycle, that's 40 signals flooding through TA → ML → Ranker. The coordinator trims `raw_signals` at 100, but there's no prioritisation of which signals get processed first.

*Fix*: Add a priority queue between scanners and the TA stage. High-confidence signals from proven strategies (volume spike, insider buying) should jump the queue. Drop signals older than N minutes.

**6. yfinance as a data source is fragile and rate-limited**

Every scanner and the MLPredictor call `yf.Ticker(symbol).history()` independently. yfinance is unofficial, has no SLA, and Yahoo throttles aggressively. Multiple agents hitting it concurrently will cause intermittent failures.

*Fix*: Add a shared data cache layer that fetches each symbol once per interval and serves all agents from memory. This also eliminates redundant API calls when multiple scanners watch the same symbol.

**7. Knowledge retriever uses TF-IDF, which misses semantic meaning**

TF-IDF with bigrams works for exact keyword matches but can't understand that "don't chase the trade" and "wait for your setup" mean the same thing. The psychology adjustments are therefore brittle.

*Fix*: Replace TF-IDF with sentence embeddings (e.g. `sentence-transformers/all-MiniLM-L6-v2` — runs locally, 80MB). Cosine similarity on dense vectors captures semantic meaning much better.

**8. MLPredictor trains on single symbols in isolation**

`_train_on_history()` trains the model on one symbol's data at a time. The last symbol trained overwrites the model state. This means the "direction" model is really just trained on whatever symbol was retrained last.

*Fix*: Aggregate training data across all symbols into a single training set. Add a `symbol_id` or market-type feature so the model can learn market-specific patterns while sharing general features.

### Lower Priority

**9. No circuit breaker for external API failures**

If IB Gateway goes down, the broker reconnect is not attempted. If yfinance starts returning errors, every scanner fails independently with no coordination.

*Fix*: Add a circuit breaker pattern — after N consecutive failures to an external service, stop calling it for M minutes and log a single alert instead of N error lines.

**10. Opportunity ranker's confluence detection is time-based but there's no event bus**

Insider + technical confluence checks look for matching signals within 7 days by scanning the coordinator's signal lists. This is O(n) on every ranking call and misses signals that were already trimmed.

*Fix*: Add a simple event store (append-only JSON or SQLite) that records all signals with timestamps. Confluence checks become index lookups instead of list scans.

**11. No test suite**

There are no unit tests or integration tests. The edge scorer has a `main()` with manual test cases, but nothing automated. This makes refactoring risky.

*Fix*: Start with the pure-logic modules: edge_scorer, adaptive_weights, edge_component_learner, pattern_learner, opportunity_ranker. These are all testable without mocking external services.

**12. Two git repos for the same system**

The VPS runs from `/root/apex-s44-monitor` (cloned from `bristmatt96-hub/apex-s44-monitor`) while development happens in `credit-catalyst`. This causes confusion during deploys.

*Fix*: Consolidate to one repo. Update the systemd service to point at the canonical directory.

---

## Summary

The system architecture is sound — the agent/message-bus pattern scales well, the signal pipeline has sensible validation stages, and the learning loop now closes the feedback gap. The biggest risks are operational: silent error swallowing, no state persistence across restarts, hardcoded long-only assumptions in a system that recommends puts and straddles, and fragile external data dependencies. Fixing those would make this production-solid.

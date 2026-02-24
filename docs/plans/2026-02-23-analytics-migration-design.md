# Analytics Tools Migration Design

**Date:** 2026-02-23
**Goal:** Migrate 11 analytics tools from OneDrive sandbox to `analytics/` in the production repo.
**Approach:** Copy + fix imports (Approach A). No functional changes.

## 11 Tools to Migrate

### Layer 0 — Foundation Data
| File | Purpose | Dependencies |
|------|---------|-------------|
| `crossover_constituents.py` | 75 Xover names → yfinance equity/balance sheet data | yfinance, pandas, numpy |
| `itraxx_main_constituents.py` | 125 Main names → yfinance equity data | yfinance, pandas, numpy |

### Layer 1 — Core Models (standalone)
| File | Purpose | Dependencies |
|------|---------|-------------|
| `hy_fair_value_model.py` | Spread decomposition, Z-score, macro fair value regression | fredapi, scipy |
| `cross_asset_credit_signals.py` | Equity vol, rates, FX, commodities → credit positioning signals | fredapi, scipy |
| `ecb_lending_conditions.py` | Bank lending survey, MFI, NPL ratios, industrial production | ecbdata, eurostat |

### Layer 1 — Core Models (depend on Layer 0)
| File | Purpose | Local Imports |
|------|---------|--------------|
| `fundamental_credit_analysis.py` | Debt/EBITDA, interest coverage, FCF/Debt from yfinance | `crossover_constituents` |
| `merton_single_name.py` | Structural credit model, distance-to-default per name | `crossover_constituents` |

### Layer 2 — Composite (depend on Layers 0-1)
| File | Purpose | Local Imports |
|------|---------|--------------|
| `distressed_monitor.py` | Liquidity stress scores, cash burn, LME watch lists | `crossover_constituents`, `fundamental_credit_analysis`, `merton_single_name` |
| `equity_credit_signals.py` | 5 equity-based signals per Xover name | `crossover_constituents` |
| `news_sentiment_monitor.py` | Finnhub news + FinBERT NLP sentiment per name | `crossover_constituents` |
| `insider_flow_tracker.py` | PDMR transactions, HY ETF flows, short interest | `crossover_constituents` |

### Layer 3 — Strategy
| File | Purpose | Local Imports |
|------|---------|--------------|
| `tranche_strategy_engine.py` | Dispersion trade construction, delta hedging, P&L attribution | None (receives data) |

## Per-File Migration Recipe

1. Copy from `C:\Users\toget\OneDrive\claude code\<file>` → `C:\Users\toget\apex-s44-monitor\analytics\<file>`
2. Fix local imports: `from crossover_constituents import ...` → `from analytics.crossover_constituents import ...`
3. Wrap heavy external deps in try/except so imports don't crash in test/CI environments
4. Verify: `python -c "from analytics.<module> import *; print('OK')"`

## Migration Batches

| Batch | Files | Commit Message |
|-------|-------|---------------|
| 1 | `crossover_constituents`, `itraxx_main_constituents` | `feat(analytics): add iTraxx constituent data layers (Xover + Main)` |
| 2 | `hy_fair_value_model`, `cross_asset_credit_signals`, `ecb_lending_conditions` | `feat(analytics): add HY fair value, cross-asset signals, ECB lending` |
| 3 | `fundamental_credit_analysis`, `merton_single_name` | `feat(analytics): add fundamental credit analysis and Merton DD model` |
| 4 | `distressed_monitor`, `equity_credit_signals`, `news_sentiment_monitor`, `insider_flow_tracker` | `feat(analytics): add distressed monitor, equity signals, news sentiment, insider flows` |
| 5 | `tranche_strategy_engine` | `feat(analytics): add tranche strategy engine for dispersion trading` |
| Final | Update CAPABILITIES.md + __init__.py | `docs: update capabilities with 11 new analytics modules` |

## Verification

After each batch:
- Import check passes
- Existing tests still pass: `python -m pytest tests/test_social_sentiment.py -v`
- No circular import issues

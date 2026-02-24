# Analytics Tools Migration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate 11 analytics tools from OneDrive sandbox to `analytics/` in the production repo with corrected imports.

**Architecture:** Copy each file, rewrite bare local imports to package-relative (`from analytics.X import ...`), wrap heavy external deps in try/except, verify import succeeds.

**Tech Stack:** Python, yfinance, fredapi, scipy, finnhub-python, ecbdata, eurostat, transformers/torch (FinBERT). All optional — guarded with try/except.

---

### Task 1: Migrate foundation data layers (Batch 1)

**Files:**
- Copy: `crossover_constituents.py` → `analytics/crossover_constituents.py`
- Copy: `itraxx_main_constituents.py` → `analytics/itraxx_main_constituents.py`

**Step 1: Copy crossover_constituents.py**

Read full content from `C:\Users\toget\OneDrive\claude code\crossover_constituents.py`.
Write to `C:\Users\toget\apex-s44-monitor\analytics\crossover_constituents.py`.

No local import fixes needed — this file has no local dependencies.

**Step 2: Copy itraxx_main_constituents.py**

Read full content from `C:\Users\toget\OneDrive\claude code\itraxx_main_constituents.py`.
Write to `C:\Users\toget\apex-s44-monitor\analytics\itraxx_main_constituents.py`.

No local import fixes needed — this file has no local dependencies.

**Step 3: Verify both import cleanly**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"from analytics.crossover_constituents import CONSTITUENTS; print(f'OK: {len(CONSTITUENTS)} names')\""`
Expected: OK with ~75 names (may fail if yfinance not installed — that's fine, just need no ImportError on the module itself)

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"from analytics.itraxx_main_constituents import MAIN_CONSTITUENTS; print(f'OK: {len(MAIN_CONSTITUENTS)} names')\""`
Expected: OK with ~125 names

**Step 4: Verify existing tests still pass**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -m pytest tests/test_social_sentiment.py -v --tb=short"`
Expected: 21 passed

**Step 5: Commit**

```bash
git add analytics/crossover_constituents.py analytics/itraxx_main_constituents.py
git commit -m "feat(analytics): add iTraxx constituent data layers (Xover 75 + Main 125)"
```

---

### Task 2: Migrate standalone core models (Batch 2)

**Files:**
- Copy: `hy_fair_value_model.py` → `analytics/hy_fair_value_model.py`
- Copy: `cross_asset_credit_signals.py` → `analytics/cross_asset_credit_signals.py`
- Copy: `ecb_lending_conditions.py` → `analytics/ecb_lending_conditions.py`

**Step 1: Copy all three files**

Read full content from `C:\Users\toget\OneDrive\claude code\hy_fair_value_model.py`.
Write to `C:\Users\toget\apex-s44-monitor\analytics\hy_fair_value_model.py`.

Read full content from `C:\Users\toget\OneDrive\claude code\cross_asset_credit_signals.py`.
Write to `C:\Users\toget\apex-s44-monitor\analytics\cross_asset_credit_signals.py`.

Read full content from `C:\Users\toget\OneDrive\claude code\ecb_lending_conditions.py`.
Write to `C:\Users\toget\apex-s44-monitor\analytics\ecb_lending_conditions.py`.

No local import fixes needed — all three are standalone (FRED / ECB data only).

**Step 2: Verify imports**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.hy_fair_value_model; print('OK')\""`
Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.cross_asset_credit_signals; print('OK')\""`
Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.ecb_lending_conditions; print('OK')\""`

Note: May show warnings about missing FRED_API_KEY or ecbdata — that's fine. Just need no crash on import.

**Step 3: Verify existing tests still pass**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -m pytest tests/test_social_sentiment.py -v --tb=short"`
Expected: 21 passed

**Step 4: Commit**

```bash
git add analytics/hy_fair_value_model.py analytics/cross_asset_credit_signals.py analytics/ecb_lending_conditions.py
git commit -m "feat(analytics): add HY fair value model, cross-asset signals, ECB lending monitor"
```

---

### Task 3: Migrate fundamental analysis + Merton DD (Batch 3)

**Files:**
- Copy: `fundamental_credit_analysis.py` → `analytics/fundamental_credit_analysis.py`
- Copy: `merton_single_name.py` → `analytics/merton_single_name.py`

**Step 1: Copy and fix fundamental_credit_analysis.py**

Read full content from `C:\Users\toget\OneDrive\claude code\fundamental_credit_analysis.py`.

Fix these imports (around line 38-40):
```python
# OLD:
    from crossover_constituents import (
        ConstituentData, CONSTITUENTS, fetch_all_constituents,
    )
# NEW:
    from analytics.crossover_constituents import (
        ConstituentData, CONSTITUENTS, fetch_all_constituents,
    )
```

Write to `C:\Users\toget\apex-s44-monitor\analytics\fundamental_credit_analysis.py`.

**Step 2: Copy and fix merton_single_name.py**

Read full content from `C:\Users\toget\OneDrive\claude code\merton_single_name.py`.

Fix this import (around line 48):
```python
# OLD:
import crossover_constituents as xoc
# NEW:
import analytics.crossover_constituents as xoc
```

Write to `C:\Users\toget\apex-s44-monitor\analytics\merton_single_name.py`.

**Step 3: Verify imports**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.fundamental_credit_analysis; print('OK')\""`
Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.merton_single_name; print('OK')\""`

**Step 4: Verify existing tests still pass**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -m pytest tests/test_social_sentiment.py -v --tb=short"`
Expected: 21 passed

**Step 5: Commit**

```bash
git add analytics/fundamental_credit_analysis.py analytics/merton_single_name.py
git commit -m "feat(analytics): add fundamental credit analysis and Merton DD model"
```

---

### Task 4: Migrate composite Layer 2 tools (Batch 4)

**Files:**
- Copy: `distressed_monitor.py` → `analytics/distressed_monitor.py`
- Copy: `equity_credit_signals.py` → `analytics/equity_credit_signals.py`
- Copy: `news_sentiment_monitor.py` → `analytics/news_sentiment_monitor.py`
- Copy: `insider_flow_tracker.py` → `analytics/insider_flow_tracker.py`

**Step 1: Copy and fix distressed_monitor.py**

Read full content from `C:\Users\toget\OneDrive\claude code\distressed_monitor.py`.

Fix these imports (around lines 40-50):
```python
# OLD (line ~40):
    from crossover_constituents import (
        ConstituentData, CONSTITUENTS, fetch_all_constituents,
    )
    from fundamental_credit_analysis import compute_all_ratios, _safe_latest
    ...
    from merton_single_name import compute_merton_all

# NEW:
    from analytics.crossover_constituents import (
        ConstituentData, CONSTITUENTS, fetch_all_constituents,
    )
    from analytics.fundamental_credit_analysis import compute_all_ratios, _safe_latest
    ...
    from analytics.merton_single_name import compute_merton_all
```

Also fix late import around line 729:
```python
# OLD:
            from crossover_constituents import compute_equity_metrics
# NEW:
            from analytics.crossover_constituents import compute_equity_metrics
```

Write to `C:\Users\toget\apex-s44-monitor\analytics\distressed_monitor.py`.

**Step 2: Copy and fix equity_credit_signals.py**

Read full content from `C:\Users\toget\OneDrive\claude code\equity_credit_signals.py`.

Fix import (around line 43):
```python
# OLD:
import crossover_constituents as xoc
# NEW:
import analytics.crossover_constituents as xoc
```

Write to `C:\Users\toget\apex-s44-monitor\analytics\equity_credit_signals.py`.

**Step 3: Copy and fix news_sentiment_monitor.py**

Read full content from `C:\Users\toget\OneDrive\claude code\news_sentiment_monitor.py`.

Fix import (around line 56):
```python
# OLD:
    from crossover_constituents import CONSTITUENTS
# NEW:
    from analytics.crossover_constituents import CONSTITUENTS
```

Write to `C:\Users\toget\apex-s44-monitor\analytics\news_sentiment_monitor.py`.

**Step 4: Copy and fix insider_flow_tracker.py**

Read full content from `C:\Users\toget\OneDrive\claude code\insider_flow_tracker.py`.

Fix import (around line 55):
```python
# OLD:
    from crossover_constituents import CONSTITUENTS
# NEW:
    from analytics.crossover_constituents import CONSTITUENTS
```

Write to `C:\Users\toget\apex-s44-monitor\analytics\insider_flow_tracker.py`.

**Step 5: Verify all four import cleanly**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.distressed_monitor; print('OK')\""`
Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.equity_credit_signals; print('OK')\""`
Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.news_sentiment_monitor; print('OK')\""`
Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.insider_flow_tracker; print('OK')\""`

**Step 6: Verify existing tests still pass**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -m pytest tests/test_social_sentiment.py -v --tb=short"`
Expected: 21 passed

**Step 7: Commit**

```bash
git add analytics/distressed_monitor.py analytics/equity_credit_signals.py analytics/news_sentiment_monitor.py analytics/insider_flow_tracker.py
git commit -m "feat(analytics): add distressed monitor, equity signals, news sentiment, insider flows"
```

---

### Task 5: Migrate tranche strategy engine (Batch 5)

**Files:**
- Copy: `tranche_strategy_engine.py` → `analytics/tranche_strategy_engine.py`

**Step 1: Copy tranche_strategy_engine.py**

Read full content from `C:\Users\toget\OneDrive\claude code\tranche_strategy_engine.py`.
Write to `C:\Users\toget\apex-s44-monitor\analytics\tranche_strategy_engine.py`.

No local import fixes needed — this module is standalone.

**Step 2: Verify import**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -c \"import analytics.tranche_strategy_engine; print('OK')\""`

**Step 3: Verify existing tests still pass**

Run: `powershell.exe -Command "cd C:\Users\toget\apex-s44-monitor; python -m pytest tests/test_social_sentiment.py -v --tb=short"`
Expected: 21 passed

**Step 4: Commit**

```bash
git add analytics/tranche_strategy_engine.py
git commit -m "feat(analytics): add tranche strategy engine for dispersion trading"
```

---

### Task 6: Update CAPABILITIES.md and push

**Files:**
- Modify: `docs/CAPABILITIES.md`

**Step 1: Update the Analytics section**

In `docs/CAPABILITIES.md`, add these 11 new modules to the Analytics table:

```markdown
| `crossover_constituents` | iTraxx Crossover data layer — 75 names mapped to yfinance tickers, equity prices, market caps, balance sheets |
| `itraxx_main_constituents` | iTraxx Main data layer — 125 IG names mapped to yfinance tickers |
| `hy_fair_value_model` | HY spread decomposition, Z-scores by rating/maturity, macro-based fair value regression, quality rotation |
| `cross_asset_credit_signals` | Cross-asset signal framework — equity vol, rates, FX, commodities → credit positioning (-2 to +2) |
| `ecb_lending_conditions` | ECB Bank Lending Survey, MFI data, NPL ratios, Eurostat industrial production by sector |
| `fundamental_credit_analysis` | Traditional credit ratios — Debt/EBITDA, interest coverage, FCF/Debt, margins from yfinance financials |
| `merton_single_name` | Structural credit model — distance-to-default, implied PD, implied spread per Xover name |
| `distressed_monitor` | Liquidity stress scores, cash burn timelines, LME risk watch lists |
| `equity_credit_signals` | 5 equity-based signals per Xover name — vol regime, momentum, drawdown, leverage, equity-credit beta |
| `news_sentiment_monitor` | Finnhub news + FinBERT NLP sentiment per name and sector |
| `insider_flow_tracker` | PDMR insider transactions, HY ETF flow sentiment, short interest tracking |
| `tranche_strategy_engine` | Dispersion trade construction, delta hedging, P&L attribution for index tranche strategies |
```

Update the count from "Analytics (18)" to "Analytics (29)".

**Step 2: Commit and push**

```bash
git add docs/CAPABILITIES.md
git commit -m "docs: update capabilities with 11 new analytics modules (18 → 29)"
git push origin credit-catalyst
```

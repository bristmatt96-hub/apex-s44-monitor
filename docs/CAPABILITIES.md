# Macro Credit Monitor v2.0 — Capabilities & Daily Operations

AI-augmented European credit relative value platform. Monitors 200 iTraxx S44 constituents (75 Crossover + 125 Main) across regulatory filings, news, social media, ratings, earnings, and cross-asset signals. Enables long/short CDS selection, bond-CDS basis trades, and delta-hedged tranche positioning (primarily 0-3%). Decentralised AI (Bittensor) provides speed edge — first to receive relevant information so positions can be adjusted quickly. Heavy on analysis, risk, and process — not marketing.

**Stack**: Python 3.10.9 | FastAPI | React (Babel CDN) | Dark theme
**Run**: `python -m app.api.main` (port 8000)
**VPS**: 143.198.56.117 (DigitalOcean)

---

## Table of Contents

1. [Daily Workflow](#daily-workflow)
2. [Web Dashboards](#web-dashboards)
3. [API Endpoints](#api-endpoints)
4. [Monitors](#monitors-24)
5. [Analytics Engine](#analytics-engine-33-modules)
6. [AI Agents & Scanners](#ai-agents--scanners)
7. [Scripts & CLI Tools](#scripts--cli-tools)
8. [Pitch & Reporting](#pitch--reporting)
9. [Data & Knowledge Systems](#data--knowledge-systems)
10. [Infrastructure](#infrastructure)

---

## Daily Workflow

### Pre-Market (06:00-07:30 UK)

| Task | Tool | Command |
|------|------|---------|
| Morning briefing | `morning_brief` | Auto-sends 07:00 UK via Telegram — overnight filings, rating actions, portfolio P&L |
| Rating action scan | `rating_actions` | S&P/Moody's/Fitch RSS — upgrades, downgrades, outlook changes, CreditWatch |
| European filing scan | `european_monitor` | Companies House, Investegate (RNS), EQS News (DGAP) filings overnight |
| News scan | `news_monitor` | Google News RSS per name; severity 1-5 classification |
| Social sentiment | `social_sentiment` | Bittensor SN13 + Claude triage — overnight Twitter/X chatter |
| Credit cycle check | `credit_cycle` | Regime update (EXPANSION / LATE_CYCLE / DISTRESS / RECOVERY) |

### Market Open (07:30-09:00 UK)

| Task | Tool | Command |
|------|------|---------|
| Universe screen | `run_universe` | `python scripts/run_universe.py` — all 75 Xover names scored and ranked |
| Equity-CDS lag scan | `equity_cds_lag` | Detects 3%+ equity drops where CDS hasn't repriced — 30-60min tradeable lag |
| Equity movers | `equity_movers` | 42 public Xover tickers checked for significant moves |
| Price alerts | `price_alert_monitor` | `python scripts/price_alert_monitor.py` — 2-min cycle, +/-1% Telegram alerts |
| Dashboard refresh | API server | `python -m app.api.main` — serves live universe, portfolio, risk to web UI |

### Intraday (09:00-17:30 UK)

| Task | Tool | Command |
|------|------|---------|
| Live market pulse | `market_pulse` | Real-time RSS scoring for bond-moving headlines |
| Gap detection | `credit_equity_bridge` | `python analytics/credit_equity_bridge.py --top 10` — CDS vs equity gaps |
| Trade structuring | `trade_structurer` | Options recommendations (puts, spreads, straddles) for flagged names |
| Relative value | `relative_value` | Rich/cheap screen with sector z-scores and pair trades |
| Risk monitoring | `portfolio_risk_manager` | Aggregate CS01, DV01, JTD, concentration checks vs limits |
| ISDA event watch | `isda_news_checker` | Credit event flagging with DC precedent matching |
| Earnings calls | `live_transcriber` / `earnings_transcript` | Real-time transcription with distress keyword detection |

### End of Day (17:30-18:30 UK)

| Task | Tool | Command |
|------|------|---------|
| Portfolio review | `run_portfolio` | `python scripts/run_portfolio.py` — positions, P&L, Greeks, stops |
| Scenario stress | `scenario_analysis` | 8 macro scenarios — ECB cuts/hikes, recession, China, sovereign, LME wave |
| Tranche pricing | `tranche_pricer` | Mark tranche positions, check base corr moves, CS01 changes |
| Dispersion update | `dispersion` | Universe CV, sector dispersion regime (low/normal/high) |
| Maturity wall check | `maturity_wall` | Upcoming refis flagged, spread adequacy scored |

### Weekly / Ad-Hoc

| Task | Tool | Command |
|------|------|---------|
| ECB lending survey | `ecb_lending_conditions` | Bank Lending Survey, MFI balance sheets, NPL ratios |
| Insider flow report | `insider_flow_tracker` | PDMR transactions, HY ETF flows (IHYG.L/HYG/JNK), short interest |
| Fundamental refresh | `fundamental_credit_analysis` | Debt/EBITDA, coverage, FCF/Debt, margins from yfinance |
| Merton model update | `merton_single_name` | Distance-to-default, implied PD, implied spread per name |
| HY fair value | `hy_fair_value_model` | Macro regression (FRED), Z-scores by rating/maturity |
| Swaption pricing | `swaption_pricer` | Black-76 + SABR vol surface for iTraxx Main/Xover index swaptions |
| Tranche calibration | `calibrate_xover_s44` / `calibrate_main_s44` | Base correlation fit to dealer quotes |
| Roll analysis | `roll_analysis_s42_vs_s44` | Series comparison: base corr, EL%, fair spread, CS01, roll P&L |
| Twitter alpha | `twitter_alpha_scanner` | xAI Grok scanning for credit-relevant intelligence |
| Substack digest | `substack_email_parser` | Research from Le Shrub + Capital Flows into KB |
| Covenant review | `covenant_risk` | Manual + Claude API assessment per watchlist name |
| Pitch materials | `pitch/` suite | Idea sheets, case studies, trade journal, risk reports |

---

## Web Dashboards

5 React SPAs served via FastAPI. Dark theme (#0a0e17), DM Sans + JetBrains Mono fonts.

| Page | URL | What it does |
|------|-----|-------------|
| **Dashboard** | `/` | Universe screen (75 names), portfolio (10 positions), risk metrics, filing alerts, heatmap cells for gap/PnL/mispricing |
| **Cockpit** | `/cockpit` | Command center — market regime, scenario builder, signal feed, portfolio & risk tabs |
| **Risk Calculator** | `/risk-calculator` | Interactive portfolio risk engine — exposure summary, DV01, CS01, JTD, stress tests |
| **Tranche Lab** | `/tranches` | iTraxx tranche pricing — equity/mezz/senior cards, scenario tables, base corr calibration |
| **Swaption Lab** | `/swaptions` | CDS swaption pricer — Black-76/SABR vol surface, payoff diagrams, Greeks heatmap |

All pages include cross-navigation (Dashboard / Cockpit / Tranches / Swaptions / Risk Calc).

---

## API Endpoints

13 FastAPI routes. JSON responses, CORS-enabled, port 8000.

### Page Routes

| Route | Method | Serves |
|-------|--------|--------|
| `/` | GET | Dashboard HTML |
| `/cockpit` | GET | Cockpit HTML |
| `/risk-calculator` | GET | Risk Calculator HTML |
| `/tranches` | GET | Tranche Lab HTML |
| `/swaptions` | GET | Swaption Lab HTML |

### Data API

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/api/universe` | GET | 75 Xover names — conviction, spreads, RV scores, thesis |
| `/api/portfolio` | GET | 10 current positions — notional, P&L, hedges, stress scenarios |
| `/api/risk` | GET | Risk snapshot — DV01, CS01, JTD, concentration HHI, risk limit traffic lights |
| `/api/filings` | GET | European regulatory filing alerts (7-day window from SQLite) |
| `/api/relative-value` | GET | Rich/cheap screen — sector z-scores, composite scores, pair trade ideas |
| `/api/maturity-wall` | GET | Top refinancing risk names ranked by spread adequacy |
| `/api/dispersion` | GET | Spread dispersion regime — universe CV, sector breakdowns |
| `/api/scenarios` | GET | 8 macro stress scenarios with P&L repricing |
| `/api/tranche-scenarios` | GET | Calibrated tranche tables (Xover + Main) from dealer quotes |
| `/api/equity-bridge` | GET | CDS-equity gap detection for all scored public names |
| `/api/equity-bridge/{name}` | GET | Single-name equity bridge detail |
| `/api/trade-structure/{name}` | GET | Options structure recommendation (catalyst + IV + gap driven) |
| `/api/spreads` | GET | Spread data with index/spread/sector filters |

---

## Monitors (24)

Real-time scanning and alerting. Most write to SQLite (`filings.db`) + send Telegram alerts.

### Market & Price

| Monitor | What it does | Frequency |
|---------|-------------|-----------|
| `market_pulse` | Real-time RSS scoring for bond-moving headlines | 5-15s cycle |
| `equity_movers` | Stock price alerts for 42 public Xover tickers | 5 min |
| `equity_cds_lag` | Detects 3%+ equity drops where CDS hasn't repriced (tradeable 30-60min lag) | 5 min |
| `price_alert_monitor` | +/-1% equity moves → Telegram alerts | 2 min |

### News & Filings

| Monitor | What it does | Frequency |
|---------|-------------|-----------|
| `european_monitor` | Companies House, Investegate (RNS), EQS News (DGAP) regulatory filings | Daily |
| `news_monitor` | Google News RSS per Xover name; severity 1-5 via Claude | ~5 min |
| `rating_actions` | S&P, Moody's, Fitch RSS — upgrades, downgrades, outlook, CreditWatch | Daily EOD |
| `rss_monitor` | General RSS feed aggregator across credit-relevant sources | Hourly |
| `credit_events_monitor` | Earnings, covenants, maturities — credit catalyst tracking | Event-driven |

### Social & Sentiment

| Monitor | What it does | Frequency |
|---------|-------------|-----------|
| `social_sentiment` | Bittensor SN13 + Claude triage (keyword blocklist → Haiku → Sonnet); 14 consumer entities | Hourly |
| `credit_twitter` | Curated credit accounts on X/Twitter → Telegram for high-priority tweets | Real-time |
| `news_sentiment_monitor` | Finnhub news + FinBERT NLP sentiment per name and sector | Periodic |

### Earnings & Transcripts

| Monitor | What it does | Frequency |
|---------|-------------|-----------|
| `earnings_monitor` | SEC filings tracker (6-K, 8-K, 10-Q, 10-K, 20-F) for all names | Daily |
| `earnings_sentiment` | Transcript analysis — distress signals, management tone, key metrics | Post-call |
| `earnings_transcript` | Full earnings call processing through Claude with credit lens; QoQ comparison | Post-call |
| `live_transcriber` | Real-time streaming transcription with distress keyword detection | During call |
| `call_transcriber` | Audio upload → Whisper API or local Whisper transcription | On-demand |

### ISDA & Legal

| Monitor | What it does | Frequency |
|---------|-------------|-----------|
| `isda_news_checker` | Credit event flagging; ISDA section mapping; grace period tracking | Hourly |
| `isda_analyzer` | Headline interpretation through ISDA Credit Derivatives Definitions lens | On-demand |
| `isda_agent` | LLM-powered ISDA analysis with DC precedent knowledge base | On-demand |

### Operations & Briefing

| Monitor | What it does | Frequency |
|---------|-------------|-----------|
| `morning_brief` | Daily 07:00 UK Telegram — overnight filings, portfolio, key moves | Daily 07:00 |
| `trade_workbench` | Catalyst calendar, liquidity runway, trade memo templates | On-demand |
| `lme_risk_calculator` | Liability Management Exercise risk scoring per name | On-demand |
| `debtwire_parser` | Debtwire Excel exports → JSON snapshots + database records | On-demand |

---

## Analytics Engine (33 Modules)

All modules use dataclasses, plain functions, argparse CLI, loguru logging, type hints.

### Core Signal Pipeline

| Module | What it does | CLI |
|--------|-------------|-----|
| `signal_scorer` | Two independent 0-100 scores: credit signal + equity repricing; gap score is one cross-asset signal among many | `--test` |
| `trade_structurer` | Options structure recommender (puts, spreads, straddles) from catalyst type + IV + gap + CDS level | `--test` |
| `credit_equity_bridge` | Orchestrator — loads credit + equity data, scores via signal_scorer, recommends trades | `--top N`, `--name`, `--no-equity` |

### Pricing & Derivatives

| Module | What it does | CLI |
|--------|-------------|-----|
| `cds_pricer` | ISDA Standard CDS Model — spread/upfront conversion, DV01, CS01, JTD, implied PD | `--spread`, `--upfront`, `--verify` |
| `swaption_pricer` | Black-76 + SABR swaption pricing, vol surface builder, 7-panel dashboard | `--index`, `--expiry`, `--json`, `--chart-only` |
| `tranche_pricer` | Gaussian copula CDO pricer — 50-pt Gauss-Hermite quadrature, CDS curve bootstrapping, full Greeks (CS01/CS02/Rho01/Theta/Recovery01/JTD), base corr calibration | `--index-spread`, `--strategy`, `--calibrate`, `--full-report` |
| `tranche_scenario_table` | P&L scenario tables for Xover + Main tranches across parallel spread bumps | Yes |
| `tranche_strategy_engine` | Dispersion trades, delta hedging, P&L attribution (carry + spread + correlation + theta + default) | Yes |

### Risk

| Module | What it does | CLI |
|--------|-------------|-----|
| `risk_metrics` | Single-name (DV01, CS01, JTD, VaR 95/99%, CVaR) + portfolio (aggregate, concentration HHI, top 5) | Yes |
| `portfolio_risk_manager` | Full portfolio Greeks, factor decomposition, correlation analysis, limit monitoring | Yes |
| `scenario_analysis` | 8 macro stress scenarios with exact P&L repricing (ECB, recession, China, sovereign, LME, fallen angel, squeeze) | `--strategy` per scenario |

### Relative Value & Selection

| Module | What it does | CLI |
|--------|-------------|-----|
| `relative_value` | Rich/cheap screener — sector z-scores, rating z-scores, momentum, composite score, pair trades | `--top`, `--sector`, `--pairs`, `--excel` |
| `hy_fair_value_model` | Spread decomposition, Z-scores by rating/maturity, macro-based fair value regression (FRED), quality rotation | Yes |
| `equity_credit_signals` | 5 equity signals per name — vol regime, momentum, drawdown, leverage/MCap erosion, equity-credit beta | Yes |
| `cross_asset_credit_signals` | Multi-asset framework — equity vol, rates, FX, commodities → positioning scores (-2 to +2) | Yes |
| `dispersion` | Spread dispersion regime analysis — universe CV, sector stats, pair trade sectors | Yes |

### Fundamental & Structural

| Module | What it does | CLI |
|--------|-------------|-----|
| `fundamental_credit_analysis` | Traditional credit ratios — Debt/EBITDA, interest coverage, FCF/Debt, margins (yfinance) | Yes |
| `merton_single_name` | Structural credit model — distance-to-default, implied PD, implied spread (Black-Scholes-Merton) | Yes |
| `covenant_risk` | Manual profiles + Claude API assessment; confidence and data quality ratings | Yes |
| `distressed_monitor` | Liquidity stress scores, cash burn timelines, LME risk watchlists per Xover name | Yes |
| `fallen_angels` | Rating migration signals — rising stars, fallen angels, distressed exits, stable core | Yes |
| `situation_classifier` | Playbook A (aggressive sponsor) vs Playbook B (maturity wall) classification | Yes |
| `maturity_wall` | Refinancing risk ranking; cross-references maturity calendar with CDS spreads | Yes |
| `fund_business_plan` | Sponsor/PE analysis — LBO exit scenarios, dividend recap risk | Yes |

### Macro & Sentiment

| Module | What it does | CLI |
|--------|-------------|-----|
| `credit_cycle` | Regime classifier (EXPANSION / LATE_CYCLE / DISTRESS / RECOVERY) using multi-factor scoring | Yes |
| `ecb_lending_conditions` | ECB Bank Lending Survey, MFI balance sheets, NPL ratios, Eurostat industrial production | Yes |
| `news_sentiment_monitor` | Finnhub news + FinBERT NLP sentiment per name and sector | Yes |
| `insider_flow_tracker` | PDMR insider transactions, HY ETF flow sentiment (IHYG.L/HYG/JNK), short interest | Yes |

### Data Layers

| Module | What it does | CLI |
|--------|-------------|-----|
| `crossover_constituents` | iTraxx Crossover data — 74 names mapped to yfinance tickers, equity, MCap, balance sheets | Yes |
| `itraxx_main_constituents` | iTraxx Main data — 133 IG names mapped to yfinance tickers, equity + fundamentals | Yes |
| `portfolio_risk_pitch` | Real risk metrics for pitch materials — net DV01, gross CS01, JTD, stress P&L | Yes |
| `backtester` | Walk-forward testing engine — Sharpe, Sortino, drawdown, win rate | Yes |
| `credit_backtest_engine` | Credit spread-specific backtesting — P&L attribution, curve scenarios | Yes |

---

## AI Agents & Scanners

### Agents (`agents/`)

| Agent | What it does |
|-------|-------------|
| `analyst` | Per-name credit assessment — queries KB, loads real CDS data, calls Claude; returns direction, conviction 1-5, thesis, catalyst, fair spread |
| `strategist` | Portfolio construction — takes all assessments, builds optimal $500M portfolio respecting risk limits (5% single-name, 25% sector, 5% drawdown review, 7.5% hard stop) |
| `risk_manager` | Hard guardrails — max position 5%, max portfolio 30%, max loss/trade 50%, max daily 5%, max weekly 10%, max sector 3 positions |
| `briefing` | Morning brief generator — daily Telegram + PDF from latest universe screen + filings |

### Scanners (`agents/scanners/`)

| Scanner | What it does |
|---------|-------------|
| `credit_options_scanner` | Maps credit deterioration to options positions; Playbook A = straddles, B = puts |
| `edgar_insider_scanner` | SEC EDGAR Form 4 insider buying/selling; 10 req/sec rate limit |
| `substack_scanner` | Research digest from Le Shrub (options flow) + Capital Flows (institutional positioning) |

---

## Scripts & CLI Tools

| Script | What it does |
|--------|-------------|
| `run_universe` | Batch screener across all 75 Xover names; outputs sorted Excel |
| `run_portfolio` | Portfolio dashboard — positions, journal, stops, earnings, Greeks, performance. `--watch` mode for live refresh |
| `run_brain` | Market Brain — scans for retail crowding, vol mispricing, timezone gaps, liquidity, shocks |
| `calibrate_xover_s44` | Base correlation calibration for Xover S44 tranches from dealer quotes |
| `calibrate_xover_s42` | Same for prior series |
| `calibrate_main_s44` | Base correlation calibration for Main S44 tranches |
| `calibrate_main_s42` | Same for prior series |
| `roll_analysis_s42_vs_s44` | Side-by-side S42 vs S44: base corr, EL%, fair spread, CS01, roll P&L |
| `import_spreads` | Imports CDS spread data from iTraxx Excel constituents file |
| `price_alert_monitor` | 42 public Xover tickers every 2 min; +/-1% Telegram alerts |
| `twitter_alpha_scanner` | Twitter alpha via xAI Grok; credit-relevant post scanning |
| `batch_transcribe` | Batch video/audio transcription via Whisper; large file chunking |
| `substack_email_parser` | Fetches Substack emails via IMAP; extracts content for KB |
| `substack_content_processor` | Processes Substack articles for knowledge base ingestion |
| `benchmark_sn13_vs_sn22` | Benchmarks Bittensor SN13 vs SN22 for social data quality |
| `refresh_dashboard` | Refreshes Excel dashboard from live API data. `--watch` for auto-refresh |

---

## Pitch & Reporting

| Module | What it does |
|--------|-------------|
| `pitch_deck` | Full pitch deck generation — strategy overview, portfolio, risk, performance |
| `idea_sheet` | Single-name trade idea sheets with thesis, catalysts, risk/reward |
| `case_study` | Deep-dive case studies (e.g. Altice France, Ardagh) |
| `trade_journal` | Trade log with entry/exit, thesis, P&L, lessons |
| `risk_report` | Portfolio risk report — Greeks, stress, limits, concentration |
| `backtest_report` | Strategy backtest results — Sharpe, drawdown, attribution |
| `tearsheet_generator` | One-page strategy tearsheets |

---

## Data & Knowledge Systems

### Reference Data (`data/`)

| File | Contents |
|------|----------|
| `itraxx_s44_master.json` | Master reference — 75 Xover + 125 Main names (entity, ticker, sector, rating, weights) |
| `itraxx_equity_map.json` | Name-to-ticker mapping, public/private flags, options availability |
| `entity_profiles/` | 70+ JSON files per constituent (fundamentals, leverage, covenants, filings) |
| `earnings_signals/` | Company-specific earnings data (INEOS Q4 2025, Q1 2026, etc.) |
| `covenant_profiles.json` | Maintenance covenant thresholds by issuer |
| `case_studies/` | Distressed case studies (Altice France, Ardagh) for pattern learning |
| `benchmarks/` | Series comparisons (SN13 vs SN22 INEOS, Nokia, TUI) |
| `maturity_wall.json` | Refinancing calendar and bucket analysis |
| `sponsors.json` | PE sponsor profiles, exit history, aggression scoring |
| `isda_precedents.json` | ISDA DC rulings and case law |
| `patterns.json` | Historical distress patterns for ML training |
| `filings.db` | SQLite — news, filings, credit events (rolling 7-day window) |

### Knowledge Base (`knowledge_base/`)

70+ ingested PDFs covering:
- Credit analysis fundamentals and methodologies
- iTraxx mechanics, index rules, and series history
- Distressed debt case studies and restructuring playbooks
- ISDA Credit Derivatives Definitions and DC precedents
- CDS pricing conventions and market practices
- Options strategy reference material

### Data Pipeline

| Component | What it does |
|-----------|-------------|
| `market_data_loader` | Reads real CDS spreads from iTraxx S44 Excel constituents file |
| `market_data_providers` | Unified interface — yfinance (primary), Finnhub, Twelve Data; auto-failover |
| `entity_profile_manager` | Continuous learning — accumulates per-entity JSON profiles from all monitors |
| `knowledge/retriever` | KB search via TF-IDF + cosine similarity |
| `knowledge/ingest` | Processes PDFs, audio (Whisper), Google Cloud Speech-to-Text into KB |

---

## Infrastructure

### Docker

- **Dockerfile**: Python 3.11-slim, FFmpeg, requirements
- **docker-compose.yml**:
  - `market-watcher`: 24/7 service (5s interval)
  - `dashboard`: Streamlit UI (port 8501)
  - `redis`: Inter-service messaging

### Key Dependencies

| Category | Libraries |
|----------|-----------|
| Core | FastAPI, pandas, numpy, requests, SQLAlchemy |
| Data | yfinance, feedparser, tweepy, macrocosmos (Bittensor SN13) |
| AI | anthropic (Claude), openai, openai-whisper |
| Quant | scipy (Gauss-Hermite, optimization), scikit-learn, xgboost, lightgbm |
| Execution | ib_insync (Interactive Brokers), ccxt |
| Viz | matplotlib, Chart.js (frontend), D3.js (tranches) |

### Risk Configuration

| Parameter | Limit |
|-----------|-------|
| Max single-name position | 5% of NAV |
| Max sector concentration | 25% of NAV |
| Max sector names | 3 positions |
| Drawdown review trigger | -5% |
| Hard stop | -7.5% |
| Max daily loss | -5% |
| Max weekly loss | -10% |

---

## System Summary

| Category | Count |
|----------|-------|
| Analytics modules | 33 |
| Monitors | 24 |
| API endpoints | 13 |
| Web dashboards | 5 |
| AI agents | 4 |
| Scanners | 3 |
| Scripts & CLI tools | 16 |
| Pitch/reporting modules | 7 |
| Knowledge base PDFs | 70+ |
| iTraxx names covered | 200 (75 Xover + 125 Main) |

---

*Macro Credit Monitor v2.0 — February 2026*

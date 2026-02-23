# APEX S44 Monitor — Capabilities

AI-powered European credit relative value platform. Monitors 75 iTraxx Crossover S44 + 125 Main S44 names across regulatory filings, news, social media, ratings, and earnings. Scores credit signals against equity repricing to find tradeable gaps. Targets $500M NAV, 10-position portfolio.

---

## Web Dashboard

| Page | URL | What it does |
|------|-----|-------------|
| Dashboard | `/` | Universe screen, portfolio, risk metrics, filing alerts |
| Cockpit | `/cockpit` | Command center with real-time React components |
| Risk Calculator | `/risk-calculator` | Interactive portfolio risk calculator |
| Tranches | `/tranches` | Tranche scenario analysis with calibrated Greeks |

### API Endpoints

| Endpoint | What it returns |
|----------|----------------|
| `/api/universe` | 75-name screen with conviction, spreads, thesis |
| `/api/portfolio` | Current 10 positions, hedges, risk summary, stress P&L |
| `/api/risk` | DV01, CS01, JTD, sector concentration, risk limit traffic lights |
| `/api/filings` | Latest European regulatory filing alerts |
| `/api/relative-value` | Rich/cheap screen, composite scores, pair trade ideas |
| `/api/maturity-wall` | Top refinancing risk names ranked by risk score |
| `/api/dispersion` | Spread dispersion regime (CV by sector and rating) |
| `/api/scenarios` | 8 macro stress scenarios with exact P&L repricing |
| `/api/tranche-scenarios` | Real market tranche tables from calibrated CSVs (Xover + Main) |
| `/api/equity-bridge` | CDS-equity gap detection for all scored public names |
| `/api/equity-bridge/{name}` | Single-name equity bridge detail |
| `/api/trade-structure/{name}` | Options structure recommendation (puts, spreads, straddles) |

---

## Monitors (21)

Real-time scanning and alerting. Most write to SQLite + send Telegram alerts.

| Monitor | What it does |
|---------|-------------|
| `european_monitor` | Scrapes Companies House, Investegate (RNS), EQS News (DGAP) for regulatory filings; classifies credit impact via Claude |
| `news_monitor` | Google News RSS per Xover name; classifies severity 1-5; triggers re-assessment on sev >= 3 |
| `earnings_monitor` | Tracks SEC filings (6-K, 8-K, 10-Q, 10-K, 20-F) for all names |
| `credit_twitter` | Monitors X/Twitter from curated credit accounts; sends Telegram for high-priority tweets |
| `social_sentiment` | Bittensor SN13 API for X posts; Claude classification (sentiment, severity, novelty); noise pre-filter for 14 consumer-facing entities |
| `market_pulse` | Real-time bond-moving news from RSS; scores headlines for price impact |
| `rating_actions` | Scrapes S&P, Moody's, Fitch RSS for upgrades, downgrades, outlook changes, watch actions |
| `equity_cds_lag` | Detects 3%+ equity drops where CDS hasn't repriced yet (30-60min lag = tradeable signal) |
| `credit_events_monitor` | Tracks earnings, covenants, maturities for alpha catalysts |
| `morning_brief` | Daily 7am UK Telegram briefing from latest universe screen + filings |
| `trade_workbench` | Catalyst calendar, liquidity runway dashboard, trade memo template |
| `lme_risk_calculator` | Scores credits for Liability Management Exercise risk |
| `earnings_sentiment` | Analyzes transcripts for distress signals, management tone, key metrics |
| `earnings_transcript` | Processes earnings calls through Claude with credit-specific lens; QoQ comparison |
| `live_transcriber` | Real-time streaming transcription of earnings calls with distress keyword detection |
| `call_transcriber` | Upload audio recordings; transcribe via Whisper API or local Whisper |
| `debtwire_parser` | Converts Debtwire Excel exports to JSON snapshots and database records |
| `isda_analyzer` | Interprets headlines through ISDA Credit Derivatives Definitions lens |
| `isda_news_checker` | Flags potential credit events; pulls ISDA sections; generates checklists; tracks grace periods |
| `isda_agent` | LLM-powered ISDA credit event analysis with DC precedent knowledge |
| `trading_tools` | Unified dashboard: transcriber, sentiment, SEC, LME risk, stress, maturity, positions |

---

## Analytics (18)

Quantitative models and scoring engines.

| Module | What it does |
|--------|-------------|
| `cds_pricer` | ISDA Standard CDS Model — spread/upfront conversion, DV01, CS01, JTD, implied PD |
| `tranche_pricer` | Gaussian copula CDO pricer — Gauss-Hermite quadrature, CDS curve bootstrapping, full Greeks (CS01/CS02/Rho01/Theta/Recovery01/JTD), base correlation calibration |
| `relative_value` | Rich/cheap screener — sector z-scores, rating z-scores, momentum, composite score |
| `maturity_wall` | Ranks entities by refinancing risk; cross-references with CDS spreads |
| `scenario_analysis` | 8 macro stress scenarios — ECB cuts/hikes, European recession, China crisis, sovereign stress, LME wave, fallen angel cascade, risk-on squeeze |
| `dispersion` | Spread dispersion regime analysis — universe CV, sector stats, pair trade sectors |
| `credit_equity_bridge` | Orchestrates CDS-equity gap detection; loads credit + equity data; scores via signal_scorer; recommends trades |
| `signal_scorer` | Two independent 0-100 scores: credit signal score + equity repricing score; gap = alpha |
| `covenant_risk` | Manual profiles + Claude API assessment; confidence/data quality ratings |
| `fallen_angels` | Rating migration signals — rising stars, fallen angels, distressed exits, stable core |
| `trade_structurer` | Options structure recommender based on catalyst type, IV percentile, gap strength, CDS level |
| `risk_metrics` | Single-name (DV01, CS01, JTD, VaR 95/99%, CVaR) + portfolio (aggregate, concentration HHI, top 5 contributors) |
| `credit_cycle` | Regime classifier (EXPANSION, LATE_CYCLE, DISTRESS, RECOVERY) using multi-factor scoring |
| `situation_classifier` | Playbook A (aggressive sponsor) vs Playbook B (maturity wall) classification |
| `portfolio_risk_pitch` | Real risk metrics for pitch deck — net DV01, gross CS01, JTD, stress P&L |
| `tranche_scenario_table` | Generates P&L scenario tables for Xover + Main tranches across parallel bumps |
| `backtester` | Testing engine for trading strategies against historical data |

---

## AI Agents & Scanners

| Agent | What it does |
|-------|-------------|
| `analyst` | Per-name credit assessment — queries KB, loads real CDS data, calls Claude; returns direction, conviction 1-5, thesis, catalyst, fair spread |
| `strategist` | Portfolio construction — takes all assessments, builds optimal $500M portfolio respecting risk limits (5% single-name, 25% sector, 5% drawdown review, 7.5% hard stop) |
| `risk_manager` | Hard guardrails — max position 5%, max portfolio 30%, max loss/trade 50%, max daily 5%, max weekly 10%, max sector 3 positions |
| `briefing` | Morning brief generator — daily Telegram + PDF from latest universe screen + filings |

| Scanner | What it does |
|---------|-------------|
| `credit_options_scanner` | Maps credit deterioration to options positions; Playbook A = straddles, B = puts |
| `edgar_insider_scanner` | SEC EDGAR Form 4 insider buying/selling; 10 req/sec rate limit |
| `substack_scanner` | Research digest from Le Shrub (options flow) + Capital Flows (institutional positioning) |

---

## Scripts & CLI

| Script | What it does |
|--------|-------------|
| `run_universe` | Batch screener across all 75 Xover names; outputs sorted Excel |
| `run_portfolio` | Portfolio dashboard — positions, journal, stops, earnings, Greeks, performance |
| `run_brain` | Market Brain — scans for retail crowding, vol mispricing, timezone gaps, liquidity, shocks |
| `calibrate_xover_s44` | Base correlation calibration for Xover S44 tranches (real dealer quotes) |
| `calibrate_xover_s42` | Same for prior series |
| `calibrate_main_s44` | Base correlation calibration for Main S44 tranches |
| `calibrate_main_s42` | Same for prior series |
| `roll_analysis_s42_vs_s44` | Side-by-side S42 vs S44: base corr, EL%, fair spread, CS01, roll P&L |
| `price_alert_monitor` | Checks 42 public Xover tickers every 2 min for +/- 1% moves; Telegram alerts |
| `twitter_alpha_scanner` | Twitter alpha via xAI Grok; credit-relevant post scanning |
| `batch_transcribe` | Batch video/audio transcription via Whisper; handles large files by chunking |
| `substack_email_parser` | Fetches Substack emails via IMAP; extracts content for KB |

---

## Data & Knowledge Systems

| Component | What it does |
|-----------|-------------|
| `market_data_loader` | Reads real CDS spreads from iTraxx S44 Excel constituents file |
| `market_data_providers` | Unified interface — yfinance (primary), Finnhub, Twelve Data; auto-failover |
| `entity_profile_manager` | Continuous learning — accumulates per-entity JSON profiles from all monitors |
| `knowledge/retriever` | KB search via TF-IDF + cosine similarity |
| `knowledge/ingest` | Processes PDFs, audio (Whisper), Google Cloud Speech-to-Text into KB |
| `covenant_profiles.json` | Manual covenant data (leverage thresholds, lien packages, change-of-control) |
| `maturity_wall.json` | Refinancing calendar with maturity dates and coupon levels |
| `sponsors.json` | PE firm / family office aggression scoring |
| `isda_precedents.json` | Credit Derivatives DC rulings and case law |
| `xover_s44.json` | iTraxx Crossover S44 universe definition (75 names by sector) |

---

## Recent Work (Feb 2026)

- **Gaussian copula tranche pricer** — full-fat CDO pricing with 4-index calibration (16/16 tranches zero error), S42 vs S44 roll analysis
- **SN13 social sentiment fix** — macrocosmos SDK v3.1.0 compatibility (gRPC, field mapping, JSON parsing)
- **Social sentiment pre-filter** — keyword-based noise filter for 14 consumer-facing entities (INEOS, Nokia, TUI, Air France, JLR, Renault, Volvo, Virgin Media, Premier Foods, Ericsson, Telecom Italia, Lagardere, SES, Eutelsat); 75% LLM cost reduction on INEOS; credit keyword safety valve ensures genuine signals always pass through

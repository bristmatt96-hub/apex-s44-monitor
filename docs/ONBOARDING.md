# Macro Credit Monitor — Onboarding Guide

**Last updated**: 2026-02-24
**Branch**: `credit-catalyst`
**Python**: 3.10.9

---

## What This System Does

AI-augmented European credit relative value platform. Monitors 200 iTraxx Europe Series 44 constituents (125 Main investment-grade + 75 Crossover high-yield) for tradeable dislocations across CDS, bonds, and tranches.

**Strategy**: Long/short CDS, bond-CDS basis, delta-hedged tranches (primarily 0-3% equity tranche). The system enables relative value selection across the full 200-name universe — what to be long, what to be short, and when basis or tranche convexity offers better expression.

**AI edge**: Decentralized AI (Bittensor subnets) provides speed — first to receive relevant information (filings, news, equity moves +/-2%, documentation situations like Ardagh/Altice France) so positions can be adjusted quickly. The LLM determines relevance, filtering noise from actionable signal across all 200 names simultaneously.

**Owner**: Matt
**Repo**: `github.com/bristmatt96-hub/apex-s44-monitor`
**VPS**: 143.198.56.117 (DigitalOcean) — runs `credit-api.service` (FastAPI on port 8000)

---

## Quick Start

```bash
# 1. Clone and enter repo
git clone https://github.com/bristmatt96-hub/apex-s44-monitor.git
cd apex-s44-monitor
git checkout credit-catalyst

# 2. Create virtual environment
python -m venv venv-trading
# Windows:
venv-trading\Scripts\activate
# Linux/Mac:
source venv-trading/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
# Optional (trading-specific packages):
pip install -r requirements-trading.txt

# 4. Set up environment variables (see section below)
cp .env.example .env   # or create manually
# Edit .env with your API keys

# 5. Start the API server
python -m app.api.main
# Server runs at http://localhost:8000

# 6. Run tests
pytest tests/ -v
```

---

## Environment Variables (.env)

Create a `.env` file in the project root. Required and optional keys:

| Key | Required | Purpose |
|-----|----------|---------|
| `OPENAI_API_KEY` | Yes | GPT-4 for analysis, signal scoring, agent reasoning |
| `ANTHROPIC_API_KEY` | Yes | Claude for analysis and code generation |
| `CHUTES_API_KEY` | Yes | Bittensor Subnet 64 (Chutes) — primary LLM inference |
| `LLM_PROVIDER` | Yes | Set to `chutes` (default LLM routing) |
| `DESEARCH_API_KEY` | Yes | Bittensor Subnet 22 (Desearch) — web search for news lookups |
| `GOPHER_API_KEY` | Yes | Bittensor Subnet 42 (Gopher) — social sentiment data |
| `MACROCOSMOS_API_KEY` | Yes | Bittensor Subnet 13 (Macrocosmos) — social data API |
| `COMPANIES_HOUSE_API_KEY` | Optional | UK Companies House filings |
| `SUBSTACK_EMAIL` | Optional | Substack article ingestion |
| `SUBSTACK_EMAIL_PASSWORD` | Optional | Substack authentication |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram alert delivery (not yet configured) |
| `TELEGRAM_CHAT_ID` | Optional | Telegram chat for alerts (not yet configured) |

---

## Architecture Overview

```
apex-s44-monitor/
|
|-- app/api/main.py           # FastAPI server — all API endpoints + HTML pages
|-- app/web/                   # Frontend HTML pages (vanilla HTML/CSS/JS)
|
|-- analytics/                 # 30+ analysis modules (the brain)
|   |-- signal_scorer.py       # Credit signal scoring (one cross-asset input)
|   |-- trade_structurer.py    # Options structure recommender
|   |-- credit_equity_bridge.py # Orchestrator: credit data + equity + scoring
|   |-- tranche_pricer.py      # iTraxx tranche pricing (Main: 0-3/3-6/6-12/12-100, Xover: 0-10/10-20/20-35/35-100)
|   |-- relative_value.py      # Rich/cheap screen
|   |-- maturity_wall.py       # Refinancing risk analysis
|   |-- dispersion.py          # Spread dispersion regime
|   |-- scenario_analysis.py   # Stress testing
|   +-- ... (30 modules total)
|
|-- monitors/                  # 22+ real-time monitors
|   |-- equity_movers.py       # Equity price screen with news lookup
|   |-- rating_actions.py      # Rating agency actions tracker
|   |-- news_monitor.py        # News sentiment scanner
|   |-- earnings_monitor.py    # Earnings event monitor
|   |-- credit_events_monitor.py
|   |-- isda_analyzer.py       # ISDA determination events
|   +-- ...
|
|-- agents/                    # AI agent team
|   |-- analyst.py             # Credit research analyst
|   |-- strategist.py          # Trade strategy generator
|   |-- briefing.py            # Morning briefing compiler
|   +-- risk_manager.py        # Risk limit enforcement
|
|-- portfolio/                 # Portfolio management
|   |-- position_tracker.py    # Live position tracking
|   |-- stop_monitor.py        # Stop loss monitoring
|   |-- performance_analytics.py
|   +-- trade_journal.py
|
|-- scripts/                   # Utility scripts
|   |-- import_spreads.py      # Bloomberg Excel -> master JSON
|   |-- run_brain.py           # Run full analysis pipeline
|   |-- run_portfolio.py       # Portfolio analytics
|   +-- run_universe.py        # Universe screen
|
|-- data/                      # Static data + databases
|-- config/                    # Settings and configuration
|-- knowledge/                 # Knowledge base (PDFs, transcripts, vectors)
|-- services/                  # Background services (market_watcher.py)
|-- pitch/                     # Report generators (tearsheets, idea sheets)
|-- deck/                      # PowerPoint deck generator (Node.js)
|-- tests/                     # pytest test suite
|-- outputs/                   # Generated outputs (reports, snapshots)
+-- docs/                      # Documentation and plans
```

---

## The Strategy Engine (Must-Read Files)

### Core — Credit RV & Tranche Positioning

| File | Purpose |
|------|---------|
| `analytics/relative_value.py` | Rich/cheap screener — sector z-scores, rating z-scores, momentum, composite score, pair trades. Primary long/short CDS selection tool. |
| `analytics/tranche_pricer.py` | Gaussian copula CDO pricer — CS01, CS02, rho01, JTD, base correlation calibration. Core for 0-3% tranche positioning. |
| `analytics/tranche_strategy_engine.py` | Dispersion trades, delta hedging, P&L attribution (carry + spread + correlation + theta + default). |
| `analytics/cds_pricer.py` | ISDA Standard CDS Model — spread/upfront, DV01, CS01, JTD, implied PD. |
| `analytics/scenario_analysis.py` | 8 macro stress scenarios with exact P&L repricing across all strategies. |
| `analytics/risk_metrics.py` | Single-name + portfolio risk: DV01, CS01, JTD, VaR 95/99%, CVaR, concentration HHI. |

### Supplementary — Cross-Asset Signals

| File | Purpose |
|------|---------|
| `analytics/signal_scorer.py` | Credit signal score (0-100) and equity repricing score (0-100). The gap score is one cross-asset signal, not the core alpha. |
| `analytics/trade_structurer.py` | Options structure recommender — used when equity put expression is chosen. |
| `analytics/credit_equity_bridge.py` | Credit-equity gap detection. Useful for identifying where equity hasn't repriced but is just one input to RV decisions. |

---

## Key Data Files

| File | What It Contains |
|------|-----------------|
| `data/itraxx_s44_master.json` | **Master reference**: 200 constituents with CDS spreads, Bloomberg tickers, ISINs, RED pairs, equity tickers. Generated by `scripts/import_spreads.py` from Bloomberg Excel. |
| `data/itraxx_equity_map.json` | 75 Xover names -> equity ticker mapping (exchange, currency, options availability) |
| `config/equity_tickers.json` | Extended ticker mapping |
| `data/entity_profiles/` | 58 JSON profiles with credit thesis, catalysts, conviction scores per name |
| `data/maturity_wall.json` | Refinancing dates and amounts |
| `data/covenant_profiles.json` | Covenant details |
| `data/isda_precedents.json` | ISDA determination precedents |
| `data/sponsors.json` | Private equity sponsor data |
| `data/benchmarks/` | Calibration CSVs for Main and Xover tranches |

### Updating Spread Data

When a new Bloomberg extract arrives:

```bash
python scripts/import_spreads.py "path/to/ITRX S44.xlsx"
```

This parses both MAIN S44 and XOVER S44 sheets, merges equity ticker data from `itraxx_equity_map.json`, and writes the new `data/itraxx_s44_master.json`.

---

## API Endpoints

The FastAPI server (`app/api/main.py`) serves both HTML pages and JSON APIs.

### HTML Pages (browser)

| URL | Page |
|-----|------|
| `/` | Main dashboard |
| `/cockpit` | Command center |
| `/risk-calculator` | Risk calculator |
| `/tranches` | Tranche pricing |
| `/capabilities` | Platform capabilities overview |

### JSON APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /api/universe` | 75 Xover names with spreads, conviction, thesis |
| `GET /api/equity-bridge` | Full equity bridge results (live yfinance data) |
| `GET /api/equity-bridge/{name}` | Single-name detailed bridge view |
| `GET /api/trade-structure/{name}` | Trade structure recommendation |
| `GET /api/portfolio` | Current positions, hedges, stress scenarios |
| `GET /api/risk` | DV01, JTD, sector concentration, limits |
| `GET /api/relative-value` | Rich/cheap screen with composite scores |
| `GET /api/maturity-wall` | Top refinancing risk names |
| `GET /api/filings` | Latest filing alerts |
| `GET /api/dispersion` | Spread dispersion regime analysis |
| `GET /api/scenarios` | Stress scenario P&L |
| `GET /api/tranche-scenarios` | Tranche scenario tables |
| `GET /api/spreads` | Master spread data (filters: index, min/max_spread, sector, public_only) |

---

## Knowledge Base

The system has a rich knowledge base for RAG (retrieval-augmented generation):

| Directory | Contents |
|-----------|----------|
| `knowledge/books/` | 38+ PDFs covering credit fundamentals, options, portfolio management, ML |
| `knowledge/books/Option Book/` | Natenberg "Option Volatility and Pricing" — 22 chapter PDFs |
| `knowledge/summaries/` | Structured summaries of Option Book chapters |
| `knowledge/processed/` | Vectorized chunks + embeddings for semantic search |
| `knowledge/transcripts/` | Earnings call transcripts |
| `knowledge/substack_articles/` | Independent credit research articles |
| `knowledge/vectors/` | FAISS/vector indices |
| `trading_knowledge/` | Additional trading books and audiobook transcripts |

---

## Bittensor Subnet Integration

The system uses 4 Bittensor subnets for decentralized AI:

| Subnet | Purpose | API Key |
|--------|---------|---------|
| **SN64 (Chutes)** | Primary LLM inference (GPT-4 class) | `CHUTES_API_KEY` |
| **SN42 (Gopher)** | Social media sentiment data | `GOPHER_API_KEY` |
| **SN22 (Desearch)** | Web search for news/event lookups | `DESEARCH_API_KEY` |
| **SN13 (Macrocosmos)** | Social data aggregation | `MACROCOSMOS_API_KEY` |

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_import_spreads.py -v

# With coverage
pytest tests/ --cov=. --cov-report=term-missing
```

Current test files:
- `tests/test_import_spreads.py` — Spread import script (8 tests)
- `tests/test_equity_movers.py` — Equity movers monitor
- `tests/test_social_sentiment.py` — Social sentiment
- `tests/test_models.py` — Core models
- `tests/test_risk_manager.py` — Risk manager
- `tests/test_coordinator.py` — Coordinator

---

## Deployment

### Local Development

```bash
python -m app.api.main    # FastAPI on localhost:8000
```

### VPS (DigitalOcean)

```bash
# Deploy from local
git push origin credit-catalyst
ssh root@143.198.56.117 "cd /root/apex-s44-monitor && git pull && systemctl restart credit-api.service"

# Verify
curl http://143.198.56.117:8000/api/equity-bridge | python3 -m json.tool
```

The service file lives at `/etc/systemd/system/credit-api.service` on the VPS.

### Market Watcher (Background Service)

```bash
python services/market_watcher.py
```

Runs continuously: scans for opportunities, monitors positions, sends Telegram alerts.

---

## Frontend Design System

All pages use a consistent dark theme with vanilla HTML/CSS/JS (no framework):

- **Background**: `#0a0e17` (dark navy)
- **Cards**: `#111827` with `#1e293b` borders
- **Accent**: `#3b82f6` (blue)
- **Success/Danger**: `#10b981` / `#ef4444`
- **Fonts**: DM Sans (body), JetBrains Mono (code/numbers)
- **Layout**: CSS Grid with `auto-fill minmax(280px, 1fr)` responsive cards
- **Data fetching**: Vanilla `fetch()` to API endpoints

---

## Risk Configuration

Defined in `config/settings.py`:

- Starting capital: $3,000
- Max position size: 5% of capital
- Max daily loss: 10%
- Max positions: 10
- Min risk/reward: 2:1
- Min confidence: 65%

Capital allocation: 50% credit tranches, 25% options, 20% equities, 5% cash reserve.

---

## Key Conventions

- **Python style**: Type hints, Pydantic models, loguru logging
- **Frontend**: Vanilla HTML/CSS/JS with Fetch API
- **Data formats**: JSON for config, SQLite for persistence, Excel for Bloomberg extracts
- **Testing**: pytest (TDD preferred)
- **Commits**: Descriptive imperative mood, co-authored with Claude
- **Branch**: All work on `credit-catalyst`

---

## Common Tasks

### Add a new entity profile

Create `data/entity_profiles/<entity_name>.json` following existing profile schema. Include: name, index, sector, spread, conviction, thesis, catalysts, risk factors.

### Update spreads from Bloomberg

```bash
python scripts/import_spreads.py "path/to/new_extract.xlsx"
```

### Generate pitch materials

```bash
node deck/deck.js              # PowerPoint deck
python pitch/tearsheet_generator.py  # Tearsheets
python pitch/idea_sheet.py     # Idea sheets
```

### Run the full analysis pipeline

```bash
python scripts/run_brain.py    # Full credit analysis
python scripts/run_universe.py # Universe screen
python scripts/run_portfolio.py # Portfolio analytics
```

---

## Outputs Directory

Generated reports and snapshots go to `outputs/`:

| Directory | Contents |
|-----------|----------|
| `outputs/analytics/` | Analysis results |
| `outputs/backtest/` | Backtest results |
| `outputs/briefs/` | Morning briefings |
| `outputs/portfolio/` | Portfolio snapshots (e.g., `risk_snapshot_20260219.json`) |
| `outputs/risk/` | Risk reports |
| `outputs/pitch/` | Generated pitch materials |
| `outputs/idea_sheets/` | Trade idea sheets |
| `outputs/case_studies/` | Case study write-ups |

---

## Troubleshooting

**Port 8000 already in use**: Kill the existing process:
```bash
# Windows
netstat -ano | findstr :8000
taskkill /pid <PID> /f

# Linux
lsof -i :8000
kill -9 <PID>
```

**Missing API keys**: Check `.env` file has all required keys listed above. The system will log warnings for missing optional keys.

**Import script fails**: Ensure the Bloomberg Excel file has exactly 2 sheets named "MAIN S44" and "XOVER S44" with expected column headers (Company Name, Wgt, Corp Tkr, 5 Yr CDS Tkr, ISIN, RED Pair, Quote Convention, Spread (bp)).

**Tests fail on import**: Make sure `scripts/__init__.py` exists (empty file, makes the scripts directory importable).

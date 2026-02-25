# Getting Started — Macro Credit Monitor

## Quick Start (5 minutes)

```bash
# 1. Clone
git clone https://github.com/bristmatt96-hub/apex-s44-monitor.git
cd apex-s44-monitor
git checkout credit-catalyst

# 2. Python 3.10+ required
python --version

# 3. Install deps
pip install -r requirements.txt

# 4. Set up API keys
cp .env.example .env
# Edit .env with your keys (see below)

# 5. Verify
python -m pytest tests/test_social_sentiment.py -q
# Should see: 21 passed
```

## API Keys You Need

| Key | Where to get it | Cost | What it does |
|-----|----------------|------|-------------|
| `CHUTES_API_KEY` | [chutes.ai](https://chutes.ai) | ~$0.08/scan | LLM inference (triage + classify) |
| `MACROCOSMOS_API_KEY` | [macrocosmos.ai](https://macrocosmos.ai) | Free (TAO) | Social data from Bittensor SN13 |
| `DESEARCH_API_KEY` | [desearch.ai](https://desearch.ai) | Free (TAO) | Social data from Bittensor SN22 |
| `COMPANIES_HOUSE_API_KEY` | [gov.uk](https://developer.company-information.service.gov.uk/) | Free | UK regulatory filings |
| `ANTHROPIC_API_KEY` | [anthropic.com](https://console.anthropic.com/) | ~$2.37/scan | Fallback LLM (optional if using Chutes) |

**Minimum to run social sentiment:** `CHUTES_API_KEY` + at least one of `MACROCOSMOS_API_KEY` or `DESEARCH_API_KEY`.

## Run Things

```bash
# Social sentiment — single name, dry run (no LLM cost)
python -m monitors.social_sentiment --entity "INEOS" --dry-run

# Social sentiment — single name, live (uses Chutes)
python -m monitors.social_sentiment --entity "INEOS"

# Social sentiment — full 75-name universe
python -m monitors.social_sentiment

# Switch LLM provider on the fly
python -m monitors.social_sentiment --provider anthropic --entity "INEOS"

# Web dashboard
python web/app.py
# Open http://localhost:5000

# Morning brief
python -m monitors.morning_brief

# European filings monitor
python -m monitors.european_monitor

# News monitor
python -m monitors.news_monitor
```

## Project Structure

```
apex-s44-monitor/
  monitors/          # 21 real-time scanners
  analytics/         # 29 quant modules (pricing, risk, RV, macro)
  agents/            # AI analyst, strategist, risk manager
  scripts/           # CLI batch tools
  web/               # Flask dashboard + React cockpit
  data/              # SQLite DBs, entity profiles, JSON configs
  knowledge/         # KB retriever + ingestion
  tests/             # pytest suite
  docs/CAPABILITIES.md  # Full feature catalog
```

See `docs/CAPABILITIES.md` for what every module does.

## Branch

All development is on `credit-catalyst`. This is the primary branch (70+ commits ahead of main).

```bash
git checkout credit-catalyst
git pull origin credit-catalyst
```

## Sync Between Machines

```bash
# Before leaving
git add . && git commit -m "WIP" && git push origin credit-catalyst

# On new machine
git pull origin credit-catalyst
```

## .env is Never Committed

`.env` is in `.gitignore`. Each machine has its own copy. Share keys securely (not via git).

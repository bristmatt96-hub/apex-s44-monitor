# Capabilities Overview Page — Design

**Date**: 2026-02-24
**Approach**: Single-page capabilities showcase (capabilities.html)

## Goal

Create a professional capabilities overview page that catalogs all 50+ modules across the Credit Catalyst platform: monitors, analytics, APIs, Bittensor integrations, and web dashboards.

## Architecture

New static HTML page using existing design system. No new APIs needed — purely informational.

```
app/web/capabilities.html   ← New page
app/api/main.py              ← Add GET /capabilities route
```

## Page Layout

```
┌─────────────────────────────────────────────────────────────┐
│ HEADER: Credit Catalyst | Capabilities Overview  [nav links]│
├─────────────────────────────────────────────────────────────┤
│ HERO STATS: 24 Monitors | 30 Analytics | 12+ APIs | 4 SN  │
├───────────────────────┬─────────────────────────────────────┤
│ REAL-TIME MONITORS    │ ANALYTICS ENGINE                    │
│  13 capability cards  │  18 capability cards                │
├───────────────────────┼─────────────────────────────────────┤
│ AI / BITTENSOR        │ DATA UNIVERSE                       │
│  4 subnet integrations│  iTraxx coverage stats              │
├───────────────────────┼─────────────────────────────────────┤
│ ALERTS & DELIVERY     │ WEB DASHBOARDS                      │
│  Telegram, logs       │  4 page links                       │
├───────────────────────┴─────────────────────────────────────┤
│ API ENDPOINTS — full list with methods + descriptions       │
├─────────────────────────────────────────────────────────────┤
│ FOOTER                                                      │
└─────────────────────────────────────────────────────────────┘
```

## Design System

Same as existing pages:
- Dark theme (--bg-base: #0a0e17, --bg-card: #111827)
- DM Sans + JetBrains Mono fonts
- Card-based layout with CSS custom properties
- Badge system for status indicators
- Vanilla HTML/CSS/JS, no build tools

## Categories

### 1. Real-Time Monitors (13)
- Equity Movers — Stock screen for 175+ iTraxx names, ±3% alerts
- Social Sentiment — Bittensor social data via Gopher/Desearch
- European Monitor — EU regulatory filings
- Credit Events Monitor — Credit event tracking
- Earnings Monitor — Earnings calendar + analysis
- Earnings Sentiment — Earnings call sentiment scoring
- Earnings Transcript — Full transcript analysis
- News Monitor — Multi-source news aggregation
- RSS Monitor — RSS feed monitoring
- Rating Actions — Credit rating changes
- ISDA News/Analyzer/Agent — ISDA documentation monitoring
- Credit Twitter — Credit market social media
- Market Pulse — Market pulse monitor
- Morning Brief — Daily morning briefing
- Debtwire Parser — Debt market news parsing
- Live/Call Transcriber — Audio transcription

### 2. Analytics Engine (18+)
- Relative Value — Rich/cheap screen with z-scores
- Credit-Equity Bridge — Merton model, gap scoring
- Signal Scorer — Alpha signal aggregation
- Trade Structurer — Trade recommendation engine
- CDS Pricer — CDS pricing, DV01, CS01, JTD
- Scenario Analysis — Stress test P&L
- Dispersion — Spread dispersion regime
- Maturity Wall — Refinancing risk analysis
- Tranche Pricer/Scenarios/Strategy — Tranche analytics
- Fallen Angels — Downgrade risk detection
- Covenant Risk — Covenant breach analysis
- Credit Cycle — Cycle positioning model
- HY Fair Value Model — High yield fair value
- Merton Single Name — Structural credit model
- Cross Asset Credit Signals — Multi-asset signals
- ECB Lending Conditions — Macro credit conditions
- Fundamental Credit Analysis — Bottom-up analysis
- Equity Credit Signals — Equity-credit linkage
- News Sentiment Monitor — News sentiment scoring
- Insider Flow Tracker — Insider trading signals
- Distressed Monitor — Distressed situations
- Backtester — Strategy backtesting
- Situation Classifier — Situation type classification

### 3. AI / Bittensor Integration (4)
- Chutes SN64 — LLM inference (~$0.08/call)
- Gopher SN42 — Social data aggregation
- Desearch SN22 — Decentralized search
- Macrocosmos SN13 — Social data

### 4. Data Universe
- 200 iTraxx S44 constituents (75 Xover + 125 Main)
- 175+ equity ticker mappings
- SQLite persistence (equity_movers.db, social_sentiment.db, filings.db)

### 5. Alerts & Delivery
- Telegram Notifier — Rich HTML alerts
- Signal Changes Log — outputs/signal_changes.txt

### 6. Web Dashboards (4)
- Dashboard (/) — Main credit overview
- Cockpit (/cockpit) — Command center
- Risk Calculator (/risk-calculator) — Portfolio risk
- Tranches (/tranches) — Tranche scenario tables

### 7. API Endpoints (12+)
Full REST API listing with method, path, description

## Files Modified

| File | Change |
|------|--------|
| `app/web/capabilities.html` | New page |
| `app/api/main.py` | Add GET /capabilities route |

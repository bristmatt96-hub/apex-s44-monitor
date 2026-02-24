# Equity Screen Alert System — Design

**Date**: 2026-02-24
**Approach**: Enhance existing `monitors/equity_movers.py` (Approach A)

## Goal

Monitor all 175+ iTraxx names. When any moves ±3%, automatically investigate why (news + social + LLM credit analysis) and send a rich Telegram alert.

## Architecture

Enhance `equity_movers.py` with 3 new capabilities on top of existing pipeline:

```
equity_movers.py (enhanced)
├── [EXISTING] load_tickers()           → 175+ names (Xover 42 + Main 133)
├── [EXISTING] fetch_prices()           → yfinance batch, return all prices
├── [EXISTING] fetch_news_for_mover()   → Google News RSS headlines
├── [EXISTING] classify_mover()         → Chutes SN64 LLM credit classification
├── [EXISTING] store_mover()            → SQLite dedup + persistence
├── [EXISTING] log_signal_change()      → outputs/signal_changes.txt
│
├── [NEW] fetch_social_buzz()           → Gopher SN42 + Desearch SN22 quick scan
├── [NEW] send_equity_alert()           → Telegram rich alert per mover
└── [NEW] market watcher integration    → register in scan_markets() loop
```

## Pipeline (per scan cycle)

1. Fetch prices — yfinance batch for all 175+ tickers (existing)
2. Filter — keep only |change| >= 3% (change default from 2%)
3. For each mover:
   a. Fetch Google News RSS (existing)
   b. Quick Gopher + Desearch social check (NEW — reuse query functions from social_sentiment.py)
   c. Classify via Chutes LLM (existing — make always-on when alerting)
4. Store to SQLite (existing)
5. Send Telegram alert per NEW mover (NEW)
6. Log to signal_changes.txt (existing)

## New Function: `fetch_social_buzz()`

Lightweight social scan — NOT a full social_sentiment.py pipeline. Just counts posts and buckets sentiment.

- Query Gopher SN42 for entity name (last 24h, max 20 results)
- Query Desearch SN22 for entity name (last 1 day, max 20 results)
- Deduplicate by post_id across sources
- Count total posts, classify as bullish/bearish/neutral using simple keyword match
- Return: `{"total": 12, "bullish": 2, "bearish": 8, "neutral": 2, "top_post": "..."}`
- No per-post LLM classification (that's social_sentiment.py's job)

Reuses `query_gopher()` and `query_desearch()` from `monitors/social_sentiment.py`.

## New Function: `send_equity_alert()`

Uses existing `alerts/telegram_notifier.py` TelegramNotifier.send_message().

Telegram alert format (HTML):
```
[red/green circle] EQUITY ALERT: {entity_name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
[chart emoji] {ticker}  {change_pct}%  ({prev} -> {curr})
[bar chart] Volume: {vol_ratio}x average
[tag] Sector: {sector} | Index: {Xover/Main}

[newspaper] News:
- {headline_1} — {source}
- {headline_2} — {source}
- {headline_3} — {source}

[speech] Social: {total} posts ({bearish} bearish, {bullish} bullish, {neutral} neutral)

[warning] Credit Impact: {POSITIVE|NEGATIVE|NEUTRAL} (severity {n}/5)
"{explanation}"
```

Dedup: rely on store_mover() — only alerts for movers not already recorded today.

## Market Watcher Integration

In `services/market_watcher.py`:
- Add equity_movers to `_init_components()` scanner list
- Call `equity_movers.run_scan(threshold=3.0, classify=True, alert=True, social=True)` in `scan_markets()`
- EU market hours awareness: run during 08:00-16:30 GMT (iTraxx names are European)
- Frequency: every scan cycle (5 min during market hours)

## New CLI Flags

- `--alert` — send Telegram alerts for detected movers (default: off for CLI, on in watcher)
- `--social` — include social buzz lookup (default: off for CLI, on in watcher)
- Default threshold changed: 2.0 → 3.0

## Config

No new env vars needed. All keys already in .env:
- CHUTES_API_KEY, GOPHER_API_KEY, DESEARCH_API_KEY
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

## Cost

- Per mover alert: ~$0.08 (Chutes classification) + free (news RSS + social queries)
- Per scan cycle with 0 movers: $0 (just yfinance)
- Typical day (2-5 movers): $0.16-$0.40

## Files Modified

| File | Change |
|------|--------|
| `monitors/equity_movers.py` | Add fetch_social_buzz(), send_equity_alert(), new CLI flags, threshold default |
| `services/market_watcher.py` | Add equity screen to scanner init + scan_markets() |

## Testing

- `python -m monitors.equity_movers --threshold 1 --social --alert` (low threshold to trigger alerts for testing)
- `python -m monitors.equity_movers --entity "Grifols" --social --alert` (single name test)
- `python -m monitors.equity_movers --status` (verify DB storage)

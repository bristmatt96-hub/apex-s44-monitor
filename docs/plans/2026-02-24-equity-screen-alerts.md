# Equity Screen Alert System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance `monitors/equity_movers.py` so that when any of 175+ iTraxx names moves ±3%, the system automatically investigates why (news + social + LLM) and sends a rich Telegram alert.

**Architecture:** Add `fetch_social_buzz()` (Gopher SN42 + Desearch SN22), `send_equity_alert()` (Telegram HTML), and market watcher integration to the existing equity_movers.py pipeline. No new files — just enhance the existing monitor and wire it into the 24/7 watcher service.

**Tech Stack:** Python 3.10+, yfinance, requests, feedparser, aiohttp (Telegram), SQLite. Bittensor subnets: Chutes SN64 (LLM), Gopher SN42 (social), Desearch SN22 (social).

**Design doc:** `docs/plans/2026-02-24-equity-screen-alerts-design.md`

---

### Task 1: Add `fetch_social_buzz()` function

**Files:**
- Modify: `monitors/equity_movers.py` (add function + imports)
- Test: `tests/test_equity_movers.py` (create)

**Step 1: Write the failing test**

Create `tests/test_equity_movers.py`:

```python
"""Tests for equity movers social buzz and alert functions."""
import sys
from types import ModuleType
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field

# Stub heavy dependencies before importing equity_movers
for mod in ["yfinance", "feedparser", "dotenv"]:
    if mod not in sys.modules:
        stub = ModuleType(mod)
        if mod == "dotenv":
            stub.load_dotenv = lambda **kw: None
        sys.modules[mod] = stub

# Stub social_sentiment module to avoid macrocosmos/anthropic imports
_ss_stub = ModuleType("monitors.social_sentiment")

@dataclass
class _FakeSocialPost:
    post_id: str
    source: str
    author: str
    content: str
    posted_at: str
    url: str
    entity_name: str
    keywords_matched: list = field(default_factory=list)

_ss_stub.SocialPost = _FakeSocialPost
_ss_stub.query_gopher = MagicMock(return_value=[])
_ss_stub.query_desearch = MagicMock(return_value=[])
sys.modules["monitors.social_sentiment"] = _ss_stub
sys.modules["monitors"] = ModuleType("monitors")

from monitors.equity_movers import fetch_social_buzz


def test_fetch_social_buzz_returns_dict_with_counts():
    """fetch_social_buzz returns a dict with total, bullish, bearish, neutral, top_post."""
    result = fetch_social_buzz("Grifols SA", ["Grifols"])
    assert isinstance(result, dict)
    assert "total" in result
    assert "bullish" in result
    assert "bearish" in result
    assert "neutral" in result
    assert "top_post" in result


def test_fetch_social_buzz_counts_posts_correctly():
    """Posts from both sources are counted and deduped by post_id."""
    gopher_posts = [
        _FakeSocialPost("p1", "X", "user1", "Grifols downgrade risk high", "2026-02-24T10:00:00Z",
                         "https://x.com/1", "Grifols SA", ["downgrade"]),
        _FakeSocialPost("p2", "X", "user2", "Grifols new drug approval great news", "2026-02-24T11:00:00Z",
                         "https://x.com/2", "Grifols SA", []),
    ]
    desearch_posts = [
        _FakeSocialPost("p1", "X", "user1", "Grifols downgrade risk high", "2026-02-24T10:00:00Z",
                         "https://x.com/1", "Grifols SA", ["downgrade"]),  # duplicate
        _FakeSocialPost("p3", "X", "user3", "Grifols restructuring rumours", "2026-02-24T12:00:00Z",
                         "https://x.com/3", "Grifols SA", ["restructuring"]),
    ]

    with patch("monitors.equity_movers.query_gopher", return_value=gopher_posts), \
         patch("monitors.equity_movers.query_desearch", return_value=desearch_posts):
        result = fetch_social_buzz("Grifols SA", ["Grifols"])

    assert result["total"] == 3  # p1, p2, p3 (p1 deduped)


def test_fetch_social_buzz_sentiment_bucketing():
    """Bearish keywords bucket posts correctly."""
    posts = [
        _FakeSocialPost("p1", "X", "u1", "Grifols default risk rising", "2026-02-24T10:00:00Z",
                         "https://x.com/1", "Grifols SA", ["default"]),
        _FakeSocialPost("p2", "X", "u2", "Grifols upgrade expected", "2026-02-24T11:00:00Z",
                         "https://x.com/2", "Grifols SA", ["upgrade"]),
        _FakeSocialPost("p3", "X", "u3", "Grifols earnings coming up", "2026-02-24T12:00:00Z",
                         "https://x.com/3", "Grifols SA", []),
    ]

    with patch("monitors.equity_movers.query_gopher", return_value=posts), \
         patch("monitors.equity_movers.query_desearch", return_value=[]):
        result = fetch_social_buzz("Grifols SA", ["Grifols"])

    assert result["bearish"] >= 1  # "default" is bearish
    assert result["bullish"] >= 1  # "upgrade" is bullish
    assert result["total"] == 3
```

**Step 2: Run test to verify it fails**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_equity_movers.py -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_social_buzz' from 'monitors.equity_movers'`

**Step 3: Implement `fetch_social_buzz()` in `monitors/equity_movers.py`**

Add these imports near top of file (after existing imports):

```python
# Social buzz (Gopher SN42 + Desearch SN22)
try:
    from monitors.social_sentiment import query_gopher, query_desearch, SocialPost
    SOCIAL_AVAILABLE = True
except ImportError:
    SOCIAL_AVAILABLE = False
```

Add these constants after existing constants block:

```python
# Sentiment keywords for quick bucketing (no LLM needed)
BEARISH_KEYWORDS = {
    "downgrade", "default", "restructuring", "distressed", "bankruptcy",
    "covenant breach", "widening", "sell", "short", "risk", "warning",
    "negative", "deteriorating", "junk", "fallen angel", "miss",
    "loss", "debt", "leverage", "investigation", "probe", "fraud",
}
BULLISH_KEYWORDS = {
    "upgrade", "tightening", "recovery", "refinanced", "improvement",
    "positive", "beat", "outperform", "buy", "upgrade", "strong",
    "growth", "profit", "deleveraging", "investment grade",
}
```

Add this function after `classify_mover()`:

```python
def fetch_social_buzz(
    entity_name: str,
    search_terms: list[str],
) -> dict:
    """Quick social buzz scan via Gopher SN42 + Desearch SN22.

    Returns dict with post counts and sentiment bucketing.
    No per-post LLM classification — just keyword matching.
    """
    if not SOCIAL_AVAILABLE:
        return {"total": 0, "bullish": 0, "bearish": 0, "neutral": 0, "top_post": ""}

    # Query both sources
    gopher_posts = []
    desearch_posts = []
    try:
        gopher_posts = query_gopher(entity_name, search_terms)
    except Exception:
        pass
    try:
        desearch_posts = query_desearch(entity_name, search_terms, days_back=1, limit=20)
    except Exception:
        pass

    # Dedup by post_id
    seen_ids = set()
    all_posts = []
    for post in gopher_posts + desearch_posts:
        if post.post_id not in seen_ids:
            seen_ids.add(post.post_id)
            all_posts.append(post)

    # Bucket sentiment by keyword
    bullish = 0
    bearish = 0
    neutral = 0
    for post in all_posts:
        content_lower = post.content.lower()
        has_bear = any(kw in content_lower for kw in BEARISH_KEYWORDS)
        has_bull = any(kw in content_lower for kw in BULLISH_KEYWORDS)

        if has_bear and not has_bull:
            bearish += 1
        elif has_bull and not has_bear:
            bullish += 1
        else:
            neutral += 1

    # Pick top post (longest content as proxy for most informative)
    top_post = ""
    if all_posts:
        best = max(all_posts, key=lambda p: len(p.content))
        top_post = best.content[:120]

    return {
        "total": len(all_posts),
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "top_post": top_post,
    }
```

**Step 4: Run test to verify it passes**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_equity_movers.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
cd C:\Users\toget\apex-s44-monitor
git add monitors/equity_movers.py tests/test_equity_movers.py
git commit -m "feat(equity): add fetch_social_buzz() — Gopher SN42 + Desearch SN22 quick scan

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Add `send_equity_alert()` Telegram function

**Files:**
- Modify: `monitors/equity_movers.py` (add function)
- Test: `tests/test_equity_movers.py` (add tests)

**Step 1: Write the failing test**

Append to `tests/test_equity_movers.py`:

```python
from monitors.equity_movers import send_equity_alert, EquityMover


def test_send_equity_alert_formats_html_message():
    """send_equity_alert returns an HTML string with key fields."""
    mover = EquityMover(
        entity_name="Grifols SA",
        index="xover",
        ticker="GRF.MC",
        sector="Healthcare",
        previous_close=7.82,
        current_price=7.45,
        change_pct=-4.73,
        volume=5000000,
        avg_volume=2200000,
        volume_ratio=2.27,
        news_headlines=[
            {"title": "Grifols faces new accounting probe", "source": "Reuters", "link": ""},
            {"title": "Short seller renews attack", "source": "FT", "link": ""},
        ],
        credit_impact="negative",
        severity=4,
        explanation="CDS spreads likely to widen on accounting concerns",
        detected_at="2026-02-24T10:30:00",
    )
    social = {"total": 12, "bullish": 2, "bearish": 8, "neutral": 2, "top_post": ""}

    html = send_equity_alert(mover, social_buzz=social, send=False)

    assert "Grifols SA" in html
    assert "GRF.MC" in html
    assert "-4.7%" in html
    assert "2.3x" in html
    assert "Healthcare" in html
    assert "Xover" in html
    assert "accounting probe" in html
    assert "12 posts" in html
    assert "NEGATIVE" in html
    assert "severity" in html.lower() or "4/5" in html


def test_send_equity_alert_gainer_uses_green():
    """Positive movers get green emoji."""
    mover = EquityMover(
        entity_name="Test Corp",
        index="main",
        ticker="TST.L",
        sector="Industrials",
        previous_close=10.0,
        current_price=10.50,
        change_pct=5.0,
        detected_at="2026-02-24T10:30:00",
    )
    html = send_equity_alert(mover, send=False)
    # Should not have red circle for a gainer
    assert "Test Corp" in html
    assert "+5.0%" in html
```

**Step 2: Run test to verify it fails**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_equity_movers.py::test_send_equity_alert_formats_html_message -v`
Expected: FAIL — `ImportError: cannot import name 'send_equity_alert'`

**Step 3: Implement `send_equity_alert()` in `monitors/equity_movers.py`**

Add import near top (after existing imports):

```python
import asyncio
```

Add function after `fetch_social_buzz()`:

```python
def send_equity_alert(
    mover: EquityMover,
    social_buzz: dict | None = None,
    send: bool = True,
) -> str:
    """Format and optionally send a Telegram alert for an equity mover.

    Args:
        mover: The EquityMover to alert on.
        social_buzz: Output from fetch_social_buzz(), or None.
        send: If True, actually send via Telegram. If False, just return HTML.

    Returns:
        The formatted HTML message string.
    """
    is_decline = mover.change_pct < 0
    emoji = "\U0001f534" if is_decline else "\U0001f7e2"  # red / green circle
    direction_word = "DOWN" if is_decline else "UP"
    idx_label = "Xover" if mover.index == "xover" else "Main"

    # Format change with sign
    change_str = f"{mover.change_pct:+.1f}%"

    # Volume string
    vol_str = f"{mover.volume_ratio:.1f}x average" if mover.volume_ratio > 0 else "N/A"

    lines = [
        f"{emoji} <b>EQUITY ALERT: {mover.entity_name}</b>",
        "\u2501" * 28,
        f"\U0001f4c9 <b>{mover.ticker}</b>  {change_str}  "
        f"({mover.previous_close:.2f} \u2192 {mover.current_price:.2f})",
        f"\U0001f4ca Volume: {vol_str}",
        f"\U0001f3f7 Sector: {mover.sector or 'N/A'} | Index: {idx_label}",
    ]

    # News section
    if mover.news_headlines:
        lines.append("")
        lines.append("\U0001f4f0 <b>News:</b>")
        for h in mover.news_headlines[:3]:
            title = h.get("title", "")[:80]
            source = h.get("source", "")
            src_str = f" \u2014 {source}" if source else ""
            lines.append(f"\u2022 {title}{src_str}")

    # Social buzz section
    if social_buzz and social_buzz.get("total", 0) > 0:
        sb = social_buzz
        lines.append("")
        lines.append(
            f"\U0001f4ac <b>Social:</b> {sb['total']} posts "
            f"({sb['bearish']} bearish, {sb['bullish']} bullish, "
            f"{sb['neutral']} neutral)"
        )

    # Credit impact section
    if mover.credit_impact:
        lines.append("")
        impact_upper = mover.credit_impact.upper()
        sev_emoji = "\u26a0\ufe0f" if impact_upper == "NEGATIVE" else "\u2139\ufe0f"
        lines.append(
            f"{sev_emoji} <b>Credit Impact: {impact_upper}</b> "
            f"(severity {mover.severity}/5)"
        )
        if mover.explanation:
            lines.append(f"<i>\"{mover.explanation[:150]}\"</i>")

    html = "\n".join(lines)

    if send:
        _send_telegram_sync(html)

    return html


def _send_telegram_sync(html: str) -> bool:
    """Send a Telegram message synchronously (for use from non-async context)."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("  TELEGRAM: not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": html,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        else:
            print(f"  TELEGRAM error: {resp.status_code} {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"  TELEGRAM send failed: {e}")
        return False
```

**Step 4: Run tests to verify they pass**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_equity_movers.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
cd C:\Users\toget\apex-s44-monitor
git add monitors/equity_movers.py tests/test_equity_movers.py
git commit -m "feat(equity): add send_equity_alert() — rich Telegram HTML alerts

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Wire social + alerts into `run_scan()` pipeline and update CLI

**Files:**
- Modify: `monitors/equity_movers.py` (update run_scan + main + default threshold)

**Step 1: Write the failing test**

Append to `tests/test_equity_movers.py`:

```python
import argparse
from monitors.equity_movers import DEFAULT_THRESHOLD_PCT


def test_default_threshold_is_3_percent():
    """Default threshold should be 3.0% not 2.0%."""
    assert DEFAULT_THRESHOLD_PCT == 3.0
```

**Step 2: Run test to verify it fails**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_equity_movers.py::test_default_threshold_is_3_percent -v`
Expected: FAIL — `assert 2.0 == 3.0`

**Step 3: Make the changes**

In `monitors/equity_movers.py`:

**3a. Change default threshold** (line ~78):
```python
# Old:
DEFAULT_THRESHOLD_PCT = 2.0
# New:
DEFAULT_THRESHOLD_PCT = 3.0
```

**3b. Add `social` and `alert` params to `run_scan()` signature** (line ~599):
```python
def run_scan(
    entity_filter: str | None = None,
    universe_filter: str = "all",
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    fetch_news: bool = True,
    classify: bool = False,
    social: bool = False,      # NEW
    alert: bool = False,       # NEW
) -> list[EquityMover]:
```

**3c. Add social buzz step** — after the news fetch loop (after line ~684 `time.sleep(0.5)`), add:

```python
    # Fetch social buzz for movers
    if social:
        print(f"\n  Fetching social buzz for {len(movers)} movers...")
        for mover in movers:
            ticker_info = next(
                (t for t in tickers if t.ticker == mover.ticker), None
            )
            search_terms = [ticker_info.search_name] if ticker_info else [mover.entity_name.split()[0]]
            buzz = fetch_social_buzz(mover.entity_name, search_terms)
            # Stash buzz on the mover object for alert formatting
            mover._social_buzz = buzz
            if buzz["total"] > 0:
                safe_name = mover.entity_name[:25].encode("ascii", "replace").decode()
                print(f"    {safe_name}: {buzz['total']} posts "
                      f"({buzz['bearish']}B/{buzz['bullish']}L/{buzz['neutral']}N)")
```

**3d. If classify not explicitly set but alert is on, auto-enable classify:**

After the `social` block above, add:
```python
    # When alerting, always classify
    if alert and not classify:
        classify = True
```

Move the existing classify block to after this check (it's already there — just make sure classify is enabled).

**3e. Add alert sending** — after `store_mover()` loop (after line ~712), modify to:

```python
    new_count = 0
    for mover in movers:
        is_new = store_mover(conn, mover)
        if is_new:
            new_count += 1
            log_signal_change(mover)

            # Send Telegram alert for new movers
            if alert:
                social_buzz = getattr(mover, "_social_buzz", None)
                send_equity_alert(mover, social_buzz=social_buzz, send=True)
                safe_name = mover.entity_name[:25].encode("ascii", "replace").decode()
                print(f"    ALERTED: {safe_name}")
```

**3f. Update CLI args** in `main()` — add after existing args:

```python
    parser.add_argument("--social", action="store_true",
                        help="Include social buzz lookup (Gopher + Desearch)")
    parser.add_argument("--alert", action="store_true",
                        help="Send Telegram alerts for detected movers")
```

And pass them to `run_scan()`:

```python
    run_scan(
        entity_filter=args.entity,
        universe_filter=args.universe,
        threshold_pct=args.threshold,
        fetch_news=not args.no_news,
        classify=args.classify,
        social=args.social,     # NEW
        alert=args.alert,       # NEW
    )
```

**Step 4: Run tests to verify they pass**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_equity_movers.py -v`
Expected: 6 PASSED

**Step 5: Commit**

```bash
cd C:\Users\toget\apex-s44-monitor
git add monitors/equity_movers.py tests/test_equity_movers.py
git commit -m "feat(equity): wire social + Telegram alerts into run_scan pipeline, threshold -> 3%

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Wire into market watcher service

**Files:**
- Modify: `services/market_watcher.py`

**Step 1: No unit test needed** — this is wiring/integration. We'll test manually.

**Step 2: Add equity screen scanner to `_init_components()`**

In `services/market_watcher.py`, add after the existing scanner imports in `_init_components()` (around line 93):

```python
        try:
            from monitors.equity_movers import run_scan as equity_screen_scan
            self.scanners['equity_screen'] = equity_screen_scan
            logger.info("  \u2713 Equity Screen loaded")
        except Exception as e:
            logger.warning(f"  \u2717 Equity Screen not available: {e}")
```

**Step 3: Add equity screen to `scan_markets()`**

In `scan_markets()`, add after the existing scanner runs (around line 158):

```python
        # Run equity screen (EU market hours focus)
        if 'equity_screen' in self.scanners:
            try:
                equity_movers = self.scanners['equity_screen'](
                    threshold_pct=3.0,
                    classify=True,
                    social=True,
                    alert=True,
                )
                if equity_movers:
                    logger.info(f"  Equity screen: {len(equity_movers)} movers alerted")
            except Exception as e:
                logger.error(f"Equity screen scan failed: {e}")
```

**Step 4: Manual integration test**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m monitors.equity_movers --threshold 1 --entity "Grifols" --social`

Verify it runs without errors and shows social buzz data.

**Step 5: Commit**

```bash
cd C:\Users\toget\apex-s44-monitor
git add services/market_watcher.py
git commit -m "feat(watcher): wire equity screen into 24/7 market watcher scan loop

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: End-to-end test with Telegram

**Step 1: Run single-name test with alerts**

```bash
cd C:\Users\toget\apex-s44-monitor
python -m monitors.equity_movers --entity "Grifols" --threshold 0.1 --social --alert --classify
```

This uses a very low threshold (0.1%) to guarantee triggering on any name. Check:
- [ ] Terminal output shows social buzz counts
- [ ] Terminal output shows "ALERTED: Grifols"
- [ ] Telegram bot received the rich HTML alert
- [ ] Alert contains news headlines, social summary, credit impact

**Step 2: Run full universe scan**

```bash
python -m monitors.equity_movers --social --alert --classify
```

Verify at default 3% threshold. If no names have moved 3% today, lower to `--threshold 1` to test.

**Step 3: Verify database**

```bash
python -m monitors.equity_movers --status
```

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address any issues found in e2e testing

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

**Step 5: Push to GitHub**

```bash
git push origin main
```

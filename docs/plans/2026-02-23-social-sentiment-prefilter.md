# Social Sentiment Pre-Filter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a fast keyword-based pre-filter to `monitors/social_sentiment.py` that drops obviously non-credit social posts (sports, cycling, entertainment) before they reach the Claude classification step, cutting LLM costs by ~90%.

**Architecture:** Two-layer filter between SN13 fetch and Claude classify. Layer 1: global noise blocklist (sports/entertainment terms that are never credit-relevant). Layer 2: per-entity noise map for names with large non-credit social footprints (INEOS, Nokia, TUI). Posts matching any `CREDIT_KEYWORDS` always pass through regardless of noise matches (safety valve).

**Tech Stack:** Pure Python, no new dependencies. Uses existing `SocialPost` dataclass and `CREDIT_KEYWORDS` list.

---

### Task 1: Add noise constants

**Files:**
- Modify: `monitors/social_sentiment.py:59-97` (after `CREDIT_KEYWORDS`, before `ENTITY_ALIASES`)

**Step 1: Write the failing test**

Create test file:
- Create: `tests/test_social_sentiment.py`

```python
"""Tests for social sentiment pre-filter."""
import pytest
import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub macrocosmos + anthropic before import
for mod in ["macrocosmos", "anthropic", "dotenv"]:
    if mod not in sys.modules:
        stub = ModuleType(mod)
        if mod == "dotenv":
            stub.load_dotenv = lambda **kw: None
        sys.modules[mod] = stub

from monitors.social_sentiment import NOISE_BLOCKLIST, ENTITY_NOISE


def test_noise_blocklist_exists_and_has_sports_terms():
    assert isinstance(NOISE_BLOCKLIST, list)
    assert len(NOISE_BLOCKLIST) >= 10
    # Must contain key sports terms
    blocklist_lower = [t.lower() for t in NOISE_BLOCKLIST]
    for term in ["grenadiers", "premier league", "cycling"]:
        assert term in blocklist_lower, f"Missing '{term}' from NOISE_BLOCKLIST"


def test_entity_noise_has_ineos():
    assert "INEOS" in ENTITY_NOISE
    ineos_lower = [t.lower() for t in ENTITY_NOISE["INEOS"]]
    assert "manchester united" in ineos_lower
    assert "grenadiers" in ineos_lower
```

**Step 2: Run test to verify it fails**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_social_sentiment.py -v`
Expected: FAIL with `ImportError` (NOISE_BLOCKLIST not defined yet)

**Step 3: Write minimal implementation**

Add after `CREDIT_KEYWORDS` list (around line 66) in `monitors/social_sentiment.py`:

```python
# Global noise terms -- never credit-relevant for any entity
NOISE_BLOCKLIST = [
    # Football / soccer
    "Manchester United", "Man Utd", "MUFC", "Premier League",
    "transfer window", "footballer", "signing players", "squad depth",
    "manager sacked", "Glazers", "Old Trafford", "OGC Nice", "Ligue 1",
    "Champions League goal", "Europa League",
    # Cycling
    "Grenadiers", "cycling", "Tour de France", "Giro d'Italia", "Vuelta",
    "Algarve", "peloton", "stage race", "GC contender", "domestique",
    "Vauquelin", "Vlasov",
    # Other sports / entertainment
    "Formula 1", "F1 team", "rugby", "sailing", "Americas Cup",
    "yacht race",
]

# Per-entity noise -- for names with big non-credit social footprints
ENTITY_NOISE = {
    "INEOS": [
        "Manchester United", "Man Utd", "MUFC", "Grenadiers", "cycling",
        "Ratcliffe football", "Old Trafford", "OGC Nice", "peloton",
        "Tour de France", "Algarve", "Americas Cup", "Vivell",
        "stage race", "Giro", "Vuelta",
    ],
    "Nokia": ["phone", "smartphone", "Android", "mobile launch", "handset"],
    "TUI": [
        "holiday", "vacation", "flight delayed", "hotel review",
        "package deal", "all inclusive", "beach resort",
    ],
}
```

**Step 4: Run test to verify it passes**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_social_sentiment.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_social_sentiment.py monitors/social_sentiment.py
git commit -m "feat(social): add noise blocklist and per-entity noise map"
```

---

### Task 2: Implement `is_credit_noise()` filter function

**Files:**
- Modify: `monitors/social_sentiment.py` (add function after `get_search_terms()`, around line 256)
- Modify: `tests/test_social_sentiment.py` (add tests)

**Step 1: Write the failing tests**

Append to `tests/test_social_sentiment.py`:

```python
from monitors.social_sentiment import is_credit_noise, SocialPost


def _make_post(content: str, entity_name: str = "INEOS Finance PLC") -> SocialPost:
    """Helper to create test posts."""
    return SocialPost(
        post_id="test_001",
        source="X",
        author="testuser",
        content=content,
        posted_at="2026-02-23T10:00:00Z",
        url="https://x.com/test/1",
        entity_name=entity_name,
        keywords_matched=[],
    )


class TestIsCreditNoise:
    """Test the pre-filter logic."""

    def test_football_post_is_noise(self):
        post = _make_post("INEOS signing better players for Manchester United this window")
        assert is_credit_noise(post) is True

    def test_cycling_post_is_noise(self):
        post = _make_post("Great debut for INEOS Grenadiers at Tour de France stage 3")
        assert is_credit_noise(post) is True

    def test_credit_post_passes_through(self):
        post = _make_post("INEOS Rosignano plant crisis, 600 jobs at risk, regional government intervening")
        assert is_credit_noise(post) is False

    def test_credit_keyword_always_passes(self):
        """Even if noise terms present, credit keywords = pass through."""
        post = _make_post(
            "Manchester United owner INEOS faces restructuring of debt facilities"
        )
        assert is_credit_noise(post) is False

    def test_neutral_post_without_noise_passes(self):
        post = _make_post("INEOS reported Q4 earnings above consensus")
        assert is_credit_noise(post) is False

    def test_entity_specific_noise_only_applies_to_that_entity(self):
        # "Manchester United" is in INEOS noise, but not Nokia
        post = _make_post("Nokia Manchester United sponsorship deal", entity_name="Nokia Oyj")
        # Should use global blocklist only -- "Manchester United" IS in global blocklist
        assert is_credit_noise(post) is True

    def test_non_noisy_entity_passes(self):
        post = _make_post("Worldline SA covenant test approaching", entity_name="Worldline SA/France")
        assert is_credit_noise(post) is False

    def test_empty_content_passes(self):
        """Don't crash on empty posts."""
        post = _make_post("")
        assert is_credit_noise(post) is False
```

**Step 2: Run tests to verify they fail**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_social_sentiment.py::TestIsCreditNoise -v`
Expected: FAIL with `ImportError` (is_credit_noise not defined)

**Step 3: Write minimal implementation**

Add to `monitors/social_sentiment.py` after `get_search_terms()`:

```python
def is_credit_noise(post: SocialPost) -> bool:
    """Fast pre-filter to reject obviously non-credit posts.

    Returns True if the post should be SKIPPED (is noise).
    Safety valve: posts matching any CREDIT_KEYWORDS always pass through.
    """
    content_lower = post.content.lower()

    if not content_lower.strip():
        return False  # Don't filter empty posts, let Claude decide

    # Safety valve: any credit keyword present = always pass through
    for kw in CREDIT_KEYWORDS:
        if kw.lower() in content_lower:
            return False

    # Check global noise blocklist
    is_noisy = False
    for term in NOISE_BLOCKLIST:
        if term.lower() in content_lower:
            is_noisy = True
            break

    # Check per-entity noise (match against search aliases)
    if not is_noisy:
        for alias_key, noise_terms in ENTITY_NOISE.items():
            if alias_key.lower() in post.entity_name.lower():
                for term in noise_terms:
                    if term.lower() in content_lower:
                        is_noisy = True
                        break
                break  # Only check one entity match

    return is_noisy
```

**Step 4: Run tests to verify they pass**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_social_sentiment.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add monitors/social_sentiment.py tests/test_social_sentiment.py
git commit -m "feat(social): implement is_credit_noise() pre-filter with safety valve"
```

---

### Task 3: Wire filter into `run_scan()` pipeline

**Files:**
- Modify: `monitors/social_sentiment.py:706-726` (the de-dupe + classify section of `run_scan()`)

**Step 1: Write the failing test**

Append to `tests/test_social_sentiment.py`:

```python
from unittest.mock import patch, MagicMock


def test_run_scan_filters_noise_before_classify(tmp_path):
    """Noise posts should never reach classify_post()."""
    with patch("monitors.social_sentiment.DB_PATH", tmp_path / "test.db"), \
         patch("monitors.social_sentiment.get_demo_posts") as mock_demo, \
         patch("monitors.social_sentiment.classify_post") as mock_classify:

        # 3 posts: 1 noise, 1 credit, 1 borderline-passes
        mock_demo.return_value = [
            _make_post("INEOS Grenadiers cycling at Tour de France"),      # noise
            _make_post("INEOS restructuring debt facilities at holdco"),   # credit keyword
            _make_post("INEOS Rosignano plant facing 600 job losses"),    # no keyword, no noise
        ]
        mock_classify.return_value = MagicMock(
            alert_worthy=False, severity=1, entity_name="test",
            sentiment="neutral", is_new_info=False, claim_summary="",
            post_id="x",
        )

        from monitors.social_sentiment import run_scan
        run_scan(entity_filter="INEOS", demo_mode=True)

        # classify_post should only be called for the 2 non-noise posts
        assert mock_classify.call_count == 2
```

**Step 2: Run test to verify it fails**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_social_sentiment.py::test_run_scan_filters_noise_before_classify -v`
Expected: FAIL (classify called 3 times, not 2)

**Step 3: Modify `run_scan()`**

In `monitors/social_sentiment.py`, replace the section between de-duplicate and classify (around lines 706-726). Change:

```python
    # De-duplicate
    new_posts = []
    skipped = 0
    for post in all_posts:
        if is_duplicate(conn, post.post_id):
            skipped += 1
        else:
            new_posts.append(post)

    print(f"\n  Total posts: {len(all_posts)} | New: {len(new_posts)} | "
          f"Duplicates skipped: {skipped}")
```

To:

```python
    # De-duplicate
    new_posts = []
    skipped = 0
    for post in all_posts:
        if is_duplicate(conn, post.post_id):
            skipped += 1
        else:
            new_posts.append(post)

    # Pre-filter: drop obvious noise before sending to Claude
    filtered_posts = []
    noise_count = 0
    for post in new_posts:
        if is_credit_noise(post):
            noise_count += 1
        else:
            filtered_posts.append(post)

    print(f"\n  Total posts: {len(all_posts)} | New: {len(new_posts)} | "
          f"Duplicates skipped: {skipped} | Noise filtered: {noise_count} | "
          f"Sent to Claude: {len(filtered_posts)}")

    if not filtered_posts:
        print("  No posts to classify after noise filter.")
        conn.close()
        return []
```

Then update the classify loop to iterate over `filtered_posts` instead of `new_posts`:

```python
    # Classify through Claude
    signals = []
    print(f"\n  Classifying {len(filtered_posts)} posts through Claude...")

    for i, post in enumerate(filtered_posts):
```

And update the progress denominator:

```python
        if i < len(filtered_posts) - 1:
            time.sleep(0.3)
```

**Step 4: Run all tests to verify they pass**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_social_sentiment.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add monitors/social_sentiment.py tests/test_social_sentiment.py
git commit -m "feat(social): wire noise pre-filter into run_scan pipeline

Drops obviously non-credit posts (sports, cycling, entertainment) before
Claude classification. Posts with credit keywords always pass through.
Expected ~90% reduction in LLM calls for noisy entities like INEOS."
```

---

### Task 4: Add `--dry-run` flag for testing the filter

**Files:**
- Modify: `monitors/social_sentiment.py` (CLI section, around line 906)

**Step 1: Write the failing test**

Append to `tests/test_social_sentiment.py`:

```python
def test_cli_dry_run_flag():
    """--dry-run should be a valid CLI argument."""
    from monitors.social_sentiment import main
    import argparse
    # Just verify the parser accepts --dry-run without error
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(["--dry-run"])
    assert args.dry_run is True
```

**Step 2: Run test to verify it passes (this one's a parser test)**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_social_sentiment.py::test_cli_dry_run_flag -v`

**Step 3: Add `--dry-run` to CLI and `run_scan()`**

In the argparse section of `main()`, add:

```python
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be filtered vs sent to Claude (no API calls)",
    )
```

In `run_scan()`, add a `dry_run: bool = False` parameter. After the noise filter section, if dry_run:

```python
    if dry_run:
        print(f"\n  [DRY RUN] Would send {len(filtered_posts)} posts to Claude:")
        for p in filtered_posts:
            print(f"    PASS: [{p.entity_name[:25]}] {p.content[:80]}...")
        print(f"\n  [DRY RUN] Would SKIP {noise_count} noise posts:")
        for post in new_posts:
            if is_credit_noise(post):
                print(f"    SKIP: [{post.entity_name[:25]}] {post.content[:80]}...")
        conn.close()
        return []
```

**Step 4: Run all tests**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_social_sentiment.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add monitors/social_sentiment.py tests/test_social_sentiment.py
git commit -m "feat(social): add --dry-run flag to preview filter without LLM calls"
```

---

### Task 5: Final integration test with real INEOS data

**Step 1: Run dry-run against INEOS**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m monitors.social_sentiment --entity "INEOS" --dry-run`

Expected output should show:
- ~30 posts SKIPPED (football/cycling noise)
- ~1-2 posts PASS (credit-relevant like Rosignano plant)
- 0 Claude API calls made

**Step 2: If results look good, run for real**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m monitors.social_sentiment --entity "INEOS"`

Verify only 1-2 posts get classified instead of 32.

**Step 3: Final commit with any tweaks**

```bash
git add -A
git commit -m "chore(social): tune noise blocklist after INEOS dry-run validation"
```

# SN13 vs SN22 Benchmark Design

**Date:** 2026-02-23
**Goal:** Build a benchmark script that queries both Bittensor SN13 (macrocosmos) and SN22 (Desearch) for the same entity + time window, then compares coverage, freshness, and signal-to-noise ratio to decide which source is better for credit-relevant social data.

## Architecture

Single script `scripts/benchmark_sn13_vs_sn22.py` that:
1. Takes an entity name (or `--all-noisy` for the 14 consumer-facing entities)
2. Queries SN13 via existing `query_sn13()` function
3. Queries SN22 via new `query_desearch()` REST client
4. Normalizes both to `SocialPost` dataclass
5. Matches/deduplicates by tweet ID
6. Scores each post using existing `is_credit_noise()` + `has_credit_keyword()`
7. Computes 8 quality metrics per source
8. Prints comparison table + saves JSON report

## SN22 Client

REST API: `GET https://api.desearch.ai/twitter`
- Auth: `Authorization: <DESEARCH_API_KEY>` header
- Params: `query`, `start_date`, `end_date`, `count`, `sort`, `lang`
- Returns: list of tweet objects (id, author, content, timestamp, url, etc.)

Query construction mirrors SN13: entity aliases + credit keywords combined.

## Metrics

| Metric | Computation |
|--------|------------|
| Total posts | Raw count |
| Unique to source | Posts found by only this source (by tweet ID) |
| Overlap | Posts found by both |
| Signal rate | % where has_credit_keyword() = True |
| Noise rate | % where is_credit_noise() = True |
| Ambiguous rate | % neither signal nor noise |
| Median freshness | Median age of posts in hours |
| Newest post | Age of most recent post |

## Demo Mode

If `DESEARCH_API_KEY` not set, generates realistic mock SN22 results:
- Takes SN13 results as base
- Adds ~30% extra mock posts (some signal, some noise)
- Removes ~10% of SN13 posts to simulate different coverage
- Adds slight timestamp variation

This lets the comparison logic be tested end-to-end without API access.

## Reuse from existing code

From `monitors.social_sentiment`:
- `SocialPost`, `ENTITY_ALIASES`, `CREDIT_KEYWORDS`
- `query_sn13()`, `is_credit_noise()`, `has_credit_keyword()`, `is_noisy_entity()`

## CLI

```
python -m scripts.benchmark_sn13_vs_sn22 --entity "INEOS"
python -m scripts.benchmark_sn13_vs_sn22 --all-noisy
python -m scripts.benchmark_sn13_vs_sn22 --entity "INEOS" --demo
```

## Environment Variables

- `MACROCOSMOS_API_KEY` — existing, for SN13
- `DESEARCH_API_KEY` — new, for SN22 (optional, falls back to demo mode)

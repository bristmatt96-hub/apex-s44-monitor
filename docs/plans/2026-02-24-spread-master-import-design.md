# iTraxx S44 Master Spread File — Design

**Date**: 2026-02-24
**Approach**: Static JSON + Import Script (Approach A)

## Goal

Create a single source of truth for all 200 iTraxx S44 constituents (125 Main + 75 Xover) with CDS spreads, Bloomberg tickers, ISINs, RED pairs, and merged equity ticker mappings. Replace scattered spread sources with one canonical file.

## Architecture

```
Bloomberg Excel extract
        |
        v
scripts/import_spreads.py    ← Parse + merge equity map
        |
        v
data/itraxx_s44_master.json  ← Single source of truth (200 names)
        |
        v
app/api/main.py GET /api/spreads  ← API endpoint with filters
```

## Master JSON Schema

File: `data/itraxx_s44_master.json`

```json
{
  "metadata": {
    "series": 44,
    "snapshot_date": "2026-02-18",
    "source": "Bloomberg ITRX S44 Constituents",
    "main_count": 125,
    "xover_count": 75,
    "main_avg_spread": 52.68,
    "xover_avg_spread": 250.11
  },
  "constituents": {
    "<Company Name>": {
      "index": "main|xover",
      "weight": 0.008,
      "corp_ticker": "INEOSQ",
      "cds_ticker": "CT716410 MSG1 Curncy",
      "isin": "...",
      "red_pair": "...",
      "quote_convention": "spread|points_upfront",
      "spread_bps": 1224.23,
      "points_upfront": null,
      "equity_ticker": "AF.PA",
      "is_public": true,
      "sector": "Consumers",
      "options_available": true,
      "options_liquidity": "medium",
      "exchange": "Euronext Paris",
      "currency": "EUR"
    }
  }
}
```

Key: company name (matching existing entity profile and equity map naming).
Equity fields merged from `data/itraxx_equity_map.json` for Xover names.
Main names get null equity fields (equity map covers Xover only currently).

## Import Script

File: `scripts/import_spreads.py`

Usage:
```
python scripts/import_spreads.py "path/to/ITRX S44.xlsx"
```

Steps:
1. Read MAIN S44 sheet → 125 rows
2. Read XOVER S44 sheet → 75 rows
3. Parse columns: Company Name, Wgt, Corp Tkr, 5 Yr CDS Tkr, ISIN, RED Pair, Quote Convention, Spread (bp), Points Upfront
4. Load existing itraxx_equity_map.json, merge equity data by fuzzy name match
5. Compute summary stats (avg spread, median, count per index)
6. Write data/itraxx_s44_master.json
7. Print summary to stdout

## API Endpoint

Route: `GET /api/spreads`

Query params:
- `index` — filter by "main" or "xover"
- `min_spread` — minimum spread in bps
- `max_spread` — maximum spread in bps
- `sector` — sector filter (exact match)
- `public_only` — boolean, filter to public companies only

Response:
```json
{
  "metadata": { ... },
  "constituents": [ ... ],
  "filter_count": 75,
  "total_count": 200
}
```

## Implementation Tasks

1. **Import script** — `scripts/import_spreads.py` — parse Excel, merge equity map, write JSON
2. **Run import** — generate `data/itraxx_s44_master.json` from the 2026-02-18 extract
3. **API endpoint** — `GET /api/spreads` in `app/api/main.py`
4. **Tests** — unit tests for import script (parse, merge, filter)

## Files

| File | Change |
|------|--------|
| `scripts/import_spreads.py` | New — Excel parser + JSON writer |
| `data/itraxx_s44_master.json` | New — master reference file (generated) |
| `app/api/main.py` | Add GET /api/spreads endpoint |
| `tests/test_import_spreads.py` | New — unit tests |

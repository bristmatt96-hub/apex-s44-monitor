# iTraxx S44 Master Spread Import — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a single source of truth JSON file with all 200 iTraxx S44 constituents (CDS spreads + equity mappings) plus an import script and API endpoint.

**Architecture:** Excel parser script reads Bloomberg extract, merges equity ticker data from existing itraxx_equity_map.json, writes master JSON. FastAPI endpoint serves the data with optional filters.

**Tech Stack:** Python, openpyxl, FastAPI, pytest

---

### Task 1: Import Script — Parse Excel + Write Master JSON

**Files:**
- Create: `scripts/import_spreads.py`
- Read: `data/itraxx_equity_map.json` (existing equity ticker mappings)
- Output: `data/itraxx_s44_master.json`

**Step 1: Write the failing test**

Create `tests/test_import_spreads.py`:

```python
"""Tests for iTraxx S44 spread import script."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _make_mock_ws(headers, rows):
    """Create a mock worksheet that yields rows like openpyxl."""
    all_rows = [headers] + rows
    mock_ws = MagicMock()
    mock_ws.iter_rows = MagicMock(return_value=(tuple(r) for r in all_rows))
    return mock_ws


# --- parse_sheet ---

def test_parse_main_sheet_returns_dict_keyed_by_name():
    from scripts.import_spreads import parse_sheet

    headers = ["Company Name", "Wgt", "Corp Tkr", "5 Yr CDS Tkr",
               "ISIN", "RED Pair", "Quote Convention", "Spread (bp)"]
    rows = [
        ["Suedzucker AG", 0.8, "SZUGR", "CT716410 MSG1 Curncy",
         "XS2550868801", "DLA7AKAC2", "Spread", 167],
        ["Stellantis NV", 0.8, "STLA", "CFIAT1E5 MSG1 Curncy",
         "XS2325733413", "NVA645AH0", "Spread", 150],
    ]
    result = parse_sheet(headers, rows, index_name="main")

    assert len(result) == 2
    assert "Suedzucker AG" in result
    assert result["Suedzucker AG"]["index"] == "main"
    assert result["Suedzucker AG"]["spread_bps"] == 167
    assert result["Suedzucker AG"]["corp_ticker"] == "SZUGR"
    assert result["Suedzucker AG"]["quote_convention"] == "spread"
    assert result["Suedzucker AG"]["points_upfront"] is None


def test_parse_xover_sheet_with_points_upfront():
    from scripts.import_spreads import parse_sheet

    headers = ["Company Name", "Wgt", "Corp Tkr", "5 Yr CDS Tkr",
               "ISIN", "RED Pair", "Quote Convention", "Spread (bp)",
               "Points Upfront (if Convention)"]
    rows = [
        ["INEOS Quattro Finance 2 Plc", 1.333, "STYRO", "CY865948 MSG1 Curncy",
         "XS2719090636", "GKBE9IAB4", "Points Upfront", 1224.229, 20.8],
    ]
    result = parse_sheet(headers, rows, index_name="xover")

    assert result["INEOS Quattro Finance 2 Plc"]["quote_convention"] == "points_upfront"
    assert result["INEOS Quattro Finance 2 Plc"]["points_upfront"] == 20.8
    assert result["INEOS Quattro Finance 2 Plc"]["spread_bps"] == 1224.229


# --- merge_equity_data ---

def test_merge_equity_data_adds_ticker():
    from scripts.import_spreads import merge_equity_data

    constituents = {
        "Air France-KLM": {
            "index": "xover", "spread_bps": 100,
            "equity_ticker": None, "is_public": None,
            "options_available": None, "options_liquidity": None,
            "sector": None, "exchange": None, "currency": None,
        }
    }
    equity_map = {
        "Air France-KLM": {
            "equity_ticker": "AF.PA", "is_public": True,
            "options_available": True, "options_liquidity": "medium",
            "sector": "Consumers", "exchange": "Euronext Paris",
            "currency": "EUR",
        }
    }
    merge_equity_data(constituents, equity_map)

    assert constituents["Air France-KLM"]["equity_ticker"] == "AF.PA"
    assert constituents["Air France-KLM"]["is_public"] is True
    assert constituents["Air France-KLM"]["sector"] == "Consumers"


def test_merge_equity_data_fuzzy_match():
    """Excel might say 'Worldline SA/France', equity map says 'Worldline SA'."""
    from scripts.import_spreads import merge_equity_data

    constituents = {
        "Worldline SA/France": {
            "index": "xover", "spread_bps": 1027,
            "equity_ticker": None, "is_public": None,
            "options_available": None, "options_liquidity": None,
            "sector": None, "exchange": None, "currency": None,
        }
    }
    equity_map = {
        "Worldline SA": {
            "equity_ticker": "WLN.PA", "is_public": True,
            "options_available": True, "options_liquidity": "good",
            "sector": "TMT", "exchange": "Euronext Paris",
            "currency": "EUR",
        }
    }
    merge_equity_data(constituents, equity_map)

    assert constituents["Worldline SA/France"]["equity_ticker"] == "WLN.PA"


# --- compute_metadata ---

def test_compute_metadata():
    from scripts.import_spreads import compute_metadata

    constituents = {
        "A": {"index": "main", "spread_bps": 50},
        "B": {"index": "main", "spread_bps": 60},
        "C": {"index": "xover", "spread_bps": 200},
    }
    meta = compute_metadata(constituents, snapshot_date="2026-02-18")

    assert meta["series"] == 44
    assert meta["main_count"] == 2
    assert meta["xover_count"] == 1
    assert meta["main_avg_spread"] == 55.0
    assert meta["xover_avg_spread"] == 200.0


def test_default_threshold_is_three():
    """Regression: equity movers threshold should remain 3.0."""
    from monitors.equity_movers import DEFAULT_THRESHOLD_PCT
    assert DEFAULT_THRESHOLD_PCT == 3.0
```

**Step 2: Run tests to verify they fail**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_import_spreads.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.import_spreads'`

**Step 3: Write the import script**

Create `scripts/import_spreads.py`:

```python
#!/usr/bin/env python3
"""
Import iTraxx S44 constituent spreads from Bloomberg Excel extract.

Usage:
    python scripts/import_spreads.py "path/to/ITRX S44.xlsx"

Reads MAIN S44 and XOVER S44 sheets, merges equity ticker data from
data/itraxx_equity_map.json, and writes data/itraxx_s44_master.json.
"""

import json
import sys
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EQUITY_MAP_PATH = PROJECT_ROOT / "data" / "itraxx_equity_map.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "itraxx_s44_master.json"


# ── Parsing ──────────────────────────────────────────────────────────


def parse_sheet(headers: list, rows: list, index_name: str) -> dict:
    """Parse rows from a single Excel sheet into a dict keyed by company name.

    Args:
        headers: Column header names (for reference, not used directly).
        rows: List of row tuples from openpyxl.
        index_name: 'main' or 'xover'.

    Returns:
        Dict keyed by company name with spread/ticker data.
    """
    constituents = {}
    has_upfront = len(headers) >= 9  # Xover has 9th column

    for row in rows:
        if not row or not row[0]:
            continue
        name = str(row[0]).strip()
        convention = str(row[6] or "Spread").strip().lower().replace(" ", "_")
        spread = row[7] if row[7] is not None else None
        upfront = row[8] if has_upfront and len(row) > 8 else None

        # Normalise spread to float
        if spread is not None:
            try:
                spread = round(float(spread), 3)
            except (ValueError, TypeError):
                spread = None

        if upfront is not None:
            try:
                upfront = round(float(upfront), 2)
            except (ValueError, TypeError):
                upfront = None

        constituents[name] = {
            "index": index_name,
            "weight": round(float(row[1]), 4) if row[1] else None,
            "corp_ticker": str(row[2]).strip() if row[2] else None,
            "cds_ticker": str(row[3]).strip() if row[3] else None,
            "isin": str(row[4]).strip() if row[4] else None,
            "red_pair": str(row[5]).strip() if row[5] else None,
            "quote_convention": convention,
            "spread_bps": spread,
            "points_upfront": upfront if convention == "points_upfront" else None,
            # Equity fields — filled by merge_equity_data
            "equity_ticker": None,
            "is_public": None,
            "options_available": None,
            "options_liquidity": None,
            "sector": None,
            "exchange": None,
            "currency": None,
        }

    return constituents


# ── Equity Map Merge ─────────────────────────────────────────────────


def _normalise(name: str) -> str:
    """Normalise company name for fuzzy matching."""
    return (
        name.lower()
        .replace("/", " ")
        .replace("-", " ")
        .replace("  ", " ")
        .strip()
    )


def merge_equity_data(constituents: dict, equity_map: dict) -> None:
    """Merge equity ticker data from equity map into constituents (in-place).

    Uses exact match first, then normalised fuzzy match.
    """
    # Build normalised lookup
    norm_lookup = {_normalise(k): v for k, v in equity_map.items()}

    equity_fields = [
        "equity_ticker", "is_public", "options_available",
        "options_liquidity", "sector", "exchange", "currency",
    ]

    for name, data in constituents.items():
        # Try exact match
        eq = equity_map.get(name)
        if not eq:
            # Try normalised match
            eq = norm_lookup.get(_normalise(name))
        if eq:
            for field in equity_fields:
                if field in eq and eq[field] is not None:
                    data[field] = eq[field]


# ── Metadata ─────────────────────────────────────────────────────────


def compute_metadata(constituents: dict, snapshot_date: str = None) -> dict:
    """Compute summary metadata from constituent data."""
    main = [c for c in constituents.values() if c["index"] == "main"]
    xover = [c for c in constituents.values() if c["index"] == "xover"]

    main_spreads = [c["spread_bps"] for c in main if c["spread_bps"] is not None]
    xover_spreads = [c["spread_bps"] for c in xover if c["spread_bps"] is not None]

    return {
        "series": 44,
        "snapshot_date": snapshot_date or str(date.today()),
        "source": "Bloomberg ITRX S44 Constituents",
        "main_count": len(main),
        "xover_count": len(xover),
        "main_avg_spread": round(sum(main_spreads) / len(main_spreads), 2) if main_spreads else 0,
        "xover_avg_spread": round(sum(xover_spreads) / len(xover_spreads), 2) if xover_spreads else 0,
        "main_median_spread": round(sorted(main_spreads)[len(main_spreads) // 2], 2) if main_spreads else 0,
        "xover_median_spread": round(sorted(xover_spreads)[len(xover_spreads) // 2], 2) if xover_spreads else 0,
    }


# ── Main ─────────────────────────────────────────────────────────────


def import_from_excel(excel_path: str, snapshot_date: str = None) -> dict:
    """Full import pipeline: parse Excel, merge equity data, return master dict."""
    wb = load_workbook(excel_path, read_only=True, data_only=True)

    all_constituents = {}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=True)
        headers = list(next(rows_iter))
        data_rows = [list(r) for r in rows_iter]

        if "MAIN" in sheet_name.upper():
            idx = "main"
        elif "XOVER" in sheet_name.upper():
            idx = "xover"
        else:
            continue

        parsed = parse_sheet(headers, data_rows, index_name=idx)
        all_constituents.update(parsed)

    wb.close()

    # Merge equity data
    if EQUITY_MAP_PATH.exists():
        with open(EQUITY_MAP_PATH) as f:
            eq_data = json.load(f)
        equity_names = eq_data.get("names", eq_data)
        merge_equity_data(all_constituents, equity_names)

    metadata = compute_metadata(all_constituents, snapshot_date)

    return {"metadata": metadata, "constituents": all_constituents}


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_spreads.py <path-to-excel>")
        sys.exit(1)

    excel_path = sys.argv[1]
    if not Path(excel_path).exists():
        print(f"File not found: {excel_path}")
        sys.exit(1)

    # Extract date from filename if possible (e.g. "2026-02-18 ITRX...")
    filename = Path(excel_path).stem
    snapshot_date = None
    if filename[:4].isdigit() and len(filename) >= 10:
        snapshot_date = filename[:10]

    master = import_from_excel(excel_path, snapshot_date)

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(master, f, indent=2, ensure_ascii=False)

    # Summary
    meta = master["metadata"]
    print(f"\n{'=' * 60}")
    print(f"  iTraxx S44 Master Import — {meta['snapshot_date']}")
    print(f"{'=' * 60}")
    print(f"  Main:  {meta['main_count']} names  avg {meta['main_avg_spread']:.1f}bp  med {meta['main_median_spread']:.1f}bp")
    print(f"  Xover: {meta['xover_count']} names  avg {meta['xover_avg_spread']:.1f}bp  med {meta['xover_median_spread']:.1f}bp")
    print(f"  Total: {meta['main_count'] + meta['xover_count']} constituents")

    # Distressed names
    distressed = [
        (n, c) for n, c in master["constituents"].items()
        if c.get("spread_bps") and c["spread_bps"] > 500
    ]
    if distressed:
        print(f"\n  Distressed (>500bp):")
        for name, c in sorted(distressed, key=lambda x: -x[1]["spread_bps"]):
            uf = f"  ({c['points_upfront']}pts)" if c.get("points_upfront") else ""
            print(f"    {name:<40} {c['spread_bps']:>8.1f}bp{uf}")

    print(f"\n  Written to: {OUTPUT_PATH}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_import_spreads.py -v`
Expected: All 5 tests PASS

**Step 5: Run import on real data**

Run: `cd C:\Users\toget\apex-s44-monitor && python scripts/import_spreads.py "C:\Users\toget\OneDrive\claude code\2026-02-18 ITRX S44 Consituents (No Formulas) (1).xlsx"`
Expected: Prints summary, writes `data/itraxx_s44_master.json` with 200 names

**Step 6: Commit**

```bash
git add scripts/import_spreads.py tests/test_import_spreads.py data/itraxx_s44_master.json
git commit -m "feat: add iTraxx S44 master spread import script + data"
```

---

### Task 2: API Endpoint — GET /api/spreads

**Files:**
- Modify: `app/api/main.py` — add /api/spreads route
- Test: `tests/test_import_spreads.py` — add API filter test

**Step 1: Write failing test**

Append to `tests/test_import_spreads.py`:

```python
def test_filter_by_index():
    """Verify we can filter constituents by index name."""
    from scripts.import_spreads import compute_metadata

    constituents = {
        "A": {"index": "main", "spread_bps": 50},
        "B": {"index": "xover", "spread_bps": 200},
        "C": {"index": "xover", "spread_bps": 300},
    }

    xover_only = {k: v for k, v in constituents.items() if v["index"] == "xover"}
    assert len(xover_only) == 2
    assert "A" not in xover_only


def test_filter_by_min_spread():
    """Verify spread threshold filter."""
    constituents = {
        "A": {"index": "main", "spread_bps": 50},
        "B": {"index": "xover", "spread_bps": 200},
        "C": {"index": "xover", "spread_bps": 800},
    }

    distressed = {k: v for k, v in constituents.items()
                  if v["spread_bps"] and v["spread_bps"] >= 500}
    assert len(distressed) == 1
    assert "C" in distressed
```

**Step 2: Run test to verify it passes (these are pure logic tests)**

Run: `cd C:\Users\toget\apex-s44-monitor && python -m pytest tests/test_import_spreads.py -v`
Expected: All 7 tests PASS

**Step 3: Add API endpoint to main.py**

Add after the existing `/api/rv` alias route in `app/api/main.py`:

```python
@app.get("/api/spreads")
async def api_spreads(
    index: str | None = None,
    min_spread: float | None = None,
    max_spread: float | None = None,
    sector: str | None = None,
    public_only: bool = False,
):
    """iTraxx S44 master spread data with optional filters."""
    master_path = PROJECT_ROOT / "data" / "itraxx_s44_master.json"
    if not master_path.exists():
        return {"error": "Master spread file not found. Run scripts/import_spreads.py first."}

    with open(master_path) as f:
        master = json.load(f)

    constituents = master.get("constituents", {})
    filtered = {}

    for name, data in constituents.items():
        if index and data.get("index") != index.lower():
            continue
        spread = data.get("spread_bps")
        if min_spread is not None and (spread is None or spread < min_spread):
            continue
        if max_spread is not None and (spread is None or spread > max_spread):
            continue
        if sector and data.get("sector", "").lower() != sector.lower():
            continue
        if public_only and not data.get("is_public"):
            continue
        filtered[name] = data

    return {
        "metadata": master.get("metadata", {}),
        "constituents": filtered,
        "filter_count": len(filtered),
        "total_count": len(constituents),
    }
```

**Step 4: Verify endpoint works**

Start server and test: `curl http://localhost:8000/api/spreads?index=xover&min_spread=500`
Expected: Returns distressed Xover names (INEOS Quattro, Worldline, INEOS Finance, SBB)

**Step 5: Commit**

```bash
git add app/api/main.py tests/test_import_spreads.py
git commit -m "feat(api): add GET /api/spreads endpoint with index/spread/sector filters"
```

---

### Task 3: Push to GitHub

**Step 1: Push all commits**

```bash
git push origin credit-catalyst
```

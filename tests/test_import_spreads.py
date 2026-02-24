"""Tests for iTraxx S44 spread import script."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


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
    from monitors.equity_movers import DEFAULT_THRESHOLD_PCT
    assert DEFAULT_THRESHOLD_PCT == 3.0

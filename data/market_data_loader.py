"""
Market Data Loader

Reads real CDS spread data from the iTraxx S44 constituents Excel file.
Returns a dict of {entity_name: {spread, convention, points_upfront, weight, ticker, isin}}.

Supports both MAIN S44 and XOVER S44 sheets.

Usage:
    from data.market_data_loader import load_market_data, find_latest_market_data
    data = load_market_data()  # auto-finds latest file
    ineos = data.get("INEOS Finance PLC")
    # {'spread': 908.29, 'convention': 'Points Upfront', 'points_upfront': 12.95,
    #  'weight': 1.333, 'ticker': 'INEGRP', 'cds_ticker': 'CY876619 MSG1 Curncy',
    #  'isin': 'XS2587558474', 'red_pair': 'GKBGFBAB7'}
"""

import glob
import os

import openpyxl


MARKET_DATA_DIR = os.path.join("data", "market_data")

# Sheet names in the Excel file
SHEETS = {
    "xover": "XOVER S44",
    "main": "MAIN S44",
}


def find_latest_market_data() -> str | None:
    """Find the most recent market data Excel file in data/market_data/."""
    pattern = os.path.join(MARKET_DATA_DIR, "itrx_s44_*.xlsx")
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None


def load_market_data(
    filepath: str | None = None,
    index: str = "xover",
) -> dict[str, dict]:
    """Load market data from the iTraxx constituents Excel file.

    Args:
        filepath: Path to the Excel file. Auto-detected if None.
        index: "xover" or "main" — which sheet to read.

    Returns:
        Dict of {entity_name: {spread, convention, points_upfront, weight,
        ticker, cds_ticker, isin, red_pair}}
    """
    if filepath is None:
        filepath = find_latest_market_data()
    if not filepath or not os.path.exists(filepath):
        return {}

    sheet_name = SHEETS.get(index.lower())
    if not sheet_name:
        return {}

    wb = openpyxl.load_workbook(filepath, data_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return {}

    ws = wb[sheet_name]
    is_xover = index.lower() == "xover"

    result = {}
    for row in range(2, ws.max_row + 1):
        name = ws.cell(row, 1).value
        if not name:
            continue

        name = str(name).strip()
        weight = ws.cell(row, 2).value
        ticker = ws.cell(row, 3).value
        cds_ticker = ws.cell(row, 4).value
        isin = ws.cell(row, 5).value
        red_pair = ws.cell(row, 6).value
        convention = ws.cell(row, 7).value
        spread_raw = ws.cell(row, 8).value

        # Parse spread — may be numeric or "N/A"
        spread = None
        if isinstance(spread_raw, (int, float)):
            spread = float(spread_raw)

        # Points upfront (Xover only, col 9)
        points_upfront = None
        if is_xover:
            pu_raw = ws.cell(row, 9).value
            if isinstance(pu_raw, (int, float)):
                points_upfront = float(pu_raw)

        result[name] = {
            "spread": spread,
            "convention": str(convention).strip() if convention else "Spread",
            "points_upfront": points_upfront,
            "weight": float(weight) if isinstance(weight, (int, float)) else None,
            "ticker": str(ticker).strip() if ticker else None,
            "cds_ticker": str(cds_ticker).strip() if cds_ticker else None,
            "isin": str(isin).strip() if isin else None,
            "red_pair": str(red_pair).strip() if red_pair else None,
        }

    wb.close()
    return result


def get_spread_context(entity_name: str, market_data: dict) -> str | None:
    """Build a market data context string for the analyst prompt.

    Tries exact match first, then fuzzy matching on key words.

    Returns a formatted string like:
        "MARKET DATA: INEOS Finance PLC trades at 908.3bps (Points Upfront: 12.95).
         Weight: 1.333%, Ticker: INEGRP, ISIN: XS2587558474"
    """
    # Exact match
    data = market_data.get(entity_name)

    # Fuzzy: try matching on significant words
    if not data:
        entity_lower = entity_name.lower()
        for mkt_name, mkt_data in market_data.items():
            mkt_lower = mkt_name.lower()
            # Check if key company words overlap
            entity_words = set(w for w in entity_lower.replace(".", "").split()
                               if len(w) > 2 and w not in {"plc", "ltd", "sarl",
                               "bv", "sa", "ag", "se", "ab", "spa", "sas",
                               "gmbh", "oyj", "the", "and", "for"})
            mkt_words = set(w for w in mkt_lower.replace(".", "").split()
                            if len(w) > 2 and w not in {"plc", "ltd", "sarl",
                            "bv", "sa", "ag", "se", "ab", "spa", "sas",
                            "gmbh", "oyj", "the", "and", "for"})
            overlap = entity_words & mkt_words
            if len(overlap) >= 1 and len(overlap) >= len(entity_words) * 0.4:
                data = mkt_data
                break

    if not data or data["spread"] is None:
        return None

    parts = [f"MARKET DATA (as of 18 Feb 2026): {entity_name}"]
    parts.append(f"5Y CDS spread: {data['spread']:.1f}bps")

    if data["convention"] == "Points Upfront" and data["points_upfront"] is not None:
        parts.append(f"Quote convention: Points Upfront ({data['points_upfront']:.2f} pts)")
    else:
        parts.append(f"Quote convention: Spread")

    if data["weight"]:
        parts.append(f"Index weight: {data['weight']:.3f}%")
    if data["ticker"]:
        parts.append(f"Corp ticker: {data['ticker']}")
    if data["isin"]:
        parts.append(f"ISIN: {data['isin']}")

    return " | ".join(parts)


def list_all_names(index: str = "xover") -> list[str]:
    """Return sorted list of all entity names in the market data file."""
    data = load_market_data(index=index)
    return sorted(data.keys())


if __name__ == "__main__":
    import sys

    index = sys.argv[1] if len(sys.argv) > 1 else "xover"
    data = load_market_data(index=index)

    if not data:
        print("No market data found.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(data)} names from {index.upper()} sheet\n")

    # Print sorted by spread descending
    sorted_names = sorted(data.items(), key=lambda x: x[1]["spread"] or 0, reverse=True)
    print(f"{'Name':<50} {'Spread':>8} {'Conv':<20} {'PU':>6} {'Ticker':<10}")
    print("-" * 100)
    for name, d in sorted_names:
        spread = f"{d['spread']:.1f}" if d['spread'] else "N/A"
        pu = f"{d['points_upfront']:.2f}" if d['points_upfront'] else "-"
        print(f"{name:<50} {spread:>8} {d['convention']:<20} {pu:>6} {d['ticker'] or '':<10}")

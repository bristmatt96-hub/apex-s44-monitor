"""
Debtwire Excel Parser for Apex Credit Monitor
Converts Debtwire Excel exports to JSON snapshots and database records
"""

import os
import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None

# Company name mappings from Debtwire names to index names
NAME_MAPPINGS = {
    "Asda Group Ltd": "Bellis Acquisition Company plc (Asda)",
    "Iceland Foods Ltd": "Iceland Bondco plc",
    "Ineos Quattro Holdings Ltd": "INEOS Quattro Holdings UK Ltd",
    "Samhallsbyggnadsbolaget I Norden AB": "SBB - Samhallsbyggnadsbolaget i Norden AB",
    "VodafoneZiggo Group Holding BV": "VodafoneZiggo Group BV",
}


def parse_debtwire_excel(file_path: str) -> Dict[str, Any]:
    """
    Parse a Debtwire Excel export file and return structured data

    Args:
        file_path: Path to the Debtwire Excel file

    Returns:
        Dictionary containing parsed company data
    """
    if pd is None:
        raise ImportError("pandas is required for Excel parsing. Install with: pip install pandas openpyxl")

    # Read the Excel file
    df = pd.read_excel(file_path, sheet_name=0, header=None)

    # Initialize result structure
    result = {
        "company_name": "",
        "ticker": "",
        "sector": "",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "overview": {
            "business_description": "",
            "business_positives": [],
            "fatal_flaw": "",
            "ownership": "",
            "public_private": "",
            "recent_news": ""
        },
        "ratings": {
            "moodys": {"rating": "", "outlook": "", "date": ""},
            "sp": {"rating": "", "outlook": "", "date": ""},
            "fitch": {"rating": "", "outlook": "", "date": ""}
        },
        "quick_assessment": {
            "period_end": "",
            "cffo": None,
            "total_debt": None,
            "interest_expense": None,
            "capex": None,
            "debt_due_one_year": None,
            "cash_on_hand": None,
            "revolver_available": None
        },
        "key_ratios": {
            "debt_to_ebitda": None,
            "ebitda_minus_capex_to_interest": None,
            "fcf_to_debt": None,
            "net_debt_to_ebitda": None
        },
        "trend_analysis": {
            "years": [],
            "revenue": [],
            "ebitda": [],
            "ebitda_margin": [],
            "total_debt": []
        },
        "debt_capitalization": [],
        "maturity_schedule": {
            "year_1": None,
            "year_2": None,
            "year_3": None,
            "year_4": None,
            "year_5": None,
            "thereafter": None
        },
        "equity_market_value": {},
        "credit_opinion": {
            "summary": "",
            "key_risks": [],
            "key_catalysts": [],
            "recommendation": ""
        }
    }

    # Parse company name from first cell typically
    for idx, row in df.iterrows():
        for col_idx, cell in enumerate(row):
            if pd.notna(cell) and isinstance(cell, str):
                cell_lower = cell.lower().strip()

                # Look for company name patterns
                if idx == 0 and col_idx == 0:
                    result["company_name"] = str(cell).strip()

                # Look for sector
                if "sector" in cell_lower:
                    next_cell = _get_next_cell(df, idx, col_idx)
                    if next_cell:
                        result["sector"] = str(next_cell).strip()

                # Look for business description
                if "business description" in cell_lower or "company description" in cell_lower:
                    next_cell = _get_next_cell(df, idx, col_idx)
                    if next_cell:
                        result["overview"]["business_description"] = str(next_cell).strip()

                # Look for ownership
                if "ownership" in cell_lower or "sponsor" in cell_lower:
                    next_cell = _get_next_cell(df, idx, col_idx)
                    if next_cell:
                        result["overview"]["ownership"] = str(next_cell).strip()
                        result["overview"]["public_private"] = "private" if "capital" in str(next_cell).lower() else "public"

                # Look for lifecycle/recent news
                if "lifecycle" in cell_lower or "status" in cell_lower:
                    next_cell = _get_next_cell(df, idx, col_idx)
                    if next_cell:
                        result["overview"]["recent_news"] = str(next_cell).strip()

                # Parse debt instruments
                if _is_debt_instrument_row(cell):
                    instrument = _parse_debt_row(df, idx)
                    if instrument:
                        result["debt_capitalization"].append(instrument)

                # Look for total debt
                if "total debt" in cell_lower:
                    next_cell = _get_next_cell(df, idx, col_idx)
                    if next_cell and _is_numeric(next_cell):
                        result["quick_assessment"]["total_debt"] = float(next_cell)

    # Apply name mapping if needed
    if result["company_name"] in NAME_MAPPINGS:
        result["company_name"] = NAME_MAPPINGS[result["company_name"]]

    return result


def _get_next_cell(df: pd.DataFrame, row_idx: int, col_idx: int) -> Optional[Any]:
    """Get the next non-empty cell in the row"""
    row = df.iloc[row_idx]
    for i in range(col_idx + 1, len(row)):
        if pd.notna(row.iloc[i]):
            return row.iloc[i]
    return None


def _is_numeric(value: Any) -> bool:
    """Check if a value is numeric"""
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", "").replace("$", "").replace("€", "").replace("£", ""))
            return True
        except:
            return False
    return False


def _is_debt_instrument_row(cell: Any) -> bool:
    """Check if a cell indicates a debt instrument row"""
    if not isinstance(cell, str):
        return False

    debt_indicators = [
        "notes", "bond", "term loan", "facility", "senior", "subordinated",
        "secured", "unsecured", "eur ", "gbp ", "usd ", "revolver"
    ]
    cell_lower = cell.lower()
    return any(indicator in cell_lower for indicator in debt_indicators)


def _parse_debt_row(df: pd.DataFrame, row_idx: int) -> Optional[Dict]:
    """Parse a debt instrument row"""
    row = df.iloc[row_idx]
    values = [v for v in row if pd.notna(v)]

    if len(values) < 2:
        return None

    instrument = {
        "instrument": str(values[0]).strip(),
        "amount": None,
        "maturity": "",
        "coupon": "",
        "price": None,
        "ytw": None,
        "stw": None,
        "rating": ""
    }

    # Parse amount (usually second value)
    for val in values[1:]:
        if _is_numeric(val):
            num = _parse_numeric(val)
            if num:
                if instrument["amount"] is None:
                    instrument["amount"] = num
                elif instrument["price"] is None and 50 < num < 150:
                    instrument["price"] = num
                break

    # Look for maturity year
    for val in values:
        if isinstance(val, str):
            year_match = re.search(r'20\d{2}', val)
            if year_match:
                instrument["maturity"] = year_match.group()
                break

    return instrument


def _parse_numeric(value: Any) -> Optional[float]:
    """Parse a numeric value from various formats"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            cleaned = value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
            # Handle parentheses for negative numbers
            if cleaned.startswith("(") and cleaned.endswith(")"):
                cleaned = "-" + cleaned[1:-1]
            return float(cleaned)
        except:
            return None
    return None


def convert_to_snapshot(data: Dict[str, Any], output_path: str) -> str:
    """
    Convert parsed Debtwire data to a credit snapshot JSON file

    Args:
        data: Parsed Debtwire data dictionary
        output_path: Path to save the JSON snapshot

    Returns:
        Path to the saved file
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return output_path


def process_debtwire_directory(input_dir: str, output_dir: str) -> List[str]:
    """
    Process all Debtwire Excel files in a directory

    Args:
        input_dir: Directory containing Debtwire Excel files
        output_dir: Directory to save JSON snapshots

    Returns:
        List of processed file paths
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    processed = []

    for excel_file in input_path.glob("*.xlsx"):
        try:
            data = parse_debtwire_excel(str(excel_file))

            # Generate output filename from company name
            company_slug = data["company_name"].lower()
            company_slug = re.sub(r'[^a-z0-9]+', '_', company_slug)
            company_slug = company_slug.strip('_')

            output_file = output_path / f"{company_slug}.json"
            convert_to_snapshot(data, str(output_file))
            processed.append(str(output_file))

            print(f"Processed: {excel_file.name} -> {output_file.name}")
        except Exception as e:
            print(f"Error processing {excel_file.name}: {e}")

    return processed


def watch_directory(input_dir: str, output_dir: str, interval_seconds: int = 60):
    """
    Watch a directory for new Debtwire Excel files and process them

    Args:
        input_dir: Directory to watch for new files
        output_dir: Directory to save JSON snapshots
        interval_seconds: How often to check for new files
    """
    import time

    processed_files = set()
    input_path = Path(input_dir)

    print(f"Watching {input_dir} for new Debtwire files...")

    while True:
        for excel_file in input_path.glob("*.xlsx"):
            if str(excel_file) not in processed_files:
                try:
                    data = parse_debtwire_excel(str(excel_file))

                    company_slug = data["company_name"].lower()
                    company_slug = re.sub(r'[^a-z0-9]+', '_', company_slug)
                    company_slug = company_slug.strip('_')

                    output_path = Path(output_dir)
                    output_path.mkdir(parents=True, exist_ok=True)

                    output_file = output_path / f"{company_slug}.json"
                    convert_to_snapshot(data, str(output_file))

                    processed_files.add(str(excel_file))
                    print(f"[{datetime.now()}] Processed: {excel_file.name}")
                except Exception as e:
                    print(f"[{datetime.now()}] Error: {excel_file.name} - {e}")

        time.sleep(interval_seconds)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python debtwire_parser.py <excel_file>           - Parse single file")
        print("  python debtwire_parser.py --batch <input_dir> <output_dir>  - Batch process")
        print("  python debtwire_parser.py --watch <input_dir> <output_dir>  - Watch directory")
        sys.exit(1)

    if sys.argv[1] == "--batch" and len(sys.argv) >= 4:
        processed = process_debtwire_directory(sys.argv[2], sys.argv[3])
        print(f"\nProcessed {len(processed)} files")

    elif sys.argv[1] == "--watch" and len(sys.argv) >= 4:
        watch_directory(sys.argv[2], sys.argv[3])

    else:
        # Single file processing
        data = parse_debtwire_excel(sys.argv[1])
        print(json.dumps(data, indent=2))

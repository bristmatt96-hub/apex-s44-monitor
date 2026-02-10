"""
CSV export and merge — writes scan results to CSV and optionally merges
with an existing tracker spreadsheet so you don't duplicate entries.
"""

import csv
import logging
from pathlib import Path

from .scanner import Match

logger = logging.getLogger(__name__)

# Column order for the output CSV
COLUMNS = [
    "Firm Name",
    "Category",
    "Role / Position",
    "Status",
    "Date Found",
    "Date Applied",
    "Source",
    "Source Type",
    "Document Type",
    "Contact Person",
    "Contact Email",
    "Notes",
    "File Path",
    "Snippet",
]


def match_to_row(m: Match) -> dict:
    return {
        "Firm Name": m.firm_name,
        "Category": m.firm_category,
        "Role / Position": m.role,
        "Status": m.status,
        "Date Found": m.date_found,
        "Date Applied": m.date_applied,
        "Source": m.source,
        "Source Type": m.source_type,
        "Document Type": m.document_type,
        "Contact Person": m.contact_person,
        "Contact Email": m.contact_email,
        "Notes": m.notes,
        "File Path": m.file_path,
        "Snippet": m.snippet,
    }


def export_csv(matches: list[Match], output_path: str) -> Path:
    """Write matches to a fresh CSV file."""
    out = Path(output_path)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for m in matches:
            writer.writerow(match_to_row(m))
    logger.info("Wrote %d rows to %s", len(matches), out)
    return out


def load_existing_tracker(tracker_path: str) -> list[dict]:
    """
    Load an existing CSV tracker.  Flexible about column names — normalises
    them to our canonical COLUMNS where possible.
    """
    rows = []
    p = Path(tracker_path)
    if not p.exists():
        logger.warning("Tracker file not found: %s", tracker_path)
        return rows

    # Column name normalisation map
    aliases = {
        "firm": "Firm Name",
        "firm name": "Firm Name",
        "company": "Firm Name",
        "company name": "Firm Name",
        "type": "Category",
        "category": "Category",
        "firm type": "Category",
        "role": "Role / Position",
        "position": "Role / Position",
        "role / position": "Role / Position",
        "job title": "Role / Position",
        "status": "Status",
        "date": "Date Found",
        "date found": "Date Found",
        "date applied": "Date Applied",
        "applied date": "Date Applied",
        "source": "Source",
        "source type": "Source Type",
        "document type": "Document Type",
        "doc type": "Document Type",
        "contact": "Contact Person",
        "contact person": "Contact Person",
        "contact name": "Contact Person",
        "email": "Contact Email",
        "contact email": "Contact Email",
        "notes": "Notes",
        "file": "File Path",
        "file path": "File Path",
        "path": "File Path",
        "snippet": "Snippet",
        "context": "Snippet",
    }

    with open(p, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return rows

        # Build column mapping
        col_map = {}
        for raw_col in reader.fieldnames:
            normalised = aliases.get(raw_col.strip().lower())
            if normalised:
                col_map[raw_col] = normalised
            elif raw_col.strip() in COLUMNS:
                col_map[raw_col] = raw_col.strip()
            else:
                col_map[raw_col] = raw_col.strip()

        for raw_row in reader:
            row = {}
            for raw_col, value in raw_row.items():
                mapped = col_map.get(raw_col, raw_col)
                row[mapped] = (value or "").strip()
            rows.append(row)

    logger.info("Loaded %d existing rows from %s", len(rows), tracker_path)
    return rows


def merge_with_tracker(
    matches: list[Match],
    tracker_path: str,
    output_path: str,
) -> tuple[Path, int, int]:
    """
    Merge new scan results with an existing tracker CSV.

    Deduplication logic:
    - If a firm already exists in the tracker, we SKIP adding a new row
      (preserving the user's manually-entered data for that firm).
    - New firms are appended at the end.
    - A column "Merge Source" is added: "existing" or "scan".

    Returns: (output_path, existing_count, new_count)
    """
    existing_rows = load_existing_tracker(tracker_path)

    # Build set of existing firm names (lowercased) for dedup
    existing_firms = set()
    for row in existing_rows:
        firm = row.get("Firm Name", "").strip().lower()
        if firm:
            existing_firms.add(firm)

    merged_columns = COLUMNS + ["Merge Source"]

    # Start with existing rows
    output_rows = []
    for row in existing_rows:
        out_row = {col: row.get(col, "") for col in COLUMNS}
        out_row["Merge Source"] = "existing"
        output_rows.append(out_row)

    # Add new matches that don't duplicate existing firms
    new_count = 0
    skipped = 0
    for m in matches:
        if m.firm_name.lower() in existing_firms:
            skipped += 1
            continue
        existing_firms.add(m.firm_name.lower())  # prevent dups within scan too
        row = match_to_row(m)
        row["Merge Source"] = "scan"
        output_rows.append(row)
        new_count += 1

    out = Path(output_path)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=merged_columns)
        writer.writeheader()
        for row in output_rows:
            writer.writerow(row)

    logger.info(
        "Merged: %d existing + %d new rows (%d skipped as duplicates) → %s",
        len(existing_rows), new_count, skipped, out,
    )
    return out, len(existing_rows), new_count

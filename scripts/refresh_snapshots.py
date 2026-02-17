#!/usr/bin/env python3
"""
Refresh Credit Snapshots

Updates company snapshot files in snapshots/ with latest data.
Can pull from Debtwire exports or manual updates.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

SNAPSHOTS_DIR = Path("snapshots")


def list_snapshots():
    """List all available snapshots."""
    if not SNAPSHOTS_DIR.exists():
        print("No snapshots directory found")
        return

    snapshots = sorted(SNAPSHOTS_DIR.glob("*.json"))
    print(f"\nCredit Snapshots: {len(snapshots)} companies\n")

    for f in snapshots:
        try:
            with open(f) as fh:
                data = json.load(fh)
            name = data.get("company_name", f.stem)
            sector = data.get("sector", "N/A")
            rating = data.get("ratings", {}).get("composite", "NR")
            updated = data.get("last_updated", "unknown")
            print(f"  {name:40s} | {sector:20s} | {rating:5s} | Updated: {updated}")
        except Exception:
            print(f"  {f.stem:40s} | ERROR reading file")


def validate_snapshots():
    """Check snapshots for missing or stale data."""
    if not SNAPSHOTS_DIR.exists():
        print("No snapshots directory found")
        return

    issues = []
    for f in sorted(SNAPSHOTS_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)

            name = data.get("company_name", f.stem)

            if not data.get("ratings"):
                issues.append(f"{name}: missing ratings")
            if not data.get("debt_capitalization"):
                issues.append(f"{name}: missing debt structure")
            if not data.get("key_ratios"):
                issues.append(f"{name}: missing key ratios")

        except Exception as e:
            issues.append(f"{f.stem}: failed to parse - {e}")

    if issues:
        print(f"\nFound {len(issues)} issues:\n")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nAll snapshots valid")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage credit snapshots")
    parser.add_argument("--list", action="store_true", help="List all snapshots")
    parser.add_argument("--validate", action="store_true", help="Validate snapshot data")

    args = parser.parse_args()

    if args.validate:
        validate_snapshots()
    else:
        list_snapshots()

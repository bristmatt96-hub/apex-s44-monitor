#!/usr/bin/env python3
"""
Job Application Scanner CLI

Scans your local folders and email stores for CVs, cover letters, pitch docs,
and application correspondence. Matches against 80+ financial institutions
and exports a structured CSV tracker.

Usage:
    python scripts/job_scanner/cli.py
    python scripts/job_scanner/cli.py --output ~/Desktop/job_tracker.csv
    python scripts/job_scanner/cli.py --merge existing_tracker.csv
    python scripts/job_scanner/cli.py --dirs ~/Documents ~/Dropbox --no-email
    python scripts/job_scanner/cli.py --strict  # only application-related docs
    python scripts/job_scanner/cli.py --days 180  # last 6 months only

Run with --help for all options.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Allow running as `python scripts/job_scanner/cli.py` from project root
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.job_scanner.scanner import run_scan, get_default_scan_dirs
from scripts.job_scanner.csv_export import export_csv, merge_with_tracker
from scripts.job_scanner.summary import generate_summary
from scripts.job_scanner.firms import get_firm_count
from scripts.job_scanner.document_parser import get_missing_deps


def main():
    parser = argparse.ArgumentParser(
        description="Scan local files and emails for job application data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dirs", nargs="+", type=str, default=None,
        help="Directories to scan (default: Documents, Downloads, Desktop, cloud sync folders)",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output CSV path (default: ./job_scan_results_YYYYMMDD.csv)",
    )
    parser.add_argument(
        "--merge", "-m", type=str, default=None,
        help="Path to existing tracker CSV to merge with (avoids duplicating known firms)",
    )
    parser.add_argument(
        "--no-email", action="store_true",
        help="Skip email store scanning",
    )
    parser.add_argument(
        "--email-paths", nargs="+", type=str, default=None,
        help="Additional paths to .eml or .mbox files to scan",
    )
    parser.add_argument(
        "--days", type=int, default=365,
        help="Only look at files modified within this many days (default: 365)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Only include documents containing application-related keywords",
    )
    parser.add_argument(
        "--summary", "-s", type=str, default=None,
        help="Path to write markdown summary report (default: alongside CSV)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--list-firms", action="store_true",
        help="Print the full list of firms being searched and exit",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("job_scanner")

    # --list-firms: print and exit
    if args.list_firms:
        from scripts.job_scanner.firms import get_all_firms
        firms = get_all_firms()
        print(f"\n{'='*70}")
        print(f"  Job Scanner — {len(firms)} firms in search list")
        print(f"{'='*70}\n")
        current_cat = None
        for name, cat, aliases in firms:
            if cat != current_cat:
                print(f"\n  --- {cat} ---")
                current_cat = cat
            alias_str = f"  (aliases: {', '.join(aliases)})" if aliases else ""
            print(f"    {name}{alias_str}")
        print()
        return

    # Check dependencies
    missing = get_missing_deps()
    if missing:
        print(f"\n  Optional dependencies not installed: {', '.join(missing)}")
        print(f"  Install them for better coverage: pip install {' '.join(missing)}")
        print()

    # Resolve directories
    if args.dirs:
        directories = [Path(d).expanduser().resolve() for d in args.dirs]
        missing_dirs = [d for d in directories if not d.is_dir()]
        if missing_dirs:
            for d in missing_dirs:
                log.warning("Directory not found: %s", d)
            directories = [d for d in directories if d.is_dir()]
    else:
        directories = get_default_scan_dirs()

    if not directories and not (not args.no_email):
        log.error("No valid directories to scan and email scanning is disabled. Nothing to do.")
        sys.exit(1)

    # Print scan plan
    print(f"\n{'='*70}")
    print(f"  Job Application Scanner")
    print(f"{'='*70}")
    print(f"  Firms in search list:  {get_firm_count()}")
    print(f"  Time window:           last {args.days} days")
    print(f"  Directories to scan:   {len(directories)}")
    for d in directories:
        print(f"    - {d}")
    print(f"  Scan emails:           {'yes' if not args.no_email else 'no'}")
    print(f"  Strict mode:           {'yes' if args.strict else 'no'}")
    if args.merge:
        print(f"  Merge with tracker:    {args.merge}")
    print(f"{'='*70}\n")

    # Run scan
    matches = run_scan(
        directories=directories,
        scan_emails=not args.no_email,
        extra_email_paths=args.email_paths,
        since_days=args.days,
        require_application_keyword=args.strict,
    )

    if not matches:
        print("\n  No firm references found in scanned files/emails.")
        print("  Try running without --strict, or expanding --dirs / --days.\n")
        return

    # Determine output paths
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    if args.output:
        csv_path = args.output
    else:
        csv_path = f"job_scan_results_{timestamp}.csv"

    summary_path = args.summary
    if summary_path is None:
        summary_path = str(Path(csv_path).with_suffix(".md"))

    # Export or merge
    existing_count = 0
    new_count = 0

    if args.merge:
        out, existing_count, new_count = merge_with_tracker(
            matches, args.merge, csv_path,
        )
        print(f"\n  Merged: {existing_count} existing + {new_count} new → {out}")
    else:
        out = export_csv(matches, csv_path)
        new_count = len(matches)
        print(f"\n  Exported {len(matches)} rows → {out}")

    # Generate summary
    report = generate_summary(
        matches,
        existing_count=existing_count,
        new_count=new_count,
        output_path=summary_path,
    )

    print(f"  Summary report → {summary_path}")
    print()

    # Print summary to terminal
    print(report)


if __name__ == "__main__":
    main()

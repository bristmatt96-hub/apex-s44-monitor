"""
Summary report generator — produces a human-readable markdown summary
with totals, timeline, category breakdown, and gaps to fill.
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .scanner import Match
from .firms import get_all_firms, get_firm_count

logger = logging.getLogger(__name__)


def generate_summary(
    matches: list[Match],
    existing_count: int = 0,
    new_count: int = 0,
    output_path: str | None = None,
) -> str:
    """
    Generate a markdown summary report.

    Args:
        matches: All Match objects from the scan
        existing_count: Number of rows from existing tracker (if merged)
        new_count: Number of new rows added (if merged)
        output_path: Optional path to write the report to

    Returns:
        The report as a string
    """
    lines: list[str] = []

    lines.append("# Job Application Scanner — Summary Report")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # ── Totals ────────────────────────────────────────────────────────────
    unique_firms = set(m.firm_name for m in matches)
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- **Unique firms found:** {len(unique_firms)}")
    lines.append(f"- **Total references:** {len(matches)}")
    lines.append(f"- **Firms in search list:** {get_firm_count()}")
    if existing_count or new_count:
        lines.append(f"- **Existing tracker rows:** {existing_count}")
        lines.append(f"- **New rows added:** {new_count}")
    lines.append("")

    # ── By Category ───────────────────────────────────────────────────────
    cat_counter: Counter[str] = Counter()
    for m in matches:
        cat_counter[m.firm_category] += 1

    lines.append("## Firms by Category")
    lines.append("")
    lines.append("| Category | Firms Found | References |")
    lines.append("|----------|-------------|------------|")

    cat_firms: dict[str, set[str]] = defaultdict(set)
    for m in matches:
        cat_firms[m.firm_category].add(m.firm_name)

    for cat in sorted(cat_firms.keys()):
        lines.append(f"| {cat} | {len(cat_firms[cat])} | {cat_counter[cat]} |")
    lines.append("")

    # ── By Status ─────────────────────────────────────────────────────────
    status_counter: Counter[str] = Counter()
    for m in matches:
        status_counter[m.status] += 1

    lines.append("## Application Status Breakdown")
    lines.append("")
    for status, count in status_counter.most_common():
        lines.append(f"- **{status}:** {count}")
    lines.append("")

    # ── By Source Type ────────────────────────────────────────────────────
    source_counter: Counter[str] = Counter()
    for m in matches:
        source_counter[m.source_type] += 1

    lines.append("## Source Breakdown")
    lines.append("")
    for src, count in source_counter.most_common():
        lines.append(f"- **{src}:** {count}")
    lines.append("")

    # ── Timeline ──────────────────────────────────────────────────────────
    dated = [m for m in matches if m.date_found]
    if dated:
        dates = sorted(set(m.date_found for m in dated))
        earliest = dates[0]
        latest = dates[-1]

        lines.append("## Timeline")
        lines.append("")
        lines.append(f"- **Earliest activity:** {earliest}")
        lines.append(f"- **Latest activity:** {latest}")
        lines.append("")

        # Monthly breakdown
        monthly: Counter[str] = Counter()
        for m in dated:
            ym = m.date_found[:7]  # YYYY-MM
            monthly[ym] += 1

        lines.append("### Monthly Activity")
        lines.append("")
        lines.append("| Month | References |")
        lines.append("|-------|------------|")
        for ym in sorted(monthly.keys()):
            lines.append(f"| {ym} | {monthly[ym]} |")
        lines.append("")

    # ── Firm Detail Table ─────────────────────────────────────────────────
    lines.append("## Firms Found")
    lines.append("")
    lines.append("| Firm | Category | Status | Date | Source | Document Type |")
    lines.append("|------|----------|--------|------|--------|---------------|")

    # Dedupe to one row per firm (most recent)
    best_per_firm: dict[str, Match] = {}
    for m in matches:
        existing = best_per_firm.get(m.firm_name)
        if existing is None or (m.date_found or "") > (existing.date_found or ""):
            best_per_firm[m.firm_name] = m

    for firm in sorted(best_per_firm.keys()):
        m = best_per_firm[firm]
        lines.append(
            f"| {m.firm_name} | {m.firm_category} | {m.status} "
            f"| {m.date_found} | {m.source_type} | {m.document_type} |"
        )
    lines.append("")

    # ── Gaps / Firms NOT found ────────────────────────────────────────────
    all_firms = get_all_firms()
    found_lower = {f.lower() for f in unique_firms}
    not_found = [
        (name, cat) for name, cat, _ in all_firms
        if name.lower() not in found_lower
    ]

    if not_found:
        lines.append("## Gaps — Firms NOT Found in Any Document or Email")
        lines.append("")
        lines.append(
            "These firms from the search list had zero matches. "
            "You may want to manually check if you have any history with them."
        )
        lines.append("")

        gap_by_cat: dict[str, list[str]] = defaultdict(list)
        for name, cat in not_found:
            gap_by_cat[cat].append(name)

        for cat in sorted(gap_by_cat.keys()):
            firms_list = ", ".join(sorted(gap_by_cat[cat]))
            lines.append(f"- **{cat}** ({len(gap_by_cat[cat])}): {firms_list}")
        lines.append("")

    # ── Manual follow-up checklist ────────────────────────────────────────
    lines.append("## Manual Follow-up Checklist")
    lines.append("")
    lines.append("- [ ] Review 'Unknown' status entries and update with actual status")
    lines.append("- [ ] Add role/position details where missing")
    lines.append("- [ ] Fill in contact person names for email-sourced entries")
    lines.append("- [ ] Check dates — scanner uses file modification time, not application date")
    lines.append("- [ ] Verify any firms marked as found in non-application documents")
    lines.append("- [ ] Cross-reference with LinkedIn application history")
    lines.append("- [ ] Check any recruitment agency portals (Hays, Robert Half, etc.)")
    lines.append("")

    report = "\n".join(lines)

    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
        logger.info("Summary report written to %s", output_path)

    return report

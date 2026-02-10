"""
Core scanner — orchestrates folder scanning, document parsing, email parsing,
firm matching, and result assembly.
"""

import logging
import os
import platform
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

from .document_parser import (
    SUPPORTED_EXTENSIONS,
    APPLICATION_KEYWORDS,
    extract_text,
    is_application_document,
)
from .email_parser import EmailRecord, discover_email_stores, parse_all_stores
from .firms import build_search_index, get_all_firms

logger = logging.getLogger(__name__)


@dataclass
class Match:
    """A single discovered reference to a firm in a document or email."""
    firm_name: str = ""
    firm_category: str = ""
    role: str = ""
    status: str = "Unknown"
    date_found: str = ""
    date_applied: str = ""
    source: str = ""          # human-readable source description
    source_type: str = ""     # Document / Email Sent / Email Received
    document_type: str = ""   # CV / Cover Letter / Pitch Doc / Business Plan / Email
    contact_person: str = ""
    contact_email: str = ""
    notes: str = ""
    file_path: str = ""
    snippet: str = ""         # context around the match


# ── Default scan directories ──────────────────────────────────────────────────

def get_default_scan_dirs() -> list[Path]:
    """Return a list of standard user folders to scan."""
    home = Path.home()
    sys = platform.system()

    dirs = [
        home / "Documents",
        home / "Downloads",
        home / "Desktop",
    ]

    # Cloud sync folders
    cloud_dirs = [
        home / "Dropbox",
        home / "OneDrive",
        home / "OneDrive - Personal",
        home / "Google Drive",
        home / "iCloud Drive",
        home / "Box",
        home / "pCloud Drive",
    ]
    if sys == "Darwin":
        cloud_dirs.append(
            home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        )

    dirs.extend(cloud_dirs)
    return [d for d in dirs if d.is_dir()]


# ── File scanning ─────────────────────────────────────────────────────────────

def scan_files(
    directories: list[Path],
    since_days: int = 365,
    extensions: set[str] | None = None,
) -> Generator[Path, None, None]:
    """
    Recursively yield files matching the extension filter that were
    modified within the time window.
    """
    if extensions is None:
        extensions = SUPPORTED_EXTENSIONS

    cutoff = datetime.now().timestamp() - (since_days * 86400)

    for directory in directories:
        logger.info("Scanning directory: %s", directory)
        try:
            for filepath in directory.rglob("*"):
                if not filepath.is_file():
                    continue
                if filepath.suffix.lower() not in extensions:
                    continue
                try:
                    if filepath.stat().st_mtime < cutoff:
                        continue
                except OSError:
                    continue
                # Skip hidden directories and common noise
                parts = filepath.parts
                if any(p.startswith(".") for p in parts[len(directory.parts):]):
                    continue
                if any(skip in str(filepath).lower() for skip in (
                    "node_modules", "__pycache__", ".git", "site-packages",
                    "venv", ".venv", "cache",
                )):
                    continue
                yield filepath
        except PermissionError:
            logger.debug("Permission denied: %s", directory)


# ── Matching engine ───────────────────────────────────────────────────────────

def _find_firms_in_text(text: str, search_index: dict) -> list[tuple[str, str, str]]:
    """
    Search text for firm name references.
    Returns list of (canonical_name, category, snippet).
    """
    found = {}
    text_lower = text.lower()

    for term, (canonical, category) in search_index.items():
        if canonical in found:
            continue
        # Use word-boundary matching to reduce false positives
        # For short terms (<=3 chars) require exact word match
        if len(term) <= 3:
            pattern = r"\b" + re.escape(term) + r"\b"
            match = re.search(pattern, text_lower)
        else:
            idx = text_lower.find(term)
            match = idx >= 0

            if match and isinstance(match, bool):
                idx = text_lower.find(term)
                # Create a pseudo match position
                match = idx

        if match:
            if isinstance(match, re.Match):
                pos = match.start()
            elif isinstance(match, int):
                pos = match
            else:
                pos = text_lower.find(term)

            # Extract snippet (100 chars either side)
            start = max(0, pos - 100)
            end = min(len(text), pos + len(term) + 100)
            snippet = text[start:end].replace("\n", " ").strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."

            found[canonical] = (canonical, category, snippet)

    return list(found.values())


def _guess_document_type(filepath: Path, text: str) -> str:
    """Heuristic classification of document type."""
    name = filepath.stem.lower()
    text_lower = text[:2000].lower() if text else ""

    if any(kw in name for kw in ("cv", "resume", "résumé", "curriculum")):
        return "CV"
    if any(kw in name for kw in ("cover", "covering", "letter")):
        return "Cover Letter"
    if any(kw in name for kw in ("pitch", "deck", "presentation")):
        return "Pitch Doc"
    if any(kw in name for kw in ("business_plan", "businessplan", "bplan")):
        return "Business Plan"

    # Check content
    if "curriculum vitae" in text_lower or "work experience" in text_lower:
        return "CV"
    if "dear" in text_lower[:500] and any(
        kw in text_lower for kw in ("application", "position", "role", "vacancy")
    ):
        return "Cover Letter"
    if "investment thesis" in text_lower or "pitch" in text_lower[:500]:
        return "Pitch Doc"
    if "business plan" in text_lower[:500] or "market opportunity" in text_lower:
        return "Business Plan"

    return "Document"


def _guess_status(text: str, direction: str = "") -> str:
    """Try to infer application status from text content."""
    lower = text.lower()
    if any(kw in lower for kw in ("offer letter", "we are pleased to offer", "compensation package")):
        return "Offer"
    if any(kw in lower for kw in ("unfortunately", "regret to inform", "not been successful", "not progressing")):
        return "Rejected"
    if any(kw in lower for kw in ("interview", "assessment", "next stage", "meet the team")):
        return "Interview"
    if any(kw in lower for kw in ("applied", "application received", "thank you for applying", "submission")):
        return "Applied"
    if direction == "sent":
        return "Applied"
    return "Unknown"


def _extract_contact_email(text: str) -> str:
    """Pull the first email address from text."""
    match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else ""


def _extract_role(text: str) -> str:
    """Try to extract a job title / role from text."""
    patterns = [
        r"(?:position|role|vacancy|job title)[:\s]*([^\n,]{5,60})",
        r"(?:applying for|application for|interest in)[:\s]*(?:the\s+)?([^\n,]{5,60})",
        r"(?:analyst|associate|trader|developer|engineer|manager|director|vp|vice president|intern)"
        r"[^\n,]{0,40}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            role = match.group(1) if match.lastindex else match.group(0)
            return role.strip()[:80]
    return ""


# ── Main scan orchestrator ────────────────────────────────────────────────────

def run_scan(
    directories: list[Path] | None = None,
    scan_emails: bool = True,
    extra_email_paths: list[str] | None = None,
    since_days: int = 365,
    require_application_keyword: bool = False,
) -> list[Match]:
    """
    Run the full scan and return a list of Match objects.

    Args:
        directories: Folders to scan (defaults to auto-detected user folders)
        scan_emails: Whether to scan email stores
        extra_email_paths: Additional paths to .eml/.mbox files
        since_days: Only look at files modified within this many days
        require_application_keyword: If True, only include documents that
            contain application-related keywords (reduces noise)
    """
    if directories is None:
        directories = get_default_scan_dirs()

    search_index = build_search_index()
    matches: list[Match] = []
    seen_keys: set[str] = set()  # dedupe: (firm, file_path)

    # ── Phase 1: Scan documents ───────────────────────────────────────────
    logger.info("Phase 1: Scanning %d directories for documents...", len(directories))
    file_count = 0
    match_count = 0

    for filepath in scan_files(directories, since_days):
        file_count += 1
        if file_count % 100 == 0:
            logger.info("  ...scanned %d files, found %d matches so far", file_count, match_count)

        text = extract_text(str(filepath))
        if not text or len(text.strip()) < 50:
            continue

        if require_application_keyword and not is_application_document(text):
            continue

        firm_hits = _find_firms_in_text(text, search_index)
        if not firm_hits:
            continue

        doc_type = _guess_document_type(filepath, text)
        status = _guess_status(text)
        role = _extract_role(text)
        contact = _extract_contact_email(text)

        try:
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
            date_str = mtime.strftime("%Y-%m-%d")
        except Exception:
            date_str = ""

        for firm_name, category, snippet in firm_hits:
            key = (firm_name, str(filepath))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            match_count += 1

            matches.append(Match(
                firm_name=firm_name,
                firm_category=category,
                role=role,
                status=status,
                date_found=date_str,
                source=filepath.name,
                source_type="Document",
                document_type=doc_type,
                contact_email=contact,
                notes=f"Found in {doc_type.lower()}: {filepath.name}",
                file_path=str(filepath),
                snippet=snippet,
            ))

    logger.info("Phase 1 complete: scanned %d files, found %d firm references", file_count, match_count)

    # ── Phase 2: Scan emails ──────────────────────────────────────────────
    if scan_emails:
        logger.info("Phase 2: Scanning email stores...")
        email_count = 0
        email_match_count = 0

        for record in parse_all_stores(
            extra_paths=extra_email_paths,
            since_days=since_days,
        ):
            email_count += 1
            if email_count % 200 == 0:
                logger.info("  ...processed %d emails, found %d matches", email_count, email_match_count)

            # Combine subject + body for searching
            full_text = f"{record.subject}\n{record.sender}\n{record.recipients}\n{record.body}"

            if require_application_keyword:
                if not any(kw in full_text.lower() for kw in APPLICATION_KEYWORDS):
                    continue

            firm_hits = _find_firms_in_text(full_text, search_index)
            if not firm_hits:
                continue

            direction_label = (
                "Email Sent" if record.direction == "sent" else "Email Received"
            )
            status = _guess_status(full_text, record.direction)
            role = _extract_role(full_text)

            date_str = ""
            if record.date:
                date_str = record.date.strftime("%Y-%m-%d")

            # Extract contact from the "other" side
            if record.direction == "sent":
                contact = record.recipients.split(",")[0].strip() if record.recipients else ""
            else:
                contact = record.sender

            contact_email = _extract_contact_email(contact)

            for firm_name, category, snippet in firm_hits:
                key = (firm_name, record.source_path, record.subject)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                email_match_count += 1

                matches.append(Match(
                    firm_name=firm_name,
                    firm_category=category,
                    role=role,
                    status=status,
                    date_found=date_str,
                    date_applied=date_str if record.direction == "sent" else "",
                    source=f"[{record.mail_client}] {record.subject}",
                    source_type=direction_label,
                    document_type="Email",
                    contact_person=contact if "@" not in contact else "",
                    contact_email=contact_email,
                    notes=f"Via {record.mail_client}: {record.subject[:80]}",
                    file_path=record.source_path,
                    snippet=snippet,
                ))

        logger.info("Phase 2 complete: processed %d emails, found %d firm references", email_count, email_match_count)

    # Sort by date (most recent first), then firm name
    matches.sort(key=lambda m: (m.date_found or "0000", m.firm_name), reverse=True)

    return matches

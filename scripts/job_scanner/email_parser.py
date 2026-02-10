"""
Email store parser — extracts sent/received emails from local mail clients.

Supported:
  - Apple Mail (~/Library/Mail/)          — .emlx files
  - Thunderbird (~/.thunderbird/)         — mbox files
  - Outlook for Mac (~/Library/Group Containers/UBF8T346G9.Office/Outlook/) — .olk15 / .olk16
  - Generic .eml / .mbox files anywhere on disk

Each parser yields EmailRecord namedtuples for downstream matching.
"""

import email
import email.policy
import logging
import mailbox
import os
import platform
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


@dataclass
class EmailRecord:
    subject: str = ""
    sender: str = ""
    recipients: str = ""
    date: datetime | None = None
    body: str = ""
    source_path: str = ""
    direction: str = "unknown"  # "sent" or "received"
    mail_client: str = "unknown"


# ── Public API ────────────────────────────────────────────────────────────────

def discover_email_stores() -> dict[str, list[Path]]:
    """
    Auto-discover local email stores.  Returns dict of
    client_name → list of store root paths.
    """
    stores: dict[str, list[Path]] = {}
    home = Path.home()
    sys = platform.system()

    # Apple Mail (macOS only)
    if sys == "Darwin":
        apple_mail = home / "Library" / "Mail"
        if apple_mail.is_dir():
            stores.setdefault("Apple Mail", []).append(apple_mail)

    # Thunderbird (cross-platform)
    if sys == "Darwin":
        tb_root = home / "Library" / "Thunderbird" / "Profiles"
    elif sys == "Linux":
        tb_root = home / ".thunderbird"
    elif sys == "Windows":
        tb_root = home / "AppData" / "Roaming" / "Thunderbird" / "Profiles"
    else:
        tb_root = None

    if tb_root and tb_root.is_dir():
        stores.setdefault("Thunderbird", []).append(tb_root)

    # Outlook for Mac
    if sys == "Darwin":
        outlook_root = (
            home / "Library" / "Group Containers"
            / "UBF8T346G9.Office" / "Outlook"
            / "Outlook 15 Profiles"
        )
        if outlook_root.is_dir():
            stores.setdefault("Outlook", []).append(outlook_root)

    return stores


def parse_all_stores(
    stores: dict[str, list[Path]] | None = None,
    extra_paths: list[str] | None = None,
    since_days: int = 365,
) -> Generator[EmailRecord, None, None]:
    """
    Iterate over all discovered (or explicitly provided) email stores
    and yield EmailRecord objects for messages within the time window.
    """
    cutoff = datetime.now(timezone.utc).replace(
        tzinfo=None
    ) - __import__("datetime").timedelta(days=since_days)

    if stores is None:
        stores = discover_email_stores()

    for client, roots in stores.items():
        for root in roots:
            logger.info("Scanning %s store: %s", client, root)
            if client == "Apple Mail":
                yield from _parse_apple_mail(root, cutoff)
            elif client == "Thunderbird":
                yield from _parse_thunderbird(root, cutoff)
            elif client == "Outlook":
                yield from _parse_outlook(root, cutoff)

    # Extra user-supplied paths (loose .eml or .mbox files)
    if extra_paths:
        for p in extra_paths:
            path = Path(p)
            if path.is_file():
                if path.suffix.lower() == ".eml":
                    rec = _parse_eml_file(path)
                    if rec and (rec.date is None or rec.date.replace(tzinfo=None) >= cutoff):
                        yield rec
                elif path.suffix.lower() in (".mbox", ""):
                    yield from _parse_mbox_file(path, cutoff)
            elif path.is_dir():
                # Scan directory for .eml files
                for eml in path.rglob("*.eml"):
                    rec = _parse_eml_file(eml)
                    if rec and (rec.date is None or rec.date.replace(tzinfo=None) >= cutoff):
                        yield rec


# ── Apple Mail (.emlx) ────────────────────────────────────────────────────────

def _parse_apple_mail(root: Path, cutoff: datetime) -> Generator[EmailRecord, None, None]:
    """Parse Apple Mail's .emlx files."""
    for emlx_path in root.rglob("*.emlx"):
        try:
            # .emlx format: first line is byte count, then RFC 822 message, then Apple plist
            with open(emlx_path, "rb") as f:
                first_line = f.readline()
                try:
                    byte_count = int(first_line.strip())
                except ValueError:
                    # Not a valid emlx
                    continue
                raw = f.read(byte_count)

            msg = email.message_from_bytes(raw, policy=email.policy.default)
            rec = _msg_to_record(msg, str(emlx_path), "Apple Mail")

            # Determine direction from folder path
            path_lower = str(emlx_path).lower()
            if "sent" in path_lower:
                rec.direction = "sent"
            elif any(x in path_lower for x in ("inbox", "archive", "all mail")):
                rec.direction = "received"

            if rec.date is None or rec.date.replace(tzinfo=None) >= cutoff:
                yield rec

        except Exception as e:
            logger.debug("Skipping %s: %s", emlx_path, e)


# ── Thunderbird (mbox) ───────────────────────────────────────────────────────

def _parse_thunderbird(root: Path, cutoff: datetime) -> Generator[EmailRecord, None, None]:
    """Scan Thunderbird profile dirs for mbox files."""
    # Thunderbird stores mbox as extensionless files alongside .msf index files
    for msf in root.rglob("*.msf"):
        mbox_path = msf.with_suffix("")
        if mbox_path.is_file():
            yield from _parse_mbox_file(mbox_path, cutoff, client="Thunderbird")

    # Also look for explicit mbox files
    for mbox_file in root.rglob("*.mbox"):
        yield from _parse_mbox_file(mbox_file, cutoff, client="Thunderbird")


def _parse_mbox_file(
    path: Path, cutoff: datetime, client: str = "Thunderbird"
) -> Generator[EmailRecord, None, None]:
    try:
        mbox = mailbox.mbox(str(path))
        path_lower = str(path).lower()
        for msg in mbox:
            rec = _msg_to_record(msg, str(path), client)
            if "sent" in path_lower:
                rec.direction = "sent"
            elif "inbox" in path_lower:
                rec.direction = "received"
            if rec.date is None or rec.date.replace(tzinfo=None) >= cutoff:
                yield rec
    except Exception as e:
        logger.debug("Cannot read mbox %s: %s", path, e)


# ── Outlook for Mac ──────────────────────────────────────────────────────────

def _parse_outlook(root: Path, cutoff: datetime) -> Generator[EmailRecord, None, None]:
    """
    Outlook for Mac 2016+ uses .olk15Message / .olk16Message files.
    These are proprietary but we can attempt basic extraction.
    Fallback: scan for any .eml exports in the Outlook directory.
    """
    # Try .eml files first (user may have exported)
    for eml in root.rglob("*.eml"):
        rec = _parse_eml_file(eml)
        if rec:
            rec.mail_client = "Outlook"
            if rec.date is None or rec.date.replace(tzinfo=None) >= cutoff:
                yield rec

    # .olk15Message / .olk16Message — best-effort extraction
    for olk_file in root.rglob("*.olk*Message"):
        try:
            with open(olk_file, "rb") as f:
                raw = f.read()
            # These files contain embedded RFC 822 headers; try to find them
            text = raw.decode("utf-8", errors="replace")
            rec = EmailRecord(
                source_path=str(olk_file),
                mail_client="Outlook",
                body=text[:5000],
            )
            # Try to extract subject
            subj_match = re.search(r"Subject:\s*(.+?)(?:\r?\n\S|\r?\n\r?\n)", text)
            if subj_match:
                rec.subject = subj_match.group(1).strip()
            from_match = re.search(r"From:\s*(.+?)(?:\r?\n\S|\r?\n\r?\n)", text)
            if from_match:
                rec.sender = from_match.group(1).strip()
            date_match = re.search(r"Date:\s*(.+?)(?:\r?\n)", text)
            if date_match:
                try:
                    rec.date = parsedate_to_datetime(date_match.group(1).strip())
                except Exception:
                    pass

            path_lower = str(olk_file).lower()
            if "sent" in path_lower:
                rec.direction = "sent"
            elif "inbox" in path_lower:
                rec.direction = "received"

            if rec.date is None or rec.date.replace(tzinfo=None) >= cutoff:
                yield rec

        except Exception as e:
            logger.debug("Skipping Outlook file %s: %s", olk_file, e)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_eml_file(path: Path) -> EmailRecord | None:
    try:
        with open(path, "rb") as f:
            msg = email.message_from_bytes(f.read(), policy=email.policy.default)
        return _msg_to_record(msg, str(path), "EML")
    except Exception as e:
        logger.debug("Cannot parse .eml %s: %s", path, e)
        return None


def _msg_to_record(msg, source_path: str, client: str) -> EmailRecord:
    """Convert an email.message.Message to an EmailRecord."""
    rec = EmailRecord(source_path=source_path, mail_client=client)

    rec.subject = str(msg.get("Subject", ""))
    rec.sender = str(msg.get("From", ""))
    rec.recipients = ", ".join(
        filter(None, [
            str(msg.get("To", "")),
            str(msg.get("Cc", "")),
        ])
    )

    date_str = msg.get("Date")
    if date_str:
        try:
            rec.date = parsedate_to_datetime(str(date_str))
        except Exception:
            pass

    # Extract body text
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_content()
                if isinstance(payload, str):
                    body_parts.append(payload)
    else:
        payload = msg.get_content()
        if isinstance(payload, str):
            body_parts.append(payload)

    rec.body = "\n".join(body_parts)[:10000]  # cap at 10k chars
    return rec

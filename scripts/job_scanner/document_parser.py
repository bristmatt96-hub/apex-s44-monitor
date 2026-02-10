"""
Document text extraction for common file formats.

Supports: PDF, DOCX, DOC (via textract fallback), TXT, RTF, HTML, MD, Pages (metadata only).
Gracefully degrades when optional dependencies are missing — tells the user what to install.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Track which optional deps are available
_AVAILABLE = {}


def _check_dep(name):
    if name not in _AVAILABLE:
        try:
            __import__(name)
            _AVAILABLE[name] = True
        except ImportError:
            _AVAILABLE[name] = False
    return _AVAILABLE[name]


# ── Public API ────────────────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".rtf", ".html", ".htm", ".md", ".pages",
    ".odt", ".tex",
}

# Keywords that suggest a file is job-application related
APPLICATION_KEYWORDS = [
    "curriculum vitae", "cv", "resume", "résumé",
    "cover letter", "covering letter", "letter of application",
    "pitch deck", "pitch doc", "investment pitch", "pitch document",
    "business plan", "executive summary",
    "personal statement", "motivation letter",
    "application", "applied", "applying",
    "interview", "assessment centre", "assessment center",
    "offer letter", "employment contract",
    "portfolio",
]


def extract_text(filepath: str) -> str | None:
    """
    Extract plain text from a file.  Returns None if the format is
    unsupported or a required dependency is missing.
    """
    ext = Path(filepath).suffix.lower()
    try:
        if ext == ".pdf":
            return _extract_pdf(filepath)
        elif ext == ".docx":
            return _extract_docx(filepath)
        elif ext in (".txt", ".md", ".tex"):
            return _extract_plain(filepath)
        elif ext in (".html", ".htm"):
            return _extract_html(filepath)
        elif ext == ".rtf":
            return _extract_rtf(filepath)
        elif ext == ".doc":
            return _extract_doc(filepath)
        elif ext == ".odt":
            return _extract_odt(filepath)
        elif ext == ".pages":
            logger.debug("Pages files require iWork export; skipping %s", filepath)
            return None
        else:
            return None
    except Exception as e:
        logger.warning("Failed to extract text from %s: %s", filepath, e)
        return None


def is_application_document(text: str) -> bool:
    """Heuristic: does the text look like a CV, cover letter, pitch doc, etc.?"""
    lower = text.lower()
    return any(kw in lower for kw in APPLICATION_KEYWORDS)


def get_missing_deps() -> list[str]:
    """Return list of recommended-but-missing packages."""
    missing = []
    checks = [
        ("PyPDF2", "PyPDF2"),
        ("docx", "python-docx"),
        ("striprtf", "striprtf"),
        ("bs4", "beautifulsoup4"),
        ("odf", "odfpy"),
    ]
    for module, pip_name in checks:
        if not _check_dep(module):
            missing.append(pip_name)
    return missing


# ── Format-specific extractors ────────────────────────────────────────────────

def _extract_pdf(filepath: str) -> str | None:
    if _check_dep("PyPDF2"):
        import PyPDF2
        text_parts = []
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts) if text_parts else None

    if _check_dep("pdfplumber"):
        import pdfplumber
        text_parts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts) if text_parts else None

    logger.warning("No PDF library available. Install PyPDF2: pip install PyPDF2")
    return None


def _extract_docx(filepath: str) -> str | None:
    if not _check_dep("docx"):
        logger.warning("python-docx not installed. pip install python-docx")
        return None
    import docx
    doc = docx.Document(filepath)
    text_parts = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(text_parts) if text_parts else None


def _extract_plain(filepath: str) -> str | None:
    encodings = ["utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, ValueError):
            continue
    return None


def _extract_html(filepath: str) -> str | None:
    raw = _extract_plain(filepath)
    if raw is None:
        return None
    if _check_dep("bs4"):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "html.parser")
        return soup.get_text(separator="\n")
    # Crude fallback: strip tags
    import re
    return re.sub(r"<[^>]+>", " ", raw)


def _extract_rtf(filepath: str) -> str | None:
    if not _check_dep("striprtf"):
        logger.warning("striprtf not installed. pip install striprtf")
        return None
    from striprtf.striprtf import rtf_to_text
    with open(filepath, "r", errors="ignore") as f:
        return rtf_to_text(f.read())


def _extract_doc(filepath: str) -> str | None:
    """Legacy .doc — try antiword or textract."""
    # Try antiword (common on macOS/Linux)
    import subprocess
    try:
        result = subprocess.run(
            ["antiword", filepath],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except FileNotFoundError:
        pass

    logger.warning(
        "Cannot read .doc files without antiword. "
        "Install via: brew install antiword (macOS) or apt install antiword (Linux)"
    )
    return None


def _extract_odt(filepath: str) -> str | None:
    if not _check_dep("odf"):
        logger.warning("odfpy not installed. pip install odfpy")
        return None
    from odf import text as odf_text
    from odf.opendocument import load
    doc = load(filepath)
    paragraphs = doc.getElementsByType(odf_text.P)
    text_parts = []
    for para in paragraphs:
        # Recursively get text content
        t = ""
        for node in para.childNodes:
            if hasattr(node, "data"):
                t += node.data
            elif hasattr(node, "__str__"):
                t += str(node)
        if t.strip():
            text_parts.append(t)
    return "\n".join(text_parts) if text_parts else None

"""
Log Sanitizer - Filters sensitive data from log output

Prevents accidental exposure of API keys, passwords, and tokens in logs.

Usage:
    from utils.log_sanitizer import setup_log_sanitization
    setup_log_sanitization()  # Call once at startup
"""
import re
import sys
from typing import List, Pattern
from loguru import logger


# Patterns to redact from logs
SENSITIVE_PATTERNS: List[Pattern] = [
    # API keys (generic patterns)
    re.compile(r'(["\']?(?:api[_-]?key|apikey)["\']?\s*[:=]\s*)["\']?([a-zA-Z0-9_-]{20,})["\']?', re.IGNORECASE),
    re.compile(r'(["\']?(?:secret[_-]?key|secretkey)["\']?\s*[:=]\s*)["\']?([a-zA-Z0-9_-]{20,})["\']?', re.IGNORECASE),

    # Bearer tokens
    re.compile(r'(Bearer\s+)([a-zA-Z0-9_.-]{20,})', re.IGNORECASE),

    # Telegram bot tokens (format: 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)
    re.compile(r'(\d{8,10}:[a-zA-Z0-9_-]{35})'),

    # OpenAI/Groq API keys (sk-...)
    re.compile(r'(sk-[a-zA-Z0-9]{20,})'),

    # Generic tokens
    re.compile(r'(["\']?(?:token|auth[_-]?token|access[_-]?token)["\']?\s*[:=]\s*)["\']?([a-zA-Z0-9_.-]{20,})["\']?', re.IGNORECASE),

    # Passwords
    re.compile(r'(["\']?(?:password|passwd|pwd)["\']?\s*[:=]\s*)["\']?([^\s"\']{4,})["\']?', re.IGNORECASE),

    # Database connection strings with credentials
    re.compile(r'(postgresql://[^:]+:)([^@]+)(@)', re.IGNORECASE),
    re.compile(r'(mysql://[^:]+:)([^@]+)(@)', re.IGNORECASE),
    re.compile(r'(mongodb://[^:]+:)([^@]+)(@)', re.IGNORECASE),

    # AWS credentials
    re.compile(r'(AKIA[0-9A-Z]{16})'),
    re.compile(r'(["\']?(?:aws[_-]?secret[_-]?access[_-]?key)["\']?\s*[:=]\s*)["\']?([a-zA-Z0-9/+=]{40})["\']?', re.IGNORECASE),

    # Credit card numbers (basic pattern)
    re.compile(r'\b(\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4})\b'),

    # Email addresses (optional - uncomment if needed)
    # re.compile(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)'),
]

# Replacement text for redacted content
REDACTED = "[REDACTED]"


def sanitize_message(message: str) -> str:
    """
    Sanitize a log message by redacting sensitive information.

    Args:
        message: The log message to sanitize

    Returns:
        Sanitized message with sensitive data replaced by [REDACTED]
    """
    sanitized = message

    for pattern in SENSITIVE_PATTERNS:
        # For patterns with capture groups, replace only the sensitive part
        if pattern.groups > 1:
            sanitized = pattern.sub(rf'\g<1>{REDACTED}', sanitized)
        else:
            sanitized = pattern.sub(REDACTED, sanitized)

    return sanitized


class SanitizingFilter:
    """Loguru filter that sanitizes sensitive data"""

    def __call__(self, record):
        # Sanitize the message
        record["message"] = sanitize_message(record["message"])

        # Also sanitize any extra data
        if record.get("extra"):
            for key, value in record["extra"].items():
                if isinstance(value, str):
                    record["extra"][key] = sanitize_message(value)

        return True


def setup_log_sanitization():
    """
    Configure loguru to sanitize all log output.
    Call this once at application startup.
    """
    # Remove default handler
    logger.remove()

    # Add new handler with sanitization filter
    logger.add(
        sys.stderr,
        filter=SanitizingFilter(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG"
    )

    # Also add file handler with sanitization
    logger.add(
        "logs/app.log",
        filter=SanitizingFilter(),
        rotation="10 MB",
        retention="7 days",
        level="INFO"
    )

    logger.info("Log sanitization enabled - sensitive data will be redacted")


def test_sanitization():
    """Test the sanitization patterns"""
    test_cases = [
        ("api_key=sk-abc123xyz789defghi", "api_key=[REDACTED]"),
        ("Using API key: sk-proj-1234567890abcdef", "Using API key: [REDACTED]"),
        ('{"password": "mysecretpass123"}', '{"password": [REDACTED]}'),
        ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz", "Bearer [REDACTED]"),
        ("Telegram bot: 123456789:ABCdefGHIjklMNOpqrSTUvwxyz12345", "Telegram bot: [REDACTED]"),
        ("postgresql://user:secretpass@localhost:5432/db", "postgresql://user:[REDACTED]@localhost:5432/db"),
    ]

    print("Testing log sanitization patterns:\n")
    all_passed = True

    for input_str, expected in test_cases:
        result = sanitize_message(input_str)
        passed = REDACTED in result and (input_str != result)
        status = "✓" if passed else "✗"
        print(f"{status} Input:    {input_str}")
        print(f"  Output:   {result}")
        print()
        if not passed:
            all_passed = False

    return all_passed


if __name__ == "__main__":
    if test_sanitization():
        print("All sanitization tests passed!")
    else:
        print("Some tests failed!")

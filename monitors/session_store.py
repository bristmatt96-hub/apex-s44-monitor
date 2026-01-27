"""
Session Store - File-based persistence for Streamlit session state.

Solves the problem of session data (positions, transcripts, etc.) being lost
when you refresh the browser, restart Streamlit, or switch between devices
(e.g. Mac <-> Windows). Data is saved to JSON files in the sessions/ directory
which syncs via git.
"""

import json
import os
from datetime import datetime

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions")


def _ensure_dir():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def save_session_data(key: str, data) -> bool:
    """Save session data to a JSON file.

    Args:
        key: Identifier for the data (e.g. 'positions', 'transcript')
        data: Any JSON-serializable data
    Returns:
        True if saved successfully
    """
    _ensure_dir()
    filepath = os.path.join(SESSIONS_DIR, f"{key}.json")
    try:
        payload = {
            "key": key,
            "saved_at": datetime.now().isoformat(),
            "data": data,
        }
        with open(filepath, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        return True
    except Exception:
        return False


def load_session_data(key: str, default=None):
    """Load session data from a JSON file.

    Args:
        key: Identifier for the data
        default: Value to return if no saved data exists
    Returns:
        The saved data, or default if not found
    """
    filepath = os.path.join(SESSIONS_DIR, f"{key}.json")
    try:
        with open(filepath, "r") as f:
            payload = json.load(f)
        return payload.get("data", default)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def delete_session_data(key: str) -> bool:
    """Delete a saved session file."""
    filepath = os.path.join(SESSIONS_DIR, f"{key}.json")
    try:
        os.remove(filepath)
        return True
    except FileNotFoundError:
        return True
    except Exception:
        return False


def get_session_info(key: str) -> dict | None:
    """Get metadata about a saved session (when it was saved, etc.)."""
    filepath = os.path.join(SESSIONS_DIR, f"{key}.json")
    try:
        with open(filepath, "r") as f:
            payload = json.load(f)
        return {"key": key, "saved_at": payload.get("saved_at")}
    except (FileNotFoundError, json.JSONDecodeError):
        return None

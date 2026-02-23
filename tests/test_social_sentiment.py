"""Tests for social sentiment pre-filter."""
import pytest
import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub macrocosmos + anthropic before import
for mod in ["macrocosmos", "anthropic", "dotenv"]:
    if mod not in sys.modules:
        stub = ModuleType(mod)
        if mod == "dotenv":
            stub.load_dotenv = lambda **kw: None
        sys.modules[mod] = stub

from monitors.social_sentiment import NOISE_BLOCKLIST, ENTITY_NOISE


def test_noise_blocklist_exists_and_has_sports_terms():
    assert isinstance(NOISE_BLOCKLIST, list)
    assert len(NOISE_BLOCKLIST) >= 10
    # Must contain key sports terms
    blocklist_lower = [t.lower() for t in NOISE_BLOCKLIST]
    for term in ["grenadiers", "premier league", "cycling"]:
        assert term in blocklist_lower, f"Missing '{term}' from NOISE_BLOCKLIST"


def test_entity_noise_has_ineos():
    assert "INEOS" in ENTITY_NOISE
    ineos_lower = [t.lower() for t in ENTITY_NOISE["INEOS"]]
    assert "manchester united" in ineos_lower
    assert "grenadiers" in ineos_lower

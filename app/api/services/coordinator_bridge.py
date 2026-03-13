"""
Credit data service — replaces old trading coordinator bridge.

Provides access to snapshots, assessments, and cached analytics
for the API layer.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger


class CreditDataService:
    """
    Central data access layer for the API.
    Reads from snapshots and cached assessment results.
    """

    def __init__(self):
        self.snapshots_dir = Path("snapshots")
        self.data_dir = Path("data")
        self._snapshot_cache: Dict[str, dict] = {}

    def get_snapshot(self, name: str) -> Optional[dict]:
        """Load a credit snapshot by company name."""
        if name in self._snapshot_cache:
            return self._snapshot_cache[name]

        name_lower = name.lower()
        for f in self.snapshots_dir.glob("*.json"):
            if name_lower in f.stem.lower():
                with open(f) as fh:
                    data = json.load(fh)
                self._snapshot_cache[name] = data
                return data
        return None

    def get_all_snapshots(self) -> List[dict]:
        """Load all credit snapshots."""
        snapshots = []
        for f in sorted(self.snapshots_dir.glob("*.json")):
            try:
                with open(f) as fh:
                    snapshots.append(json.load(fh))
            except Exception as e:
                logger.warning(f"Failed to load snapshot {f}: {e}")
        return snapshots

    def get_universe_names(self) -> List[str]:
        """Return names from the XO S44 index."""
        xover_path = Path("indices/xover_s44.json")
        if not xover_path.exists():
            return []
        with open(xover_path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item.get("name", "") for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            names = []
            for sector, companies in data.get("sectors", {}).items():
                names.extend(companies)
            return names
        return []


# Singleton
_service: Optional[CreditDataService] = None


def get_service() -> CreditDataService:
    global _service
    if _service is None:
        _service = CreditDataService()
    return _service

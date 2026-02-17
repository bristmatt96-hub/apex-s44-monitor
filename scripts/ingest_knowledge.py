#!/usr/bin/env python3
"""
Knowledge Base Ingestion Script

Processes PDF books into searchable chunks for the credit analyst agent.
Delegates to knowledge/ingest.py for the actual processing.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge.ingest import main as ingest_main


if __name__ == "__main__":
    ingest_main()

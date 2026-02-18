"""
Ingest trading-specific knowledge into the trading agent.
Only processes files from trading_knowledge/books/

Usage:
    python ingest_trading_knowledge.py
"""
from knowledge.ingest import KnowledgeIngestion
from loguru import logger

if __name__ == "__main__":
    logger.info("=== Trading Knowledge Ingestion ===")
    logger.info("Looking for PDFs in: trading_knowledge/books/")
    logger.info("Looking for audiobooks in: trading_knowledge/audiobooks/")

    # Use the trading-specific folder
    ki = KnowledgeIngestion(base_path="trading_knowledge")

    # Process all files
    ki.process_all()

    logger.info("Done! Knowledge base updated.")

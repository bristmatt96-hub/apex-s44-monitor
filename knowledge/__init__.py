"""
Knowledge Base module for Apex Credit Monitor
Includes trading knowledge ingestion and retrieval
"""

from .pdf_processor import (
    KnowledgeBase,
    extract_text_from_pdf,
    index_pdf,
    chunk_text,
    get_credit_concept,
    list_credit_concepts,
    render_knowledge_base_ui,
    CREDIT_CONCEPTS,
    PYPDF_AVAILABLE
)

# Trading knowledge system
from .retriever import KnowledgeRetriever, get_retriever, RetrievalResult

__all__ = [
    # Original exports
    'KnowledgeBase',
    'extract_text_from_pdf',
    'index_pdf',
    'chunk_text',
    'get_credit_concept',
    'list_credit_concepts',
    'render_knowledge_base_ui',
    'CREDIT_CONCEPTS',
    'PYPDF_AVAILABLE',
    # Trading knowledge
    'KnowledgeRetriever',
    'get_retriever',
    'RetrievalResult'
]

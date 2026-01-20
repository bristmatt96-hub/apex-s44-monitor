"""
Knowledge Base module for Apex Credit Monitor
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

__all__ = [
    'KnowledgeBase',
    'extract_text_from_pdf',
    'index_pdf',
    'chunk_text',
    'get_credit_concept',
    'list_credit_concepts',
    'render_knowledge_base_ui',
    'CREDIT_CONCEPTS',
    'PYPDF_AVAILABLE'
]

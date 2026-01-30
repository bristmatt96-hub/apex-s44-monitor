"""
Text File Indexer for Knowledge Base
Indexes plain text files (transcripts, notes, etc.) into the knowledge base.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from .pdf_processor import chunk_text, KnowledgeBase


def extract_text_from_file(file_path: str) -> Dict[str, Any]:
    """
    Extract text and metadata from a plain text file.

    Args:
        file_path: Path to text file

    Returns:
        Dictionary with extracted text and metadata
    """
    file_path = Path(file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Try to extract title from first line if it's a header
    lines = content.split('\n')
    title = None
    if lines and lines[0].startswith('#'):
        title = lines[0].lstrip('#').strip()

    metadata = {
        'filename': file_path.name,
        'path': str(file_path),
        'title': title,
        'file_type': 'text',
        'processed_at': datetime.now().isoformat()
    }

    return {
        'metadata': metadata,
        'full_text': content,
        'total_chars': len(content)
    }


def index_text_file(file_path: str, category: str = "transcript") -> str:
    """
    Index a text file into the knowledge base.

    Args:
        file_path: Path to text file
        category: Category for organizing

    Returns:
        Document ID
    """
    # Extract text
    extracted = extract_text_from_file(file_path)

    # Chunk the text
    chunks = chunk_text(extracted['full_text'])

    # Create index entry
    doc_id = hashlib.md5(extracted['metadata']['filename'].encode()).hexdigest()[:12]

    indexed_doc = {
        'doc_id': doc_id,
        'metadata': extracted['metadata'],
        'category': category,
        'chunks': chunks,
        'chunk_count': len(chunks),
        'indexed_at': datetime.now().isoformat()
    }

    # Add to knowledge base
    kb = KnowledgeBase()
    kb.documents[doc_id] = indexed_doc
    kb._save()

    print(f"Indexed: {extracted['metadata']['filename']} ({len(chunks)} chunks)")
    return doc_id


def index_transcripts_folder(transcripts_dir: str = None) -> list:
    """
    Index all text files in the transcripts folder.

    Args:
        transcripts_dir: Path to transcripts directory

    Returns:
        List of indexed filenames
    """
    if transcripts_dir is None:
        transcripts_dir = Path(__file__).parent / "transcripts"
    else:
        transcripts_dir = Path(transcripts_dir)

    if not transcripts_dir.exists():
        print(f"Transcripts directory not found: {transcripts_dir}")
        return []

    kb = KnowledgeBase()
    indexed = []

    for txt_file in transcripts_dir.glob("*.txt"):
        try:
            # Check if already indexed
            existing_docs = kb.list_documents()
            if any(d['filename'] == txt_file.name for d in existing_docs):
                print(f"Skipping (already indexed): {txt_file.name}")
                continue

            doc_id = index_text_file(str(txt_file), "transcript")
            indexed.append(txt_file.name)
        except Exception as e:
            print(f"Error indexing {txt_file.name}: {e}")

    return indexed


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Index specific file
        file_path = sys.argv[1]
        category = sys.argv[2] if len(sys.argv) > 2 else "transcript"
        doc_id = index_text_file(file_path, category)
        print(f"Document ID: {doc_id}")
    else:
        # Index all transcripts
        print("Indexing all transcripts...")
        indexed = index_transcripts_folder()
        print(f"\nIndexed {len(indexed)} files")

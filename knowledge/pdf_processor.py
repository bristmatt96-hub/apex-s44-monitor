"""
PDF Knowledge Base Processor for Apex Credit Monitor
Extracts and indexes content from credit/finance PDFs for reference

This enables the system to learn from your books:
- The Pragmatist's Guide to Leveraged Finance
- Credit analysis guides
- Industry reports
"""

import os
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

# Try to import PDF libraries
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# For text processing
import hashlib


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[Dict]:
    """
    Split text into overlapping chunks for better retrieval

    Args:
        text: Full text to chunk
        chunk_size: Target size of each chunk in characters
        overlap: Overlap between consecutive chunks

    Returns:
        List of chunk dictionaries with text and metadata
    """
    chunks = []
    start = 0
    chunk_id = 0

    while start < len(text):
        end = start + chunk_size

        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence endings
            for punct in ['. ', '.\n', '? ', '!\n']:
                last_punct = text.rfind(punct, start + chunk_size // 2, end + 100)
                if last_punct != -1:
                    end = last_punct + 1
                    break

        chunk_text = text[start:end].strip()

        if chunk_text:
            chunks.append({
                'id': chunk_id,
                'text': chunk_text,
                'start_char': start,
                'end_char': end,
                'hash': hashlib.md5(chunk_text.encode()).hexdigest()[:8]
            })
            chunk_id += 1

        start = end - overlap

    return chunks


def extract_text_from_pdf(pdf_path: str) -> Dict[str, Any]:
    """
    Extract text and metadata from a PDF file

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dictionary with extracted text, metadata, and page info
    """
    if not PYPDF_AVAILABLE:
        raise ImportError("pypdf is required. Install with: pip install pypdf")

    pdf_path = Path(pdf_path)

    with open(pdf_path, 'rb') as f:
        reader = pypdf.PdfReader(f)

        # Extract metadata
        metadata = {
            'filename': pdf_path.name,
            'path': str(pdf_path),
            'pages': len(reader.pages),
            'title': reader.metadata.title if reader.metadata else None,
            'author': reader.metadata.author if reader.metadata else None,
            'processed_at': datetime.now().isoformat()
        }

        # Extract text page by page
        pages = []
        full_text = ""

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            pages.append({
                'page_num': i + 1,
                'text': page_text,
                'char_count': len(page_text)
            })
            full_text += page_text + "\n\n"

        return {
            'metadata': metadata,
            'pages': pages,
            'full_text': full_text.strip(),
            'total_chars': len(full_text)
        }


def index_pdf(pdf_path: str, category: str = "general") -> Dict[str, Any]:
    """
    Extract, chunk, and index a PDF for the knowledge base

    Args:
        pdf_path: Path to PDF file
        category: Category for organizing (e.g., "credit_analysis", "sector_report")

    Returns:
        Indexed document dictionary
    """
    # Extract text
    extracted = extract_text_from_pdf(pdf_path)

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

    return indexed_doc


class KnowledgeBase:
    """
    Simple knowledge base for storing and searching indexed PDFs

    For production, you'd want to use a vector database (Pinecone, Chroma, etc.)
    This is a simple keyword-based implementation for getting started.
    """

    def __init__(self, storage_path: str = None):
        """Initialize knowledge base"""
        if storage_path is None:
            storage_path = Path(__file__).parent / "kb_index.json"
        self.storage_path = Path(storage_path)
        self.documents = {}
        self._load()

    def _load(self):
        """Load existing index from disk"""
        if self.storage_path.exists():
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.documents = data.get('documents', {})

    def _save(self):
        """Save index to disk"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump({
                'documents': self.documents,
                'last_updated': datetime.now().isoformat()
            }, f, indent=2)

    def add_document(self, pdf_path: str, category: str = "general") -> str:
        """
        Add a PDF to the knowledge base

        Args:
            pdf_path: Path to PDF file
            category: Category for organizing

        Returns:
            Document ID
        """
        indexed = index_pdf(pdf_path, category)
        doc_id = indexed['doc_id']
        self.documents[doc_id] = indexed
        self._save()
        print(f"Indexed: {indexed['metadata']['filename']} ({indexed['chunk_count']} chunks)")
        return doc_id

    def search(self, query: str, top_k: int = 5, category: str = None) -> List[Dict]:
        """
        Search the knowledge base for relevant chunks

        Args:
            query: Search query
            top_k: Number of results to return
            category: Optional category filter

        Returns:
            List of relevant chunks with scores
        """
        query_terms = set(query.lower().split())
        results = []

        for doc_id, doc in self.documents.items():
            if category and doc.get('category') != category:
                continue

            for chunk in doc['chunks']:
                chunk_text_lower = chunk['text'].lower()
                # Simple scoring: count matching terms
                score = sum(1 for term in query_terms if term in chunk_text_lower)

                if score > 0:
                    results.append({
                        'doc_id': doc_id,
                        'doc_title': doc['metadata'].get('title') or doc['metadata']['filename'],
                        'chunk_id': chunk['id'],
                        'text': chunk['text'],
                        'score': score
                    })

        # Sort by score and return top_k
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]

    def search_credit_concept(self, concept: str) -> List[Dict]:
        """
        Search for a credit analysis concept

        Args:
            concept: Credit concept to search for (e.g., "leverage ratio", "covenant")

        Returns:
            Relevant chunks explaining the concept
        """
        # Expand common credit terms
        expansions = {
            'leverage': ['leverage', 'debt/ebitda', 'debt to ebitda', 'gearing', 'net debt'],
            'coverage': ['coverage', 'interest coverage', 'ebitda/interest', 'fixed charge'],
            'liquidity': ['liquidity', 'cash', 'revolver', 'working capital', 'current ratio'],
            'covenant': ['covenant', 'financial covenant', 'maintenance', 'incurrence'],
            'default': ['default', 'event of default', 'cross-default', 'acceleration'],
            'subordination': ['subordination', 'senior', 'junior', 'pari passu', 'waterfall'],
            'security': ['security', 'secured', 'unsecured', 'collateral', 'lien', 'pledge']
        }

        # Build expanded query
        query_terms = [concept]
        for key, terms in expansions.items():
            if key in concept.lower():
                query_terms.extend(terms)

        return self.search(' '.join(query_terms), top_k=10)

    def get_stats(self) -> Dict:
        """Get knowledge base statistics"""
        total_chunks = sum(doc['chunk_count'] for doc in self.documents.values())
        categories = {}
        for doc in self.documents.values():
            cat = doc.get('category', 'general')
            categories[cat] = categories.get(cat, 0) + 1

        return {
            'total_documents': len(self.documents),
            'total_chunks': total_chunks,
            'categories': categories,
            'documents': [
                {
                    'id': doc_id,
                    'title': doc['metadata'].get('title') or doc['metadata']['filename'],
                    'chunks': doc['chunk_count'],
                    'category': doc.get('category')
                }
                for doc_id, doc in self.documents.items()
            ]
        }

    def list_documents(self) -> List[Dict]:
        """List all indexed documents"""
        return [
            {
                'doc_id': doc_id,
                'filename': doc['metadata']['filename'],
                'title': doc['metadata'].get('title'),
                'pages': doc['metadata']['pages'],
                'chunks': doc['chunk_count'],
                'category': doc.get('category'),
                'indexed_at': doc.get('indexed_at')
            }
            for doc_id, doc in self.documents.items()
        ]


# ============== CREDIT-SPECIFIC KNOWLEDGE ==============

# Pre-defined credit concepts for quick lookup
CREDIT_CONCEPTS = {
    "leverage_ratios": {
        "definition": "Measures of a company's debt relative to earnings or cash flow",
        "key_metrics": ["Debt/EBITDA", "Net Debt/EBITDA", "Debt/Equity"],
        "thresholds": {
            "investment_grade": "< 3.0x",
            "high_yield_bb": "3.0x - 5.0x",
            "high_yield_b": "5.0x - 7.0x",
            "distressed": "> 7.0x"
        }
    },
    "coverage_ratios": {
        "definition": "Measures of a company's ability to service its debt",
        "key_metrics": ["EBITDA/Interest", "(EBITDA-Capex)/Interest", "FFO/Debt"],
        "thresholds": {
            "strong": "> 4.0x",
            "adequate": "2.0x - 4.0x",
            "weak": "1.5x - 2.0x",
            "stressed": "< 1.5x"
        }
    },
    "liquidity_analysis": {
        "definition": "Assessment of short-term financial flexibility",
        "components": ["Cash", "Revolver availability", "Near-term maturities", "Working capital"],
        "key_questions": [
            "Can the company cover 12-month maturities?",
            "What is the revolver headroom?",
            "Are there seasonal working capital needs?"
        ]
    },
    "credit_events": {
        "spread_widening": ["Rating downgrade", "Missed guidance", "Covenant breach", "Management departure", "Regulatory action"],
        "spread_tightening": ["Rating upgrade", "Deleveraging", "Asset sale", "Strong earnings", "M&A premium"]
    }
}


def get_credit_concept(concept_name: str) -> Optional[Dict]:
    """Get pre-defined credit concept explanation"""
    return CREDIT_CONCEPTS.get(concept_name.lower().replace(' ', '_'))


def list_credit_concepts() -> List[str]:
    """List available pre-defined credit concepts"""
    return list(CREDIT_CONCEPTS.keys())


# ============== STREAMLIT INTEGRATION ==============

def index_books_folder(kb: 'KnowledgeBase') -> List[str]:
    """Index all PDFs in the knowledge/books folder"""
    books_dir = Path(__file__).parent / "books"
    if not books_dir.exists():
        return []

    indexed = []
    for pdf_file in books_dir.glob("*.pdf"):
        try:
            # Check if already indexed
            existing_docs = kb.list_documents()
            if any(d['filename'] == pdf_file.name for d in existing_docs):
                continue

            doc_id = kb.add_document(str(pdf_file), "credit_analysis")
            indexed.append(pdf_file.name)
        except Exception as e:
            print(f"Error indexing {pdf_file.name}: {e}")

    return indexed


def render_knowledge_base_ui(st, kb: KnowledgeBase):
    """Render knowledge base interface in Streamlit"""
    st.markdown("### Knowledge Base")
    st.caption("Search your indexed credit books for concepts and analysis")

    # Stats
    stats = kb.get_stats()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Documents", stats['total_documents'])
    with col2:
        st.metric("Chunks", stats['total_chunks'])
    with col3:
        st.metric("Categories", len(stats.get('categories', {})))

    # Scan books folder button
    books_dir = Path(__file__).parent / "books"
    if books_dir.exists():
        pdf_count = len(list(books_dir.glob("*.pdf")))
        indexed_count = stats['total_documents']

        if pdf_count > indexed_count:
            st.warning(f"Found {pdf_count} PDFs in books folder, only {indexed_count} indexed.")
            if st.button("Index All Books", key="index_books"):
                with st.spinner("Indexing PDFs... this may take a few minutes"):
                    indexed = index_books_folder(kb)
                    if indexed:
                        st.success(f"Indexed {len(indexed)} new documents: {', '.join(indexed[:5])}{'...' if len(indexed) > 5 else ''}")
                        st.rerun()
                    else:
                        st.info("All books already indexed")

    # Search section - MOVED UP for prominence
    st.markdown("---")
    st.markdown("#### 🔍 Search Your Credit Books")

    search_query = st.text_input("Search query", placeholder="e.g., covenant lite, leverage ratio, distressed exchange")

    if search_query:
        results = kb.search(search_query, top_k=5)

        if results:
            for i, result in enumerate(results):
                with st.expander(f"{i+1}. {result['doc_title']} (Score: {result['score']})"):
                    st.markdown(result['text'][:800] + "..." if len(result['text']) > 800 else result['text'])
        else:
            st.info("No results found. Try different keywords.")

    # Document list
    st.markdown("---")
    st.markdown("#### 📚 Indexed Documents")

    docs = kb.list_documents()
    if docs:
        for doc in docs:
            st.markdown(f"- **{doc['filename']}** ({doc['pages']} pages, {doc['chunks']} chunks)")
    else:
        st.info("No documents indexed yet. Click 'Index All Books' above or upload a PDF below.")

    # Upload section - moved down
    with st.expander("Upload New PDF"):
        uploaded_file = st.file_uploader("Upload PDF", type=['pdf'])
        category = st.selectbox("Category", ["credit_analysis", "sector_report", "company_report", "general"])

        if uploaded_file and st.button("Index Document"):
            # Save uploaded file temporarily (cross-platform)
            temp_path = Path(tempfile.gettempdir()) / uploaded_file.name
            with open(temp_path, 'wb') as f:
                f.write(uploaded_file.getbuffer())

            try:
                doc_id = kb.add_document(str(temp_path), category)
                st.success(f"Indexed: {uploaded_file.name} (ID: {doc_id})")
            except Exception as e:
                st.error(f"Error indexing: {e}")

    # Quick credit concepts
    st.markdown("---")
    st.markdown("#### 📖 Quick Credit Concepts")

    concept = st.selectbox("Select concept", list_credit_concepts())
    concept_data = get_credit_concept(concept)

    if concept_data:
        st.markdown(f"**Definition:** {concept_data.get('definition', 'N/A')}")

        if 'key_metrics' in concept_data:
            st.markdown("**Key Metrics:**")
            for metric in concept_data['key_metrics']:
                st.markdown(f"- {metric}")

        if 'thresholds' in concept_data:
            st.markdown("**Thresholds:**")
            for level, value in concept_data['thresholds'].items():
                st.markdown(f"- {level.replace('_', ' ').title()}: {value}")


if __name__ == "__main__":
    print("PDF Knowledge Base Processor")
    print("=" * 40)

    if not PYPDF_AVAILABLE:
        print("pypdf not installed. Install with: pip install pypdf")
        exit(1)

    # Test with a sample file if provided
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        print(f"\nIndexing: {pdf_path}")

        kb = KnowledgeBase()
        doc_id = kb.add_document(pdf_path, "credit_analysis")
        print(f"Document ID: {doc_id}")

        print("\nStats:")
        print(json.dumps(kb.get_stats(), indent=2))

        # Test search
        print("\nTest search for 'leverage ratio':")
        results = kb.search("leverage ratio", top_k=3)
        for r in results:
            print(f"  - [{r['score']}] {r['text'][:100]}...")
    else:
        print("\nUsage: python pdf_processor.py <pdf_file>")
        print("\nOr import and use in your code:")
        print("  from knowledge.pdf_processor import KnowledgeBase")
        print("  kb = KnowledgeBase()")
        print("  kb.add_document('my_book.pdf', 'credit_analysis')")
        print("  results = kb.search('leverage ratio')")

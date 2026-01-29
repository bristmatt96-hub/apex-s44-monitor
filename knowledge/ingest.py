"""
Knowledge Ingestion System
Processes PDFs and audiobooks into a searchable knowledge base
"""
import os
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Generator
from datetime import datetime
from dataclasses import dataclass, asdict
from loguru import logger

# PDF processing
try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("pypdf not installed - PDF processing disabled")

# Audio transcription
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("whisper not installed - audio transcription disabled")

# Text processing
import re


@dataclass
class KnowledgeChunk:
    """A chunk of knowledge from a book"""
    id: str
    source: str  # filename
    source_type: str  # 'pdf' or 'audiobook'
    title: str
    chunk_index: int
    content: str
    word_count: int
    topics: List[str]
    created_at: str


class KnowledgeIngestion:
    """
    Ingests books and audiobooks into searchable knowledge base.

    Directory structure:
    knowledge/
    ├── books/          # Drop PDFs here
    ├── audiobooks/     # Drop M4B/MP3 files here
    ├── processed/      # Extracted text stored here
    └── vectors/        # Vector embeddings (future)
    """

    def __init__(self, base_path: str = "knowledge"):
        self.base_path = Path(base_path)
        self.books_path = self.base_path / "books"
        self.audiobooks_path = self.base_path / "audiobooks"
        self.processed_path = self.base_path / "processed"
        self.vectors_path = self.base_path / "vectors"

        # Create directories
        for path in [self.books_path, self.audiobooks_path, self.processed_path, self.vectors_path]:
            path.mkdir(parents=True, exist_ok=True)

        # Knowledge index
        self.index_file = self.processed_path / "index.json"
        self.index = self._load_index()

        # Chunk settings
        self.chunk_size = 1000  # words per chunk
        self.chunk_overlap = 100  # overlap between chunks

        # Whisper model (loaded on demand)
        self._whisper_model = None

    def _load_index(self) -> Dict:
        """Load or create knowledge index"""
        if self.index_file.exists():
            with open(self.index_file, 'r') as f:
                return json.load(f)
        return {"files": {}, "chunks": [], "stats": {"total_chunks": 0, "total_words": 0}}

    def _save_index(self) -> None:
        """Save knowledge index"""
        with open(self.index_file, 'w') as f:
            json.dump(self.index, f, indent=2)

    def _get_file_hash(self, filepath: Path) -> str:
        """Get hash of file to detect changes"""
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _chunk_text(self, text: str, source: str, source_type: str, title: str) -> List[KnowledgeChunk]:
        """Split text into overlapping chunks"""
        # Clean text
        text = re.sub(r'\s+', ' ', text).strip()
        words = text.split()

        chunks = []
        start = 0
        chunk_index = 0

        while start < len(words):
            end = start + self.chunk_size
            chunk_words = words[start:end]
            chunk_text = ' '.join(chunk_words)

            # Detect topics in chunk
            topics = self._detect_topics(chunk_text)

            chunk = KnowledgeChunk(
                id=f"{hashlib.md5(f'{source}_{chunk_index}'.encode()).hexdigest()[:12]}",
                source=source,
                source_type=source_type,
                title=title,
                chunk_index=chunk_index,
                content=chunk_text,
                word_count=len(chunk_words),
                topics=topics,
                created_at=datetime.now().isoformat()
            )
            chunks.append(chunk)

            start = end - self.chunk_overlap
            chunk_index += 1

        return chunks

    def _detect_topics(self, text: str) -> List[str]:
        """Detect trading-related topics in text"""
        text_lower = text.lower()
        topics = []

        topic_keywords = {
            'technical_analysis': ['support', 'resistance', 'trend', 'chart', 'pattern', 'indicator', 'moving average', 'rsi', 'macd'],
            'options': ['option', 'call', 'put', 'strike', 'expiration', 'premium', 'greeks', 'delta', 'theta', 'volatility'],
            'psychology': ['emotion', 'fear', 'greed', 'discipline', 'mindset', 'psychology', 'bias', 'patience'],
            'risk_management': ['risk', 'stop loss', 'position size', 'drawdown', 'risk reward', 'money management'],
            'fundamentals': ['earnings', 'revenue', 'valuation', 'p/e', 'balance sheet', 'cash flow', 'fundamental'],
            'market_structure': ['market maker', 'liquidity', 'order flow', 'bid ask', 'spread', 'volume'],
            'strategies': ['strategy', 'setup', 'entry', 'exit', 'trade plan', 'system', 'backtest'],
            'crypto': ['bitcoin', 'ethereum', 'crypto', 'blockchain', 'defi', 'token'],
            'forex': ['forex', 'currency', 'pip', 'lot', 'leverage', 'exchange rate'],
            'macro': ['fed', 'interest rate', 'inflation', 'gdp', 'economic', 'recession', 'monetary']
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in text_lower for kw in keywords):
                topics.append(topic)

        return topics

    # ==================== PDF Processing ====================

    def process_pdf(self, filepath: Path) -> Optional[List[KnowledgeChunk]]:
        """Extract text from PDF and chunk it"""
        if not PDF_AVAILABLE:
            logger.error("pypdf not installed")
            return None

        try:
            logger.info(f"Processing PDF: {filepath.name}")

            reader = PdfReader(filepath)
            text_parts = []

            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

                if (i + 1) % 50 == 0:
                    logger.info(f"  Processed {i + 1}/{len(reader.pages)} pages")

            full_text = '\n'.join(text_parts)

            if not full_text.strip():
                logger.warning(f"No text extracted from {filepath.name}")
                return None

            # Get title from filename
            title = filepath.stem.replace('_', ' ').replace('-', ' ').title()

            # Chunk the text
            chunks = self._chunk_text(full_text, filepath.name, 'pdf', title)

            logger.info(f"  Created {len(chunks)} chunks from {filepath.name}")
            return chunks

        except Exception as e:
            logger.error(f"Error processing PDF {filepath.name}: {e}")
            return None

    def process_all_pdfs(self) -> int:
        """Process all PDFs in books folder"""
        pdf_files = list(self.books_path.glob("*.pdf"))

        if not pdf_files:
            logger.info("No PDF files found in knowledge/books/")
            return 0

        logger.info(f"Found {len(pdf_files)} PDF files to process")
        total_chunks = 0

        for pdf_path in pdf_files:
            file_hash = self._get_file_hash(pdf_path)

            # Skip if already processed
            if pdf_path.name in self.index["files"]:
                if self.index["files"][pdf_path.name].get("hash") == file_hash:
                    logger.info(f"Skipping {pdf_path.name} (already processed)")
                    continue

            chunks = self.process_pdf(pdf_path)

            if chunks:
                # Save chunks
                self._save_chunks(chunks)

                # Update index
                self.index["files"][pdf_path.name] = {
                    "hash": file_hash,
                    "type": "pdf",
                    "chunks": len(chunks),
                    "processed_at": datetime.now().isoformat()
                }

                total_chunks += len(chunks)

        self._save_index()
        return total_chunks

    # ==================== Audiobook Processing ====================

    def _load_whisper_model(self, model_size: str = "base"):
        """Load Whisper model for transcription"""
        if not WHISPER_AVAILABLE:
            raise RuntimeError("whisper not installed. Run: pip install openai-whisper")

        if self._whisper_model is None:
            logger.info(f"Loading Whisper model ({model_size})...")
            self._whisper_model = whisper.load_model(model_size)

        return self._whisper_model

    def transcribe_audiobook(self, filepath: Path, model_size: str = "base") -> Optional[str]:
        """Transcribe audiobook to text"""
        try:
            logger.info(f"Transcribing: {filepath.name}")
            logger.info("  This may take a while (roughly 1x audio duration)...")

            model = self._load_whisper_model(model_size)

            result = model.transcribe(
                str(filepath),
                verbose=True,
                language="en"
            )

            return result["text"]

        except Exception as e:
            logger.error(f"Error transcribing {filepath.name}: {e}")
            return None

    def process_audiobook(self, filepath: Path, model_size: str = "base") -> Optional[List[KnowledgeChunk]]:
        """Process audiobook: transcribe and chunk"""
        # Check for cached transcription
        cache_file = self.processed_path / f"{filepath.stem}_transcript.txt"

        if cache_file.exists():
            logger.info(f"Using cached transcription for {filepath.name}")
            with open(cache_file, 'r') as f:
                text = f.read()
        else:
            text = self.transcribe_audiobook(filepath, model_size)

            if not text:
                return None

            # Cache transcription
            with open(cache_file, 'w') as f:
                f.write(text)
            logger.info(f"  Saved transcription to {cache_file.name}")

        # Get title from filename
        title = filepath.stem.replace('_', ' ').replace('-', ' ').title()

        # Chunk the text
        chunks = self._chunk_text(text, filepath.name, 'audiobook', title)

        logger.info(f"  Created {len(chunks)} chunks from {filepath.name}")
        return chunks

    def process_all_audiobooks(self, model_size: str = "base") -> int:
        """Process all audiobooks in audiobooks folder"""
        audio_extensions = ['.m4b', '.m4a', '.mp3', '.wav', '.flac']
        audio_files = []

        for ext in audio_extensions:
            audio_files.extend(self.audiobooks_path.glob(f"*{ext}"))

        if not audio_files:
            logger.info("No audiobook files found in knowledge/audiobooks/")
            return 0

        logger.info(f"Found {len(audio_files)} audiobook files to process")
        total_chunks = 0

        for audio_path in audio_files:
            file_hash = self._get_file_hash(audio_path)

            # Skip if already processed
            if audio_path.name in self.index["files"]:
                if self.index["files"][audio_path.name].get("hash") == file_hash:
                    logger.info(f"Skipping {audio_path.name} (already processed)")
                    continue

            chunks = self.process_audiobook(audio_path, model_size)

            if chunks:
                # Save chunks
                self._save_chunks(chunks)

                # Update index
                self.index["files"][audio_path.name] = {
                    "hash": file_hash,
                    "type": "audiobook",
                    "chunks": len(chunks),
                    "processed_at": datetime.now().isoformat()
                }

                total_chunks += len(chunks)

        self._save_index()
        return total_chunks

    # ==================== Storage ====================

    def _save_chunks(self, chunks: List[KnowledgeChunk]) -> None:
        """Save chunks to processed folder"""
        for chunk in chunks:
            chunk_file = self.processed_path / f"chunk_{chunk.id}.json"
            with open(chunk_file, 'w') as f:
                json.dump(asdict(chunk), f, indent=2)

            self.index["chunks"].append(chunk.id)

        self.index["stats"]["total_chunks"] = len(self.index["chunks"])

    def process_all(self, whisper_model: str = "base") -> Dict:
        """Process all books and audiobooks"""
        logger.info("=" * 50)
        logger.info("Starting Knowledge Ingestion")
        logger.info("=" * 50)

        pdf_chunks = self.process_all_pdfs()
        audio_chunks = self.process_all_audiobooks(whisper_model)

        # Calculate total words
        total_words = 0
        for chunk_id in self.index["chunks"]:
            chunk_file = self.processed_path / f"chunk_{chunk_id}.json"
            if chunk_file.exists():
                with open(chunk_file, 'r') as f:
                    chunk = json.load(f)
                    total_words += chunk.get("word_count", 0)

        self.index["stats"]["total_words"] = total_words
        self._save_index()

        logger.info("=" * 50)
        logger.info("Knowledge Ingestion Complete")
        logger.info(f"  PDF chunks: {pdf_chunks}")
        logger.info(f"  Audiobook chunks: {audio_chunks}")
        logger.info(f"  Total chunks: {len(self.index['chunks'])}")
        logger.info(f"  Total words: {total_words:,}")
        logger.info("=" * 50)

        return {
            "pdf_chunks": pdf_chunks,
            "audio_chunks": audio_chunks,
            "total_chunks": len(self.index["chunks"]),
            "total_words": total_words
        }

    def get_stats(self) -> Dict:
        """Get knowledge base statistics"""
        return {
            "files_processed": len(self.index["files"]),
            "total_chunks": self.index["stats"].get("total_chunks", 0),
            "total_words": self.index["stats"].get("total_words", 0),
            "files": list(self.index["files"].keys())
        }


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Knowledge Ingestion System")
    parser.add_argument("--pdfs", action="store_true", help="Process PDFs only")
    parser.add_argument("--audiobooks", action="store_true", help="Process audiobooks only")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large"],
                       help="Whisper model size (default: base)")
    parser.add_argument("--stats", action="store_true", help="Show knowledge base stats")

    args = parser.parse_args()

    ingestion = KnowledgeIngestion()

    if args.stats:
        stats = ingestion.get_stats()
        print("\nKnowledge Base Statistics:")
        print(f"  Files processed: {stats['files_processed']}")
        print(f"  Total chunks: {stats['total_chunks']}")
        print(f"  Total words: {stats['total_words']:,}")
        print(f"  Files: {', '.join(stats['files']) if stats['files'] else 'None'}")
    elif args.pdfs:
        ingestion.process_all_pdfs()
    elif args.audiobooks:
        ingestion.process_all_audiobooks(args.model)
    else:
        ingestion.process_all(args.model)

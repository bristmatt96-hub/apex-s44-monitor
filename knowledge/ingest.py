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

# Audio transcription - Whisper (local)
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("whisper not installed - local audio transcription disabled")

# Audio transcription - Google Cloud Speech-to-Text
try:
    from google.cloud import speech_v1 as speech
    from google.cloud.speech_v1 import types
    GOOGLE_SPEECH_AVAILABLE = True
except ImportError:
    GOOGLE_SPEECH_AVAILABLE = False
    logger.warning("google-cloud-speech not installed - Google transcription disabled")

# Audio file handling for Google Cloud
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# Text processing
import re
import io
import wave


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
    category: str = ""  # Book category folder (trading_psychology, technical_analysis, etc.)


class KnowledgeIngestion:
    """
    Ingests books and audiobooks into searchable knowledge base.

    Directory structure (scans both locations):

    Primary location:
    knowledge/
    ├── books/                    # Drop PDFs here (or in topic subfolders)
    │   ├── trading_psychology/   # Mental game, discipline, emotional control
    │   ├── technical_analysis/   # Charts, patterns, indicators
    │   ├── market_structure/     # How markets work, order flow
    │   ├── risk_management/      # Position sizing, capital preservation
    │   ├── options_strategies/   # Options trading, Greeks, volatility
    │   ├── behavioral_finance/   # Market psychology, biases
    │   ├── macro_economics/      # Fed, interest rates, economic cycles
    │   └── classics/             # Timeless wisdom, foundational texts
    ├── audiobooks/               # Drop M4B/MP3 files here
    ├── processed/                # Extracted text stored here
    └── vectors/                  # Vector embeddings (future)

    Alternative location (also scanned if exists):
    trading_knowledge/
    ├── books/                    # PDFs here or in topic subfolders
    │   └── [same topic subfolders as above]
    └── audiobooks/               # M4B/MP3 audiobook files
    """

    # Book category folders
    BOOK_CATEGORIES = [
        'trading_psychology',
        'technical_analysis',
        'market_structure',
        'risk_management',
        'options_strategies',
        'behavioral_finance',
        'macro_economics',
        'classics'
    ]

    def __init__(self, base_path: str = "knowledge"):
        self.base_path = Path(base_path)
        self.books_path = self.base_path / "books"
        self.audiobooks_path = self.base_path / "audiobooks"
        self.processed_path = self.base_path / "processed"
        self.vectors_path = self.base_path / "vectors"

        # Alternative books location (trading_knowledge/books)
        self.alt_books_path = Path("trading_knowledge/books")

        # Alternative audiobooks location (trading_knowledge/audiobooks)
        self.alt_audiobooks_path = Path("trading_knowledge/audiobooks")

        # Create directories
        for path in [self.books_path, self.audiobooks_path, self.processed_path, self.vectors_path]:
            path.mkdir(parents=True, exist_ok=True)

        # Create topic subfolders in books/
        for category in self.BOOK_CATEGORIES:
            (self.books_path / category).mkdir(parents=True, exist_ok=True)

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

    def _chunk_text(self, text: str, source: str, source_type: str, title: str, category: str = "") -> List[KnowledgeChunk]:
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

            # Add category to topics if not already present
            if category and category not in topics:
                topics.insert(0, category)

            chunk = KnowledgeChunk(
                id=f"{hashlib.md5(f'{source}_{chunk_index}'.encode()).hexdigest()[:12]}",
                source=source,
                source_type=source_type,
                title=title,
                chunk_index=chunk_index,
                content=chunk_text,
                word_count=len(chunk_words),
                topics=topics,
                created_at=datetime.now().isoformat(),
                category=category
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

    def process_pdf(self, filepath: Path, category: str = "") -> Optional[List[KnowledgeChunk]]:
        """Extract text from PDF and chunk it"""
        if not PDF_AVAILABLE:
            logger.error("pypdf not installed")
            return None

        try:
            category_info = f" [{category}]" if category else ""
            logger.info(f"Processing PDF: {filepath.name}{category_info}")

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

            # Chunk the text with category
            chunks = self._chunk_text(full_text, filepath.name, 'pdf', title, category)

            logger.info(f"  Created {len(chunks)} chunks from {filepath.name}")
            return chunks

        except Exception as e:
            logger.error(f"Error processing PDF {filepath.name}: {e}")
            return None

    def process_all_pdfs(self) -> int:
        """Process all PDFs in books folder, topic subfolders, and alternative locations"""
        # Collect all PDFs with their categories
        pdf_files_with_category = []

        # Root level PDFs (no category)
        for pdf_path in self.books_path.glob("*.pdf"):
            pdf_files_with_category.append((pdf_path, "", self.books_path))

        # PDFs in topic subfolders
        for category in self.BOOK_CATEGORIES:
            category_path = self.books_path / category
            if category_path.exists():
                for pdf_path in category_path.glob("*.pdf"):
                    pdf_files_with_category.append((pdf_path, category, self.books_path))

        # Also check alternative books path (trading_knowledge/books/)
        if self.alt_books_path.exists():
            logger.info(f"Checking alternative books location: {self.alt_books_path}")

            # Root level PDFs in alt path
            for pdf_path in self.alt_books_path.glob("*.pdf"):
                pdf_files_with_category.append((pdf_path, "", self.alt_books_path))

            # PDFs in topic subfolders in alt path
            for category in self.BOOK_CATEGORIES:
                category_path = self.alt_books_path / category
                if category_path.exists():
                    for pdf_path in category_path.glob("*.pdf"):
                        pdf_files_with_category.append((pdf_path, category, self.alt_books_path))

        if not pdf_files_with_category:
            logger.info("No PDF files found in knowledge/books/ or trading_knowledge/books/")
            return 0

        logger.info(f"Found {len(pdf_files_with_category)} PDF files to process")

        # Show breakdown by category and location
        by_category = {}
        by_location = {"knowledge/books": 0, "trading_knowledge/books": 0}
        for pdf_path, cat, base_path in pdf_files_with_category:
            cat_name = cat or "uncategorized"
            by_category[cat_name] = by_category.get(cat_name, 0) + 1
            if base_path == self.alt_books_path:
                by_location["trading_knowledge/books"] += 1
            else:
                by_location["knowledge/books"] += 1

        for cat, count in by_category.items():
            logger.info(f"  {cat}: {count} files")
        for loc, count in by_location.items():
            if count > 0:
                logger.info(f"  Location {loc}: {count} files")

        total_chunks = 0

        for pdf_path, category, base_path in pdf_files_with_category:
            file_hash = self._get_file_hash(pdf_path)

            # Use relative path as key to handle same filename in different folders
            # Include location prefix to distinguish between knowledge/ and trading_knowledge/
            try:
                relative_key = str(pdf_path.relative_to(base_path))
                if base_path == self.alt_books_path:
                    relative_key = f"alt:{relative_key}"
            except ValueError:
                relative_key = pdf_path.name

            # Skip if already processed
            if relative_key in self.index["files"]:
                if self.index["files"][relative_key].get("hash") == file_hash:
                    logger.info(f"Skipping {relative_key} (already processed)")
                    continue

            chunks = self.process_pdf(pdf_path, category)

            if chunks:
                # Save chunks
                self._save_chunks(chunks)

                # Update index with category info
                self.index["files"][relative_key] = {
                    "hash": file_hash,
                    "type": "pdf",
                    "category": category,
                    "source_path": str(pdf_path),
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
        """Transcribe audiobook to text using local Whisper"""
        try:
            logger.info(f"Transcribing with Whisper: {filepath.name}")
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

    def transcribe_with_google(self, filepath: Path) -> Optional[str]:
        """Transcribe audiobook using Google Cloud Speech-to-Text"""
        if not GOOGLE_SPEECH_AVAILABLE:
            raise RuntimeError("google-cloud-speech not installed. Run: pip install google-cloud-speech")

        try:
            logger.info(f"Transcribing with Google Cloud: {filepath.name}")

            # Initialize Google Speech client
            client = speech.SpeechClient()

            # Convert audio to WAV format if needed (Google requires specific formats)
            audio_path = filepath
            temp_wav = None

            if filepath.suffix.lower() not in ['.wav', '.flac']:
                if not PYDUB_AVAILABLE:
                    logger.error("pydub required for non-WAV files. Run: pip install pydub")
                    return None

                logger.info("  Converting audio to WAV format...")
                audio = AudioSegment.from_file(str(filepath))
                # Convert to mono, 16kHz for Google Speech
                audio = audio.set_channels(1).set_frame_rate(16000)
                temp_wav = self.processed_path / f"{filepath.stem}_temp.wav"
                audio.export(str(temp_wav), format="wav")
                audio_path = temp_wav

            # For long audio files, use long_running_recognize
            file_size = audio_path.stat().st_size

            if file_size > 10 * 1024 * 1024:  # > 10MB, use GCS (requires upload)
                logger.info("  Large file detected - using chunked processing...")
                return self._transcribe_google_chunked(audio_path, client)

            # Read audio file
            with open(audio_path, 'rb') as f:
                audio_content = f.read()

            audio = speech.RecognitionAudio(content=audio_content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code="en-US",
                enable_automatic_punctuation=True,
            )

            logger.info("  Sending to Google Cloud Speech-to-Text...")

            # Use long_running_recognize for longer audio
            operation = client.long_running_recognize(config=config, audio=audio)
            logger.info("  Waiting for transcription to complete...")
            response = operation.result(timeout=3600)  # 1 hour timeout

            # Combine all transcription results
            transcript_parts = []
            for result in response.results:
                if result.alternatives:
                    transcript_parts.append(result.alternatives[0].transcript)

            # Clean up temp file
            if temp_wav and temp_wav.exists():
                temp_wav.unlink()

            full_transcript = ' '.join(transcript_parts)
            logger.info(f"  Transcription complete: {len(full_transcript)} characters")
            return full_transcript

        except Exception as e:
            logger.error(f"Error transcribing with Google: {e}")
            return None

    def _transcribe_google_chunked(self, filepath: Path, client) -> Optional[str]:
        """Transcribe large audio files in chunks"""
        if not PYDUB_AVAILABLE:
            logger.error("pydub required for chunked processing. Run: pip install pydub")
            return None

        try:
            logger.info("  Loading audio for chunked processing...")
            audio = AudioSegment.from_file(str(filepath))
            audio = audio.set_channels(1).set_frame_rate(16000)

            # Split into 1-minute chunks (Google limit is ~1 min for sync, longer for async)
            chunk_length_ms = 60 * 1000  # 1 minute
            chunks = [audio[i:i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

            logger.info(f"  Processing {len(chunks)} audio chunks...")
            transcript_parts = []

            for i, chunk in enumerate(chunks):
                logger.info(f"  Transcribing chunk {i + 1}/{len(chunks)}...")

                # Export chunk to bytes
                buffer = io.BytesIO()
                chunk.export(buffer, format="wav")
                audio_content = buffer.getvalue()

                audio_input = speech.RecognitionAudio(content=audio_content)
                config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=16000,
                    language_code="en-US",
                    enable_automatic_punctuation=True,
                )

                response = client.recognize(config=config, audio=audio_input)

                for result in response.results:
                    if result.alternatives:
                        transcript_parts.append(result.alternatives[0].transcript)

            full_transcript = ' '.join(transcript_parts)
            logger.info(f"  Chunked transcription complete: {len(full_transcript)} characters")
            return full_transcript

        except Exception as e:
            logger.error(f"Error in chunked transcription: {e}")
            return None

    def process_audiobook(self, filepath: Path, model_size: str = "base", backend: str = "whisper") -> Optional[List[KnowledgeChunk]]:
        """
        Process audiobook: transcribe and chunk

        Args:
            filepath: Path to audio file
            model_size: Whisper model size (only for whisper backend)
            backend: 'whisper' for local, 'google' for Google Cloud Speech-to-Text
        """
        # Check for cached transcription
        cache_file = self.processed_path / f"{filepath.stem}_transcript.txt"

        if cache_file.exists():
            logger.info(f"Using cached transcription for {filepath.name}")
            with open(cache_file, 'r') as f:
                text = f.read()
        else:
            # Choose transcription backend
            if backend == "google":
                if not GOOGLE_SPEECH_AVAILABLE:
                    logger.error("Google Cloud Speech not available. Install: pip install google-cloud-speech")
                    return None
                text = self.transcribe_with_google(filepath)
            else:
                # Default to Whisper
                if not WHISPER_AVAILABLE:
                    logger.error("Whisper not available. Install: pip install openai-whisper")
                    return None
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

    def process_all_audiobooks(self, model_size: str = "base", backend: str = "whisper") -> int:
        """
        Process all audiobooks in audiobooks folder and alternative locations

        Args:
            model_size: Whisper model size (only for whisper backend)
            backend: 'whisper' for local, 'google' for Google Cloud Speech-to-Text
        """
        audio_extensions = ['.m4b', '.m4a', '.mp3', '.wav', '.flac']
        audio_files_with_base = []  # (path, base_path) tuples

        # Primary location: knowledge/audiobooks/
        for ext in audio_extensions:
            for audio_path in self.audiobooks_path.glob(f"*{ext}"):
                audio_files_with_base.append((audio_path, self.audiobooks_path))

        # Alternative location: trading_knowledge/audiobooks/
        if self.alt_audiobooks_path.exists():
            logger.info(f"Checking alternative audiobooks location: {self.alt_audiobooks_path}")
            for ext in audio_extensions:
                for audio_path in self.alt_audiobooks_path.glob(f"*{ext}"):
                    audio_files_with_base.append((audio_path, self.alt_audiobooks_path))

        if not audio_files_with_base:
            logger.info("No audiobook files found in knowledge/audiobooks/ or trading_knowledge/audiobooks/")
            return 0

        # Show breakdown by location
        primary_count = sum(1 for _, base in audio_files_with_base if base == self.audiobooks_path)
        alt_count = sum(1 for _, base in audio_files_with_base if base == self.alt_audiobooks_path)

        logger.info(f"Found {len(audio_files_with_base)} audiobook files to process")
        if primary_count > 0:
            logger.info(f"  knowledge/audiobooks/: {primary_count} files")
        if alt_count > 0:
            logger.info(f"  trading_knowledge/audiobooks/: {alt_count} files")
        logger.info(f"Using transcription backend: {backend}")

        total_chunks = 0

        for audio_path, base_path in audio_files_with_base:
            file_hash = self._get_file_hash(audio_path)

            # Use prefixed key to distinguish locations
            if base_path == self.alt_audiobooks_path:
                index_key = f"alt_audio:{audio_path.name}"
            else:
                index_key = audio_path.name

            # Skip if already processed
            if index_key in self.index["files"]:
                if self.index["files"][index_key].get("hash") == file_hash:
                    logger.info(f"Skipping {audio_path.name} (already processed)")
                    continue

            chunks = self.process_audiobook(audio_path, model_size, backend)

            if chunks:
                # Save chunks
                self._save_chunks(chunks)

                # Update index
                self.index["files"][index_key] = {
                    "hash": file_hash,
                    "type": "audiobook",
                    "backend": backend,
                    "source_path": str(audio_path),
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

    def process_all(self, whisper_model: str = "base", backend: str = "whisper") -> Dict:
        """Process all books and audiobooks"""
        logger.info("=" * 50)
        logger.info("Starting Knowledge Ingestion")
        logger.info("=" * 50)

        pdf_chunks = self.process_all_pdfs()
        audio_chunks = self.process_all_audiobooks(whisper_model, backend)

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
        # Count by category and location
        by_category = {}
        by_location = {"knowledge/books": 0, "trading_knowledge/books": 0}

        for filename, info in self.index["files"].items():
            category = info.get("category", "") or "uncategorized"
            by_category[category] = by_category.get(category, 0) + 1

            # Check location based on key prefix
            if filename.startswith("alt:"):
                by_location["trading_knowledge/books"] += 1
            else:
                by_location["knowledge/books"] += 1

        # Check for available PDF files in both locations
        available_pdfs = []
        if self.books_path.exists():
            available_pdfs.extend(list(self.books_path.rglob("*.pdf")))
        if self.alt_books_path.exists():
            available_pdfs.extend(list(self.alt_books_path.rglob("*.pdf")))

        return {
            "files_processed": len(self.index["files"]),
            "total_chunks": self.index["stats"].get("total_chunks", 0),
            "total_words": self.index["stats"].get("total_words", 0),
            "files": list(self.index["files"].keys()),
            "by_category": by_category,
            "by_location": by_location,
            "pdfs_available": len(available_pdfs),
            "alt_path_exists": self.alt_books_path.exists()
        }


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Knowledge Ingestion System")
    parser.add_argument("--pdfs", action="store_true", help="Process PDFs only")
    parser.add_argument("--process-books", action="store_true", help="Process all books (PDFs) in topic folders")
    parser.add_argument("--audiobooks", action="store_true", help="Process audiobooks only")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large"],
                       help="Whisper model size (default: base)")
    parser.add_argument("--backend", default="whisper", choices=["whisper", "google"],
                       help="Transcription backend: 'whisper' (local) or 'google' (Google Cloud Speech)")
    parser.add_argument("--stats", action="store_true", help="Show knowledge base stats")

    args = parser.parse_args()

    ingestion = KnowledgeIngestion()

    if args.stats:
        stats = ingestion.get_stats()
        print("\nKnowledge Base Statistics:")
        print(f"  Files processed: {stats['files_processed']}")
        print(f"  Total chunks: {stats['total_chunks']}")
        print(f"  Total words: {stats['total_words']:,}")
        print(f"  PDFs available: {stats['pdfs_available']}")

        print("\n  Locations:")
        print(f"    knowledge/books/: exists")
        alt_status = "exists" if stats['alt_path_exists'] else "NOT FOUND"
        print(f"    trading_knowledge/books/: {alt_status}")

        if stats.get('by_location'):
            print("\n  By Location:")
            for loc, count in stats['by_location'].items():
                if count > 0:
                    print(f"    {loc}: {count} files")

        if stats.get('by_category'):
            print("\n  By Category:")
            for cat, count in stats['by_category'].items():
                print(f"    {cat}: {count} files")
        print(f"\n  Files: {', '.join(stats['files']) if stats['files'] else 'None'}")

        # Show available backends
        print("\n  Transcription Backends:")
        whisper_status = "available" if WHISPER_AVAILABLE else "NOT INSTALLED (pip install openai-whisper)"
        google_status = "available" if GOOGLE_SPEECH_AVAILABLE else "NOT INSTALLED (pip install google-cloud-speech)"
        print(f"    whisper: {whisper_status}")
        print(f"    google: {google_status}")

    elif args.pdfs or args.process_books:
        ingestion.process_all_pdfs()
    elif args.audiobooks:
        ingestion.process_all_audiobooks(args.model, args.backend)
    else:
        ingestion.process_all(args.model, args.backend)

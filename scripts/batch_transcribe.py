"""
Batch Video/Audio Transcription using OpenAI Whisper API
Transcribes MP4/audio files and adds them to the knowledge base.

Handles large files (audiobooks) by splitting into chunks automatically.

Usage:
    python scripts/batch_transcribe.py path/to/audiobooks/
    python scripts/batch_transcribe.py path/to/single_file.m4b
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from openai import OpenAI

# Check which API to use (Groq is free, OpenAI is paid)
def get_transcription_client():
    """Get the best available transcription client (Groq free, OpenAI paid)"""
    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if groq_key:
        # Groq offers FREE Whisper transcription
        print("Using Groq (FREE Whisper transcription)")
        return OpenAI(
            api_key=groq_key,
            base_url="https://api.groq.com/openai/v1"
        ), "groq"
    elif openai_key:
        print("Using OpenAI (paid)")
        return OpenAI(api_key=openai_key), "openai"
    else:
        return None, None


def get_whisper_model(provider: str) -> str:
    """Get the correct Whisper model name for the provider"""
    if provider == "groq":
        return "whisper-large-v3"  # Groq's model name
    else:
        return "whisper-1"  # OpenAI's model name

# Supported audio/video formats (including .m4b audiobooks)
SUPPORTED_FORMATS = {'.mp4', '.mp3', '.m4a', '.m4b', '.wav', '.webm', '.mpeg', '.mpga', '.oga', '.ogg', '.flac'}

# OpenAI file size limit (25MB, use 20MB to be safe)
MAX_CHUNK_SIZE_MB = 20
CHUNK_DURATION_MINUTES = 15  # Split into 15-minute chunks


def check_ffmpeg():
    """Check if ffmpeg is installed."""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_audio_duration(file_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(file_path)
        ], capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0


def split_audio_file(file_path: Path, chunk_dir: Path, chunk_minutes: int = 15) -> list:
    """
    Split a large audio file into smaller chunks using ffmpeg.

    Args:
        file_path: Path to audio file
        chunk_dir: Directory to save chunks
        chunk_minutes: Length of each chunk in minutes

    Returns:
        List of chunk file paths
    """
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_seconds = chunk_minutes * 60

    # Get total duration
    duration = get_audio_duration(file_path)
    if duration == 0:
        print(f"  Warning: Could not determine duration, attempting full file...")
        return [file_path]

    num_chunks = int(duration // chunk_seconds) + 1
    print(f"  Splitting into {num_chunks} chunks (~{chunk_minutes} min each)...")

    chunks = []
    for i in range(num_chunks):
        start_time = i * chunk_seconds
        chunk_name = f"{file_path.stem}_chunk{i:03d}.mp3"
        chunk_path = chunk_dir / chunk_name

        # Use ffmpeg to extract chunk and convert to mp3 (smaller, compatible)
        cmd = [
            'ffmpeg', '-y',  # Overwrite
            '-i', str(file_path),
            '-ss', str(start_time),
            '-t', str(chunk_seconds),
            '-vn',  # No video
            '-acodec', 'libmp3lame',
            '-ab', '64k',  # Lower bitrate for smaller files
            '-ar', '16000',  # 16kHz sample rate (Whisper optimal)
            '-ac', '1',  # Mono
            str(chunk_path)
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            if chunk_path.exists() and chunk_path.stat().st_size > 0:
                chunks.append(chunk_path)
        except subprocess.CalledProcessError as e:
            print(f"  Warning: Failed to create chunk {i}: {e}")

    return chunks


def transcribe_file(client: OpenAI, file_path: Path, provider: str = "openai") -> str:
    """
    Transcribe a single audio/video file using Whisper API.

    Args:
        client: OpenAI-compatible client
        file_path: Path to audio/video file
        provider: 'groq' or 'openai'

    Returns:
        Transcribed text
    """
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    print(f"  Uploading {file_size_mb:.1f}MB...")

    # Get correct model name for provider
    model = get_whisper_model(provider)

    # Financial/trading context prompt improves accuracy for jargon
    TRADING_PROMPT = (
        "This is an audiobook about trading, investing, and financial markets. "
        "Common terms include: EBITDA, P/E ratio, stop loss, take profit, "
        "leverage, margin, candlestick, moving average, RSI, MACD, volume, "
        "options, calls, puts, strike price, expiration, theta, delta, gamma, "
        "bid-ask spread, liquidity, volatility, drawdown, Sharpe ratio, "
        "position sizing, risk management, backtesting, algorithmic trading."
    )

    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="text",
            prompt=TRADING_PROMPT
        )

    return transcript


def transcribe_large_file(client: OpenAI, file_path: Path, provider: str = "openai") -> str:
    """
    Transcribe a large audio file by splitting into chunks.

    Args:
        client: OpenAI-compatible client
        file_path: Path to audio file
        provider: 'groq' or 'openai'

    Returns:
        Combined transcribed text
    """
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    print(f"  Large file detected ({file_size_mb:.1f}MB). Splitting...")

    # Create temp directory for chunks
    temp_dir = Path(tempfile.mkdtemp(prefix="transcribe_"))

    try:
        # Split into chunks
        chunks = split_audio_file(file_path, temp_dir, CHUNK_DURATION_MINUTES)

        if not chunks:
            raise Exception("Failed to split audio file")

        # Transcribe each chunk
        transcripts = []
        for i, chunk_path in enumerate(chunks):
            print(f"  Transcribing chunk {i+1}/{len(chunks)}...")
            try:
                transcript = transcribe_file(client, chunk_path, provider)
                transcripts.append(transcript)
            except Exception as e:
                print(f"  Warning: Chunk {i+1} failed: {e}")
                transcripts.append(f"[Chunk {i+1} transcription failed]")

        # Combine transcripts
        return "\n\n".join(transcripts)

    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def save_transcript(transcript: str, source_file: Path, output_dir: Path) -> Path:
    """
    Save transcript to a text file.

    Args:
        transcript: The transcribed text
        source_file: Original audio/video file
        output_dir: Directory to save transcript

    Returns:
        Path to saved transcript file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create output filename
    output_name = source_file.stem + "_transcript.txt"
    output_path = output_dir / output_name

    # Add metadata header
    content = f"""# Transcript: {source_file.name}
# Transcribed: {datetime.now().isoformat()}
# Source: OpenAI Whisper API

{transcript}
"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  Saved: {output_path}")
    return output_path


def index_transcript(transcript_path: Path, category: str = "audiobook"):
    """
    Add transcript to the knowledge base.

    Args:
        transcript_path: Path to transcript text file
        category: Category for knowledge base
    """
    try:
        from knowledge.text_indexer import index_text_file
        doc_id = index_text_file(str(transcript_path), category)
        print(f"  Indexed: {transcript_path.name} (ID: {doc_id})")
        return doc_id
    except ImportError:
        print(f"  Note: text_indexer not available, transcript saved but not indexed")
        return None
    except Exception as e:
        print(f"  Note: Indexing failed ({e}), transcript saved")
        return None


def batch_transcribe(input_path: str, output_dir: str = None):
    """
    Transcribe all audio/video files in a directory or a single file.

    Args:
        input_path: Path to directory or single file
        output_dir: Output directory (defaults to knowledge/transcripts/)
    """
    # Get transcription client (Groq free, OpenAI paid)
    client, provider = get_transcription_client()
    if not client:
        print("ERROR: No transcription API key found!")
        print("Add one of these to your .env file:")
        print("  GROQ_API_KEY=gsk_...  (FREE - recommended)")
        print("  OPENAI_API_KEY=sk-... (paid)")
        print("\nGet free Groq key at: https://console.groq.com/keys")
        sys.exit(1)

    # Check for ffmpeg (needed for large files)
    has_ffmpeg = check_ffmpeg()
    if not has_ffmpeg:
        print("WARNING: ffmpeg not found. Large files (>25MB) will fail.")
        print("Install ffmpeg: https://ffmpeg.org/download.html")
        print("On Windows with Chocolatey: choco install ffmpeg")
        print("")

    # Set up paths
    input_path = Path(input_path)
    if output_dir:
        output_dir = Path(output_dir)
    else:
        output_dir = project_root / "knowledge" / "transcripts"

    # Find files to transcribe
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = [f for f in input_path.iterdir()
                 if f.suffix.lower() in SUPPORTED_FORMATS]
    else:
        print(f"ERROR: Path not found: {input_path}")
        sys.exit(1)

    if not files:
        print(f"No supported audio/video files found in {input_path}")
        print(f"Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}")
        sys.exit(1)

    # Calculate total size
    total_size_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)

    print(f"\n{'='*60}")
    print(f"BATCH TRANSCRIPTION - Whisper API ({provider.upper()})")
    print(f"{'='*60}")
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")
    print(f"Files to process: {len(files)}")
    print(f"Total size: {total_size_mb:.1f}MB")
    print(f"ffmpeg available: {'Yes' if has_ffmpeg else 'No'}")
    print(f"{'='*60}\n")

    # Process each file
    results = {
        'success': [],
        'failed': []
    }

    for i, file_path in enumerate(files, 1):
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        print(f"\n[{i}/{len(files)}] Processing: {file_path.name} ({file_size_mb:.1f}MB)")

        try:
            # Check if file needs splitting
            if file_size_mb > MAX_CHUNK_SIZE_MB:
                if not has_ffmpeg:
                    raise Exception(f"File too large ({file_size_mb:.1f}MB) and ffmpeg not installed")
                transcript = transcribe_large_file(client, file_path, provider)
            else:
                transcript = transcribe_file(client, file_path, provider)

            # Save
            transcript_path = save_transcript(transcript, file_path, output_dir)

            # Index (optional)
            index_transcript(transcript_path)

            results['success'].append(file_path.name)
            print(f"  SUCCESS")

        except Exception as e:
            print(f"  FAILED: {e}")
            results['failed'].append((file_path.name, str(e)))

    # Summary
    print(f"\n{'='*60}")
    print(f"COMPLETE")
    print(f"{'='*60}")
    print(f"Successful: {len(results['success'])}")
    print(f"Failed: {len(results['failed'])}")

    if results['failed']:
        print(f"\nFailed files:")
        for name, error in results['failed']:
            print(f"  - {name}: {error}")

    print(f"\nTranscripts saved to: {output_dir}")
    print(f"\nNext steps:")
    print(f"  1. Review transcripts in {output_dir}")
    print(f"  2. Run: git add knowledge/transcripts/ && git commit -m 'Add audiobook transcripts'")
    print(f"  3. Push to GitHub to sync across machines")

    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nExamples:")
        print("  python scripts/batch_transcribe.py trading_knowledge\\audiobooks")
        print("  python scripts/batch_transcribe.py C:\\Audiobooks\\trading_book.m4b")
        sys.exit(0)

    input_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    batch_transcribe(input_path, output_dir)

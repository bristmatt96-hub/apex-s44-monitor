"""
Batch Video/Audio Transcription using OpenAI Whisper API
Transcribes MP4/audio files and adds them to the knowledge base.

Usage:
    python scripts/batch_transcribe.py path/to/videos/
    python scripts/batch_transcribe.py path/to/single_file.mp4
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from openai import OpenAI

# Supported audio/video formats
SUPPORTED_FORMATS = {'.mp4', '.mp3', '.m4a', '.wav', '.webm', '.mpeg', '.mpga', '.oga', '.ogg'}

def transcribe_file(client: OpenAI, file_path: Path) -> str:
    """
    Transcribe a single audio/video file using OpenAI Whisper API.

    Args:
        client: OpenAI client
        file_path: Path to audio/video file

    Returns:
        Transcribed text
    """
    print(f"  Transcribing: {file_path.name}...")

    # Check file size (OpenAI limit is 25MB)
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 25:
        print(f"  WARNING: File is {file_size_mb:.1f}MB (limit 25MB). Will attempt anyway...")

    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text"
        )

    return transcript


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


def index_transcript(transcript_path: Path, category: str = "transcript"):
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
        # Fallback: create simple index entry
        print(f"  Note: text_indexer not available, transcript saved but not indexed")
        return None


def batch_transcribe(input_path: str, output_dir: str = None):
    """
    Transcribe all audio/video files in a directory or a single file.

    Args:
        input_path: Path to directory or single file
        output_dir: Output directory (defaults to knowledge/transcripts/)
    """
    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not found in environment or .env file")
        print("Add it to your .env file: OPENAI_API_KEY=sk-...")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

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
        print(f"Supported formats: {', '.join(SUPPORTED_FORMATS)}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"BATCH TRANSCRIPTION - OpenAI Whisper API")
    print(f"{'='*60}")
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")
    print(f"Files to process: {len(files)}")
    print(f"{'='*60}\n")

    # Process each file
    results = {
        'success': [],
        'failed': []
    }

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] Processing: {file_path.name}")

        try:
            # Transcribe
            transcript = transcribe_file(client, file_path)

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
    print(f"  2. Run: git add knowledge/transcripts/ && git commit -m 'Add transcripts'")
    print(f"  3. Push to GitHub to sync across machines")

    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nExamples:")
        print("  python scripts/batch_transcribe.py C:\\Videos\\earnings_calls\\")
        print("  python scripts/batch_transcribe.py ~/Downloads/presentation.mp4")
        sys.exit(0)

    input_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    batch_transcribe(input_path, output_dir)

"""
Earnings Call Transcriber
Upload audio recordings of earnings calls and transcribe them for sentiment analysis
Uses OpenAI Whisper (API or local) for speech-to-text
"""

import streamlit as st
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
import json

# Check for optional dependencies
WHISPER_AVAILABLE = False
OPENAI_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    pass

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    pass


# ============================================================================
# TRANSCRIPTION BACKENDS
# ============================================================================

def transcribe_with_openai_api(audio_path: str, api_key: str) -> Tuple[str, Optional[str]]:
    """
    Transcribe using OpenAI Whisper API.
    Requires: pip install openai
    Cost: ~$0.006 per minute of audio
    """
    if not OPENAI_AVAILABLE:
        return "", "OpenAI package not installed. Run: pip install openai"

    try:
        client = openai.OpenAI(api_key=api_key)

        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )

        return transcript, None

    except Exception as e:
        return "", f"OpenAI API error: {str(e)}"


def transcribe_with_local_whisper(audio_path: str, model_size: str = "base") -> Tuple[str, Optional[str]]:
    """
    Transcribe using local Whisper model.
    Requires: pip install openai-whisper
    Models: tiny, base, small, medium, large
    - tiny/base: Fast, less accurate (good for quick analysis)
    - small/medium: Balanced
    - large: Best accuracy, slow, needs GPU
    """
    if not WHISPER_AVAILABLE:
        return "", "Whisper not installed. Run: pip install openai-whisper"

    try:
        model = whisper.load_model(model_size)
        result = model.transcribe(audio_path)
        return result["text"], None

    except Exception as e:
        return "", f"Whisper error: {str(e)}"


def transcribe_with_assemblyai(audio_path: str, api_key: str) -> Tuple[str, Optional[str]]:
    """
    Transcribe using AssemblyAI API.
    Good for long earnings calls, has speaker diarization.
    Cost: ~$0.00025 per second (~$0.90 per hour)
    """
    try:
        import requests
        import time

        headers = {"authorization": api_key}

        # Upload file
        with open(audio_path, "rb") as f:
            upload_response = requests.post(
                "https://api.assemblyai.com/v2/upload",
                headers=headers,
                data=f
            )
        upload_url = upload_response.json()["upload_url"]

        # Request transcription
        transcript_response = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            headers=headers,
            json={
                "audio_url": upload_url,
                "speaker_labels": True  # Identify different speakers
            }
        )
        transcript_id = transcript_response.json()["id"]

        # Poll for completion
        while True:
            result = requests.get(
                f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                headers=headers
            ).json()

            if result["status"] == "completed":
                return result["text"], None
            elif result["status"] == "error":
                return "", f"AssemblyAI error: {result.get('error', 'Unknown')}"

            time.sleep(3)

    except Exception as e:
        return "", f"AssemblyAI error: {str(e)}"


# ============================================================================
# AUDIO FILE HANDLING
# ============================================================================

SUPPORTED_FORMATS = [".mp3", ".m4a", ".wav", ".mp4", ".webm", ".ogg", ".flac"]

def validate_audio_file(uploaded_file) -> Tuple[bool, str]:
    """Validate uploaded audio file."""
    if uploaded_file is None:
        return False, "No file uploaded"

    # Check extension
    name = uploaded_file.name.lower()
    ext = Path(name).suffix

    if ext not in SUPPORTED_FORMATS:
        return False, f"Unsupported format: {ext}. Supported: {', '.join(SUPPORTED_FORMATS)}"

    # Check size (max 100MB for most APIs)
    size_mb = uploaded_file.size / (1024 * 1024)
    if size_mb > 100:
        return False, f"File too large: {size_mb:.1f}MB. Max: 100MB"

    return True, f"Valid audio file: {name} ({size_mb:.1f}MB)"


def save_uploaded_file(uploaded_file) -> str:
    """Save uploaded file to temp directory and return path."""
    ext = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(uploaded_file.getvalue())
        return tmp.name


# ============================================================================
# STREAMLIT UI
# ============================================================================

def render_call_transcriber():
    """Render the earnings call transcriber UI."""
    st.header("🎙️ Earnings Call Transcriber")
    st.caption("Record earnings calls on your phone, upload here, get instant transcript + sentiment")

    # Recording guide tabs
    tab1, tab2, tab3 = st.tabs(["📱 Recording Guide", "⚙️ Transcribe", "💡 Tips"])

    with tab1:
        st.markdown("## How to Record Earnings Calls")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("""
            ### Android (Recommended Setup)

            **Best Apps:**
            | App | Quality | Free? |
            |-----|---------|-------|
            | **Easy Voice Recorder** | Excellent | Yes |
            | **Hi-Q MP3 Recorder** | High bitrate | Yes |
            | **Samsung Voice Recorder** | Good | Built-in |
            | **Google Recorder** (Pixel) | Best | Built-in |

            **Settings for Best Quality:**
            ```
            Format: M4A or MP3
            Bitrate: 128kbps+ (higher = better)
            Sample rate: 44.1kHz
            ```

            **Direct Call Recording (if dialing in):**
            - **Cube ACR** - Works on most phones
            - **Call Recorder - ACR** - Reliable backup
            - Note: Some carriers/phones block this
            """)

        with col2:
            st.markdown("""
            ### iPhone

            **Voice Memos (Built-in):**
            1. Open Voice Memos app
            2. Tap red record button
            3. Place near speaker
            4. Tap stop when done
            5. Share → Save to Files → Upload here

            **For Direct Call Recording:**
            - **TapeACall** (~$4/month)
            - **Rev Call Recorder** (free, uses their service)

            **AirDrop Tip:**
            Record on iPhone → AirDrop to Mac → Upload
            """)

        st.markdown("---")

        st.markdown("""
        ### Recommended Setup (Best Quality)

        ```
        ┌─────────────────────────────────────────────────────────┐
        │                                                         │
        │   LAPTOP                         PHONE                  │
        │   ┌─────────┐                   ┌─────────┐            │
        │   │ Webcast │ ───speaker───►    │ Record  │            │
        │   │ playing │    ~30cm          │   app   │            │
        │   └─────────┘                   └─────────┘            │
        │       │                              │                  │
        │       │ (wear headphones             │                  │
        │       │  to hear yourself)           ▼                  │
        │                                 Upload M4A              │
        │                                 to this tool            │
        └─────────────────────────────────────────────────────────┘
        ```

        **Why this works:**
        - Webcast audio quality > phone dial-in quality
        - No carrier restrictions on recording
        - Consistent volume levels
        - Works every time

        **Pro tips:**
        - Place phone 20-30cm from laptop speaker
        - Use a quiet room (no echo/background noise)
        - Test with a 30-second clip first
        - Disable phone notifications during recording
        """)

        st.markdown("---")

        st.markdown("""
        ### Finding Earnings Call Dial-ins

        **Where to find webcast/dial-in:**
        1. Company IR page → "Events" or "Presentations"
        2. SEC filing (6-K/8-K) often has dial-in number
        3. Bloomberg: `COMP <GO>` → Events
        4. Google: "[Company] Q3 2025 earnings call webcast"

        **Typical schedule:**
        - US companies: 8-10 AM ET
        - European companies: 8-10 AM CET (2-4 AM ET)
        - Call duration: 45-90 minutes
        """)

    with tab2:
        # Step 1: Upload audio
        st.subheader("Step 1: Upload Recording")

        uploaded_file = st.file_uploader(
            "Upload earnings call recording",
            type=["mp3", "m4a", "wav", "mp4", "webm", "ogg", "flac"],
            help="Record the earnings call on your phone and upload here"
        )

        if uploaded_file:
            valid, message = validate_audio_file(uploaded_file)
            if valid:
                st.success(message)

                # Estimate duration (rough: 1MB ≈ 1 minute for compressed audio)
                size_mb = uploaded_file.size / (1024 * 1024)
                est_duration = size_mb * 1.5  # rough estimate
                st.caption(f"Estimated duration: ~{est_duration:.0f} minutes")
            else:
                st.error(message)
                return

        # Step 2: Choose transcription method
        st.markdown("---")
        st.subheader("Step 2: Choose Transcription Method")

        method = st.radio(
            "Transcription backend:",
            ["OpenAI Whisper API (Recommended)", "Local Whisper (Free)", "AssemblyAI (Speaker Labels)"],
            horizontal=True
        )

        # API key inputs
        api_key = None
        model_size = "base"

        if "OpenAI" in method:
            api_key = st.text_input(
                "OpenAI API Key:",
                type="password",
                help="Get from: https://platform.openai.com/api-keys"
            )
            st.caption("Cost: ~$0.006/minute (~$0.36/hour)")

            if not OPENAI_AVAILABLE:
                st.warning("OpenAI package not installed. Run: `pip install openai`")

        elif "Local" in method:
            model_size = st.select_slider(
                "Model size (larger = more accurate, slower):",
                options=["tiny", "base", "small", "medium", "large"],
                value="base"
            )
            st.caption("First run downloads model. 'base' is good balance of speed/accuracy.")

            if not WHISPER_AVAILABLE:
                st.warning("Whisper not installed. Run: `pip install openai-whisper`")
                st.info("Also needs ffmpeg: `brew install ffmpeg` (Mac) or `apt install ffmpeg` (Linux)")

        elif "AssemblyAI" in method:
            api_key = st.text_input(
                "AssemblyAI API Key:",
                type="password",
                help="Get from: https://www.assemblyai.com/dashboard"
            )
            st.caption("Cost: ~$0.015/minute (~$0.90/hour). Includes speaker identification.")

        # Step 3: Transcribe
        st.markdown("---")
        st.subheader("Step 3: Transcribe")

        company_name = st.text_input("Company name:", placeholder="e.g., Ardagh Group")
        call_date = st.date_input("Call date:", value=datetime.now())

        if st.button("🎯 Transcribe Recording", type="primary", disabled=not uploaded_file):
            if not uploaded_file:
                st.error("Please upload an audio file first")
                return

            # Save file temporarily
            with st.spinner("Saving audio file..."):
                audio_path = save_uploaded_file(uploaded_file)

            # Transcribe
            transcript = ""
            error = None

            if "OpenAI" in method:
                if not api_key:
                    st.error("Please enter your OpenAI API key")
                    return
                with st.spinner("Transcribing with OpenAI Whisper API... (typically 1-2 minutes)"):
                    transcript, error = transcribe_with_openai_api(audio_path, api_key)

            elif "Local" in method:
                with st.spinner(f"Transcribing with local Whisper ({model_size})... (may take a while)"):
                    transcript, error = transcribe_with_local_whisper(audio_path, model_size)

            elif "AssemblyAI" in method:
                if not api_key:
                    st.error("Please enter your AssemblyAI API key")
                    return
                with st.spinner("Transcribing with AssemblyAI... (typically 2-5 minutes)"):
                    transcript, error = transcribe_with_assemblyai(audio_path, api_key)

            # Clean up temp file
            try:
                os.unlink(audio_path)
            except Exception:
                pass

            if error:
                st.error(error)
                return

            if not transcript:
                st.error("Transcription returned empty. Check audio quality.")
                return

            # Success!
            st.success(f"Transcription complete! ({len(transcript)} characters)")

            # Store in session state for sentiment analysis
            st.session_state["last_transcript"] = transcript
            st.session_state["last_transcript_company"] = company_name
            st.session_state["last_transcript_date"] = str(call_date)

            # Show transcript
            st.markdown("---")
            st.subheader("📝 Transcript")

            st.text_area(
                "Full transcript:",
                value=transcript,
                height=400,
                help="Copy this or use 'Analyze Sentiment' below"
            )

            # Word count and stats
            words = len(transcript.split())
            st.caption(f"Words: {words:,} | Characters: {len(transcript):,} | Est. pages: {words // 300}")

            # Download button
            st.download_button(
                "📥 Download Transcript",
                data=transcript,
                file_name=f"{company_name or 'earnings_call'}_{call_date}.txt",
                mime="text/plain"
            )

            # Quick link to sentiment analysis
            st.markdown("---")
            st.subheader("Step 4: Analyze Sentiment")

            if st.button("🔍 Run Sentiment Analysis", type="primary"):
                # Import and run sentiment analyzer
                try:
                    from monitors.earnings_sentiment import analyze_transcript

                    with st.spinner("Analyzing sentiment..."):
                        result = analyze_transcript(transcript, company_name or "Unknown")

                    # Display results
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        color = "🔴" if result.overall_score < -10 else "🟡" if result.overall_score < 10 else "🟢"
                        st.metric("Sentiment", f"{result.overall_score:.0f}")
                        st.caption(color)

                    with col2:
                        st.metric("Mgmt Confidence", f"{result.management_confidence:.0f}%")

                    with col3:
                        high_flags = len([f for f in result.red_flags if f.severity == "HIGH"])
                        st.metric("High Severity Flags", high_flags)

                    # Red flags
                    if result.red_flags:
                        st.markdown("### 🚨 Red Flags Detected")
                        high = [f for f in result.red_flags if f.severity == "HIGH"]
                        for flag in high[:5]:
                            st.warning(f"**{flag.category}**: {flag.text[:100]}...")

                    # Action recommendation
                    st.markdown("---")
                    high_flags = len([f for f in result.red_flags if f.severity == "HIGH"])
                    if high_flags >= 3 or result.overall_score < -20:
                        st.error("⚠️ **ELEVATED CONCERN** - Review CDS levels, check for advisor engagement")
                    elif high_flags >= 1 or result.overall_score < 0:
                        st.warning("🟡 **MONITOR CLOSELY** - Some distress signals detected")
                    else:
                        st.success("🟢 **STABLE** - No significant distress signals")

                except ImportError:
                    st.error("Sentiment analyzer not available")
                except Exception as e:
                    st.error(f"Analysis error: {e}")

        # Show previously transcribed content if available
        if "last_transcript" in st.session_state and not uploaded_file:
            st.markdown("---")
            st.info(f"Previous transcript available: {st.session_state.get('last_transcript_company', 'Unknown')} "
                   f"({st.session_state.get('last_transcript_date', 'Unknown date')})")

            if st.button("Load Previous Transcript"):
                st.text_area(
                    "Previous transcript:",
                    value=st.session_state["last_transcript"],
                    height=300
                )

    with tab3:
        st.markdown("""
        ## Alpha Edge: The Timeline

        ```
        ┌────────────────────────────────────────────────────────────────┐
        │  YOUR WORKFLOW                    vs    EVERYONE ELSE         │
        ├────────────────────────────────────────────────────────────────┤
        │                                                                │
        │  09:00  Earnings call starts      09:00  Waiting for          │
        │         You're recording                 Debtwire...          │
        │                                                                │
        │  10:00  Call ends                 ...                         │
        │         Upload recording                                       │
        │                                                                │
        │  10:05  Transcript ready          ...                         │
        │                                                                │
        │  10:10  Sentiment analysis        ...                         │
        │         complete                                               │
        │                                                                │
        │  10:15  YOU TRADE                 ...                         │
        │         ════════════                                          │
        │                                                                │
        │  Day +9 ...                       Debtwire publishes          │
        │                                   transcript                   │
        │                                   Everyone else reads it       │
        │                                   Market already moved         │
        └────────────────────────────────────────────────────────────────┘
        ```

        ## Cost Comparison

        | Method | Cost/Hour | 1-Hour Call | Speed |
        |--------|-----------|-------------|-------|
        | OpenAI Whisper API | $0.36 | $0.36 | Fast (1-2 min) |
        | AssemblyAI | $0.90 | $0.90 | Medium (2-5 min) |
        | Local Whisper | Free | $0 | Slow (5-15 min) |
        | Debtwire Subscription | ~$30k/yr | N/A | 5-10 days late |

        ## Quality Tips

        **For best transcription accuracy:**

        1. **Use webcast, not phone dial-in**
           - Higher audio quality = better transcription
           - Phone lines compress audio

        2. **Quiet environment**
           - No background noise, TV, conversations
           - Avoid rooms with echo

        3. **Consistent volume**
           - Don't adjust volume during recording
           - Test levels before call starts

        4. **File format**
           - M4A or MP3 preferred
           - 128kbps+ bitrate
           - Mono is fine (stereo doesn't help)

        ## What to Listen For (Live)

        While recording, note timestamps for:

        | Signal | What to Note |
        |--------|--------------|
        | "Restructuring" mentioned | Timestamp + context |
        | Advisor names (Houlihan, PJT) | Huge red flag |
        | Liquidity questions from analysts | Note the answer |
        | Management hedging/evasion | "We'll get back to you" |
        | Covenant discussion | Compliance, waivers |
        | Guidance changes | Up/down/withdrawn |

        These notes + transcript + sentiment = complete picture
        """)

        st.markdown("---")
        st.markdown("### XO S44 Earnings Calendar")
        st.info("Coming soon: Integration with earnings calendar to alert you before calls")


# ============================================================================
# SETUP INSTRUCTIONS
# ============================================================================

def show_setup_instructions():
    """Show setup instructions for transcription backends."""
    st.markdown("""
    ## Setup Instructions

    ### Option 1: OpenAI Whisper API (Recommended)

    ```bash
    pip install openai
    ```

    Then get API key from: https://platform.openai.com/api-keys

    **Pros:** Fast, accurate, no local setup
    **Cons:** Costs ~$0.36/hour of audio


    ### Option 2: Local Whisper (Free)

    ```bash
    # Install Whisper
    pip install openai-whisper

    # Install ffmpeg (required)
    # Mac:
    brew install ffmpeg

    # Linux:
    sudo apt install ffmpeg

    # Windows:
    # Download from ffmpeg.org
    ```

    **Pros:** Free, runs locally, private
    **Cons:** Slower, needs decent CPU/GPU


    ### Option 3: AssemblyAI

    ```bash
    pip install requests
    ```

    Get API key from: https://www.assemblyai.com/dashboard

    **Pros:** Speaker diarization (who said what), good accuracy
    **Cons:** Costs ~$0.90/hour, slower for long files
    """)


if __name__ == "__main__":
    show_setup_instructions()

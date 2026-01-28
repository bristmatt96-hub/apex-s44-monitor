"""
Live Earnings Call Transcriber
Real-time streaming transcription with live distress keyword detection
Analyze while the call is happening - don't wait for it to end
"""

import streamlit as st
import threading
import queue
import time
from datetime import datetime
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass
import json
import re

# ============================================================================
# MEMORY LIMITS - prevent unbounded session_state growth
# ============================================================================
MAX_TRANSCRIPT_CHARS = 500_000   # ~80k words / ~4 hours of speech
MAX_ALERTS = 500                 # max alerts kept in memory

# Check for optional dependencies
DEEPGRAM_AVAILABLE = False
ASSEMBLYAI_RT_AVAILABLE = False
PYAUDIO_AVAILABLE = False

try:
    from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
    DEEPGRAM_AVAILABLE = True
except ImportError:
    pass

try:
    import assemblyai as aai
    ASSEMBLYAI_RT_AVAILABLE = True
except ImportError:
    pass

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pass


# ============================================================================
# DISTRESS KEYWORDS FOR LIVE DETECTION
# ============================================================================

LIVE_ALERT_KEYWORDS = {
    # HIGH PRIORITY - Flash red immediately
    "high": [
        "restructuring", "restructure", "recapitalization", "recapitalisation",
        "liability management", "lme", "debt exchange",
        "houlihan", "pjt partners", "moelis", "lazard", "rothschild",
        "kirkland", "weil gotshal", "milbank", "akin gump",
        "covenant waiver", "covenant holiday", "covenant breach",
        "liquidity concerns", "liquidity crisis", "cash preservation",
        "going concern", "material uncertainty",
        "creditor discussions", "bondholder discussions", "ad hoc group",
        "chapter 11", "administration", "insolvency", "bankruptcy",
        "strategic alternatives", "strategic review",
    ],
    # MEDIUM PRIORITY - Highlight yellow
    "medium": [
        "covenant", "covenants", "leverage ratio", "interest coverage",
        "liquidity", "cash position", "revolver", "credit facility",
        "maturity", "maturities", "refinancing", "refinance",
        "downgrade", "rating agency", "moody's", "s&p", "fitch",
        "challenging", "headwinds", "difficult environment",
        "cost cutting", "cost reduction", "headcount",
        "asset sale", "divestiture", "disposal",
        "guidance", "outlook", "forecast",
        "below expectations", "missed", "shortfall",
    ],
    # LOW PRIORITY - Note but don't alert
    "low": [
        "one-time", "non-recurring", "exceptional", "extraordinary",
        "temporary", "transitory", "short-term",
        "working capital", "capex", "capital expenditure",
        "margin", "ebitda", "revenue", "earnings",
    ]
}

@dataclass
class LiveAlert:
    timestamp: str
    keyword: str
    severity: str
    context: str
    audio_timestamp: Optional[float] = None


# ============================================================================
# LIVE TRANSCRIPTION BACKENDS
# ============================================================================

class LiveTranscriber:
    """Base class for live transcription."""

    def __init__(self, on_transcript: Callable, on_alert: Callable):
        self.on_transcript = on_transcript  # Called with new text
        self.on_alert = on_alert  # Called with LiveAlert
        self.full_transcript = ""
        self.is_running = False
        self.alerts: List[LiveAlert] = []

    def append_transcript(self, text: str):
        """Append text to transcript with memory cap."""
        self.full_transcript += text + " "
        if len(self.full_transcript) > MAX_TRANSCRIPT_CHARS:
            # Keep most recent portion
            self.full_transcript = self.full_transcript[-MAX_TRANSCRIPT_CHARS:]

    def check_for_keywords(self, text: str, audio_time: float = 0):
        """Check new text for distress keywords."""
        text_lower = text.lower()

        for severity, keywords in LIVE_ALERT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    # Get context around keyword
                    idx = text_lower.find(keyword)
                    start = max(0, idx - 30)
                    end = min(len(text), idx + len(keyword) + 30)
                    context = text[start:end]

                    alert = LiveAlert(
                        timestamp=datetime.now().strftime("%H:%M:%S"),
                        keyword=keyword.upper(),
                        severity=severity,
                        context=f"...{context}...",
                        audio_timestamp=audio_time
                    )
                    self.alerts.append(alert)
                    # Cap alerts list to prevent unbounded growth
                    if len(self.alerts) > MAX_ALERTS:
                        self.alerts = self.alerts[-MAX_ALERTS:]
                    self.on_alert(alert)

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class DeepgramLiveTranscriber(LiveTranscriber):
    """
    Real-time transcription using Deepgram.
    Excellent accuracy, ~300ms latency, $0.0043/min
    """

    def __init__(self, api_key: str, on_transcript: Callable, on_alert: Callable):
        super().__init__(on_transcript, on_alert)
        self.api_key = api_key
        self.client = None
        self.connection = None

    def start(self):
        if not DEEPGRAM_AVAILABLE:
            raise RuntimeError("Deepgram not installed. Run: pip install deepgram-sdk")

        self.client = DeepgramClient(self.api_key)
        self.is_running = True

        # Configure live transcription
        options = LiveOptions(
            model="nova-2",  # Best accuracy
            language="en",
            smart_format=True,
            punctuate=True,
            interim_results=True,  # Get partial results
            utterance_end_ms=1000,
            vad_events=True,
        )

        self.connection = self.client.listen.live.v("1")

        def on_message(self, result, **kwargs):
            transcript = result.channel.alternatives[0].transcript
            if transcript:
                if result.is_final:
                    self.append_transcript(transcript)
                    self.check_for_keywords(transcript, result.start)
                self.on_transcript(transcript, result.is_final)

        def on_error(self, error, **kwargs):
            print(f"Deepgram error: {error}")

        self.connection.on(LiveTranscriptionEvents.Transcript, on_message)
        self.connection.on(LiveTranscriptionEvents.Error, on_error)

        self.connection.start(options)

    def send_audio(self, audio_data: bytes):
        """Send audio chunk to Deepgram."""
        if self.connection and self.is_running:
            self.connection.send(audio_data)

    def stop(self):
        self.is_running = False
        if self.connection:
            self.connection.finish()


class AssemblyAILiveTranscriber(LiveTranscriber):
    """
    Real-time transcription using AssemblyAI.
    Good accuracy, speaker labels available, ~1s latency
    """

    def __init__(self, api_key: str, on_transcript: Callable, on_alert: Callable):
        super().__init__(on_transcript, on_alert)
        self.api_key = api_key
        self.transcriber = None

    def start(self):
        if not ASSEMBLYAI_RT_AVAILABLE:
            raise RuntimeError("AssemblyAI RT not installed. Run: pip install assemblyai")

        aai.settings.api_key = self.api_key
        self.is_running = True

        def on_data(transcript: aai.RealtimeTranscript):
            if transcript.text:
                is_final = isinstance(transcript, aai.RealtimeFinalTranscript)
                if is_final:
                    self.append_transcript(transcript.text)
                    self.check_for_keywords(transcript.text)
                self.on_transcript(transcript.text, is_final)

        def on_error(error: aai.RealtimeError):
            print(f"AssemblyAI error: {error}")

        self.transcriber = aai.RealtimeTranscriber(
            on_data=on_data,
            on_error=on_error,
            sample_rate=16000,
        )
        self.transcriber.connect()

    def send_audio(self, audio_data: bytes):
        """Send audio chunk to AssemblyAI."""
        if self.transcriber and self.is_running:
            self.transcriber.stream(audio_data)

    def stop(self):
        self.is_running = False
        if self.transcriber:
            self.transcriber.close()


# ============================================================================
# AUDIO CAPTURE
# ============================================================================

class SystemAudioCapture:
    """
    Capture system audio (what you hear from speakers).
    This captures the webcast/call audio.
    """

    def __init__(self, callback: Callable):
        self.callback = callback
        self.is_running = False
        self.stream = None
        self.pa = None

    def get_loopback_device(self):
        """Find loopback/system audio device."""
        if not PYAUDIO_AVAILABLE:
            return None

        self.pa = pyaudio.PyAudio()

        # Look for loopback device
        for i in range(self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(i)
            name = info.get("name", "").lower()

            # Common loopback device names
            if any(x in name for x in ["loopback", "stereo mix", "what u hear", "wave out"]):
                return i

            # macOS: BlackHole or Soundflower
            if any(x in name for x in ["blackhole", "soundflower"]):
                return i

        return None

    def start(self, device_index: Optional[int] = None):
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError("PyAudio not installed. Run: pip install pyaudio")

        self.pa = pyaudio.PyAudio()
        self.is_running = True

        # Audio settings
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000
        CHUNK = 1024

        self.stream = self.pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK,
            stream_callback=self._audio_callback
        )
        self.stream.start_stream()

    def _audio_callback(self, in_data, frame_count, time_info, status):
        if self.is_running:
            self.callback(in_data)
        return (in_data, pyaudio.paContinue)

    def stop(self):
        self.is_running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.pa:
            self.pa.terminate()


# ============================================================================
# STREAMLIT UI
# ============================================================================

def render_live_transcriber():
    """Render the live transcription UI."""
    st.header("🔴 LIVE Earnings Call Transcriber")
    st.caption("Real-time transcription with instant distress keyword alerts")

    # Show the value proposition
    with st.expander("⚡ Why Live Transcription?"):
        st.markdown("""
        ### The Speed Advantage

        | Traditional | Live |
        |-------------|------|
        | Call ends at 10:00 | Transcript appears word-by-word |
        | Upload recording | **See "restructuring" at 9:15** |
        | Wait 2-5 min for transcription | **Get alert instantly** |
        | Then run sentiment | **Analyze during call** |
        | Trade at 10:10 | **Trade at 9:16** |

        ### How It Works

        ```
        Webcast Audio → Your Computer → Live API → Transcript
              ↓                              ↓
        You're listening              Keywords flagged instantly
        ```

        ### Setup Required

        **To capture system audio (what your speakers play):**

        **Mac:**
        - Install BlackHole: `brew install blackhole-2ch`
        - Set BlackHole as audio output in System Preferences
        - Select BlackHole as input in this app

        **Windows:**
        - Enable "Stereo Mix" in Sound settings
        - Or install VB-Cable (free virtual audio cable)

        **Linux:**
        - PulseAudio monitor source (usually works out of box)
        """)

    st.markdown("---")

    # Service selection
    col1, col2 = st.columns(2)

    with col1:
        service = st.radio(
            "Transcription Service:",
            ["Deepgram (Recommended)", "AssemblyAI"],
            help="Deepgram: ~300ms latency, $0.0043/min. AssemblyAI: ~1s latency, has speaker labels"
        )

    with col2:
        if "Deepgram" in service:
            api_key = st.text_input(
                "Deepgram API Key:",
                type="password",
                help="Get free key: https://console.deepgram.com"
            )
            st.caption("$0.0043/min (~$0.26/hour) - 300ms latency")
        else:
            api_key = st.text_input(
                "AssemblyAI API Key:",
                type="password",
                help="Get key: https://www.assemblyai.com"
            )
            st.caption("$0.015/min (~$0.90/hour) - 1s latency")

    # Company info
    company_name = st.text_input("Company Name:", placeholder="e.g., Ardagh Group")

    st.markdown("---")

    # Initialize session state
    if "live_transcript" not in st.session_state:
        st.session_state.live_transcript = ""
    if "live_alerts" not in st.session_state:
        st.session_state.live_alerts = []
    if "is_transcribing" not in st.session_state:
        st.session_state.is_transcribing = False

    # Control buttons
    col1, col2, col3 = st.columns(3)

    with col1:
        start_button = st.button(
            "🔴 Start Live Transcription",
            type="primary",
            disabled=st.session_state.is_transcribing or not api_key
        )

    with col2:
        stop_button = st.button(
            "⏹️ Stop",
            disabled=not st.session_state.is_transcribing
        )

    with col3:
        clear_button = st.button("🗑️ Clear")

    if clear_button:
        st.session_state.live_transcript = ""
        st.session_state.live_alerts = []
        st.rerun()

    # Main display area
    st.markdown("---")

    # Two columns: transcript and alerts
    col_transcript, col_alerts = st.columns([2, 1])

    with col_transcript:
        st.subheader("📝 Live Transcript")

        # Transcript display area
        transcript_placeholder = st.empty()
        transcript_placeholder.text_area(
            "Transcript:",
            value=st.session_state.live_transcript or "Waiting for audio...",
            height=400,
            disabled=True,
            key="transcript_display"
        )

        # Word count
        if st.session_state.live_transcript:
            words = len(st.session_state.live_transcript.split())
            st.caption(f"Words: {words:,}")

    with col_alerts:
        st.subheader("🚨 Live Alerts")

        # Alert display
        alert_container = st.container()

        with alert_container:
            if st.session_state.live_alerts:
                for alert in reversed(st.session_state.live_alerts[-10:]):  # Last 10 alerts
                    if alert.severity == "high":
                        st.error(f"**{alert.timestamp}** - {alert.keyword}\n{alert.context}")
                    elif alert.severity == "medium":
                        st.warning(f"**{alert.timestamp}** - {alert.keyword}\n{alert.context}")
                    else:
                        st.info(f"**{alert.timestamp}** - {alert.keyword}")
            else:
                st.info("No alerts yet. Keywords will appear here when detected.")

        # Alert summary
        if st.session_state.live_alerts:
            high_count = len([a for a in st.session_state.live_alerts if a.severity == "high"])
            med_count = len([a for a in st.session_state.live_alerts if a.severity == "medium"])

            st.markdown("---")
            st.markdown(f"**Summary:** 🔴 {high_count} high | 🟡 {med_count} medium")

            if high_count >= 2:
                st.error("⚠️ Multiple high-severity alerts - Consider trading NOW")

    # Instructions if not started
    if not st.session_state.is_transcribing and not st.session_state.live_transcript:
        st.markdown("---")
        st.markdown("""
        ### Quick Start

        1. **Setup audio routing** (one-time):
           - Mac: Install BlackHole, route audio through it
           - Windows: Enable Stereo Mix
           - Or: Use microphone to pick up speaker audio

        2. **Start the earnings call webcast** in your browser

        3. **Click "Start Live Transcription"** above

        4. **Watch for alerts** in the right panel

        5. **Trade when you see HIGH severity alerts** - you're ahead of everyone waiting for Debtwire
        """)

    # Simulated demo mode (for testing without real audio)
    st.markdown("---")
    with st.expander("🧪 Demo Mode (Test without audio setup)"):
        st.markdown("Paste sample text to see how keyword detection works:")

        demo_text = st.text_area(
            "Sample earnings call text:",
            placeholder="e.g., 'We have engaged Houlihan Lokey as our restructuring advisor...'",
            height=100
        )

        if st.button("🔍 Test Keyword Detection"):
            if demo_text:
                # Simulate detection (with memory cap)
                st.session_state.live_transcript += demo_text + " "
                if len(st.session_state.live_transcript) > MAX_TRANSCRIPT_CHARS:
                    st.session_state.live_transcript = st.session_state.live_transcript[-MAX_TRANSCRIPT_CHARS:]

                # Check for keywords
                text_lower = demo_text.lower()
                for severity, keywords in LIVE_ALERT_KEYWORDS.items():
                    for keyword in keywords:
                        if keyword in text_lower:
                            alert = LiveAlert(
                                timestamp=datetime.now().strftime("%H:%M:%S"),
                                keyword=keyword.upper(),
                                severity=severity,
                                context=demo_text[:60] + "..."
                            )
                            st.session_state.live_alerts.append(alert)

                # Cap alerts list
                if len(st.session_state.live_alerts) > MAX_ALERTS:
                    st.session_state.live_alerts = st.session_state.live_alerts[-MAX_ALERTS:]

                st.rerun()

    # Download transcript
    if st.session_state.live_transcript:
        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            st.download_button(
                "📥 Download Transcript",
                data=st.session_state.live_transcript,
                file_name=f"{company_name or 'earnings_call'}_live_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain"
            )

        with col2:
            if st.button("🔍 Run Full Sentiment Analysis"):
                try:
                    from monitors.earnings_sentiment import analyze_transcript

                    with st.spinner("Analyzing..."):
                        result = analyze_transcript(st.session_state.live_transcript, company_name or "Unknown")

                    st.metric("Sentiment Score", f"{result.overall_score:.0f}")
                    st.metric("Management Confidence", f"{result.management_confidence:.0f}%")

                    high_flags = len([f for f in result.red_flags if f.severity == "HIGH"])
                    if high_flags >= 3:
                        st.error("⚠️ ELEVATED CONCERN - Review CDS levels immediately")
                    elif high_flags >= 1:
                        st.warning("🟡 MONITOR CLOSELY")
                    else:
                        st.success("🟢 STABLE")

                except Exception as e:
                    st.error(f"Analysis error: {e}")


# ============================================================================
# SETUP INSTRUCTIONS
# ============================================================================

def show_audio_setup():
    """Show detailed audio setup instructions."""
    st.markdown("""
    # Audio Setup for Live Transcription

    To capture what your speakers are playing (the earnings call webcast),
    you need to route system audio to a virtual input device.

    ## macOS Setup

    ### Option 1: BlackHole (Recommended, Free)

    ```bash
    # Install via Homebrew
    brew install blackhole-2ch

    # Or download from: https://existential.audio/blackhole/
    ```

    **After installing:**
    1. Open "Audio MIDI Setup" (search in Spotlight)
    2. Click "+" → "Create Multi-Output Device"
    3. Check both "BlackHole 2ch" and your speakers
    4. Set this as your output device
    5. In this app, select "BlackHole 2ch" as input

    ### Option 2: Soundflower (Older, still works)
    - Download from GitHub
    - Similar setup to BlackHole

    ## Windows Setup

    ### Option 1: Stereo Mix (Built-in, if available)
    1. Right-click speaker icon → Sound settings
    2. Sound Control Panel → Recording tab
    3. Right-click → Show Disabled Devices
    4. Enable "Stereo Mix"
    5. Select it as input in this app

    ### Option 2: VB-Cable (Free virtual cable)
    1. Download from https://vb-audio.com/Cable/
    2. Set "CABLE Input" as your output
    3. Select "CABLE Output" as input here
    4. Use a multi-output to still hear audio

    ## Linux Setup

    PulseAudio usually has a monitor source that captures system audio:

    ```bash
    # List sources
    pactl list short sources

    # Look for something like:
    # alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
    ```

    ## Alternative: Microphone Method

    If you can't set up virtual audio:
    1. Play webcast through speakers
    2. Use microphone as input
    3. Position mic near speaker
    4. Works, but lower quality
    """)


if __name__ == "__main__":
    show_audio_setup()

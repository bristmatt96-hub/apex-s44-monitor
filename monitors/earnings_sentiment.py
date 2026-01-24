"""
Earnings Call Sentiment Analyzer
Analyzes earnings transcripts for distress signals, management tone, and key metrics
Built for EUR HY credit monitoring - focuses on leverage, liquidity, and restructuring language
"""

import streamlit as st
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

class SentimentScore(Enum):
    VERY_NEGATIVE = -2
    NEGATIVE = -1
    NEUTRAL = 0
    POSITIVE = 1
    VERY_POSITIVE = 2

@dataclass
class MetricExtraction:
    metric_name: str
    value: str
    context: str
    yoy_change: Optional[str] = None

@dataclass
class RedFlag:
    category: str
    text: str
    severity: str  # HIGH, MEDIUM, LOW
    explanation: str

@dataclass
class SentimentResult:
    overall_score: float  # -100 to +100
    management_confidence: float  # 0-100
    distress_signals: int  # count
    red_flags: List[RedFlag]
    metrics_extracted: List[MetricExtraction]
    key_quotes: List[str]
    analyst_concerns: List[str]
    summary: str

# ============================================================================
# DISTRESS LANGUAGE DICTIONARIES
# ============================================================================

DISTRESS_PHRASES = {
    # Liquidity concerns (HIGH severity)
    "liquidity concerns": ("HIGH", "Direct admission of liquidity stress"),
    "tight liquidity": ("HIGH", "Liquidity under pressure"),
    "liquidity position": ("MEDIUM", "Discussing liquidity - context matters"),
    "cash preservation": ("HIGH", "Defensive cash management"),
    "preserve cash": ("HIGH", "Defensive cash management"),
    "draw on revolver": ("MEDIUM", "Using credit facilities"),
    "fully drawn": ("HIGH", "Credit facilities exhausted"),
    "covenant waiver": ("HIGH", "Breaching financial covenants"),
    "covenant holiday": ("HIGH", "Negotiating with lenders"),
    "amend and extend": ("MEDIUM", "Maturity management"),
    "refinancing risk": ("HIGH", "Upcoming debt concerns"),

    # Restructuring language (HIGH severity)
    "restructuring": ("HIGH", "Active restructuring discussion"),
    "recapitalization": ("MEDIUM", "Balance sheet restructuring"),
    "liability management": ("HIGH", "LME in progress or planned"),
    "debt exchange": ("HIGH", "Distressed exchange likely"),
    "tender offer": ("MEDIUM", "Buying back debt - could be opportunistic or distressed"),
    "consent solicitation": ("HIGH", "Changing bond terms"),
    "bondholder discussions": ("HIGH", "Negotiating with creditors"),
    "creditor discussions": ("HIGH", "Active creditor negotiations"),
    "advisor": ("MEDIUM", "Could be restructuring advisor"),
    "houlihan": ("HIGH", "Restructuring advisor engaged"),
    "pjt partners": ("HIGH", "Restructuring advisor engaged"),
    "moelis": ("HIGH", "Restructuring advisor engaged"),
    "kirkland": ("HIGH", "Restructuring counsel engaged"),
    "weil gotshal": ("HIGH", "Restructuring counsel engaged"),
    "milbank": ("HIGH", "Restructuring counsel engaged"),

    # Operational distress (MEDIUM-HIGH)
    "cost cutting": ("MEDIUM", "Defensive measures"),
    "headcount reduction": ("MEDIUM", "Cutting staff"),
    "plant closure": ("HIGH", "Significant operational changes"),
    "asset sale": ("MEDIUM", "Deleveraging or distress - context matters"),
    "strategic alternatives": ("HIGH", "Often precedes major changes"),
    "going concern": ("HIGH", "Auditor concerns"),
    "material uncertainty": ("HIGH", "Auditor language for distress"),

    # Hedging/defensive language (LOW-MEDIUM)
    "challenging environment": ("LOW", "Standard defensive language"),
    "headwinds": ("LOW", "Acknowledging difficulties"),
    "unprecedented": ("LOW", "Often used to excuse poor results"),
    "one-time": ("LOW", "Adjusting out bad items"),
    "non-recurring": ("LOW", "Adjusting out bad items"),
    "temporary": ("LOW", "Downplaying issues"),
    "transitory": ("LOW", "Downplaying issues"),

    # Leverage/credit concerns
    "deleveraging": ("MEDIUM", "Working to reduce debt"),
    "covenant compliance": ("MEDIUM", "Monitoring covenants closely"),
    "rating agency": ("LOW", "Discussing ratings"),
    "downgrade": ("HIGH", "Rating action or risk"),
    "negative outlook": ("MEDIUM", "Rating agency concern"),
    "credit watch": ("HIGH", "Imminent rating action"),

    # Cash flow concerns
    "working capital pressure": ("MEDIUM", "Cash tied up in operations"),
    "negative free cash flow": ("HIGH", "Burning cash"),
    "cash burn": ("HIGH", "Direct admission of cash burn"),
    "below expectations": ("MEDIUM", "Missing targets"),
    "revised guidance": ("MEDIUM", "Changing forecasts - direction matters"),
    "withdrawn guidance": ("HIGH", "Cannot forecast - major uncertainty"),
}

POSITIVE_PHRASES = {
    "strong liquidity": ("Healthy cash position", 2),
    "ample liquidity": ("Comfortable cash position", 2),
    "well capitalized": ("Balance sheet strength", 2),
    "no near-term maturities": ("Runway on debt", 3),
    "investment grade": ("Strong credit quality", 3),
    "upgraded": ("Improving credit", 3),
    "positive outlook": ("Rating agency confidence", 2),
    "record results": ("Strong performance", 2),
    "ahead of expectations": ("Beating targets", 2),
    "raised guidance": ("Improving outlook", 2),
    "organic growth": ("Core business growing", 1),
    "market share gains": ("Competitive strength", 1),
    "pricing power": ("Strong market position", 2),
    "margin expansion": ("Improving profitability", 2),
    "cash generation": ("Positive cash flow", 2),
    "dividend increase": ("Confidence in outlook", 1),
    "buyback": ("Returning capital", 1),
    "deleveraged": ("Reduced debt burden", 2),
}

MANAGEMENT_EVASION_PHRASES = [
    "let me get back to you",
    "we'll provide more detail",
    "that's commercially sensitive",
    "we don't disclose",
    "i can't comment on",
    "it's too early to say",
    "we're not going to speculate",
    "we'll see how things develop",
    "next question",
    "i think we've covered that",
]

Q_AND_A_CONCERN_PATTERNS = [
    r"concerned about",
    r"worried about",
    r"risk of",
    r"what happens if",
    r"worst case",
    r"downside scenario",
    r"covenant",
    r"liquidity",
    r"maturity wall",
    r"refinancing",
    r"can you survive",
    r"runway",
    r"burn rate",
]

# ============================================================================
# METRIC EXTRACTION PATTERNS
# ============================================================================

METRIC_PATTERNS = {
    "ebitda": [
        r"(?:adjusted\s+)?ebitda\s+(?:of\s+)?(?:EUR|USD|\$|€)?\s*([\d,.]+)\s*(?:million|billion|m|bn)?",
        r"(?:EUR|USD|\$|€)\s*([\d,.]+)\s*(?:million|billion|m|bn)?\s+(?:adjusted\s+)?ebitda",
    ],
    "leverage": [
        r"(?:net\s+)?leverage\s+(?:ratio\s+)?(?:of\s+)?([\d.]+)x",
        r"([\d.]+)x\s+(?:net\s+)?leverage",
        r"debt\s+to\s+ebitda\s+(?:of\s+)?([\d.]+)",
    ],
    "revenue": [
        r"revenue\s+(?:of\s+)?(?:EUR|USD|\$|€)?\s*([\d,.]+)\s*(?:million|billion|m|bn)?",
        r"(?:EUR|USD|\$|€)\s*([\d,.]+)\s*(?:million|billion|m|bn)?\s+(?:in\s+)?revenue",
    ],
    "liquidity": [
        r"liquidity\s+(?:of\s+)?(?:EUR|USD|\$|€)?\s*([\d,.]+)\s*(?:million|billion|m|bn)?",
        r"(?:EUR|USD|\$|€)\s*([\d,.]+)\s*(?:million|billion|m|bn)?\s+(?:of\s+)?liquidity",
        r"cash\s+(?:and\s+equivalents\s+)?(?:of\s+)?(?:EUR|USD|\$|€)?\s*([\d,.]+)",
    ],
    "margin": [
        r"(?:ebitda\s+)?margin\s+(?:of\s+)?([\d.]+)%",
        r"([\d.]+)%\s+(?:ebitda\s+)?margin",
    ],
    "capex": [
        r"(?:capital\s+expenditure|capex)\s+(?:of\s+)?(?:EUR|USD|\$|€)?\s*([\d,.]+)",
    ],
    "interest_coverage": [
        r"interest\s+coverage\s+(?:of\s+)?([\d.]+)x",
        r"([\d.]+)x\s+interest\s+coverage",
    ],
}

YOY_PATTERNS = [
    r"(up|down|increased|decreased|grew|fell|declined)\s+(\d+(?:\.\d+)?)\s*%?\s+(?:year[- ]over[- ]year|yoy|y/y|versus last year)",
    r"(\d+(?:\.\d+)?)\s*%\s+(higher|lower|increase|decrease)\s+(?:than|versus|compared to)\s+(?:last year|prior year)",
]


# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================

def extract_metrics(text: str) -> List[MetricExtraction]:
    """Extract financial metrics from transcript text."""
    metrics = []
    text_lower = text.lower()

    for metric_name, patterns in METRIC_PATTERNS.items():
        for pattern in patterns:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                # Get surrounding context (50 chars each side)
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].replace('\n', ' ').strip()

                # Look for YoY change nearby
                yoy_change = None
                context_window = text[max(0, match.start()-100):min(len(text), match.end()+100)].lower()
                for yoy_pattern in YOY_PATTERNS:
                    yoy_match = re.search(yoy_pattern, context_window)
                    if yoy_match:
                        yoy_change = yoy_match.group(0)
                        break

                metrics.append(MetricExtraction(
                    metric_name=metric_name.upper(),
                    value=match.group(1),
                    context=f"...{context}...",
                    yoy_change=yoy_change
                ))

    return metrics


def find_distress_signals(text: str) -> Tuple[List[RedFlag], int]:
    """Identify distress-related language in transcript."""
    red_flags = []
    text_lower = text.lower()

    for phrase, (severity, explanation) in DISTRESS_PHRASES.items():
        # Find all occurrences
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        matches = pattern.finditer(text)

        for match in matches:
            # Get context
            start = max(0, match.start() - 75)
            end = min(len(text), match.end() + 75)
            context = text[start:end].replace('\n', ' ').strip()

            red_flags.append(RedFlag(
                category=phrase.upper(),
                text=f"...{context}...",
                severity=severity,
                explanation=explanation
            ))

    # Count unique high-severity flags
    high_severity_count = len([f for f in red_flags if f.severity == "HIGH"])

    return red_flags, high_severity_count


def calculate_sentiment_score(text: str, red_flags: List[RedFlag]) -> float:
    """Calculate overall sentiment score from -100 to +100."""
    text_lower = text.lower()

    # Start at neutral
    score = 0.0

    # Negative scoring from red flags
    for flag in red_flags:
        if flag.severity == "HIGH":
            score -= 10
        elif flag.severity == "MEDIUM":
            score -= 5
        else:
            score -= 2

    # Positive scoring
    for phrase, (_, points) in POSITIVE_PHRASES.items():
        count = text_lower.count(phrase.lower())
        score += count * points * 3

    # Normalize to -100 to +100
    score = max(-100, min(100, score))

    return score


def assess_management_confidence(text: str) -> float:
    """Score management confidence/defensiveness (0-100, higher = more confident)."""
    text_lower = text.lower()

    confidence = 50.0  # Start neutral

    # Deduct for evasion
    for phrase in MANAGEMENT_EVASION_PHRASES:
        count = text_lower.count(phrase)
        confidence -= count * 5

    # Deduct for hedging language
    hedging_words = ["may", "might", "could", "possibly", "potentially", "uncertain"]
    for word in hedging_words:
        # Count but weight less than evasion
        count = len(re.findall(r'\b' + word + r'\b', text_lower))
        confidence -= count * 0.5

    # Add for confident language
    confident_words = ["will", "committed", "confident", "certain", "definitely", "absolutely"]
    for word in confident_words:
        count = len(re.findall(r'\b' + word + r'\b', text_lower))
        confidence += count * 1

    # Normalize
    confidence = max(0, min(100, confidence))

    return confidence


def extract_analyst_concerns(text: str) -> List[str]:
    """Extract questions/concerns raised by analysts in Q&A."""
    concerns = []

    # Split into Q&A section if possible
    qa_markers = ["question-and-answer", "q&a", "questions and answers", "operator:"]
    qa_start = len(text)

    text_lower = text.lower()
    for marker in qa_markers:
        pos = text_lower.find(marker)
        if pos != -1 and pos < qa_start:
            qa_start = pos

    qa_section = text[qa_start:] if qa_start < len(text) else text

    # Find concern patterns
    for pattern in Q_AND_A_CONCERN_PATTERNS:
        matches = re.finditer(pattern, qa_section, re.IGNORECASE)
        for match in matches:
            # Get sentence context
            start = max(0, match.start() - 50)
            end = min(len(qa_section), match.end() + 100)

            # Find sentence boundaries
            context = qa_section[start:end]

            # Clean up
            context = context.replace('\n', ' ').strip()
            if len(context) > 20:
                concerns.append(f"...{context}...")

    return concerns[:10]  # Limit to top 10


def extract_key_quotes(text: str, red_flags: List[RedFlag]) -> List[str]:
    """Extract most important quotes from the transcript."""
    quotes = []

    # Get unique contexts from high-severity red flags
    seen = set()
    for flag in sorted(red_flags, key=lambda x: x.severity == "HIGH", reverse=True):
        if flag.text not in seen:
            quotes.append(flag.text)
            seen.add(flag.text)
            if len(quotes) >= 5:
                break

    return quotes


def analyze_transcript(text: str, company_name: str = "Unknown") -> SentimentResult:
    """Main analysis function - analyzes full transcript."""

    # Extract metrics
    metrics = extract_metrics(text)

    # Find distress signals
    red_flags, distress_count = find_distress_signals(text)

    # Calculate scores
    sentiment_score = calculate_sentiment_score(text, red_flags)
    management_confidence = assess_management_confidence(text)

    # Extract concerns and quotes
    analyst_concerns = extract_analyst_concerns(text)
    key_quotes = extract_key_quotes(text, red_flags)

    # Generate summary
    if sentiment_score < -30:
        sentiment_label = "HIGHLY NEGATIVE"
    elif sentiment_score < -10:
        sentiment_label = "NEGATIVE"
    elif sentiment_score < 10:
        sentiment_label = "NEUTRAL"
    elif sentiment_score < 30:
        sentiment_label = "POSITIVE"
    else:
        sentiment_label = "HIGHLY POSITIVE"

    high_flags = len([f for f in red_flags if f.severity == "HIGH"])
    medium_flags = len([f for f in red_flags if f.severity == "MEDIUM"])

    summary = f"""
{company_name} Earnings Call Analysis
=====================================
Overall Sentiment: {sentiment_label} ({sentiment_score:.1f}/100)
Management Confidence: {management_confidence:.1f}/100
Distress Signals: {high_flags} HIGH, {medium_flags} MEDIUM severity
Metrics Extracted: {len(metrics)}
Analyst Concerns Flagged: {len(analyst_concerns)}
"""

    return SentimentResult(
        overall_score=sentiment_score,
        management_confidence=management_confidence,
        distress_signals=distress_count,
        red_flags=red_flags,
        metrics_extracted=metrics,
        key_quotes=key_quotes,
        analyst_concerns=analyst_concerns,
        summary=summary.strip()
    )


# ============================================================================
# STREAMLIT UI
# ============================================================================

def render_earnings_analyzer():
    """Render the earnings call sentiment analyzer in Streamlit."""
    st.header("📊 Earnings Call Sentiment Analyzer")
    st.caption("Analyze earnings transcripts for distress signals and management tone")

    # Input
    transcript_text = st.text_area(
        "Paste earnings call transcript:",
        height=300,
        placeholder="Paste the full earnings call transcript here..."
    )

    company_name = st.text_input("Company Name:", placeholder="e.g., Ardagh Group")

    if st.button("🔍 Analyze Transcript", type="primary"):
        if not transcript_text:
            st.error("Please paste a transcript to analyze")
            return

        with st.spinner("Analyzing transcript..."):
            result = analyze_transcript(transcript_text, company_name or "Unknown")

        # Display results
        st.markdown("---")

        # Summary metrics in columns
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            sentiment_color = "🔴" if result.overall_score < -10 else "🟡" if result.overall_score < 10 else "🟢"
            st.metric(
                "Sentiment Score",
                f"{result.overall_score:.1f}",
                delta=None
            )
            st.caption(sentiment_color + " " + ("Negative" if result.overall_score < -10 else "Neutral" if result.overall_score < 10 else "Positive"))

        with col2:
            conf_color = "🔴" if result.management_confidence < 40 else "🟡" if result.management_confidence < 60 else "🟢"
            st.metric(
                "Mgmt Confidence",
                f"{result.management_confidence:.1f}%"
            )
            st.caption(conf_color + " " + ("Low" if result.management_confidence < 40 else "Medium" if result.management_confidence < 60 else "High"))

        with col3:
            high_flags = len([f for f in result.red_flags if f.severity == "HIGH"])
            st.metric(
                "High Severity Flags",
                high_flags
            )
            st.caption("🔴 Distress signals" if high_flags > 3 else "🟡 Some concerns" if high_flags > 0 else "🟢 Clean")

        with col4:
            st.metric(
                "Metrics Found",
                len(result.metrics_extracted)
            )

        # Tabs for detailed results
        tab1, tab2, tab3, tab4 = st.tabs([
            "🚨 Red Flags",
            "📈 Metrics",
            "❓ Analyst Concerns",
            "💬 Key Quotes"
        ])

        with tab1:
            if result.red_flags:
                # Group by severity
                high = [f for f in result.red_flags if f.severity == "HIGH"]
                medium = [f for f in result.red_flags if f.severity == "MEDIUM"]
                low = [f for f in result.red_flags if f.severity == "LOW"]

                if high:
                    st.subheader("🔴 HIGH Severity")
                    for flag in high[:10]:
                        with st.expander(f"**{flag.category}** - {flag.explanation}"):
                            st.write(flag.text)

                if medium:
                    st.subheader("🟡 MEDIUM Severity")
                    for flag in medium[:10]:
                        with st.expander(f"**{flag.category}** - {flag.explanation}"):
                            st.write(flag.text)

                if low:
                    st.subheader("🟢 LOW Severity")
                    for flag in low[:5]:
                        with st.expander(f"**{flag.category}** - {flag.explanation}"):
                            st.write(flag.text)
            else:
                st.success("No distress signals detected!")

        with tab2:
            if result.metrics_extracted:
                for metric in result.metrics_extracted:
                    col_a, col_b = st.columns([1, 3])
                    with col_a:
                        st.markdown(f"**{metric.metric_name}**")
                        st.markdown(f"### {metric.value}")
                        if metric.yoy_change:
                            st.caption(f"YoY: {metric.yoy_change}")
                    with col_b:
                        st.caption(metric.context)
                    st.markdown("---")
            else:
                st.info("No metrics extracted. Try including more financial data in the transcript.")

        with tab3:
            if result.analyst_concerns:
                for i, concern in enumerate(result.analyst_concerns, 1):
                    st.markdown(f"**{i}.** {concern}")
            else:
                st.info("No analyst concerns flagged in Q&A section.")

        with tab4:
            if result.key_quotes:
                for quote in result.key_quotes:
                    st.markdown(f"> {quote}")
                    st.markdown("---")
            else:
                st.info("No key quotes extracted.")

        # Overall assessment
        st.markdown("---")
        st.subheader("📋 Overall Assessment")

        # Credit-focused interpretation
        high_flags = len([f for f in result.red_flags if f.severity == "HIGH"])

        if high_flags >= 5 or result.overall_score < -30:
            st.error("""
            **⚠️ ELEVATED CREDIT CONCERN**

            Multiple distress signals detected. This transcript suggests:
            - Active restructuring discussions or advisor engagement
            - Liquidity/covenant concerns mentioned
            - Management may be in defensive mode

            **Action:** Review CDS levels, check for advisor hires, monitor for LME announcement
            """)
        elif high_flags >= 2 or result.overall_score < -10:
            st.warning("""
            **🟡 MODERATE CONCERN**

            Some distress-related language detected. Consider:
            - Monitoring upcoming maturities
            - Checking covenant headroom
            - Watching for guidance changes

            **Action:** Add to watchlist, increase monitoring frequency
            """)
        else:
            st.success("""
            **🟢 STABLE**

            No significant distress signals detected in this transcript.
            Standard monitoring appropriate.
            """)


# ============================================================================
# CLI TESTING
# ============================================================================

if __name__ == "__main__":
    # Test with sample text
    sample = """
    Our adjusted EBITDA for the nine months was USD 1.072 billion, representing a 7% increase year-over-year.
    Net leverage at the restricted group level was 8.2x pre-recapitalization, and we expect this to reduce
    to approximately 5.4x post-recapitalization. We have strong liquidity of over $500 million.

    The recapitalization was completed on November 12th. We engaged Houlihan Lokey as our advisor
    during this process. Our covenant compliance remains tight but manageable.

    Q&A:
    Analyst: I'm concerned about the maturity wall in 2027. What's your refinancing plan?
    Management: We're confident in our ability to address the maturities well in advance.
    """

    result = analyze_transcript(sample, "Test Company")
    print(result.summary)
    print(f"\nRed Flags: {len(result.red_flags)}")
    print(f"Metrics: {len(result.metrics_extracted)}")

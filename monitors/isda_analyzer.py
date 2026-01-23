"""
ISDA Credit Event Analyzer
Interprets headlines and articles through the lens of ISDA Credit Derivatives Definitions

Key ISDA 2014 Credit Events:
1. Bankruptcy
2. Failure to Pay
3. Restructuring (Mod-R, Mod-Mod-R, Old-R)
4. Obligation Acceleration (rare)
5. Obligation Default (rare)
6. Repudiation/Moratorium (sovereigns)

Plus: Succession Events (M&A, spin-offs)
"""

import streamlit as st
import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class CreditEventType(Enum):
    BANKRUPTCY = "Bankruptcy"
    FAILURE_TO_PAY = "Failure to Pay"
    RESTRUCTURING = "Restructuring"
    OBLIGATION_ACCELERATION = "Obligation Acceleration"
    OBLIGATION_DEFAULT = "Obligation Default"
    REPUDIATION_MORATORIUM = "Repudiation/Moratorium"
    SUCCESSION_EVENT = "Succession Event"
    NOT_A_CREDIT_EVENT = "Not a Credit Event (Yet)"
    WATCH = "Watch Closely"


# ============== ISDA DEFINITIONS ==============

ISDA_DEFINITIONS = {
    CreditEventType.BANKRUPTCY: {
        "description": "Filing for bankruptcy, insolvency, administration, liquidation, or similar proceedings",
        "triggers": [
            "chapter 11", "chapter 7", "chapter 15", "bankruptcy", "insolvency",
            "administration", "liquidation", "winding up", "receiver appointed",
            "bankruptcy filing", "filed for bankruptcy", "seeks bankruptcy",
            "enters administration", "insolvency proceedings", "creditor protection"
        ],
        "isda_notes": [
            "Bankruptcy is typically the clearest Credit Event",
            "Filing date is the Event Determination Date",
            "No grace period - immediate trigger",
            "Deliverable obligations become immediately relevant"
        ],
        "what_to_watch": [
            "Confirm filing is by the Reference Entity (not a subsidiary)",
            "Check if there's a Successor determination needed",
            "Monitor for deliverable obligation pricing"
        ]
    },

    CreditEventType.FAILURE_TO_PAY: {
        "description": "Failure to make payment on one or more Obligations when due (after grace period)",
        "triggers": [
            "missed payment", "failed to pay", "payment default", "non-payment",
            "interest payment missed", "coupon missed", "principal not paid",
            "grace period", "payment holiday", "failed to make", "did not pay",
            "unable to pay", "payment failure", "defaulted on payment"
        ],
        "isda_notes": [
            "Standard Grace Period Extension: 3 business days beyond contractual grace",
            "Payment Requirement: Typically $1M (check confirmation)",
            "Must be on a Borrowed Money obligation",
            "Technical defaults may not qualify"
        ],
        "what_to_watch": [
            "What is the contractual grace period? (often 30 days for bonds)",
            "Has the grace period expired?",
            "Is the amount above the Payment Requirement threshold?",
            "Is this a Borrowed Money obligation?"
        ]
    },

    CreditEventType.RESTRUCTURING: {
        "description": "Agreement between issuer and creditors resulting in credit deterioration",
        "triggers": [
            "restructuring", "debt exchange", "exchange offer", "liability management",
            "lme", "maturity extension", "coupon reduction", "principal haircut",
            "debt-for-equity", "consent solicitation", "amendment", "waiver",
            "covenant relief", "standstill", "forbearance agreement", "scheme of arrangement",
            "haircut", "write-down", "bail-in"
        ],
        "isda_notes": [
            "Must result from credit deterioration (not optional refinancing)",
            "Multiple Holder Obligation: Must bind all holders (not just consenting)",
            "Restructuring flavors: Old-R (full), Mod-R (EU standard), Mod-Mod-R (limited)",
            "Key test: Is this a VOLUNTARY exchange or BINDING on all holders?"
        ],
        "what_to_watch": [
            "Is exchange voluntary or binding? Voluntary = likely NOT a Credit Event",
            "Are ALL holders bound, or just those who consent?",
            "What Restructuring type applies? (Check trade confirmation)",
            "Is there a maturity limitation bucket issue?",
            "Could this be characterized as refinancing instead?"
        ],
        "subtypes": {
            "Mod-R": "EU standard - 60M/60M maturity limitation",
            "Mod-Mod-R": "Limited restructuring - maturity caps apply",
            "Old-R": "Full restructuring - no maturity limitation (rare now)"
        }
    },

    CreditEventType.SUCCESSION_EVENT: {
        "description": "Merger, consolidation, amalgamation, transfer of assets/liabilities, or demerger",
        "triggers": [
            "merger", "acquisition", "acquires", "acquired by", "takeover",
            "spin-off", "demerger", "split", "carve-out", "asset sale",
            "transfer of", "assumption of debt", "successor", "consolidation",
            "combined entity", "new parent"
        ],
        "isda_notes": [
            "Not a Credit Event, but affects CDS contracts",
            "May require Successor determination by DC",
            "Universal Successor: >75% of relevant obligations",
            "Multiple Successors possible (pro-rata allocation)",
            "Check if Reference Entity changes"
        ],
        "what_to_watch": [
            "Who assumes the Relevant Obligations?",
            "Is there a Universal Successor (>75%)?",
            "Will ISDA DC make a Successor determination?",
            "Does the debt stay with original entity or transfer?",
            "Are there any change of control triggers in bonds?"
        ]
    },

    CreditEventType.NOT_A_CREDIT_EVENT: {
        "description": "Situations that may look concerning but don't trigger CDS",
        "triggers": [
            "covenant breach", "covenant waiver", "technical default",
            "rating downgrade", "outlook negative", "watchlist",
            "liquidity concerns", "going concern", "profit warning",
            "earnings miss", "guidance cut", "margin pressure"
        ],
        "isda_notes": [
            "Covenant breaches are NOT Credit Events",
            "Rating actions are NOT Credit Events",
            "These may LEAD to Credit Events but don't trigger them",
            "Watch for escalation path"
        ],
        "what_to_watch": [
            "Could this escalate to Failure to Pay?",
            "Is a Restructuring likely to follow?",
            "What's the liquidity runway?",
            "Are acceleration rights being triggered?"
        ]
    }
}

# High-priority keywords that warrant immediate attention
HIGH_PRIORITY_TRIGGERS = [
    "bankruptcy", "chapter 11", "insolvency", "administration",
    "missed payment", "payment default", "failed to pay",
    "restructuring", "liability management", "exchange offer",
    "haircut", "write-down", "debt-for-equity"
]


# ============== ANALYSIS FUNCTIONS ==============

@dataclass
class ISDAAnalysis:
    """Result of ISDA analysis"""
    event_type: CreditEventType
    confidence: str  # High, Medium, Low
    triggers_found: List[str]
    isda_notes: List[str]
    what_to_watch: List[str]
    summary: str
    is_high_priority: bool


def analyze_text_for_isda(text: str) -> ISDAAnalysis:
    """
    Analyze text for ISDA Credit Event implications.
    Returns structured analysis with event type, notes, and watch items.
    """
    text_lower = text.lower()

    # Track all matches
    all_matches = {}

    for event_type, definition in ISDA_DEFINITIONS.items():
        triggers = definition.get("triggers", [])
        matches = []
        for trigger in triggers:
            if trigger.lower() in text_lower:
                matches.append(trigger)
        if matches:
            all_matches[event_type] = matches

    # Determine primary event type (prioritize actual Credit Events over "Watch")
    priority_order = [
        CreditEventType.BANKRUPTCY,
        CreditEventType.FAILURE_TO_PAY,
        CreditEventType.RESTRUCTURING,
        CreditEventType.SUCCESSION_EVENT,
        CreditEventType.NOT_A_CREDIT_EVENT
    ]

    primary_event = None
    primary_matches = []

    for event_type in priority_order:
        if event_type in all_matches:
            primary_event = event_type
            primary_matches = all_matches[event_type]
            break

    if not primary_event:
        return ISDAAnalysis(
            event_type=CreditEventType.WATCH,
            confidence="Low",
            triggers_found=[],
            isda_notes=["No specific ISDA triggers detected"],
            what_to_watch=["Monitor for further developments"],
            summary="No clear ISDA implications detected",
            is_high_priority=False
        )

    # Get definition details
    definition = ISDA_DEFINITIONS[primary_event]

    # Check if high priority
    is_high_priority = any(hp in text_lower for hp in HIGH_PRIORITY_TRIGGERS)

    # Determine confidence
    if len(primary_matches) >= 3:
        confidence = "High"
    elif len(primary_matches) >= 2:
        confidence = "Medium"
    else:
        confidence = "Low"

    # Build summary
    if primary_event == CreditEventType.NOT_A_CREDIT_EVENT:
        summary = f"Not a Credit Event, but watch for escalation. Triggers: {', '.join(primary_matches[:3])}"
    elif primary_event == CreditEventType.SUCCESSION_EVENT:
        summary = f"Potential Succession Event - may require DC determination. Triggers: {', '.join(primary_matches[:3])}"
    else:
        summary = f"Potential {primary_event.value} - verify details against ISDA definitions. Triggers: {', '.join(primary_matches[:3])}"

    return ISDAAnalysis(
        event_type=primary_event,
        confidence=confidence,
        triggers_found=primary_matches,
        isda_notes=definition.get("isda_notes", []),
        what_to_watch=definition.get("what_to_watch", []),
        summary=summary,
        is_high_priority=is_high_priority
    )


def format_isda_alert(tweet_text: str, analysis: ISDAAnalysis) -> str:
    """Format ISDA analysis for Telegram alert"""

    event_emoji = {
        CreditEventType.BANKRUPTCY: "🚨",
        CreditEventType.FAILURE_TO_PAY: "⚠️",
        CreditEventType.RESTRUCTURING: "📋",
        CreditEventType.SUCCESSION_EVENT: "🔄",
        CreditEventType.NOT_A_CREDIT_EVENT: "👀",
        CreditEventType.WATCH: "📌"
    }

    emoji = event_emoji.get(analysis.event_type, "📌")

    msg = f"\n\n{emoji} *ISDA Analysis*\n"
    msg += f"Event Type: *{analysis.event_type.value}*\n"
    msg += f"Confidence: {analysis.confidence}\n"

    if analysis.triggers_found:
        msg += f"Triggers: {', '.join(analysis.triggers_found[:4])}\n"

    if analysis.what_to_watch:
        msg += f"\n_Watch: {analysis.what_to_watch[0]}_"

    return msg


def get_full_isda_analysis(text: str) -> str:
    """Get detailed ISDA analysis for display in UI"""
    analysis = analyze_text_for_isda(text)

    output = []
    output.append(f"## ISDA Analysis\n")
    output.append(f"**Event Type:** {analysis.event_type.value}")
    output.append(f"**Confidence:** {analysis.confidence}")
    output.append(f"**High Priority:** {'Yes' if analysis.is_high_priority else 'No'}")
    output.append(f"\n**Summary:** {analysis.summary}\n")

    if analysis.triggers_found:
        output.append("### Triggers Detected")
        for trigger in analysis.triggers_found:
            output.append(f"- {trigger}")

    output.append("\n### ISDA Notes")
    for note in analysis.isda_notes:
        output.append(f"- {note}")

    output.append("\n### What to Watch")
    for item in analysis.what_to_watch:
        output.append(f"- {item}")

    # Add restructuring subtypes if relevant
    if analysis.event_type == CreditEventType.RESTRUCTURING:
        definition = ISDA_DEFINITIONS[CreditEventType.RESTRUCTURING]
        if "subtypes" in definition:
            output.append("\n### Restructuring Types")
            for subtype, desc in definition["subtypes"].items():
                output.append(f"- **{subtype}:** {desc}")

    return "\n".join(output)


# ============== STREAMLIT UI ==============

def render_isda_analyzer():
    """Render the ISDA analyzer UI"""

    st.subheader("ISDA Credit Event Analyzer")
    st.caption("Interpret headlines and articles through ISDA Credit Derivatives Definitions")

    tab1, tab2, tab3 = st.tabs(["Analyze Text", "ISDA Reference", "Recent Alerts"])

    with tab1:
        render_text_analyzer()

    with tab2:
        render_isda_reference()

    with tab3:
        render_recent_isda_alerts()


def render_text_analyzer():
    """Text input for ISDA analysis"""

    st.markdown("### Paste Article or Headline")
    st.caption("Paste any credit-related text to analyze for ISDA implications")

    text_input = st.text_area(
        "Enter text to analyze",
        height=200,
        placeholder="Paste headline, article excerpt, or press release here...\n\nExample: 'Company X announces exchange offer for outstanding bonds, offering holders 80 cents on the dollar plus equity in exchange for existing notes'"
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        analyze_btn = st.button("Analyze", type="primary")

    if analyze_btn and text_input:
        st.markdown("---")

        analysis = analyze_text_for_isda(text_input)

        # Header with color coding
        if analysis.event_type == CreditEventType.BANKRUPTCY:
            st.error(f"🚨 **{analysis.event_type.value}** - Confidence: {analysis.confidence}")
        elif analysis.event_type == CreditEventType.FAILURE_TO_PAY:
            st.error(f"⚠️ **{analysis.event_type.value}** - Confidence: {analysis.confidence}")
        elif analysis.event_type == CreditEventType.RESTRUCTURING:
            st.warning(f"📋 **{analysis.event_type.value}** - Confidence: {analysis.confidence}")
        elif analysis.event_type == CreditEventType.SUCCESSION_EVENT:
            st.info(f"🔄 **{analysis.event_type.value}** - Confidence: {analysis.confidence}")
        else:
            st.info(f"👀 **{analysis.event_type.value}** - Confidence: {analysis.confidence}")

        st.markdown(f"**Summary:** {analysis.summary}")

        # Triggers
        if analysis.triggers_found:
            st.markdown("**Triggers Detected:**")
            st.markdown(", ".join([f"`{t}`" for t in analysis.triggers_found]))

        # Two columns for notes and watch items
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### ISDA Notes")
            for note in analysis.isda_notes:
                st.markdown(f"- {note}")

        with col2:
            st.markdown("### What to Watch")
            for item in analysis.what_to_watch:
                st.markdown(f"- {item}")

        # Restructuring subtypes
        if analysis.event_type == CreditEventType.RESTRUCTURING:
            st.markdown("---")
            st.markdown("### Restructuring Types (Check Your Confirmation)")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown("**Mod-R** (EU Standard)")
                st.caption("60M/60M maturity limitation")
            with col2:
                st.markdown("**Mod-Mod-R** (Limited)")
                st.caption("Maturity caps apply")
            with col3:
                st.markdown("**Old-R** (Full)")
                st.caption("No limitation (rare)")

        # Key question for restructuring
        if analysis.event_type == CreditEventType.RESTRUCTURING:
            st.markdown("---")
            st.warning("**Key Question:** Is this exchange VOLUNTARY or BINDING on all holders? Voluntary exchanges typically do NOT trigger Restructuring Credit Events.")


def render_isda_reference():
    """Reference guide for ISDA Credit Events"""

    st.markdown("### ISDA 2014 Credit Event Definitions")

    for event_type, definition in ISDA_DEFINITIONS.items():
        if event_type == CreditEventType.NOT_A_CREDIT_EVENT:
            continue

        with st.expander(f"**{event_type.value}**"):
            st.markdown(f"**Definition:** {definition['description']}")

            st.markdown("**Key Triggers:**")
            st.markdown(", ".join([f"`{t}`" for t in definition['triggers'][:10]]))

            st.markdown("**ISDA Notes:**")
            for note in definition['isda_notes']:
                st.markdown(f"- {note}")

            st.markdown("**What to Watch:**")
            for item in definition['what_to_watch']:
                st.markdown(f"- {item}")

    # Not a Credit Event section
    st.markdown("---")
    st.markdown("### Things That Are NOT Credit Events")

    not_ce = ISDA_DEFINITIONS[CreditEventType.NOT_A_CREDIT_EVENT]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Common Misconceptions:**")
        for trigger in not_ce['triggers'][:6]:
            st.markdown(f"- {trigger.title()}")
    with col2:
        st.markdown("**But Watch For:**")
        for item in not_ce['what_to_watch']:
            st.markdown(f"- {item}")


def render_recent_isda_alerts():
    """Show recent alerts with ISDA analysis"""

    st.markdown("### Recent Credit Twitter Alerts")
    st.caption("ISDA analysis is automatically added to Telegram alerts")

    st.info("Credit Twitter alerts now include ISDA analysis when credit-relevant keywords are detected. Check your Telegram for the latest alerts with ISDA interpretation.")

    # Example alert format
    st.markdown("---")
    st.markdown("**Example Alert Format:**")

    example = """
*Credit Alert* (restructuring, exchange offer)

@ReutersBiz (News Wire)

BREAKING: Acme Corp announces exchange offer for $500M outstanding senior notes, offering holders 85 cents plus warrants

[View on X](https://x.com/...)

📋 *ISDA Analysis*
Event Type: *Restructuring*
Confidence: High
Triggers: restructuring, exchange offer

_Watch: Is exchange voluntary or binding? Voluntary = likely NOT a Credit Event_
"""
    st.code(example, language=None)


def render_lme_vs_bankruptcy_tree():
    """LME vs Bankruptcy decision tree for quick reference"""

    st.markdown("### LME vs Bankruptcy: Will It Trigger CDS?")
    st.caption("Quick decision tree based on DC precedents")

    st.markdown("""
    ```
    HEADLINE RECEIVED
          │
          ▼
    ┌─────────────────────────────────────┐
    │  What type of action is announced?  │
    └─────────────────────────────────────┘
          │
    ┌─────┴─────┬─────────────┬──────────────────┐
    │           │             │                  │
    ▼           ▼             ▼                  ▼
VOLUNTARY    BINDING      COURT FILING      MISSED
EXCHANGE    AGREEMENT    (Bankruptcy)       PAYMENT
    │           │             │                  │
    ▼           ▼             ▼                  ▼
  ┌───┐      ┌───┐         ┌───┐              ┌───┐
  │NO │      │???│         │YES│              │YES│
  │CE │      │   │         │CE │              │CE │
  └───┘      └───┘         └───┘              └───┘
    │           │             │                  │
    │      Check if         Filing =          After
    │      binding on       Immediate         Grace
    │      ALL holders      Trigger           Period
    │           │
    │           ▼
    │    ┌──────────────────┐
    │    │ TSA/Lock-up with │
    │    │ >90% support?    │
    │    └──────────────────┘
    │      │YES        │NO
    │      ▼           ▼
    │   ┌─────┐     ┌─────┐
    │   │ YES │     │ NO  │
    │   │ CE  │     │ CE  │
    │   └─────┘     └─────┘
    │   (Ardagh)   (Intrum LME)
    │
    ▼
┌────────────────────────────────────┐
│  VOLUNTARY = NOT a Credit Event   │
│  (Isolux, most LMEs)              │
│                                    │
│  Key: Non-participating holders   │
│  keep original terms unchanged    │
└────────────────────────────────────┘
    ```
    """)

    # Jurisdiction-specific guidance
    st.markdown("---")
    st.markdown("### By Jurisdiction")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**France**")
        st.markdown("""
        | Proceeding | Credit Event? |
        |------------|---------------|
        | Mandat ad hoc | NO |
        | Conciliation | NO |
        | Safeguard | **YES** |
        | Sauvegarde Accélérée | **YES** |
        | Redressement | **YES** |
        | Liquidation | **YES** |

        *Key: Does it impose mandatory stay?*
        """)

        st.markdown("**UK**")
        st.markdown("""
        | Proceeding | Credit Event? |
        |------------|---------------|
        | Voluntary Exchange | NO |
        | Scheme of Arrangement | **YES** |
        | Administration | **YES** |
        | CVA (binding) | **YES** |
        | Liquidation | **YES** |

        *Schemes bind all holders = Restructuring CE*
        """)

    with col2:
        st.markdown("**US**")
        st.markdown("""
        | Proceeding | Credit Event? |
        |------------|---------------|
        | Voluntary Exchange | NO |
        | Uptier/Dropdown | NO* |
        | Chapter 11 | **YES** |
        | Chapter 7 | **YES** |
        | Chapter 15 + Stay | **YES** |
        | Chapter 15 only | NO |

        *Unless reaches binding threshold (Ardagh)*
        """)

        st.markdown("**Netherlands**")
        st.markdown("""
        | Proceeding | Credit Event? |
        |------------|---------------|
        | WHOA (Scheme) | **YES** |
        | Suspension of Payments | **YES** |
        | Bankruptcy | **YES** |

        *WHOA = Dutch scheme, binds creditors (Selecta)*
        """)

    # Key tests
    st.markdown("---")
    st.markdown("### Key Questions to Ask")

    st.markdown("""
    1. **Is this VOLUNTARY or BINDING on all holders?**
       - Voluntary = NO Credit Event (most LMEs)
       - Binding via scheme/court = YES Credit Event

    2. **What consent threshold triggers "binding"?**
       - Check indenture CACs (typically 75% or 90%)
       - TSA reaching threshold = potential CE date (Ardagh)

    3. **Is there a court filing?**
       - Chapter 11/7 = immediate Bankruptcy CE
       - French Safeguard = Bankruptcy CE
       - UK Administration = Bankruptcy CE

    4. **What jurisdiction?**
       - US Chapter 15: depends on relief sought (stay = CE)
       - French Conciliation: NOT a CE (yet)
       - Watch for transition to court-supervised process

    5. **Is there a missed payment?**
       - Check contractual grace period (often 30 days)
       - + 3 business day ISDA extension
       - Payment Requirement threshold ($1M typically)
    """)


def render_isda_analyzer():
    """Render the ISDA analyzer UI"""

    st.subheader("ISDA Credit Event Analyzer")
    st.caption("Interpret headlines and articles through ISDA Credit Derivatives Definitions")

    tab1, tab2, tab3, tab4 = st.tabs(["Analyze Text", "LME vs Bankruptcy", "ISDA Reference", "Recent Alerts"])

    with tab1:
        render_text_analyzer()

    with tab2:
        render_lme_vs_bankruptcy_tree()

    with tab3:
        render_isda_reference()

    with tab4:
        render_recent_isda_alerts()

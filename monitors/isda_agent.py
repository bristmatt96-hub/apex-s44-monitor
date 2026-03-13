"""
ISDA Credit Event Agent - LLM-powered analysis with DC precedent knowledge
Ingests real Credit Derivatives Determinations Committee rulings and case law
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Try to import OpenAI
OPENAI_AVAILABLE = False
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    pass

# Try to import Anthropic
ANTHROPIC_AVAILABLE = False
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    pass

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")



# ============== ISDA DC PRECEDENT DATABASE ==============
# Real cases and how they were determined

ISDA_PRECEDENTS = {
    "Portugal Telecom": {
        "year": 2014,
        "events": ["Restructuring", "Succession Event"],
        "summary": "Complex case involving Oi S.A. merger. DC determined Succession Event occurred when PT merged with Oi. Later restructuring of Oi raised questions about which entity was Reference Entity.",
        "key_rulings": [
            "Merger with Oi triggered Succession Event determination",
            "DC had to determine allocation of CDS contracts between PT and Oi",
            "Highlighted importance of tracking corporate restructurings for CDS holders"
        ],
        "lessons": [
            "Cross-border mergers can create complex Succession Event questions",
            "Reference Entity identity must be tracked through corporate changes",
            "Language in original CDS confirmation matters for successor determination"
        ]
    },

    "Abengoa": {
        "year": 2015,
        "events": ["Failure to Pay", "Restructuring"],
        "summary": "Spanish renewable energy company. Missed payments triggered Failure to Pay. Subsequent Spanish insolvency proceeding (concurso) and homologación raised Restructuring questions.",
        "key_rulings": [
            "Failure to Pay confirmed after grace period expiry on €20M payment",
            "Spanish homologación (court-approved restructuring) analyzed for Restructuring CE",
            "Binding nature on non-consenting creditors was key test"
        ],
        "lessons": [
            "Spanish homologación CAN trigger Restructuring if it binds all holders",
            "Grace period must fully expire before Failure to Pay",
            "Payment Requirement threshold matters (typically $1M)",
            "Local insolvency law nuances affect CE determination"
        ]
    },

    "Isolux Corsán": {
        "year": 2016,
        "events": ["Restructuring"],
        "summary": "Spanish infrastructure company. Exchange offer and subsequent Spanish insolvency proceedings.",
        "key_rulings": [
            "Initial exchange offer was VOLUNTARY - not a Credit Event",
            "Later binding concurso proceedings triggered Restructuring analysis",
            "Distinction between voluntary and binding restructuring is critical"
        ],
        "lessons": [
            "Voluntary exchanges do NOT trigger Restructuring Credit Events",
            "Only when ALL holders are bound does Restructuring potentially trigger",
            "Spanish concurso (insolvency) binds all creditors"
        ]
    },

    "Intrum": {
        "year": 2023,
        "events": ["Potential Restructuring - LME"],
        "summary": "Swedish debt collector. Liability Management Exercise (LME) with exchange offer. Key question: does modern LME structure trigger Restructuring?",
        "key_rulings": [
            "Exchange offers with coercive elements analyzed carefully",
            "Distinction between 'economically coercive' vs 'legally binding'",
            "Consent threshold manipulation tactics scrutinized"
        ],
        "lessons": [
            "Modern LMEs are structured to AVOID triggering CDS",
            "Even 'coercive' exchanges may not meet 'binding' test",
            "Exit consents and CAC usage affects analysis",
            "Watch for: (1) Are non-participating holders worse off? (2) Is there legal compulsion?"
        ]
    },

    "Codere": {
        "year": 2013,
        "events": ["Failure to Pay"],
        "summary": "Spanish gaming company. Famous case where company deliberately missed a payment to trigger CDS for hedge fund holders.",
        "key_rulings": [
            "Failure to Pay confirmed despite intentional nature",
            "Intent of issuer does not affect CE determination",
            "If payment is missed and grace period expires, it's a CE"
        ],
        "lessons": [
            "ISDA definitions are mechanical - intent doesn't matter",
            "Manufactured defaults are valid Credit Events",
            "This led to increased scrutiny of 'narrowly tailored' CEs"
        ]
    },

    "Caesars Entertainment": {
        "year": 2015,
        "events": ["Bankruptcy", "Failure to Pay"],
        "summary": "US casino operator. Complex structure with operating company bankruptcy while parent guaranteed debt.",
        "key_rulings": [
            "Chapter 11 filing by Caesars Entertainment Operating Company triggered Bankruptcy CE",
            "Questions about guarantee enforcement and which entity was Reference Entity",
            "Intercompany transactions scrutinized for fraudulent conveyance"
        ],
        "lessons": [
            "Subsidiary vs parent bankruptcy matters for CDS",
            "Guarantee structure affects which entity is Reference Entity",
            "Complex corporate structures require careful CE analysis"
        ]
    },

    "iHeartMedia": {
        "year": 2018,
        "events": ["Bankruptcy", "Failure to Pay"],
        "summary": "US radio company. Chapter 11 with complex capital structure and multiple tranches of debt.",
        "key_rulings": [
            "Chapter 11 filing confirmed Bankruptcy Credit Event",
            "Multiple series of CDS affected differently based on Reference Entity definition",
            "Deliverable obligation determination complex due to capital structure"
        ],
        "lessons": [
            "Chapter 11 is clear Bankruptcy trigger",
            "Reference Entity definition in confirmation critical",
            "Different debt tranches may have different CDS treatment"
        ]
    },

    "Noble Group": {
        "year": 2018,
        "events": ["Restructuring"],
        "summary": "Singapore commodity trader. Scheme of arrangement under Singapore/Bermuda law.",
        "key_rulings": [
            "Scheme of arrangement binds ALL creditors (including non-consenting)",
            "Therefore meets Multiple Holder Obligation test for Restructuring",
            "Restructuring Credit Event confirmed"
        ],
        "lessons": [
            "Schemes of arrangement typically DO trigger Restructuring",
            "Unlike voluntary exchanges, schemes bind all holders",
            "Jurisdiction of scheme matters (UK/Singapore schemes well-established)"
        ]
    },

    "Nortel Networks": {
        "year": 2009,
        "events": ["Bankruptcy"],
        "summary": "Canadian telecom equipment. Coordinated CCAA (Canada) and Chapter 15 (US) filings.",
        "key_rulings": [
            "CCAA filing in Canada triggered Bankruptcy CE",
            "Cross-border insolvency protocols analyzed",
            "Chapter 15 recognition confirmed applicability"
        ],
        "lessons": [
            "CCAA (Canadian Companies' Creditors Arrangement Act) = Bankruptcy CE",
            "Chapter 15 recognizes foreign proceedings",
            "Cross-border cases may have multiple relevant filings"
        ]
    },

    "Windstream": {
        "year": 2019,
        "events": ["Failure to Pay", "Bankruptcy"],
        "summary": "US telecom. Aurelius hedge fund argued covenant breach accelerated debt. Company filed Chapter 11.",
        "key_rulings": [
            "Covenant breach alone was NOT a Credit Event",
            "But subsequent Chapter 11 filing was Bankruptcy CE",
            "Acceleration did not itself trigger Failure to Pay"
        ],
        "lessons": [
            "Covenant breach is NOT a Credit Event",
            "Acceleration alone doesn't trigger Failure to Pay",
            "Only actual non-payment after grace period = Failure to Pay",
            "Bankruptcy filing is cleaner CE than trying to use acceleration"
        ]
    },

    "Rallye (Casino Group)": {
        "year": 2019,
        "events": ["Restructuring"],
        "summary": "French retail holding company. Sauvegarde proceedings (French insolvency protection).",
        "key_rulings": [
            "French sauvegarde proceedings analyzed",
            "Court-approved plan binds all creditors in affected classes",
            "Restructuring CE triggered by binding nature of sauvegarde plan"
        ],
        "lessons": [
            "French sauvegarde = potentially Restructuring CE",
            "Court approval makes plan binding on non-consenting creditors",
            "European insolvency procedures vary by jurisdiction"
        ]
    },

    "Steinhoff": {
        "year": 2018,
        "events": ["Potential Restructuring"],
        "summary": "South African/Dutch retailer. Complex CVA and scheme of arrangement structure.",
        "key_rulings": [
            "Company Voluntary Arrangement (CVA) analysis",
            "Intercompany claims and third-party releases",
            "Multiple restructuring tools used in sequence"
        ],
        "lessons": [
            "CVAs can trigger Restructuring if binding",
            "Multi-jurisdictional restructurings are complex",
            "Sequence of restructuring steps matters"
        ]
    },

    "Phones4U": {
        "year": 2014,
        "events": ["Bankruptcy"],
        "summary": "UK mobile phone retailer. Entered administration after losing carrier contracts.",
        "key_rulings": [
            "UK Administration = Bankruptcy Credit Event",
            "Administrator appointment is the trigger date",
            "No need to wait for liquidation"
        ],
        "lessons": [
            "UK Administration is clear Bankruptcy CE",
            "Similar to US Chapter 11 in triggering effect",
            "Speed of UK process can catch market off guard"
        ]
    },

    "Thomas Cook": {
        "year": 2019,
        "events": ["Bankruptcy"],
        "summary": "UK travel company. Compulsory liquidation after failed rescue deal.",
        "key_rulings": [
            "Compulsory liquidation = Bankruptcy CE",
            "Failed last-minute rescue did not prevent CE",
            "Multiple group entities affected"
        ],
        "lessons": [
            "UK compulsory liquidation = Bankruptcy",
            "Failed rescue attempts don't delay CE",
            "Group structure matters - which entity is Reference Entity?"
        ]
    },

    "Banco Espirito Santo": {
        "year": 2014,
        "events": ["Restructuring", "Governmental Intervention"],
        "summary": "Portuguese bank. Resolution and bail-in by Portuguese authorities. Good bank/bad bank split.",
        "key_rulings": [
            "Governmental Intervention analyzed (bank-specific CE)",
            "Senior bonds transferred to 'good bank' Novo Banco",
            "Subordinated debt left in 'bad bank' - different CE treatment"
        ],
        "lessons": [
            "Bank resolution can trigger Governmental Intervention CE",
            "Good bank/bad bank splits complicate CDS settlement",
            "Seniority determines which entity bonds follow",
            "EU Bank Recovery and Resolution Directive (BRRD) implications"
        ]
    },

    "Europcar": {
        "year": 2021,
        "events": ["Restructuring"],
        "summary": "French car rental. Sauvegarde accélérée (accelerated safeguard) proceedings.",
        "key_rulings": [
            "French sauvegarde accélérée binds dissenting creditors",
            "Court approval makes plan binding",
            "Restructuring CE confirmed"
        ],
        "lessons": [
            "French accelerated safeguard = likely Restructuring CE",
            "Pre-pack French restructurings still bind all creditors",
            "Speed of process doesn't affect binding nature"
        ]
    },

    "Selecta": {
        "year": 2021,
        "events": ["Restructuring"],
        "summary": "Swiss vending company. Used Dutch WHOA (Wet Homologatie Onderhands Akkoord) scheme.",
        "key_rulings": [
            "Dutch WHOA analyzed for first time by DC",
            "WHOA binds dissenting creditors in affected classes",
            "Restructuring Credit Event triggered"
        ],
        "lessons": [
            "Dutch WHOA = Restructuring CE (new tool, now established)",
            "Similar to UK scheme of arrangement in effect",
            "Netherlands becoming popular restructuring jurisdiction"
        ]
    },

    "OI Brasil (Oi S.A.)": {
        "year": 2016,
        "events": ["Bankruptcy", "Restructuring"],
        "summary": "Brazilian telecom. Recuperação Judicial (Brazilian reorganization). Linked to Portugal Telecom succession.",
        "key_rulings": [
            "Brazilian RJ (Recuperação Judicial) = Bankruptcy or Restructuring depending on analysis",
            "Largest bankruptcy in Brazilian history at time",
            "Complex interplay with PT succession determination"
        ],
        "lessons": [
            "Brazilian RJ filing can trigger Bankruptcy CE",
            "Or may be analyzed as Restructuring depending on trade",
            "Latin American insolvency regimes have their own nuances"
        ]
    },

    "Pacific Gas & Electric (PG&E)": {
        "year": 2019,
        "events": ["Bankruptcy"],
        "summary": "California utility. Chapter 11 due to wildfire liabilities.",
        "key_rulings": [
            "Chapter 11 filing = Bankruptcy CE",
            "Investment grade issuer pre-filing",
            "Utility regulatory framework didn't prevent CE"
        ],
        "lessons": [
            "Even regulated utilities can trigger CDS",
            "Investment grade status irrelevant once filed",
            "Tort liabilities can drive bankruptcy of large corporates"
        ]
    },

    "Hertz": {
        "year": 2020,
        "events": ["Bankruptcy"],
        "summary": "US car rental. Chapter 11 during COVID-19 pandemic.",
        "key_rulings": [
            "Chapter 11 filing = Bankruptcy CE",
            "COVID-19 circumstances didn't affect CE analysis",
            "Successful emergence didn't unwind CE"
        ],
        "lessons": [
            "Pandemic-driven bankruptcies treated same as others",
            "CE is triggered at filing, not affected by later emergence",
            "Market dislocation can create settlement challenges"
        ]
    },

    "Avianca": {
        "year": 2020,
        "events": ["Bankruptcy"],
        "summary": "Colombian airline. Chapter 11 filing in US (foreign debtor).",
        "key_rulings": [
            "Foreign company can file Chapter 11 in US",
            "Chapter 11 = Bankruptcy CE regardless of domicile",
            "Airline-specific considerations didn't change analysis"
        ],
        "lessons": [
            "US Chapter 11 available to foreign debtors",
            "Jurisdiction of filing matters, not incorporation",
            "Industry-specific factors don't change CE definitions"
        ]
    },

    "Rallye SA": {
        "year": 2020,
        "events": ["Restructuring"],
        "summary": "French holding company (Casino parent). Sauvegarde followed by plan modification.",
        "key_rulings": [
            "French sauvegarde plan modifications analyzed",
            "Binding nature of court-approved plan confirmed",
            "Restructuring CE applicable"
        ],
        "lessons": [
            "French sauvegarde = Restructuring CE",
            "Plan modifications also binding",
            "Holding company vs opco distinction matters"
        ]
    },

    "Garuda Indonesia": {
        "year": 2021,
        "events": ["Restructuring", "Failure to Pay"],
        "summary": "Indonesian airline. Sukuk (Islamic bond) missed payments and PKPU restructuring.",
        "key_rulings": [
            "Sukuk analyzed same as conventional bonds for FtP",
            "Indonesian PKPU (restructuring) process examined",
            "Grace period analysis applied normally"
        ],
        "lessons": [
            "Sukuk treated same as bonds for ISDA purposes",
            "Emerging market insolvency regimes require careful analysis",
            "Payment mechanics may differ but CE tests same"
        ]
    },

    "Evergrande": {
        "year": 2023,
        "events": ["Failure to Pay", "Restructuring"],
        "summary": "Chinese property developer. Multiple missed payments, offshore restructuring attempts.",
        "key_rulings": [
            "Failure to Pay confirmed after grace period expiry",
            "Offshore vs onshore debt treatment different",
            "Hong Kong scheme of arrangement for offshore debt"
        ],
        "lessons": [
            "Chinese property sector has unique characteristics",
            "Offshore bonds (USD) may have different CE than onshore",
            "Government intervention can complicate timeline",
            "Hong Kong schemes bind offshore creditors"
        ]
    },

    "Sri Lanka (Sovereign)": {
        "year": 2022,
        "events": ["Failure to Pay", "Repudiation/Moratorium"],
        "summary": "Sovereign default. Announced suspension of external debt payments.",
        "key_rulings": [
            "Sovereign Failure to Pay after grace period",
            "Repudiation/Moratorium also analyzed",
            "IMF program implications"
        ],
        "lessons": [
            "Sovereign CDS has Repudiation/Moratorium CE (not available for corporates)",
            "Announced payment suspension = potential trigger",
            "Sovereign restructurings often prolonged"
        ]
    },

    "Russia (Sovereign)": {
        "year": 2022,
        "events": ["Failure to Pay"],
        "summary": "Sovereign default due to sanctions preventing payment in USD.",
        "key_rulings": [
            "Failure to Pay despite issuer willingness to pay",
            "Sanctions blocking payment mechanism analyzed",
            "Payment in rubles when USD required = non-payment"
        ],
        "lessons": [
            "Inability to pay (sanctions) still triggers FtP",
            "Willingness to pay is irrelevant - it's a mechanical test",
            "Currency of payment must match obligation terms",
            "Force majeure arguments rejected"
        ]
    }
}


# ============== ISDA KNOWLEDGE BASE ==============

ISDA_SYSTEM_PROMPT = """You are an expert ISDA Credit Derivatives analyst with deep knowledge of:

1. ISDA 2014 Credit Derivatives Definitions
2. Credit Derivatives Determinations Committee (DC) rulings and precedents
3. How different restructuring types (Mod-R, Mod-Mod-R, Old-R) affect CDS
4. Nuances of different bankruptcy/insolvency regimes globally

You have studied all major DC determinations including:

CORPORATE CASES:
- Portugal Telecom (succession events, merger complexity)
- Abengoa (Spanish homologación, Failure to Pay)
- Isolux (voluntary vs binding restructuring - voluntary = NO CE)
- Intrum (modern LME structures, coercive vs binding)
- Codere (manufactured defaults - intent irrelevant)
- Caesars (subsidiary vs parent, guarantees)
- Noble Group (Singapore scheme of arrangement)
- Windstream (covenant breach is NOT a CE)
- Rallye/Casino (French sauvegarde)
- Phones4U, Thomas Cook (UK administration)
- Banco Espirito Santo (bank resolution, bail-in)
- Europcar (French sauvegarde accélérée)
- Selecta (Dutch WHOA - new tool, binds creditors)
- OI Brasil (Brazilian Recuperação Judicial)
- PG&E (regulated utility Chapter 11)
- Hertz, Avianca (COVID-era bankruptcies)
- Garuda Indonesia (sukuk, emerging markets)
- Evergrande (China property, offshore vs onshore)

SOVEREIGN CASES:
- Russia 2022 (sanctions blocking payment = still FtP)
- Sri Lanka 2022 (Repudiation/Moratorium)

KEY PRINCIPLES YOU APPLY:

FAILURE TO PAY:
- Must be on a Borrowed Money obligation
- Grace period must fully expire (typically 30 days contractual + 3 business days ISDA extension)
- Payment Requirement threshold (typically $1M) must be breached
- Intent of issuer is IRRELEVANT (Codere precedent)

BANKRUPTCY:
- Filing date is Event Determination Date
- No grace period - immediate trigger
- Must be the Reference Entity (not just a subsidiary unless guaranteed)
- Chapter 11, CCAA, Administration, Insolvency filing all qualify

RESTRUCTURING:
- MUST bind ALL holders, not just consenting ones
- Voluntary exchange offers are NOT Credit Events (Isolux)
- Schemes of arrangement ARE typically Credit Events (Noble Group)
- Spanish homologación CAN be Credit Event if binding (Abengoa)
- French sauvegarde CAN be Credit Event
- Modern LMEs are structured to AVOID triggering (Intrum)

KEY TEST FOR RESTRUCTURING:
"Is the arrangement LEGALLY BINDING on non-consenting creditors?"
- If yes → Potential Restructuring CE
- If no (purely voluntary) → NOT a Credit Event

RESTRUCTURING FLAVORS:
- Mod-R (European standard): 60M maturity limitation for deliverables
- Mod-Mod-R: More limited maturity buckets
- Old-R: No limitation (rare, mostly legacy)
- Check the trade confirmation for which applies!

SUCCESSION EVENTS:
- Merger, consolidation, amalgamation triggers analysis
- Universal Successor test: >75% of Relevant Obligations
- May result in contract splitting if multiple successors
- Corporate restructurings must be tracked carefully (PT/Oi)

When analyzing a situation:
1. Identify which Credit Event type is potentially relevant
2. Apply the specific ISDA definition tests
3. Reference relevant DC precedents
4. Highlight key questions that need answers
5. Note what to watch for / next steps

Always be precise about:
- What IS vs what is NOT a Credit Event
- The specific tests that must be met
- Relevant precedents and how they apply
- Jurisdictional nuances (UK vs US vs Spain vs France etc.)

If uncertain, say so and explain what additional information would be needed.
"""


def build_precedent_context() -> str:
    """Build context string from precedent database"""
    context = "RELEVANT ISDA DC PRECEDENTS:\n\n"

    for name, data in ISDA_PRECEDENTS.items():
        context += f"=== {name} ({data['year']}) ===\n"
        context += f"Events: {', '.join(data['events'])}\n"
        context += f"Summary: {data['summary']}\n"
        context += "Key Lessons:\n"
        for lesson in data['lessons']:
            context += f"  - {lesson}\n"
        context += "\n"

    return context


def query_isda_agent_openai(question: str, article_text: str = "") -> str:
    """Query the ISDA agent using OpenAI"""
    if not OPENAI_AVAILABLE or not OPENAI_API_KEY:
        return "OpenAI not available. Please add OPENAI_API_KEY to secrets."

    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    # Build the user message
    user_message = f"Question: {question}\n\n"
    if article_text:
        user_message += f"Article/Text to analyze:\n{article_text}\n\n"
    user_message += "Please analyze this using ISDA definitions and relevant DC precedents."

    # Add precedent context
    precedent_context = build_precedent_context()

    try:
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": ISDA_SYSTEM_PROMPT + "\n\n" + precedent_context},
                {"role": "user", "content": user_message}
            ],
            temperature=0.3,
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error querying OpenAI: {str(e)}"


def query_isda_agent_anthropic(question: str, article_text: str = "") -> str:
    """Query the ISDA agent using Anthropic Claude"""
    if not ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
        return "Anthropic not available. Please add ANTHROPIC_API_KEY to secrets."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build the user message
    user_message = f"Question: {question}\n\n"
    if article_text:
        user_message += f"Article/Text to analyze:\n{article_text}\n\n"
    user_message += "Please analyze this using ISDA definitions and relevant DC precedents."

    # Add precedent context
    precedent_context = build_precedent_context()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=ISDA_SYSTEM_PROMPT + "\n\n" + precedent_context,
            messages=[
                {"role": "user", "content": user_message}
            ]
        )
        return response.content[0].text
    except Exception as e:
        return f"Error querying Anthropic: {str(e)}"


def query_isda_agent(question: str, article_text: str = "", provider: str = "auto") -> str:
    """Query the ISDA agent using available provider"""
    if provider == "auto":
        # Prefer Anthropic if available
        if ANTHROPIC_AVAILABLE and ANTHROPIC_API_KEY:
            provider = "anthropic"
        elif OPENAI_AVAILABLE and OPENAI_API_KEY:
            provider = "openai"
        else:
            return "No LLM provider available. Please add OPENAI_API_KEY or ANTHROPIC_API_KEY to secrets."

    if provider == "anthropic":
        return query_isda_agent_anthropic(question, article_text)
    else:
        return query_isda_agent_openai(question, article_text)


def get_precedent(name: str) -> Optional[Dict]:
    """Look up a specific ISDA precedent by name."""
    for key, data in ISDA_PRECEDENTS.items():
        if name.lower() in key.lower():
            return {"name": key, **data}
    return None


def search_precedents(event_type: str = None, keyword: str = None) -> List[Dict]:
    """Search precedents by event type or keyword."""
    results = []
    for name, data in ISDA_PRECEDENTS.items():
        if event_type and not any(event_type.lower() in e.lower() for e in data["events"]):
            continue
        if keyword:
            text = json.dumps(data).lower()
            if keyword.lower() not in text:
                continue
        results.append({"name": name, **data})
    return sorted(results, key=lambda x: x["year"], reverse=True)

"""
ISDA Credit Event Agent - LLM-powered analysis with DC precedent knowledge
Ingests real Credit Derivatives Determinations Committee rulings and case law
"""

import streamlit as st
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

# Helper function to safely get secrets (handles missing secrets.toml)
def get_secret(key, default=""):
    """Get secret from Streamlit secrets or environment variables"""
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except Exception:
        return os.environ.get(key, default)

# Load API keys from secrets
OPENAI_API_KEY = get_secret("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY", "")


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

    "Intrum (2023 LME)": {
        "year": 2023,
        "events": ["Potential Restructuring - LME"],
        "summary": "Swedish debt collector. Liability Management Exercise (LME) with exchange offer. Key question: does modern LME structure trigger Restructuring? (Note: Company later filed Chapter 11 in 2024 - see separate entry)",
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
    },

    # ============== 2023-2025 LME ERA PRECEDENTS ==============

    "Credit Suisse": {
        "year": 2023,
        "events": ["Governmental Intervention"],
        "summary": "Swiss regulator FINMA ordered full write-down of CHF 16bn AT1 bonds. Senior and Tier 2 bonds transferred to UBS intact.",
        "key_rulings": [
            "Question: Did Governmental Intervention CE occur on Subordinated CDS?",
            "Answer: NO - because Reference Obligation (Tier 2) was not affected",
            "AT1 write-down hit a junior layer but Tier 2 was transferred intact",
            "Standard 'Subordinated CDS' contracts reference Tier 2, NOT AT1s"
        ],
        "lessons": [
            "The 'Reference Obligation Trap' - GI must affect the Reference Obligation",
            "For GI to trigger, must write down Reference Obligation or pari passu/senior",
            "Hierarchy matters - junior layer write-down may NOT trigger CDS",
            "Massive 'protection gap' exposed - AT1 holders lost everything, CDS paid zero",
            "Bank capital structure hierarchy is critical for CDS analysis"
        ]
    },

    "Casino Guichard-Perrachon": {
        "year": 2023,
        "events": ["Restructuring"],
        "summary": "French retailer used Conciliation (amicable) then Safeguard (court-supervised) proceedings.",
        "key_rulings": [
            "Question: Does opening Conciliation trigger Bankruptcy?",
            "Answer: NO - Conciliation is voluntary/consensual",
            "BUT: Safeguard DOES trigger - it imposes mandatory stay on creditors",
            "Key distinction between consensual and coercive proceedings"
        ],
        "lessons": [
            "French Conciliation (consensual) = NOT a Credit Event",
            "French Safeguard (coercive, court-supervised) = Bankruptcy/Restructuring CE",
            "Only proceedings imposing mandatory stay trigger 'Bankruptcy' clause",
            "Watch for: when does company move from Conciliation to Safeguard?"
        ]
    },

    "Matalan": {
        "year": 2020,
        "events": ["Bankruptcy"],
        "summary": "UK retailer filed Chapter 15 in US seeking recognition AND automatic stay.",
        "key_rulings": [
            "Compared to Thomas Cook (which only sought recognition - NO CE)",
            "Matalan asked for recognition PLUS automatic stay",
            "DC ruled: requesting broad stay = 'relief similar to judgment of insolvency'",
            "Therefore: Bankruptcy CE confirmed"
        ],
        "lessons": [
            "The 'Relief Sought' Test for Chapter 15",
            "Chapter 15 with recognition only = NOT a Credit Event",
            "Chapter 15 with recognition + stay = Bankruptcy CE",
            "Read the actual Chapter 15 filing - what relief is requested?",
            "Thomas Cook (recognition only) vs Matalan (recognition + stay)"
        ]
    },

    "Intrum AB (2024)": {
        "year": 2024,
        "events": ["Bankruptcy"],
        "summary": "Swedish debt collector filed for US Chapter 11 to implement pre-packaged reorganization.",
        "key_rulings": [
            "Chapter 11 filing by European entity = Bankruptcy CE",
            "Pre-packaged/technical nature did not affect CE analysis",
            "US Chapter 11 available to foreign debtors"
        ],
        "lessons": [
            "US Chapter 11 by European company = clear Bankruptcy CE",
            "Pre-pack nature irrelevant - filing is the trigger",
            "Confirms foreign companies can use US Chapter 11",
            "Jurisdiction of filing matters, not place of incorporation"
        ]
    },

    "Altice France": {
        "year": 2025,
        "events": ["Bankruptcy"],
        "summary": "Entered Accelerated Safeguard proceedings in France. ~95% of bonds locked up in restructuring agreement. Also aggressively used dropdown threats.",
        "key_rulings": [
            "Accelerated Safeguard = Bankruptcy CE (relief from creditors)",
            "CRITICAL: ~95% bonds 'locked up' - could not be traded in auction",
            "DC abandoned standard auction - used Section 3.2(d) Composite Price mechanism",
            "Composite Price calculated from exit package (New Notes + Cash + Equity)"
        ],
        "lessons": [
            "French Accelerated Safeguard = Bankruptcy CE",
            "AUCTION FAILURE RISK when high lock-up percentage",
            "Section 3.2(d) 'Composite Settlement' used when bonds un-auctionable",
            "Composite Price = value of cash + new notes + equity in restructuring",
            "'Locking up the float' is NO LONGER a valid avoidance tactic - DC will switch to cash settlement",
            "Dropdown threats (moving assets to unrestricted subs) used to coerce creditors",
            "Critical precedent for LME-era settlements"
        ]
    },

    "Ardagh Packaging Finance": {
        "year": 2025,
        "events": ["Restructuring"],
        "summary": "Distressed exchange with Transaction Support Agreement (TSA). External Review Panel ruled CE occurred at TSA signing, not deal close.",
        "key_rulings": [
            "Question: CE date = TSA signing (Oct 7) or deal close (Nov 12)?",
            "Answer: TSA signing date (earlier date)",
            "External Review Panel (3 KCs/Judges, NOT market participants) ruled: 'binding means inevitable'",
            "Panel prioritized legal certainty over 'market custom' of waiting for closing"
        ],
        "lessons": [
            "THE 'BINDING' TRIGGER - CE occurs when agreement is mathematically inevitable",
            "'Binding Threshold' = LOWER of: Contractual CAC OR Statutory Scheme threshold",
            "Senior Notes: 90% CAC required, 92% signed TSA → 92% > 90% = BOUND immediately",
            "PIK Notes: 90% CAC required, only 82% signed → pivoted to English Scheme (75% threshold)",
            "PIK result: 82% > 75% Scheme threshold = also BOUND",
            "Protection sellers caught off guard by earlier trigger date",
            "ERP = 'Supreme Court' of CDS - convened when DC can't reach 80% supermajority"
        ]
    },

    "Adler Group": {
        "year": 2023,
        "events": ["LME - No Credit Event"],
        "summary": "German real estate company. Used exit consents to strip covenants from old bonds, creating 'zombie bonds'. CDS remained attached to hollow shell.",
        "key_rulings": [
            "Exchange offer: Old Bonds for New Bonds with haircut",
            "Exit consent mechanism: participating holders voted to strip old bond covenants",
            "Old bonds left as 'zombie bonds' - worthless but technically not restructured",
            "CDS did NOT trigger - no change to Ranking, Principal, Coupon, or Maturity"
        ],
        "lessons": [
            "THE 'ZOMBIE BOND' / COVENANT STRIP TACTIC",
            "ISDA Restructuring requires change to: Ranking, Principal, Coupon, or Maturity",
            "Stripping covenants (Negative Pledge, Cross-Default) does NOT fit this list",
            "Old bond remains outstanding with original payment terms - CDS references this zombie",
            "CDS left 'orphaned' on hollow shell that won't technically default",
            "Exit consents force 'voluntary' participation without triggering CDS"
        ]
    }
}


# ============== ISDA KNOWLEDGE BASE ==============

ISDA_SYSTEM_PROMPT = """You are an expert ISDA Credit Derivatives analyst with deep knowledge of:

1. ISDA 2014 Credit Derivatives Definitions
2. Credit Derivatives Determinations Committee (DC) rulings and precedents
3. How different restructuring types (Mod-R, Mod-Mod-R, Old-R) affect CDS
4. Nuances of different bankruptcy/insolvency regimes globally
5. Modern LME (Liability Management Exercise) structures and their CE implications

You have studied all major DC determinations including:

CORPORATE CASES (Classic):
- Portugal Telecom (succession events, merger complexity)
- Abengoa (Spanish homologación, Failure to Pay)
- Isolux (voluntary vs binding restructuring - voluntary = NO CE)
- Codere (manufactured defaults - intent irrelevant)
- Caesars (subsidiary vs parent, guarantees)
- Noble Group (Singapore scheme of arrangement)
- Windstream (covenant breach is NOT a CE)
- Phones4U, Thomas Cook (UK administration)
- Banco Espirito Santo (bank resolution, bail-in)
- Europcar (French sauvegarde accélérée)
- Selecta (Dutch WHOA - new tool, binds creditors)
- OI Brasil (Brazilian Recuperação Judicial)
- PG&E (regulated utility Chapter 11)
- Hertz, Avianca (COVID-era bankruptcies)
- Garuda Indonesia (sukuk, emerging markets)
- Evergrande (China property, offshore vs onshore)

LME ERA CASES (2023-2025) - CRITICAL NEW PRECEDENTS:
- Credit Suisse 2023 (AT1 write-down, Reference Obligation hierarchy gap)
- Casino 2023 (Conciliation vs Safeguard - consensual vs coercive)
- Adler 2023 (Exit consents, 'Zombie Bond' - covenant strip avoids CDS trigger)
- Matalan 2020 (Chapter 15 'Relief Sought' test vs Thomas Cook)
- Intrum 2024 (European company Chapter 11 in US)
- Altice France 2025 (Accelerated Safeguard + Section 3.2(d) 'Composite Settlement')
- Ardagh 2025 (TSA/Lock-Up signing = 'Binding Trigger', CAC vs Scheme threshold)

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

============== 2023-2025 KEY INTERPRETIVE DEVELOPMENTS ==============

THE "BINDING" TRIGGER (Ardagh 2025):
- A Restructuring CE can occur at TSA/Lock-Up Agreement signing
- NOT just when actual debt exchange closes
- "Binding" is a MATHEMATICALLY DYNAMIC threshold, not a fixed ISDA number
- The test: "Binding Threshold" = LOWER of: (1) Contractual CAC or (2) Statutory Scheme threshold
- Ardagh Senior Notes: 90% CAC required, 92% signed TSA → 92% > 90% = BOUND immediately
- Ardagh PIK Notes: 90% CAC required, only 82% signed → pivoted to English Scheme (75%)
- PIK result: 82% > 75% Scheme threshold = also BOUND
- EXTERNAL REVIEW PANEL (ERP) = "Supreme Court" of CDS (3 KCs/Judges, NOT market participants)
- ERP prioritized "legal certainty" over "market custom" of waiting for closing

THE "COMPOSITE SETTLEMENT" / BROKEN AUCTION (Altice 2025):
- When 90%+ bonds are locked up in restructuring, auction may fail
- Locked-up bonds cannot be freely traded in standard auction
- DC abandoned auction - invoked Section 3.2(d) "Composite Price" mechanism
- Composite = value of cash + new notes + equity from restructuring
- "Locking up the float" is NO LONGER a valid avoidance tactic
- DC will simply switch to cash settlement using Composite Price

============== LME AVOIDANCE TACTICS (The "Playbook") ==============

EXIT CONSENTS / "ZOMBIE BOND" (Adler 2023):
- Issuer offers exchange: Old Bonds → New Bonds (often with haircut)
- Exit consent: participating holders vote to strip Old Bond covenants
- Covenants stripped: Negative Pledge, Cross-Default, etc.
- Result: Old bond is "zombie" - worthless but payment terms unchanged
- CDS does NOT trigger: no change to Ranking, Principal, Coupon, or Maturity
- CDS left "orphaned" on hollow shell

DROP-DOWN TRANSACTIONS (J.Crew / Envision / Altice style):
- Company uses "Unrestricted Subsidiary" baskets
- Transfers valuable assets (IP, operating units) out of credit group
- Raises new debt secured by those assets
- Reference Entity (original issuer) hasn't failed to pay or restructured
- CDS attached to empty shell

CAC MANIPULATION / "VOTE RIGGING":
- Sponsor issues new debt to friendly affiliates
- Dilutes voting pool mathematically
- Crosses waiver threshold before ISDA Grace Period expires
- Manufactured majority waives default retroactively
- Prevents Failure to Pay trigger

THE "REFERENCE OBLIGATION" HIERARCHY GAP (Credit Suisse 2023):
- For bank CDS, standard "Subordinated CDS" references Tier 2, NOT AT1s
- For Governmental Intervention CE to trigger, must affect Reference Obligation or senior
- If write-down hits junior layer (AT1) but skips Tier 2 = NO CE
- Creates massive "protection gap" - bonds written down but CDS pays zero
- Bank capital structure hierarchy is critical

CONCILIATION vs SAFEGUARD (Casino 2023):
- French Conciliation (amicable, consensual) = NOT a Credit Event
- French Safeguard (court-supervised, coercive) = Bankruptcy/Restructuring CE
- Key test: Does proceeding impose MANDATORY stay on creditors?
- Consensual proceedings without stay = no trigger
- Watch for transition from Conciliation to Safeguard

CHAPTER 15 "RELIEF SOUGHT" TEST (Matalan vs Thomas Cook):
- Chapter 15 for recognition only = NOT a Credit Event (Thomas Cook)
- Chapter 15 for recognition + automatic stay = Bankruptcy CE (Matalan)
- Key: what relief is actually requested in the filing?
- Broad stay request = "relief similar to judgment of insolvency"
- Must read actual Chapter 15 petition to determine

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


# ============== STREAMLIT UI ==============

def render_isda_agent():
    """Render the ISDA Agent UI"""

    st.subheader("ISDA Credit Event Agent")
    st.caption("LLM-powered analysis with DC precedent knowledge")

    # Check for API keys
    has_openai = OPENAI_AVAILABLE and OPENAI_API_KEY
    has_anthropic = ANTHROPIC_AVAILABLE and ANTHROPIC_API_KEY

    if not has_openai and not has_anthropic:
        st.error("No LLM provider configured. Add OPENAI_API_KEY or ANTHROPIC_API_KEY to Streamlit secrets.")
        st.info("This agent requires an LLM to provide nuanced ISDA analysis based on DC precedents.")

        # Still show precedent database
        st.markdown("---")
        render_precedent_browser()
        return

    # Provider selection
    col1, col2 = st.columns([1, 3])
    with col1:
        providers = []
        if has_anthropic:
            providers.append("Anthropic (Claude)")
        if has_openai:
            providers.append("OpenAI (GPT-4)")

        selected_provider = st.selectbox("LLM Provider", providers)
        provider = "anthropic" if "Anthropic" in selected_provider else "openai"

    with col2:
        st.markdown(f"✅ Using {selected_provider}")

    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["Ask Agent", "Analyze Article", "DC Precedents"])

    with tab1:
        render_agent_query(provider)

    with tab2:
        render_article_analysis(provider)

    with tab3:
        render_precedent_browser()


def render_agent_query(provider: str):
    """Free-form query to the ISDA agent"""

    st.markdown("### Ask the ISDA Agent")
    st.caption("Ask any question about ISDA Credit Events, DC precedents, or how to interpret a situation")

    # Example questions
    with st.expander("Example questions"):
        st.markdown("""
        - "If a company does a voluntary exchange offer at 80 cents, is that a Restructuring Credit Event?"
        - "How did the DC rule on Intrum's LME? What made it different from a binding restructuring?"
        - "What's the difference between Mod-R and Mod-Mod-R for restructuring?"
        - "If a Spanish company enters concurso, does that trigger Bankruptcy or Restructuring?"
        - "Can a covenant breach trigger a Credit Event?"
        - "What happened with Codere and why does it matter for manufactured defaults?"
        """)

    question = st.text_area(
        "Your question",
        height=100,
        placeholder="Ask about ISDA Credit Events, DC rulings, or how to analyze a specific situation..."
    )

    if st.button("Ask Agent", type="primary", key="ask_agent"):
        if question:
            with st.spinner("Analyzing with DC precedent knowledge..."):
                response = query_isda_agent(question, provider=provider)

            st.markdown("### Agent Response")
            st.markdown(response)
        else:
            st.warning("Please enter a question")


def render_article_analysis(provider: str):
    """Analyze an article or press release"""

    st.markdown("### Analyze Article for ISDA Implications")
    st.caption("Paste a news article, press release, or any text for detailed ISDA analysis")

    article_text = st.text_area(
        "Paste article or text",
        height=250,
        placeholder="Paste the full article, press release, or relevant text here..."
    )

    specific_question = st.text_input(
        "Specific question (optional)",
        placeholder="e.g., 'Does this trigger a Restructuring CE under Mod-R?'"
    )

    if st.button("Analyze", type="primary", key="analyze_article"):
        if article_text:
            question = specific_question if specific_question else "Analyze this for ISDA Credit Event implications. What type of event might this be? What are the key questions? What precedents are relevant?"

            with st.spinner("Performing detailed ISDA analysis..."):
                response = query_isda_agent(question, article_text, provider=provider)

            st.markdown("### ISDA Analysis")
            st.markdown(response)
        else:
            st.warning("Please paste an article or text to analyze")


def render_precedent_browser():
    """Browse the DC precedent database"""

    st.markdown("### DC Precedent Database")
    st.caption("Key Credit Derivatives Determinations Committee rulings")

    # Filter by event type
    all_events = set()
    for data in ISDA_PRECEDENTS.values():
        all_events.update(data["events"])

    event_filter = st.multiselect(
        "Filter by event type",
        sorted(all_events),
        default=[]
    )

    for name, data in sorted(ISDA_PRECEDENTS.items(), key=lambda x: x[1]["year"], reverse=True):
        # Apply filter
        if event_filter and not any(e in data["events"] for e in event_filter):
            continue

        with st.expander(f"**{name}** ({data['year']}) - {', '.join(data['events'])}"):
            st.markdown(f"**Summary:** {data['summary']}")

            st.markdown("**Key Rulings:**")
            for ruling in data["key_rulings"]:
                st.markdown(f"- {ruling}")

            st.markdown("**Lessons for Future Cases:**")
            for lesson in data["lessons"]:
                st.markdown(f"- {lesson}")

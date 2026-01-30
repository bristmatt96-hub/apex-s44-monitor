"""
Crisis Memory - Historical Market Crash Data

Provides the Market Brain with "memory" of how markets behaved during
major crises. This helps recognize patterns and set realistic expectations.

INCLUDED CRISES:
1. Great Financial Crisis (2008-2009)
2. COVID-19 Crash (March 2020)
3. 2022 Bear Market (Fed tightening)

KEY LESSONS THE BRAIN LEARNS:
- Crashes are FAST (weeks), recoveries are SLOW (months/years)
- VIX spikes precede bottoms by days/weeks
- Quality recovers first, junk stays down
- "This time is different" is usually wrong
- Bear market rallies are violent but short-lived
"""
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, timedelta


@dataclass
class CrisisPhase:
    """A phase within a crisis"""
    name: str
    start_date: str
    end_date: str
    spy_change_pct: float
    vix_range: tuple  # (low, high)
    description: str
    lesson: str


@dataclass
class SectorRecovery:
    """How a sector performed during recovery"""
    sector: str
    days_to_bottom: int
    days_to_recover_50pct: int
    days_to_new_high: int
    max_drawdown_pct: float
    first_to_recover: bool


@dataclass
class CrisisMemory:
    """Complete memory of a market crisis"""
    name: str
    trigger: str
    start_date: str
    bottom_date: str
    recovery_date: str  # Back to pre-crisis level

    # Key metrics
    peak_to_trough_pct: float
    days_to_bottom: int
    days_to_recover: int
    vix_peak: float
    vix_at_bottom: float

    # Phases
    phases: List[CrisisPhase]

    # Sector performance
    sector_recovery: List[SectorRecovery]

    # Trading lessons
    key_lessons: List[str]
    what_worked: List[str]
    what_failed: List[str]


# =============================================================================
# GREAT FINANCIAL CRISIS (2008-2009)
# =============================================================================

GFC_2008 = CrisisMemory(
    name="Great Financial Crisis",
    trigger="Lehman Brothers collapse, subprime mortgage crisis, banking system failure",
    start_date="2007-10-09",  # SPY peak
    bottom_date="2009-03-09",  # SPY bottom
    recovery_date="2013-03-28",  # Back to 2007 highs

    peak_to_trough_pct=-56.8,  # SPY fell 56.8%
    days_to_bottom=517,        # ~17 months to bottom
    days_to_recover=1461,      # ~4 years to recover

    vix_peak=80.86,            # October 2008
    vix_at_bottom=49.68,       # VIX still elevated at market bottom

    phases=[
        CrisisPhase(
            name="Initial Decline",
            start_date="2007-10-09",
            end_date="2008-03-17",
            spy_change_pct=-18.6,
            vix_range=(16, 35),
            description="Bear Stearns collapse, slow grind down",
            lesson="Early declines feel like corrections, not crashes"
        ),
        CrisisPhase(
            name="Bear Market Rally",
            start_date="2008-03-17",
            end_date="2008-05-19",
            spy_change_pct=+14.4,
            vix_range=(18, 27),
            description="'The worst is over' rally after Bear Stearns rescue",
            lesson="Bear market rallies are violent and convincing - DON'T TRUST THEM"
        ),
        CrisisPhase(
            name="Lehman Collapse",
            start_date="2008-09-15",
            end_date="2008-10-10",
            spy_change_pct=-28.5,
            vix_range=(30, 80),
            description="Lehman bankruptcy, AIG bailout, money markets break",
            lesson="True panic: 25-30% drops in WEEKS. This is when to start watching."
        ),
        CrisisPhase(
            name="Capitulation",
            start_date="2008-11-20",
            end_date="2009-03-09",
            spy_change_pct=-28.0,
            vix_range=(40, 55),
            description="Grinding lower despite bailouts, 'no end in sight'",
            lesson="Final capitulation happens when NO ONE believes it will recover"
        ),
        CrisisPhase(
            name="Recovery Phase 1",
            start_date="2009-03-09",
            end_date="2009-06-12",
            spy_change_pct=+40.0,
            vix_range=(25, 50),
            description="Violent rally, most missed it waiting for 'retest'",
            lesson="First leg up is FAST. If you wait for confirmation, you miss 30%+"
        ),
    ],

    sector_recovery=[
        SectorRecovery("Technology", days_to_bottom=517, days_to_recover_50pct=180, days_to_new_high=1100, max_drawdown_pct=-52, first_to_recover=True),
        SectorRecovery("Consumer Discretionary", days_to_bottom=517, days_to_recover_50pct=200, days_to_new_high=1200, max_drawdown_pct=-58, first_to_recover=False),
        SectorRecovery("Financials", days_to_bottom=517, days_to_recover_50pct=400, days_to_new_high=2500, max_drawdown_pct=-83, first_to_recover=False),
        SectorRecovery("Healthcare", days_to_bottom=450, days_to_recover_50pct=150, days_to_new_high=900, max_drawdown_pct=-40, first_to_recover=True),
        SectorRecovery("Energy", days_to_bottom=517, days_to_recover_50pct=300, days_to_new_high=1800, max_drawdown_pct=-55, first_to_recover=False),
    ],

    key_lessons=[
        "Crashes take MONTHS, not days - don't try to catch the exact bottom",
        "VIX above 40 for extended periods = capitulation zone, start scaling in",
        "Bear market rallies (+15-20%) are TRAPS - don't go all in",
        "Financials (cause of crisis) recover LAST - avoid epicenter",
        "Tech and Healthcare recover FIRST - focus there",
        "The bottom happens when sentiment is worst, not when news improves",
        "First rally is 40%+ in 3 months - if you miss it, you miss most of it",
    ],

    what_worked=[
        "Scaling in over 6+ months (not all at once)",
        "Buying quality (AAPL, MSFT, JNJ) not junk (Citi, AIG)",
        "Selling bear market rallies",
        "Waiting for VIX to spike above 60 before heavy buying",
        "Diversifying across sectors (not just financials)",
    ],

    what_failed=[
        "Buying the first dip (too early by 12 months)",
        "Catching falling knives in financials",
        "Going all-in at any single point",
        "Trusting 'the Fed will save us' rallies",
        "Using leverage during high volatility",
    ]
)


# =============================================================================
# COVID-19 CRASH (2020)
# =============================================================================

COVID_2020 = CrisisMemory(
    name="COVID-19 Crash",
    trigger="Global pandemic, economic shutdown, liquidity crisis",
    start_date="2020-02-19",  # SPY peak
    bottom_date="2020-03-23",  # SPY bottom
    recovery_date="2020-08-18",  # Back to Feb highs

    peak_to_trough_pct=-33.9,  # SPY fell 33.9%
    days_to_bottom=33,         # Just 33 days! Fastest crash ever
    days_to_recover=181,       # ~6 months to recover

    vix_peak=82.69,            # March 16, 2020
    vix_at_bottom=61.59,       # VIX still 60+ at the bottom

    phases=[
        CrisisPhase(
            name="Initial Shock",
            start_date="2020-02-19",
            end_date="2020-02-28",
            spy_change_pct=-12.8,
            vix_range=(14, 40),
            description="Italy outbreak, virus goes global, 'just the flu' denial",
            lesson="First week is denial phase - don't buy yet"
        ),
        CrisisPhase(
            name="Dead Cat Bounce",
            start_date="2020-02-28",
            end_date="2020-03-03",
            spy_change_pct=+4.6,
            vix_range=(33, 40),
            description="Brief relief rally, 'containment is working'",
            lesson="First bounce is a TRAP - selling continues"
        ),
        CrisisPhase(
            name="Panic Selling",
            start_date="2020-03-04",
            end_date="2020-03-23",
            spy_change_pct=-26.1,
            vix_range=(40, 82),
            description="Lockdowns, margin calls, liquidity crisis, circuit breakers",
            lesson="Peak panic = VIX 80+, circuit breakers, 'end of world' headlines"
        ),
        CrisisPhase(
            name="V-Recovery",
            start_date="2020-03-23",
            end_date="2020-06-08",
            spy_change_pct=+44.5,
            vix_range=(25, 60),
            description="Fed unlimited QE, stimulus checks, 'don't fight the Fed'",
            lesson="When Fed goes 'unlimited', BUY. Recovery was V-shaped and violent."
        ),
    ],

    sector_recovery=[
        SectorRecovery("Technology", days_to_bottom=33, days_to_recover_50pct=25, days_to_new_high=60, max_drawdown_pct=-32, first_to_recover=True),
        SectorRecovery("Healthcare", days_to_bottom=33, days_to_recover_50pct=30, days_to_new_high=75, max_drawdown_pct=-28, first_to_recover=True),
        SectorRecovery("Consumer Discretionary", days_to_bottom=33, days_to_recover_50pct=40, days_to_new_high=90, max_drawdown_pct=-38, first_to_recover=False),
        SectorRecovery("Financials", days_to_bottom=33, days_to_recover_50pct=120, days_to_new_high=365, max_drawdown_pct=-43, first_to_recover=False),
        SectorRecovery("Energy", days_to_bottom=33, days_to_recover_50pct=300, days_to_new_high=600, max_drawdown_pct=-62, first_to_recover=False),
        SectorRecovery("Airlines/Travel", days_to_bottom=40, days_to_recover_50pct=400, days_to_new_high=999, max_drawdown_pct=-70, first_to_recover=False),
    ],

    key_lessons=[
        "COVID crash was the FASTEST in history - 33 days peak to trough",
        "But recovery was also FASTEST - V-shaped, not U-shaped",
        "VIX 80+ and circuit breakers = extreme panic = START BUYING",
        "Fed 'unlimited QE' announcement was THE signal to buy aggressively",
        "Tech (WFH beneficiaries) recovered in WEEKS, travel took YEARS",
        "Buying QUALITY on day 2-3 of panic worked spectacularly",
        "This was 'buy the dip' heaven - but only if you acted fast",
    ],

    what_worked=[
        "Buying tech (FAANG, cloud, e-commerce) during panic",
        "Acting on Fed QE announcement (March 23)",
        "Buying when VIX hit 80 (peak fear)",
        "Avoiding airlines/cruise/energy (epicenter)",
        "Scaling in during the week of March 16-23",
    ],

    what_failed=[
        "Waiting for 'second leg down' (it never came)",
        "Shorting after the first bounce",
        "Buying airlines/travel too early",
        "Waiting for VIX to 'normalize' before buying",
        "Being too cautious when Fed went unlimited",
    ]
)


# =============================================================================
# 2022 BEAR MARKET (Fed Tightening)
# =============================================================================

BEAR_2022 = CrisisMemory(
    name="2022 Bear Market",
    trigger="Fed rate hikes, inflation, end of QE, growth stock derating",
    start_date="2022-01-03",  # SPY peak
    bottom_date="2022-10-12",  # SPY bottom
    recovery_date="2024-01-19",  # Back to Jan 2022 highs

    peak_to_trough_pct=-25.4,  # SPY fell 25.4%
    days_to_bottom=282,        # ~9 months to bottom
    days_to_recover=746,       # ~2 years to recover

    vix_peak=36.45,            # Lower than GFC/COVID - orderly decline
    vix_at_bottom=31.62,       # VIX elevated but not extreme

    phases=[
        CrisisPhase(
            name="Growth Selloff",
            start_date="2022-01-03",
            end_date="2022-03-14",
            spy_change_pct=-13.0,
            vix_range=(17, 36),
            description="High PE stocks crushed, ARK -50%, rates rising",
            lesson="Rate hike cycles hit growth/tech FIRST and HARDEST"
        ),
        CrisisPhase(
            name="Bear Market Rally #1",
            start_date="2022-03-14",
            end_date="2022-03-29",
            spy_change_pct=+11.0,
            vix_range=(20, 30),
            description="'Fed pivot' hopes, 'priced in' narrative",
            lesson="Every bear market has multiple +10% rallies - they're traps"
        ),
        CrisisPhase(
            name="Grinding Lower",
            start_date="2022-04-01",
            end_date="2022-06-16",
            spy_change_pct=-18.7,
            vix_range=(25, 35),
            description="Inflation not peaking, Fed hawkish, crypto collapse",
            lesson="Slow grinds are harder to trade than panics"
        ),
        CrisisPhase(
            name="Bear Market Rally #2",
            start_date="2022-06-16",
            end_date="2022-08-16",
            spy_change_pct=+17.4,
            vix_range=(19, 28),
            description="'Soft landing' narrative, 'peak inflation'",
            lesson="17% rally in a bear market - STILL A TRAP"
        ),
        CrisisPhase(
            name="Final Capitulation",
            start_date="2022-08-16",
            end_date="2022-10-12",
            spy_change_pct=-17.6,
            vix_range=(25, 33),
            description="UK pension crisis, 'higher for longer', no pivot coming",
            lesson="Bottom came when 'no pivot' was accepted, not when pivot happened"
        ),
    ],

    sector_recovery=[
        SectorRecovery("Technology", days_to_bottom=282, days_to_recover_50pct=150, days_to_new_high=500, max_drawdown_pct=-35, first_to_recover=False),
        SectorRecovery("Energy", days_to_bottom=100, days_to_recover_50pct=50, days_to_new_high=150, max_drawdown_pct=-15, first_to_recover=True),
        SectorRecovery("Healthcare", days_to_bottom=250, days_to_recover_50pct=100, days_to_new_high=400, max_drawdown_pct=-18, first_to_recover=True),
        SectorRecovery("Financials", days_to_bottom=282, days_to_recover_50pct=200, days_to_new_high=550, max_drawdown_pct=-25, first_to_recover=False),
        SectorRecovery("Growth/ARK", days_to_bottom=350, days_to_recover_50pct=400, days_to_new_high=999, max_drawdown_pct=-78, first_to_recover=False),
    ],

    key_lessons=[
        "Rate hike cycles are SLOW bears - 9+ months of grinding",
        "Multiple +15% rallies are TRAPS in a rate hike cycle",
        "Energy and value OUTPERFORM in rising rate environment",
        "Growth stocks can fall 70-80% (ARK, unprofitable tech)",
        "Bottom comes when bad news is 'accepted', not when news improves",
        "VIX stayed 25-35 (not 60+) - orderly decline, not panic",
        "Patience required - took 2 years to recover",
    ],

    what_worked=[
        "Selling growth rallies",
        "Buying energy and value",
        "Waiting for VIX spikes to buy (even small ones)",
        "Not fighting the Fed",
        "Avoiding unprofitable tech",
    ],

    what_failed=[
        "Buying every dip in growth stocks",
        "'Averaging down' on ARK/meme stocks",
        "Expecting a V-recovery like COVID",
        "Betting on Fed pivot too early",
        "Going all-in on any single rally",
    ]
)


# =============================================================================
# MEMORY ACCESS FUNCTIONS
# =============================================================================

ALL_CRISES = [GFC_2008, COVID_2020, BEAR_2022]


def get_crisis_memory(crisis_name: str) -> Optional[CrisisMemory]:
    """Get memory of a specific crisis"""
    for crisis in ALL_CRISES:
        if crisis_name.lower() in crisis.name.lower():
            return crisis
    return None


def get_all_lessons() -> List[str]:
    """Get all key lessons from all crises"""
    lessons = []
    for crisis in ALL_CRISES:
        lessons.extend(crisis.key_lessons)
    return lessons


def get_recovery_patterns() -> Dict[str, Dict]:
    """Get sector recovery patterns across crises"""
    patterns = {}

    for crisis in ALL_CRISES:
        for sector in crisis.sector_recovery:
            if sector.sector not in patterns:
                patterns[sector.sector] = {
                    'avg_days_to_bottom': 0,
                    'avg_days_to_recover_50pct': 0,
                    'avg_max_drawdown': 0,
                    'times_first_to_recover': 0,
                    'crises_count': 0
                }

            p = patterns[sector.sector]
            p['avg_days_to_bottom'] += sector.days_to_bottom
            p['avg_days_to_recover_50pct'] += sector.days_to_recover_50pct
            p['avg_max_drawdown'] += sector.max_drawdown_pct
            p['times_first_to_recover'] += 1 if sector.first_to_recover else 0
            p['crises_count'] += 1

    # Calculate averages
    for sector, data in patterns.items():
        n = data['crises_count']
        data['avg_days_to_bottom'] /= n
        data['avg_days_to_recover_50pct'] /= n
        data['avg_max_drawdown'] /= n

    return patterns


def identify_crisis_type(
    vix_level: float,
    vix_spike_pct: float,
    spy_drawdown_pct: float,
    days_declining: int
) -> Dict:
    """
    Identify what type of crisis current conditions resemble.

    Returns analysis of which historical crisis is most similar.
    """
    analysis = {
        'most_similar': None,
        'similarity_score': 0,
        'expected_pattern': None,
        'recommendations': []
    }

    # COVID-like: Fast crash, VIX 60+
    if vix_level > 60 and days_declining < 45:
        analysis['most_similar'] = 'COVID-19 (Fast Crash)'
        analysis['similarity_score'] = min(1.0, vix_level / 80)
        analysis['expected_pattern'] = 'V-shaped recovery likely if Fed intervenes'
        analysis['recommendations'] = [
            "Watch for Fed/government intervention announcement",
            "Be ready to buy FAST when intervention comes",
            "Focus on tech/growth (WFH beneficiaries if pandemic-like)",
            "Avoid epicenter (whatever sector caused crisis)",
        ]

    # GFC-like: Slow grind, financial system stress
    elif vix_level > 40 and days_declining > 100:
        analysis['most_similar'] = 'GFC 2008 (Slow Crash)'
        analysis['similarity_score'] = min(1.0, days_declining / 500)
        analysis['expected_pattern'] = 'U-shaped recovery, multiple bear rallies'
        analysis['recommendations'] = [
            "DO NOT rush - crashes like this take 12-18 months",
            "Sell bear market rallies (+15% moves)",
            "Wait for VIX 60+ sustained before heavy buying",
            "Focus on healthcare/staples (defensive)",
            "Avoid financials if banking system is stressed",
        ]

    # 2022-like: Orderly decline, Fed tightening
    elif 25 <= vix_level <= 40 and days_declining > 60:
        analysis['most_similar'] = '2022 Bear (Orderly)'
        analysis['similarity_score'] = 0.7
        analysis['expected_pattern'] = 'Grinding decline with multiple false rallies'
        analysis['recommendations'] = [
            "Patience - these take 9-12 months",
            "Every +10% rally is a selling opportunity",
            "Favor value/energy over growth",
            "Don't fight the Fed",
            "Wait for 'pivot accepted' narrative to die",
        ]

    else:
        analysis['most_similar'] = 'Normal Correction'
        analysis['similarity_score'] = 0.3
        analysis['expected_pattern'] = 'Standard 10-15% correction, recovers in 3-6 months'
        analysis['recommendations'] = [
            "Standard buy-the-dip rules apply",
            "Scale in over 2-4 weeks",
            "Focus on quality names at support levels",
        ]

    return analysis


def format_crisis_summary(crisis: CrisisMemory) -> str:
    """Format a crisis summary for display"""
    return f"""
╔══════════════════════════════════════════════════════════════╗
║  {crisis.name.upper():^60}║
╠══════════════════════════════════════════════════════════════╣
║  Trigger: {crisis.trigger[:50]:50}  ║
║  Peak to Trough: {crisis.peak_to_trough_pct:+.1f}%                                     ║
║  Days to Bottom: {crisis.days_to_bottom}                                         ║
║  Days to Recover: {crisis.days_to_recover}                                       ║
║  VIX Peak: {crisis.vix_peak:.1f}                                            ║
╠══════════════════════════════════════════════════════════════╣
║  KEY LESSONS:                                                ║
"""  + "\n".join([f"║  • {lesson[:56]:56}  ║" for lesson in crisis.key_lessons[:5]]) + """
╚══════════════════════════════════════════════════════════════╝
"""


def get_what_recovers_first() -> str:
    """Get summary of what typically recovers first"""
    return """
╔══════════════════════════════════════════════════════════════╗
║           WHAT RECOVERS FIRST (Historical Pattern)           ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  FAST RECOVERERS (buy during panic):                        ║
║  • Technology (especially quality: AAPL, MSFT, GOOGL)       ║
║  • Healthcare (defensive + essential)                        ║
║  • Consumer Staples (people still buy food)                 ║
║                                                              ║
║  SLOW RECOVERERS (wait for confirmation):                   ║
║  • Financials (often at epicenter)                          ║
║  • Energy (depends on demand recovery)                       ║
║  • Industrials (economic cycle dependent)                   ║
║                                                              ║
║  AVOID DURING CRISIS:                                        ║
║  • Whatever sector CAUSED the crisis                        ║
║  • Highly leveraged companies                                ║
║  • Unprofitable growth stocks                               ║
║  • Airlines/Travel (if demand shock)                        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""

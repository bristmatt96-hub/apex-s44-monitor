// ═══════════════════════════════════════════════════════════════
// STRATEGIES IN CREDIT — DECK CONFIGURATION
// ═══════════════════════════════════════════════════════════════
//
// HOW TO USE:
// 1. Edit the sections below for each client meeting
// 2. Run: node deck.js
// 3. Your customised deck appears as strategies_in_credit.pptx
//
// You only need to edit this file — deck.js reads from it.
// ═══════════════════════════════════════════════════════════════

module.exports = {

  // ─────────────────────────────────────────
  // SECTION 1: CLIENT-SPECIFIC SETTINGS
  // Change these for each platform meeting
  // ─────────────────────────────────────────

  client: {

    // Which platform are you meeting?
    // Options: "Millennium", "Citadel / Surveyor", "Balyasny",
    //          "ExodusPoint", "Observatory", "Verition", "Generic"
    name: "Generic",

    // Capital ask — adjust per platform's typical pod size
    capitalAsk: "$75-100m",

    // What this platform cares about most (shows on "The Ask" slide)
    // Uncomment ONE block below, or write your own
    //
    // MILLENNIUM — obsessive about drawdown, Sharpe, independence
    // platformFit: [
    //   "Drawdown discipline: 5% hard stop aligns with Millennium's risk framework",
    //   "Sharpe >2.0 over 18 years — consistent risk-adjusted returns",
    //   "Solo PM model: capital efficient, no team overhead, immediate deployment",
    //   "Zero overlap with existing credit pods — correlation/tranche is a unique sleeve",
    //   "Proprietary technology removes dependency on platform infrastructure",
    // ],
    //
    // CITADEL / SURVEYOR — want to see how you fit their ecosystem
    // platformFit: [
    //   "Strategy complements Surveyor's existing fundamental credit teams",
    //   "Correlation/tranche trading adds a structural alpha source they don't currently have",
    //   "Technology stack integrates with Citadel's data infrastructure",
    //   "European credit focus diversifies their predominantly US credit exposure",
    //   "Solo PM with 28 years — minimal onboarding, immediate deployment",
    // ],
    //
    // BALYASNY — capacity, scaling, and process
    // platformFit: [
    //   "Clear capacity path: $75m start → $200m within 18 months",
    //   "Process-driven approach aligns with BAM's systematic culture",
    //   "Technology scales without headcount — AI does the work of 3 analysts",
    //   "European credit correlation is an underexplored niche with room to grow",
    //   "Risk framework designed for multi-manager from day one",
    // ],
    //
    // GENERIC (default) — works for any platform
    platformFit: [
      "28-year track record in European credit with verifiable P&L",
      "Proprietary monitoring and analysis technology — running live today",
      "Capital efficient: solo PM, no team overhead, immediate deployment",
      "Platform-compatible risk framework from day one",
      "Strategy that is genuinely differentiated from existing credit pods",
    ],
  },

  // ─────────────────────────────────────────
  // SECTION 2: YOUR TRACK RECORD
  // Update if numbers change or you want
  // to emphasise different stats
  // ─────────────────────────────────────────

  trackRecord: {
    avgAnnualPL:  "$30m",
    peakYearPL:   "$80m",
    sharpe:       ">2.0",
    bookManaged:  "$500m+",

    avgLabel:     "Avg. Annual P&L",
    avgSub:       "18-year average",
    peakLabel:    "Peak Year P&L",
    peakSub:      "Best single year",
    sharpeLabel:  "Sharpe Ratio",
    sharpeSub:    "Risk-adjusted",
    bookLabel:    "Book Managed",
    bookSub:      "Peak notional",

    headline: "A 28-year European credit veteran with proprietary technology, seeking a platform allocation to trade correlation dispersion and credit catalysts.",

    bio: "Built the European index tranche franchise at Bank of America from inception. Traded through every major credit cycle since 1997. Now building AI-augmented tools to systematise 28 years of pattern recognition.",
  },

  // ─────────────────────────────────────────
  // SECTION 3: THE PROCESS
  // Update descriptions as your workflow evolves
  // ─────────────────────────────────────────

  process: {
    steps: [
      {
        title: "SIGNAL",
        desc: "Credit monitoring system scans 202 iTraxx names for deterioration signals: filing anomalies, covenant triggers, earnings misses, liquidity stress",
      },
      {
        title: "FILTER",
        desc: "Discretionary overlay: Is this a real catalyst or noise? Cross-reference with documentation analysis, management behaviour, sector dynamics",
      },
      {
        title: "SIZE",
        desc: "Regime-aware position sizing. Aggressive in high-conviction / low-correlation environments. Defensive when correlation is rising",
      },
      {
        title: "EXECUTE",
        desc: "Index tranches, single-name CDS, cash bonds, equity options. Choose instrument based on liquidity, carry profile, and asymmetry",
      },
      {
        title: "MANAGE",
        desc: "Daily P&L attribution, scenario stress, correlation monitoring. Actively adjust hedges as thesis plays out or environment shifts",
      },
      {
        title: "EXIT",
        desc: "Pre-defined targets and stops. Exit when thesis is realised, invalidated, or risk/reward deteriorates. No hoping",
      },
    ],
  },

  // ─────────────────────────────────────────
  // SECTION 4: TECHNOLOGY STACK
  // Update as you build new tools or
  // enhance existing ones
  // ─────────────────────────────────────────

  technology: {
    headline: "AI-augmented tools I built — not bought",
    tools: [
      {
        title: "Credit Monitoring System",
        desc: "24/7 automated surveillance of all 202 iTraxx Europe S44 constituents. Scans SEC/FCA filings, earnings, covenant compliance, management changes. Sends real-time alerts to my phone via Telegram when signals trigger.",
        highlight: "Running live on dedicated infrastructure",
      },
      {
        title: "Documentation Analysis Engine",
        desc: "AI-powered scrubbing of credit agreements, indentures, and restricted payment baskets. Identifies covenant weaknesses and liability management vulnerabilities that traditional credit analysts miss.",
        highlight: "The edge most credit PMs don't have",
      },
      {
        title: "Liquidity Regime Dashboard",
        desc: "Howell-inspired global liquidity framework tracking central bank balance sheets, cross-border flows, and collateral availability. Maps the macro environment to regime-specific position sizing rules.",
        highlight: "Systematic overlay on discretionary judgment",
      },
    ],
  },

  // ─────────────────────────────────────────
  // SECTION 5: WHY IT'S REPEATABLE
  // The three structural edges
  // ─────────────────────────────────────────

  edges: [
    {
      title: "The Timing Gap Is Structural",
      body: "Credit deterioration signals appear 3-6 months before equity markets reprice. This gap exists because credit analysts read documentation that equity analysts ignore, and credit markets trade on fundamentals while equities trade on momentum. The gap has persisted for 20+ years across every cycle I've traded.",
    },
    {
      title: "Documentation Complexity Is Increasing, Not Decreasing",
      body: "Post-2020 credit agreements are more complex than ever — restricted payment baskets, J.Crew blockers, covenant-lite structures. Most buy-side credit analysts don't read the docs deeply enough. My documentation analysis engine exploits this widening information asymmetry at scale.",
    },
    {
      title: "Correlation Mispricing Is Persistent",
      body: "Index tranche markets consistently misprice tail correlation because most participants are hedgers (banks buying protection) or yield seekers (selling mezzanine). There are very few dedicated correlation traders who understand both the technical pricing and the fundamental credit drivers. I built this franchise — I know where it misprices.",
    },
  ],

  // ─────────────────────────────────────────
  // SECTION 6: ALPHA ATTRIBUTION
  // What's portable and what's not
  // ─────────────────────────────────────────

  alpha: {
    portable: [
      "Correlation dispersion trading — identifying when tranche pricing diverges from fundamental credit reality",
      "Credit catalyst identification — the 3-6 month timing gap between documentation/fundamental signals and market repricing",
      "Regime awareness — knowing when to lean in (low correlation, high dispersion) vs. when to sit on hands (correlation spike, liquidity withdrawal)",
      "Documentation edge — deep knowledge of covenant structures that AI tools now scale across the entire universe",
      "28 years of pattern recognition across every cycle since Asian crisis",
    ],
    notPortable: [
      "Flow franchise P&L — the bid/offer capture from running a bank book doesn't exist on buy-side. I'm not counting it.",
      "Bank balance sheet — sell-side could warehouse risk that a pod can't. My sizing accounts for this.",
      "2015-16 lesson — I was wrong-footed on energy credit contagion. I've built explicit regime detection to prevent this class of error.",
    ],
    portableEstimate: "Estimated portable alpha component: $15-25m annually at $75-100m capital allocation",
  },

  // ─────────────────────────────────────────
  // SECTION 7: TRADE EXAMPLE
  // Swap in different examples per meeting
  // ─────────────────────────────────────────

  tradeExample: {
    title: "How the six-step process generates a trade",
    steps: [
      { step: "SIGNAL",  detail: "Monitoring system flags restricted payment basket activity at Company X — €200m dividend recap filed while leverage at 5.5x" },
      { step: "FILTER",  detail: "Documentation engine confirms weak covenant package: no restricted payments cap, no portability limits. Management history shows pattern of creditor-hostile behaviour" },
      { step: "SIZE",    detail: "Liquidity regime: neutral. Correlation environment: low dispersion → single-name opportunity, not index. Size: 2% of capital via 5yr CDS protection" },
      { step: "EXECUTE", detail: "Buy CDS protection at 350bps. Simultaneously buy 3-month equity puts to capture the cross-asset timing gap as equity analysts haven't yet focused on the credit deterioration" },
      { step: "MANAGE",  detail: "Daily monitoring of spread movement, CDS-bond basis, and equity implied vol. Hedge delta if equity moves first. Roll CDS if curve flattens" },
      { step: "EXIT",    detail: "CDS widens to 550bps on downgrade (target hit). Equity puts +180%. Total P&L: $1.8m on $75m book = 2.4% return from single trade" },
    ],
  },

  // ─────────────────────────────────────────
  // SECTION 8: RISK FRAMEWORK
  // ─────────────────────────────────────────

  risk: {
    limits: [
      { param: "Daily Stop-Loss",            limit: "1.0%",         action: "Flatten all positions; review before resuming" },
      { param: "Weekly Stop-Loss",           limit: "2.0%",         action: "50% risk reduction; regime reassessment" },
      { param: "Monthly Drawdown",           limit: "3.5%",         action: "Reduce to 25% risk; CIO approval to rebuild" },
      { param: "Max Peak-to-Trough",         limit: "5.0%",         action: "Full de-risk; strategy review with risk committee" },
      { param: "Single-Name Concentration",  limit: "5% per name",  action: "Hard limit — no exceptions" },
      { param: "Liquidity Test",             limit: "90% in 5 days",action: "Ongoing monitoring — portfolio must be liquidatable" },
    ],
    scenarios: [
      { title: "Spread Shock",          desc: "iTraxx Main +50bps, Xover +150bps. Portfolio impact modelled daily. Max loss at current positioning: -1.8%" },
      { title: "Correlation Spike",     desc: "Correlation to 0.8 (GFC levels). Tranche positions marked to stressed implied correlation surface. Automatic hedge trigger" },
      { title: "Liquidity Withdrawal",  desc: "Howell regime shifts to contraction. Pre-programmed 50% gross reduction within 48 hours. No discretion required" },
    ],
  },

  // ─────────────────────────────────────────
  // SECTION 9: CONTACT
  // ─────────────────────────────────────────

  contact: {
    name:  "Matt Bristow",
    email: "toget_mattbristow@hotmail.co.uk",
    phone: "+44 7809 158381",
  },
};

# European LME Playbook

## Overview

European high yield has increasingly adopted US LME tactics, but with important jurisdictional and structural differences. This playbook covers Europe-specific considerations.

---

## European Restructuring Mechanisms

### 1. UK Scheme of Arrangement (Part 26 Companies Act 2006)

**What It Is:**
Court-supervised restructuring that binds all creditors (including dissenters) if approved by requisite majorities.

**Approval Thresholds:**
- 75% by value in each class
- Majority by number (>50%) in each class
- Court sanction required

**Key Features:**
- Can cram down dissenting creditors
- Cross-class cram-down possible (new Restructuring Plan)
- Used for debt-for-equity swaps, maturity extensions, haircuts
- Relatively quick (3-4 months typical)

**CDS Implications:**
- Usually triggers Restructuring Credit Event
- Binding on all holders = meets ISDA criteria
- Watch for class composition manipulation

**Notable Uses:** Codere, DTEK, various UK retail names

---

### 2. UK Restructuring Plan (Part 26A - "Super Scheme")

**What It Is:**
Enhanced scheme introduced 2020, allows cross-class cram-down.

**Key Features:**
- Can cram down entire dissenting classes
- "No worse off" test vs relevant alternative
- Court has discretion on fairness
- More powerful than traditional Scheme

**When Used:**
- When unanimous consent impossible
- When junior creditors blocking
- Complex multi-class structures

**CDS Implications:**
- Same as Scheme - likely Restructuring trigger

---

### 3. Netherlands WHOA (Wet Homologatie Onderhands Akkoord)

**What It Is:**
Dutch restructuring law (2021) allowing court-confirmed plans without formal insolvency.

**Approval Thresholds:**
- 2/3 by value in each class
- Cross-class cram-down possible
- "Best interests" and "absolute priority" tests

**Key Features:**
- Debtor-in-possession (no administrator)
- Can be initiated by debtor or creditors
- Restructuring stays possible
- Can bind dissenting classes

**Why Netherlands:**
- Many European HY holdcos in Netherlands
- Tax-efficient structures
- Predictable legal system
- WHOA designed to compete with UK Scheme

**CDS Implications:**
- Likely Restructuring Credit Event if binding
- May need DC determination

---

### 4. German StaRUG (Stabilisierungs- und Restrukturierungsrahmen)

**What It Is:**
German pre-insolvency restructuring framework (2021).

**Key Features:**
- Court confirmation without insolvency
- Cross-class cram-down possible
- Moratorium available
- Creditor-friendly (compared to some)

**Limitations:**
- Less tested than UK Scheme
- Some complexity with German law

---

### 5. Irish Examinership

**What It Is:**
Court-supervised restructuring with independent examiner.

**Key Features:**
- 70-day maximum period
- Examiner proposes scheme
- Court approval required
- Can impair all creditors

**Why Ireland:**
- Many European HY issuers Irish-incorporated
- Tax reasons
- English-speaking, common law

---

### 6. French Sauvegarde / Accelerated Safeguard

**What It Is:**
French pre-insolvency proceedings allowing restructuring.

**Key Features:**
- Sauvegarde: debtor must be in difficulty but not insolvent
- Accelerated Safeguard: fast-track for pre-negotiated deals
- Committee voting by class
- Cross-class cram-down limited

**French Specificities:**
- Employee protection strong
- Courts may prioritize jobs over creditors
- Less predictable outcomes

---

## European vs US: Key Differences

| Feature | US | Europe |
|---------|-----|--------|
| **Primary Forum** | Chapter 11 (Delaware/SDNY) | UK Scheme / Local |
| **Automatic Stay** | Yes (Ch.11) | Varies by jurisdiction |
| **DIP Financing** | Established | Less developed |
| **Cross-Class Cram-Down** | Yes (Ch.11) | Yes (Scheme/WHOA/StaRUG) |
| **Pre-Pack Speed** | Moderate | Can be faster (UK) |
| **Holdco Jurisdiction** | Delaware/NY | Luxembourg/Netherlands/Ireland |
| **Opco Jurisdiction** | Often US | Local operating countries |
| **Enforcement** | Clear | Multi-jurisdiction complexity |
| **Intercreditor Docs** | Established precedents | Evolving |
| **LME Precedents** | Extensive | Growing rapidly |

---

## European Holdco Structures

### Common Structure
```
Luxembourg Holdco (bonds issued here)
    ↓
Netherlands Intermediate (sometimes)
    ↓
UK/German/French OpCo (operating assets)
    ↓
Local Subsidiaries (various jurisdictions)
```

### Why This Matters for LME

1. **Jurisdictional Arbitrage:**
   - Restructuring can be done at different levels
   - Choice of forum affects creditor rights
   - Luxembourg traditionally creditor-unfriendly
   - Netherlands/UK more predictable

2. **Structural Subordination:**
   - Holdco debt structurally junior to opco debt
   - Value may sit at opco level
   - Intercreditor agreements critical

3. **Multi-Jurisdiction Complexity:**
   - Different laws for different entities
   - Enforcement challenges
   - Recognition of foreign proceedings

---

## European Sponsor Behavior Patterns

### Aggressive Sponsors (Watch Closely)
| Sponsor | Known For | Names in XO S44 |
|---------|-----------|-----------------|
| Bain Capital | Aggressive value extraction | Various |
| Apollo | Complex structures | Various |
| KKR | Large LBOs, dividend recaps | Various |
| CVC | Mixed record | Various |
| Permira | Long holds when stuck | CABB |

### Sponsor Distress Playbook
1. **Milk the Asset:** Dividend recaps while possible
2. **Delay Recognition:** Covenant holidays, amendments
3. **Control the Process:** Hire advisors early, control information
4. **Play Creditors:** Different treatment for different tranches
5. **Preserve Optionality:** Keep multiple paths open
6. **Extract Value:** Management fees, monitoring fees continue
7. **Negotiate from Strength:** Threaten bankruptcy if exchange rejected

---

## European-Specific LME Tactics

### 1. UK Scheme Shopping
**Tactic:** Structure transaction to access UK Scheme even if not UK company.

**Mechanism:**
- Establish "sufficient connection" to UK
- Move COMI (Center of Main Interest) if needed
- English law governing bonds helps

**Defense:**
- Challenge jurisdiction
- Argue insufficient connection
- Object at sanction hearing

### 2. Dutch WHOA Play
**Tactic:** Use WHOA for non-Dutch companies with Dutch elements.

**Mechanism:**
- Dutch holdco or intermediate
- Dutch-law governed debt
- Quick timeline

### 3. Double Luxco
**Tactic:** Use Luxembourg vehicles to complicate creditor enforcement.

**Mechanism:**
- Multiple Luxembourg entities
- Opaque ownership structures
- Difficult to pierce

### 4. Multi-Jurisdiction Asset Shuffle
**Tactic:** Move assets to creditor-unfriendly jurisdictions.

**Mechanism:**
- Transfer to unrestricted subs in favorable jurisdictions
- Intercompany loans across borders
- Complicate enforcement

### 5. European Up-Tier
**Tactic:** Serta-style up-tier using European structures.

**Mechanism:**
- Same concept: subset exchanges into super-priority
- May use European-law mechanisms
- Less precedent (still evolving)

---

## Jurisdiction Reference

### Luxembourg
- **Restructuring Options:** Composition with creditors, controlled management
- **Creditor Friendliness:** LOW (historically)
- **Common Use:** Holdco for tax efficiency
- **Watch For:** Difficulty enforcing against Luxco

### Netherlands
- **Restructuring Options:** WHOA (new), Suspension of Payments, Bankruptcy
- **Creditor Friendliness:** MEDIUM-HIGH (improving with WHOA)
- **Common Use:** Intermediate holding companies
- **Watch For:** WHOA becoming preferred European forum

### United Kingdom
- **Restructuring Options:** Scheme, Restructuring Plan, Administration, CVA
- **Creditor Friendliness:** MEDIUM-HIGH (predictable)
- **Common Use:** Operating companies, some holdcos
- **Watch For:** Scheme/Restructuring Plan for cross-border

### Ireland
- **Restructuring Options:** Examinership, Scheme of Arrangement
- **Creditor Friendliness:** MEDIUM
- **Common Use:** Holding companies (tax), aircraft leasing
- **Watch For:** 70-day examinership window

### Germany
- **Restructuring Options:** StaRUG, Insolvency Plan, Self-Administration
- **Creditor Friendliness:** MEDIUM-HIGH (improving)
- **Common Use:** Operating companies
- **Watch For:** StaRUG gaining traction

### France
- **Restructuring Options:** Sauvegarde, Redressement, Liquidation
- **Creditor Friendliness:** LOW-MEDIUM (employee-focused)
- **Common Use:** Operating companies
- **Watch For:** Court may prioritize employment

---

## European CDS Specifics

### iTraxx Crossover (XO)
- Main European HY CDS index
- 75 names, equal weight
- Rolls every 6 months (Mar/Sep)
- Mod-Mod-R typically

### Single-Name European HY CDS
- Less liquid than US
- Wider bid-ask spreads
- Mod-Mod-R standard
- DC determinations sometimes slower

### European DC (EMEA DC)
- Separate from Americas DC
- May interpret differently
- Watch for precedent-setting decisions

### Common Questions for European CDS
1. **Is the Scheme/WHOA a Restructuring?** Usually YES if binding and distressed
2. **Is the exchange voluntary?** If truly voluntary (can keep old bonds paying), may be NO
3. **What's the Reference Entity?** Check carefully for multi-entity structures
4. **Deliverable after restructuring?** New instruments may not qualify

---

## Monitoring European LME

### Key Sources
| Source | Content | Access |
|--------|---------|--------|
| Debtwire | News, intelligence | Subscription |
| 9fin | Covenant analysis, news | Subscription |
| Reorg Research | Restructuring analysis | Subscription |
| LCD (Pitchbook) | Loan/CLO news | Subscription |
| Bloomberg | Pricing, news | Terminal |
| Companies House (UK) | Filings | Free |
| KvK (Netherlands) | Filings | Paid |
| RCS (Luxembourg) | Filings | Paid |

### Red Flags in European Context
- COMI shift announcements
- New legal entity formations
- Change of auditor
- Board changes (restructuring specialists)
- Local regulatory filings
- Court filings in any jurisdiction


# Recovery Analysis Framework

## Overview

When LME is likely, shift focus from credit analysis to recovery analysis. This framework helps estimate potential recoveries across scenarios.

---

## Recovery Estimation Methods

### 1. Trading Price Method

**Concept:** Market price reflects collective recovery expectations.

**Formula:**
```
Implied Recovery = Current Price / 100
```

**Example:**
- Bond at 75 → Market expects ~75% recovery
- Bond at 45 → Market expects ~45% recovery

**Limitations:**
- Includes technical factors (liquidity, forced selling)
- May not reflect final recovery
- Basis between price and eventual recovery common

### 2. Enterprise Value Method

**Concept:** Estimate EV, subtract senior claims, allocate to your tranche.

**Steps:**
1. Estimate going-concern EV (EBITDA × multiple)
2. Subtract administrative claims
3. Waterfall through capital structure
4. Calculate % to your tranche

**Example:**
```
EBITDA: $200m
Multiple: 5.0x
EV: $1,000m

Capital Structure:
- Admin claims: $50m
- 1L TL: $400m (100% recovery)
- 1L Notes: $300m (100% recovery)
- 2L Notes: $200m (125/200 = 62.5% recovery)
- Unsecured: $300m (0% recovery)
- Remaining value: $250m (to 1L/2L)

1L gets: $700m / $700m = 100%
2L gets: $250m / $200m = 125% → capped at 100% + accrued
Unsecured: $0 → 0%
```

### 3. Liquidation Value Method

**Concept:** What would assets fetch in liquidation?

**Components:**
- Cash: 100%
- Receivables: 70-90%
- Inventory: 50-70%
- PP&E: 20-50%
- Intangibles: 0-30%
- Goodwill: 0%

**When to Use:**
- Businesses with no going-concern value
- Asset-heavy companies
- Real estate
- Distressed sales

### 4. Comparable Transactions

**Concept:** Look at similar restructurings for recovery benchmarks.

**Sources:**
- Moody's/S&P recovery studies
- Historical LME outcomes
- Sector-specific precedents

---

## Recovery by Seniority (Historical Averages)

| Seniority | Average Recovery | Range |
|-----------|-----------------|-------|
| 1st Lien Bank Debt | 70-80% | 50-100% |
| 1st Lien Notes | 60-70% | 40-100% |
| 2nd Lien | 30-50% | 0-80% |
| Senior Unsecured | 30-45% | 0-70% |
| Subordinated | 10-25% | 0-50% |
| Equity | 0-5% | 0-20% |

**Note:** European recovery rates historically slightly lower than US.

---

## LME-Specific Recovery Considerations

### Exchange Offers

**Typical Mechanics:**
- Old bonds exchanged for new package
- Package may include: new notes + equity + cash
- Usually at discount to par
- Participation incentive (early bird)

**Recovery Calculation:**
```
Recovery = (New Notes Value + Equity Value + Cash) / Old Par

Example:
Old Notes: $100 par
Exchange: $60 new notes + $15 equity + $5 cash
Recovery: 80%
```

**Watch For:**
- New notes trading level post-exchange
- Equity value realization timeline
- Governance rights in new structure
- Fees extracted in transaction

### Up-Tier Transactions

**Recovery Impact:**
- Participating lenders: Better recovery (often near par)
- Non-participating: Severely impaired (20-50% typical)
- Differential can be 30-50pts

**Example (Serta-style):**
```
Before: All lenders pari passu
After:
- Participating (55%): Exchange into new super-priority
- Non-participating (45%): Remain in now-junior debt

Eventual Recovery:
- Participants: 90%+
- Non-participants: 20-30%
```

### Drop-Down Transactions

**Recovery Impact:**
- Remaining bondholders lose access to dropped assets
- Recovery depends on what's left in restricted group
- Can be devastating without J.Crew blocker

**Example:**
```
Before: $500m bonds secured by all assets
After: $300m of assets moved to unrestricted sub

Effective Collateral: $200m
Potential Recovery: 40% (vs 100% pre-drop)
```

---

## Scenario Analysis Template

### Base Case
```
Assumption: Consensual restructuring, going-concern
EV Multiple: Xₓ
EV: $XXXm
Recovery: XX%
```

### Downside Case
```
Assumption: Contested, longer timeline, value leakage
EV Multiple: Xₓ (lower)
EV: $XXXm
Recovery: XX%
```

### Liquidation Case
```
Assumption: No going-concern, asset sale
Liquidation Value: $XXXm
Recovery: XX%
```

### LME Adverse Case
```
Assumption: Aggressive LME, non-participant
Value Extraction: $XXm
Recovery: XX% (potentially much lower)
```

---

## XO S44 Recovery Estimates

### Tier 1: Active Restructuring

**Very Group (Distress 100 - RESTRUCTURING)**
```
Status: Carlyle selling 2 months post-acquisition
Likely Outcome: Significant haircut or asset sale
Recovery Estimate: 20-40%
Key Driver: What Carlyle can extract in fire sale
CDS: Credit Event likely triggered
```

**INEOS Quattro (Distress 87 - STRESSED)**
```
Status: Bonds at 67-75, yields 17-33%
Trading Implied Recovery: 67-75%
Recovery Estimate: 50-70%
Key Driver: Chemicals cycle, separation from INEOS Group
CDS: High probability of triggering
```

**Merlin (Distress 53 - STRESSED)**
```
Status: "Evaluating liquidity options", bonds 63-76
Trading Implied Recovery: 63-76%
Recovery Estimate: 55-75%
Key Driver: Theme park valuations, Blackstone support
CDS: Elevated probability
```

### Tier 2: Elevated Risk

**INEOS Group (Distress 44)**
```
Status: Bonds at 79-86
Trading Implied Recovery: 79-86%
Recovery Estimate: 65-80%
Key Driver: Interplay with INEOS Quattro, Ratcliffe support
CDS: Medium-High probability
```

**Stonegate (Distress 20)**
```
Status: Prior restructuring, 7.6x leverage
Recovery Estimate: 70-85%
Key Driver: UK pubs asset base, trading recovery
CDS: Medium probability
```

---

## Recovery Drivers by Sector

### Chemicals (INEOS, CABB)
- Cyclical asset base
- Commodity exposure
- Plant valuations: 4-6x EBITDA in distress
- Environmental liabilities can reduce value
- Recovery: Typically 50-70% for secured

### Retail/Consumer (Very, Stonegate)
- Inventory liquidation risk
- Lease liabilities complicate
- Brand value uncertain
- Recovery: Highly variable, 30-70%

### Infrastructure (Mundys, Aggreko)
- Long-duration concessions valuable
- Contracted cash flows
- Strategic buyer interest
- Recovery: Usually higher, 70-90% for secured

### Gaming/Leisure (Merlin, Cirsa)
- Asset-heavy (real estate, equipment)
- License values
- Recovery: Moderate, 50-75%

### Telecom/Media
- Subscriber base valuation
- Infrastructure value
- Spectrum assets
- Recovery: Varies widely by asset mix

---

## Documentation Impact on Recovery

### Strong Documentation = Higher Recovery
- J.Crew blockers preserve collateral
- Anti-Serta prevents priming
- Tight baskets limit leakage
- Recovery uplift: 10-20%

### Weak Documentation = Recovery Risk
- Unrestricted sub leakage
- Up-tier vulnerability
- Asset stripping
- Recovery reduction: 20-40%

---

## CDS vs Cash Recovery

**Important:** CDS recovery ≠ Cash bond recovery

| Factor | CDS | Cash |
|--------|-----|------|
| Timing | Auction within weeks | May take months/years |
| Deliverable | Must find qualifying bonds | Own what you own |
| Recovery basis | Auction price | Actual distribution |
| Accrued interest | May not get | Usually get |
| Currency | USD typically | Original currency |

**Basis Opportunities:**
- CDS recovery often differs from eventual cash recovery
- Can create trading opportunities
- Auction mechanics matter

---

## Recovery Monitoring Checklist

When credit enters distress:

- [ ] Calculate trading implied recovery
- [ ] Estimate EV range (bear/base/bull)
- [ ] Map capital structure waterfall
- [ ] Identify priority claims (admin, DIP, etc.)
- [ ] Assess documentation vulnerability
- [ ] Estimate LME-specific scenarios
- [ ] Compare to peer precedents
- [ ] Monitor advisor signals
- [ ] Track creditor group formation
- [ ] Assess CDS trigger probability
- [ ] Model auction recovery scenarios


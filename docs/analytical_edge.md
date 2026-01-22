# Analytical Edge Framework

## Beyond Consensus

Most analysts do:
- Read Debtwire/9fin report
- Look at leverage ratio
- Check bond price
- Parrot rating agency

**Edge comes from:**
- Asking questions others don't
- Seeing trajectory before it's obvious
- Understanding what's actually priced in
- Knowing what catalysts matter

---

## The 10 Questions Others Don't Ask

### 1. "What does the sponsor actually want?"

Don't assume sponsor = supportive. Ask:
- How long have they held? (>7 years = desperate to exit)
- What's their cost basis? (underwater = different behavior)
- Is the fund near end of life? (pressure to mark/exit)
- Have they done LMEs before? (reveals playbook)
- What's their reputation worth? (some protect it, some don't)

**Apply to portfolio:**
| Credit | Sponsor | Hold Period | Likely Behavior |
|--------|---------|-------------|-----------------|
| CABB | Permira | 11 years | Desperate to exit, may accept haircut |
| Stonegate | TDR | 15 years | Will take any exit |
| Merlin | Blackstone | 5 years | Protect reputation, may support |
| Aggreko | Consortium | 4.5 years | Looking to sell, not inject |

---

### 2. "What's the REAL liquidity runway?"

Not just: Cash + Revolver
But: Cash + Revolver - Restricted Cash - Minimum Operating Cash - Near-term Capex - Interest

```
Example calculation:
Reported cash: $200m
Less: Trapped in foreign subs: -$50m
Less: Minimum operating: -$30m
Less: Capex next 12mo: -$60m
Less: Interest next 12mo: -$80m
Plus: Revolver available: +$100m
= TRUE RUNWAY: $80m (not $300m headline)
```

**Questions to dig:**
- How much cash is at non-guarantor subs?
- What's trapped by local regulations?
- Any letters of credit eating revolver?
- Capex: truly discretionary or maintenance?

---

### 3. "What's the covenant headroom trajectory?"

Not just: "They have 20% headroom"
But: "At current trajectory, breach in Q3"

```
Model forward:
Current EBITDA: $100m, declining 10% QoQ
Covenant: 5.0x Net Debt/EBITDA
Current: 4.0x

Q1: EBITDA $90m → 4.4x
Q2: EBITDA $81m → 4.9x
Q3: EBITDA $73m → 5.5x ← BREACH
```

**This is the edge:** Know WHEN the breach comes, not just IF.

---

### 4. "What's the maturity REAL refinancing risk?"

Not just: "Maturity in 2027"
But: "Given current leverage/spreads, can they actually refinance?"

**Refinancing reality check:**
```
Current: 5.0x leverage, B3 rating
Market: New B3 issuance at 10% yield
Interest on new debt: $100m × 10% = $10m
Current interest: $100m × 6% = $6m

Interest coverage drops from 3.0x to 2.0x
→ May not be refinanceable at any price
→ Maturity = restructuring trigger
```

---

### 5. "Who actually OWNS this debt?"

Different owners = different behavior:
- CLOs: Forced sellers at downgrade, can't participate in LME
- Hedge funds: Will play hardball, may buy into blocking position
- Insurance: Regulatory constraints, often passive
- Banks: Relationship considerations, may extend
- Distressed funds: Want the LME, bought for recovery

**Edge:** If you know ownership, you predict behavior.

**How to find:**
- 13F filings (US managers)
- Company announcements (>5% holders)
- CLO trustee reports
- Trade color from sellside

---

### 6. "What's the EBITDA quality?"

Not just: "EBITDA is $100m"
But: "Recurring, unmanipulated EBITDA is $70m"

**Adjustments to reverse:**
| Add-back | Skepticism Level |
|----------|------------------|
| "One-time" costs | HIGH (often recurring) |
| Stock comp | MEDIUM (real cost) |
| Restructuring | HIGH (if every year = operating) |
| "Pro forma" synergies | VERY HIGH (rarely achieved) |
| Working capital normalization | MEDIUM |

**Rule:** If adjusted EBITDA is >20% above GAAP, be very skeptical.

---

### 7. "What happens to EBITDA in recession?"

Not just: "Current EBITDA supports leverage"
But: "In downturn, what's the floor?"

**Stress test:**
```
Current EBITDA: $100m
Revenue decline scenario: -20%
Operating leverage: 3x
EBITDA decline: -60%
Stressed EBITDA: $40m

Current leverage: 4x → Stressed: 10x
```

**Sector beta to GDP:**
| Sector | EBITDA Sensitivity |
|--------|-------------------|
| Consumer discretionary | HIGH (luxury, travel) |
| Staples | LOW (food, essentials) |
| Industrials/Chemicals | HIGH (cyclical) |
| Telecom/Media | MEDIUM |
| Healthcare | LOW |
| Gaming | MEDIUM-HIGH |

---

### 8. "What's the ACTUAL asset value?"

Going concern multiples ≠ distressed sale reality

**Haircuts to apply:**
| Asset Type | Going Concern | Distressed Sale |
|------------|---------------|-----------------|
| Real estate | 8-10x | 5-7x |
| Equipment | 5-7x | 3-5x |
| Brands/IP | 10-15x | 2-5x |
| Customer relationships | 8-12x | 0-3x |
| Goodwill | Book value | Zero |

**Recovery calculation:**
```
Going concern EV: $500m
Distressed haircut: 40%
Realistic EV: $300m
Senior debt: $250m
Recovery: $300m / $250m = 100% + some

BUT if forced liquidation:
Liquidation value: $150m
Recovery: 60%
```

---

### 9. "What does the bond price IMPLY about expectations?"

Reverse engineer market expectations:

**Example at 75 price:**
```
Price: 75
Implies market expects: 75% recovery
Current leverage: 7x
Implied EV at recovery: Covers ~5x debt
Implied EBITDA multiple: ~5x

So market is pricing:
- Either EBITDA collapse, or
- Distressed multiple, or
- Significant haircut
```

**Opportunity if you disagree:**
- If you think recovery is 90% → Buy at 75
- If you think recovery is 60% → Sell/Short

---

### 10. "What's the path dependency?"

Not just: "This could be good or bad"
But: "What sequence of events leads to each outcome?"

**Decision tree:**
```
INEOS Quattro:
├── Chemicals recover in 6mo
│   ├── EBITDA to $1.2bn → Refinance 2027 → Bonds to 95
│   └── EBITDA flat → Can't refi → LME → Bonds to 65
└── Chemicals stay weak
    ├── Ratcliffe injects equity → Bonds to 85
    └── No support → LME certain → Bonds to 55-60
```

**Edge:** Map the tree, assign probabilities, calculate expected value.

---

## Building Conviction

### High Conviction Long (Must have ALL):
- [ ] Trajectory clearly improving
- [ ] Market hasn't priced it (cheap to trajectory)
- [ ] Catalyst identified with timeline
- [ ] Downside understood and acceptable
- [ ] No documentation red flags
- [ ] Liquidity to exit

### High Conviction Short (Must have ALL):
- [ ] Trajectory clearly deteriorating
- [ ] Market in denial (expensive to trajectory)
- [ ] Catalyst identified with timeline
- [ ] Can borrow/find CDS
- [ ] No squeeze risk
- [ ] Position size manageable

---

## Variant Perception Framework

**What does consensus think?**
(Read sellside reports, Debtwire, talk to brokers)

**Where might consensus be wrong?**
| If Consensus Is | Consider |
|-----------------|----------|
| "Sponsor will support" | What if fund is end of life? |
| "Asset value protects" | What in distressed sale? |
| "Refinancing is fine" | At what spread? Coverage? |
| "LME is priced" | What if worse than priced? |
| "Improvement coming" | What's the evidence? |

**Your variant must be:**
1. Different from consensus
2. Supported by evidence
3. Actionable in size
4. Testable (you'll know if wrong)

---

## XO S44 Application

### INEOS Quattro - Key Questions

**Consensus:** "Distressed, LME coming, priced at 70"

**Variant questions:**
1. What if chemicals cycle turns faster than expected?
   - Historical cycles: 18-24 months trough
   - Current trough: 24 months
   - Early indicators: PMI, destocking, pricing

2. What if Ratcliffe injects equity?
   - His net worth: ~$15bn
   - Amount needed: ~$2bn
   - Probability: 20%? 30%?
   - Impact: Bonds to 85-90

3. What if intercompany with INEOS Group is negative?
   - Watch for asset transfers
   - Check Companies House for new charges
   - Monitor INEOS Group relative value

**My variant:** [Document yours]

---

### Merlin - Key Questions

**Consensus:** "LME imminent, Blackstone will manage process"

**Variant questions:**
1. What if theme park valuations hold up?
   - Real estate value
   - Brand value (Legoland, Tussauds)
   - Strategic buyer interest?

2. How will Blackstone play this?
   - Their reputation matters
   - They've supported portfolio cos before
   - But also done aggressive LMEs

3. What's the holdout strategy worth?
   - Can you block a scheme?
   - What's the holdout premium?
   - Litigation value?

**My variant:** [Document yours]


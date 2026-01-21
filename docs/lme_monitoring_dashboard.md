# LME Monitoring Dashboard

## Daily/Weekly Monitoring Checklist

### 1. Market Price Signals

| Signal | Threshold | Action | Frequency |
|--------|-----------|--------|-----------|
| Bond drops >5pts in day | Any name | Investigate immediately | Daily |
| Bond drops >10pts in week | Any name | Full doc review | Daily |
| Bonds cross below 90 | Any name | Add to LME watchlist | Daily |
| Bonds cross below 80 | Any name | Assume LME likely | Daily |
| Bonds cross below 70 | Any name | Assume restructuring | Daily |
| CDS-bond basis >200bps | Any name | Check CDS triggers | Weekly |
| Tranche price divergence | Multi-tranche | Structural play underway | Daily |

### 2. News/Headline Triggers

**CRITICAL (Act Immediately):**
- "[Company] hires [restructuring advisor]"
- "[Company] designates unrestricted subsidiary"
- "[Company] announces exchange offer"
- "Ad hoc group forms at [Company]"
- "[Company] misses interest payment"
- "Scheme of Arrangement filed"

**HIGH (Same-Day Review):**
- "[Company] exploring strategic alternatives"
- "[Sponsor] considering options for [Company]"
- "Covenant waiver/amendment at [Company]"
- "[Company] draws on revolver"
- "Rating downgrade to CCC"
- "[Company] sells [asset] to affiliate"

**MEDIUM (Weekly Review):**
- "Rating downgrade"
- "Outlook revised to Negative"
- "[Company] appoints new CFO"
- "[Sponsor] takes dividend"
- "Intercompany reorganization"

### 3. Advisor Tracking

When these advisors appear, LME is imminent:

**Company-Side (Debtor):**
| Advisor | Specialty | Alert Level |
|---------|-----------|-------------|
| Houlihan Lokey | Restructuring | CRITICAL |
| Evercore | Restructuring | CRITICAL |
| PJT Partners | Restructuring | CRITICAL |
| Lazard | Restructuring | CRITICAL |
| Rothschild | Restructuring | CRITICAL |
| Moelis | Restructuring | CRITICAL |
| Kirkland & Ellis | Legal (debtor) | CRITICAL |
| Weil Gotshal | Legal | CRITICAL |
| Latham & Watkins | Legal | HIGH |
| FTI Consulting | Operational | MEDIUM |
| AlixPartners | Operational | MEDIUM |

**Creditor-Side:**
| Advisor | Signal |
|---------|--------|
| Milbank | Creditor group forming |
| Gibson Dunn | Creditor defense |
| Akin Gump | Creditor group |
| Paul Weiss | Creditor group |
| Davis Polk | Creditor group |

---

## Portfolio LME Risk Tiers

### Tier 1: CRITICAL (Monitor Daily)
Credits with:
- Distress score >50
- Bonds <80
- Lifecycle = "STRESSED" or "RESTRUCTURING"
- Advisor hired
- "Evaluating liquidity options" language

**Current Tier 1 Names:**
| Credit | Distress | Bonds | Status |
|--------|----------|-------|--------|
| Very Group | 100 | N/A | RESTRUCTURING |
| INEOS Quattro | 87 | 67-75 | STRESSED |
| Merlin | 53 | 63-76 | STRESSED |

### Tier 2: HIGH (Monitor 2-3x/Week)
Credits with:
- Distress score 30-50
- Bonds 80-90
- PE-backed with 8+ year hold
- Explicit "cash burn" language
- Recent rating downgrade with Negative outlook

**Current Tier 2 Names:**
| Credit | Distress | Bonds | Key Concern |
|--------|----------|-------|-------------|
| INEOS Group | 44 | 79-86 | 9x leverage, downgrades |
| Stonegate | 20 | ~par | Prior restructuring, 7.6x leverage |

### Tier 3: ELEVATED (Monitor Weekly)
Credits with:
- Distress score 15-30
- PE-backed with 5+ year hold
- Operational restructuring (site closures, asset sales)
- Negative rating outlook

**Current Tier 3 Names:**
| Credit | Distress | Concern |
|--------|----------|---------|
| CABB | 15 | Permira 11yr hold, cash burn |
| Aggreko | 15 | S&P Negative, large debt |

### Tier 4: WATCH (Monitor Monthly)
Credits with:
- Distress score 10-15
- High leverage but stable
- ZIRP-era documentation

---

## LME Phase Indicators

### Phase 0: Pre-Distress (Monitoring)
**Signals:**
- Normal trading levels
- Ratings stable
- No advisor activity

**Action:** Standard monitoring

### Phase 1: Early Warning (Elevated Monitoring)
**Signals:**
- Bond price decline (>90, declining)
- Rating outlook to Negative
- EBITDA deterioration
- Sponsor taking dividends despite leverage

**Action:** Review documentation, assess covenant headroom

### Phase 2: Distress Acknowledged (Active Monitoring)
**Signals:**
- Bonds <90
- Rating downgrade
- "Exploring strategic alternatives" language
- Advisor appointment rumors

**Action:** Full doc analysis, assess LME vulnerability, consider position

### Phase 3: LME Preparation (Critical Monitoring)
**Signals:**
- Advisor formally hired
- Bonds <80
- "Evaluating liquidity options"
- Revolver draw
- Ad hoc creditor groups forming

**Action:** Assess participation strategy, legal review, sign cooperation agreements

### Phase 4: LME Execution (Active Management)
**Signals:**
- Exchange offer announced
- Consent solicitation launched
- Scheme of Arrangement filed
- Bankruptcy filing

**Action:** Make participation decision, assess recovery, CDS trigger analysis

### Phase 5: Post-LME (Recovery Assessment)
**Signals:**
- Transaction closed
- New securities issued
- Emergence from restructuring

**Action:** Assess new capital structure, re-evaluate position

---

## Weekly LME Review Template

### Portfolio Scan
```
Date: ___________
Reviewed by: ___________

1. PRICE MOVEMENTS
   Names with >3pt decline this week:
   - 
   - 

2. NEWS/HEADLINES
   LME-relevant headlines:
   - 
   - 

3. ADVISOR APPOINTMENTS
   New advisors engaged:
   - 

4. RATING ACTIONS
   Downgrades/Outlook changes:
   - 

5. TIER CHANGES
   Credits moving to higher tier:
   - 

6. ACTION ITEMS
   Required follow-ups:
   - 
```

---

## CDS Monitoring Integration

### Weekly CDS Check
For names with active CDS positions:

| Check | Source | Frequency |
|-------|--------|-----------|
| ISDA DC announcements | cdsdeterminationscommittees.org | Daily |
| CDS spread movements | Bloomberg/Markit | Daily |
| CDS-bond basis | Calculate | Weekly |
| Auction announcements | ISDA | As needed |
| Successor determinations | ISDA DC | As needed |

### CDS Trigger Scenarios by Name

**Very Group:**
- Status: RESTRUCTURING
- Trigger Risk: HIGH
- Watch: Failure to Pay, Restructuring
- Note: Carlyle exit process may not trigger if voluntary

**INEOS Quattro:**
- Status: STRESSED
- Trigger Risk: HIGH
- Watch: Restructuring if binding exchange
- Note: Separate reference entity from INEOS Group

**Merlin:**
- Status: STRESSED, "evaluating liquidity options"
- Trigger Risk: HIGH
- Watch: Any binding amendments
- Note: UK Scheme would likely trigger

---

## Escalation Protocol

### When to Escalate

**Immediate Escalation:**
- Restructuring advisor hired
- Bond drops >10pts in day
- Failure to Pay notice
- Scheme/Bankruptcy filing
- Exchange offer launched

**Same-Day Escalation:**
- Bonds cross below 80
- Rating downgrade to CCC
- "Evaluating liquidity options" language
- Ad hoc group announcement
- Intercompany asset transfer

**Next-Day Escalation:**
- Bonds cross below 90
- Rating downgrade with Negative outlook
- Revolver fully drawn
- Major asset sale announced


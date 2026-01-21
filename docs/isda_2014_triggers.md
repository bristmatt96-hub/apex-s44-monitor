# ISDA 2014 Credit Derivatives Definitions - Credit Event Reference

## Overview

The 2014 ISDA Credit Derivatives Definitions govern CDS contracts and determine when credit events trigger settlement. Understanding these definitions is critical when assessing LME implications for CDS positions.

**Note:** This is a summary reference. Always consult actual ISDA documentation and legal counsel for specific situations.

---

## Credit Event Types

### 1. Bankruptcy (Section 4.2)

**Trigger:** Reference Entity:
- Files for bankruptcy/insolvency proceedings
- Has involuntary petition filed against it (not dismissed within 30 days)
- Makes general assignment for benefit of creditors
- Has receiver/administrator appointed
- Is dissolved (other than pursuant to consolidation)

**LME Implications:**
- Formal bankruptcy filing = definite trigger
- Out-of-court restructuring = NO trigger (usually)
- Scheme of Arrangement = depends on jurisdiction/circumstances

**Key Point:** Most LMEs are designed to AVOID bankruptcy, so Bankruptcy Credit Event is typically NOT triggered by LME.

---

### 2. Failure to Pay (Section 4.5)

**Trigger:** Reference Entity fails to make payment when due:
- After expiration of any applicable Grace Period
- Of at least the Payment Requirement amount (typically USD 1m)

**Conditions:**
- Payment must be due and payable
- Grace Period must have expired
- Amount must meet threshold
- Must be on Borrowed Money (bonds, loans)

**LME Implications:**
- Missed interest/principal payment = trigger
- Payment made within Grace Period = NO trigger
- Exchange where old bonds remain = potential trigger if payment missed
- Selective default on one tranche = may trigger

**Grace Period Considerations:**
- Standard: 30 days for interest, none for principal
- Check specific bond indenture
- Grace Period Extension: If docs allow cure, extra time may apply

---

### 3. Restructuring (Section 4.7) - EUROPEAN CONTRACTS

**This is the KEY credit event for LME analysis in Europe.**

**Trigger (any of the following applied to Borrowed Money):**
1. **Reduction in interest rate or amount**
2. **Reduction in principal amount**
3. **Postponement/deferral of payment** (interest or principal)
4. **Change in ranking** (subordination)
5. **Change in currency** (to non-permitted currency)

**CRITICAL CONDITIONS:**
- Must result from **deterioration in creditworthiness or financial condition**
- Must **bind all holders** of the affected obligation
- Does NOT include changes that are:
  - Pursuant to original terms (e.g., PIK toggle, scheduled amortization)
  - Voluntary (freely offered exchange with full payment alternative)
  - Not binding on all holders

**LME Implications:**

| LME Type | Restructuring Credit Event? |
|----------|---------------------------|
| Exchange offer (voluntary) | Usually NO - not binding |
| Consent solicitation changing terms | Potentially YES if binding |
| Amendment reducing coupon | YES if binding and distressed |
| Maturity extension (binding) | YES if binding and distressed |
| Up-tier exchange | Complex - depends on mechanics |
| Drop-down | Usually NO - no change to bond terms |
| Asset sale to unrestricted sub | Usually NO |
| Scheme of Arrangement | Usually YES - binding on all |

**Multiple Holder Obligation:**
- Restructuring must apply to an obligation with multiple holders
- Bilateral loans may not qualify

---

### 4. Restructuring Sub-Types (European Contracts)

European CDS typically trades with one of these Restructuring definitions:

#### Mod-Mod-R (Modified Modified Restructuring)
- Most common in European HY CDS
- Restructuring is a Credit Event
- Deliverable obligations limited to 60 months (5 years) for restructured bonds, 30 months for others
- Protects seller from long-dated delivery

#### Mod-R (Modified Restructuring)
- Less common
- Different maturity limitations
- Used in some legacy contracts

#### Full Restructuring (CR)
- No maturity limitation on deliverables
- Rarely used in European HY

**Know your contract type** - it affects settlement options.

---

### 5. Repudiation/Moratorium (Section 4.6)

**Trigger:** Reference Entity or Governmental Authority:
- Repudiates or rejects the obligation
- Declares moratorium on payments
- AND a Failure to Pay or Restructuring follows

**LME Implications:**
- Rare in corporate LMEs
- More relevant for sovereign situations
- "We won't pay" announcements matter

---

### 6. Obligation Acceleration (Section 4.3) - Typically NOT in European HY

**Trigger:** One or more obligations become due and payable prior to maturity due to default.

**Note:** Usually NOT included in standard European HY CDS. Check your confirmation.

---

### 7. Obligation Default (Section 4.4) - Typically NOT in European HY

**Trigger:** One or more obligations become capable of being declared due and payable (cross-default).

**Note:** Usually NOT included in standard European HY CDS.

---

## Determining the Reference Entity

### Successor Provisions (Section 2.2)

When a Reference Entity undergoes corporate changes:

**Universal Successor:** Entity that assumes 75%+ of relevant obligations
**Multiple Successors:** If obligations split, CDS may split

**LME Implications:**
- Corporate reorganization may change Reference Entity
- Spin-offs/splits require analysis
- Successor determination by DC (Determinations Committee)

---

## Deliverable Obligations (Settlement)

If Credit Event triggered, CDS settlement requires delivery of qualifying obligations:

**Standard Deliverable Obligation Characteristics:**
- Not Bearer
- Transferable
- Not contingent
- Assignable Loan (if loan)
- Maximum Maturity: 30 years (subject to Restructuring limits)
- Not domestic currency (if specified)

**LME Implications:**
- New debt from exchange may or may not be deliverable
- Check if obligations remain "Borrowed Money"
- Subordinated debt may not qualify if senior specified

---

## ISDA Determinations Committee (DC)

The DC decides:
1. Whether Credit Event occurred
2. Successor determinations
3. Auction terms

**Process:**
1. Question submitted to DC
2. DC deliberates (usually within days)
3. Decision published
4. Auction held (if Credit Event confirmed)

**Monitoring:** Watch ISDA DC announcements for names in your portfolio at [https://www.cdsdeterminationscommittees.org/](https://www.cdsdeterminationscommittees.org/)

---

## LME Scenario Analysis

### Scenario 1: Voluntary Exchange Offer

**Situation:** Company offers bondholders exchange of old bonds for new bonds with lower face value.

**Credit Event?** Generally NO
- Voluntary = no binding change
- Holders can choose to keep old bonds
- No Failure to Pay if old bonds continue paying

**But watch for:**
- Exit consents stripping protections from old bonds
- Coercive features making it "binding in practice"
- Failure to pay on old bonds after exchange

---

### Scenario 2: Consent Solicitation Changing Terms

**Situation:** Company solicits consent to amend bond terms (reduce coupon, extend maturity).

**Credit Event?** Potentially YES
- If amendment passes and is binding on all holders
- AND results from credit deterioration
- Could trigger Restructuring Credit Event

---

### Scenario 3: UK Scheme of Arrangement

**Situation:** Company uses UK Scheme to restructure bonds.

**Credit Event?** Usually YES
- Scheme binds all holders (including dissenters)
- Typically involves payment reduction/deferral
- Clear Restructuring Credit Event in most cases

---

### Scenario 4: Up-Tier Exchange (Serta-style)

**Situation:** Some lenders exchange into super-priority debt, others left behind.

**Credit Event?** Complex
- Original debt terms may not change
- Subordination is effective, not legal
- May NOT trigger Restructuring if original terms unchanged
- Possible DC referral needed

---

### Scenario 5: Drop-Down (J.Crew-style)

**Situation:** Assets moved to unrestricted sub, new debt issued there.

**Credit Event?** Usually NO
- Bond terms don't change
- No payment missed
- Recovery may be impaired but no Credit Event

**Key Point:** Drop-downs can devastate recovery WITHOUT triggering CDS.

---

## Quick Reference: Credit Event Triggers

| Event | Bankruptcy | Failure to Pay | Restructuring |
|-------|-----------|----------------|---------------|
| Chapter 11 filing | YES | - | - |
| Missed coupon (after grace) | - | YES | - |
| Exchange offer (voluntary) | - | - | Usually NO |
| Binding amendment to terms | - | - | Likely YES |
| Scheme of Arrangement | - | - | Usually YES |
| Up-tier exchange | - | - | Complex |
| Drop-down | - | - | NO |
| Asset sale | - | - | NO |
| Dividend recap | - | - | NO |

---

## Monitoring Checklist for CDS Positions

- [ ] Confirm CDS contract terms (Mod-Mod-R typical for European HY)
- [ ] Monitor DC announcements
- [ ] Track Reference Entity changes
- [ ] Assess LME announcements for Credit Event potential
- [ ] Note Grace Periods for Failure to Pay
- [ ] Check if proposed changes are binding vs voluntary
- [ ] Evaluate recovery impact even if no Credit Event

---

## Important Disclaimer

This document is a summary reference for monitoring purposes only. It does not constitute legal advice. ISDA definitions are complex and fact-specific interpretations require legal counsel. Always consult:
- Actual CDS confirmations
- ISDA Master Agreement
- Legal counsel specializing in derivatives
- ISDA DC determinations


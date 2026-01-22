# Credit Snapshot Schema

## Documentation Risk Section

Add this section to each credit snapshot to track LME risk:

```json
"documentation_risk": {
  "doc_vintage": "2021",
  "governing_law": "New York",
  "covenant_quality": "WEAK|MEDIUM|STRONG",
  "lme_risk_score": "LOW|MEDIUM|HIGH|CRITICAL",
  
  "key_provisions": {
    "j_crew_blocker": false,
    "anti_serta_provisions": false,
    "unrestricted_sub_capacity": "UNLIMITED|CAPPED|RESTRICTED",
    "permitted_investment_basket": "$XXm or X% of assets",
    "restricted_payment_capacity": "$XXm",
    "grower_baskets": true,
    "asset_sale_covenant": "LOOSE|MODERATE|TIGHT",
    "amendment_threshold_liens": "50%|66.7%|100%",
    "open_market_purchase": true,
    "maintenance_covenants": false
  },
  
  "lme_risk_flags": [
    "Unrestricted subsidiary designation permitted",
    "No J.Crew blocker on IP",
    "Low amendment threshold for lien priority",
    "Large permitted investment basket",
    "Grower baskets uncapped"
  ],
  
  "structural_position": {
    "entity_type": "HOLDCO|OPCO",
    "guarantor_coverage": "95%|<80%",
    "structural_subordination_risk": "LOW|MEDIUM|HIGH"
  },
  
  "cds_considerations": {
    "reference_entity": "Company Name",
    "restructuring_type": "Mod-Mod-R",
    "credit_event_risk": "LOW|MEDIUM|HIGH",
    "note": "Any specific CDS considerations"
  },
  
  "sponsor_behavior": {
    "recent_dividends": true,
    "dividend_history": "3 dividend recaps since LBO",
    "asset_sales_to_affiliates": false,
    "note": "Sponsor has history of aggressive capital returns"
  },
  
  "monitoring_triggers": [
    "Watch for unrestricted subsidiary designation",
    "Monitor intercompany transactions",
    "Track advisor appointments"
  ]
}
```

## LME Risk Score Definitions

| Score | Criteria |
|-------|----------|
| **LOW** | Strong docs (2023+), J.Crew/Serta blockers, tight covenants, IG or near-IG |
| **MEDIUM** | Standard HY docs, some protections, moderate leverage, no immediate concerns |
| **HIGH** | ZIRP-era docs, weak covenants, high leverage, sponsor-owned, distress indicators |
| **CRITICAL** | Active LME indicators, advisors hired, bonds <80, documented loopholes identified |

## Quick Assessment Questions

When reviewing documentation, answer these:

1. **Can assets be moved out?**
   - Unrestricted sub designation?
   - Permitted investment capacity?
   - J.Crew blocker?

2. **Can you be primed?**
   - Amendment threshold for liens?
   - Anti-Serta provisions?
   - Permitted debt baskets?

3. **Are you structurally junior?**
   - Holdco vs opco?
   - Guarantor coverage?
   - Intercompany loan restrictions?

4. **What's the sponsor history?**
   - Dividend recaps?
   - Asset sales?
   - Aggressive value extraction?

5. **Will CDS protect you?**
   - Credit Event triggers?
   - Voluntary vs binding transactions?
   - Reference Entity considerations?

## Integration with Existing Snapshots

For credits already in portfolio, add documentation_risk section when:
1. Distress score > 20
2. Bonds trading < 90
3. PE-backed with leverage > 5x
4. Complex multi-entity structure
5. ZIRP-era documentation

Priority credits for documentation review:
- INEOS Group (distress 44)
- INEOS Quattro (distress 87, STRESSED)
- Merlin Entertainment (distress 53)
- Stonegate (distress 20)
- CABB (distress 15, PE-backed)

## Headline Monitoring Integration

When these headlines appear, immediately check documentation:

| Headline | Check |
|----------|-------|
| "[Company] hires [advisor]" | LME provisions, unrestricted subs |
| "Ad hoc group forms" | Amendment thresholds, coordination |
| "Exchange offer" | Voluntary vs binding, CDS trigger |
| "Asset sale to affiliate" | J.Crew blocker, permitted investments |
| "Designates unrestricted subsidiary" | IP protection, value leakage |
| "Intercompany reorganization" | Structural subordination, guarantees |


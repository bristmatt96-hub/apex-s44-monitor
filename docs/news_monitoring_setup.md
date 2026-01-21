# News Monitoring Setup

## Goal
Be first to see relevant news and understand implications before the market moves.

---

## Alert Configuration

### Tier 1 Credits (Immediate Alert - Any News)

**Keywords to monitor:**
```
"Very Group" OR "Summer BC" OR "Carlyle Very"
"INEOS Quattro" OR "Quattro Holdings"
"Merlin Entertainment" OR "Motion Bondco" OR "Blackstone Merlin"
```

**Alert channels:** Push notification, SMS, email

### Tier 2 Credits (High Priority)

**Keywords:**
```
"INEOS Group" OR "INEOS Holdings" OR "Jim Ratcliffe INEOS"
"Stonegate Pub" OR "TDR Stonegate"
```

**Alert channels:** Push notification, email

### Tier 3 Credits (Standard Priority)

**Keywords:**
```
"CABB chemicals" OR "Permira CABB" OR "Monitchem"
"Aggreko" OR "Albion Financing"
```

**Alert channels:** Email digest

---

## Universal Keywords (All Credits)

### Restructuring Alerts
```
[Company] + "restructuring"
[Company] + "liability management"
[Company] + "exchange offer"
[Company] + "consent solicitation"
[Company] + "scheme of arrangement"
[Company] + "WHOA"
[Company] + "Chapter 11"
```

### Advisor Alerts
```
[Company] + "Houlihan Lokey"
[Company] + "Evercore"
[Company] + "PJT Partners"
[Company] + "Lazard restructuring"
[Company] + "Rothschild"
[Company] + "Kirkland Ellis"
[Company] + "Weil Gotshal"
```

### Distress Signals
```
[Company] + "liquidity"
[Company] + "strategic alternatives"
[Company] + "covenant waiver"
[Company] + "covenant breach"
[Company] + "going concern"
[Company] + "material uncertainty"
```

### Rating Alerts
```
[Company] + "Moody's" + "downgrade"
[Company] + "S&P" + "downgrade"  
[Company] + "Fitch" + "downgrade"
[Company] + "outlook negative"
[Company] + "CCC"
```

### Corporate Actions
```
[Company] + "dividend"
[Company] + "asset sale"
[Company] + "acquisition"
[Company] + "disposal"
[Sponsor] + "exit"
[Sponsor] + "sale process"
```

---

## Source Configuration

### Real-Time (Seconds)
| Source | Setup | Cost |
|--------|-------|------|
| Bloomberg Terminal | NEWS alerts | $$$ |
| Refinitiv Eikon | News alerts | $$$ |
| Twitter/X | Follow company, advisors | Free |
| Company IR | RSS/email signup | Free |

### Fast (Minutes)
| Source | Setup | Cost |
|--------|-------|------|
| Debtwire | Email alerts | $$ |
| 9fin | App notifications | $$ |
| LCD/Pitchbook | Alerts | $$ |
| Rating agency feeds | Direct subscription | $ |

### Standard (Hours)
| Source | Setup | Cost |
|--------|-------|------|
| Google Alerts | Keyword setup | Free |
| Feedly | RSS aggregation | Free/$ |
| Industry newsletters | Email signup | Varies |

---

## Alert Processing Workflow

```
NEWS HITS
    ↓
[30 sec] Classify: Positive/Negative/Neutral?
    ↓
[30 sec] Is this priced? Check current levels
    ↓
[60 sec] Consult Cheat Sheet for this credit
    ↓
[60 sec] Determine price impact estimate
    ↓
[60 sec] Check execution (liquidity, bid/ask)
    ↓
[DECISION] Trade / Wait / Pass
```

---

## Pre-Market Routine (15 min)

### Daily Checklist
```
□ Check overnight news (Asia, early Europe)
□ Review Tier 1 credit prices (any moves >1pt?)
□ Scan Debtwire/9fin headlines
□ Check ISDA DC for any announcements
□ Review calendar (earnings, maturities, events)
□ Note any unusual volume from prior day
```

### Weekly Addition (Monday)
```
□ Rating agency calendar for week
□ Earnings calendar for portfolio names
□ Court calendars (UK, Netherlands, US)
□ Index rebalancing dates
□ CDS roll dates
```

---

## Event Calendar Integration

### Earnings Dates
Track and set alerts for:
- 1 week before (position review)
- Day before (reminder)
- Release time (be ready)

### Maturity Dates
Track and alert:
- 12 months before (refinancing watch)
- 6 months before (pressure building)
- 3 months before (critical)
- 1 month before (execution risk)

### Rating Review Dates
Alert when:
- Review announced
- Review date approaching
- 90 days post negative outlook (action due)

---

## Information Edge Tactics

### 1. Source Triangulation
Don't rely on single source. Cross-reference:
- News wires
- Bond price moves
- CDS moves
- Social media chatter
- Court filings

### 2. Leading Indicators
Watch these BEFORE news:
- Unusual bond volume
- CDS spread moves
- Stock moves (if public)
- Credit facility draws
- Advisor firm activity

### 3. Network Intelligence
Build relationships with:
- Buyside peers (careful on MNPI)
- Sellside analysts
- Restructuring advisors
- Legal counsel
- Company IR (for public info)

### 4. Filing Monitoring
Set up for:
- UK Companies House (free)
- SEC EDGAR (US exposure)
- Court filings (PACER, UK courts)
- Dutch KvK
- Luxembourg RCS

---

## Speed Practice

### Drill: Headline Response
Practice rapid assessment:
1. Read headline
2. Start timer
3. Classify, quantify, decide
4. Stop timer
Target: <3 minutes to decision

### Drill: Cheat Sheet Recall
Test yourself:
1. Name a credit
2. Without looking, list top 3 price drivers
3. Check against cheat sheet
Goal: Instant recall for Tier 1/2 names

---

## Tech Stack Recommendations

### Essential
- Bloomberg/Eikon terminal (if available)
- Debtwire subscription
- Mobile alerts configured
- Spreadsheet with current prices

### Helpful
- 9fin app
- Custom RSS aggregator
- Position tracking system
- Alert logging system

### Advanced
- API feeds for prices
- Automated alert parsing
- News sentiment analysis
- Price alert bots


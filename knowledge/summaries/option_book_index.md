# Option Book Summaries — Master Index

**Source**: Sheldon Natenberg, *Option Volatility and Pricing* (2nd Edition)
**Purpose**: Structured summaries mapping options theory to our CDS-Equity Options Bridge strategy

---

## Part I: Fundamentals (Chapters 1-6)

| Chapter | Topic | Summary |
|---------|-------|---------|
| [Ch 1](option_book_ch01.md) | The Language of Options | Calls, puts, exercise styles, intrinsic/time value, parity graphs |
| [Ch 2](option_book_ch02.md) | Elementary Strategies | Basic long/short positions, spreads as building blocks, P&L profiles |
| [Ch 3](option_book_ch03.md) | Theoretical Pricing Models | Black-Scholes, probability distributions, theoretical edge vs. luck |
| [Ch 4](option_book_ch04.md) | Volatility | Historical vs. implied vol, lognormal distribution, vol as standard deviation |
| [Ch 5](option_book_ch05.md) | Using Theoretical Value | Dynamic hedging, replication, capturing theoretical edge through adjustments |
| [Ch 6](option_book_ch06.md) | The Greeks | Delta, gamma, theta, vega, rho — sensitivities that drive position management |

## Part II: Spreading (Chapters 7-12)

| Chapter | Topic | Summary |
|---------|-------|---------|
| [Ch 7](option_book_ch07.md) | Introduction to Spreading | Why spreads exist, spread types, risk reduction through offsetting positions |
| [Ch 8](option_book_ch08.md) | Volatility Spreads | Straddles, strangles, butterflies, time spreads — trading vol directly |
| [Ch 9](option_book_ch09.md) | Risk Considerations | Greeks at portfolio level, scenario analysis, position limits |
| [Ch 10](option_book_ch10.md) | Bull and Bear Spreads | Vertical spreads, directional strategies, combining direction with vol view |
| [Ch 11](option_book_ch11.md) | Option Arbitrage | Put-call parity, conversions, reversals, boxes, jelly rolls |
| [Ch 12](option_book_ch12.md) | Early Exercise of American Options | Dividend-driven exercise, interest rate effects, exercise boundaries |

## Part III: Applied Theory (Chapters 13-18)

| Chapter | Topic | Summary |
|---------|-------|---------|
| [Ch 13](option_book_ch13.md) | Hedging with Options | Protective puts/calls, covered writes, fences, portfolio insurance, IV regime rules |
| [Ch 14](option_book_ch14.md) | Volatility Revisited | Vol forecasting, mean reversion, GARCH, volatility cones, term structure |
| [Ch 15](option_book_ch15.md) | Stock Index Futures and Options | Index construction, index arbitrage, cash settlement, tracking error |
| [Ch 16](option_book_ch16.md) | Intermarket Spreading | Cross-market spreads, correlation, percentage vs. point matching |
| [Ch 17](option_book_ch17.md) | Position Analysis | Graphical analysis, risk curves, complex position decomposition |
| [Ch 18](option_book_ch18.md) | Models and the Real World | Model assumptions vs. reality, fat tails, skew, jump risk, expiration straddles |

## Appendices

| Appendix | Topic | Summary |
|----------|-------|---------|
| [Appendix A](option_book_appendix_glossary.md) | Glossary of Option Terminology | Complete glossary with credit-equity bridge context |
| [Appendices C-E](option_book_appendices_cde.md) | Vol Spread Characteristics, Strategy Selection, Synthetics | Greeks table for all spread types, direction x IV strategy matrix, put-call parity |

---

## Quick Reference: Credit-Equity Bridge Strategy Mapping

### When to use which chapter:

| Strategy Decision | Relevant Chapters |
|---|---|
| **Gap score interpretation** | Ch 4 (vol basics), Ch 14 (vol forecasting), Ch 18 (fat tails) |
| **IV percentile thresholds** | Ch 4, Ch 8 (vol spreads), Ch 14 (vol cones), App D (strategy matrix) |
| **Put structure selection** | Ch 2 (elementary), Ch 10 (verticals), Ch 13 (hedging), App D |
| **Strike selection** | Ch 6 (delta/gamma), Ch 18 (skew, ln(E/U)/sqrt(t) normalisation) |
| **Expiry selection** | Ch 8 (time spreads), Ch 14 (term structure), Ch 12 (early exercise) |
| **Position sizing** | Ch 6 (Greeks), Ch 9 (risk), Ch 13 (delta-based hedge sizing) |
| **Risk management** | Ch 5 (hedging), Ch 9 (portfolio risk), Ch 18 (gap risk, model limits) |
| **Synthetic alternatives** | Ch 11 (arbitrage), App E (synthetics), Ch 15 (index substitutes) |

### Core Insight
The entire Natenberg framework supports our thesis: **buy puts when credit signals (CDS widening, filing alerts, maturity walls) indicate stress BEFORE equity volatility reprices**. The gap score captures the divergence between credit-implied risk and equity-implied risk. Chapters 4, 14, and 18 provide the theoretical foundation; Chapters 8, 10, and 13 provide the structural toolkit; Appendix D provides the decision matrix.

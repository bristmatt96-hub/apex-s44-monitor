# Chapter 16: Intermarket Spreading

## Key Concepts
- **Intermarket spread fundamentals**: Spreading one instrument against another in a different market. Requires identifying a relationship between two contracts and exploiting mispricings between them
- **Point vs. percent matching**: A spread can be balanced in point terms (equal notional on each side) or percent terms (equal dollar value at risk). For contracts at different prices, you need more contracts of the lower-priced instrument to equalise dollar exposure
- **Dollar delta ($delta)**: The dollar value change for a 1% change in the underlying price. $delta = (contract price × point value) / 100. This normalises delta across instruments trading at different prices with different point values
- **$delta neutral spreads**: To create a balanced intermarket spread, ensure that $delta exposure on both sides is equal. This means the dollar at risk on each side of the spread is matched
- **Volatility relationships between markets**: Closely related markets (e.g., OEX vs. NYA, heating oil vs. crude oil) tend to have well-defined volatility ratios. If NYA volatility is typically 87% of OEX volatility, this ratio can be exploited
- **Intermarket volatility spreads**: Buy straddles in the relatively cheap (low IV) market, sell straddles in the relatively expensive (high IV) market. If the volatility relationship holds, profit is equal to the IV differential
- **$gamma, $theta, $vega**: Dollar-normalised versions of the Greeks for cross-market comparison. Adjusted by the volatility ratio to reflect the true risk when markets move at different rates
- **Crack spreads**: In energy markets, the spread between crude oil and its refined products (gasoline, heating oil). A 3:2:1 crack spread reflects the typical refinery output ratio

## Trading Rules & Practical Takeaways
- **Equalise dollar values, not contract counts**: When spreading two instruments, ensure (contracts × price × point value) is equal on both sides. Simply buying one and selling one of equal-priced contracts is usually wrong
- **Volatility ratio is key to intermarket vol spreads**: The individual volatilities don't matter as much as their ratio. If XYZ is always 25% more volatile than ABC, the spread ratio is the same regardless of actual vol levels
- **ATM options simplify intermarket spreads**: Using at-the-money options (delta ≈ 50) avoids the need to know exact volatility for delta calculation. This is valuable when you're trading the relative vol relationship, not absolute levels
- **Adjust ratios for volatility differences**: When balancing an intermarket vol spread, multiply each side by its volatility. The formula: ABC contracts × $delta × ABC delta × ABC vol = XYZ contracts × $delta × XYZ delta × XYZ vol
- **Watch for regime changes in vol relationships**: While some market pairs maintain stable vol ratios (stock indexes), others can shift dramatically (commodities during supply shocks). The spread is at risk if the vol relationship changes

## Application to Credit-Equity Bridge Strategy
- **CDS-equity spread IS an intermarket spread**: Our entire strategy is fundamentally an intermarket spread — we observe signals in the credit market (CDS) and trade options in the equity market. Chapter 16 provides the theoretical framework for what we're doing
- **$delta concept applies to cross-asset signals**: When a CDS spread widens by X basis points, we need to estimate the equivalent equity move. The gap score is essentially measuring the $delta imbalance between credit and equity markets — how much credit has moved relative to equity
- **Volatility relationship between credit and equity**: Just as NYA vol is ~87% of OEX vol, there's a relationship between CDS-implied equity vol and actual equity IV. When this ratio diverges (credit implies higher vol than equity options reflect), that's our trading signal
- **Normalisation across our universe**: With 44 names at different prices, currencies, and volatilities, the $delta/$gamma/$vega framework is exactly what we need to compare opportunities. A Nokia put at €6.42 and a Volkswagen put at €90+ are not comparable in raw terms — they need dollar-normalisation
- **Options on spreads**: The chapter mentions options whose payoff depends on a spread between two markets. Conceptually, our strategy payoff depends on the CDS-equity spread converging. If such cross-market options existed (credit-contingent equity puts), they would be the perfect instrument for our strategy

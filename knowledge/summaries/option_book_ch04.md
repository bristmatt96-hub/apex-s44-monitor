# Chapter 4: Volatility

## Key Concepts
- **Volatility = speed of the market**: Low-vol markets have tight price distributions (high, narrow bell curves); high-vol markets have wide distributions (low, fat bell curves). Options are more valuable in high-vol markets
- **Normal distribution / random walk**: Pricing models assume prices follow a random walk — each day's move is independent. The resulting price distribution after many days approximates a normal (bell-shaped) curve
- **Mean and standard deviation**: A normal distribution is fully described by two numbers — the mean (peak location) and standard deviation (how fast the curve spreads). For options, what matters is the standard deviation (volatility), not the mean
- **One standard deviation captures ~68% of outcomes**: Roughly 68% of outcomes fall within 1 SD of the mean, 95% within 2 SD, and 99.7% within 3 SD. This gives traders probability-based strike selection
- **Annualised volatility**: Volatility is expressed as an annualised percentage. To convert to a daily move: daily vol = annual vol / sqrt(252). A stock with 30% annual vol moves about 1.9% per day (one SD)
- **Volatility is direction-neutral**: High volatility increases BOTH call and put values because it increases the probability of finishing in-the-money, regardless of direction. The asymmetric payoff of options means only one tail matters
- **Historical vs implied volatility**: Historical vol measures past price movement; implied vol is what the market is currently pricing into options. The difference between them is where trading opportunities arise

## Trading Rules & Practical Takeaways
- **Use standard deviations for strike selection**: If annual vol is 30% and you have 3 months, expected 1-SD move = 30% x sqrt(0.25) = 15%. An 85% strike put is ~1 SD OTM — roughly 16% probability of finishing ITM
- **Low vol = cheap options = opportunity**: When implied vol is low relative to historical vol or expected future vol, options are cheap. This is the ideal time to buy puts
- **High vol = expensive options = use spreads**: When implied vol is high, outright put purchases are expensive. Use put spreads or calendar spreads to reduce vega exposure
- **Vol of vol matters**: Volatility itself is volatile — it can spike suddenly (credit events, earnings) or compress slowly (complacency). Fat tails in the vol distribution create opportunities

## Application to Credit-Equity Bridge Strategy
- **IV percentile is the key decision variable**: Our trade_structurer uses IV percentile to switch between structures. This chapter explains WHY: low IV percentile means the distribution is priced too narrow — if credit signals suggest a wider distribution ahead, puts are cheap
- **Strike selection via standard deviations**: For a maturity_wall catalyst with 6-month puts, 80% strike on a 30%-vol stock is roughly 1.3 SD OTM. If credit stress suggests 2+ SD moves are coming, this gives excellent risk/reward
- **The credit signal IS a volatility forecast**: When CDS widens sharply but equity IV stays low, the credit market is forecasting higher future volatility that equity options haven't priced. The gap score quantifies this disconnect
- **Sector volatility clustering**: The chapter's discussion of different markets having inherent volatility levels maps to our sector spread heuristics — Energy names (inherently higher vol) vs TMT names (potentially lower vol) need different strike selections

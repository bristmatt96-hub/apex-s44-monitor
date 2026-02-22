# Chapter 7: Introduction to Spreading

## Key Concepts
- **Spreading = risk management**: Spreads enable traders to exploit mispriced options while reducing exposure to adverse changes in market conditions (direction, vol, time). Most successful option traders are spread traders, not naked option buyers/sellers
- **Price relationship trading**: A spread assumes a quantifiable relationship between instruments. The trader profits when prices revert to their expected relationship, regardless of market direction
- **Volatility spreads vs directional spreads**: Volatility spreads (delta neutral) profit from vol being mispriced; directional spreads profit from underlying price movement. The chapter focuses on volatility spreads
- **Spread categories**: Backspreads (long more options than short, positive gamma/vega), ratio vertical spreads (short more than long, negative gamma/vega), straddles/strangles, butterflies/condors, time spreads (calendar spreads)
- **Why spreads work**: Over short periods, individual option mispricings may not converge to theoretical value. Spreads hedge against short-term adverse moves, allowing the trader to hold until the law of large numbers works

## Trading Rules & Practical Takeaways
- **Never hold naked long options hoping to profit**: The odds are against you (must be right on direction AND speed). Spread against another option to isolate the mispricing
- **Match spread type to market view**: If you think vol is too low → use positive vega spreads (backspreads, long straddles, long time spreads). If vol is too high → use negative vega spreads (ratio verticals, short straddles, butterflies)
- **Spread reduces but doesn't eliminate risk**: Every spread has risk characteristics (gamma, theta, vega). Understand the Greek profile before entering
- **Liquidity matters for spreading**: You need to be able to enter and exit both legs. Illiquid markets make spreads impractical

## Application to Credit-Equity Bridge Strategy
- **Our strategy IS a directional spread at heart**: We buy puts (bearish directional view from credit signal) and often sell lower-strike puts (put spread) to manage cost. This chapter validates the approach — naked put buying is suboptimal; put spreads improve the risk/reward
- **Calendar put spreads for uncertain timing**: When the credit catalyst has an uncertain timeline (e.g., maturity wall in 6-12 months), selling near-dated puts and buying far-dated puts (calendar spread) monetises theta while maintaining long-term bearish exposure
- **Butterflies for range-bound views**: If credit signals suggest moderate stress (gap_score 30-50, MODERATE) rather than collapse, a put butterfly can profit from the stock settling in a lower range without needing a crash
- **Spread selection maps to our trade_structurer**: OTM_PUT = naked directional; ATM_PUT_SPREAD = bull put inversion (bearish debit spread); CALENDAR_PUT = time spread; STRADDLE = long straddle for binary events. The chapter provides the theoretical justification for each

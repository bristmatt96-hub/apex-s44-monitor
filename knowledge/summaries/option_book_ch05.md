# Chapter 5: Using an Option's Theoretical Value

## Key Concepts
- **Delta-neutral hedging**: To profit from mispriced options, establish a hedge using the delta ratio. Buy underpriced options and sell delta-equivalent units of the underlying (or vice versa). The hedge must be dynamically adjusted
- **Delta**: The rate of change of option value with respect to the underlying price. Calls have delta 0-100; puts have delta 0 to -100. ATM options have delta ~50
- **Dynamic rebalancing**: As the underlying moves, delta changes, so the hedge ratio must be adjusted. This continual rebalancing is how the theoretical edge is captured over time
- **Positive edge requires many trades**: Like a casino, edge is only realised over many trades. Any single trade may lose. The discipline is to consistently trade with positive expected value
- **Theoretical value assumes you can hedge**: An option's theoretical value is only meaningful if you can actually hedge. Illiquid underlyings or inability to short-sell undermines the model
- **Transaction costs eat into edge**: Frequent rebalancing incurs commissions and bid-ask spreads. The edge must exceed total transaction costs for the strategy to be profitable

## Trading Rules & Practical Takeaways
- **Only buy options when they're cheap relative to your volatility forecast**: The purchase is justified when the implied vol (market price) is below your expected realised vol
- **Hedge or accept directional risk**: Without hedging, you're speculating on direction AND volatility. Delta-neutral positions isolate the volatility bet
- **The more you rebalance, the closer to theoretical profit**: In theory, continuous rebalancing captures the full edge. In practice, daily rebalancing is a reasonable compromise
- **Size positions to survive variance**: Even with edge, short-term P&L can be highly variable. Position sizing must account for the distribution of outcomes, not just expected value

## Application to Credit-Equity Bridge Strategy
- **We are NOT delta-neutral**: Our strategy is directional — we buy puts expecting the equity to fall. We accept directional risk because our credit signal gives us an informational edge on direction. This is a deliberate departure from the textbook approach
- **But delta awareness still matters**: Knowing the delta of our puts tells us the effective short position size. A 100-lot of 25-delta puts gives us exposure equivalent to shorting 2,500 shares
- **Implied vol = the market's volatility forecast**: When we buy puts at low IV percentile, we're disagreeing with the market's vol forecast. The credit signal is our basis for this disagreement
- **Transaction cost awareness**: European single-stock options often have wide bid-ask spreads. Our max_premium_pct constraint in the trade_structurer accounts for this — we won't pay more than 3-5% of notional regardless of theoretical attractiveness
- **Hedging via put spreads**: Selling a lower-strike put to partially finance our long put is a form of hedging — we give up some of the extreme downside profit to reduce cost and vega exposure

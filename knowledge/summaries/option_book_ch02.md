# Chapter 2: Elementary Strategies

## Key Concepts
- **Profit/loss at expiration**: At expiry, an option is worth either zero (OTM) or intrinsic value (ITM). Profit = intrinsic value minus premium paid
- **Four basic positions**: Long call (bullish, limited risk), short call (bearish, unlimited risk), long put (bearish, limited risk), short put (bullish, limited risk)
- **Breakeven points**: For long calls: strike + premium. For long puts: strike - premium
- **Risk/reward asymmetry**: Long options have limited risk (premium paid) and theoretically unlimited profit. Short options have limited profit (premium collected) and potentially unlimited risk
- **Spread strategies**: Bull/bear spreads, straddles, strangles, butterflies, and condors are combinations of basic positions that shape the risk/reward profile
- **Synthetic positions**: Combinations of options and underlying that replicate other instruments (e.g., long call + short put = synthetic long underlying)
- **Parity relationships**: Put-call parity links calls, puts, and the underlying: C - P = S - K (simplified). Violations create arbitrage opportunities

## Trading Rules & Practical Takeaways
- **Long put = defined-risk bearish bet**: Maximum loss is the premium paid — ideal when conviction is high but timing uncertain
- **Put spreads reduce cost**: Buying a higher-strike put and selling a lower-strike put caps profit but significantly reduces premium outlay
- **Straddles for binary events**: Buying both a call and put at the same strike profits from large moves in either direction — useful for restructuring/M&A situations
- **Strike selection determines risk profile**: OTM puts are cheaper but need larger moves to profit; ATM puts are more expensive but have higher probability of profit
- **Ratio spreads for skewed views**: Buying 1 ATM put and selling 2 OTM puts creates a position that profits from moderate declines but has downside risk below the lower strike

## Application to Credit-Equity Bridge Strategy
- **OTM puts for maturity_wall catalyst**: Chapter confirms cheapest structure for directional bear bets. Our trade_structurer correctly uses OTM puts (80% strike, 6-month) when IV percentile < 25
- **Put spreads for earnings_downgrade**: When IV is elevated (>40th percentile), the chapter supports using put spreads to reduce vega exposure — aligns with our ATM_PUT_SPREAD recommendation
- **Straddles for aggressive_sponsor**: Binary outcomes (take-private, dividend recap, or recovery) make straddles appropriate — confirms our STRADDLE recommendation for this catalyst when IV < 30
- **Synthetic understanding**: If we ever need to replicate a put synthetically (short stock + long call), this framework applies — relevant for illiquid European option markets
- **Breakeven awareness**: For every trade recommendation, the breakeven calculation tells us the minimum equity move needed. A 3-month 90% put at 3% premium needs a 13% decline to profit — this must be calibrated against typical credit-to-equity lag timings

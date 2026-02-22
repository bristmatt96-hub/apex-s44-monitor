# Chapter 14: Volatility Revisited

## Key Concepts
- **Historical volatility calculation methods**: Multiple approaches exist — close-to-close, high-low-close (Parkinson), OHLC (Garman-Klass). High-low methods capture more information per trading day and can produce better estimates with fewer data points
- **Volatility mean reversion**: Volatility tends to revert to a long-term mean. When current vol is unusually high, it tends to decline; when unusually low, it tends to rise. This is the fundamental basis for vol trading
- **Implied vs. historical volatility**: IV reflects the market's forward-looking estimate of future realised volatility. Historical vol tells you what happened; IV tells you what the market expects. The gap between them creates trading opportunities
- **Volatility forecasting**: The best predictor of future volatility is often a weighted combination of recent historical vol, long-term average vol, and current implied vol. Simple moving averages of historical vol are commonly used
- **GARCH models**: Generalised Autoregressive Conditional Heteroskedasticity models capture volatility clustering — the tendency for large moves to follow large moves and small moves to follow small moves
- **Volatility cones**: Plot historical volatility over different lookback periods to create a "cone" showing the range of volatilities observed. Useful for determining whether current IV is relatively high or low for the given time horizon
- **Term structure of volatility**: IV varies by expiration. Short-term options often have higher IV than long-term options in high-vol environments (inverted term structure) and lower IV in low-vol environments (normal term structure)

## Trading Rules & Practical Takeaways
- **Use volatility cones for regime detection**: Compare current IV percentile against the historical range for that specific tenor. An option might look cheap vs. 30-day historical vol but expensive vs. 90-day
- **Mean reversion trading**: When IV is at extreme percentiles, bet on reversion. Buy vol when IV is at historically low levels; sell vol when at historically high levels. But be aware that vol can stay extreme longer than expected
- **Volatility clustering**: After a quiet period, expect continued quiet. After a volatile period, expect continued volatility. This has implications for position sizing and timing
- **Historical vol lookback period matters**: 10-day HV captures recent moves but is noisy. 30-60 day HV is more stable. Use multiple lookback periods to get a fuller picture
- **Don't confuse cheap with good**: Low IV doesn't automatically mean options are cheap. If realised vol is even lower, the options are still expensive relative to what will actually happen

## Application to Credit-Equity Bridge Strategy
- **Volatility cones are our IV percentile system**: Our trade_structurer uses IV percentile thresholds (25th, 50th, 75th) to determine structure selection. This chapter provides the theoretical foundation — we're essentially using a simplified volatility cone approach
- **Mean reversion + credit signals = powerful combo**: When CDS spread widens (credit stress signal) AND IV percentile is low, we have the ideal setup. Vol is likely to increase (mean reversion from low levels + fundamental catalyst from credit deterioration). This is when straight put purchases are optimal
- **Volatility clustering informs timing**: If a name has been quiet for months (low HV clustering), a credit signal breaking through suggests the clustering regime is about to shift. This is the gap score concept — credit stress arrives before equity volatility reprices
- **Term structure for expiry selection**: When selecting put expiration, check the IV term structure. If near-term IV is much higher than far-term (inverted structure), consider buying further-dated options where IV is relatively cheaper
- **GARCH-like thinking for our gap score**: The gap between credit signal strength and equity vol repricing is analogous to a GARCH gap — the conditional variance (credit-implied) differs from the unconditional variance (equity IV). Our strategy exploits this divergence

# Chapter 10: Bull and Bear Spreads

## Key Concepts
- **Directional spreads with vol awareness**: Unlike pure directional bets, these spreads integrate option pricing theory. A bullish trader doesn't just buy calls — they construct spreads that exploit vol mispricing while maintaining directional bias
- **Bull/bear ratio spreads**: Modify the delta-neutral ratio to introduce directional bias. A bear put spread buys more ATM puts than it sells OTM puts. The vol edge remains, but with a bearish tilt
- **Delta inversion risk**: Ratio spreads can invert — a bearish spread can become bullish if the underlying moves too far, because delta of deep ITM options converges to 100. The spread "flips" against you
- **Vertical spreads for direction**: Bull call spread (buy lower strike, sell higher strike) or bear put spread (buy higher strike, sell lower strike). These are pure directional trades with capped risk and capped reward
- **Synthetic equivalents**: A bull call spread has the same P&L profile as a bull put spread at the same strikes. Use whichever is more liquid or cheaper to execute
- **Collar strategies**: Buy a put (protection), sell a call (finance the put). Creates a floor and ceiling on an existing position. Cost can be near-zero if put and call premiums offset

## Trading Rules & Practical Takeaways
- **Bear put spreads are the core directional bearish strategy**: Buy a higher-strike put, sell a lower-strike put. Maximum profit = strike difference minus net premium. Maximum loss = net premium paid
- **Choose strike width based on expected move**: If you expect a 15% decline, a 95/85 put spread captures that range. A 95/80 spread captures more but costs more
- **Use naked puts only when vol is very cheap**: If IV percentile is below 20, outright put purchases may be justified because vol expansion will amplify returns. Above that, spreads reduce vega cost
- **Don't fight delta inversion**: If a ratio spread inverts, close or adjust. Don't hold and hope — the position is now working against your view

## Application to Credit-Equity Bridge Strategy
- **Bear put spread IS our ATM_PUT_SPREAD structure**: The chapter provides the complete framework. Buy 95% strike put, sell 85% strike put. Max loss = net debit. Max profit = 10% of notional minus premium. This is our go-to structure when IV percentile is 25-50
- **Strike selection maps to expected decline**: Credit stress typically causes 15-30% equity drops over 3-6 months. So a 95/80 or 90/75 put spread captures the expected range. Our trade_structurer's strike_pct should reflect this
- **Collars for existing equity positions**: If a portfolio already holds shares of Xover names (unlikely for us, but relevant for PM pitches), a collar provides downside protection funded by upside cap. Worth mentioning in recommendations
- **No delta inversion risk for us**: We use bear put spreads (long higher strike, short lower strike), not ratio spreads. Delta inversion doesn't apply — both options have the same position direction

# Chapter 9: Risk Considerations

## Key Concepts
- **Theoretical edge is not the only criterion**: A spread with the highest theoretical edge may not be the best trade. Risk-adjusted returns matter — spreads with higher break-even volatility provide more margin for error
- **Break-even (implied) volatility of a spread**: The volatility at which the spread shows zero P&L. Higher break-even vol = more room for error. A spread selling vol at 22% implied (when your estimate is 15%) is safer than one selling at 17% implied
- **Asymmetric risk**: Volatility risk is asymmetric — underestimating vol is typically worse than overestimating it. If you sell vol and it spikes, losses can be severe. If you buy vol and it drops, losses are limited to premium paid
- **Greeks for position sizing**: Aggregate Greeks across the entire position reveal true risk exposure. A position may look hedged at the individual option level but have massive gamma or vega exposure in aggregate
- **Stress testing**: Always evaluate spreads at extreme scenarios — what happens if vol doubles? What if the underlying moves 3 standard deviations? What if interest rates change? The worst-case scenario defines the real risk
- **Risk vs reward tradeoff in spread selection**: Butterflies have the highest break-even vol (most margin for error) but lowest absolute profit. Short straddles have highest profit potential but lowest margin for error. Always choose the spread that matches your confidence level

## Trading Rules & Practical Takeaways
- **Always check break-even volatility before entering**: Don't just look at theoretical edge. Ask "how wrong can I be and still make money?"
- **Size to the worst case, not the expected case**: If your worst-case loss is X, size the position so X is tolerable. Don't size based on expected profit
- **Prefer spreads with wider break-even ranges**: Given similar theoretical edge, choose the spread with more margin for error. Consistency beats occasional big wins
- **Gamma risk is your biggest enemy in short vol**: Negative gamma means losses accelerate as the underlying moves. This is the "picking up pennies in front of a steamroller" risk
- **Don't overweight theoretical precision**: Vol estimates are always wrong to some degree. Build positions that are profitable across a range of volatility outcomes, not just at your point estimate

## Application to Credit-Equity Bridge Strategy
- **We are BUYING vol (positive vega), so asymmetric risk works in our favour**: When we buy puts, our worst case is losing the premium. The book confirms this is the safer side of the risk equation — underestimating vol (buying too cheap) is less dangerous than overestimating it (selling too expensive)
- **Break-even vol for our put spreads**: Before entering any put spread, calculate the break-even vol. If we're buying a put spread when IV is at the 25th percentile, what vol needs to realise for us to profit? If the answer is below historical average, we have margin for error
- **Max premium constraint = position sizing rule**: Our trade_structurer's max_premium_pct (3-5%) is exactly the stress-test approach the chapter recommends — limiting worst-case loss to a tolerable percentage of notional
- **Spread selection by confidence**: STRONG gap signals (>50) → can use higher-risk/higher-reward structures (OTM puts, higher delta). MODERATE signals (30-50) → use lower-risk structures (put spreads, butterflies). This maps confidence to margin-for-error

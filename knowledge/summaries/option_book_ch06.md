# Chapter 6: Option Values and Changing Market Conditions (The Greeks)

## Key Concepts
- **Delta (Δ)**: Rate of change of option price vs underlying price. Calls: 0 to +100; Puts: 0 to -100. ATM ≈ 50 delta. Also approximates probability of finishing ITM
- **Gamma (Γ)**: Rate of change of delta. Highest for ATM options near expiry. Long options have positive gamma (benefit from large moves); short options have negative gamma (hurt by large moves)
- **Theta (Θ)**: Time decay per day. Long options lose value as time passes (negative theta). Theta accelerates as expiry approaches, especially for ATM options. The cost of holding a long option position
- **Vega (V/κ)**: Sensitivity to changes in implied volatility. Long options have positive vega (benefit from vol increase). ATM options have highest vega. Vega decreases as expiry approaches
- **Rho (ρ)**: Sensitivity to interest rate changes. Generally small for short-dated equity options. Rising rates increase call values, decrease put values (for stock options)
- **Interest rate and dividend effects**: Rising rates make calls more valuable (cheaper substitute for owning stock). Rising dividends make puts more valuable (cheaper substitute for shorting stock)
- **Greeks change with market conditions**: Delta depends on moneyness and time; gamma peaks at ATM near expiry; theta is worst at ATM near expiry; vega is highest at ATM with long time to expiry

## Trading Rules & Practical Takeaways
- **Target delta determines directional exposure**: Our recommended target_delta in trade recommendations directly controls how much we profit per unit move in the underlying
- **Buy gamma when you expect large moves**: Long puts have positive gamma — we profit disproportionately from large downward moves. This is ideal for credit event-driven trades
- **Monitor theta bleed**: Every day we hold a long put, theta erodes its value. Monthly theta cost = option price × (theta/option price). If credit catalyst doesn't materialise within the expected timeframe, theta destroys the position
- **Vega is your friend at low IV**: Buying puts when IV is low means we benefit from both the directional move AND the likely IV expansion that accompanies stress events. Double tailwind
- **Gamma-theta tradeoff**: Positive gamma (profiting from moves) always comes with negative theta (time decay). The question is whether the expected move justifies the theta cost

## Application to Credit-Equity Bridge Strategy
- **IV percentile < 25: Maximum vega benefit**: At low IV percentile, our puts have maximum vega exposure. When the credit event hits, IV spikes AND the stock drops — we profit on both. This is why trade_structurer recommends OTM puts (high vega per dollar) at low IV
- **IV percentile > 50: Minimise vega cost**: At high IV percentile, vega exposure is dangerous — vol could compress even as the stock falls. This is why trade_structurer switches to put spreads (long put + short put = lower net vega) or far OTM puts
- **Theta budgeting**: For a 3-month ATM put at 30% IV, theta might be ~0.05% of notional per day. Over 90 days, that's 4.5% of notional just in time decay. This must be smaller than the expected move to be profitable
- **Delta selection = conviction mapping**: Our trade_structurer's target_delta (0.15-0.50) maps to conviction. High conviction (STRONG gap) → higher delta puts (closer to ATM, more expensive, more profit per unit move). Lower conviction → lower delta (further OTM, cheaper, needs bigger move)
- **Gamma matters for event timing**: Near-expiry puts have enormous gamma — small moves produce huge P&L changes. For restructuring events with uncertain timing, longer-dated puts with moderate gamma are safer. For imminent catalysts (earnings, rating action), shorter-dated puts with higher gamma maximise profit

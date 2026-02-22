# Chapter 17: Position Analysis

## Key Concepts
- **Position graphing**: The primary tool for understanding complex option positions. Plot P&L (y-axis) against underlying price (x-axis) under current conditions, at expiration, and at intermediate time points
- **Interpreting the Greeks visually**: Delta = slope at current price; Gamma = curvature (positive gamma = smile/convex, negative gamma = frown/concave); Theta = vertical shift over time; Vega = vertical shift with vol changes
- **Contract position (tail risk)**: At extreme prices, determine how many contracts you're effectively long or short. On the upside, count net long/short calls (all puts go to zero); on the downside, count net long/short puts (all calls go to zero). This reveals unlimited risk exposure
- **Ratio vertical spread analysis**: Negative gamma + positive theta + negative vega. The position has an implied volatility — the vol at which it breaks even. Above that vol it loses, below it profits
- **Diagonal/time spread analysis**: Positive gamma + negative theta + negative vega (for short time spread). Movement helps, time decay hurts, vol decrease helps. The position becomes more extreme (higher gamma risk) as expiration approaches
- **Gamma-neutral doesn't mean risk-free**: Even if delta, gamma, and vega are all neutral, the position can lose if model assumptions are wrong. A "neutral" position is only neutral if the model is correct
- **Complex multi-leg positions**: Large positions spanning multiple strikes and expirations require systematic analysis. Decompose into Greeks, but also visualise the full P&L graph because Greeks only describe local behaviour
- **Multi-underlying positions**: When positions span different underlyings, use $delta/$gamma/$theta/$vega and express price changes in standard deviations to make the positions comparable

## Trading Rules & Practical Takeaways
- **Always know your contract position**: Before entering any spread, calculate what happens if the market makes a very large move in either direction. The "tail" position determines your ultimate risk — unlimited upside/downside risk vs. limited
- **Graph before you trade**: Mentally or computationally visualise the P&L graph using: theoretical edge (where it crosses zero), delta (slope), gamma (curvature), and contract position (tail behaviour). This takes seconds and prevents catastrophic surprises
- **Gamma risk increases near expiration**: The curvature of at-the-money options becomes extreme near expiry. Positions that look benign with 4 weeks to go can become unmanageable with 1 week left
- **Time and volatility affect delta**: As time passes or vol falls, deltas move away from 50 (ITM options → 100, OTM options → 0). This changes the position's directional exposure even if nothing else changes
- **Use standard deviations for cross-asset comparison**: To compare P&L sensitivity across positions in different underlying instruments, express price moves in standard deviations rather than points or percent

## Application to Credit-Equity Bridge Strategy
- **Position analysis is essential for our portfolio**: With 44 potential names, we could have multiple concurrent positions. Each needs individual analysis plus portfolio-level aggregation. This chapter provides the analytical framework
- **Our put positions have defined contract exposure**: When we buy puts, our downside contract position is long (profit from further decline). Our upside contract position is flat (puts expire worthless, limited loss = premium). This is the ideal profile for our credit-stress thesis
- **Gamma behaviour near expiry informs our exit timing**: If we hold puts that are near ATM as expiration approaches, gamma becomes extreme. Either close the position or roll to longer-dated options to avoid the gamma cliff
- **Greeks change with market conditions**: If we buy a 10% OTM put and the stock drops 8%, our put is now near ATM with much higher gamma and vega. This is actually beneficial — our position is gaining convexity as our thesis plays out. Understanding this dynamic helps us avoid panic-selling a winning position
- **Standard deviation framework for gap score calibration**: The gap score measures how far credit has moved relative to equity in "signal space." Expressing both sides in standard deviations (e.g., CDS moved 2σ while equity moved 0.5σ) would make the gap score more robust across names at different price levels and volatilities
- **Portfolio-level risk aggregation**: When we have multiple put positions, aggregate the $delta, $gamma, $theta, $vega across the portfolio. This reveals net exposure: are we net long volatility? How much time decay are we paying daily? How much directional exposure do we have across the book?

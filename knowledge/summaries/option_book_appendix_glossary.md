# Appendix A: Glossary of Option and Related Terminology

## Key Terms for Credit-Equity Bridge Strategy

### Core Option Terms
- **At-the-Money (ATM)**: Exercise price = current underlying price. Highest gamma, most time value, most sensitive to vol changes
- **In-the-Money (ITM)**: Call with strike < underlying (or put with strike > underlying). High delta, lower time value
- **Out-of-the-Money (OTM)**: Call with strike > underlying (or put with strike < underlying). Low delta, all time value — our primary put structure
- **American Option**: Can be exercised anytime before expiration. Most US single-stock options
- **European Option**: Can only be exercised at expiration. Most index options, many Eurex options — relevant for our European equity targets
- **Assignment**: When the option seller is notified the buyer is exercising. Risk for short option positions
- **Automatic Exercise**: Clearing house exercises ITM options at expiration unless instructed otherwise

### Strategy Terms
- **Backspread**: Delta-neutral spread buying more options than sold (long gamma, long vega). Profits from large moves
- **Butterfly**: Buy one lower + one higher strike, sell two middle strikes. Low cost directional/vol bet
- **Collar/Fence/Cylinder**: Long put + short call (or vice versa) against underlying position. Zero-cost hedge structure
- **Conversion/Reversal**: Arbitrage combining synthetic and actual underlying positions to exploit put-call parity violations
- **Covered Write (Buy/Write)**: Sell call against long stock. Income strategy, caps upside
- **Straddle**: Long call + long put, same strike. Pure volatility bet
- **Strangle**: Long call + long put, different strikes. Cheaper vol bet, needs bigger move
- **Time/Calendar Spread**: Same strike, different expirations. Profits from time decay differential

### Greek Letters
- **Delta**: Price sensitivity to underlying movement. Our primary hedge ratio
- **Gamma**: Rate of delta change. Highest for ATM near expiry. Determines adjustment frequency
- **Theta**: Time decay per day. Cost of holding long options — the "insurance premium"
- **Vega**: Sensitivity to implied volatility changes. Critical for our strategy — we want vega exposure when buying puts before vol reprices
- **Rho**: Sensitivity to interest rate changes. Usually minor for short-dated options

### Exotic/Advanced Terms
- **Barrier Option**: Activates or deactivates at a price level. Knock-in/knock-out structures
- **Asian/Average Price Option**: Payoff based on average price over period
- **Chooser Option**: Straddle where you must decide to keep the call or put by a set date
- **Compound Option**: Option on an option
- **Lookback Option**: Payoff based on best price during the option's life

## Application to Credit-Equity Bridge Strategy
This glossary provides the shared vocabulary for our trade_structurer decision tree. Key mappings:
- **OTM puts** = our primary instrument when gap score is strong and IV is low
- **Bear put spreads** = bear vertical spreads in the glossary — used when IV is moderate
- **Put ratio backspreads** = backspreads — used when we want unlimited downside exposure at lower cost
- **Collars/fences** = used conceptually when managing portfolio-level hedges
- **Vega** = the primary Greek we want exposure to — buying options before vol reprices captures vega profit

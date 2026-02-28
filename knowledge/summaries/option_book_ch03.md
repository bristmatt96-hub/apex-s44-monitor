# Chapter 3: Introduction to Theoretical Pricing Models

## Key Concepts
- **Expected return and edge**: An option's theoretical value is the price at which you'd break even over many trades. Paying less than theoretical value gives you a positive edge — like buying a roulette bet for less than 95 cents
- **Speed matters as much as direction**: Unlike underlying instruments where direction is the only variable, option traders must also predict market speed (volatility). Being right on direction but wrong on speed can still produce losses
- **Five key pricing inputs**: (1) underlying price, (2) exercise price, (3) time to expiration, (4) expected direction of movement, (5) expected speed/volatility of movement
- **Lognormal distribution assumption**: The Black-Scholes model assumes returns follow a lognormal distribution — prices can rise indefinitely but can't fall below zero. This creates asymmetry critical for options pricing
- **Forward pricing**: The theoretical value uses the forward price (spot + carry costs - dividends), not the spot price. This accounts for the cost of holding the underlying through expiry
- **Interest rates and carry**: Interest rates affect option values because options are substitutes for the underlying position — they embed a financing component

## Trading Rules & Practical Takeaways
- **Always compare price to theoretical value**: The edge = theoretical value - market price. Positive edge = buy; negative edge = sell. This is the foundation of informed option trading
- **Don't buy options just for leverage**: Speculators who buy options purely for limited-risk/unlimited-reward lose because they pay more than theoretical value and must be right on both direction AND speed
- **Time is always working against long options**: Time value decays constantly — the option buyer fights the clock
- **The model is a guide, not gospel**: All models make simplifying assumptions about distributions that may not hold in reality. Use them as frameworks, not truth

## Application to Credit Strategy
- **Theoretical value framework applies to all instruments**: Whether pricing CDS, basis trades, or tranches, the core principle is the same — compare price to theoretical value and exploit the gap. This applies to long/short CDS selection, bond-CDS basis, and tranche positioning, not just options
- **The gap score is one cross-asset signal**: When credit signals lead equity repricing, it can inform options positioning as one possible trade expression. But the primary strategy is long/short CDS, basis, and tranches — not equity puts
- **Time-to-expiry selection matters when using options**: When equity put expression is chosen, match expiry to catalyst timing — maturity wall catalysts need 6-9 month puts, not 3-month
- **Forward price matters for European options**: European equity puts (Eurex) are priced off forward prices — relevant when options are the chosen expression

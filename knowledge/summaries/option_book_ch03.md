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

## Application to Credit-Equity Bridge Strategy
- **Our edge comes from information asymmetry in timing**: Credit signals (CDS widening, filings) give us advance warning of equity repricing. This timing advantage is how we can buy puts below their eventual realised value — we know the speed component before the equity market does
- **The gap score IS the edge calculation**: When gap_score is high (credit signal >> equity repricing), puts are mispriced because the market hasn't factored in the credit deterioration signal. We're buying theoretical value cheaply
- **Time-to-expiry selection is critical**: Being right about direction (equity will fall) but wrong about timing (it takes 6 months not 3) destroys put trades. The trade_structurer must match expiry to expected catalyst timing — maturity_wall catalysts need 6-9 month puts, not 3-month
- **Forward price matters for European options**: Our European equity puts (Eurex) are priced off forward prices. High dividend-paying stocks have lower forward prices, making puts relatively cheaper — relevant for Consumer sector names paying dividends

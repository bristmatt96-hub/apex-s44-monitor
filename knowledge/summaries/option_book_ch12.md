# Chapter 12: Early Exercise of American Options

## Key Concepts
- **Early exercise = giving up time value**: Exercising early converts the option into the underlying, forfeiting any remaining time value. Only rational when the cash flow benefit exceeds the time value surrendered
- **Futures options early exercise**: Driven by interest rates. Deep ITM futures options with stock-type settlement earn interest on the intrinsic value if exercised early. Exercise when interest earned > time value remaining
- **Stock options — calls**: Only exercise early to capture a dividend. If the dividend exceeds the time value of the call, exercise just before ex-dividend. Otherwise, selling the call is always better
- **Stock options — puts**: Deep ITM puts on low-volatility stocks may be exercised early to earn interest on the cash received from selling stock at the strike price. More likely when interest rates are high and vol is low
- **American premium**: The extra value of an American option over its European equivalent. For calls, the premium is related to expected dividends. For puts, related to interest rates. Usually small (0-5% of option value)
- **Automatic exercise risk**: Short options positions face assignment risk. The risk is highest just before ex-dividend dates (calls) and when options are deep ITM near expiry

## Trading Rules & Practical Takeaways
- **For European options (most of our targets), early exercise is irrelevant**: European options on Eurex, Euronext, etc. cannot be exercised early. This simplifies our strategy significantly
- **Watch for American-style options on LSE**: Some UK-listed options (PTEC.L, ZEG.L, etc.) may be American. Check exercise style before trading
- **Dividend awareness for call spreads**: If we ever use call-based structures (unlikely for bearish strategy), understand that short calls can be assigned early around ex-dividend dates
- **Deep ITM puts have minimal time value**: If our put becomes deep ITM (stock drops 30%+), the option will trade near intrinsic value. Time value approaches zero, so there's little benefit to holding vs exercising (for American) or closing

## Application to Credit-Equity Bridge Strategy
- **Mostly irrelevant for our core strategy**: We buy European puts on European equities — no early exercise. However, for any US-listed or American-style options, be aware of assignment risk on short legs of put spreads
- **Early assignment on short put leg**: If we have a bear put spread and the stock crashes, the short lower-strike put (American) could be assigned early, requiring us to buy the stock. This converts the spread into a stock position + long put. Not catastrophic but changes the risk profile
- **Implications for calendar put spreads**: If the short near-term put is American and goes deep ITM, early assignment converts the position into long stock + long far-dated put. This may actually be acceptable — it's equivalent to a protective put, which still benefits from further decline
- **American premium is essentially rounding error**: For our strategy's precision level (3-5% max premium, ±10% strike), the American premium is negligible. Don't overthink it

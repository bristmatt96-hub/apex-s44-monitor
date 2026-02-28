# Chapter 1: The Language of Options

## Key Concepts
- **Calls vs Puts**: A call is the right to buy (go long); a put is the right to sell (go short) the underlying asset at the strike price before expiration
- **Contract specifications**: Every option is defined by underlying asset, exercise/strike price, expiration date, and type (call/put)
- **American vs European exercise**: American options can be exercised any time before expiry; European only at expiry. Most exchange-traded options are American
- **Exercise and assignment**: The buyer exercises; the seller gets assigned. All rights lie with the buyer, all obligations with the seller
- **Opening vs closing transactions**: Opening creates a new position; closing offsets an existing one. Open interest tracks outstanding contracts
- **Long vs short market position**: Being long a call or short a put = bullish; being long a put or short a call = bearish
- **Settlement types**: Physical delivery (stock/commodity changes hands) vs cash settlement (index options — pay difference in cash)

## Trading Rules & Practical Takeaways
- Always know your exercise style (American/European) — it affects pricing and early assignment risk
- Understand the difference between being long/short an option vs being long/short the market
- Margin requirements apply to short option positions; long options require premium payment only
- An option ceases to exist after exercise — it converts into an underlying position at the strike price
- In-the-money options at expiry are typically auto-exercised by the exchange

## Application to Credit Strategy
- **Options as one trade expression**: The primary strategy is long/short CDS, bond-CDS basis, and delta-hedged tranches (0-3%). Equity puts are one possible expression when credit-equity divergence is the chosen angle — not the core instrument
- **European vs American**: Most European equity options (Eurex, Euronext) are European-style — no early exercise. Relevant when options expression is selected
- **Cash settlement awareness**: Index options settle in cash — relevant for iTraxx swaptions and index-level hedging
- **Assignment risk on short legs**: When put spreads are part of the expression, assignment risk applies on the short leg

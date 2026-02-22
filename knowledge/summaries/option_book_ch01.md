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

## Application to Credit-Equity Bridge Strategy
- **Put options are the core instrument**: When our gap score signals credit stress ahead of equity repricing, we buy puts — the right to sell the equity at a fixed price. This chapter's foundation on puts as the right to take a short position at a fixed price is the building block
- **European vs American**: Most European equity options (Eurex, Euronext) are European-style — no early exercise. This simplifies our pricing models in the trade structurer
- **Cash settlement awareness**: Index options (e.g., sector ETF puts for sector_stress catalyst) settle in cash, simplifying exit
- **Assignment risk on short legs**: When our trade_structurer recommends put spreads (selling a lower-strike put), we carry assignment risk on the short leg — relevant for ATM_PUT_SPREAD and CALENDAR_PUT structures

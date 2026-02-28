# Appendices C, D, E: Volatility Spread Characteristics, Strategy Selection & Synthetic Relationships

## Appendix C: Characteristics of Volatility Spreads

All spreads assumed approximately delta neutral:

| Spread Type | Gamma | Theta | Vega | Large Move | IV Increase | Time Passing |
|---|---|---|---|---|---|---|
| Call/Put Backspread | + | - | + | Helps | Helps | Hurts |
| Ratio Vertical Spread | - | + | - | Hurts | Hurts | Helps |
| Long Straddle/Strangle | + | - | + | Helps | Helps | Hurts |
| Short Straddle/Strangle | - | + | - | Hurts | Hurts | Helps |
| Long Butterfly | - | + | - | Hurts | Hurts | Helps |
| Short Butterfly | + | - | + | Helps | Helps | Hurts |
| Long Time Spread (1:1) | - | + | + | Hurts | Helps | Helps |
| Short Time Spread (1:1) | + | - | - | Helps | Hurts | Hurts |

**Key insight**: Gamma and theta are always opposite sign. You pay for gamma (movement profit) via theta (time decay). This is the fundamental tradeoff in all option strategies.

## Appendix D: What's the Right Strategy?

Strategy selection matrix by direction view x IV regime:

### Bearish + Low IV (our ideal setup)
- Buy naked puts
- Bear vertical spreads: buy ATM put / sell OTM put
- Sell OTM call butterflies
- Buy ITM call time spreads

### Bearish + Moderate IV
- Sell the underlying
- Bear vertical spreads: buy OTM call / sell ATM call, or buy ITM put / sell ATM put
- Buy ITM call butterflies
- Sell OTM call time spreads

### Bearish + High IV
- Sell naked calls
- Bear vertical spreads (tighter)
- Ratio vertical spreads
- Sell straddles/strangles
- Buy ATM call butterflies
- Sell ATM call time spreads

### No Direction + Low IV
- Backspreads
- Buy straddles/strangles
- Sell ATM butterflies
- Buy ATM time spreads

### No Direction + High IV
- Ratio vertical spreads
- Sell straddles/strangles
- Buy ATM butterflies
- Sell ATM time spreads

### No Direction + No IV View
- **Sit on the sidelines** — a disciplined trader waits for better conditions

## Appendix E: Synthetic & Arbitrage Relationships

### Core Synthetic Equivalents
- Synthetic long underlying = long call + short put (same strike/expiry)
- Synthetic short underlying = short call + long put
- Synthetic long call = long underlying + long put
- Synthetic short call = short underlying + short put
- Synthetic long put = short underlying + long call
- Synthetic short put = long underlying + short call

### Arbitrage Structures
- **Conversion** = long underlying + short call + long put (same strike)
- **Reverse Conversion** = short underlying + long call + short put
- **Box** = synthetic long underlying at one strike + synthetic short at another = bull call spread + bear put spread
- **Jelly Roll** = synthetic long underlying in one month + synthetic short in another = call time spread + put time spread (reversed)

### European Option Arbitrage Values
- For futures: synthetic market = call - put = futures price - exercise price
- For stocks: synthetic market = call - put = stock price - exercise price + carry costs - dividends
- Box market = present value of (difference between exercise prices)
- Jelly roll market = carry costs on exercise price between expirations - expected dividends

## Application to Credit Strategy

### Strategy Selection Matrix — When Options Are the Expression
When the trade expression includes equity options (not always — primary instruments are CDS, basis, tranches):
- **Bearish + Low IV** → straight put purchase
- **Bearish + Moderate IV** → bear put spread
- **Bearish + Moderate-High IV** → put ratio backspread
- **Moderate conviction** → calendar put spreads or narrower verticals
- The trade_structurer encodes this logic for the subset of trades using options

### Volatility Spread Greeks
When long puts (one possible expression):
- A large move in the underlying **helps** (positive gamma)
- An increase in IV **helps** (positive vega)
- Time passing **hurts** (negative theta) — the cost of carry on this expression

### Synthetic Relationships for Advanced Structures
Understanding that a long put = short underlying + long call means we could alternatively express our bearish view via:
- Selling stock short + buying a call (= synthetic put)
- But direct put purchases are simpler and have defined risk, which is preferred for our strategy

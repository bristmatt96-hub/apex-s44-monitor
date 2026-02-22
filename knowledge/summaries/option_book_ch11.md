# Chapter 11: Option Arbitrage

## Key Concepts
- **Synthetic positions**: Any option position can be replicated with combinations of other options and the underlying. Long call + short put = synthetic long underlying. Short underlying + long call = synthetic long put. These create arbitrage opportunities when prices diverge
- **Put-call parity**: C - P = S - PV(K) for European options. This relationship must hold; violations create risk-free profit. It links call prices, put prices, underlying prices, and interest rates
- **Conversion and reversal**: A conversion is long underlying + long put + short call (same strike). A reversal is the opposite. Both are arbitrage trades that exploit put-call parity violations. Risk-free profit when the synthetic and actual prices diverge
- **Box spreads**: A bull call spread + bear put spread at the same strikes = a box. The value at expiry is always the strike difference. If the box can be bought for less than PV(strike difference), it's an arbitrage
- **Interest rate effects on arbitrage**: Conversions and reversals are financing trades — their profitability depends on interest rates and the cost of carrying positions. The arbitrage edge is often just the interest rate differential
- **Dividend arbitrage**: For stocks paying dividends, put-call parity includes the dividend. If the market misprices the dividend component, arbitrage opportunities arise around ex-dividend dates

## Trading Rules & Practical Takeaways
- **Use put-call parity to check fair pricing**: Before buying a put, check if the equivalent synthetic position (short stock + long call) is cheaper. European markets sometimes have pricing inefficiencies
- **Conversions/reversals are market-maker territory**: These require very tight execution and low transaction costs. Retail traders can't compete here, but understanding the mechanics helps spot mispricing
- **Dividend risk in synthetic positions**: If you hold a synthetic short (short call + long put) and the stock goes ex-dividend, the short call may be assigned early. Understand the dividend calendar for each name

## Application to Credit-Equity Bridge Strategy
- **Put-call parity as a sanity check**: Before entering any put position, verify the price makes sense relative to the corresponding call and the underlying. If our target put seems expensive, check if a synthetic put (short stock + long call) is cheaper
- **Dividend adjustment for European names**: Many Xover names (Telecom Italia, ThyssenKrupp, etc.) pay dividends. Put-call parity means puts are worth more when dividends are expected — but only if the market hasn't already priced them in. Check dividend calendars before trade entry
- **Synthetic puts when options are illiquid**: For Xover names with illiquid put markets (low options_liquidity in our equity map), we could theoretically construct synthetic puts. However, short-selling European stocks requires borrowing — adding complexity and cost
- **Box spread pricing reveals implied rates**: The discount on a box spread reveals the market's implied interest rate. This can be compared to actual rates as another relative value signal

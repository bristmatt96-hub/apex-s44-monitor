# Chapter 8: Volatility Spreads

## Key Concepts
- **Backspreads (long ratio spreads)**: More long options than short, always at different strikes. Positive gamma, positive vega, negative theta. Profit from large price movements. Call backspreads for upside; put backspreads for downside
- **Ratio vertical spreads**: More short options than long. Negative gamma, negative vega, positive theta. Profit from price stability and declining vol. The inverse of backspreads
- **Straddles and strangles**: Long straddles (buy ATM call + ATM put) profit from large moves in either direction. Short straddles profit from no movement. Strangles use OTM strikes — cheaper but need bigger moves
- **Butterflies and condors**: Long butterfly = buy wings, sell body. Profits from price stability around the short strike. Maximum profit when underlying expires at middle strike. Limited risk on both sides
- **Calendar (time) spreads**: Sell near-term option, buy longer-term option at same strike. Profits from time decay differential — near-term decays faster. Positive vega (benefits from vol increase). Maximum profit when underlying at strike at near-term expiry
- **Spread classification by Greeks**: Every volatility spread can be classified by its gamma, theta, and vega signs. Positive gamma = positive vega = negative theta (and vice versa). There's always a tradeoff

## Trading Rules & Practical Takeaways
- **Put backspreads for expected crashes**: Buy more OTM puts than ATM puts you sell. Done for a credit, unlimited downside profit. Ideal when you expect a large down move but want protection if wrong
- **Ratio put spreads for high-IV environments**: Sell more OTM puts than you buy ATM puts. Collect premium. Works if stock doesn't crash below the lower strike. Dangerous in genuine credit events
- **Calendar spreads when timing is uncertain**: Sell the near month, buy the far month. If the catalyst doesn't trigger immediately, you profit from the faster decay of the near-term option
- **Butterfly for moderate views**: Low cost, limited risk, but limited profit. Best when you have a specific price target

## Application to Credit-Equity Bridge Strategy
- **Put backspread for restructuring catalyst**: When our trade_structurer identifies a restructuring catalyst (binary outcome — recovery or collapse), a put backspread is ideal. Sell 1 ATM put, buy 2 OTM puts. Credit received if wrong (recovery), large profit if right (collapse). This should be added as a possible structure
- **Calendar put for maturity_wall**: Maturity walls have known dates. Sell puts expiring before the maturity date, buy puts expiring after. This reduces carry cost while maintaining exposure through the critical refinancing window
- **Straddle for aggressive_sponsor (confirmed)**: The book validates our STRADDLE recommendation for binary outcomes. PE sponsor situations can go either way — LBO (stock up) or dividend recap/value extraction (credit deterioration, stock down)
- **Avoid ratio put spreads on credit stress names**: Selling more puts than we buy creates naked short put exposure below the lower strike — exactly the scenario where credit events cause 30-50% drops. Never sell naked downside on names with genuine credit stress

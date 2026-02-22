# Chapter 15: Stock Index Futures and Options

## Key Concepts
- **Index calculation**: Stock indexes are calculated as weighted averages of component stocks. Weighting methods include price-weighted (DJIA), capitalisation-weighted (S&P 500, Euro Stoxx 50), and equal-weighted
- **Index arbitrage (program trading)**: If the futures price deviates from the theoretical forward price (spot + carry costs - dividends), arbitrageurs buy the cheap instrument and sell the expensive one. This keeps futures in line with the cash index
- **Basis and fair value**: The basis = futures price - cash index. Fair value = carrying cost - expected dividends. When futures trade above fair value, buy stocks/sell futures; when below, sell stocks/buy futures
- **Index options vs. stock options**: Index options settle in cash (no physical delivery). The exercise/settlement mechanism creates unique risks — you can't perfectly hedge an index option position by holding the index
- **Tracking error**: A portfolio's returns may not perfectly match the index returns, creating tracking error. This is a risk for anyone hedging portfolios with index options or futures
- **Settlement procedures**: Index options can settle using opening prices (AM settlement) or closing prices (PM settlement). AM settlement means the settlement price is determined by the opening prices of all index components, which can differ significantly from the previous close
- **Systematic vs. unsystematic risk**: Index options hedge systematic (market) risk but not unsystematic (stock-specific) risk. Beta measures a stock's sensitivity to the broader market

## Trading Rules & Practical Takeaways
- **Use beta-adjusted hedging**: When hedging a stock portfolio with index options/futures, adjust the hedge ratio by the portfolio's beta. A portfolio with beta = 1.2 needs 20% more index options than a portfolio with beta = 1.0
- **Be aware of settlement risk**: AM-settled index options can have very different settlement values from the previous day's close. This creates "pin risk" on expiration day
- **Tracking error is real risk**: Don't assume a portfolio perfectly tracks an index. The deviation creates unhedged exposure that can be significant in stressed markets
- **Dividend considerations**: Index futures pricing must account for the dividend stream of index components. Errors in dividend estimates create pricing errors in both futures and options
- **Conversion/reversal in indexes**: The put-call parity relationship may not hold perfectly in index options because of the difficulty of creating a perfect index position. This creates apparent arbitrage opportunities that are actually illiquid

## Application to Credit-Equity Bridge Strategy
- **Our targets are mostly single-stock options, not index options**: This chapter is less directly relevant since we buy puts on individual equities (Volkswagen, Nokia, etc.) based on name-specific credit signals. However, understanding index dynamics helps when signals affect multiple names in the same sector
- **Beta-adjusted position sizing**: If we have multiple names in the same sector showing credit stress (e.g., European autos), we could potentially use index options (Euro Stoxx 50 puts) as a cheaper alternative. The beta relationship tells us the hedge ratio needed
- **Settlement mechanics matter for European options**: Our target options are mostly European-style (Eurex, Euronext). Understanding AM vs. PM settlement is important for exit timing around expiration
- **Tracking error concept applies to our strategy**: When we use a sector-level CDS index (iTraxx Crossover) as a signal but trade single-name equity puts, we face a "tracking error" between the signal source and the trade instrument. The gap score partially captures this
- **Systematic risk in credit crises**: In a genuine credit event, correlation spikes — all names in a sector may decline together. Understanding the index/single-stock relationship helps decide between concentrated single-name trades vs. broader index puts

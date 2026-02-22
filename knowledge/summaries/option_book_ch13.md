# Chapter 13: Hedging with Options

## Key Concepts
- **Options as insurance**: Options transfer part of the risk from one party to another, functioning like insurance policies. The option price is the premium; the distance between current price and strike is the deductible
- **Protective calls and puts**: The simplest hedge — buy a call to protect a short position, buy a put to protect a long position. Limited downside risk with unlimited profit potential retained. A protective put + long stock = synthetic long call
- **Covered writes (overwrites)**: Sell a call against a long position (or put against short position). Generates income that provides partial protection, but caps upside profit. Selling ATM options maximises time premium collected
- **Fences (collars/tunnels/range forwards)**: Simultaneously buy a protective option and sell a covered option. Long fence = long underlying + long put + short call = synthetic bull vertical spread. Popular because they offer known protection at low or zero cost
- **IV regime determines strategy choice**: In high IV environments, buy as few options as possible, sell as many as possible (ratio writes). In low IV environments, buy as many options as possible, sell as few as possible (ratio purchases)
- **Portfolio insurance**: Replicating a put option by continuously rehedging the underlying position — selling as market falls, buying as market rises. Cost of replication = theoretical value of the put. Transaction costs are the main practical limitation
- **Delta-based hedge sizing**: A hedger who wants to retain 50% of upside exposure needs puts with total delta of -50. Can use one ATM put (delta -50) or several OTM puts adding to -50

## Trading Rules & Practical Takeaways
- **Match hedge strategy to IV regime**: When IV is high (options overpriced), prefer selling covered options or ratio writes. When IV is low (options underpriced), prefer buying protective options
- **Fence = zero-cost hedge**: If a hedger wants protection without cash outlay, a fence (buy OTM put + sell OTM call vs. long stock) often achieves near-zero cost while providing a floor and ceiling
- **Choose strikes based on risk tolerance**: Higher deductible (further OTM protective option) = lower premium but less protection. The choice is subjective based on the hedger's worst-case scenario
- **Volatility spreads as hedges**: Time spreads and butterflies can be used as delta-targeted hedges while also having a positive theoretical edge if positioned correctly relative to IV
- **Portfolio insurance limitations**: The 1987 crash exposed the fatal flaw — in a gap move (discontinuous prices), the rehedging process cannot keep up. Transaction costs also erode the strategy in practice

## Application to Credit-Equity Bridge Strategy
- **Our core trade IS a protective put**: When we detect credit stress (CDS widening) before equity reprices, we are essentially buying insurance on the equity via puts. Chapter 13 validates this as the fundamental hedging strategy
- **IV regime directly maps to our trade_structurer decision tree**: When IV percentile is low (<25th), we should buy more options (straight puts, put spreads with wide wings). When IV is high (>75th), we should consider selling premium (covered structures, ratio spreads) — this exactly matches our existing logic
- **Fence/collar concept for partial hedges**: If our gap score is moderate (30-50) rather than strong, a fence structure (buy OTM put, sell further OTM put) = bear put spread might be optimal. This limits cost while providing targeted downside exposure
- **Delta-based sizing**: We should size our put positions based on the desired delta exposure relative to the underlying notional we want to hedge. If gap score suggests a 5% move is likely, buy puts whose total delta * notional = desired P&L from that move
- **Portfolio insurance parallel**: Our strategy is essentially manual portfolio insurance — we're buying puts (or replicating put-like exposure) when credit signals indicate the "insurance" is needed, rather than continuously rehedging

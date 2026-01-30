# Trading Books Knowledge Base

Drop PDF books into the appropriate folder. The system will index them and use insights to inform trading decisions.

## Folder Structure

### trading_psychology/
Mental game, discipline, emotional control
- Trading in the Zone (Mark Douglas)
- The Psychology of Trading (Brett Steenbarger)
- Thinking Fast and Slow (Kahneman)
- Reminiscences of a Stock Operator (Lefevre)

### technical_analysis/
Charts, patterns, indicators
- Technical Analysis of Financial Markets (Murphy)
- Japanese Candlestick Charting (Nison)
- Encyclopedia of Chart Patterns (Bulkowski)

### market_structure/
How markets work, order flow, market makers
- Trading and Exchanges (Harris)
- Flash Boys (Lewis)
- Market Wizards series (Schwager)

### risk_management/
Position sizing, capital preservation, drawdown control
- The Complete Guide to Position Sizing (Van Tharp)
- Fortune's Formula (Poundstone)
- Against the Gods (Bernstein)

### options_strategies/
Options trading, Greeks, volatility
- Option Volatility and Pricing (Natenberg)
- Options as a Strategic Investment (McMillan)
- Dynamic Hedging (Taleb)

### behavioral_finance/
Market psychology, crowd behavior, biases
- Irrational Exuberance (Shiller)
- A Random Walk Down Wall Street (Malkiel)
- Fooled by Randomness (Taleb)

### macro_economics/
Fed, interest rates, economic cycles
- The Alchemy of Finance (Soros)
- Principles for Dealing with the Changing World Order (Dalio)
- When Genius Failed (Lowenstein)

### classics/
Timeless wisdom, foundational texts
- The Intelligent Investor (Graham)
- Security Analysis (Graham & Dodd)
- Common Stocks and Uncommon Profits (Fisher)

## How to Use

1. Drop PDF files into the appropriate folder
2. Run: `python -m knowledge.ingest --process-books`
3. The system will extract text, chunk it, and index it
4. Insights will appear in trade alerts when relevant

## What Gets Indexed

- Full text content
- Topics and themes per chunk
- Source attribution (so you know which book said what)

## Philosophy

"Read 500 pages every day. That's how knowledge works.
It builds up, like compound interest." - Warren Buffett

# APEX S44 Monitor - Multi-Agent Trading System

Autonomous multi-agent trading system designed for aggressive risk/reward trading across multiple markets including equities, crypto, forex, and options.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              COORDINATOR                                     │
│    (Central orchestrator - routes messages, enforces risk limits)           │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          ▼                          ▼                          ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│     SCANNERS        │   │  SIGNAL PROCESSORS  │   │     EXECUTION       │
│                     │   │                     │   │                     │
│ - Equity Scanner    │   │ - TechnicalAnalyzer │   │ - TradeExecutor     │
│ - Crypto Scanner    │   │ - MLPredictor       │   │   (IB Integration)  │
│ - Forex Scanner     │   │ - OpportunityRanker │   │                     │
│ - Options Scanner   │   │                     │   │                     │
│ - Edgar Insider     │   │                     │   │                     │
│ - Options Flow      │   │                     │   │                     │
│ - Substack Scanner  │   │                     │   │                     │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
```

## Message Flow

```
Scanner → new_signal → Coordinator → TechnicalAnalyzer → signal_analyzed
                                          ↓
                            Coordinator → MLPredictor → ml_prediction
                                          ↓
                            Coordinator → OpportunityRanker → rankings
                                          ↓
                            [Auto-execute OR Manual approval]
                                          ↓
                            TradeExecutor → trade_executed
```

## Quick Start

### 1. Clone and Setup Environment

```bash
# Clone the repository
git clone <repo-url>
cd apex-s44-monitor

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy example config
cp .env.example .env

# Edit with your API keys
nano .env  # or your preferred editor
```

Required configuration:
- **Kraken API** - For crypto trading (UK-friendly exchange)
- **Telegram Bot** - For trade notifications
- **Interactive Brokers** - TWS or Gateway running for equity/options

### 3. Run the System

```bash
# Show current configuration
python main.py --config

# Run market scan only (no execution)
python main.py --scan

# Run with manual trade approval (recommended)
python main.py

# Run with paper trading
python main.py --paper

# Run with auto-execution (DANGEROUS - use with caution)
python main.py --auto
```

## Project Structure

```
apex-s44-monitor/
├── agents/                     # Multi-agent system
│   ├── coordinator.py         # Master orchestrator
│   ├── scanners/              # Market opportunity detection
│   │   ├── base_scanner.py
│   │   ├── equity_scanner.py
│   │   ├── crypto_scanner.py
│   │   ├── forex_scanner.py
│   │   ├── options_scanner.py
│   │   ├── edgar_insider_scanner.py
│   │   ├── options_flow_scanner.py
│   │   └── substack_scanner.py
│   ├── signals/               # Signal processing pipeline
│   │   ├── technical_analyzer.py
│   │   ├── ml_predictor.py
│   │   └── opportunity_ranker.py
│   └── execution/
│       └── trade_executor.py
├── core/                       # Framework foundations
│   ├── base_agent.py          # Abstract agent class
│   ├── models.py              # Data models
│   ├── broker.py              # IB integration
│   ├── adaptive_weights.py    # Learning system
│   └── model_manager.py       # ML lifecycle
├── config/
│   └── settings.py            # Pydantic configuration
├── knowledge/                  # Knowledge base
│   ├── ingest.py              # PDF/audio processing
│   ├── retriever.py           # Semantic search
│   └── books/                 # Trading books
├── strategies/
│   └── backtester.py          # Strategy validation
├── utils/
│   └── telegram_notifier.py   # Trade alerts
├── deploy/                     # VPS deployment
│   ├── setup-vps.sh
│   └── *.service              # Systemd services
├── main.py                    # Entry point
├── apex_monitor.py            # Streamlit dashboard
└── requirements.txt
```

## Agent Types

### Market Scanners
Autonomous agents that continuously scan markets for trading opportunities:

| Scanner | Market | Data Source |
|---------|--------|-------------|
| EquityScanner | Stocks, ETFs, SPACs | Yahoo Finance, IB |
| CryptoScanner | Cryptocurrency | Kraken, CCXT |
| ForexScanner | Foreign Exchange | IB, OANDA |
| OptionsScanner | Options | IB Options Chain |
| EdgarInsiderScanner | SEC Filings | SEC EDGAR |
| OptionsFlowScanner | Unusual Options | Market Data |
| SubstackScanner | Research Digests | RSS Feeds |

### Signal Processors
Pipeline agents that validate and score opportunities:

- **TechnicalAnalyzer** - Validates signals using 10+ indicators (RSI, MACD, ADX, Bollinger Bands, etc.)
- **MLPredictor** - Machine learning predictions (XGBoost, LightGBM)
- **OpportunityRanker** - Composite scoring based on risk/reward, confidence, and market context

### Trade Executor
Executes approved trades through Interactive Brokers with:
- Position sizing based on risk
- Stop-loss/take-profit management
- PDT compliance for US equities

## Risk Management

| Parameter | Default | Description |
|-----------|---------|-------------|
| Starting Capital | $3,000 | Initial trading capital |
| Max Position Size | 5% | Maximum per-trade allocation |
| Max Positions | 10 | Maximum concurrent positions |
| Max Daily Loss | 10% | Daily loss limit (stops trading) |
| Min Risk/Reward | 2:1 | Minimum acceptable R:R ratio |
| Min Confidence | 60% | Minimum signal confidence |

## Adaptive Learning

The system continuously learns from trade outcomes:
- Tracks win rate, profit factor, and R:R by market type
- Recalculates market weights every 24 hours
- Gradually shifts allocation toward better-performing markets (max 15%/day)

## Notifications

Telegram alerts for:
- Trade entries and exits
- Risk limit breaches
- System status updates
- Manual approval requests

## Deployment

### Local Development
```bash
./setup_mac.sh     # macOS
./setup_windows.bat # Windows
```

### 24/7 VPS Deployment
```bash
cd deploy
./setup-vps.sh
```

Creates systemd services for:
- Trading system
- IB Gateway
- Virtual display (Xvfb)

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=agents --cov=core

# Run specific test file
pytest tests/test_coordinator.py
```

## Web Dashboard

```bash
streamlit run apex_monitor.py
```

## License

Private - All Rights Reserved

## Disclaimer

This software is for educational purposes only. Trading involves substantial risk of loss. Past performance does not guarantee future results. Use at your own risk.

# Supporting Systems

## Overview

Beyond the core signal pipeline, APEX includes several supporting systems that enhance functionality:

1. **Knowledge Retriever** — TF-IDF search over trading books for psychology adjustments
2. **Telegram Notifier** — Real-time alerts and daily summaries
3. **Web Dashboard** — Visual interface for monitoring and control
4. **Data Cache** — Shared caching layer for market data

---

## 1. Knowledge Retriever

**Location**: `knowledge/retriever.py`

### Purpose

Searches ingested trading literature to find relevant wisdom for score adjustments. The system can penalize "greed trap" setups and reward disciplined entries based on knowledge base matches.

### Ingested Sources

- *Option Volatility and Pricing* — Natenberg
- *Market Wizards* series — Schwager
- *Trading in the Zone* — Douglas
- *Reminiscences of a Stock Operator* — Lefèvre
- Custom trading rules and notes

### TF-IDF Implementation

```python
class KnowledgeRetriever:
    def __init__(self, knowledge_dir: str = 'knowledge/data'):
        self.knowledge_dir = Path(knowledge_dir)
        self.documents: List[Dict] = []
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),    # Unigrams and bigrams
            max_features=5000,     # Limit vocabulary
            stop_words='english'
        )
        self.tfidf_matrix = None

        self._load_documents()
        self._build_index()

    def _load_documents(self) -> None:
        """Load and parse all documents"""
        for file_path in self.knowledge_dir.glob('*.txt'):
            with open(file_path, 'r') as f:
                content = f.read()

            # Split into chunks (paragraphs)
            chunks = content.split('\n\n')

            for i, chunk in enumerate(chunks):
                if len(chunk.strip()) > 50:  # Minimum length
                    self.documents.append({
                        'id': f"{file_path.stem}_{i}",
                        'source': file_path.stem,
                        'content': chunk.strip(),
                        'length': len(chunk)
                    })

    def _build_index(self) -> None:
        """Build TF-IDF index"""
        if not self.documents:
            return

        texts = [doc['content'] for doc in self.documents]
        self.tfidf_matrix = self.vectorizer.fit_transform(texts)

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Search for relevant documents"""
        if self.tfidf_matrix is None:
            return []

        # Vectorize query
        query_vector = self.vectorizer.transform([query])

        # Cosine similarity
        similarities = cosine_similarity(query_vector, self.tfidf_matrix)[0]

        # Get top results
        top_indices = similarities.argsort()[-top_k:][::-1]

        results = []
        for idx in top_indices:
            if similarities[idx] > 0.1:  # Minimum similarity threshold
                results.append({
                    **self.documents[idx],
                    'similarity': float(similarities[idx])
                })

        return results
```

### Psychology Queries

```python
# Greed trap detection
query = "overconfidence greed chasing momentum overbought"
matches = retriever.search(query)

if matches and signal['momentum_score'] > 0.8:
    # Apply penalty
    multiplier *= 0.92

# Discipline detection
query = "patience disciplined entry wait for setup"
matches = retriever.search(query)

if matches and signal['trend_score'] > 0.7:
    # Apply bonus
    multiplier *= 1.05
```

### Example Matches

**Query**: "greed trap overbought momentum"

**Match** (from Trading in the Zone):
> "The most dangerous phrase in trading is 'this time is different.' When a stock has run up 50% in a week, the prudent trader takes profits while the greedy trader adds to the position..."

**Similarity**: 0.73

---

## 2. Telegram Notifier

**Location**: `notifications/telegram.py`

### Purpose

Sends real-time notifications for:
- Trade entries and exits
- New opportunities (for manual approval)
- Daily P&L summaries
- Risk warnings
- System alerts

### Configuration

```python
class TelegramNotifier(BaseAgent):
    def __init__(self, config: Optional[Dict] = None):
        super().__init__("TelegramNotifier", config)

        self.bot_token = config.get('telegram_bot_token')
        self.chat_id = config.get('telegram_chat_id')
        self.enabled = bool(self.bot_token and self.chat_id)

        # Rate limiting
        self.last_message_time: Dict[str, datetime] = {}
        self.min_interval = 5  # seconds between same-type messages
```

### Message Types

#### Trade Entry

```python
async def _send_entry(self, payload: Dict) -> None:
    message = f"""
🟢 *TRADE ENTRY*

Symbol: `{payload['symbol']}`
Side: {payload['side'].upper()}
Quantity: {payload['quantity']}
Entry: ${payload['entry_price']:.2f}
Stop: ${payload['stop_loss']:.2f}
Target: ${payload['target_price']:.2f}
R:R: {payload['risk_reward']:.1f}:1
Strategy: {payload['strategy']}
"""
    await self._send(message)
```

#### Trade Exit

```python
async def _send_exit(self, payload: Dict) -> None:
    emoji = "💰" if payload['pnl'] > 0 else "📉"
    color = "🟢" if payload['pnl'] > 0 else "🔴"

    message = f"""
{emoji} *TRADE EXIT*

Symbol: `{payload['symbol']}`
Side: {payload['side'].upper()}
Entry: ${payload['entry_price']:.2f}
Exit: ${payload['exit_price']:.2f}
P&L: {color} ${payload['pnl']:.2f} ({payload['pnl_pct']:+.1f}%)
Reason: {payload['reason']}
"""
    await self._send(message)
```

#### Opportunity Alert

```python
async def _send_opportunity(self, payload: Dict) -> None:
    opp = payload['opportunity']

    message = f"""
⚡ *NEW OPPORTUNITY*

Symbol: `{opp['symbol']}`
Type: {opp['signal_type']}
Entry: ${opp['entry_price']:.2f}
Target: ${opp['target_price']:.2f}
Stop: ${opp['stop_loss']:.2f}
R:R: {opp['risk_reward_ratio']:.1f}:1
Confidence: {opp['ml_adjusted_confidence']:.0%}
Score: {opp['opportunity_score']:.2f}
Strategy: {opp.get('metadata', {}).get('strategy', 'unknown')}

Reply /approve {opp['id']} to execute
"""
    await self._send(message)
```

#### Daily Summary

```python
async def _send_daily_summary(self, payload: Dict) -> None:
    trades = payload['trades']
    winners = sum(1 for t in trades if t['pnl'] > 0)
    losers = len(trades) - winners
    total_pnl = sum(t['pnl'] for t in trades)

    emoji = "📈" if total_pnl > 0 else "📉"

    message = f"""
{emoji} *DAILY SUMMARY*

Date: {payload['date']}
Trades: {len(trades)}
Winners: {winners} ✅
Losers: {losers} ❌
Win Rate: {winners/len(trades)*100:.0f}%

Total P&L: ${total_pnl:.2f}
Capital: ${payload['capital']:.2f}
Day Return: {total_pnl/payload['capital']*100:+.2f}%
"""
    await self._send(message)
```

### Command Handling

```python
async def handle_command(self, command: str, args: List[str]) -> None:
    if command == '/approve':
        opportunity_id = args[0] if args else None
        if opportunity_id:
            await self._approve_opportunity(opportunity_id)

    elif command == '/reject':
        opportunity_id = args[0] if args else None
        if opportunity_id:
            await self._reject_opportunity(opportunity_id)

    elif command == '/status':
        await self._send_status()

    elif command == '/positions':
        await self._send_positions()

    elif command == '/close':
        symbol = args[0] if args else None
        if symbol:
            await self._close_position(symbol)
```

---

## 3. Web Dashboard

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Next.js       │────▶│   FastAPI       │────▶│   APEX Core    │
│   (Vercel)      │     │   (VPS)         │     │   (VPS)        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### FastAPI Backend

**Location**: `api/main.py`

```python
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="APEX Trading API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://apex-dashboard.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/positions")
async def get_positions():
    executor = get_trade_executor()
    return {
        "positions": [
            {
                "symbol": p.symbol,
                "side": p.side,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "pnl": p.pnl,
                "pnl_pct": p.pnl_pct
            }
            for p in executor.positions
        ]
    }

@app.get("/api/trades")
async def get_trades(limit: int = 50):
    executor = get_trade_executor()
    return {
        "trades": [
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                "strategy": t.metadata.get('strategy')
            }
            for t in executor.trade_history[-limit:]
        ]
    }

@app.get("/api/opportunities")
async def get_opportunities():
    coordinator = get_coordinator()
    return {
        "opportunities": coordinator.ranked_opportunities
    }

@app.get("/api/stats")
async def get_stats():
    executor = get_trade_executor()
    trades = executor.trade_history

    if not trades:
        return {"error": "No trade history"}

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]

    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": len(winners) / len(trades) if trades else 0,
        "total_pnl": sum(t.pnl for t in trades),
        "avg_winner": sum(t.pnl for t in winners) / len(winners) if winners else 0,
        "avg_loser": sum(t.pnl for t in losers) / len(losers) if losers else 0,
        "profit_factor": (
            sum(t.pnl for t in winners) / abs(sum(t.pnl for t in losers))
            if losers and sum(t.pnl for t in losers) != 0 else 0
        )
    }

@app.post("/api/close/{symbol}")
async def close_position(symbol: str):
    executor = get_trade_executor()
    position = next((p for p in executor.positions if p.symbol == symbol), None)

    if not position:
        raise HTTPException(404, f"No position for {symbol}")

    await executor._close_position(position, reason="manual_api")
    return {"status": "closed", "symbol": symbol}
```

### Next.js Frontend

Key components:

#### PositionsTable

```typescript
export function PositionsTable({ positions }: { positions: Position[] }) {
  return (
    <table className="w-full">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Side</th>
          <th>Qty</th>
          <th>Entry</th>
          <th>Current</th>
          <th>P&L</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((pos) => (
          <tr key={pos.symbol}>
            <td>{pos.symbol}</td>
            <td className={pos.side === 'long' ? 'text-green-500' : 'text-red-500'}>
              {pos.side.toUpperCase()}
            </td>
            <td>{pos.quantity}</td>
            <td>${pos.entry_price.toFixed(2)}</td>
            <td>${pos.current_price.toFixed(2)}</td>
            <td className={pos.pnl > 0 ? 'text-green-500' : 'text-red-500'}>
              ${pos.pnl.toFixed(2)} ({pos.pnl_pct.toFixed(1)}%)
            </td>
            <td>
              <button onClick={() => closePosition(pos.symbol)}>
                Close
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

#### PnLChart

```typescript
export function PnLChart({ trades }: { trades: Trade[] }) {
  const data = trades.map((t, i) => ({
    date: new Date(t.exit_time).toLocaleDateString(),
    cumulative: trades.slice(0, i + 1).reduce((sum, t) => sum + t.pnl, 0)
  }));

  return (
    <LineChart data={data}>
      <XAxis dataKey="date" />
      <YAxis />
      <Line type="monotone" dataKey="cumulative" stroke="#10B981" />
    </LineChart>
  );
}
```

---

## 4. Data Cache

**Location**: `core/data_cache.py`

### Purpose

Provides a shared caching layer for market data to:
- Prevent redundant API calls across agents
- Handle rate limiting centrally
- Reduce latency for frequently-accessed symbols

### Singleton Pattern

```python
class DataCache:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'DataCache':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
```

### Cache Structure

```python
def __init__(self):
    # Cache: {cache_key: (dataframe, fetch_time)}
    self._cache: Dict[str, Tuple[pd.DataFrame, datetime]] = {}
    self._cache_lock = asyncio.Lock()

    # Rate limiting
    self._last_fetch_time: Optional[datetime] = None
    self._min_fetch_interval = 0.5  # seconds

    # TTL settings
    self._ttl_seconds = {
        'intraday': 60,    # 1 minute for 1m/5m/15m data
        'daily': 300,      # 5 minutes for 1d data
        'options': 120     # 2 minutes for options chains
    }
```

### Symbol Normalization

```python
def _normalize_symbol(self, symbol: str, market_type: str) -> str:
    if market_type == 'forex':
        # EUR/USD -> EURUSD=X
        clean = symbol.replace('/', '')
        return f"{clean}=X" if not clean.endswith('=X') else clean

    elif market_type == 'crypto':
        # BTC/USDT -> BTC-USD
        return symbol.replace('/', '-').replace('USDT', 'USD')

    else:
        # Equity - uppercase
        return symbol.upper()
```

### Cache Lookup

```python
async def get_history(
    self,
    symbol: str,
    market_type: str = 'equity',
    period: str = '3mo',
    interval: str = '1d'
) -> Optional[pd.DataFrame]:

    cache_key = self._get_cache_key(symbol, market_type, period, interval)
    ttl = self._get_ttl(interval)

    # Check cache
    async with self._cache_lock:
        if cache_key in self._cache:
            df, fetch_time = self._cache[cache_key]
            if not self._is_expired(fetch_time, ttl):
                self._cache_hits += 1
                return df.copy()

    # Cache miss - fetch with rate limiting
    await self._rate_limit()

    normalized = self._normalize_symbol(symbol, market_type)
    ticker = yf.Ticker(normalized)

    # Run in executor to avoid blocking
    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(
        None,
        lambda: ticker.history(period=period, interval=interval)
    )

    if df is not None and not df.empty:
        df.columns = [c.lower() for c in df.columns]
        async with self._cache_lock:
            self._cache[cache_key] = (df.copy(), datetime.now())

    return df
```

### Statistics

```python
def get_stats(self) -> Dict:
    return {
        'cached_entries': len(self._cache),
        'total_fetches': self._fetch_count,
        'cache_hits': self._cache_hits,
        'hit_rate': (
            self._cache_hits / (self._cache_hits + self._fetch_count)
            if (self._cache_hits + self._fetch_count) > 0 else 0
        )
    }
```

---

## System Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                        APEX Core System                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Scanners   │──│ Validators  │──│  Executor   │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          │                                       │
│                          ▼                                       │
│                  ┌───────────────┐                               │
│                  │   DataCache   │◄──── All market data requests │
│                  └───────────────┘                               │
│                          │                                       │
│         ┌────────────────┼────────────────┐                      │
│         ▼                ▼                ▼                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Knowledge  │  │  Telegram   │  │   FastAPI   │              │
│  │  Retriever  │  │  Notifier   │  │   Backend   │              │
│  └─────────────┘  └──────┬──────┘  └──────┬──────┘              │
│                          │                │                      │
└──────────────────────────┼────────────────┼──────────────────────┘
                           │                │
                           ▼                ▼
                    ┌─────────────┐  ┌─────────────┐
                    │  Telegram   │  │   Next.js   │
                    │    App      │  │  Dashboard  │
                    └─────────────┘  └─────────────┘
```

---

## Future Improvements

### Knowledge Retriever
- Replace TF-IDF with sentence embeddings (MiniLM)
- Add real-time news sentiment analysis
- Include earnings calendar integration

### Telegram Notifier
- Add interactive buttons for approvals
- Include charts/images in notifications
- Voice alerts for critical notifications

### Web Dashboard
- Real-time WebSocket updates
- Mobile-responsive design
- Advanced charting with TradingView

### Data Cache
- Add Redis backend for persistence
- Implement cache warming on startup
- Add fallback data sources

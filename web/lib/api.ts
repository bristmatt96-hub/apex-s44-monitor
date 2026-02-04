const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface Position {
  symbol: string
  market_type: string
  quantity: number
  entry_price: number
  current_price: number
  entry_time: string
  stop_loss: number | null
  take_profit: number | null
  unrealized_pnl: number
  unrealized_pnl_pct: number
  market_value: number
  reasoning: string[]
  composite_score: number | null
  strategy: string | null
}

export interface PositionDetail extends Position {
  thesis_history: ThesisEvent[]
}

export interface ThesisEvent {
  timestamp: string
  event_type: string
  reasoning: string[]
  composite_score: number
  confidence: number
  notes: string | null
}

export interface PnLSummary {
  daily_pnl: number
  daily_pnl_pct: number
  ytd_pnl: number
  ytd_pnl_pct: number
  realized_today: number
  unrealized_today: number
  total_positions: number
  winning_positions: number
  losing_positions: number
}

export interface Opportunity {
  symbol: string
  market_type: string
  signal_type: string
  composite_score: number
  risk_reward: number
  confidence: number
  entry_price: number
  target_price: number
  stop_loss: number
  rank: number
  reasoning: string[]
  strategy: string | null
}

export interface SystemStatus {
  state: string
  trading_enabled: boolean
  auto_execute: boolean
  agents_active: number
  signals_raw: number
  signals_analyzed: number
  signals_ranked: number
  positions_count: number
  pending_trades: number
}

async function fetchAPI<T>(endpoint: string): Promise<T> {
  const res = await fetch(`${API_URL}${endpoint}`, {
    cache: 'no-store',
  })

  if (!res.ok) {
    throw new Error(`API error: ${res.status}`)
  }

  return res.json()
}

export const api = {
  getPositions: () => fetchAPI<Position[]>('/api/positions'),
  getPositionDetail: (symbol: string) => fetchAPI<PositionDetail>(`/api/positions/${symbol}`),
  getPnL: () => fetchAPI<PnLSummary>('/api/pnl'),
  getOpportunities: (limit = 10) => fetchAPI<Opportunity[]>(`/api/opportunities?limit=${limit}`),
  getStatus: () => fetchAPI<SystemStatus>('/api/status'),
}

'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { api, PositionDetail } from '@/lib/api'
import { ThesisTimeline } from '@/components/dashboard/thesis-timeline'
import { ArrowLeft, TrendingUp, TrendingDown, Target, Shield } from 'lucide-react'

function formatCurrency(value: number, showSign = true): string {
  const sign = showSign && value >= 0 ? '+' : ''
  return `${sign}$${Math.abs(value).toFixed(2)}`
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

export default function PositionDetailPage() {
  const params = useParams()
  const router = useRouter()
  const symbol = params.symbol as string

  const [position, setPosition] = useState<PositionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchPosition = async () => {
      try {
        setError(null)
        const data = await api.getPositionDetail(symbol)
        setPosition(data)
      } catch (err) {
        setError('Position not found')
        console.error('Position fetch error:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchPosition()
  }, [symbol])

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <div className="skeleton h-8 w-8 rounded" />
          <div className="skeleton h-6 w-24" />
        </div>
        <div className="card">
          <div className="skeleton h-8 w-32 mb-4" />
          <div className="skeleton h-24 w-full" />
        </div>
      </div>
    )
  }

  if (error || !position) {
    return (
      <div className="space-y-6">
        <button
          onClick={() => router.back()}
          className="flex items-center gap-2 text-foreground-muted hover:text-foreground tap-target"
        >
          <ArrowLeft size={20} />
          <span>Back</span>
        </button>
        <div className="card text-center py-8">
          <p className="text-accent-red">{error || 'Position not found'}</p>
        </div>
      </div>
    )
  }

  const isProfit = position.unrealized_pnl >= 0
  const pnlColor = isProfit ? 'text-accent-green' : 'text-accent-red'
  const PnlIcon = isProfit ? TrendingUp : TrendingDown

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.back()}
          className="p-2 rounded-lg bg-background-card hover:bg-background-elevated transition-colors tap-target"
        >
          <ArrowLeft size={20} />
        </button>
        <div>
          <h1 className="text-xl font-bold">{position.symbol}</h1>
          <p className="text-foreground-muted text-sm capitalize">
            {position.market_type} • {position.quantity} shares
          </p>
        </div>
      </div>

      {/* P&L Card */}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <div className={`p-2 rounded-lg ${isProfit ? 'bg-accent-green/20' : 'bg-accent-red/20'}`}>
            <PnlIcon size={24} className={pnlColor} />
          </div>
          <div>
            <p className={`text-2xl font-bold ${pnlColor}`}>
              {formatCurrency(position.unrealized_pnl)}
            </p>
            <p className={`text-sm ${pnlColor}`}>
              {formatPercent(position.unrealized_pnl_pct)}
            </p>
          </div>
        </div>

        {/* Price info */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-foreground-muted text-xs">Entry</p>
            <p className="font-semibold">${position.entry_price.toFixed(2)}</p>
          </div>
          <div>
            <p className="text-foreground-muted text-xs">Current</p>
            <p className="font-semibold">${position.current_price.toFixed(2)}</p>
          </div>
          {position.stop_loss && (
            <div className="flex items-center gap-2">
              <Shield size={14} className="text-accent-red" />
              <div>
                <p className="text-foreground-muted text-xs">Stop</p>
                <p className="font-semibold">${position.stop_loss.toFixed(2)}</p>
              </div>
            </div>
          )}
          {position.take_profit && (
            <div className="flex items-center gap-2">
              <Target size={14} className="text-accent-green" />
              <div>
                <p className="text-foreground-muted text-xs">Target</p>
                <p className="font-semibold">${position.take_profit.toFixed(2)}</p>
              </div>
            </div>
          )}
        </div>

        {/* Score badge */}
        {position.composite_score && (
          <div className="mt-4 pt-4 border-t border-border-muted">
            <div className="flex items-center justify-between">
              <span className="text-foreground-muted text-sm">Edge Score</span>
              <span className="px-3 py-1 bg-accent-blue/20 text-accent-blue rounded-full font-semibold">
                {position.composite_score.toFixed(1)}/10
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Entry Reasoning */}
      {position.reasoning && position.reasoning.length > 0 && (
        <div className="card">
          <h2 className="font-semibold mb-3">Entry Reasoning</h2>
          <ul className="space-y-2">
            {position.reasoning.map((reason, i) => (
              <li key={i} className="text-sm text-foreground-muted flex items-start gap-2">
                <span className="text-accent-green mt-0.5">•</span>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Thesis Evolution */}
      <div>
        <h2 className="font-semibold mb-3">Thesis Evolution</h2>
        <ThesisTimeline events={position.thesis_history} />
      </div>
    </div>
  )
}

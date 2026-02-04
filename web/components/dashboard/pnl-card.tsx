'use client'

import { PnLSummary } from '@/lib/api'

interface PnLCardProps {
  pnl: PnLSummary | null
  loading?: boolean
}

function formatCurrency(value: number): string {
  const absValue = Math.abs(value)
  if (absValue >= 1000) {
    return `${value >= 0 ? '' : '-'}$${(absValue / 1000).toFixed(1)}k`
  }
  return `${value >= 0 ? '+' : '-'}$${absValue.toFixed(2)}`
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

export function PnLCard({ pnl, loading }: PnLCardProps) {
  if (loading || !pnl) {
    return (
      <div className="card">
        <div className="flex justify-between">
          <div className="space-y-2">
            <div className="skeleton h-4 w-20" />
            <div className="skeleton h-8 w-32" />
            <div className="skeleton h-4 w-16" />
          </div>
          <div className="space-y-2 text-right">
            <div className="skeleton h-4 w-16 ml-auto" />
            <div className="skeleton h-6 w-24" />
            <div className="skeleton h-4 w-12 ml-auto" />
          </div>
        </div>
      </div>
    )
  }

  const dailyColor = pnl.daily_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'
  const ytdColor = pnl.ytd_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'

  return (
    <div className="card">
      <div className="flex justify-between items-start">
        {/* Daily P&L */}
        <div>
          <p className="text-foreground-muted text-sm font-medium">Today</p>
          <p className={`text-3xl font-bold ${dailyColor}`}>
            {formatCurrency(pnl.daily_pnl)}
          </p>
          <p className={`text-sm ${dailyColor}`}>
            {formatPercent(pnl.daily_pnl_pct)}
          </p>
        </div>

        {/* YTD P&L */}
        <div className="text-right">
          <p className="text-foreground-muted text-sm font-medium">YTD</p>
          <p className={`text-2xl font-semibold ${ytdColor}`}>
            {formatCurrency(pnl.ytd_pnl)}
          </p>
          <p className={`text-sm ${ytdColor}`}>
            {formatPercent(pnl.ytd_pnl_pct)}
          </p>
        </div>
      </div>

      {/* Quick stats */}
      <div className="flex justify-between mt-4 pt-4 border-t border-border-muted">
        <div className="text-center">
          <p className="text-foreground-muted text-xs">Positions</p>
          <p className="font-semibold">{pnl.total_positions}</p>
        </div>
        <div className="text-center">
          <p className="text-foreground-muted text-xs">Winning</p>
          <p className="font-semibold text-accent-green">{pnl.winning_positions}</p>
        </div>
        <div className="text-center">
          <p className="text-foreground-muted text-xs">Losing</p>
          <p className="font-semibold text-accent-red">{pnl.losing_positions}</p>
        </div>
        <div className="text-center">
          <p className="text-foreground-muted text-xs">Realized</p>
          <p className={`font-semibold ${pnl.realized_today >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
            {formatCurrency(pnl.realized_today)}
          </p>
        </div>
      </div>
    </div>
  )
}

'use client'

import Link from 'next/link'
import { ChevronRight } from 'lucide-react'
import { Position } from '@/lib/api'

interface PositionCardProps {
  position: Position
}

function formatCurrency(value: number): string {
  return `${value >= 0 ? '+' : ''}$${Math.abs(value).toFixed(2)}`
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

export function PositionCard({ position }: PositionCardProps) {
  const isProfit = position.unrealized_pnl >= 0
  const pnlColor = isProfit ? 'text-accent-green' : 'text-accent-red'

  return (
    <Link
      href={`/positions/${position.symbol}`}
      className="card flex items-center justify-between tap-target hover:bg-background-elevated transition-colors"
    >
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-lg">{position.symbol}</span>
          <span className="text-foreground-subtle text-xs uppercase">
            {position.market_type}
          </span>
        </div>
        <div className="text-foreground-muted text-sm">
          {position.quantity} @ ${position.entry_price.toFixed(2)}
        </div>
      </div>

      <div className="text-right mr-2">
        <div className={`font-semibold ${pnlColor}`}>
          {formatCurrency(position.unrealized_pnl)}
        </div>
        <div className={`text-sm ${pnlColor}`}>
          {formatPercent(position.unrealized_pnl_pct)}
        </div>
      </div>

      <ChevronRight size={20} className="text-foreground-subtle" />
    </Link>
  )
}

export function PositionCardSkeleton() {
  return (
    <div className="card flex items-center justify-between">
      <div className="flex-1">
        <div className="skeleton h-5 w-16 mb-2" />
        <div className="skeleton h-4 w-24" />
      </div>
      <div className="text-right mr-2">
        <div className="skeleton h-5 w-16 mb-1" />
        <div className="skeleton h-4 w-12" />
      </div>
    </div>
  )
}

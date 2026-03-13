'use client'

import { Position } from '@/lib/api'
import { PositionCard, PositionCardSkeleton } from './position-card'
import { Briefcase } from 'lucide-react'

interface PositionListProps {
  positions: Position[] | null
  loading?: boolean
}

export function PositionList({ positions, loading }: PositionListProps) {
  if (loading) {
    return (
      <div className="space-y-3">
        <PositionCardSkeleton />
        <PositionCardSkeleton />
        <PositionCardSkeleton />
      </div>
    )
  }

  if (!positions || positions.length === 0) {
    return (
      <div className="card flex flex-col items-center justify-center py-8 text-foreground-muted">
        <Briefcase size={32} className="mb-2 opacity-50" />
        <p>No open positions</p>
        <p className="text-sm">Opportunities will appear here when traded</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {positions.map((position) => (
        <PositionCard key={position.symbol} position={position} />
      ))}
    </div>
  )
}

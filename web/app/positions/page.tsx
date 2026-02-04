'use client'

import { useEffect, useState } from 'react'
import { api, Position } from '@/lib/api'
import { PositionList } from '@/components/dashboard/position-list'
import { RefreshCw } from 'lucide-react'

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[] | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchPositions = async () => {
    try {
      const data = await api.getPositions()
      setPositions(data)
    } catch (err) {
      console.error('Positions fetch error:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPositions()
    const interval = setInterval(fetchPositions, 30000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Positions</h1>
        <button
          onClick={() => { setLoading(true); fetchPositions() }}
          disabled={loading}
          className="p-2 rounded-lg bg-background-card tap-target"
        >
          <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <PositionList positions={positions} loading={loading} />
    </div>
  )
}

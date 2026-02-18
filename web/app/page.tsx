'use client'

import { useEffect, useState } from 'react'
import { api, Position, PnLSummary } from '@/lib/api'
import { PnLCard } from '@/components/dashboard/pnl-card'
import { PositionList } from '@/components/dashboard/position-list'
import { RefreshCw, Wifi, WifiOff } from 'lucide-react'

export default function DashboardPage() {
  const [pnl, setPnl] = useState<PnLSummary | null>(null)
  const [positions, setPositions] = useState<Position[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const fetchData = async () => {
    try {
      setError(null)
      const [pnlData, positionsData] = await Promise.all([
        api.getPnL(),
        api.getPositions(),
      ])
      setPnl(pnlData)
      setPositions(positionsData)
      setLastUpdated(new Date())
    } catch (err) {
      setError('Failed to load data')
      console.error('Dashboard fetch error:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()

    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleRefresh = () => {
    setLoading(true)
    fetchData()
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Dashboard</h1>
          {lastUpdated && (
            <p className="text-foreground-muted text-xs">
              Updated {lastUpdated.toLocaleTimeString()}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {error ? (
            <WifiOff size={18} className="text-accent-red" />
          ) : (
            <Wifi size={18} className="text-accent-green" />
          )}
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="p-2 rounded-lg bg-background-card hover:bg-background-elevated transition-colors tap-target"
          >
            <RefreshCw
              size={18}
              className={loading ? 'animate-spin text-accent-blue' : 'text-foreground-muted'}
            />
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg p-3 text-sm text-accent-red">
          {error}. Using cached data.
        </div>
      )}

      {/* P&L Card */}
      <PnLCard pnl={pnl} loading={loading && !pnl} />

      {/* Positions Section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-foreground-muted">
            Open Positions
            {positions && positions.length > 0 && (
              <span className="ml-2 text-foreground">({positions.length})</span>
            )}
          </h2>
        </div>
        <PositionList positions={positions} loading={loading && !positions} />
      </div>
    </div>
  )
}

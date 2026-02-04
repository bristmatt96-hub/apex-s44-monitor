'use client'

import { useEffect, useState } from 'react'
import { api, Opportunity } from '@/lib/api'
import { TrendingUp, RefreshCw } from 'lucide-react'

export default function OpportunitiesPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[] | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchOpportunities = async () => {
    try {
      const data = await api.getOpportunities(10)
      setOpportunities(data)
    } catch (err) {
      console.error('Opportunities fetch error:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchOpportunities()
    const interval = setInterval(fetchOpportunities, 30000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Opportunities</h1>
        <button
          onClick={() => { setLoading(true); fetchOpportunities() }}
          disabled={loading}
          className="p-2 rounded-lg bg-background-card tap-target"
        >
          <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {loading && !opportunities ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="card">
              <div className="skeleton h-5 w-20 mb-2" />
              <div className="skeleton h-4 w-full" />
            </div>
          ))}
        </div>
      ) : opportunities && opportunities.length > 0 ? (
        <div className="space-y-3">
          {opportunities.map((opp) => (
            <div key={opp.symbol} className="card">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{opp.symbol}</span>
                  <span className="text-xs text-foreground-subtle uppercase">{opp.market_type}</span>
                </div>
                <span className="px-2 py-0.5 bg-accent-blue/20 text-accent-blue rounded text-sm font-medium">
                  #{opp.rank}
                </span>
              </div>

              <div className="flex items-center gap-4 text-sm mb-3">
                <span className="text-foreground-muted">
                  Score: <span className="text-foreground font-medium">{opp.composite_score.toFixed(1)}</span>
                </span>
                <span className="text-foreground-muted">
                  R:R: <span className="text-accent-green font-medium">{opp.risk_reward.toFixed(1)}:1</span>
                </span>
                <span className="text-foreground-muted">
                  Conf: <span className="text-foreground font-medium">{(opp.confidence * 100).toFixed(0)}%</span>
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 text-xs mb-3">
                <div>
                  <span className="text-foreground-subtle">Entry</span>
                  <p className="font-medium">${opp.entry_price.toFixed(2)}</p>
                </div>
                <div>
                  <span className="text-foreground-subtle">Target</span>
                  <p className="font-medium text-accent-green">${opp.target_price.toFixed(2)}</p>
                </div>
                <div>
                  <span className="text-foreground-subtle">Stop</span>
                  <p className="font-medium text-accent-red">${opp.stop_loss.toFixed(2)}</p>
                </div>
              </div>

              {opp.reasoning && opp.reasoning.length > 0 && (
                <div className="pt-2 border-t border-border-muted">
                  {opp.reasoning.slice(0, 2).map((r, i) => (
                    <p key={i} className="text-xs text-foreground-muted flex items-start gap-1">
                      <span className="text-accent-green">•</span> {r}
                    </p>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="card flex flex-col items-center py-8 text-foreground-muted">
          <TrendingUp size={32} className="mb-2 opacity-50" />
          <p>No opportunities ranked yet</p>
        </div>
      )}
    </div>
  )
}

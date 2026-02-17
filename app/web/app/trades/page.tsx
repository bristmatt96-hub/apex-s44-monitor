'use client'

import { Clock } from 'lucide-react'

export default function TradesPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Trade History</h1>

      <div className="card flex flex-col items-center py-8 text-foreground-muted">
        <Clock size={32} className="mb-2 opacity-50" />
        <p>Trade history coming soon</p>
        <p className="text-sm">Past trades will appear here</p>
      </div>
    </div>
  )
}

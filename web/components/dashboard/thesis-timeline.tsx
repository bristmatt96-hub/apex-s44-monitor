'use client'

import { ThesisEvent } from '@/lib/api'

interface ThesisTimelineProps {
  events: ThesisEvent[]
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getEventIcon(type: string): string {
  switch (type) {
    case 'entry':
      return '🎯'
    case 'score_update':
      return '📊'
    case 'confluence_added':
      return '✨'
    case 'stop_adjusted':
      return '🛡️'
    default:
      return '•'
  }
}

function getEventLabel(type: string): string {
  switch (type) {
    case 'entry':
      return 'Entry'
    case 'score_update':
      return 'Score Update'
    case 'confluence_added':
      return 'New Signal'
    case 'stop_adjusted':
      return 'Stop Adjusted'
    default:
      return type
  }
}

export function ThesisTimeline({ events }: ThesisTimelineProps) {
  if (!events || events.length === 0) {
    return (
      <div className="text-foreground-muted text-sm py-4 text-center">
        No thesis history available
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {events.map((event, index) => (
        <div key={index} className="relative pl-6">
          {/* Timeline line */}
          {index < events.length - 1 && (
            <div className="absolute left-[9px] top-6 bottom-0 w-0.5 bg-border" />
          )}

          {/* Timeline dot */}
          <div className="absolute left-0 top-1 w-5 h-5 rounded-full bg-background-card border-2 border-accent-blue flex items-center justify-center text-xs">
            {getEventIcon(event.event_type)}
          </div>

          {/* Event content */}
          <div className="card-elevated">
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium text-sm">
                {getEventLabel(event.event_type)}
              </span>
              <span className="text-foreground-subtle text-xs">
                {formatDate(event.timestamp)}
              </span>
            </div>

            {/* Score badge */}
            <div className="inline-flex items-center gap-2 mb-3">
              <span className="px-2 py-0.5 bg-accent-blue/20 text-accent-blue rounded text-sm font-medium">
                Score: {event.composite_score.toFixed(1)}/10
              </span>
              {event.confidence > 0 && (
                <span className="text-foreground-muted text-xs">
                  {(event.confidence * 100).toFixed(0)}% confidence
                </span>
              )}
            </div>

            {/* Reasoning */}
            {event.reasoning && event.reasoning.length > 0 && (
              <ul className="space-y-1">
                {event.reasoning.map((reason, i) => (
                  <li key={i} className="text-sm text-foreground-muted flex items-start gap-2">
                    <span className="text-accent-green mt-0.5">•</span>
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            )}

            {/* Notes */}
            {event.notes && (
              <p className="text-xs text-foreground-subtle mt-2 italic">
                {event.notes}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

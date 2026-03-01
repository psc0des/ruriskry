/**
 * LiveLogPanel.jsx — slide-out panel showing real-time SSE scan progress.
 *
 * Opens when a scan is triggered and streams events from:
 *   GET /api/scan/{scanId}/stream
 *
 * Each event is displayed as a color-coded log line.  Events buffer in the
 * backend queue so connecting after scan start works fine — all prior events
 * are delivered immediately.
 *
 * Props:
 *   scanId    — UUID from POST /api/scan/*  (null hides the panel)
 *   agentType — "cost" | "monitoring" | "deploy"
 *   onClose   — callback to close the panel
 *   isOpen    — bool, controls visibility
 */

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { BASE } from '../api'

// ── Helpers ────────────────────────────────────────────────────────────────

const AGENT_LABELS = {
  cost:       'Cost Agent',
  monitoring: 'SRE Agent',
  deploy:     'Deploy Agent',
}

/**
 * Map an event type + optional decision to display properties.
 * Returns { icon, colour, label }.
 */
function eventStyle(event) {
  switch (event.event) {
    case 'scan_started':
      return { icon: '🚀', colour: 'text-slate-400', label: 'Started' }
    case 'discovery':
      return { icon: '🔍', colour: 'text-blue-400', label: 'Discovery' }
    case 'analysis':
      return { icon: '🧠', colour: 'text-purple-400', label: 'Analysis' }
    case 'reasoning':
      return { icon: '🤔', colour: 'text-purple-300', label: 'Reasoning' }
    case 'proposal':
      return { icon: '📋', colour: 'text-orange-400', label: 'Proposal' }
    case 'evaluation':
      return { icon: '⚖️', colour: 'text-yellow-400', label: 'Evaluation' }
    case 'verdict': {
      const d = event.decision?.toLowerCase()
      if (d === 'approved')  return { icon: '✅', colour: 'text-green-400',  label: 'Approved' }
      if (d === 'escalated') return { icon: '⚠️', colour: 'text-orange-400', label: 'Escalated' }
      if (d === 'denied')    return { icon: '🚫', colour: 'text-red-400',    label: 'Denied' }
      return { icon: '⚖️', colour: 'text-yellow-400', label: 'Verdict' }
    }
    // Backward compatibility for older event names during transition.
    case 'agent_returned':
      return { icon: '🔍', colour: 'text-blue-400', label: 'Discovery' }
    case 'evaluating':
      return { icon: '⚖️', colour: 'text-yellow-400', label: 'Evaluation' }
    case 'persisted':
      return { icon: '💾', colour: 'text-slate-500', label: 'Persisted' }
    case 'scan_complete':
      return { icon: '✔️', colour: 'text-green-300', label: 'Complete' }
    case 'scan_error':
      return { icon: '❌', colour: 'text-red-400', label: 'Error' }
    default:
      return { icon: '•', colour: 'text-slate-400', label: event.event }
  }
}

/** Format ISO timestamp to HH:MM:SS */
function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return ''
  }
}

// ── Log line ───────────────────────────────────────────────────────────────

function LogLine({ event }) {
  const { icon, colour, label } = eventStyle(event)
  const msg = event.message || JSON.stringify(event)

  return (
    <div className="flex items-start gap-2 py-1 border-b border-slate-800/60 last:border-0">
      {/* Timestamp */}
      <span className="text-slate-600 font-mono text-xs shrink-0 w-20 pt-0.5">
        {fmtTime(event.timestamp)}
      </span>
      {/* Icon */}
      <span className="shrink-0 text-sm">{icon}</span>
      {/* Message */}
      <span className={`text-xs font-mono leading-relaxed ${colour} break-words min-w-0`}>
        {msg}
      </span>
    </div>
  )
}

// ── Main panel ─────────────────────────────────────────────────────────────

export default function LiveLogPanel({ scanId, agentType, onClose, isOpen }) {
  const [events, setEvents]   = useState([])
  const [done, setDone]       = useState(false)
  const bottomRef             = useRef(null)
  const esRef                 = useRef(null)   // EventSource ref for cleanup

  // Reset and reconnect whenever scanId changes
  useEffect(() => {
    if (!scanId || !isOpen) return

    // Reset state for new scan
    setEvents([])
    setDone(false)

    // Close any previous EventSource
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }

    const es = new EventSource(`${BASE}/scan/${scanId}/stream`)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        setEvents(prev => [...prev, event])
        if (event.event === 'scan_complete' || event.event === 'scan_error') {
          setDone(true)
          es.close()
          esRef.current = null
        }
      } catch {
        // Ignore malformed events
      }
    }

    es.onerror = () => {
      // SSE connection dropped — mark done so user isn't stuck
      setDone(true)
      es.close()
      esRef.current = null
    }

    // Cleanup: close EventSource when component unmounts or scanId changes
    return () => {
      es.close()
      esRef.current = null
    }
  }, [scanId, isOpen])

  // Auto-scroll to bottom on each new event
  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [events])

  const handleClose = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    onClose()
  }, [onClose])

  if (!isOpen || !scanId) return null

  const agentLabel = AGENT_LABELS[agentType] ?? agentType

  return (
    <>
      {/* Backdrop — semi-transparent overlay */}
      <div
        className="fixed inset-0 bg-black/40 z-30"
        onClick={handleClose}
        aria-hidden="true"
      />

      {/* Slide-out panel — fixed right side */}
      <div className="fixed top-0 right-0 h-full w-full max-w-lg bg-slate-900 border-l border-slate-700 shadow-2xl z-40 flex flex-col">

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">
              {agentLabel} — Live Scan Log
            </h2>
            <p className="text-xs text-slate-500 font-mono mt-0.5">
              {scanId.slice(0, 8)}…
            </p>
          </div>
          <div className="flex items-center gap-3">
            {!done && (
              <span className="flex items-center gap-1.5 text-xs text-yellow-400 font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
                Scanning…
              </span>
            )}
            {done && (
              <span className="text-xs text-green-400 font-mono">Complete</span>
            )}
            <button
              onClick={handleClose}
              className="text-slate-500 hover:text-slate-200 transition-colors text-lg leading-none"
              title="Close log panel"
            >
              ✕
            </button>
          </div>
        </div>

        {/* ── Log body ── */}
        <div className="flex-1 overflow-y-auto px-4 py-3 font-mono">
          {events.length === 0 && (
            <p className="text-slate-600 text-xs text-center py-8">
              Connecting to scan stream…
            </p>
          )}
          {events.map((ev, i) => (
            <LogLine key={i} event={ev} />
          ))}
          {/* Invisible sentinel for auto-scroll */}
          <div ref={bottomRef} />
        </div>

        {/* ── Footer ── */}
        <div className="px-4 py-3 border-t border-slate-700 shrink-0">
          <p className="text-xs text-slate-600">
            {events.length} event{events.length !== 1 ? 's' : ''} received
            {!done && ' · streaming…'}
          </p>
        </div>
      </div>
    </>
  )
}

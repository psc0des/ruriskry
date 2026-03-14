/**
 * AgentControls.jsx — panel for manually triggering operational agent scans.
 *
 * Shows four buttons (Cost, SRE, Deploy, Run All) with a resource-group input.
 * Each button:
 *   1. Calls POST /api/scan/{type} → receives a scan_id immediately
 *   2. Opens a LiveLogPanel that streams real-time SSE events for that scan
 *   3. Polls GET /api/scan/{scan_id}/status every 2 s until status !== "running"
 *   4. Calls onScanComplete() so the parent re-fetches evaluations
 *
 * Refresh-resilience: on mount, fetches each agent's last run and restores
 * scanning state + polling for any scans still running on the backend.
 * This means refreshing the page no longer loses track of in-progress scans.
 *
 * Stop button: appears inline on each agent button while that scan is running.
 */

import React, { useState, useRef, useCallback, useEffect } from 'react'
import {
  triggerScan,
  triggerAllScans,
  fetchScanStatus,
  cancelScan,
  fetchAgentLastRun,
} from '../api'
import LiveLogPanel from './LiveLogPanel'
import { DollarSign, Activity, Shield, Zap, ClipboardList } from 'lucide-react'

// ── Helpers ────────────────────────────────────────────────────────────────

const AGENT_LABELS = {
  cost:       'Cost Scan',
  monitoring: 'Monitoring Scan',
  deploy:     'Deploy Scan',
}

const AGENT_DESCRIPTIONS = {
  cost:       'Find idle or over-provisioned resources',
  monitoring: 'Check health metrics + anomaly alerts',
  deploy:     'Audit NSG rules and config drift',
}

const AGENT_ICON_CMP = {
  cost:       DollarSign,
  monitoring: Activity,
  deploy:     Shield,
}

// Map agent type (cost/monitoring/deploy) → registered agent name used by the API
const AGENT_NAME = {
  cost:       'cost-optimization-agent',
  monitoring: 'monitoring-agent',
  deploy:     'deploy-agent',
}

// Status badge colours
function statusColour(status) {
  if (status === 'complete') return 'text-green-400'
  if (status === 'error')    return 'text-red-400'
  if (status === 'running')  return 'text-yellow-400'
  return 'text-slate-500'
}

// ── Spinner ────────────────────────────────────────────────────────────────

function Spinner() {
  return (
    <span
      className="inline-block w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"
      aria-hidden="true"
    />
  )
}

// ── Single agent button ────────────────────────────────────────────────────

function AgentButton({ type, scanning, lastStatus, onTrigger, onViewResults, scanId, onStop }) {
  const isRunning = scanning[type]

  return (
    <button
      onClick={() => onTrigger(type)}
      disabled={isRunning}
      className={`
        flex flex-col items-start gap-1 p-4 rounded-xl border transition-all text-left w-full
        ${isRunning
          ? 'border-yellow-500/40 bg-yellow-500/5 cursor-not-allowed opacity-80'
          : 'border-slate-600 bg-slate-700/50 hover:bg-slate-700 hover:border-slate-500 cursor-pointer'
        }
      `}
    >
      {/* Top row: icon + label + stop button + spinner */}
      <div className="flex items-center gap-2 w-full">
        {(() => { const Icon = AGENT_ICON_CMP[type]; return Icon ? <Icon className="w-4 h-4 text-slate-400 shrink-0" /> : null })()}
        <span className="flex-1 text-sm font-semibold text-slate-200">
          {AGENT_LABELS[type]}
        </span>
        {/* Stop button — only when this agent is scanning and we have its scan ID */}
        {isRunning && scanId && (
          <button
            onClick={(e) => { e.stopPropagation(); onStop(type) }}
            title="Cancel scan"
            className="shrink-0 text-[10px] font-mono text-red-400/70 hover:text-red-300 border border-red-500/20 hover:border-red-500/40 rounded px-1.5 py-0.5 transition-colors"
          >
            stop
          </button>
        )}
        {isRunning && <Spinner />}
      </div>

      {/* Description */}
      <p className="text-xs text-slate-500 leading-snug">{AGENT_DESCRIPTIONS[type]}</p>

      {/* Status line */}
      {lastStatus[type] && (
        lastStatus[type].status === 'complete' ? (
          // Clickable only when there are verdicts to show
          (lastStatus[type].evaluations_count ?? 0) > 0 ? (
            <span
              className="text-xs font-mono mt-0.5 text-green-400 underline decoration-dotted cursor-pointer hover:text-green-300"
              title="Click to view verdict details"
              onClick={(e) => { e.stopPropagation(); onViewResults?.() }}
            >
              Done · {lastStatus[type].evaluations_count} verdict(s) →
            </span>
          ) : (
            <span className="text-xs font-mono mt-0.5 text-slate-500">
              Done · 0 verdicts (no issues found)
            </span>
          )
        ) : (
          <p className={`text-xs font-mono mt-0.5 ${statusColour(lastStatus[type].status)}`}>
            {lastStatus[type].status === 'running' && 'Scanning…'}
            {lastStatus[type].status === 'error' && (
              lastStatus[type].scan_error?.includes('429') || lastStatus[type].scan_error?.includes('Too Many')
                ? 'Rate limited — wait 60s and retry'
                : lastStatus[type].scan_error
                  ? `Error: ${lastStatus[type].scan_error.slice(0, 80)}…`
                  : lastStatus[type].error
                    ? `Error: ${lastStatus[type].error}`
                    : 'Agent framework error'
            )}
          </p>
        )
      )}
    </button>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

/**
 * @param {{ onScanComplete: () => void, onViewVerdicts: () => void }} props
 *   onScanComplete — called when any scan finishes so the parent can re-fetch
 *   evaluation data and update the dashboard.
 */
export default function AgentControls({ onScanComplete, onViewVerdicts }) {
  // Default empty → API sends null resource_group → agents scan whole subscription.
  const [resourceGroup, setResourceGroup] = useState('')

  // Per-agent scanning state: { cost: bool, monitoring: bool, deploy: bool }
  const [scanning,   setScanning]   = useState({ cost: false, monitoring: false, deploy: false })

  // Per-agent last status from poll: { cost: obj|null, monitoring: ..., deploy: ... }
  const [lastStatus, setLastStatus] = useState({ cost: null, monitoring: null, deploy: null })

  // Per-agent scan IDs — needed for Stop button and log-panel re-open after refresh.
  const [scanIds, setScanIds] = useState({ cost: null, monitoring: null, deploy: null })

  // Live log panel state: which scan_id + agent_type to show.
  const [liveLog, setLiveLog] = useState({ open: false, scanId: null, agentType: null, scanEntries: null })

  // Store polling interval IDs so we can clear them when done.
  const pollRefs = useRef({ cost: null, monitoring: null, deploy: null })

  // Stable ref for onScanComplete — lets startPolling have [] deps so it
  // never changes reference, which keeps the mount-restore effect stable.
  const onScanCompleteRef = useRef(onScanComplete)
  useEffect(() => { onScanCompleteRef.current = onScanComplete }, [onScanComplete])

  // Guard so the mount-restore effect only runs once even if the component re-renders.
  const restoredRef = useRef(false)

  /**
   * Start polling GET /api/scan/{scanId}/status every 2 s.
   * Stops automatically when status !== "running".
   * Uses onScanCompleteRef so this callback never needs to be recreated.
   */
  const startPolling = useCallback((scanId, agentType) => {
    if (pollRefs.current[agentType]) clearInterval(pollRefs.current[agentType])

    pollRefs.current[agentType] = setInterval(async () => {
      try {
        const result = await fetchScanStatus(scanId)
        setLastStatus(prev => ({ ...prev, [agentType]: result }))

        if (result.status !== 'running') {
          clearInterval(pollRefs.current[agentType])
          pollRefs.current[agentType] = null
          setScanning(prev => ({ ...prev, [agentType]: false }))
          setScanIds(prev => ({ ...prev, [agentType]: null }))
          onScanCompleteRef.current()  // always calls the latest onScanComplete
        }
      } catch {
        // Network hiccup — keep polling
      }
    }, 2_000)
  }, [])  // stable — uses refs only, no captured props

  /**
   * On mount: check each agent's last run. If any are still running on the
   * backend (e.g. user refreshed mid-scan), restore scanning state, scan IDs,
   * and polling so the UI stays in sync without re-triggering the scan.
   */
  useEffect(() => {
    if (restoredRef.current) return
    restoredRef.current = true

    const types = ['cost', 'monitoring', 'deploy']

    Promise.allSettled(types.map(t => fetchAgentLastRun(AGENT_NAME[t])))
      .then(results => {
        const running = []

        results.forEach((r, i) => {
          if (r.status === 'fulfilled' && r.value?.status === 'running' && r.value?.scan_id) {
            const agentType = types[i]
            const scanId    = r.value.scan_id
            setScanning(prev  => ({ ...prev, [agentType]: true }))
            setLastStatus(prev => ({ ...prev, [agentType]: { status: 'running' } }))
            setScanIds(prev   => ({ ...prev, [agentType]: scanId }))
            startPolling(scanId, agentType)
            running.push({ scanId, agentType })
          }
        })

        // Restore "View Scan Log" button for the in-progress scan(s)
        if (running.length === 1) {
          setLiveLog({ open: false, scanId: running[0].scanId, agentType: running[0].agentType, scanEntries: null })
        } else if (running.length > 1) {
          setLiveLog({ open: false, scanId: null, agentType: 'all', scanEntries: running })
        }
      })
  }, [startPolling])

  /**
   * Trigger one agent scan, open live log, then begin polling for results.
   */
  const handleTrigger = useCallback(async (agentType) => {
    const rg = resourceGroup.trim() || null
    setScanning(prev => ({ ...prev, [agentType]: true }))
    setLastStatus(prev => ({ ...prev, [agentType]: { status: 'running' } }))
    try {
      const { scan_id } = await triggerScan(agentType, rg)
      setScanIds(prev => ({ ...prev, [agentType]: scan_id }))
      // Open the live log panel for this scan
      setLiveLog({ open: true, scanId: scan_id, agentType })
      startPolling(scan_id, agentType)
    } catch (err) {
      setScanning(prev => ({ ...prev, [agentType]: false }))
      setLastStatus(prev => ({ ...prev, [agentType]: { status: 'error', error: err.message } }))
    }
  }, [resourceGroup, startPolling])

  /**
   * Trigger all three scans simultaneously.
   * Opens a merged log panel showing all 3 agents' streams.
   */
  const handleTriggerAll = useCallback(async () => {
    const rg = resourceGroup.trim() || null
    setScanning({ cost: true, monitoring: true, deploy: true })
    setLastStatus({
      cost:       { status: 'running' },
      monitoring: { status: 'running' },
      deploy:     { status: 'running' },
    })
    try {
      const { scan_ids } = await triggerAllScans(rg)
      const types = ['cost', 'monitoring', 'deploy']
      // Track scan IDs per agent
      const newIds = {}
      types.forEach((t, i) => { newIds[t] = scan_ids[i] ?? null })
      setScanIds(newIds)
      // Open merged log panel showing all 3 agents' streams simultaneously
      if (scan_ids.length) {
        setLiveLog({
          open: true,
          scanId: null,
          agentType: 'all',
          scanEntries: scan_ids.map((id, i) => ({ scanId: id, agentType: types[i] })),
        })
      }
      scan_ids.forEach((scanId, i) => startPolling(scanId, types[i]))
    } catch (err) {
      setScanning({ cost: false, monitoring: false, deploy: false })
      setScanIds({ cost: null, monitoring: null, deploy: null })
      const errStatus = { status: 'error', error: err.message }
      setLastStatus({ cost: errStatus, monitoring: errStatus, deploy: errStatus })
    }
  }, [resourceGroup, startPolling])

  /**
   * Cancel an in-progress scan triggered from this panel.
   */
  const handleStop = useCallback(async (agentType) => {
    const scanId = scanIds[agentType]
    if (!scanId) return
    try { await cancelScan(scanId) } catch { /* ignore — backend may already be done */ }
    if (pollRefs.current[agentType]) {
      clearInterval(pollRefs.current[agentType])
      pollRefs.current[agentType] = null
    }
    setScanning(prev  => ({ ...prev, [agentType]: false }))
    setLastStatus(prev => ({ ...prev, [agentType]: { status: 'error', scan_error: 'Cancelled by user' } }))
    setScanIds(prev   => ({ ...prev, [agentType]: null }))
  }, [scanIds])

  const anyScanning = Object.values(scanning).some(Boolean)
  // Only say "all agents" when every agent is scanning (Run All was clicked)
  const allScanning = Object.values(scanning).every(Boolean)

  return (
    <>
      <section className="bg-slate-800 rounded-xl border border-slate-700 p-5">
        {/* ── Panel header ── */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
              Agent Controls
            </h2>
            <p className="text-xs text-slate-600 mt-0.5">
              Trigger ops agent scans directly from the dashboard
            </p>
          </div>

          {/* Global scanning badge */}
          {anyScanning && (
            <div className="flex items-center gap-1.5 text-xs text-yellow-400 font-mono">
              <Spinner />
              scanning…
            </div>
          )}
        </div>

        {/* ── Resource group input ── */}
        <div className="mb-4">
          <label className="block text-xs text-slate-500 mb-1" htmlFor="rg-input">
            Resource Group <span className="text-slate-600">(optional)</span>
          </label>
          <input
            id="rg-input"
            type="text"
            value={resourceGroup}
            onChange={e => setResourceGroup(e.target.value)}
            placeholder="e.g. ruriskry-prod-rg (leave empty to scan whole subscription)"
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-blue-500 transition-colors font-mono"
          />
        </div>

        {/* ── Individual agent buttons ── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
          {['cost', 'monitoring', 'deploy'].map(type => (
            <AgentButton
              key={type}
              type={type}
              scanning={scanning}
              lastStatus={lastStatus}
              scanId={scanIds[type]}
              onTrigger={handleTrigger}
              onStop={handleStop}
              onViewResults={() => {
                // Pick the first action_id from this scan's evaluations.
                const firstId = lastStatus[type]?.evaluations?.[0]?.action_id
                if (firstId) onViewVerdicts?.(firstId)
              }}
            />
          ))}
        </div>

        {/* ── View Log button — reopen a closed-but-still-active scan log ── */}
        {!liveLog.open && (liveLog.scanId || liveLog.scanEntries?.length) && (
          <button
            onClick={() => setLiveLog(prev => ({ ...prev, open: true }))}
            className="w-full mb-3 py-2 rounded-xl text-sm font-semibold border border-slate-500/60 bg-slate-700/30 hover:bg-slate-700/50 text-slate-300 hover:text-slate-100 cursor-pointer transition-all flex items-center justify-center gap-2"
          >
            <ClipboardList className="w-3.5 h-3.5" /> View Scan Log
          </button>
        )}

        {/* ── Run All button ── */}
        <button
          onClick={handleTriggerAll}
          disabled={anyScanning}
          className={`
            w-full py-2.5 rounded-xl text-sm font-semibold transition-all border
            ${anyScanning
              ? 'border-slate-600 bg-slate-700/40 text-slate-500 cursor-not-allowed'
              : 'border-blue-500/60 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 hover:text-blue-200 cursor-pointer'
            }
          `}
        >
          {anyScanning ? (
            <span className="flex items-center justify-center gap-2">
              <Spinner />
              {allScanning ? 'Running all agents…' : 'Scan in progress…'}
            </span>
          ) : (
            <span className="flex items-center justify-center gap-2">
              <Zap className="w-3.5 h-3.5" /> Run All Agents
            </span>
          )}
        </button>
      </section>

      {/* ── Live Log Panel (portaled to document.body) ── */}
      <LiveLogPanel
        scanId={liveLog.scanId}
        agentType={liveLog.agentType}
        scanEntries={liveLog.scanEntries}
        isOpen={liveLog.open}
        onClose={() => setLiveLog(prev => ({ ...prev, open: false }))}
      />
    </>
  )
}

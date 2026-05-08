/**
 * Admin.jsx — system configuration + admin actions.
 *
 * Two sections:
 *   1. System Configuration — mode, timeouts, feature flags (read from GET /api/config)
 *   2. Danger Zone — Reset button with typed DELETE confirmation
 */

import React, { useEffect, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Settings, AlertTriangle, Trash2, RefreshCw, CheckCircle, XCircle } from 'lucide-react'
import { fetchConfig, adminReset } from '../api'
import GlowCard from '../components/magicui/GlowCard'

// ── Helper components ──────────────────────────────────────────────────────

function ConfigRow({ label, value, mono = false }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-slate-800/60 last:border-0">
      <span className="text-xs text-slate-400">{label}</span>
      <span className={`text-xs font-medium text-slate-200 ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  )
}

function StatusBadge({ enabled }) {
  return enabled ? (
    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
      Enabled
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-slate-700/50 text-slate-500 border border-slate-700/60">
      <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
      Disabled
    </span>
  )
}

function ModeBadge({ mode }) {
  const isLive = mode === 'live'
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-0.5 rounded-full border ${
      isLive
        ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
        : 'bg-amber-500/10 text-amber-400 border-amber-500/25'
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full ${isLive ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
      {isLive ? 'Live (Azure)' : 'Mock'}
    </span>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

export default function Admin() {
  const { fetchAll, loggedInUser } = useOutletContext()
  const [config, setConfig] = useState(null)
  const [configError, setConfigError] = useState(null)
  const [resetting, setResetting] = useState(false)
  const [showResetModal, setShowResetModal] = useState(false)
  const [resetConfirmText, setResetConfirmText] = useState('')
  const [resetResult, setResetResult] = useState(null) // { ok: bool, message: string }
  const confirmInputRef = useRef(null)

  useEffect(() => {
    if (!loggedInUser) return
    fetchConfig()
      .then(setConfig)
      .catch(e => setConfigError(e.message))
  }, [loggedInUser])

  function openResetModal() {
    setResetConfirmText('')
    setResetResult(null)
    setShowResetModal(true)
    setTimeout(() => confirmInputRef.current?.focus(), 50)
  }

  async function handleReset() {
    if (resetConfirmText !== 'DELETE') return
    setResetting(true)
    setShowResetModal(false)
    try {
      const result = await adminReset()
      await fetchAll()
      setResetResult({ ok: true, message: `Reset complete — ${result.total} records deleted.` })
    } catch (e) {
      setResetResult({ ok: false, message: `Reset failed: ${e.message}` })
    } finally {
      setResetting(false)
    }
  }

  if (loggedInUser !== 'admin') {
    return (
      <div className="p-6 flex items-center justify-center min-h-64">
        <div className="text-center space-y-2">
          <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto" />
          <p className="text-sm font-semibold text-slate-200">Access Denied</p>
          <p className="text-xs text-slate-500">Administrator account required to view this page.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">

      {/* ── Page header ── */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center bg-slate-800 border border-slate-700">
          <Settings className="w-4.5 h-4.5 text-slate-400" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-100 leading-none">Admin</h1>
          <p className="text-xs text-slate-500 mt-0.5">System configuration and management</p>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">

      {/* ── System Configuration ── */}
      <GlowCard color="slate" intensity="low" className="p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <Settings className="w-4 h-4 text-slate-500" />
            System Configuration
          </h2>
          <button
            onClick={() => fetchConfig().then(setConfig).catch(e => setConfigError(e.message))}
            className="text-slate-600 hover:text-slate-300 transition-colors"
            title="Refresh config"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>

        {configError ? (
          <p className="text-xs text-rose-400">{configError}</p>
        ) : !config ? (
          <div className="space-y-2.5">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-8 bg-slate-800/60 rounded animate-pulse" />
            ))}
          </div>
        ) : (
          <div>
            <ConfigRow label="Mode" value={<ModeBadge mode={config.mode} />} />
            <ConfigRow label="LLM Timeout" value={`${config.llm_timeout}s`} mono />
            <ConfigRow label="LLM Concurrency" value={`${config.llm_concurrency_limit} parallel`} mono />
            <ConfigRow label="Execution Gateway" value={<StatusBadge enabled={config.execution_gateway_enabled} />} />
            <ConfigRow label="Live Topology" value={<StatusBadge enabled={config.use_live_topology} />} />
            <ConfigRow label="Version" value={`v${config.version}`} mono />
          </div>
        )}
      </GlowCard>

      {/* ── Danger Zone ── */}
      <GlowCard color="red" intensity="low" className="p-5" style={{ borderColor: 'rgba(239,68,68,0.2)' }}>
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="w-4 h-4 text-rose-500" />
          <h2 className="text-sm font-semibold text-rose-400">Danger Zone</h2>
        </div>

        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-200">Reset all local data</p>
            <p className="text-xs text-slate-500 mt-0.5 max-w-sm">
              Permanently deletes all local evaluation, execution, scan, and alert records.
              Cosmos DB data is never touched. The server stays running.
            </p>
          </div>
          <button
            onClick={openResetModal}
            disabled={resetting}
            className="shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-rose-500/10 border border-rose-500/30 text-rose-400 hover:bg-rose-500/20 hover:border-rose-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Trash2 className="w-4 h-4" />
            {resetting ? 'Resetting…' : 'Reset'}
          </button>
        </div>

        {/* Inline result notification */}
        {resetResult && (
          <div className={`mt-4 flex items-center gap-2 text-xs rounded-lg px-3 py-2 border ${
            resetResult.ok
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
          }`}>
            {resetResult.ok
              ? <CheckCircle className="w-3.5 h-3.5 shrink-0" />
              : <XCircle className="w-3.5 h-3.5 shrink-0" />}
            {resetResult.message}
          </div>
        )}
      </GlowCard>

      </div>

      {/* ── Typed DELETE confirmation modal ── */}
      {showResetModal && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={() => setShowResetModal(false)}>
          <div className="bg-slate-800 border border-rose-500/30 rounded-xl p-6 w-full max-w-sm shadow-2xl space-y-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
              <h3 className="text-sm font-semibold text-slate-200">Confirm data reset</h3>
            </div>
            <p className="text-xs text-slate-400">
              This will permanently delete all local scan, evaluation, execution, and alert records.
              <strong className="text-slate-200"> This cannot be undone.</strong>
            </p>
            <div className="space-y-1.5">
              <label className="text-xs text-slate-500">
                Type <span className="font-mono font-bold text-rose-400">DELETE</span> to confirm
              </label>
              <input
                ref={confirmInputRef}
                type="text"
                value={resetConfirmText}
                onChange={e => setResetConfirmText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && resetConfirmText === 'DELETE') handleReset() }}
                placeholder="DELETE"
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:border-rose-500/60"
              />
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowResetModal(false)} className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors">
                Cancel
              </button>
              <button
                onClick={handleReset}
                disabled={resetConfirmText !== 'DELETE'}
                className="px-4 py-1.5 text-sm bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/40 text-rose-300 hover:text-rose-200 rounded-lg font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Reset all data
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}

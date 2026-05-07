/**
 * Decision Quality page — Phase 36C
 *
 * Shows precision, recall, F1, and a confusion matrix derived from
 * decisions that have been correlated to real alerts (or confirmed safe
 * after the 7-day window). Switches to an empty-state card on a fresh
 * install (when no decisions have been labeled yet).
 */

import React, { useState, useEffect } from 'react'
import { fetchAccuracyMetrics } from '../api'
import { BarChart2, AlertCircle, RefreshCw } from 'lucide-react'

// ── helpers ──────────────────────────────────────────────────────────────────

function pct(v) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function num(v) {
  if (v == null) return '—'
  return v
}

// ── sub-components ───────────────────────────────────────────────────────────

function MetricCard({ label, value, description }) {
  return (
    <div className="rounded-xl p-5 flex flex-col gap-1"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
      <div className="text-xs text-slate-400 uppercase tracking-wider">{label}</div>
      <div className="text-3xl font-bold text-slate-100" style={{ fontFamily: 'var(--font-data)' }}>
        {value}
      </div>
      {description && <div className="text-xs text-slate-500 mt-1">{description}</div>}
    </div>
  )
}

function ConfusionMatrix({ tp, tn, fp, fn }) {
  const cell = (label, count, colorClass, desc) => (
    <div className={`rounded-lg p-4 flex flex-col items-center gap-1 ${colorClass}`}>
      <div className="text-2xl font-bold" style={{ fontFamily: 'var(--font-data)' }}>{count}</div>
      <div className="text-xs font-semibold">{label}</div>
      <div className="text-[11px] text-center opacity-70">{desc}</div>
    </div>
  )

  return (
    <div className="grid grid-cols-2 gap-3">
      {cell('True Positive', tp,
        'bg-emerald-900/30 border border-emerald-700/40 text-emerald-300',
        'ESCALATED/DENIED → incident occurred')}
      {cell('False Positive', fp,
        'bg-amber-900/20 border border-amber-700/30 text-amber-300',
        'ESCALATED/DENIED → no incident')}
      {cell('False Negative', fn,
        'bg-red-900/30 border border-red-700/40 text-red-300',
        'APPROVED → incident occurred')}
      {cell('True Negative', tn,
        'bg-slate-800/60 border border-slate-700/40 text-slate-300',
        'APPROVED → no incident')}
    </div>
  )
}

function VerdictRow({ verdict, data }) {
  const label = verdict.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())
  const total = data.incident_correlated + data.no_incident_observed
  const rate = data.rate != null ? pct(data.rate) : '—'
  return (
    <tr className="border-t border-slate-800">
      <td className="py-2 pr-4 text-sm text-slate-300">{label}</td>
      <td className="py-2 px-3 text-sm text-right" style={{ fontFamily: 'var(--font-data)' }}>{total}</td>
      <td className="py-2 px-3 text-sm text-right text-rose-400" style={{ fontFamily: 'var(--font-data)' }}>
        {data.incident_correlated}
      </td>
      <td className="py-2 px-3 text-sm text-right text-emerald-400" style={{ fontFamily: 'var(--font-data)' }}>
        {data.no_incident_observed}
      </td>
      <td className="py-2 pl-3 text-sm text-right text-slate-200" style={{ fontFamily: 'var(--font-data)' }}>
        {rate}
      </td>
    </tr>
  )
}

function EmptyStateCard() {
  return (
    <div className="max-w-xl mx-auto mt-16 text-center px-4">
      <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-5"
        style={{ background: 'linear-gradient(135deg,#1e3a5f,#0f2a47)', border: '1px solid rgba(56,189,248,0.2)' }}>
        <BarChart2 className="w-7 h-7 text-sky-400" />
      </div>
      <h2 className="text-xl font-semibold text-slate-100 mb-3">
        Decision quality metrics start in 7 days
      </h2>
      <p className="text-sm text-slate-400 leading-relaxed">
        RuriSkry tracks whether each verdict was followed by an incident on
        the same resource. After 7 days of operation, this card shows
        precision, recall, and F1 — the same metrics ML researchers use to
        grade a model.
      </p>
      <p className="text-sm text-slate-500 mt-3">
        Run a scan and let alerts fire to populate this dashboard.
      </p>
    </div>
  )
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function DecisionQuality() {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [days, setDays]       = useState(30)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAccuracyMetrics({ days })
      setMetrics(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [days]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">

      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100 tracking-tight">Decision Quality</h1>
          <p className="text-sm text-slate-400 mt-1">
            Accuracy metrics derived from alert correlation
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Window selector */}
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="text-sm bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button
            onClick={load}
            className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="flex items-center gap-2 text-sm text-rose-400 bg-rose-900/20 border border-rose-800/40 rounded-lg px-4 py-3 mb-6">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* ── Loading skeleton ── */}
      {loading && !metrics && (
        <div className="animate-pulse space-y-4">
          <div className="grid grid-cols-3 gap-4">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-28 rounded-xl bg-slate-800/60" />
            ))}
          </div>
          <div className="h-64 rounded-xl bg-slate-800/40" />
        </div>
      )}

      {/* ── Empty state ── */}
      {!loading && metrics?.empty_state && <EmptyStateCard />}

      {/* ── Populated view ── */}
      {!loading && metrics && !metrics.empty_state && (
        <div className="space-y-6">

          {/* Top metrics */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <MetricCard
              label="Precision"
              value={pct(metrics.precision)}
              description="Of ESCALATED/DENIED verdicts, what fraction predicted a real incident?"
            />
            <MetricCard
              label="Recall"
              value={pct(metrics.recall)}
              description="Of all incidents that occurred, what fraction was the system already flagging?"
            />
            <MetricCard
              label="F1 Score"
              value={pct(metrics.f1)}
              description="Harmonic mean of precision and recall — the balanced accuracy signal."
            />
          </div>

          {/* Confusion matrix + breakdown side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

            {/* Confusion matrix */}
            <div className="rounded-xl p-5"
              style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
              <h3 className="text-sm font-semibold text-slate-300 mb-4">Confusion Matrix</h3>
              <ConfusionMatrix
                tp={metrics.confusion_matrix.tp}
                tn={metrics.confusion_matrix.tn}
                fp={metrics.confusion_matrix.fp}
                fn={metrics.confusion_matrix.fn}
              />
              <p className="text-xs text-slate-500 mt-3">
                {metrics.total_labeled} labeled decisions in the last {metrics.window_days} days
              </p>
            </div>

            {/* Per-verdict breakdown */}
            <div className="rounded-xl p-5"
              style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
              <h3 className="text-sm font-semibold text-slate-300 mb-4">By Predicted Verdict</h3>
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="text-left text-xs text-slate-500 pb-2">Verdict</th>
                    <th className="text-right text-xs text-slate-500 pb-2 px-3">Total</th>
                    <th className="text-right text-xs text-rose-500/70 pb-2 px-3">Incident</th>
                    <th className="text-right text-xs text-emerald-500/70 pb-2 px-3">No incident</th>
                    <th className="text-right text-xs text-slate-500 pb-2 pl-3">Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(metrics.by_predicted_verdict).map(([verdict, data]) => (
                    <VerdictRow key={verdict} verdict={verdict} data={data} />
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-slate-500 mt-3">
                Rate = fraction of decisions in each verdict band followed by an incident.
              </p>
            </div>

          </div>
        </div>
      )}
    </div>
  )
}

/**
 * FewShotExamplesModal — Phase 38C
 *
 * Shows the few-shot examples retrieved and used when a borderline
 * governance decision was re-evaluated. Examples from the shipped seed
 * bank are tagged "(seed)" so operators can distinguish generic examples
 * from their own org's validated decisions.
 */

import React from 'react'
import { X, Sparkles } from 'lucide-react'

function VerdictChip({ verdict }) {
  const colors = {
    approved:    'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
    approved_if: 'bg-sky-900/40 text-sky-300 border-sky-700/40',
    escalated:   'bg-amber-900/40 text-amber-300 border-amber-700/40',
    denied:      'bg-red-900/40 text-red-300 border-red-700/40',
  }
  const v = (verdict || '').toLowerCase()
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${colors[v] ?? 'bg-slate-700 text-slate-300 border-slate-600'}`}>
      {verdict?.toUpperCase() ?? '—'}
    </span>
  )
}

function SeedTag() {
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded font-medium bg-teal-900/40 text-teal-400 border border-teal-700/40 cursor-help"
      title="From RuriSkry's curated seed bank — replaced over time as your team's overrides accumulate"
    >
      seed
    </span>
  )
}

export default function FewShotExamplesModal({ examples, onClose }) {
  if (!examples || examples.length === 0) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.7)' }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div
        className="w-full max-w-xl mx-4 rounded-2xl shadow-2xl"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-teal-400" />
            <h2 className="text-sm font-semibold text-slate-100">Few-Shot Calibration Examples</h2>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 transition-colors p-1 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Description */}
        <div className="px-5 pt-3 pb-2">
          <p className="text-xs text-slate-400 leading-relaxed">
            This verdict was borderline (SRI within ±3 of a decision boundary).
            The system retrieved these similar past decisions and used them to
            calibrate the final verdict.
          </p>
        </div>

        {/* Examples list */}
        <div className="px-5 pb-5 space-y-3 mt-1">
          {examples.map((ex, idx) => (
            <div
              key={ex.seed_id || ex.decision_id || idx}
              className="rounded-lg p-3 space-y-1.5"
              style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <VerdictChip verdict={ex.verdict} />
                {ex.is_seed && <SeedTag />}
                <span className="text-xs text-slate-400 font-mono">
                  {(ex.action_type || '').replace(/_/g, ' ')}
                </span>
                {ex.sri_composite != null && (
                  <span className="text-xs text-slate-500" style={{ fontFamily: 'var(--font-data)' }}>
                    SRI {typeof ex.sri_composite === 'number' ? ex.sri_composite.toFixed(1) : ex.sri_composite}
                  </span>
                )}
              </div>
              {ex.summary_text && (
                <p className="text-xs text-slate-400 leading-relaxed line-clamp-2">
                  {ex.summary_text}
                </p>
              )}
              {ex.outcome_reason && (
                <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">
                  {ex.outcome_reason}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

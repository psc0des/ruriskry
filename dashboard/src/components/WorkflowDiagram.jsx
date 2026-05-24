/**
 * WorkflowDiagram — "How RuriSkry Protects Production"
 *
 * Interactive product-facing diagram for the Overview page.
 * Click any stage to open a detail panel explaining what happens there.
 * No Mermaid dependency — pure React + SVG.
 */

import React, { useState, useCallback, useEffect } from 'react'
import GlowCard from './magicui/GlowCard'

// ── Layout constants ────────────────────────────────────────────────────────

const W       = 640   // diagram canvas width (px)
const NODE_W  = 248   // node box width
const NODE_H  = 58    // node box height
const CX      = W / 2 // horizontal centre
const NL      = CX - NODE_W / 2
const STEP    = NODE_H + 52  // vertical distance between node tops
const CANVAS_H = STEP * 5 + NODE_H + 16

// ── Node data ───────────────────────────────────────────────────────────────

const NODES = [
  {
    id: 'signal',
    label: 'Cloud Signal',
    sub: 'Change · Alert · Drift detected',
    accent: '#3b82f6',
    dot: '#60a5fa',
    badge: 'ENTRY POINT',
    badgeColor: '#1d4ed8',
    title: 'Cloud Signal / Proposed Change',
    what: 'A change request or alert detected in your cloud environment — a new deployment, a resource configuration drift, a scale-up proposal, or an incoming Azure Monitor alert.',
    how: 'Triggered by: automated scan (Ops Agents), incoming Azure Monitor webhook, or a manual operator trigger from the dashboard.',
    output: 'A ProposedAction with resource ID, action type, environment tier, and associated metadata — the starting point for governance.',
    note: 'Nothing is executed at this stage. The signal is captured and queued for evaluation.',
  },
  {
    id: 'ops-agents',
    label: 'Ops Agents',
    sub: 'Monitoring · Cost · Deploy',
    accent: '#0d9488',
    dot: '#2dd4bf',
    badge: '3 AGENTS',
    badgeColor: '#0f766e',
    title: 'Ops Agents: Monitoring, Cost, Deploy',
    what: 'Three specialized agents scan your infrastructure — Monitoring checks health signals and open alerts, Cost flags spend anomalies and under-utilized resources, Deploy reviews change risk and deployment history.',
    how: 'Each agent runs Azure API queries, reads live inventory, and applies Universal Rules Engine findings (34 rules) before generating proposed actions.',
    output: 'A list of ProposedActions per agent, each tagged with resource, action type, severity tier, and rule evidence.',
    note: 'Rule findings are injected before every LLM call to catch obvious violations early and reduce hallucination.',
  },
  {
    id: 'governance',
    label: 'Governance Review',
    sub: 'Blast Radius · Policy · Historical · Financial',
    accent: '#7c3aed',
    dot: '#a78bfa',
    badge: '4 AGENTS IN PARALLEL',
    badgeColor: '#6d28d9',
    title: 'Governance Review: Four Evaluation Dimensions',
    what: 'Four governance agents evaluate each proposed action simultaneously. Blast Radius checks how many resources would be affected. Policy validates compliance rules and security posture. Historical compares to past decisions and outcomes. Financial scores budget impact.',
    how: 'Each agent uses Claude with few-shot calibration examples to score its dimension 0–100. Borderline decisions trigger a re-run with additional context.',
    output: 'Four dimension scores (policy, blast_radius, historical, financial) plus policy violations, evidence citations, and condition suggestions.',
    note: 'All four run in parallel via the WorkflowBuilder graph. Results join at the scoring executor before the SRI is computed.',
  },
  {
    id: 'sri',
    label: 'Skry Risk Index',
    sub: 'SRI composite score + explanation',
    accent: '#d97706',
    dot: '#fbbf24',
    badge: 'COMPOSITE SCORE',
    badgeColor: '#b45309',
    title: 'Skry Risk Index (SRI)',
    what: 'A composite 0–100 risk score synthesizing all four governance dimensions. Low (≤25) is safe to auto-approve. Medium (26–60) may proceed with conditions. High (>60) is escalated to a human reviewer.',
    how: 'Weighted average of dimension scores, adjusted for critical policy violations. A critical violation floors the SRI at 80+ regardless of other scores.',
    output: 'SRI composite, per-dimension breakdown, triage tier (1/2/3), triage mode (deterministic/llm), and a human-readable explanation.',
    note: 'Tier 1 decisions (SRI ≤25, non-prod, isolated scope) bypass the LLM entirely — fully deterministic for speed and cost efficiency.',
  },
  {
    id: 'gate',
    label: 'Decision Gate',
    sub: 'Approved · Approved If · Escalated · Denied',
    accent: '#059669',
    dot: '#34d399',
    badge: '4 OUTCOMES',
    badgeColor: '#047857',
    title: 'Decision Gate: Four Outcomes',
    what: 'The governance verdict based on SRI, policy violations, and conditions. APPROVED proceeds automatically. APPROVED_IF proceeds once its conditions are satisfied. ESCALATED requires human sign-off in the Decisions page. DENIED blocks the action entirely.',
    how: 'The condition gate may promote APPROVED_IF → APPROVED when all conditions are already satisfied at decision time. Human operators can override any verdict.',
    output: 'A GovernanceVerdict with verdict enum, SRI scores, policy evidence, conditions, and execution gateway instructions.',
    note: 'Every human override is captured with a fingerprint hash (Override Feedback) and feeds the few-shot calibration bank over time.',
  },
  {
    id: 'execution',
    label: 'Controlled Execution',
    sub: 'Terraform PR · Agent Plan · Human Review · Blocked',
    accent: '#6366f1',
    dot: '#818cf8',
    badge: 'AUDITED',
    badgeColor: '#4338ca',
    title: 'Controlled Execution: Gated & Audited',
    what: 'Only APPROVED and APPROVED_IF (with conditions satisfied) decisions reach execution. The gateway selects the path: Terraform PR for infrastructure changes, Agent Plan for operational actions, Human Review queue for escalations, or Blocked for denials.',
    how: 'The az executor runs against a strict 13-pattern allowlist. Terraform PRs are opened via git automation. All executions are logged with before/after state.',
    output: 'Execution record with status (applied / pr_created / failed / blocked), duration, and full audit trail.',
    note: 'Rollback is available for supported action types. All records are viewable in the Decisions page drilldown.',
  },
]

// ── Component ───────────────────────────────────────────────────────────────

export default function WorkflowDiagram() {
  const [active, setActive] = useState(null)

  const close = useCallback(() => setActive(null), [])

  useEffect(() => {
    if (!active) return
    const onKey = (e) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, close])

  return (
    <>
      <style>{`
        @keyframes ruriflow { to { stroke-dashoffset: -26; } }
        @keyframes ruri-modal-in {
          from { opacity: 0; transform: translate(-50%, -47%); }
          to   { opacity: 1; transform: translate(-50%, -50%); }
        }
        .ruri-node { transition: all 0.18s; }
        .ruri-node:hover { filter: brightness(1.15); transform: translateY(-1px); }
        .ruri-node:focus-visible { outline: 2px solid #6366f1; outline-offset: 2px; }
      `}</style>

      <GlowCard color="purple" intensity="low">
        <div className="p-6">
          <div className="flex items-baseline justify-between mb-1">
            <h2 className="text-base font-semibold text-slate-100">
              How RuriSkry Protects Production
            </h2>
            <span className="text-[11px] text-slate-500 font-mono tracking-wide">
              Click any stage to explore
            </span>
          </div>
          <p className="text-xs text-slate-500 mb-5 leading-relaxed">
            Every proposed cloud change passes through this pipeline before anything is executed.
          </p>

          {/* ── Diagram canvas ── */}
          <div className="overflow-x-auto">
            <div style={{ position: 'relative', width: W, height: CANVAS_H, margin: '0 auto' }}>

              {/* Animated flow arrows */}
              <svg
                aria-hidden="true"
                style={{
                  position: 'absolute', inset: 0,
                  width: W, height: CANVAS_H,
                  pointerEvents: 'none', overflow: 'visible',
                }}
              >
                <defs>
                  <marker id="ruri-arrow" markerWidth="8" markerHeight="6"
                    refX="7" refY="3" orient="auto">
                    <polygon points="0 0,8 3,0 6" fill="#4f46e5" />
                  </marker>
                </defs>
                {NODES.slice(0, -1).map((node, i) => {
                  const y1 = STEP * i + NODE_H + 2
                  const y2 = STEP * (i + 1) - 6
                  return (
                    <path
                      key={node.id}
                      d={`M ${CX} ${y1} L ${CX} ${y2}`}
                      stroke="#4f46e5"
                      strokeWidth={2}
                      fill="none"
                      strokeDasharray="8 5"
                      markerEnd="url(#ruri-arrow)"
                      style={{
                        animation: 'ruriflow 0.8s linear infinite',
                        filter: 'drop-shadow(0 0 3px #4f46e5)',
                      }}
                    />
                  )
                })}
              </svg>

              {/* Stage nodes */}
              {NODES.map((node, i) => {
                const isActive = active?.id === node.id
                return (
                  <button
                    key={node.id}
                    className="ruri-node"
                    onClick={() => setActive(node)}
                    style={{
                      position: 'absolute',
                      left: NL,
                      top: STEP * i,
                      width: NODE_W,
                      height: NODE_H,
                      background: isActive
                        ? `linear-gradient(135deg, ${node.accent}40, ${node.accent}28)`
                        : 'rgba(15, 23, 42, 0.85)',
                      border: `1.5px solid ${isActive ? node.accent : 'rgba(51,65,85,0.55)'}`,
                      borderRadius: 10,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      padding: '0 16px',
                      cursor: 'pointer',
                      boxShadow: isActive
                        ? `0 4px 20px ${node.accent}44, inset 0 0 0 1px ${node.accent}30`
                        : 'none',
                    }}
                  >
                    <span style={{
                      width: 9, height: 9, borderRadius: '50%', flexShrink: 0,
                      background: node.dot,
                      boxShadow: `0 0 7px ${node.dot}`,
                    }} />
                    <div style={{ textAlign: 'left' }}>
                      <div style={{
                        fontFamily: 'var(--font-data)',
                        fontSize: '0.775rem',
                        fontWeight: 700,
                        color: isActive ? node.dot : '#e2e8f0',
                        whiteSpace: 'nowrap',
                      }}>
                        {node.label}
                      </div>
                      <div style={{
                        fontFamily: 'var(--font-ui)',
                        fontSize: '0.6rem',
                        color: isActive ? `${node.dot}99` : '#475569',
                        whiteSpace: 'nowrap',
                        marginTop: 2,
                      }}>
                        {node.sub}
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          <p className="text-center text-[11px] text-slate-700 font-mono mt-3 tracking-wide">
            ↑ Click any stage · Press Esc to close
          </p>
        </div>
      </GlowCard>

      {/* ── Detail modal ── */}
      {active && (
        <>
          {/* Backdrop */}
          <div
            aria-hidden="true"
            onClick={close}
            style={{
              position: 'fixed', inset: 0,
              background: 'rgba(2,6,23,0.72)',
              backdropFilter: 'blur(4px)',
              zIndex: 200,
            }}
          />

          {/* Panel */}
          <div
            role="dialog"
            aria-modal="true"
            aria-label={active.title}
            style={{
              position: 'fixed',
              top: '50%', left: '50%',
              transform: 'translate(-50%, -50%)',
              width: 520, maxWidth: '92vw',
              background: '#070f1e',
              border: '1px solid rgba(51,65,85,0.5)',
              borderLeft: `4px solid ${active.accent}`,
              borderRadius: 12,
              padding: '22px 26px',
              zIndex: 201,
              boxShadow: `0 24px 64px -12px rgba(2,6,23,0.9), 0 0 40px ${active.accent}22`,
              animation: 'ruri-modal-in 0.17s ease',
            }}
          >
            {/* Close */}
            <button
              onClick={close}
              aria-label="Close"
              style={{
                position: 'absolute', top: 12, right: 14,
                background: 'none', border: 'none', cursor: 'pointer',
                fontFamily: 'var(--font-data)', fontSize: '0.85rem',
                fontWeight: 700, color: '#475569',
                padding: '2px 7px', borderRadius: 4,
              }}
            >✕</button>

            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <span style={{
                width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                background: active.dot,
                boxShadow: `0 0 8px ${active.dot}`,
              }} />
              <h3 style={{
                fontFamily: 'var(--font-data)',
                fontSize: '0.9rem', fontWeight: 700,
                color: active.dot, margin: 0, lineHeight: 1.3,
              }}>
                {active.title}
              </h3>
              <span style={{
                marginLeft: 'auto', flexShrink: 0,
                fontFamily: 'var(--font-data)',
                fontSize: '0.575rem', fontWeight: 700,
                letterSpacing: '0.08em',
                padding: '3px 8px', borderRadius: 4,
                background: active.badgeColor, color: '#fff',
              }}>
                {active.badge}
              </span>
            </div>

            {/* Detail rows */}
            {[
              { label: 'What',   value: active.what   },
              { label: 'How',    value: active.how    },
              { label: 'Output', value: active.output },
            ].map(({ label, value }) => (
              <div key={label} style={{ display: 'flex', gap: 14, marginBottom: 11 }}>
                <span style={{
                  fontFamily: 'var(--font-data)', fontWeight: 700,
                  fontSize: '0.6rem', color: '#475569',
                  textTransform: 'uppercase', letterSpacing: '0.07em',
                  width: 50, flexShrink: 0, paddingTop: 2,
                }}>
                  {label}
                </span>
                <span style={{
                  fontFamily: 'var(--font-ui)',
                  fontSize: '0.8rem', color: '#94a3b8', lineHeight: 1.6,
                }}>
                  {value}
                </span>
              </div>
            ))}

            {/* Note */}
            <div style={{
              borderTop: '1px solid rgba(30,41,59,0.8)',
              paddingTop: 10, marginTop: 2,
              fontFamily: 'var(--font-ui)',
              fontSize: '0.775rem', color: '#334155',
              fontStyle: 'italic', lineHeight: 1.55,
            }}>
              {active.note}
            </div>
          </div>
        </>
      )}
    </>
  )
}

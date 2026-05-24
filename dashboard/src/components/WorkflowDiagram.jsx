/**
 * WorkflowDiagram — "How RuriSkry Protects Production"
 *
 * Accurate MAF WorkflowBuilder topology validated against source code:
 *
 *  • Two entry points:
 *      - Alert Trigger: webhook creates PENDING record; investigation is
 *        manually triggered from the Alerts page (NOT auto-investigated).
 *      - Agent Scan: /scan/all fires Cost + Monitoring + Deploy as three
 *        concurrent background tasks, each with its own scan_id.
 *        run_rules_prescan() runs INSIDE each agent during proposal generation.
 *
 *  • Per-proposal governance (WorkflowBuilder graph, Phase 33D):
 *      DispatchExecutor → fan-out ×4 (Blast Radius, Policy, Historical,
 *      Financial in parallel) → fan-in → ScoringExecutor → ConditionGateExecutor
 *      → GovernanceVerdict.
 *      After the verdict: _maybe_rerun_borderline() re-runs the full graph
 *      with few-shot examples if SRI is within ±3 of a tier boundary (20/30/60).
 *
 * Click any node to open a detail panel. Press Esc or click backdrop to close.
 */

import React, { useState, useCallback, useEffect } from 'react'
import GlowCard from './magicui/GlowCard'

// ── Layout ──────────────────────────────────────────────────────────────────

const W      = 760
const CX     = W / 2      // 380
const NODE_H = 52

const Y = {
  entry:     0,
  agents:    140,   // gap of 88 px for convergence + fan-out bus
  scoring:   274,   // gap of 82 px for fan-in bus
  condgate:  364,
  verdict:   454,
  execution: 544,
}
const CANVAS_H = Y.execution + NODE_H + 20   // 616

// Entry nodes — two side-by-side
const ENTRY_W  = 160
const ENTRY_CX = [190, 570]

// 4 governance agent nodes — 145 px wide, 15 px gaps
// centres: 140, 300, 460, 620
const AGENT_W  = 145
const AGENT_CX = [140, 300, 460, 620]
const AGENT_LX = AGENT_CX.map(cx => cx - AGENT_W / 2)

// Pipeline nodes (scoring … execution) — centred
const PIPE_W  = 212
const PIPE_LX = CX - PIPE_W / 2   // 274

// Fan-out bus: midpoint between entry bottom and agents top
const BUS_OUT_Y = Math.round((Y.entry + NODE_H + Y.agents) / 2)  // 96
// Fan-in  bus: midpoint between agents bottom and scoring top
const BUS_IN_Y  = Math.round((Y.agents + NODE_H + Y.scoring) / 2) // 233

// ── Node data ────────────────────────────────────────────────────────────────

const NODES = [

  // ─── ENTRY 1: Alert ──────────────────────────────────────────────────────
  {
    id: 'alert', group: 'entry',
    label: 'Alert Trigger',
    sub:   'Azure Monitor webhook → PENDING',
    accent: '#3b82f6', dot: '#60a5fa',
    badge: 'ENTRY 1', badgeColor: '#1d4ed8',
    title: 'Alert Trigger — Two-Step Process',
    what:   'Azure Monitor fires a webhook to POST /api/alerts. RuriSkry normalises the payload (_normalize_azure_alert_payload) and creates a PENDING alert record. Investigation does NOT start automatically.',
    how:    'An operator sees the pending alert in the Alerts page and clicks "Investigate", which calls POST /api/alerts/{id}/investigate. Only then does _run_alert_investigation() start as a background task, running the MonitoringAgent to generate proposals.',
    output: 'On investigate: MonitoringAgent.scan() returns proposals with rules evidence already injected (run_rules_prescan runs inside the agent). Each proposal then enters the governance pipeline.',
    note:   'The 30-minute cooldown window deduplicates repeat alerts on the same resource+metric. A Slack Block Kit card fires when the alert is received, and again when the verdict is issued.',
  },

  // ─── ENTRY 2: Agent Scan ─────────────────────────────────────────────────
  {
    id: 'scan', group: 'entry',
    label: 'Agent Scan',
    sub:   'Cost · Monitoring · Deploy',
    accent: '#3b82f6', dot: '#60a5fa',
    badge: 'ENTRY 2', badgeColor: '#1d4ed8',
    title: 'Ops Agent Scan (Cost, Monitoring, Deploy)',
    what:   'POST /api/scan/all creates three independent background tasks — one per agent — each with its own scan_id. They share a single pre-fetched inventory snapshot so all three see identical resource state.',
    how:    'Each agent\'s scan() calls run_rules_prescan() internally against the InventoryIndex before sending proposals to governance. Rules evidence is stamped on the ProposedAction at this point — inside the agent, not as a separate pipeline stage.',
    output: 'Three parallel scan runs (separate scan_ids). Each produces a list of ProposedActions with rule evidence pre-injected. Each proposal is then evaluated independently through the governance pipeline.',
    note:   'Cost uses Advisor + Cost Management APIs; Monitoring uses Metrics + Health + alerts feed; Deploy uses Resource Graph + deployment history. All three run concurrently as asyncio background tasks.',
  },

  // ─── GOVERNANCE AGENTS (fan-out, 4 parallel) ─────────────────────────────
  {
    id: 'blast', group: 'agents',
    label: 'Blast Radius',
    sub:   'Dependencies · scope',
    accent: '#7c3aed', dot: '#a78bfa',
    badge: 'PARALLEL', badgeColor: '#6d28d9',
    title: 'Blast Radius Agent',
    what:   'Evaluates how many resources, services, and dependencies would be affected if this action executes. Flags cross-referenced resources — is this NSG attached to 3 subnets? Is this VM in a scale set?',
    how:    'Queries the InventoryIndex (O(1) lookups) for upstream/downstream dependencies. Scores 0–100 based on affected resource count, service criticality tier, and whether the resource is referenced by others.',
    output: 'blast_radius_score (0–100) + list of affected resources + rationale string.',
    note:   'Runs in parallel with Policy, Historical, and Financial. The WorkflowBuilder DispatchExecutor fans out the same ProposedAction to all four simultaneously.',
  },
  {
    id: 'policy', group: 'agents',
    label: 'Policy',
    sub:   '15 policies · violations',
    accent: '#7c3aed', dot: '#a78bfa',
    badge: 'PARALLEL', badgeColor: '#6d28d9',
    title: 'Policy Agent',
    what:   'Validates the proposed action against all 15 active governance policies — security exposure, compliance tags, public access rules, encryption requirements, NSG direction, AKS node sizing, and more.',
    how:    'Cross-references the proposal against data/policies.json. Critical violations (e.g. POL-SEC-002: opening an NSG inbound rule) floor the SRI at 80+ regardless of other dimension scores. nsg_change_direction: "open" always triggers CRITICAL.',
    output: 'policy_score + list of PolicyViolation objects (each with policy_id, severity, reason, evidence).',
    note:   'A critical violation overrides the composite SRI regardless of the other three agents\' scores. This is the primary safety net for security-breaking changes.',
  },
  {
    id: 'historical', group: 'agents',
    label: 'Historical',
    sub:   'Past decisions · patterns',
    accent: '#7c3aed', dot: '#a78bfa',
    badge: 'PARALLEL', badgeColor: '#6d28d9',
    title: 'Historical Agent',
    what:   'Compares this proposal to past decisions on the same resource or action type. Was this resource denied before? Was this action type consistently approved? Identifies repetition patterns and anomalies.',
    how:    'Queries governance-decisions Cosmos container for 90 days of decisions matching this resource + action. Few-shot examples from the calibration bank calibrate scoring via cosine similarity (AI Search index: governance-decisions).',
    output: 'historical_score + past_decision_summary + consistency_indicator.',
    note:   'Context compounds over time. After 50+ labeled decisions, few-shot retrieval significantly improves consistency — borderline decisions are re-run with retrieved examples.',
  },
  {
    id: 'financial', group: 'agents',
    label: 'Financial',
    sub:   'Cost impact · Advisor',
    accent: '#7c3aed', dot: '#a78bfa',
    badge: 'PARALLEL', badgeColor: '#6d28d9',
    title: 'Financial Agent',
    what:   'Scores the budget impact of the proposed action. Will this increase cost? Is it a cost-saving action? Does it affect a resource flagged in Azure Advisor cost recommendations?',
    how:    'Uses Cost Management API data and Azure Advisor recommendations to estimate cost delta. Cost-saving actions score favourably; cost-increasing actions in high-spend subscriptions score high (risky).',
    output: 'financial_score + cost_delta_estimate + advisor_flag (bool).',
    note:   'Cost-saving actions (scale down, delete unused resources) can reduce the composite SRI even when other dimensions are borderline.',
  },

  // ─── SCORING (fan-in) ─────────────────────────────────────────────────────
  {
    id: 'scoring', group: 'pipeline',
    label: 'Scoring  ·  SRI',
    sub:   'Fan-in · composite 0–100 · borderline re-run',
    accent: '#d97706', dot: '#fbbf24',
    badge: 'FAN-IN', badgeColor: '#b45309',
    title: 'Scoring Executor — SRI Composite (Fan-in)',
    what:   'The scoring_executor receives all four agent results only after ALL four complete (fan-in barrier). It computes the composite SRI 0–100 and stamps the triage tier.',
    how:    'Weights: Policy 35%, Blast Radius 25%, Historical 20%, Financial 20%. clamp_score() applies ±30 guardrail. Critical policy violations override the composite to 80+. triage_tier (1/2/3) and triage_mode (deterministic/llm) are stamped here.',
    output: 'sri_composite + per-dimension scores + triage_tier + triage_mode + human-readable SRI explanation.',
    note:   'After the full workflow completes, _maybe_rerun_borderline() re-runs the entire governance graph if SRI is within ±3 of a tier boundary (20, 30, or 60) — injecting the top-3 few-shot examples from the calibration bank. Borderline re-run is non-fatal; original verdict is used if retrieval fails.',
  },

  // ─── CONDITION GATE ───────────────────────────────────────────────────────
  {
    id: 'condgate', group: 'pipeline',
    label: 'Condition Gate',
    sub:   'APPROVED_IF → APPROVED?',
    accent: '#059669', dot: '#34d399',
    badge: 'PROMOTION CHECK', badgeColor: '#047857',
    title: 'Condition Gate Executor (WorkflowBuilder)',
    what:   'Before issuing the final verdict, the condition_gate_executor checks whether any APPROVED_IF conditions are already satisfied at decision time. If all conditions pass, the verdict is promoted to APPROVED automatically — no human needed.',
    how:    'Each condition (e.g. "ensure backup is enabled before proceeding") is evaluated against current resource state. All must pass for automatic promotion. Uses ctx.yield_output(verdict) to emit the final GovernanceVerdict — this is the WorkflowBuilder output executor.',
    output: 'Final GovernanceVerdict with resolved verdict enum, condition_satisfied flags, few_shot_examples_used count, and execution gateway instructions.',
    note:   'Human operators can also satisfy conditions manually via POST /api/decisions/{id}/satisfy-condition from the Decisions page, triggering the same promotion logic.',
  },

  // ─── VERDICT ──────────────────────────────────────────────────────────────
  {
    id: 'verdict', group: 'pipeline',
    label: 'Governance Verdict',
    sub:   'Approved · Approved If · Escalated · Denied',
    accent: '#059669', dot: '#34d399',
    badge: '4 OUTCOMES', badgeColor: '#047857',
    title: 'Governance Verdict: Four Outcomes',
    what:   'The final decision persisted to governance-decisions: APPROVED (auto-proceed), APPROVED_IF (proceed once conditions met), ESCALATED (requires human sign-off), DENIED (blocked and logged).',
    how:    'APPROVED flows straight to the Execution Gateway. ESCALATED appears in the Decisions page pending queue. DENIED triggers a Slack Block Kit notification with the full evidence trail.',
    output: 'GovernanceVerdict record with verdict enum, all scores, policy violations, conditions, few_shot_examples_used, execution_id, and timestamp.',
    note:   'Every human override (force_execute, dismiss_escalated, satisfy_condition, reverse_denial) is captured with a fingerprint hash (Phase 35A) and feeds the few-shot calibration bank over time.',
  },

  // ─── EXECUTION GATEWAY ────────────────────────────────────────────────────
  {
    id: 'execution', group: 'pipeline',
    label: 'Execution Gateway',
    sub:   'Terraform PR · az CLI · Human Review · Blocked',
    accent: '#6366f1', dot: '#818cf8',
    badge: 'AUDITED', badgeColor: '#4338ca',
    title: 'Execution Gateway: Gated & Audited',
    what:   'Only APPROVED verdicts reach execution. The gateway selects the path: Terraform PR for infrastructure changes, az CLI execution (13-pattern allowlist) for operational actions, Human Review queue for escalations, or Blocked for denials.',
    how:    'The az executor runs with Managed Identity (_ensure_az_authenticated() calls az login --identity once per process, cached with a module-level flag). Terraform PRs are opened via git automation. All executions are persisted to governance-executions with before/after state.',
    output: 'Execution record with status (applied / pr_created / failed / blocked), duration, stdout/stderr, and rollback metadata.',
    note:   'Sticky sessions (sticky_sessions_affinity = "sticky" in Container App Terraform) are required for SSE streaming of the scan live log to work correctly across multiple replicas.',
  },
]

// ── Reusable node box ────────────────────────────────────────────────────────

function NodeBox({ node, isActive, onClick, width, style }) {
  return (
    <button
      className="ruri-node"
      onClick={() => onClick(node)}
      title={node.title}
      style={{
        position: 'absolute',
        width,
        height: NODE_H,
        background: isActive
          ? `linear-gradient(135deg, ${node.accent}3a, ${node.accent}22)`
          : 'rgba(8,14,28,0.92)',
        border: `1.5px solid ${isActive ? node.accent : 'rgba(51,65,85,0.5)'}`,
        borderRadius: 9,
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '0 12px',
        cursor: 'pointer',
        boxShadow: isActive ? `0 4px 22px ${node.accent}40` : 'none',
        outline: 'none',
        overflow: 'hidden',
        ...style,
      }}
    >
      <span style={{
        width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
        background: node.dot, boxShadow: `0 0 6px ${node.dot}`,
      }} />
      <div style={{ textAlign: 'left', overflow: 'hidden', minWidth: 0 }}>
        <div style={{
          fontFamily: 'var(--font-data)', fontSize: '0.72rem', fontWeight: 700,
          color: isActive ? node.dot : '#e2e8f0',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>
          {node.label}
        </div>
        <div style={{
          fontFamily: 'var(--font-ui)', fontSize: '0.575rem',
          color: isActive ? `${node.dot}99` : '#475569',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 2,
        }}>
          {node.sub}
        </div>
      </div>
    </button>
  )
}

// ── SVG connections ──────────────────────────────────────────────────────────

function Connections() {
  const ani     = { animation: 'ruriflow 0.85s linear infinite' }
  const aniSlow = { animation: 'ruriflow 1.1s linear infinite' }

  return (
    <svg
      aria-hidden="true"
      style={{
        position: 'absolute', inset: 0, width: W, height: CANVAS_H,
        pointerEvents: 'none', overflow: 'visible',
      }}
    >
      <defs>
        {[
          ['a-blue',   '#3b82f6'],
          ['a-purple', '#7c3aed'],
          ['a-amber',  '#d97706'],
          ['a-green',  '#059669'],
          ['a-indigo', '#6366f1'],
        ].map(([id, fill]) => (
          <marker key={id} id={id} markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">
            <polygon points="0 0,7 2.5,0 5" fill={fill} />
          </marker>
        ))}
      </defs>

      {/* ── Entry beziers converge at fan-out bus centre ── */}
      {ENTRY_CX.map((cx, i) => (
        <path
          key={i}
          d={`M ${cx} ${Y.entry + NODE_H} C ${cx} ${BUS_OUT_Y - 18},${CX} ${BUS_OUT_Y - 18},${CX} ${BUS_OUT_Y}`}
          stroke="#3b82f6" strokeWidth={1.8} fill="none" strokeDasharray="7 5"
          style={{ ...ani, filter: 'drop-shadow(0 0 2px #3b82f660)' }}
        />
      ))}

      {/* ── Fan-out horizontal bus ── */}
      <line
        x1={AGENT_CX[0]} y1={BUS_OUT_Y}
        x2={AGENT_CX[3]} y2={BUS_OUT_Y}
        stroke="#7c3aed" strokeWidth={1.6} strokeDasharray="5 4"
        style={{ ...aniSlow, filter: 'drop-shadow(0 0 2px #7c3aed55)' }}
      />
      <text
        x={AGENT_CX[3] + 7} y={BUS_OUT_Y + 4}
        fill="#6d28d9" fontFamily="JetBrains Mono,monospace" fontSize="9" fontWeight="700"
      >
        ×4 PARALLEL
      </text>

      {/* ── Fan-out drops → each agent ── */}
      {AGENT_CX.map(cx => (
        <line
          key={cx}
          x1={cx} y1={BUS_OUT_Y}
          x2={cx} y2={Y.agents - 5}
          stroke="#7c3aed" strokeWidth={1.6} strokeDasharray="6 4"
          markerEnd="url(#a-purple)"
          style={{ ...ani, filter: 'drop-shadow(0 0 2px #7c3aed55)' }}
        />
      ))}

      {/* ── Agent rises → fan-in bus ── */}
      {AGENT_CX.map(cx => (
        <line
          key={cx}
          x1={cx} y1={Y.agents + NODE_H}
          x2={cx} y2={BUS_IN_Y}
          stroke="#d97706" strokeWidth={1.6} strokeDasharray="6 4"
          style={{ ...ani, filter: 'drop-shadow(0 0 2px #d9770655)' }}
        />
      ))}

      {/* ── Fan-in horizontal bus ── */}
      <line
        x1={AGENT_CX[0]} y1={BUS_IN_Y}
        x2={AGENT_CX[3]} y2={BUS_IN_Y}
        stroke="#d97706" strokeWidth={1.6} strokeDasharray="5 4"
        style={{ ...aniSlow, filter: 'drop-shadow(0 0 2px #d9770655)' }}
      />
      <text
        x={AGENT_CX[3] + 7} y={BUS_IN_Y + 4}
        fill="#b45309" fontFamily="JetBrains Mono,monospace" fontSize="9" fontWeight="700"
      >
        AGGREGATED
      </text>

      {/* ── Fan-in bus centre → Scoring ── */}
      <line
        x1={CX} y1={BUS_IN_Y}
        x2={CX} y2={Y.scoring - 5}
        stroke="#d97706" strokeWidth={1.8} strokeDasharray="7 5"
        markerEnd="url(#a-amber)"
        style={{ ...ani, filter: 'drop-shadow(0 0 2px #d9770660)' }}
      />

      {/* ── Borderline re-run loop: Scoring left edge → curves back to bus ── */}
      <path
        d={`M ${PIPE_LX} ${Y.scoring + NODE_H / 2} C ${PIPE_LX - 52} ${Y.scoring + NODE_H / 2},${PIPE_LX - 52} ${BUS_OUT_Y},${CX - 4} ${BUS_OUT_Y}`}
        stroke="#f59e0b" strokeWidth={1.4} fill="none" strokeDasharray="4 4"
        markerEnd="url(#a-amber)"
        style={{ filter: 'drop-shadow(0 0 2px #f59e0b55)' }}
      />
      <text
        x={PIPE_LX - 62} y={Y.scoring - 6}
        fill="#92400e" fontFamily="JetBrains Mono,monospace" fontSize="8" fontWeight="700"
        textAnchor="end"
      >
        borderline
      </text>
      <text
        x={PIPE_LX - 62} y={Y.scoring + 5}
        fill="#92400e" fontFamily="JetBrains Mono,monospace" fontSize="8" fontWeight="700"
        textAnchor="end"
      >
        re-run ±3
      </text>

      {/* ── Pipeline straight arrows ── */}
      {[
        [Y.scoring,  Y.condgate,  '#059669', 'a-green'],
        [Y.condgate, Y.verdict,   '#059669', 'a-green'],
        [Y.verdict,  Y.execution, '#6366f1', 'a-indigo'],
      ].map(([yFrom, yTo, color, marker], i) => (
        <line
          key={i}
          x1={CX} y1={yFrom + NODE_H}
          x2={CX} y2={yTo - 5}
          stroke={color} strokeWidth={1.8} strokeDasharray="7 5"
          markerEnd={`url(#${marker})`}
          style={{ ...ani, filter: `drop-shadow(0 0 2px ${color}55)` }}
        />
      ))}
    </svg>
  )
}

// ── Detail modal ─────────────────────────────────────────────────────────────

function DetailModal({ node, onClose }) {
  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(2,6,23,0.75)',
          backdropFilter: 'blur(4px)',
          zIndex: 200,
        }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={node.title}
        style={{
          position: 'fixed',
          top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 520, maxWidth: '92vw',
          background: '#060d1b',
          border: '1px solid rgba(51,65,85,0.45)',
          borderLeft: `4px solid ${node.accent}`,
          borderRadius: 12,
          padding: '22px 26px',
          zIndex: 201,
          boxShadow: `0 28px 64px -12px rgba(2,6,23,0.95), 0 0 48px ${node.accent}1a`,
          animation: 'ruri-modal-in 0.16s ease',
        }}
      >
        {/* Close — slate-400 for visibility */}
        <button
          onClick={onClose}
          aria-label="Close"
          className="ruri-close"
          style={{
            position: 'absolute', top: 11, right: 13,
            background: 'none', border: 'none', cursor: 'pointer',
            fontFamily: 'var(--font-data)', fontSize: '0.9rem',
            fontWeight: 700, color: '#94a3b8',
            padding: '3px 8px', borderRadius: 4,
            lineHeight: 1, transition: 'all 0.12s',
          }}
        >✕</button>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, paddingRight: 32 }}>
          <span style={{
            width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
            background: node.dot, boxShadow: `0 0 8px ${node.dot}`,
          }} />
          <h3 style={{
            fontFamily: 'var(--font-data)', fontSize: '0.875rem',
            fontWeight: 700, color: node.dot, margin: 0, lineHeight: 1.3,
          }}>
            {node.title}
          </h3>
          <span style={{
            marginLeft: 'auto', flexShrink: 0,
            fontFamily: 'var(--font-data)', fontSize: '0.575rem',
            fontWeight: 700, letterSpacing: '0.08em',
            padding: '3px 8px', borderRadius: 4,
            background: node.badgeColor, color: '#fff',
          }}>
            {node.badge}
          </span>
        </div>

        {[
          { label: 'What',   value: node.what   },
          { label: 'How',    value: node.how    },
          { label: 'Output', value: node.output },
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
              fontFamily: 'var(--font-ui)', fontSize: '0.8rem',
              color: '#94a3b8', lineHeight: 1.6,
            }}>
              {value}
            </span>
          </div>
        ))}

        <div style={{
          borderTop: '1px solid rgba(30,41,59,0.7)',
          paddingTop: 10, marginTop: 2,
          fontFamily: 'var(--font-ui)', fontSize: '0.775rem',
          color: '#334155', fontStyle: 'italic', lineHeight: 1.55,
        }}>
          {node.note}
        </div>
      </div>
    </>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function WorkflowDiagram() {
  const [active, setActive] = useState(null)
  const close = useCallback(() => setActive(null), [])

  useEffect(() => {
    if (!active) return
    const onKey = (e) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, close])

  const entryNodes    = NODES.filter(n => n.group === 'entry')
  const agentNodes    = NODES.filter(n => n.group === 'agents')
  const pipelineNodes = NODES.filter(n => n.group === 'pipeline')

  return (
    <>
      <style>{`
        @keyframes ruriflow { to { stroke-dashoffset: -26; } }
        @keyframes ruri-modal-in {
          from { opacity: 0; transform: translate(-50%, -47%); }
          to   { opacity: 1; transform: translate(-50%, -50%); }
        }
        .ruri-node { transition: border-color 0.15s, box-shadow 0.15s, background 0.15s; }
        .ruri-node:hover {
          border-color: rgba(99,102,241,0.55) !important;
          background: rgba(12,20,40,0.98) !important;
        }
        .ruri-node:focus-visible { outline: 2px solid #6366f1; outline-offset: 2px; }
        .ruri-close:hover { background: rgba(51,65,85,0.5) !important; color: #f1f5f9 !important; }
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
            Two entry paths feed the MAF WorkflowBuilder pipeline. Four governance agents
            evaluate each proposal in parallel — their results aggregate at the scoring
            executor before a verdict is issued.
          </p>

          <div className="overflow-x-auto">
            <div style={{ position: 'relative', width: W, height: CANVAS_H, margin: '0 auto' }}>

              <Connections />

              {/* Entry nodes */}
              {entryNodes.map((node, i) => (
                <NodeBox
                  key={node.id}
                  node={node}
                  isActive={active?.id === node.id}
                  onClick={setActive}
                  width={ENTRY_W}
                  style={{ left: ENTRY_CX[i] - ENTRY_W / 2, top: Y.entry }}
                />
              ))}

              {/* 4 parallel governance agents */}
              {agentNodes.map((node, i) => (
                <NodeBox
                  key={node.id}
                  node={node}
                  isActive={active?.id === node.id}
                  onClick={setActive}
                  width={AGENT_W}
                  style={{ left: AGENT_LX[i], top: Y.agents }}
                />
              ))}

              {/* Pipeline nodes */}
              {pipelineNodes.map(node => (
                <NodeBox
                  key={node.id}
                  node={node}
                  isActive={active?.id === node.id}
                  onClick={setActive}
                  width={node.id === 'execution' ? PIPE_W + 28 : PIPE_W}
                  style={{
                    left: node.id === 'execution' ? CX - (PIPE_W + 28) / 2 : PIPE_LX,
                    top: Y[node.id],
                  }}
                />
              ))}

            </div>
          </div>

          <p className="text-center text-[11px] text-slate-700 font-mono mt-3 tracking-wide">
            ↑ Click any stage · Press Esc to close
          </p>
        </div>
      </GlowCard>

      {active && <DetailModal node={active} onClose={close} />}
    </>
  )
}

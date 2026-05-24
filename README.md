# 🛡️ RuriSkry — AI-Powered Ops. AI-Governed Decisions.

> Ops agents propose cloud changes. Governance agents score the risk. Humans approve what reaches production.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Azure](https://img.shields.io/badge/cloud-Azure-0078D4.svg)](https://azure.microsoft.com)
[![AI Dev Days Hackathon 2026](https://img.shields.io/badge/hackathon-AI%20Dev%20Days%202026-purple.svg)](https://microsoft.com)

<p align="center">
  <img src="docs/ruriskry-demo.gif" alt="RuriSkry demo walkthrough" width="100%">
</p>

<p align="center">
  <a href="docs/videos/ruriskry-full-walkthrough.webm"><strong>Watch the full archived live-deployment walkthrough</strong></a>
</p>

RuriSkry is two systems in one: a team of **Azure AI Cloud Ops Agents** (Monitoring, Cost, Deploy) that propose and plan cloud changes — and an **AI Change Advisory Board** (Policy, Blast Radius, Historical, Financial) that simulates, scores, and adjudicates every proposed action *before* it touches production. Ops agents supply the changes; the CAB decides whether they ship.

Born at the Microsoft AI Dev Days Hackathon 2026, RuriSkry has since matured into a fully async, enterprise-ready governance engine with live Azure topology analysis, a 34-rule deterministic rules engine, durable audit trails (Cosmos DB), Slack alerting, explainable AI verdicts with counterfactual analysis, operator override feedback capture, and 1462 automated tests.

---

## The Problem

In every enterprise I've worked in over 8 years as a Cloud Engineer and SRE, one principle has been non-negotiable: **no production change ships without a four-eyes review**. Every infrastructure change goes through a **CAB — a Change Advisory Board**. Someone senior reviews the blast radius, checks for policy violations, looks at historical incidents, and signs off. That's the standard.

But when AI agents start managing infrastructure — **who reviews them?**

Sure, there are guardrails — token limits, permission scopes, hardcoded rules. But guardrails only say what an agent **can't** do. Nobody's simulating what happens **if** it does. Nobody's scoring the blast radius before the action runs.

And the consequences are real:

- A **cost optimization agent** deletes a disaster recovery VM to save $800/month — not knowing it just compromised a compliance requirement
- An **SRE agent** restarts a payment service — unaware that identical restarts caused cascade failures three times before
- A **deployment agent** opens a network port — accidentally exposing internal admin dashboards to the public internet

Today's tooling offers two options: **block actions with static rules** or **monitor after execution**. Nobody simulates outcomes before allowing an agent to act.

## The Solution — A CAB for AI

RuriSkry is a **governance engine** that acts as the **Change Advisory Board for AI agents**. Just like a human CAB reviews production changes across risk, compliance, precedent, and cost — RuriSkry does the same for every AI agent action, automatically. Before any action executes, it runs through four specialized governance agents that produce a branded **Skry Risk Index (SRI™)**:

```
+-------------------------------------------------------+
|              SKRY RISK INDEX (SRI)                    |
|                                                       |
|  SRI:Infrastructure  [#####.........]  32/100         |
|  SRI:Policy          [######........]  40/100         |
|  SRI:Historical      [##............]  15/100         |
|  SRI:Cost            [#.............]  10/100         |
|                      ----------------                 |
|  SRI Composite                         72/100         |
|                                                       |
|  Verdict:  DENIED                                     |
|  Reason:   Critical policy violation +                |
|            high blast radius on prod chain            |
+-------------------------------------------------------+
```

### SRI™ Dimensions

| Dimension | What It Measures | Agent |
|-----------|-----------------|-------|
| **SRI:Infrastructure** | Blast radius — downstream resources and services affected | Blast Radius Simulation Agent |
| **SRI:Policy** | Governance compliance — policy violations and severity | Policy & Compliance Agent |
| **SRI:Historical** | Precedent risk — similarity to past incidents | Historical Pattern Agent |
| **SRI:Cost** | Financial volatility — projected cost change and over-optimization | Financial Impact Agent |

### Decision Thresholds

- **SRI ≤ 25, no contextual conditions** → ✅ Auto-Approve — low risk, execute immediately
- **SRI ≤ 25, contextual conditions present** → 🔒 Conditional Approval (APPROVED_IF) — approved in principle, gated on structured conditions (maintenance window, blast-radius sign-off, metric threshold). Auto-checkable conditions are polled every 60 s by a background watcher; human-required conditions need explicit sign-off via API. Conditions can auto-promote to APPROVED at evaluation time if all are already met.
- **SRI 26–60** → ⚠️ Escalate — moderate risk, human review required
- **SRI > 60** → ❌ Deny — high risk, action blocked with explanation
- **Any non-overridden HIGH policy violation** → ⚠️ Escalate floor — prevents score dilution where low blast radius / cost dims push composite below 25 despite a HIGH policy flag
- **Non-overridden CRITICAL violation** → ❌ Deny
- **LLM-overridden CRITICAL violation** → ⚠️ Escalate — LLM context noted but human approval (VP/CAB) is still mandatory; LLM cannot auto-approve CRITICAL policies

---

## Architecture

<p align="center">
  <img src="docs/architecture-diagram.png" alt="RuriSkry System Architecture" width="100%">
</p>

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Agent-to-Agent Protocol | A2A SDK (`a2a-sdk`) + `agent-framework-a2a` | Network protocol for agent discovery and task streaming |
| Agent Orchestration | Microsoft Agent Framework (`agent-framework-core`) | Multi-agent coordination + configurable LLM tool calls |
| Model Intelligence | Azure OpenAI Foundry — gpt-4.1-mini (default) | LLM reasoning for each governance agent (configurable via `foundry_model` in tfvars) |
| MCP Interception | FastMCP stdio server | Intercept actions from Claude Desktop / MCP hosts |
| Infrastructure Graph | Azure Resource Graph + Azure Retail Prices API | Real-time dependency topology (KQL + tags) and SKU cost data |
| Incident Search | Azure AI Search (BM25) | Historical incident similarity |
| Audit DB | Azure Cosmos DB (SQL API) | Governance decisions + agent registry + scan-run records |
| Secret Management | Azure Key Vault + `DefaultAzureCredential` | Runtime secret resolution |
| Dashboard | React + Vite + FastAPI | 9-page governance UI with SSE real-time streaming, custom design system, animated components |
| Slack Notifications | Slack Incoming Webhook (Block Kit attachments) | Real-time alerts for DENIED/ESCALATED verdicts, Azure Monitor alerts, agent scan failures, and inventory staleness |
| Azure Monitor → RuriSkry | Alert Processing Rule (APR) scoped to target subscription + `azurerm_monitor_action_group.ruriskry` (`terraform-core`) | One APR routes ALL current and future alert rules automatically — no per-rule wiring. Alerts POST to `/api/alert-trigger` → `pending` record → **Investigate** → `MonitoringAgent` → governance verdict → Alerts tab |
| Decision Explanation Engine | `DecisionExplainer` — LLM summary + counterfactual analysis | Click any verdict row → 6-section drilldown with "what would change this?" analysis |

---

## Key Features

> Each feature below is summarized for a quick read. Deep-dive design and data flow live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Intelligent Governance — LLM as Decision Maker
All 4 governance agents use gpt-4.1-mini as an **active decision maker**, not a narrator. The
deterministic rule engine produces a **baseline score**; the LLM then receives the full policy
definitions, the ops agent's reasoning, and the baseline — and adjusts the score up or down
with explicit justification. A guardrail bounds adjustments to ±30 points so hallucination
cannot dominate. This enables **remediation intent detection**: when an ops agent is fixing a
security issue (not creating one), the LLM recognises that intent and reduces the risk score
rather than blocking the fix.

### Decision Quality Metrics (Phases 36 + 38)
RuriSkry measures its own accuracy and improves on borderline cases.

- **Decision-Incident Linkage (Phase 36)** — every Azure Monitor alert is correlated against recent decisions on the same resource (7-day window, exact `resource_id` match); a 6-hour background labeler marks aged decisions that saw no incident. The **Decision Quality** dashboard page surfaces precision, recall, and F1 from labeled decisions, with a clean empty-state on day 1.
- **Few-Shot Seed Bank (Phase 38)** — 40 curated examples ship in `data/few_shot_seed_bank.json` and load into an Azure AI Search vector index (`text-embedding-3-small`, 1536-dim) on startup. When a verdict is **borderline** (composite SRI within ±3 of a boundary), all 4 agents re-run with the top-3 most-similar examples injected, improving calibration. Real validated decisions outrank seeds over time; a "Few-shot calibrated" badge + modal appears on borderline verdicts.

### Universal Rules Engine (Phase 40)
Before any LLM call, a **34-rule deterministic engine** scans every resource against a self-registering `@rule` registry, in three layers:

- **Layer 1 — Universal rules (UNIV-*, 26):** fire on any resource sharing a common property (public network access, TLS version, managed identity, missing tags, unattached disks, single-region data services), covering all 311+ Azure types without per-type special-casing.
- **Layer 2 — Microsoft API enrichment:** Azure Advisor, Defender for Cloud, Policy Insights, Resource Health (require `Reader`+). `GET /api/coverage/status` reports which APIs are accessible; 403s surface the missing role in an amber `CoverageStatusBanner`.
- **Layer 3 — Type-aware rules (TYPE-*, 8):** inspect service-specific schema — NSG SSH/RDP exposure, AKS autoscaler, SQL failover groups, Cosmos auto-failover, App Service client certs.

Findings are injected into the LLM prompt as confirmed context — the LLM **enriches and validates**, it doesn't discover. Post-scan, proposals dedup by `(resource_id, action_type)` with rule-derived entries winning; a `coverage_manifest` is stored in every scan record.

### Two-Layer Intelligence
Operational agents aren't blind action-proposers — they query **real Azure data** (Resource Graph tags, Monitor metrics, NSG rules, activity logs) via gpt-4.1-mini before proposing. RuriSkry then provides an **independent second opinion** from 4 governance agents in parallel: the ops agent catches obvious risks; RuriSkry catches what it missed.

All three operational agents use a **four-phase detection pipeline**: (0) rules engine runs deterministically against the full inventory; (1) Microsoft APIs (Advisor, Defender, Policy) confirm findings; (2) the LLM investigates with real metric data and open-ended KQL across all 200+ Azure types; (3) a post-scan safety net auto-proposes anything the LLM skipped. Each phase dedups against the others — rule-derived proposals win.

- **Monitoring Agent** — 6-step proactive scan (VM power state, DB/container health, observability gaps, orphans) + handles 5 Azure Monitor alert types.
- **Deploy Agent** — audits 9 security domains (NSG, storage, DB/Key Vault, VM posture, Defender, Policy).
- **Cost Agent** — flags deallocated VMs, unattached disks, orphaned public IPs, over-provisioned SKUs, backed by Advisor + Policy.

### Live Azure Topology Analysis
In live mode (`USE_LIVE_TOPOLOGY=true`), governance agents query **Azure Resource Graph in
real-time** — no stale JSON snapshots. Tag-based dependency parsing (`depends-on`, `governs`),
KQL VM-to-NSG network joins, reverse dependency scans, and live SKU cost from the Azure Retail
Prices API. Every governance decision reflects the actual state of your infrastructure.

### Fully Async Pipeline
All 7 agents (4 governance + 3 operational) are **fully async end-to-end** — from `@af.tool`
callbacks through Azure SDK clients. `asyncio.gather()` runs 4 governance agents truly in
parallel; topology enrichment fans out 4 concurrent KQL queries + 1 HTTP cost lookup. Async
Azure SDK clients use `azure.identity.aio.DefaultAzureCredential` for non-blocking auth.

### Durable Scan Tracking + Real-Time SSE
Agent scans are persisted to **Cosmos DB** (or local JSON) and survive server restarts.
`GET /api/scan/{id}/stream` provides **Server-Sent Events** for real-time scan progress —
9 event types from discovery through verdict. Late-connecting clients receive buffered events.
Scans are cancellable via `PATCH /api/scan/{id}/cancel`.

Proposals are evaluated in **configurable parallel batches** (`PROPOSAL_BATCH_SIZE` env var, default 4) using `asyncio.gather` — a 35-proposal Deploy scan drops from ~19 min sequential to ~5 min evaluation time. `POST /api/scan/all` pre-fetches one shared inventory snapshot so all three agents operate on identical resource data.

### Slack Notifications
Five event types trigger an instant **Slack Block Kit message** via Incoming Webhook —
no one needs to watch the dashboard:

| Event | Colour | Trigger |
|---|---|---|
| DENIED / ESCALATED verdict | 🔴 red / 🟡 amber | Any governance decision at the threshold or above |
| Azure Monitor alert fired | 🟡 amber | Webhook received — investigation started |
| Azure Monitor alert resolved | 🟢 green | Investigation complete |
| **Agent scan failed** | 🔴 red | Unhandled exception in `_run_agent_scan` — includes scan ID, agent type, error, and whether auto-retry was triggered |
| **Inventory stale** | 🟡 amber | Background watcher fires when inventory age exceeds `2 × inventory_stale_hours` (default 48 h); deduped to once per calendar day |

- **Zero-config** — empty webhook URL disables silently (deployed: stored as a Key Vault secret). **Fire-and-forget** — never blocks a verdict. **Master switch** — `SLACK_NOTIFICATIONS_ENABLED=false`. **Auto-retry** — a crashed scan restarts once (guarded by `retry_of`).
- See [`docs/slack-setup.md`](docs/slack-setup.md) for the full setup guide.

### Decision Explanation & Counterfactual Drilldown
Click any row in the Live Activity Feed to open a **6-section full-page drilldown**:

1. **Verdict header** — SRI composite score, resource, agent, timestamp
2. **SRI™ Dimensional Breakdown** — 4 weighted bars; primary factor marked
3. **Decision Explanation** — gpt-4.1-mini plain-English summary, risk highlights, policy violations
4. **Counterfactual Analysis** — "what would change this outcome?" — 3 hypothetical scenarios
   with score transitions (e.g. `77.0 → 53.1 → ESCALATED`)
5. **Agent Reasoning** — proposing agent's rationale + per-governance-agent assessments
6. **Audit Trail** — full raw JSON, collapsible

No extra setup needed — the explanation engine works in both mock and live mode.

### Execution Gateway & Human-in-the-Loop
APPROVED verdicts don't execute directly on Azure — that would cause **IaC state drift**. The Execution Gateway routes verdicts to IaC-safe paths:

- **DENIED** → blocked, logged, Slack alert
- **ESCALATED** → human review (Approve/Dismiss in the drilldown)
- **APPROVED + IaC-managed** → user clicks **Create Terraform PR** (confirmation overlay to verify/override the detected repo + path) → PR against the IaC repo; human merges; CI runs `terraform apply`
- **APPROVED + not IaC-managed** → marked for manual execution

IaC detection reads `managed_by=terraform` tags (live via `ResourceGraphClient`, else `seed_resources.json`). The PR overlay lets the user search their GitHub PAT's repos if tags are wrong. The engine evaluates; Terraform executes; humans approve — IaC state never drifts.

### LLM-Driven Execution Agent
The **"Fix by Agent"** button is fully LLM-driven end-to-end:

```
Operational Agent (LLM thinks) → Governance (LLM scores) → Execution (LLM acts)
```

Two-phase with human review between: **Plan** (LLM reads resource state → structured steps table: operation, target, params, reason, impact, rollback hint) → **human reviews** → **Execute** (LLM calls Azure SDK write tools as planned, fail-safe on any step).

The agent picks a fix via a 4-step decision tree, each stamped with a **Remediation Confidence badge**:
1. **Specific tool** (`start_vm`, `delete_nsg_rule`, …) — *Automated fix* (green)
2. **Generic PATCH** (`update_resource_property` via `begin_update_by_id`; checks `fetch_azure_docs` for the right `api_version`/`property_path`) — *Generic fix* (blue)
3. **Guided manual** (`guided_manual` — copy-pasteable az CLI + Portal steps) — *Guided manual* (amber)
4. **Manual** — *Manual* (grey), last resort

The generic PATCH covers storage `allowBlobPublicAccess`, Key Vault `enableSoftDelete`, App Service `httpsOnly`, database `publicNetworkAccess`, and hundreds of other property fixes. Works in mock and live mode (see the Execution Status screenshot below).

### One-Click Rollback
After a fix is applied, an amber **↩ Rollback** button appears. It confirms the exact inverse operation (`rollback_hint` from the stored plan), then `ExecutionAgent.rollback()` inverts each step (`RESTART_SERVICE` → deallocate, `SCALE_*` → resize back, `MODIFY_NSG` → restore rule). `rolled_back` status + `rollback_log` are stored for audit.

### Resource Inventory — Deterministic Discovery
The LLM used to non-deterministically pick which `query_resource_graph` calls to make (0 verdicts one run, 6 the next). The **Resource Inventory** removes that:

- **One KQL query, no type filter** — `build_inventory()` fetches every subscription resource.
- **VM power state enrichment** — `instance_view()` runs in parallel for all VMs; `powerState` is injected before the agent runs.
- **Injected into every prompt** — the agent reviews every resource by name; it can't skip what's in front of it.
- **LLM still decides** — inventory is for discovery completeness only; the LLM decides risk / proposal / urgency.
- **Cosmos-backed** — snapshots persist; choose `existing` / `refresh` / `skip` per scan.

### Post-Execution Verification
After Execute, a **verification pass** re-checks the resource via read-only tools to confirm the fix took effect; the result (`{confirmed, message, checked_at}`) is stored on the `ExecutionRecord` and shown as a ✓ Verified / ⚠ Unconfirmed banner. The Overview also gained an **Execution Metrics card**, an **Alerts Activity card**, and an **Admin panel** (`/admin`) for config + danger-zone reset.

### LLM Rate Limiting
All 7 agents call Azure OpenAI through `run_with_throttle()` — an `asyncio.Semaphore` +
exponential backoff wrapper. Governance agents fall back to deterministic rule-based scoring
on 429s; operational agents return `[]` (no false positives from stale seed data).

### Production Security Hardening
The API layer is hardened for public deployment: **dashboard login** (one-time admin setup; 256-bit session tokens, 8h TTL), **API key auth** on all `POST`/`PATCH` (`X-API-Key` or session token, constant-time compare; SSE via `?token=`), a separate **alert-webhook secret**, **X-Request-ID** tracing, **per-IP rate limiting** (10 req/60s), **`reviewed_by` validation**, and an **admin-reset guard** (403 in live mode).

→ Details in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) § Production Security Hardening.

### Evidence-Aware Scoring
Each governance agent can attach a structured `EvidencePayload` from real Azure data to adjust its score on confirmed facts — BlastRadius (dependency count, SPOF), Policy (live tags confirm a CRITICAL applies), Historical (prior escalations/denials), Financial (real SKU cost). Bounded by the same ±30 pt guardrail.

→ Details in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) § Evidence-Aware Scoring.

### Conditional Approvals (APPROVED_IF)
A fourth verdict beyond APPROVED / ESCALATED / DENIED — **APPROVED_IF** — says "proceed, but only when these conditions are met," avoiding expensive ESCALATED reviews for borderline cases. Conditions: `TIME_WINDOW` and `METRIC_THRESHOLD` (auto-checkable), `BLAST_RADIUS_CONFIRMED`, `OWNER_NOTIFIED`, `DEPENDENCY_CONFIRMED` (human sign-off).

A 60-second `ConditionWatcher` polls auto-conditions; if all are met at evaluation time the verdict promotes to APPROVED immediately. Admin force-execute requires a mandatory justification. The dashboard shows an amber `🔒 Conditional` badge + conditions panel with sign-off buttons.

### Operator Override Feedback Capture
Every human override — force-executing a DENIED, dismissing an ESCALATED, or satisfying a condition — captures a **`VerdictOverride` record** with a fingerprint hash of the decision context, creating a feedback loop:

- **Three types**: `force_execute`, `dismiss`, `condition_satisfied`.
- **Fingerprint dedup** correlates future similar decisions to detect repeated disagreement with the engine.
- **Full audit trail** (type, reviewer, mandatory justification ≥20 chars for `force_execute`, original verdict) stored in Cosmos `governance-overrides` (partition `/fingerprint_hash`).
- **Override Metrics card** + `GET /api/overrides` / `GET /api/overrides/metrics` — a leading indicator of policy miscalibration.

### Agent Framework Workflow Engine
The governance pipeline runs as a **7-executor workflow graph** (Microsoft Agent Framework) — the **production default** since Phase 33D (`USE_WORKFLOWS=false` reverts to the deprecated legacy path):

```
[DispatchExecutor]
      ├──→ BlastRadiusExecutor ─┐
      ├──→ PolicyExecutor       ├──→ [ScoringExecutor] → [ConditionGateExecutor] → GovernanceVerdict
      ├──→ HistoricalExecutor   │
      └──→ FinancialExecutor   ─┘
```

- **Fan-out / fan-in** — dispatch → 4 parallel executors → scoring aggregates.
- **ConditionGateExecutor** promotes APPROVED_IF → APPROVED in-flight.
- **Durable checkpointing** (`CosmosCheckpointStore`) + **scan resume** (`POST /api/scan/{id}/resume`).
- **Streaming** maps `executor_invoked`/`completed` to `evaluation`/`reasoning` SSE events.

---

## Dashboard

A 9-page React governance UI with real-time SSE streaming, custom design tokens, and animated components. Fully responsive — on mobile the sidebar collapses to an overlay drawer triggered by a hamburger button in the header. Includes an **inline Glossary & FAQ**: every page exposes contextual `i` icons next to verdicts, agents, and key terms; clicking opens a popover with a short definition and a deep link into the full glossary page (top-bar Glossary entry).

### Overview — Production Protection Flow
<p align="center">
  <img src="docs/screenshots/visual-scan-overview.png" alt="How RuriSkry protects production" width="100%">
</p>

> Interactive decision pipeline: alert triggers and agent scans fan out to four governance agents, aggregate into SRI scoring, pass through condition gates, and route into controlled execution.

### Agents — Enterprise Scan Management
<p align="center">
  <img src="docs/screenshots/visual-scan-agents.png" alt="Agents Page" width="100%">
</p>

> Single-system agents page: agent cards with inline scan/stop/live log buttons, Cosmos-backed scan history table with filters, and a dual-mode log viewer (live SSE for running scans, structured evaluation display for completed scans). All scan state managed by a single `useScanManager` hook.

### Governance Decisions
<p align="center">
  <img src="docs/screenshots/visual-scan-decisions.png" alt="Governance Decisions" width="100%">
</p>

> Full decision history with VerdictBadges (APPROVED / ESCALATED / DENIED). Click any row to open the 6-section drilldown with counterfactual analysis.

### Audit Log
<p align="center">
  <img src="docs/screenshots/visual-scan-auditlog.png" alt="Audit Log" width="100%">
</p>

> Scan-level audit log: every scan run recorded with agent, timestamps, proposal/verdict counts, status, and duration.

### Azure Monitor Alerts
<p align="center">
  <img src="docs/screenshots/visual-scan-alerts.png" alt="Alerts Dashboard" width="100%">
</p>

> Azure Monitor alerts flow in via webhook and land in a **Pending** queue. Click **Investigate** in the table row or inside the alert drilldown panel to manually trigger the Monitoring Agent. While investigating, the panel shows a **live terminal-style investigation log** (real-time event stream via polling) — reasoning steps, discoveries, verdicts, and execution status — all without needing the SSE stream. Governance verdicts and action buttons appear once investigation completes.

### Resource Inventory Browser
<p align="center">
  <img src="docs/screenshots/visual-scan-inventory.png" alt="Resource Inventory Browser" width="100%">
</p>

> Full Azure resource inventory: summary cards (total resources, VMs, App Services, types), stale-age warning, refresh button with live progress, **subscription filter** (auto-shown when resources span >1 subscription), type filter, resource group filter, name search, expandable resource rows with per-resource detail, VM power-state dot (green=running, red=deallocated, gray=unknown). Scan modal lets you choose inventory mode (existing / refresh / skip) before each scan.

### Admin Panel
<p align="center">
  <img src="docs/screenshots/visual-scan-admin.png" alt="Admin Panel" width="100%">
</p>

> System configuration (mode, LLM timeout, feature flags), execution gateway status, and danger zone reset — gear icon in the sidebar.

### Decision Quality — Self-Measuring Governance
<p align="center">
  <img src="docs/screenshots/visual-scan-decision-quality.png" alt="Decision Quality" width="100%">
</p>

> Precision, recall, and F1 over labeled decisions. As operators accumulate validated decisions, the engine measures its own accuracy using a confusion matrix of incident-correlated outcomes. Breakdown by verdict band (Approved / Approved If / Escalated / Denied) with incident rate per band. Shows a clean empty-state card on day one — no errors until data is available.

### Execution Status — LLM-Driven Remediation
<p align="center">
  <img src="docs/screenshots/execution-status.png" alt="Execution Status" width="100%">
</p>

> The Execution Gateway turns governance outcomes into controlled action paths: Terraform PR, Azure Portal handoff, agent-generated fix plan, dismissal, or rollback — all captured in the decision audit trail.

### Slack Notifications
<p align="center">
  <img src="docs/screenshots/slack-alerts.png" alt="Slack Alert Notifications" width="100%">
</p>

> DENIED and ESCALATED verdicts, Azure Monitor alerts (fired + investigated), resolution summaries, agent scan failures (with auto-retry status), and inventory staleness alerts are pushed to Slack in real-time via Block Kit messages with "View in Dashboard" deep links.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Azure subscription
- Azure CLI (`az login` completed)
- Terraform 1.5+
- Node.js 18+ (for dashboard)
- Docker Desktop — required to build and push the backend image (`scripts/deploy.sh` handles this automatically)

### Setup

Detailed infra runbook: [`infrastructure/terraform-core/deploy.md`](infrastructure/terraform-core/deploy.md)

```bash
# Clone the repository
git clone https://github.com/psc0des/ruriskry.git
cd ruriskry

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Deploy to Azure (one command)

`scripts/deploy.sh` is the **single entry point** for provisioning and deploying the entire system. It handles everything: Terraform init, staged infrastructure apply (ACR + identity first, then all resources), Docker image build/push, Container App image swap, GitHub PAT prompt, React dashboard build + deploy to Static Web Apps, and health check. Run it from the repo root in **Git Bash** or **WSL** (not PowerShell).

```bash
# 1. One-time: create remote state storage (see deploy.md § "One-time Setup")

# 2. Configure your deployment
cp infrastructure/terraform-core/terraform.tfvars.example \
   infrastructure/terraform-core/terraform.tfvars
# Edit terraform.tfvars — set subscription_id and suffix at minimum

# 3. Deploy everything
bash scripts/deploy.sh

# If Stage 2 fails partway, resume without rebuilding Stage 1 or Docker:
bash scripts/deploy.sh --stage2
```

When it finishes, you'll see live URLs for both the dashboard and backend.

### Generate local .env (for local development)

`scripts/setup_env.sh` reads Terraform outputs and generates a `.env` file so you can run the backend locally (`uvicorn src.api.dashboard_api:app --reload`) against real Azure services. **This is only needed for local development** — the production Container App gets its env vars directly from Terraform.

```bash
bash scripts/setup_env.sh                # safe mode — Key Vault secret names only (recommended)
bash scripts/setup_env.sh --include-keys # also writes raw API keys into .env (local dev only)
bash scripts/setup_env.sh --no-prompt    # non-interactive — uses Azure CLI defaults for sub/tenant IDs
```

### Run locally

```bash
# Run RuriSkry — Dashboard REST API (most common for development)
uvicorn src.api.dashboard_api:app --reload

# Run React dashboard (in separate terminal)
cd dashboard && npm install && npm run dev

# Other entry points:
python -m src.mcp_server.server    # MCP stdio server (for Claude Desktop)
python examples/demo.py                     # direct pipeline demo (3 scenarios)
python examples/demo_a2a.py                 # A2A protocol demo (local dev only)
python examples/demo_live.py                # two-layer intelligence demo
```

### Run Tests

```bash
# Expected: 1462 passed, 0 failed
# Tests use mock mode by default — no Azure credentials needed.
pytest tests/ -v

# Frontend / SSE / modal flows — Playwright (5 specs cover Phase 33B + 34F)
cd dashboard && npx playwright test
```

### Set up Slack notifications (optional)

See [`docs/slack-setup.md`](docs/slack-setup.md) — create a Slack app, enable Incoming Webhooks, set `slack_webhook_url` in `terraform.tfvars`, and apply.

---

## Use Cases

See [`docs/use_cases.md`](docs/use_cases.md) for 18 real-world scenarios across all 3 agents — cost right-sizing, VM crash recovery, NSG security violations, IaC-managed Terraform PRs, and more.

---

## Project Structure

```
ruriskry/
├── src/
│   ├── operational_agents/     # The governed — propose actions
│   │   ├── monitoring_agent.py      # 6-step enterprise scan + 5-type alert handling
│   │   ├── cost_agent.py            # VM waste, unattached disks, orphaned public IPs
│   │   └── deploy_agent.py          # 9-domain security audit + 3-layer detection (hardcoded + Advisor/Defender/Policy + LLM)
│   ├── governance_agents/      # The governors — SRI™ dimension agents
│   │   ├── _llm_governance.py       # Shared guardrail logic — clamp, parse, annotate (±30 pt enforcement)
│   │   ├── blast_radius_agent.py    # SRI:Infrastructure
│   │   ├── policy_agent.py          # SRI:Policy
│   │   ├── historical_agent.py      # SRI:Historical
│   │   └── financial_agent.py       # SRI:Cost
│   ├── core/                   # Decision engine & tracking
│   │   ├── models.py                # Pydantic data models (read first)
│   │   ├── pipeline.py              # asyncio.gather() orchestration
│   │   ├── governance_engine.py     # SRI™ scoring + verdicts
│   │   ├── risk_triage.py           # Tier 1/2 classification — fast-path vs full governance
│   │   ├── decision_tracker.py      # Cosmos DB audit trail (verdicts)
│   │   ├── scan_run_tracker.py      # Cosmos DB / JSON scan-run store
│   │   ├── alert_tracker.py         # Azure Monitor alert lifecycle tracking
│   │   ├── execution_gateway.py     # Routes APPROVED → HITL / Terraform PR / execution
│   │   ├── execution_agent.py       # LLM-driven execution planning, verify, rollback
│   │   ├── az_executor.py           # Audited az CLI executor — 13-pattern allowlist, shell=False
│   │   ├── playbook_generator.py    # Tier 3 playbook — 10 templates (SQL, Redis, KV, ACR, Cosmos, SB)
│   │   ├── override_capture.py      # VerdictOverride capture + fingerprint hashing (Phase 35A)
│   │   ├── decision_alert_correlator.py  # 7-day resource_id correlation (Phase 36)
│   │   ├── decision_labeler.py      # 6-hour background labeler — incident_correlated / no_incident_observed
│   │   ├── decision_embedder.py     # text-embedding-3-small embeddings for few-shot retrieval
│   │   ├── seed_bank_loader.py      # Idempotent startup loader for few_shot_seed_bank.json
│   │   ├── few_shot_retrieval.py    # Cosine similarity retrieval from AI Search vector index
│   │   ├── terraform_pr_generator.py # GitHub PR generation for IaC-managed resources
│   │   ├── explanation_engine.py    # Counterfactual analysis + LLM summary
│   │   ├── interception.py          # Action interception façade
│   │   └── workflows/               # Agent Framework 7-executor graph (Phase 33)
│   │       ├── __init__.py
│   │       ├── workflow_builder.py       # Fan-out/fan-in executor graph
│   │       └── checkpoint_store.py      # CosmosCheckpointStore for scan resume
│   ├── a2a/                    # A2A Protocol layer
│   │   ├── ruriskry_a2a_server.py   # A2A server + Agent Card
│   │   ├── operational_a2a_clients.py  # A2A client wrappers
│   │   └── agent_registry.py        # Connected agent tracking
│   ├── mcp_server/             # RuriSkry as MCP provider
│   │   └── server.py                # FastMCP — 3 tools: evaluate, query history, risk profile
│   ├── infrastructure/         # Azure service clients (mock fallback)
│   │   ├── azure_tools.py           # 5 sync + 10 async (*_async) tools: Resource Graph, metrics, NSG, activity log, resource health, Advisor, Defender, Policy, ARM metadata
│   │   ├── resource_graph.py        # Live: KQL topology enrichment (tags + NSG join + cost)
│   │   ├── cost_lookup.py           # Azure Retail Prices API — SKU→monthly cost (no auth)
│   │   ├── llm_throttle.py          # asyncio.Semaphore + exponential backoff for LLM calls
│   │   ├── cosmos_client.py         # 5 Cosmos clients: decisions, executions, inventory, agents/admin, overrides (Phase 35A)
│   │   ├── search_client.py         # Azure AI Search client
│   │   ├── openai_client.py         # Azure OpenAI / gpt-4.1-mini client
│   │   └── secrets.py               # Key Vault secret resolver
│   ├── notifications/          # Outbound alerting
│   │   └── slack_notifier.py        # 5 notification types: verdict, alert fired/resolved, scan failure, inventory stale (Block Kit)
│   ├── governance/             # Finding → proposal adapter
│   │   └── finding_to_proposal.py   # finding_to_proposal() — Finding → ProposedAction (Phase 40)
│   ├── rules/                  # Universal + type-aware rules engine (Phase 40)
│   │   ├── base.py                  # @rule decorator + self-registering registry
│   │   ├── inventory_index.py       # O(1) InventoryIndex — by_type, get, is_referenced
│   │   ├── agent_integration.py     # run_rules_prescan() wired before every LLM call
│   │   ├── universal/               # 26 UNIV-* rules (public network, TLS, MI, tags, disks…)
│   │   └── type_aware/              # 8 TYPE-* rules (NSG SSH/RDP, AKS, SQL, Cosmos, App Service)
│   └── api/                    # Dashboard REST endpoints
│       └── dashboard_api.py         # ~60 REST endpoints: scans, alerts, SSE, explanation, HITL, conditional approvals, config
├── dashboard/                  # React + Vite governance dashboard
├── data/                       # Seed data + local persistence (mock fallback)
│   ├── agents/                      # A2A agent registry (mock)
│   ├── alerts/                      # Alert records (local fallback)
│   ├── decisions/                   # Audit trail (mock)
│   ├── executions/                  # Execution records (mock)
│   ├── overrides/                   # Override feedback records (Phase 35A)
│   ├── scans/                       # Scan-run records (mock — ScanRunTracker)
│   ├── seed_incidents.json
│   ├── seed_resources.json
│   ├── few_shot_seed_bank.json      # 40 validated examples — all action×verdict combos (Phase 38)
│   └── policies.json                # Governance policy rules (JSON — edit to add rules)
├── examples/demo.py                     # Direct pipeline demo (3 scenarios)
├── examples/demo_a2a.py                 # A2A protocol demo
├── examples/demo_live.py                # Two-layer intelligence demo
├── tests/
├── docs/
│   ├── ARCHITECTURE.md              # System design, agent descriptions, data flow
│   ├── SETUP.md                     # Setup instructions, environment variables
│   ├── API.md                       # API endpoint reference
│   ├── SERVICES.md                  # Azure service dependency map
│   ├── FAQ.md                       # Common post-deploy questions and answers
│   ├── slack-setup.md               # Slack webhook setup guide for contributors
│   ├── alert-wiring.md              # Azure Monitor → RuriSkry wiring guide
│   └── use_cases.md                 # Real-world scenarios for all 3 agents (end-to-end flows)
└── scripts/
    ├── deploy.sh                    # One-command full deploy (Terraform + Docker + dashboard)
    ├── cleanup.sh                   # Wipe Azure resources for a clean re-deploy
    ├── setup_env.sh                 # Generate .env from Terraform outputs (for local dev)
    └── seed_data.py                 # Seed demo incidents into AI Search (local dev only)
```

---

## Demo Scenarios

Run `python examples/demo.py` (direct pipeline) or `python examples/demo_a2a.py` (A2A protocol, local dev only).

### Scenario 1: Dangerous Action → DENIED
**Cost Agent** proposes deleting `vm-23` (disaster-recovery VM, $847/mo).
RuriSkry detects the `purpose=disaster-recovery` tag → POL-DR-001 critical violation fires, overriding the numeric score.
**SRI™: 74.0 → ❌ DENIED** (critical policy override)

### Scenario 2: Safe Action → AUTO-APPROVED
**Monitoring Agent** proposes scaling `web-tier-01` (D4s_v3 → D8s_v3) during a CPU spike.
No critical violations, low blast radius, no historical incidents matching the pattern.
**SRI™: 14.1 → ✅ AUTO-APPROVED**

### Scenario 3: Moderate Risk → ESCALATED
**Deploy Agent** proposes modifying `nsg-east` (add deny-all inbound rule) with `nsg_change_direction="restrict"`.
POL-SEC-001 fires (HIGH — NSG changes require security review). Rule 3.5 floors the verdict at ESCALATED even if composite is low.
**SRI™: 55.2 → ⚠️ ESCALATED for human review**

---

## Origin

RuriSkry was created for the **Microsoft AI Dev Days Hackathon 2026** (Feb 10 – Mar 15, 2026),
challenge track: *Automate and Optimize Software Delivery — Leverage Agentic DevOps Principles*.

Since its hackathon origins, the project has matured into a production-grade governance engine
with fully async internals, live Azure topology analysis (Resource Graph + Retail Prices API),
durable Cosmos DB audit trails, Slack alerting, explainable AI with counterfactual
drilldowns, and a comprehensive 1462-test suite.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## Current Status & Honest Expectations

RuriSkry solves a real and underserved problem: holding AI agents accountable before they act on production infrastructure. The core architecture — SRI™ scoring engine, governance pipeline, HITL execution flow, Cosmos DB audit trail — is designed to production standards and has been validated end-to-end against a live Azure environment.

**What works today (validated):**

- Full governance pipeline: scan → verdict → HITL → execution, tested across Monitoring, Cost, and Deploy agents
- Live Azure execution via Managed Identity — `az login --identity` auto-authenticates on first execution; all subsequent calls are free. Validated with VM restart (`exit_code: 0`, `status: applied`)
- GitHub Terraform PR creation — detects IaC-managed resources via `managed_by=terraform` tags, opens PRs against the correct repo/path
- 1462 automated tests pass in mock mode — no Azure credentials required to run the full suite

**What this means for you:**

- The governance logic, policy engine, and scoring model are well-tested and intentional
- The agent execution paths (plan → execute → verify → rollback) work; behaviour on resource configurations or Azure environments not yet tested may surface edge cases
- You will likely find bugs — every issue reported makes this better for everyone

**Direct remediation coverage (Phase 34A Tier 1 SDK):**

RuriSkry **scans every resource type** in Azure (`Reader` is the only role for scanning). **Direct API remediation (Tier 1)** now covers 7 resource categories:

| Resource | Operation | Role required |
|---|---|---|
| Virtual Machines | start / restart / resize | `Virtual Machine Contributor` |
| Network Security Groups | create / modify / delete rules | `Network Contributor` |
| App Services | restart | `Website Contributor` |
| Function Apps | restart | `Website Contributor` |
| App Service Plans | scale SKU / worker count | `Website Contributor` |
| AKS node pools | scale node count | `Azure Kubernetes Service Contributor Role` |
| Storage Accounts | rotate keys | `Storage Account Key Operator` (per account — can't be subscription-scoped) |

All Tier 1 tools support **dry-run mode** — pass `dry_run=True` in the execute call to validate the full call path and write an audit record without making the mutating API call.

**Tier 3 Playbook (Phase 34D)** — For resource types without a Tier 1 SDK tool, RuriSkry now generates a Tier 3 remediation playbook visible in the decision drilldown. The playbook shows the exact `az` CLI command to run, a rollback command where reversible, risk level, estimated duration, and whether the operation requires downtime. Supported combinations:

| Resource | Operation |
|---|---|
| SQL Database | scale up / scale down |
| Redis Cache | restart / scale up / rotate keys |
| Key Vault | update config (soft-delete) |
| Container Registry | scale up / scale down |
| Cosmos DB | update config (consistency level) |
| Service Bus namespace | scale up |

**Phase 34E/34F** add audited `az` CLI execution from the dashboard, gated by an **A2 Validator** (a conservative GPT-4.1 critic, 5s timeout — warns but never blocks). The playbook panel offers **Run as dry-run** and **▶ Run live**; both flow through a confirmation modal and write a full Cosmos audit record (incl. validator summary). Safety invariants: a hard-coded 13-pattern allowlist checked before any subprocess, `shell=False` always, args passed as a list — new patterns require a code change. In Container Apps the executor auto-authenticates via System-Assigned MI (`az login --identity`); requires `az` in the image (see [`docs/SETUP.md`](docs/SETUP.md)).

For types without Tier 1/Tier 3 coverage, the Execution Gateway creates a Terraform PR for human review; non-Terraform environments still get verdicts and recommendations to apply manually.

**If you're deploying RuriSkry:**
- Start with mock mode (`USE_LOCAL_MOCKS=true`) to understand how the decision pipeline works before connecting live Azure credentials
- Run it alongside your existing change management process, not as a replacement, while you build confidence in the verdicts
- Tune policies and scoring weights to your environment — they live in `data/policies.json` and `src/core/governance_engine.py` and are designed to be adjusted

**If you find something broken:**
- Open an issue — a clear reproduction case is the most valuable contribution you can make
- The codebase is structured to be readable and modifiable; fixes and policy contributions are welcome

This is open-source in the truest sense: the code is available, the design is transparent, and the expectation is that it improves through use and collaboration — not that it works perfectly out of the box on day one.

---

<p align="center">
  <b>RuriSkry: AI agents propose the fix. An AI Change Advisory Board decides if it ships. 🛡️</b>
</p>

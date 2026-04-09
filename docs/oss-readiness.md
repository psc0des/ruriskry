# OSS Readiness Audit — SentinelLayer

**Audited:** 2026-04-09  
**Status:** Findings captured — implementation pending  
**Purpose:** Issues to resolve before public OSS release

---

## CRITICAL — Blocks launch

| # | File | Line | Issue |
|---|------|------|-------|
| C1 | `src/api/dashboard_api.py` | 2814 | `POST /api/admin/reset` has no auth guard — any client can wipe all in-memory scan/alert state and reset execution gateway. Only touches local JSON (not Cosmos) but still clears `_scans`, `_alerts`, `_execution_gateway` globals. |
| C2 | `src/api/dashboard_api.py` | all routes | **Zero authentication on all 37 endpoints** — scan, approve HITL actions, read decisions, trigger investigations all public. |
| C3 | `src/api/dashboard_api.py` | 2589 | `reviewed_by` pulled from unvalidated request body (`body.get("reviewed_by", "dashboard-user")`) — audit trail can be spoofed by any caller. |

**Fix approach:**
- C1: Add `if not settings.use_local_mocks: raise HTTPException(403)` guard, or require admin header
- C2: Decision needed — static API key header vs Azure AD OIDC vs "document as deploy-behind-APIM"
- C3: Validate `reviewed_by` against Azure AD token claims once auth is added

---

## HIGH — Fix before significant adoption

| # | File | Line | Issue |
|---|------|------|-------|
| H1 | `src/api/dashboard_api.py` | 250, 287 | `_scans`, `_alerts`, SSE queues are in-memory Python dicts. Requires sticky sessions (`affinity=sticky` on Container Apps). Pod crash loses all active scan state. Not HA. |
| H2 | No middleware | — | No rate limiting on any endpoint. `/api/scan` spins up 3 LLM agents per call — one misbehaving client exhausts Foundry TPM quota. Add `slowapi` or `limits`. |
| H3 | `src/api/dashboard_api.py` | 205 | `allow_headers=["*"]` CORS — no origin validation. Should be explicit allowlist. |
| H4 | `src/api/dashboard_api.py` | ~1850 | `POST /api/alert-trigger` has no payload signature verification. Any client knowing the URL can inject fake alerts. Azure Monitor supports `Authorization: SharedAccessSignature` on secure webhooks — should validate. |

---

## MEDIUM — Fix for production grade

| # | File | Line | Issue |
|---|------|------|-------|
| M1 | `src/config.py` | 30 | `cosmos_database: str = "ruriskry"` hardcoded. Should be `var.project_name` or configurable via env var `COSMOS_DATABASE`. |
| M2 | `infrastructure/terraform-core/main.tf` | 72–77 | `name_prefix = "ruriskry-core"` and `acr_prefix = "ruriskrycore"` hardcoded. Should derive from a `var.project_name` (default `"ruriskry"`) so OSS forks can rename. |
| M3 | `src/core/terraform_pr_generator.py` | 96–180 | Branch naming hardcodes `ruriskry/approved/...`. Should be a configurable prefix (`settings.pr_branch_prefix`). |
| M4 | `src/operational_agents/monitoring_agent.py` | 316 | Demo scan uses `target_resource_group="ruriskry-prod-rg"` as default. Should be `None` or read from config. Same in `deploy_agent.py:198`. |
| M5 | `infrastructure/terraform-core/variables.tf` | 183 | Cosmos DB free tier enabled by default. **Azure allows only one free Cosmos account per subscription** — any org that already has one will get a hard failure mid-deploy with no clear error. Default should be `false`. |
| M6 | `src/api/dashboard_api.py` | 980, 1764, 2163 | Hard `limit=500` ceiling, no `offset` or cursor-based pagination. Orgs with >500 decisions/alerts hit a wall. |
| M7 | `src/core/scan_run_tracker.py` | 167 | O(n) in-memory sort of all JSON files on every `list_recent()` call. Same in `alert_tracker.py:147`. Acceptable now; breaks at scale. |
| M8 | `src/config.py` | 84 | `use_local_mocks: bool = True` default. New deployers who miss `USE_LOCAL_MOCKS=false` silently get mock mode — agents return canned data, no cloud calls, no error. Should default `False` with loud startup warning in mock mode. |
| M9 | `infrastructure/terraform-core/main.tf` | 521, 899 | ACR Basic SKU (10 GB cap, no geo-replication) and Static Web App Free tier (100 GB bandwidth, no SLA) are hardcoded. Expose as `var.acr_sku` and `var.swa_sku` so enterprise users can override. |
| M10 | `src/a2a/agent_registry.py` | 214 | Writes agent stats to `data/agents/` local JSON. No Cosmos equivalent — state lost on container restart. |

---

## LOW — Polish for OSS credibility

| # | File | Line | Issue |
|---|------|------|-------|
| L1 | `src/infrastructure/inventory_builder.py` | 10 | Docstring uses `"e7e0ed80-..."` (partial real subscription ID). Use `"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"`. |
| L2 | `src/api/dashboard_api.py` | 2800 | Health response hardcodes `"service": "ruriskry-backend"`. Should use `settings.service_name` or similar. |
| L3 | `infrastructure/terraform-core/variables.tf` | 72, 287 | Search SKU defaults to `"free"` (50 MB index limit). Fine for OSS but should be documented as a dev-only default. |
| L4 | No tracing | — | No `X-Request-ID` header injection or correlation ID in logs. Hard to debug distributed failures across Container App + Cosmos + LLM. |
| L5 | `data/seed_resources.json` | — | Demo resource names (`vm-web-01`, `nsg-east-prod`, `payment-api-prod`) look like real infra. Add a prominent comment at top of file. |

---

## Proposed Fix Batches

### Batch A — Quick wins, no design decision needed (est. 1–2 hours)
- C1: Guard `admin/reset` — refuse in live mode (`use_local_mocks=false`)
- M5: Set `cosmos_free_tier = false` as default in variables.tf
- M6: Add `offset: int = 0` pagination param to list endpoints
- M8: Default `use_local_mocks = False` + add loud startup log warning in mock mode
- L1: Fix docstring UUID placeholder
- L2: Make health response service name use a config value

### Batch B — Naming / configuration (est. 1 hour)
- M1: Make `cosmos_database` configurable via env
- M2: Make terraform `name_prefix` derive from `var.project_name`
- M3: Make PR branch prefix configurable (`settings.pr_branch_prefix`)
- M4: Remove hardcoded `ruriskry-prod-rg` from agent demo defaults
- L3: Document Search free SKU limitation

### Batch C — Rate limiting + CORS (est. 30 min)
- H2: Add `slowapi` rate limiter on `/api/scan` and `/api/alert-trigger`
- H3: Replace `allow_headers=["*"]` with explicit allowlist

### Batch D — Auth (design decision required)
- C2: API authentication strategy — static API key / Azure AD / document as "deploy behind APIM"
- C3: Tie `reviewed_by` to auth identity once decided
- H4: Alert webhook signature verification (Azure Monitor Secure Webhook)

### Batch E — State durability (larger effort)
- H1: Move active scan state (`_scans`, SSE queues) to Cosmos or Redis to eliminate sticky sessions requirement
- M10: Move agent registry stats to Cosmos

---

## Notes
- `.gitignore` already covers all `*.tfstate`, `backend.hcl`, `.terraform/` — no secrets in git
- `USE_LOCAL_MOCKS=false` hardcoded in terraform-core Container App env vars — live mode by default in deployed instances
- All Cosmos clients have proper fallbacks — no hardcoded connection strings in source
- Alert wiring already updated to use Alert Processing Rules (APR) — one rule covers all current and future alert rules in target subscription

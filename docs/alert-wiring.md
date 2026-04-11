# Alert Wiring — How Azure Monitor Alerts Reach RuriSkry

This document explains every component involved in routing Azure Monitor alerts into
the RuriSkry governance engine: what each piece is, why it exists, how the pieces
connect, and how to configure each deployment scenario correctly.

---

## Table of Contents

1. [What "alert wiring" means](#1-what-alert-wiring-means)
2. [Full end-to-end chain](#2-full-end-to-end-chain)
3. [Component reference](#3-component-reference)
   - [3.1 Azure Monitor Alert Rules](#31-azure-monitor-alert-rules)
   - [3.2 Action Group](#32-action-group)
   - [3.3 Alert Processing Rule (APR)](#33-alert-processing-rule-apr)
   - [3.4 POST /api/alert-trigger endpoint](#34-post-apialert-trigger-endpoint)
   - [3.5 Alert normalizer](#35-alert-normalizer)
   - [3.6 Deduplication and cooldown](#36-deduplication-and-cooldown)
4. [Deployment scenarios](#4-deployment-scenarios)
   - [4.1 Single subscription (default)](#41-single-subscription-default)
   - [4.2 Cross-subscription / hub-spoke](#42-cross-subscription--hub-spoke)
   - [4.3 You already have existing alert rules](#43-you-already-have-existing-alert-rules)
5. [Demo environment wiring](#5-demo-environment-wiring)
6. [Securing the webhook endpoint](#6-securing-the-webhook-endpoint)
7. [Payload formats Azure Monitor sends](#7-payload-formats-azure-monitor-sends)
8. [Narrowing alert scope](#8-narrowing-alert-scope)
9. [Verifying the wiring](#9-verifying-the-wiring)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. What "alert wiring" means

RuriSkry includes a **Monitoring Agent** that investigates Azure operational events
(CPU spikes, VM heartbeat loss, service restarts) and routes proposed remediation
actions through the full governance pipeline. For this to happen automatically, Azure
Monitor must be told where to deliver alert payloads — that delivery target is
RuriSkry's `/api/alert-trigger` endpoint.

"Alert wiring" is the configuration that creates that delivery path.

There are two separate wiring paths in this project:

| Path | What it covers | Who configures it |
|------|---------------|-------------------|
| **Core APR** | Every alert in the monitored subscription | Terraform (`terraform-core`) — fully automatic |
| **Demo environment** | Synthetic demo VMs (`terraform-demo`) | `deploy.sh --stage2` — automatic if demo is deployed first |

---

## 2. Full end-to-end chain

```
┌─────────────────────────────────────────────────────────────────────┐
│  Azure Subscription (monitored)                                      │
│                                                                      │
│  Alert Rule fires (metric threshold OR log query result)             │
│         │                                                            │
│         ▼                                                            │
│  Alert Processing Rule  "apr-ruriskry-governance-fanout"             │
│  scope: /subscriptions/<target_sub>                                  │
│  effect: ADD action group → azurerm_monitor_action_group.ruriskry    │
│         │                                                            │
└─────────┼────────────────────────────────────────────────────────────┘
          │  (cross-subscription action group reference is supported)
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Action Group  "<project>-core-alert-handler-<suffix>"               │
│  webhook_receiver.service_uri =                                      │
│    https://<container-app-fqdn>/api/alert-trigger                   │
│  use_common_alert_schema = false                                     │
│         │                                                            │
└─────────┼────────────────────────────────────────────────────────────┘
          │  HTTP POST (JSON payload)
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  RuriSkry Backend  (Azure Container App)                             │
│                                                                      │
│  POST /api/alert-trigger                                             │
│    ├── Webhook secret check (ALERT_WEBHOOK_SECRET, optional)         │
│    ├── Payload normalizer  (_normalize_azure_alert_payload)          │
│    ├── Deduplication check (same resource+metric, 30-min cooldown)   │
│    └── Creates alert record with status "pending"                    │
│                                                                      │
│  Returns: {"status": "pending", "alert_id": "<uuid>"}               │
│                                                                      │
│  User opens Alerts tab in the dashboard                              │
│    └── Clicks "Investigate" → POST /api/alerts/{id}/investigate      │
│           └── MonitoringAgent runs governance pipeline               │
└─────────────────────────────────────────────────────────────────────┘
```

Key point: the endpoint **does not auto-investigate**. It creates a `pending` record
and returns immediately. Investigation is user-triggered. This is intentional — it
gives the operator a chance to review the alert before committing AI-driven
investigation resources.

---

## 3. Component reference

### 3.1 Azure Monitor Alert Rules

Alert rules define what condition triggers an alert. RuriSkry works with any alert
rule type Azure Monitor supports:

| Rule type | Terraform resource | Example in `terraform-demo` |
|-----------|-------------------|------------------------------|
| Metric alert | `azurerm_monitor_metric_alert` | CPU > 80% on vm-web-01 (15-min window) |
| Log Alert V2 | `azurerm_monitor_scheduled_query_rules_alert_v2` | No heartbeat from vm-dr-01 in 15 min |
| Activity Log alert | `azurerm_monitor_activity_log_alert` | Any resource deletion in subscription |

You do **not** need to modify your existing alert rules. The APR intercepts alert
events at the subscription level and adds the RuriSkry action group on top of
whatever action groups the rule already has. Your existing email/PagerDuty/Teams
actions are unaffected.

---

### 3.2 Action Group

**File:** `infrastructure/terraform-core/main.tf` — `azurerm_monitor_action_group.ruriskry`

```hcl
resource "azurerm_monitor_action_group" "ruriskry" {
  name       = "${local.name_prefix}-alert-handler-${local.name_suffix}"
  short_name = "ruriskry"

  webhook_receiver {
    name                    = "ruriskry-webhook"
    service_uri             = "https://${azurerm_container_app.backend.ingress[0].fqdn}/api/alert-trigger"
    use_common_alert_schema = false
  }
}
```

The `service_uri` is computed at Terraform plan time from the Container App's FQDN.
Every `terraform apply` keeps this URL current — if the Container App is redeployed
and its FQDN changes, a subsequent `terraform apply` updates the action group
automatically. No manual URL management is needed.

`use_common_alert_schema = false` preserves the richer, format-specific payload so
the normalizer can extract metric values, thresholds, and severity levels that the
Common Alert Schema strips out. See [section 7](#7-payload-formats-azure-monitor-sends)
for detail on what each schema looks like.

---

### 3.3 Alert Processing Rule (APR)

**File:** `infrastructure/terraform-core/main.tf` — `azurerm_monitor_alert_processing_rule_action_group.ruriskry`

```hcl
resource "azurerm_monitor_alert_processing_rule_action_group" "ruriskry" {
  provider            = azurerm.target          # lives in the MONITORED subscription
  name                = "apr-ruriskry-governance-fanout"
  resource_group_name = azurerm_resource_group.ruriskry_monitor.name
  scopes              = ["/subscriptions/${local.scan_subscription_id}"]
  description         = "Routes all Azure Monitor alerts to the RuriSkry AI governance engine. Managed by Terraform — do not edit manually."

  add_action_group_ids = [azurerm_monitor_action_group.ruriskry.id]
}
```

**What an APR does:** An Alert Processing Rule is an Azure resource that intercepts
fired alerts and modifies how they are handled — adding or suppressing action groups,
changing severity, etc. — without touching the alert rules themselves. Think of it
as middleware for the alerting pipeline.

**Why it lives in the target subscription:** Azure requires an APR to be in the same
subscription as its `scopes`. When you monitor a different subscription from the one
RuriSkry is deployed in (hub-spoke), Terraform uses the aliased `azurerm.target`
provider to create the APR in the correct subscription while the backend action group
stays in the RuriSkry infra subscription. Azure APRs support cross-subscription
action group references.

**Why a dedicated resource group:** The APR is placed in `ruriskry-monitor-rg-<suffix>`,
a resource group in the target subscription created solely for monitoring
infrastructure. This keeps it separate from the RuriSkry backend infra and from
the customer's workload resources.

**Scope:** The default scope is the entire target subscription. Every alert rule in
that subscription — existing and future — is intercepted. See
[section 8](#8-narrowing-alert-scope) if you want a narrower scope.

---

### 3.4 POST /api/alert-trigger endpoint

**File:** `src/api/dashboard_api.py` — `trigger_alert()`

This is the webhook target that Azure Monitor POSTs to. On receipt it:

1. Verifies the `Authorization: Bearer <secret>` header if `ALERT_WEBHOOK_SECRET` is set.
2. Runs `_normalize_azure_alert_payload()` to flatten the Azure envelope into RuriSkry's
   internal format (`resource_id`, `metric`, `value`, `threshold`, `severity`, etc.).
3. Checks for a duplicate alert (same resource + metric already `pending`/`investigating`,
   or resolved within the last 30 minutes). If found, returns the existing record with
   `{"duplicate": true}`.
4. Creates a new `pending` alert record (persisted to disk).
5. Returns `{"status": "pending", "alert_id": "<uuid>"}` immediately.

The endpoint is **exempt from the global API key middleware** — it has its own
`ALERT_WEBHOOK_SECRET` mechanism because Azure Monitor cannot send arbitrary headers
beyond `Authorization`.

---

### 3.5 Alert normalizer

**File:** `src/api/dashboard_api.py` — `_normalize_azure_alert_payload()`

Azure Monitor sends different JSON shapes depending on the alert rule type and whether
`use_common_alert_schema` is on. The normalizer handles four shapes and converts all
of them to the same flat internal dict. See
[section 7](#7-payload-formats-azure-monitor-sends) for the payload shapes and how
each is parsed.

**The Log Analytics workspace pivot** is worth understanding in detail. When a
Log Alert V2 fires on a `count = 0` query (e.g. "no heartbeats in 15 minutes"),
there are no result rows, so `AffectedConfigurationItems` is empty. Azure also sets
`alertTargetIDs` to the *workspace* ARM ID, not the VM that stopped reporting.

The normalizer detects this by checking whether `alertTargetIDs[0]` contains
`operationalinsights/workspaces`, then regex-extracts the VM name from the alert
rule name or description and reconstructs the correct VM ARM ID using the subscription
and resource group found in the workspace ARM ID. Without this pivot, the Monitoring
Agent would investigate the Log Analytics workspace instead of the VM.

---

### 3.6 Deduplication and cooldown

**File:** `src/api/dashboard_api.py` — inside `trigger_alert()`

Azure Monitor evaluates alert rules on a schedule (every 5 minutes by default). During
a persistent outage a rule fires → resolves → fires again on every evaluation cycle,
generating a new alert every 5 minutes. The deduplication logic prevents alert floods:

- If an alert for the same `(resource_id, metric)` is currently `pending` or
  `investigating`, the incoming alert is dropped and the existing record's ID is
  returned.
- If the most recent alert for that combination resolved or was investigated within the
  last **30 minutes**, it is also suppressed (the cooldown window).

The cooldown comparison uses ISO 8601 UTC strings
(`existing.get("resolved_at") >= cutoff.isoformat()`), which works because ISO 8601
strings sort lexicographically in chronological order.

To adjust the cooldown window, change `_ALERT_COOLDOWN_MINUTES` in `dashboard_api.py`.

---

## 4. Deployment scenarios

### 4.1 Single subscription (default)

RuriSkry and the resources it monitors live in the same Azure subscription.

**Configuration:** Leave `target_subscription_id` empty in
`infrastructure/terraform-core/terraform.tfvars`.

```hcl
# terraform.tfvars
subscription_id        = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
# target_subscription_id not set — defaults to subscription_id
```

**What Terraform does:**
- The `azurerm.target` provider alias resolves to the same subscription as `azurerm`.
- The APR, its resource group, and the action group are all in the same subscription.
- No extra IAM grants are needed beyond the standard Terraform deployment permissions.

**Deploy:**
```bash
bash scripts/deploy.sh
```

---

### 4.2 Cross-subscription / hub-spoke

RuriSkry runs in a central platform subscription; the resources it governs live in
one or more workload subscriptions.

**Configuration:**

```hcl
# terraform.tfvars
subscription_id        = "aaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"   # platform / RuriSkry sub
target_subscription_id = "bbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"   # workload sub to scan
```

**What Terraform does automatically:**
- The `azurerm.target` provider points at the workload subscription.
- `azurerm_resource_group.ruriskry_monitor` is created in the workload subscription.
- The APR is created in the workload subscription with `scopes` set to that subscription.
- The APR references the action group in the platform subscription — Azure APRs
  support cross-subscription action group references.
- The Container App Managed Identity is granted `Reader`, `Network Contributor`, and
  `VM Contributor` on the workload subscription automatically by `main.tf`.

**One manual prerequisite:** The identity running `terraform apply` needs
`Monitoring Contributor` on the workload subscription to create the APR. Grant it once:

```bash
az role assignment create \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Monitoring Contributor" \
  --scope "/subscriptions/<workload_subscription_id>"
```

If `terraform apply` fails at the APR resource with `AuthorizationFailed`, this is
the missing grant. Fix it and re-run with targeting:

```bash
terraform apply -chdir=infrastructure/terraform-core \
  -target=azurerm_resource_group.ruriskry_monitor \
  -target=azurerm_monitor_alert_processing_rule_action_group.ruriskry
```

---

### 4.3 You already have existing alert rules

If your subscription already has alert rules with their own action groups
(email, PagerDuty, Slack, etc.), you do not need to change them.

The APR **adds** the RuriSkry action group to alert delivery. It does not replace or
suppress existing action groups. Your existing notification paths continue to fire
exactly as before; RuriSkry is additive.

Concretely: if an alert rule fires and its action group emails on-call, that email
still goes out. Azure also evaluates the APR, which appends the RuriSkry action
group, causing a second HTTP POST to `/api/alert-trigger` at the same time.

If you want RuriSkry to receive alerts from only a specific subset of rules rather
than all rules in the subscription, see [section 8](#8-narrowing-alert-scope).

---

## 5. Demo environment wiring

`infrastructure/terraform-demo` deploys a realistic mini production environment:
two VMs (`vm-web-01`, `vm-dr-01`), a Log Analytics workspace, Azure Monitor Agent
extensions, data collection rules, and three alert rules.

This module is optional. It exists to demonstrate concrete end-to-end alert flows
without needing a live production environment.

### Alert rules in terraform-demo

| Rule | Type | Condition | Expected governance outcome |
|------|------|-----------|----------------------------|
| `alert-vm-web-01-cpu-high` | Metric alert | Average CPU > 80% over 15 min | Monitoring Agent proposes scale-up → **APPROVED** (legitimate load) |
| `alert-vm-dr-01-heartbeat` | Log Alert V2 | No heartbeat from dr-01 in 15 min | Cost Agent flags as idle → proposes deletion → **DENIED** (disaster recovery policy) |
| `alert-vm-web-01-heartbeat` | Log Alert V2 | No heartbeat from web-01 in 15 min | Monitoring Agent detects stopped web server → proposes restart_service → **APPROVED** |

### How the wiring works

The demo environment has its own action group (`ag-ruriskry-prod`) with a
`dynamic webhook_receiver` block:

```hcl
dynamic "webhook_receiver" {
  for_each = var.alert_webhook_url != "" ? [1] : []
  content {
    name                    = "ruriskry-alert-trigger"
    service_uri             = var.alert_webhook_url
    use_common_alert_schema = false
  }
}
```

The webhook receiver only exists when `alert_webhook_url` is set in
`terraform-demo/terraform.tfvars`. The value must be
`https://<backend-url>/api/alert-trigger`.

### Automatic wiring via deploy.sh --stage2

When you run `deploy.sh` after deploying terraform-demo, the script:

1. Reads `BACKEND_URL` from `terraform-core` outputs.
2. Checks whether `alert_webhook_url` is already set in `terraform-demo/terraform.tfvars`.
3. If not, injects `alert_webhook_url = "<BACKEND_URL>/api/alert-trigger"`.
4. Runs `terraform apply -auto-approve -target=azurerm_monitor_action_group.prod` in
   `terraform-demo` to activate the webhook receiver immediately (no full apply needed).

### Manual wiring (if auto-wiring was skipped)

```bash
# 1. Get the backend URL
BACKEND_URL=$(terraform -chdir=infrastructure/terraform-core output -raw backend_url)

# 2. Add to terraform-demo/terraform.tfvars
echo "alert_webhook_url = \"$BACKEND_URL/api/alert-trigger\"" \
  >> infrastructure/terraform-demo/terraform.tfvars

# 3. Apply only the action group (fast — no VM changes)
terraform -chdir=infrastructure/terraform-demo apply -auto-approve \
  -target=azurerm_monitor_action_group.prod
```

---

## 6. Securing the webhook endpoint

By default `/api/alert-trigger` is unauthenticated. This is acceptable when the
backend is on a private network or during development. For public deployments, enable
the webhook secret.

### Enable ALERT_WEBHOOK_SECRET

```bash
# Generate a strong secret
SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# Store in Key Vault (recommended)
az keyvault secret set \
  --vault-name "<kv-name>" \
  --name "alert-webhook-secret" \
  --value "$SECRET"

# Wire into the Container App
az containerapp secret set \
  --name "<container-app-name>" \
  --resource-group "<resource-group>" \
  --secrets "alert-webhook-secret=keyvaultref:<kv-secret-uri>,identityref:<managed-identity-id>"

az containerapp update \
  --name "<container-app-name>" \
  --resource-group "<resource-group>" \
  --set-env-vars "ALERT_WEBHOOK_SECRET=secretref:alert-webhook-secret"
```

Or set `ALERT_WEBHOOK_SECRET` in your `.env` for local development.

### Tell Azure Monitor to send the secret

Add the `aad_auth` block to the webhook receiver in Terraform:

```hcl
webhook_receiver {
  name                    = "ruriskry-webhook"
  service_uri             = "https://<fqdn>/api/alert-trigger"
  use_common_alert_schema = false
  aad_auth {
    object_id = "<managed-identity-or-service-principal-object-id>"
  }
}
```

### How the check works

When `ALERT_WEBHOOK_SECRET` is set, the endpoint verifies:

```python
expected = f"Bearer {settings.alert_webhook_secret}"
if authorization != expected:
    raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")
```

The `Authorization` header must be `Bearer <your-secret>`. Requests without the
correct header receive a 401 before any processing happens.

---

## 7. Payload formats Azure Monitor sends

`_normalize_azure_alert_payload()` in `src/api/dashboard_api.py` handles four payload
shapes. Understanding which shape each alert rule type produces helps when debugging
why an alert is parsed incorrectly.

### Shape 1 — Already-flat (test payloads / direct API calls)

When calling `/api/alert-trigger` directly (e.g. `curl`, integration tests), the
Azure envelope can be omitted:

```json
{
  "resource_id": "/subscriptions/.../virtualMachines/vm-web-01",
  "metric": "Percentage CPU",
  "value": 95.0,
  "threshold": 80.0,
  "severity": "2",
  "resource_group": "ruriskry-prod-rg"
}
```

Detection: `"resource_id" in raw or "metric" in raw`. Passed through unchanged.

---

### Shape 2 — Common Alert Schema (use_common_alert_schema = true)

Standardised envelope with `data.essentials` and `data.alertContext`. Fired by any
alert type when `use_common_alert_schema = true` is set on the action group.

RuriSkry uses `use_common_alert_schema = false` by default because the common schema
drops metric values and thresholds. If you switch, set `use_common_alert_schema = true`
in Terraform — the normalizer handles both.

```json
{
  "schemaId": "azureMonitorCommonAlertSchema",
  "data": {
    "essentials": {
      "alertRule": "alert-vm-web-01-cpu-high",
      "severity": "Sev2",
      "targetResourceName": "vm-web-01",
      "targetResourceGroup": "ruriskry-prod-rg",
      "firedDateTime": "2026-04-11T10:30:00Z",
      "alertTargetIDs": ["/subscriptions/.../virtualMachines/vm-web-01"]
    },
    "alertContext": {
      "condition": {
        "metricName": "Percentage CPU",
        "metricValue": 95.0,
        "threshold": 80.0
      }
    }
  }
}
```

---

### Shape 3 — Non-common Log Alert V2 (use_common_alert_schema = false + scheduled query rule)

Fired by `azurerm_monitor_scheduled_query_rules_alert_v2`. The `alertContext` has
`AffectedConfigurationItems` (VM names from query results) and `SearchQuery` (raw KQL).

When the query fires on *silence* (`count = 0`, e.g. no heartbeat), both
`AffectedConfigurationItems` and `ResultCount` are empty/zero. Azure sets
`alertTargetIDs` to the **Log Analytics workspace** ARM ID, not the VM.

```json
{
  "schemaId": "Microsoft.Insights/scheduledQueryRules",
  "data": {
    "essentials": {
      "alertRule": "alert-vm-dr-01-heartbeat",
      "severity": "Sev2",
      "description": "Detects when vm-dr-01 stops sending heartbeats — idle/stopped VM",
      "alertTargetIDs": [
        "/subscriptions/xxx/resourceGroups/yyy/providers/Microsoft.OperationalInsights/workspaces/ruriskry-log-abc"
      ],
      "firedDateTime": "2026-04-11T10:30:00Z"
    },
    "alertContext": {
      "AffectedConfigurationItems": [],
      "SearchQuery": "Heartbeat | where _ResourceId =~ '...' | where TimeGenerated > ago(15m)",
      "ResultCount": 0,
      "Threshold": 0,
      "Operator": "LessThanOrEqual"
    }
  }
}
```

**Workspace pivot logic:** The normalizer detects `operationalinsights/workspaces` in
the target ID, then regex-searches the `description` and `alertRule` fields for a VM
name pattern (`\b([a-z][a-z0-9]+-[a-z0-9][-a-z0-9]*)\b`). If a match is found (e.g.
`vm-dr-01`), it extracts the subscription ID and resource group from the workspace
ARM ID and constructs the correct VM ARM ID:

```
/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Compute/virtualMachines/<name>
```

If the regex does not match, `resource_id` falls back to the workspace ARM ID. Check
backend logs for `alert-normalizer: workspace pivot` to confirm whether extraction
succeeded.

The regex matches names like `vm-dr-01`, `web-server-01`, `app-node-02` — anything
with at least one hyphen. Single-word names (e.g. `myvm`) are not matched; include the
full name in the `description` field to ensure the pivot works.

---

### Shape 4 — Classic Metric Alert (data.context)

Fired by `azurerm_monitor_metric_alert`. Has `data.context.resourceId` and
`data.context.condition.allOf[]` instead of `data.essentials`.

```json
{
  "data": {
    "context": {
      "resourceId": "/subscriptions/.../virtualMachines/vm-web-01",
      "resourceGroupName": "ruriskry-prod-rg",
      "name": "alert-vm-web-01-cpu-high",
      "timestamp": "2026-04-11T10:30:00Z",
      "severity": "Sev2",
      "condition": {
        "allOf": [
          {
            "metricName": "Percentage CPU",
            "metricValue": 95.0,
            "threshold": 80.0
          }
        ]
      }
    },
    "status": "Activated"
  }
}
```

Detection: `data.context.resourceId` or `data.context.condition` present.

---

## 8. Narrowing alert scope

The default APR scope is the entire target subscription. To narrow it, change
`scopes` in `main.tf` before your first `terraform apply`:

```hcl
# One resource group only
scopes = ["/subscriptions/${local.scan_subscription_id}/resourceGroups/your-prod-rg"]

# Multiple resource groups
scopes = [
  "/subscriptions/${local.scan_subscription_id}/resourceGroups/rg-prod-api",
  "/subscriptions/${local.scan_subscription_id}/resourceGroups/rg-prod-data",
]

# One specific resource
scopes = [
  "/subscriptions/${local.scan_subscription_id}/resourceGroups/prod-rg/providers/Microsoft.Compute/virtualMachines/vm-web-01"
]
```

You can also add `condition` blocks to filter by severity, alert rule name, or
resource type without changing the scope:

```hcl
resource "azurerm_monitor_alert_processing_rule_action_group" "ruriskry" {
  # ... existing config ...

  condition {
    severity {
      operator = "Equals"
      values   = ["Sev0", "Sev1", "Sev2"]   # ignore Sev3 (informational) and Sev4 (verbose)
    }
  }
}
```

Other supported condition types: `alert_rule_name`, `alert_rule_id`, `description`,
`monitor_service`, `monitor_condition`, `signal_type`, `target_resource_type`. See the
[AzureRM provider docs](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/monitor_alert_processing_rule_action_group)
for the full list.

---

## 9. Verifying the wiring

### Check via deploy.sh

Running `bash scripts/deploy.sh` (or `--stage2`) at any time re-checks and prints:

```
✓  Alert Processing Rule in place: apr-ruriskry-governance-fanout
✓  All alerts in sub <id> route to RuriSkry automatically (managed by Terraform).
```

### Manual CLI verification

```bash
# Read subscription values from tfvars
TARGET_SUB=$(grep target_subscription_id infrastructure/terraform-core/terraform.tfvars \
  | sed "s/.*= *\"//;s/\".*//")
INFRA_SUB=$(grep '^subscription_id' infrastructure/terraform-core/terraform.tfvars \
  | sed "s/.*= *\"//;s/\".*//")
ALERT_SUB=${TARGET_SUB:-$INFRA_SUB}

# Get the monitor resource group name from Terraform output
APR_RG=$(terraform -chdir=infrastructure/terraform-core output -raw monitor_resource_group_name)

# 1. Confirm the APR exists
az monitor alert-processing-rule show \
  --name "apr-ruriskry-governance-fanout" \
  --resource-group "$APR_RG" \
  --subscription "$ALERT_SUB" \
  --output table

# 2. Confirm the action group webhook URL is correct
BACKEND_RG=$(terraform -chdir=infrastructure/terraform-core output -raw resource_group_name 2>/dev/null \
  || echo "ruriskry-core-engine-rg")
az monitor action-group list \
  --resource-group "$BACKEND_RG" \
  --query "[].{name:name, webhook:webhookReceivers[0].serviceUri}" \
  --output table

# 3. Send a synthetic test alert (no secret configured)
BACKEND_URL=$(terraform -chdir=infrastructure/terraform-core output -raw backend_url)
curl -s -X POST "$BACKEND_URL/api/alert-trigger" \
  -H "Content-Type: application/json" \
  -d '{
    "resource_id": "test-vm-01",
    "metric": "Percentage CPU",
    "value": 95,
    "threshold": 80,
    "severity": "2",
    "resource_group": "test-rg"
  }' | jq .
# Expected: {"status":"pending","alert_id":"<uuid>"}

# 4. Confirm the record appears in the alerts list
curl -s "$BACKEND_URL/api/alerts" | jq '.[0] | {alert_id, resource_name, metric, status}'
```

---

## 10. Troubleshooting

### APR was not created — AuthorizationFailed

**Symptom:** `terraform apply` failed at
`azurerm_monitor_alert_processing_rule_action_group.ruriskry` with
`AuthorizationFailed` or `does not have authorization to perform action`.

**Cause:** The identity running `terraform apply` lacks `Monitoring Contributor` on
the target subscription.

**Fix:**

```bash
az role assignment create \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Monitoring Contributor" \
  --scope "/subscriptions/<target_subscription_id>"

# Re-run only the APR resources (fast, no other infra touched)
terraform apply -chdir=infrastructure/terraform-core \
  -target=azurerm_resource_group.ruriskry_monitor \
  -target=azurerm_monitor_alert_processing_rule_action_group.ruriskry
```

---

### Alert arrives but resource_id is a Log Analytics workspace ARM ID

**Symptom:** Monitoring Agent investigates the wrong resource (a workspace instead
of a VM). Backend logs show no `alert-normalizer: workspace pivot` line.

**Cause:** The alert rule name or description does not contain a recognisable resource
name pattern. The workspace pivot regex `\b([a-z][a-z0-9]+-[a-z0-9][-a-z0-9]*)\b`
found no match.

**Fix:** Include the VM name in the alert rule's `description` or `name`:

```hcl
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "dr01_heartbeat" {
  name        = "alert-vm-dr-01-heartbeat"          # 'vm-dr-01' matched by regex
  description = "Detects heartbeat loss on vm-dr-01 — idle/stopped VM"
  # ...
}
```

The regex matches names like `vm-dr-01`, `web-server-01`, `app-node-02` (at least one
hyphen required). Single-word names are not matched — use the `description` field to
include the full hyphenated name.

---

### Alert flood — same alert arriving every 5 minutes

**Symptom:** Many `pending` records for the same resource and metric accumulate in
the Alerts tab.

**Cause:** Either the 30-minute cooldown window is shorter than the persistent outage,
or the deduplication key (`resource_id`, `metric`) is not matching consistently because
the normalizer extracts slightly different values from consecutive payloads.

**Diagnose:**

```bash
curl -s "$BACKEND_URL/api/alerts" \
  | jq '[.[] | {resource_id, metric, status, received_at}] | sort_by(.received_at) | reverse | .[0:10]'
```

If values differ between records, inspect the `alert_payload._raw_azure_payload` field
on recent records to see what Azure is actually sending.

**Increase the cooldown** in `src/api/dashboard_api.py`:

```python
_ALERT_COOLDOWN_MINUTES = 60   # default is 30
```

---

### "Demo environment not configured — skipping webhook wiring"

**Symptom:** This message appears at the end of `deploy.sh`. Demo VMs exist but
alerts are not reaching the backend.

**Cause:** `infrastructure/terraform-demo/terraform.tfvars` does not exist, or
`infrastructure/terraform-demo/.terraform` does not exist (demo not initialised).

**Fix:**

```bash
# 1. Set up terraform-demo
cp infrastructure/terraform-demo/terraform.tfvars.example \
   infrastructure/terraform-demo/terraform.tfvars
# Edit: set subscription_id, suffix, vm_admin_password, alert_email

# 2. Initialise and apply
terraform -chdir=infrastructure/terraform-demo init
terraform -chdir=infrastructure/terraform-demo apply

# 3. Re-run deploy.sh to inject the webhook URL
bash scripts/deploy.sh --stage2
```

---

### Webhook returns 401

**Symptom:** Azure Monitor action group delivery history shows HTTP 401. Backend
logs show `Invalid or missing webhook secret`.

**Cause:** `ALERT_WEBHOOK_SECRET` is set on the backend but the action group is not
sending the matching `Authorization: Bearer <secret>` header.

**Fix:** Either disable the secret check (acceptable on a private network):

```bash
az containerapp update \
  --name "<container-app-name>" \
  --resource-group "<resource-group>" \
  --remove-env-vars ALERT_WEBHOOK_SECRET
```

Or verify the current secret value matches what the action group sends:

```bash
az keyvault secret show \
  --vault-name "<kv-name>" \
  --name "alert-webhook-secret" \
  --query value -o tsv
```

---

### Action group webhook URL is stale after backend redeployment

**Symptom:** Alerts stop arriving after a Container App revision update that changed
the FQDN.

**Cause:** This should not happen with the Terraform-managed action group —
`service_uri` is recomputed on every `terraform apply`. If it does happen, the action
group was edited manually in the Azure portal or via CLI, overwriting Terraform's value.

**Fix:**

```bash
terraform apply -chdir=infrastructure/terraform-core \
  -target=azurerm_monitor_action_group.ruriskry
```

To prevent recurrence: do not edit the action group manually. The APR description
reads "Managed by Terraform — do not edit manually" as a signal to operators.

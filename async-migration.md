# Async End-to-End Migration — Implementation Guide

> **Created by:** Claude Opus 4.6 (architecture & research)
> **To be implemented by:** Claude Sonnet 4.6 (code changes)
> **Date:** 2026-03-03
> **Baseline:** 466 tests passing, 0 failures

---

## Why This Migration Exists

The Microsoft Agent Framework (`agent_framework/_tools.py` line 501-502) runs sync
`@af.tool` callbacks **directly on the event loop** — no thread pool, no
`run_in_executor`. This means every sync Azure SDK call inside an `@af.tool`
callback blocks the entire async event loop.

```python
# From agent_framework/_tools.py:501-502 — the smoking gun
res = self.__call__(**kwargs)                           # calls sync func DIRECTLY
result = await res if inspect.isawaitable(res) else res  # no thread offload
```

In production (framework enabled), when `asyncio.gather()` runs 4 governance
agents "in parallel", they actually serialize because each agent's `@af.tool`
callback blocks the loop for ~1,100ms of Azure SDK calls.

**The fix:** Make `@af.tool` callbacks `async def` (the framework already supports
this — same line 502 will `await` the coroutine). Then use async Azure SDKs
underneath so the calls are truly non-blocking.

---

## Scope of Changes

### Files to MODIFY (6 files):

| # | File | What Changes |
|---|------|-------------|
| 1 | `src/infrastructure/resource_graph.py` | Add async methods using `azure.mgmt.resourcegraph.aio` |
| 2 | `src/infrastructure/cost_lookup.py` | Add `async get_sku_monthly_cost_async()` using `httpx.AsyncClient` |
| 3 | `src/governance_agents/blast_radius_agent.py` | Make `@af.tool` callback `async def` |
| 4 | `src/governance_agents/financial_agent.py` | Make `@af.tool` callback `async def` |
| 5 | `src/infrastructure/azure_tools.py` | Add async variants of all 5 tools |
| 6 | `src/operational_agents/cost_agent.py` | Make `@af.tool` callbacks `async def` |
| 7 | `src/operational_agents/monitoring_agent.py` | Make `@af.tool` callbacks `async def` |
| 8 | `src/operational_agents/deploy_agent.py` | Make `@af.tool` callbacks `async def` |

### File to CREATE (1 file):

| # | File | Purpose |
|---|------|---------|
| 1 | `tests/test_async_migration.py` | Tests for async infra layer |

### Files to UPDATE (docs, after implementation):

| # | File | What to update |
|---|------|---------------|
| 1 | `README.md` | Architecture section re: async-first |
| 2 | `CONTEXT.md` | Coding standards, async patterns |
| 3 | `STATUS.md` | New phase entry |
| 4 | `docs/ARCHITECTURE.md` | Async execution model detail |
| 5 | `docs/SETUP.md` | Any new deps |
| 6 | `docs/API.md` | If any API behavior changes |
| 7 | `learning/32-async-end-to-end.md` | Teaching doc |

---

## Implementation Steps

### STEP 1: `src/infrastructure/cost_lookup.py` — Add async function

**Current state:** `get_sku_monthly_cost()` (line 31) uses sync `httpx.get()` (line 90).

**What to do:** Add a new async function `get_sku_monthly_cost_async()` BELOW the
existing sync function. Do NOT delete or modify the sync function — it's still
used by the non-framework path and by mock mode.

```python
# Add this AFTER the existing get_sku_monthly_cost() function (after line 146)

async def get_sku_monthly_cost_async(
    sku: str,
    location: str,
    *,
    os_type: str = "",
) -> float | None:
    """Async variant of get_sku_monthly_cost — non-blocking HTTP call.

    Same logic, same cache, but uses httpx.AsyncClient instead of
    httpx.get so it doesn't block the event loop. Used by the async
    infrastructure layer when the Microsoft Agent Framework calls
    async @af.tool callbacks.
    """
    if not sku or not location:
        return None

    key = f"{sku.lower()}::{location.lower()}::{os_type.lower()}"
    if key in _cache:
        return _cache[key]

    try:
        filter_str = (
            f"armRegionName eq '{location}' "
            f"and armSkuName eq '{sku}' "
            f"and priceType eq 'Consumption' "
            f"and type eq 'Consumption' "
            f"and unitOfMeasure eq '1 Hour'"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                RETAIL_PRICES_URL,
                params={"$filter": filter_str},
                timeout=5.0,
            )
        resp.raise_for_status()
        items = resp.json().get("Items", [])

        # Reuse the same _is_payg and OS-aware filtering logic.
        # IMPORTANT: Define _is_payg as a module-level or nested function
        # so both sync and async variants share the exact same logic.
        # Actually, just extract the filtering into a shared helper (see below).

        # ... same filtering logic as sync version ...

    except Exception as exc:
        logger.debug(
            "cost_lookup(async): failed for sku=%s location=%s: %s", sku, location, exc
        )
        return None
```

**IMPORTANT REFACTOR:** To avoid duplicating the PAYG/OS filtering logic, extract
the post-fetch filtering into a shared private function:

```python
def _extract_monthly_cost(items: list[dict], os_type: str) -> float | None:
    """Shared filtering logic for both sync and async cost lookup.

    Given the Items list from the Azure Retail Prices API response,
    applies PAYG/OS filtering and returns the monthly cost, or None.
    """
    def _is_payg(item: dict) -> bool:
        sku_name = item.get("skuName") or ""
        return (
            item.get("retailPrice", 0) > 0
            and "Spot" not in sku_name
            and "Low Priority" not in sku_name
        )

    if os_type.lower() == "windows":
        windows_prices = [
            i["retailPrice"]
            for i in items
            if _is_payg(i) and "Windows" in (i.get("skuName") or "")
        ]
        payg_prices = windows_prices or [
            i["retailPrice"] for i in items if _is_payg(i)
        ]
    else:
        payg_prices = [
            i["retailPrice"]
            for i in items
            if _is_payg(i) and "Windows" not in (i.get("skuName") or "")
        ]

    if payg_prices:
        return round(min(payg_prices) * 730, 2)
    return None
```

Then both sync and async functions call `_extract_monthly_cost(items, os_type)` and
handle caching identically. The sync function's inline `_is_payg` moves into this
shared helper.

**Exact edit plan for cost_lookup.py:**

1. Add `_extract_monthly_cost()` as a module-level function (around line 30, before
   the sync function).
2. Refactor `get_sku_monthly_cost()` to call `_extract_monthly_cost()` instead of
   having inline filtering (lines 98-132 replaced).
3. Add `get_sku_monthly_cost_async()` after the sync function, also calling
   `_extract_monthly_cost()`.
4. Both functions share the same `_cache` dict.

---

### STEP 2: `src/infrastructure/resource_graph.py` — Add async methods

**Current state:** `ResourceGraphClient` uses sync `azure.mgmt.resourcegraph.ResourceGraphClient`
(line 77). Methods `get_resource()`, `list_all()`, `_azure_get_resource()`,
`_azure_list_all()`, `_azure_enrich_topology()` are all sync.

**What to do:** Add async variants of the Azure-mode methods. Keep the sync
versions intact for backward compatibility (non-framework path still uses them
via `asyncio.to_thread()`).

**Changes to `__init__`:** Store an async client alongside the sync one when in Azure mode.

```python
# In __init__, after the existing sync client setup (around line 80):
if not self._is_mock:
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.resourcegraph import ResourceGraphClient as AzRGClient

    credential = DefaultAzureCredential()
    self._rg_client = AzRGClient(credential)
    # Also create async client for async methods
    from azure.mgmt.resourcegraph.aio import ResourceGraphClient as AsyncAzRGClient
    self._async_rg_client = AsyncAzRGClient(credential)
    self._resources = {}
```

Wait — `DefaultAzureCredential` from `azure.identity` is sync. For the async
client, we need `azure.identity.aio.DefaultAzureCredential`. But we already
verified `azure.mgmt.resourcegraph.aio` exists. Let's check if azure.identity.aio
exists. **The Sonnet model should verify this:**

```bash
python -c "from azure.identity.aio import DefaultAzureCredential; print('async identity OK')"
```

If it doesn't exist, the sync `DefaultAzureCredential` can still be passed to the
async `ResourceGraphClient` — the Azure SDK supports this pattern (credential is
only used for token acquisition, which is a quick local operation).

**New async methods to add:**

```python
async def get_resource_async(self, resource_id: str) -> dict | None:
    """Async variant of get_resource — non-blocking Azure API calls."""
    if self._is_mock:
        return self._mock_find(resource_id)
    return await self._azure_get_resource_async(resource_id)

async def list_all_async(self) -> list[dict]:
    """Async variant of list_all."""
    if self._is_mock:
        return list(self._resources.values())
    return await self._azure_list_all_async()

async def _azure_get_resource_async(self, resource_id: str) -> dict | None:
    """Async version of _azure_get_resource."""
    from azure.mgmt.resourcegraph.models import QueryRequest

    # Same KQL construction as sync version
    is_arm_id = resource_id.startswith("/") and "/providers/" in resource_id
    if is_arm_id:
        kql = (
            "Resources"
            f" | where id =~ '{_kql_escape(resource_id)}'"
            " | extend osType = tostring(properties.storageProfile.osDisk.osType)"
            " | project id, name, type, location, tags, sku, resourceGroup, osType"
        )
    else:
        name = resource_id.split("/")[-1]
        kql = (
            "Resources"
            f" | where name =~ '{_kql_escape(name)}'"
            " | extend osType = tostring(properties.storageProfile.osDisk.osType)"
            " | project id, name, type, location, tags, sku, resourceGroup, osType"
        )
    request = QueryRequest(
        subscriptions=[self._cfg.azure_subscription_id],
        query=kql,
    )
    try:
        response = await self._async_rg_client.resources(request)
        if response.data:
            if not is_arm_id and len(response.data) > 1:
                logger.warning(
                    "ResourceGraphClient(async): short-name lookup for %r matched %d resources"
                    " — using first result; provide a full ARM ID.",
                    resource_id, len(response.data),
                )
            row = response.data[0]
            resource = {
                "id": row.get("id"),
                "name": row.get("name"),
                "type": row.get("type"),
                "location": row.get("location"),
                "tags": row.get("tags") or {},
                "sku": row.get("sku") or {},
                "resource_group": row.get("resourceGroup", ""),
                "os_type": row.get("osType", ""),
            }
            return await self._azure_enrich_topology_async(resource)
    except Exception as exc:
        logger.error("ResourceGraphClient(async): Azure query failed: %s", exc)
    return None
```

**The key win — `_azure_enrich_topology_async()`:**

The sync version runs 4 KQL queries SEQUENTIALLY (~275ms each = ~1,100ms total).
The async version runs them CONCURRENTLY via `asyncio.gather()`:

```python
async def _azure_enrich_topology_async(self, resource: dict) -> dict:
    """Async version with concurrent KQL queries via asyncio.gather()."""
    from azure.mgmt.resourcegraph.models import QueryRequest
    from src.infrastructure.cost_lookup import get_sku_monthly_cost_async

    name = resource.get("name", "")
    tags = resource.get("tags", {})
    rg = resource.get("resource_group", "")
    rid = resource.get("id", "")
    rtype = (resource.get("type") or "").lower()

    # 1. depends-on tag (instant, no query)
    depends_on_tag = tags.get("depends-on", "")
    dependencies = (
        [d.strip() for d in depends_on_tag.split(",") if d.strip()]
        if depends_on_tag else []
    )

    # 2. governs tag (instant, no query)
    governs_tag = tags.get("governs", "")
    governs = (
        [g.strip() for g in governs_tag.split(",") if g.strip()]
        if governs_tag else []
    )

    # 3. Build concurrent KQL tasks
    async def _nsg_for_vm() -> list[str]:
        """VM -> NIC -> NSG network join."""
        if "microsoft.compute/virtualmachines" not in rtype or not name:
            return []
        kql = f"""
Resources
| where name =~ '{_kql_escape(name)}'
| extend nicIds = properties.networkProfile.networkInterfaces
| mv-expand nic = nicIds
| extend nicId = tolower(tostring(nic.id))
| join kind=leftouter (
    Resources
    | where type =~ 'microsoft.network/networkinterfaces'
    | extend nsgId = tolower(tostring(properties.networkSecurityGroup.id))
    | project id=tolower(id), nsgId
) on $left.nicId == $right.id
| extend nsgName = tostring(split(nsgId, '/')[8])
| where isnotempty(nsgName)
| project nsgName
"""
        try:
            req = QueryRequest(
                subscriptions=[self._cfg.azure_subscription_id], query=kql
            )
            resp = await self._async_rg_client.resources(req)
            return [row.get("nsgName", "") for row in (resp.data or []) if row.get("nsgName")]
        except Exception as exc:
            logger.debug("enrich_topology(async): NSG KQL failed for %s: %s", name, exc)
            return []

    async def _vms_behind_nsg() -> list[str]:
        """NSG governs — which VMs sit behind this NSG."""
        if "microsoft.network/networksecuritygroups" not in rtype or not rid:
            return []
        kql = f"""
Resources
| where type =~ 'microsoft.network/networkinterfaces'
| where resourceGroup =~ '{_kql_escape(rg)}'
| where properties.networkSecurityGroup.id =~ '{_kql_escape(rid)}'
| extend vmId = tostring(properties.virtualMachine.id)
| where isnotempty(vmId)
| extend vmName = tostring(split(vmId, '/')[8])
| project vmName
"""
        try:
            req = QueryRequest(
                subscriptions=[self._cfg.azure_subscription_id], query=kql
            )
            resp = await self._async_rg_client.resources(req)
            return [row.get("vmName", "") for row in (resp.data or []) if row.get("vmName")]
        except Exception as exc:
            logger.debug("enrich_topology(async): NSG-governs KQL failed for %s: %s", name, exc)
            return []

    async def _reverse_dependents() -> list[str]:
        """Reverse lookup: who depends on this resource."""
        if not name:
            return []
        kql = f"""
Resources
| where isnotempty(tags['depends-on'])
| extend _deps = split(tags['depends-on'], ',')
| mv-expand _dep = _deps
| where trim(' ', tostring(_dep)) =~ '{_kql_escape(name)}'
| distinct name
"""
        try:
            req = QueryRequest(
                subscriptions=[self._cfg.azure_subscription_id], query=kql
            )
            resp = await self._async_rg_client.resources(req)
            return [
                row.get("name", "")
                for row in (resp.data or [])
                if row.get("name") and row.get("name") != name
            ]
        except Exception as exc:
            logger.debug("enrich_topology(async): reverse-lookup failed for %s: %s", name, exc)
            return []

    async def _get_cost() -> float | None:
        """Monthly cost from Azure Retail Prices API."""
        sku_name = (resource.get("sku") or {}).get("name", "")
        location = resource.get("location", "")
        os_type = resource.get("os_type", "")
        return await get_sku_monthly_cost_async(sku_name, location, os_type=os_type)

    # ── Run ALL 4 queries concurrently ──────────────────────────────
    import asyncio
    nsg_names, governed_vms, dependents, monthly_cost = await asyncio.gather(
        _nsg_for_vm(),
        _vms_behind_nsg(),
        _reverse_dependents(),
        _get_cost(),
    )

    # Merge results
    for nsg in nsg_names:
        if nsg not in dependencies:
            dependencies.append(nsg)
    for vm in governed_vms:
        if vm not in governs:
            governs.append(vm)

    resource.update({
        "dependencies": dependencies,
        "dependents": dependents,
        "governs": governs,
        "services_hosted": [],
        "consumers": [],
        "monthly_cost": monthly_cost,
    })
    return resource
```

**CRITICAL:** The `asyncio` import should be at the top of the file (it's already
imported in blast_radius_agent.py but needs adding to resource_graph.py if missing).

---

### STEP 3: `src/governance_agents/blast_radius_agent.py` — Async `@af.tool`

**Current state:** The `@af.tool` callback `evaluate_blast_radius_rules` (line 255)
is sync. In framework mode, it calls `self._evaluate_rules(a)` which calls
`self._find_resource()` which calls `self._rg_client.get_resource()` (sync Azure).

**What to change:**

1. Add an async version of `_evaluate_rules` that uses async ResourceGraphClient.

2. Make the `@af.tool` callback `async def`.

**The key insight:** In framework mode (`_evaluate_with_framework`), the `@af.tool`
callback needs to call the async infrastructure. But `_evaluate_rules` itself has
multiple helper calls (`_find_resource`, `_detect_spofs`, `_get_affected_zones`)
that each do Azure lookups. We need async versions of these helpers.

**Approach — add `_evaluate_rules_async()`:**

```python
async def _evaluate_rules_async(self, action: ProposedAction) -> BlastRadiusResult:
    """Async rule-based evaluation — uses async ResourceGraphClient."""
    resource = await self._find_resource_async(action.target.resource_id)
    affected_resources = self._get_affected_resources(resource)  # pure dict traversal, no IO
    affected_services = self._get_affected_services(resource)    # pure dict traversal, no IO
    spofs = await self._detect_spofs_async(resource, affected_resources)
    zones = await self._get_affected_zones_async(resource, affected_resources)

    score = self._calculate_score(
        action=action, resource=resource,
        affected_resources=affected_resources,
        affected_services=affected_services, spofs=spofs,
    )
    reasoning = self._build_reasoning(action, resource, score, affected_resources, spofs)

    return BlastRadiusResult(
        sri_infrastructure=score,
        affected_resources=affected_resources,
        affected_services=affected_services,
        single_points_of_failure=spofs,
        availability_zones_impacted=zones,
        reasoning=reasoning,
    )

async def _find_resource_async(self, resource_id: str) -> dict | None:
    if self._rg_client is not None:
        return await self._rg_client.get_resource_async(resource_id)
    # Mock mode (sync is fine, no IO)
    if resource_id in self._resources:
        return self._resources[resource_id]
    name = resource_id.split("/")[-1]
    return self._resources.get(name)

async def _detect_spofs_async(self, resource, affected_resources):
    spofs = []
    if resource and resource.get("tags", {}).get("criticality") == "critical":
        spofs.append(resource["name"])
    for name in affected_resources:
        if self._rg_client is not None:
            r = await self._rg_client.get_resource_async(name)
        else:
            r = self._resources.get(name)
        if r and r.get("tags", {}).get("criticality") == "critical":
            if name not in spofs:
                spofs.append(name)
    return spofs

async def _get_affected_zones_async(self, resource, affected_resources):
    zones = []
    if resource:
        loc = resource.get("location")
        if loc:
            zones.append(loc)
    for name in affected_resources:
        if self._rg_client is not None:
            r = await self._rg_client.get_resource_async(name)
        else:
            r = self._resources.get(name)
        if r:
            loc = r.get("location")
            if loc and loc not in zones:
                zones.append(loc)
    return zones
```

**Then update `_evaluate_with_framework()`:**

Change the `@af.tool` callback from sync to async (around line 246-263):

```python
# BEFORE (line 255):
def evaluate_blast_radius_rules(action_json: str) -> str:

# AFTER:
async def evaluate_blast_radius_rules(action_json: str) -> str:
    """Evaluate infrastructure blast radius using rule-based scoring."""
    try:
        a = ProposedAction.model_validate_json(action_json)
    except Exception:
        a = action
    r = await self._evaluate_rules_async(a)
    result_holder.append(r)
    return r.model_dump_json()
```

**Also update the non-framework evaluate() path.** Currently (lines 201-207):

```python
if not self._use_framework:
    if self._rg_client is not None:
        return await asyncio.to_thread(self._evaluate_rules, action)
    return self._evaluate_rules(action)
```

Change to use the async path when rg_client exists:

```python
if not self._use_framework:
    if self._rg_client is not None:
        return await self._evaluate_rules_async(action)
    return self._evaluate_rules(action)  # mock: pure in-memory, no IO
```

This replaces `asyncio.to_thread()` with a truly async call. The `asyncio` import
can stay for other uses but `to_thread` is no longer needed in this file.

**Also update the framework fallback** (line 215):

```python
# BEFORE:
return self._evaluate_rules(action)

# AFTER — use async if rg_client exists:
if self._rg_client is not None:
    return await self._evaluate_rules_async(action)
return self._evaluate_rules(action)
```

---

### STEP 4: `src/governance_agents/financial_agent.py` — Same pattern

**Exact same pattern as blast_radius_agent.** The financial agent's `@af.tool`
callback (line 267) calls `self._evaluate_rules(a)` which calls
`self._find_resource()` → sync Azure SDK.

**Changes needed:**

1. Add `_evaluate_rules_async()` — only difference from sync: calls
   `_find_resource_async()`.
2. Add `_find_resource_async()` — uses `self._rg_client.get_resource_async()`.
3. Make `@af.tool evaluate_financial_rules` → `async def`.
4. Update `evaluate()` non-framework path: replace `asyncio.to_thread()` with
   `await self._evaluate_rules_async(action)`.
5. Update framework fallback to use async when rg_client exists.

Note: `_estimate_cost_change`, `_detect_over_optimisation`, `_build_projection`,
`_calculate_score`, `_build_reasoning` are all pure computation (no IO). They stay
sync and are called from within `_evaluate_rules_async()` without issues.

---

### STEP 5: `src/infrastructure/azure_tools.py` — Add async variants

**Current state:** 5 sync functions used by ops agents' `@af.tool` callbacks.

**What to do:** Add async variants of each function. The mock paths return instantly
(no IO), so we can just `return` mock data directly in the async function. The live
paths use async Azure SDK clients.

**Naming convention:** Add `_async` suffix: `query_resource_graph_async`, etc.

**For `query_resource_graph_async`:**

```python
async def query_resource_graph_async(kusto_query: str, subscription_id: str = "") -> list[dict]:
    """Async variant of query_resource_graph — non-blocking Azure API calls."""
    if _use_mocks():
        return _mock_query_resource_graph(kusto_query)

    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.resourcegraph.aio import ResourceGraphClient
        from azure.mgmt.resourcegraph.models import QueryRequest
        from src.config import settings

        sub_id = subscription_id or settings.azure_subscription_id
        credential = DefaultAzureCredential()
        async with ResourceGraphClient(credential) as client:
            request = QueryRequest(
                subscriptions=[sub_id] if sub_id else [],
                query=kusto_query,
            )
            result = await client.resources(request)
            return [dict(row) for row in (result.data or [])]
    except Exception as exc:
        raise RuntimeError(
            f"azure_tools.query_resource_graph_async failed. "
            f"Query attempted: {kusto_query!r}. Error: {exc}. "
            "Run 'az login' and ensure AZURE_SUBSCRIPTION_ID is configured."
        ) from exc
```

**For `query_metrics_async`:**

```python
async def query_metrics_async(
    resource_id: str, metric_names: list[str], timespan: str = "PT24H"
) -> dict:
    """Async variant of query_metrics."""
    if _use_mocks():
        return _mock_query_metrics(resource_id, metric_names, timespan)

    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.query.aio import MetricsQueryClient

        credential = DefaultAzureCredential()
        async with MetricsQueryClient(credential) as client:
            result = await client.query_resource(
                resource_uri=resource_id,
                metric_names=metric_names,
                timespan=_parse_duration(timespan),
            )
            # ... same processing logic as sync version ...
    except Exception as exc:
        raise RuntimeError(...) from exc
```

**IMPORTANT NOTE for Sonnet:** `azure.monitor.query` is NOT installed in the current
venv. The ops agents (`cost_agent`, `monitoring_agent`) import it at runtime inside
the live-mode branch. In mock mode it's never imported. The async variant
`azure.monitor.query.aio` will similarly only be imported in the live branch.
This means:
- Mock-mode tests will pass without installing it.
- Live-mode requires `pip install azure-monitor-query`.
- The current test suite runs entirely in mock mode, so no new deps needed for tests.

**For `get_resource_details_async`:**

```python
async def get_resource_details_async(resource_id: str) -> dict:
    """Async variant of get_resource_details."""
    safe_id = resource_id.replace("'", "''")
    results = await query_resource_graph_async(f"Resources | where id =~ '{safe_id}'")
    if results:
        return results[0]
    if _use_mocks():
        name = resource_id.split("/")[-1] if "/" in resource_id else resource_id
        for r in _seed().get("resources", []):
            if r.get("name", "").lower() == name.lower():
                return r
    return {}
```

**For `query_activity_log_async`:**

```python
async def query_activity_log_async(resource_group: str, timespan: str = "P7D") -> list[dict]:
    """Async variant of query_activity_log."""
    if _use_mocks():
        return _mock_activity_log(resource_group)

    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.query.aio import LogsQueryClient
        from azure.monitor.query import LogsQueryStatus
        from src.config import settings

        workspace_id = settings.log_analytics_workspace_id
        if not workspace_id:
            raise ValueError("LOG_ANALYTICS_WORKSPACE_ID is not configured.")

        credential = DefaultAzureCredential()
        async with LogsQueryClient(credential) as client:
            kql = (
                "AzureActivity "
                f"| where ResourceGroup =~ '{resource_group}' "
                "| order by TimeGenerated desc "
                "| take 50 "
                "| project TimeGenerated, OperationNameValue, ActivityStatusValue, "
                "Caller, ResourceType, Resource, Level"
            )
            result = await client.query_workspace(
                workspace_id=workspace_id,
                query=kql,
                timespan=_parse_duration(timespan),
            )
            if result.status == LogsQueryStatus.SUCCESS:
                rows = []
                for row in result.table.rows:
                    rows.append({
                        "timestamp": str(row[0]), "operation": str(row[1]),
                        "status": str(row[2]), "caller": str(row[3]),
                        "resource_type": str(row[4]), "resource": str(row[5]),
                        "level": str(row[6]),
                    })
                return rows
            return []
    except Exception as exc:
        raise RuntimeError(...) from exc
```

**For `list_nsg_rules_async`:**

```python
async def list_nsg_rules_async(nsg_resource_id: str) -> list[dict]:
    """Async variant of list_nsg_rules."""
    details = await get_resource_details_async(nsg_resource_id)
    props = details.get("properties", {})
    rules = props.get("securityRules", [])
    if rules:
        return rules
    seed_rules = details.get("rules", [])
    if seed_rules:
        return seed_rules
    if _use_mocks():
        name = nsg_resource_id.split("/")[-1] if "/" in nsg_resource_id else nsg_resource_id
        for r in _seed().get("resources", []):
            if r.get("name", "").lower() == name.lower() and "networkSecurityGroups" in r.get("type", ""):
                return r.get("rules", [])
    return []
```

---

### STEP 6: Ops Agents — Make `@af.tool` callbacks async

**All 3 ops agents follow the exact same pattern.** Each has 5-6 `@af.tool`
callbacks that call sync `azure_tools` functions. Change each to `async def` and
call the `_async` variant.

**For each ops agent (`cost_agent.py`, `monitoring_agent.py`, `deploy_agent.py`):**

1. Update imports to include async variants:
   ```python
   from src.infrastructure.azure_tools import (
       query_resource_graph, query_resource_graph_async,
       query_metrics, query_metrics_async,
       get_resource_details, get_resource_details_async,
       query_activity_log, query_activity_log_async,
       list_nsg_rules, list_nsg_rules_async,
   )
   ```

2. Change each `@af.tool` callback from `def` to `async def` and replace the
   azure_tools call with its async variant.

   Example for cost_agent.py:
   ```python
   # BEFORE:
   @af.tool(name="query_resource_graph", ...)
   def tool_query_resource_graph(kusto_query: str) -> str:
       data = query_resource_graph(kusto_query)
       return json.dumps(data, default=str)

   # AFTER:
   @af.tool(name="query_resource_graph", ...)
   async def tool_query_resource_graph(kusto_query: str) -> str:
       data = await query_resource_graph_async(kusto_query)
       return json.dumps(data, default=str)
   ```

3. The `propose_action` tool callback does NOT call azure_tools — it's pure
   validation + list append. It can stay `sync` or become `async` — doesn't matter.
   Keep it sync to avoid unnecessary change.

**File-specific notes:**

- `cost_agent.py`: 5 azure_tools callbacks + 1 propose_action (keep sync)
- `monitoring_agent.py`: 5 azure_tools callbacks + 1 propose_action (keep sync)
- `deploy_agent.py`: 4 azure_tools callbacks (no `query_metrics`) + 1 propose_action (keep sync)

---

### STEP 7: Tests — `tests/test_async_migration.py`

Create a new test file focused on the async layer. Tests should verify:

1. **`get_sku_monthly_cost_async` basic behavior** — mock httpx.AsyncClient, verify
   correct URL/params, verify cache sharing with sync variant.

2. **`_extract_monthly_cost` shared helper** — test OS-aware filtering (reuse
   existing test data from test_live_topology.py).

3. **`ResourceGraphClient.get_resource_async`** — mock mode returns same result as
   sync `get_resource`. Verify by creating client in mock mode and comparing.

4. **`_azure_enrich_topology_async` concurrent execution** — verify that
   `asyncio.gather` is used (mock the async_rg_client, verify all queries fire).

5. **`BlastRadiusAgent` framework path uses async tool** — patch the framework so
   the tool callback is called, verify it's awaited (not blocking).

6. **`FinancialImpactAgent` framework path uses async tool** — same pattern.

7. **Async azure_tools variants** — verify `query_resource_graph_async` returns
   same mock data as sync version. Same for all 5 functions.

**Test structure:**

```python
"""Tests for async end-to-end infrastructure migration.

Verifies that the async variants of ResourceGraphClient, cost_lookup, and
azure_tools produce identical results to their sync counterparts and that
the @af.tool callbacks in governance/ops agents are async-compatible.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCostLookupAsync:
    """Async cost lookup uses httpx.AsyncClient and shares cache."""

    @pytest.mark.asyncio
    async def test_async_returns_same_as_sync(self):
        """Both variants return identical results for the same input."""
        # ... mock httpx and httpx.AsyncClient with same response ...

    @pytest.mark.asyncio
    async def test_async_shares_cache_with_sync(self):
        """Cache populated by sync is read by async and vice versa."""
        # ... populate cache via sync, read via async ...

    @pytest.mark.asyncio
    async def test_extract_monthly_cost_shared_logic(self):
        """The shared _extract_monthly_cost helper works correctly."""
        # ... test with Windows/Linux/empty os_type ...


class TestResourceGraphClientAsync:
    """Async methods on ResourceGraphClient."""

    @pytest.mark.asyncio
    async def test_mock_mode_async_matches_sync(self):
        """In mock mode, async and sync return identical results."""

    @pytest.mark.asyncio
    async def test_enrich_topology_uses_gather(self):
        """Async enrichment fires concurrent KQL queries."""


class TestAsyncAzureTools:
    """Async variants of azure_tools functions."""

    @pytest.mark.asyncio
    async def test_query_resource_graph_async_mock(self):
        """Mock mode returns same data as sync variant."""

    # ... similar for other 4 functions ...


class TestGovernanceAgentAsyncTools:
    """Governance agents' @af.tool callbacks are async."""

    @pytest.mark.asyncio
    async def test_blast_radius_tool_is_async(self):
        """The evaluate_blast_radius_rules tool is an async function."""

    @pytest.mark.asyncio
    async def test_financial_tool_is_async(self):
        """The evaluate_financial_rules tool is an async function."""
```

**IMPORTANT:** Ensure `pytest-asyncio` is installed. Check with:
```bash
pip show pytest-asyncio
```
If not installed: `pip install pytest-asyncio`.

Also check if the project uses `asyncio_mode = "auto"` in pytest config. If not,
each test needs the `@pytest.mark.asyncio` decorator.

---

### STEP 8: Run Full Test Suite

After all code changes, run the FULL test suite:

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

**Expected:** All 466 existing tests PASS (no regressions) + new async tests PASS.

**If any existing test fails:**
- The sync paths MUST remain unchanged. Only new async methods were added.
- The `evaluate()` method routing should still call sync `_evaluate_rules()` in
  mock mode (when `_rg_client is None`).
- Mock mode never touches async code paths.

**Run a targeted test to verify no mock-mode regression:**
```bash
python -m pytest tests/test_blast_radius.py tests/test_financial_agent.py -v --tb=short
```

---

### STEP 9: Update Documentation

After all tests pass, update these files. Be surgical — only add/modify sections
relevant to the async migration. Do NOT rewrite entire files.

#### 9a. `STATUS.md`

Add a new phase entry in the Quick State Summary table and the detailed phases
section. Use the pattern of existing entries. Call it **Phase 20 — Async
End-to-End Infrastructure Calls**.

Key points to include:
- `@af.tool` callbacks now `async def` — non-blocking event loop
- `ResourceGraphClient` has async methods using `azure.mgmt.resourcegraph.aio`
- `_azure_enrich_topology_async()` runs 4 KQL queries concurrently via `asyncio.gather()`
- `get_sku_monthly_cost_async()` uses `httpx.AsyncClient`
- `azure_tools.py` has async variants of all 5 functions
- Sync paths preserved for mock mode (no regression)
- Performance: ~1,100ms → ~300ms per governance agent enrichment

#### 9b. `CONTEXT.md`

In the coding standards / patterns section, add a note about the async pattern:
- `@af.tool` callbacks MUST be `async def` when they perform IO (Azure SDK calls)
- The agent framework supports both sync and async tools (line 502 of `_tools.py`)
- Use `async with` for Azure SDK async clients (they implement `__aenter__/__aexit__`)
- Share caches between sync/async variants (same `_cache` dict)

#### 9c. `docs/ARCHITECTURE.md`

Update the execution flow diagram / description to reflect:
- `asyncio.gather()` over 4 governance agents is now TRULY parallel (not serialized by blocking tools)
- `_azure_enrich_topology_async()` runs 4 KQL queries concurrently
- Mention the `agent_framework/_tools.py:501-502` discovery

#### 9d. `README.md`

In the architecture or features section, update any mention of "async-first" to
reflect that it's now truly async end-to-end, not just at the pipeline level.

#### 9e. `docs/SETUP.md`

No new dependencies required for mock mode. If adding `azure-monitor-query` for
live mode, mention it. Otherwise, no changes needed.

#### 9f. `docs/API.md`

No API endpoint changes. No updates needed unless the response times or behavior
section mentions performance characteristics.

---

### STEP 10: Create Learning Doc

Create `learning/32-async-end-to-end.md` with:

1. **What was built** — Async end-to-end infrastructure calls
2. **Why** — `@af.tool` sync callbacks block the event loop (with code reference)
3. **Python concepts:**
   - `async def` vs `def` in the context of `@af.tool` decorator
   - `asyncio.gather()` for concurrent coroutines
   - `async with` context managers for Azure SDK clients
   - Shared mutable state (`_cache` dict) between sync and async code
   - `inspect.isawaitable()` — how the framework detects async tools
4. **Design pattern:** Dual sync/async API (keep sync for backward compat, add
   async for production performance)
5. **Performance impact:** Sequential (~1,100ms per agent) → concurrent (~300ms)
6. **Key takeaway:** Always check how your framework executes tool callbacks.
   Assumptions about thread pools can be wrong — read the source code.

---

### STEP 11: Update Memory

Update `C:\Users\THISPC\.claude\projects\E--AI-Hackathon-sentinellayer\memory\MEMORY.md`
with a new section for Phase 20.

---

## Verification Checklist

Before considering this migration complete, verify ALL of these:

- [ ] `get_sku_monthly_cost_async()` exists and shares `_cache` with sync variant
- [ ] `_extract_monthly_cost()` shared helper exists and both sync/async use it
- [ ] `ResourceGraphClient.get_resource_async()` exists and works in mock mode
- [ ] `ResourceGraphClient._azure_enrich_topology_async()` uses `asyncio.gather()`
- [ ] `BlastRadiusAgent._evaluate_with_framework()` has `async def` tool callback
- [ ] `BlastRadiusAgent.evaluate()` non-framework live path uses `_evaluate_rules_async`
- [ ] `FinancialImpactAgent._evaluate_with_framework()` has `async def` tool callback
- [ ] `FinancialImpactAgent.evaluate()` non-framework live path uses `_evaluate_rules_async`
- [ ] All 5 `azure_tools.py` async variants exist
- [ ] All 3 ops agents' `@af.tool` callbacks are `async def`
- [ ] All 466 existing tests still pass
- [ ] New async tests pass
- [ ] Sync paths are UNTOUCHED for mock mode
- [ ] No new pip dependencies required for test suite
- [ ] Documentation updated (STATUS.md, CONTEXT.md, ARCHITECTURE.md, etc.)
- [ ] Learning doc created (`learning/32-async-end-to-end.md`)
- [ ] Memory file updated

---

## Important Warnings

1. **Do NOT delete sync functions.** They are still used by:
   - Mock mode (no IO, no reason to be async)
   - `asyncio.to_thread()` fallback (can be removed from blast_radius/financial
     agents after async paths are verified)
   - Any external code that imports them directly

2. **Do NOT change the `_evaluate_rules()` sync method.** It's the core
   deterministic logic. The async variant (`_evaluate_rules_async`) wraps it by
   replacing only the IO calls (find_resource, detect_spofs, get_affected_zones)
   with async equivalents.

3. **Do NOT add `asyncio_mode = "auto"` to pytest config** unless it's already
   there. Use `@pytest.mark.asyncio` on individual tests instead.

4. **The `propose_action` tool callback in ops agents should stay sync.** It does
   no IO — just validation and list append. Making it async adds no value.

5. **`azure.monitor.query` is not installed.** The async variants for
   `query_metrics_async` and `query_activity_log_async` will import from
   `azure.monitor.query.aio` only in the live-mode branch. Tests run in mock mode
   and never hit this import. This is the existing pattern — don't change it.

6. **Cache thread safety:** The `_cache` dict in `cost_lookup.py` is shared between
   sync and async variants. In CPython, dict operations are GIL-protected, so this
   is safe. Do NOT add locks — they'd add complexity with no benefit in CPython.

---

## Prompt for Sonnet

When switching to Sonnet, give it this prompt:

> Read `async-migration.md` in the project root. It contains a detailed
> step-by-step implementation guide for making infrastructure calls async
> end-to-end. Follow it exactly — all 11 steps. The guide was written by Opus
> after deep analysis of the codebase and the Microsoft Agent Framework source
> code. Start with Step 1 (cost_lookup.py), work through each step sequentially,
> run the full test suite at Step 8, then update docs and create the learning file.
> The baseline is 466 tests passing. Do not break any existing tests.

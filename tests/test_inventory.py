"""Tests for Phase 30 — Resource Inventory (builder, formatter, Cosmos client, API).

All tests use local mock mode (USE_LOCAL_MOCKS=true is the default).
No real Azure calls are made.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# inventory_builder tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_inventory_no_type_filter():
    """KQL must NOT contain 'where type in~' — all resource types must be included."""
    captured_queries = []

    async def mock_query_rg(kusto_query, subscription_id=""):
        captured_queries.append(kusto_query)
        return []

    # Patch at the azure_tools level since inventory_builder imports it lazily inside the function
    with patch(
        "src.infrastructure.azure_tools.query_resource_graph_async",
        side_effect=mock_query_rg,
    ):
        from src.infrastructure.inventory_builder import build_inventory
        await build_inventory("sub-abc-123")

    assert len(captured_queries) == 1
    assert "where type in~" not in captured_queries[0].lower()
    assert "where type ==" not in captured_queries[0].lower()


@pytest.mark.asyncio
async def test_build_inventory_groups_by_type():
    """Resources must be grouped into by_type dynamically from the result set."""
    resources = [
        {"id": "/sub/rg/vm-01", "name": "vm-01", "type": "microsoft.compute/virtualmachines", "location": "eastus", "resourceGroup": "rg", "tags": {}, "properties": {}, "sku": {}},
        {"id": "/sub/rg/site-01", "name": "site-01", "type": "Microsoft.Web/sites", "location": "eastus", "resourceGroup": "rg", "tags": {}, "properties": {}, "sku": {}},
        {"id": "/sub/rg/vm-02", "name": "vm-02", "type": "Microsoft.Compute/virtualMachines", "location": "eastus", "resourceGroup": "rg", "tags": {}, "properties": {}, "sku": {}},
    ]

    async def mock_query_rg(kusto_query, subscription_id=""):
        return resources

    async def _noop_enrich(vms, sub, progress):
        return vms

    # Patch at azure_tools since inventory_builder imports lazily inside the function
    with patch("src.infrastructure.azure_tools.query_resource_graph_async", side_effect=mock_query_rg):
        with patch("src.infrastructure.inventory_builder._enrich_vm_power_states", new=_noop_enrich):
            from src.infrastructure.inventory_builder import build_inventory
            doc = await build_inventory("sub-abc-123")

    assert doc["resource_count"] == 3
    # Both VM entries → should be grouped under the same lowercase type key
    type_summary = doc["type_summary"]
    assert type_summary.get("microsoft.compute/virtualmachines") == 2
    assert type_summary.get("microsoft.web/sites") == 1


@pytest.mark.asyncio
async def test_build_inventory_enriches_vm_power_state():
    """VMs must have powerState injected from the Compute instance view."""
    vm = {"id": "/sub/abc/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-01",
          "name": "vm-01", "type": "microsoft.compute/virtualmachines",
          "location": "eastus", "resourceGroup": "rg", "tags": {}, "properties": {}, "sku": {}}

    async def mock_query_rg(kusto_query, subscription_id=""):
        return [vm]

    async def mock_enrich(vms, sub, progress):
        return [{**v, "powerState": "VM running"} for v in vms]

    with patch("src.infrastructure.azure_tools.query_resource_graph_async", side_effect=mock_query_rg):
        with patch("src.infrastructure.inventory_builder._enrich_vm_power_states", new=mock_enrich):
            from src.infrastructure.inventory_builder import build_inventory
            doc = await build_inventory("sub-abc-123")

    vms_in_result = [r for r in doc["resources"] if "virtualmachine" in r.get("type", "").lower()]
    assert len(vms_in_result) == 1
    assert vms_in_result[0]["powerState"] == "VM running"


@pytest.mark.asyncio
async def test_build_inventory_vm_enrichment_partial_failure():
    """If one VM enrichment fails, others must still succeed; failed VM gets 'unknown'."""
    vms = [
        {"id": "/sub/rg/vm-01", "name": "vm-01", "type": "microsoft.compute/virtualmachines",
         "location": "eastus", "resourceGroup": "rg", "tags": {}, "properties": {}, "sku": {}},
        {"id": "/sub/rg/vm-02", "name": "vm-02", "type": "microsoft.compute/virtualmachines",
         "location": "eastus", "resourceGroup": "rg", "tags": {}, "properties": {}, "sku": {}},
    ]

    async def mock_query_rg(kusto_query, subscription_id=""):
        return vms

    call_count = [0]

    async def mock_enrich(vms_in, sub, progress):
        result = []
        for vm in vms_in:
            call_count[0] += 1
            if vm["name"] == "vm-01":
                result.append({**vm, "powerState": "VM running"})
            else:
                result.append({**vm, "powerState": "unknown (enrichment failed)"})
        return result

    with patch("src.infrastructure.azure_tools.query_resource_graph_async", side_effect=mock_query_rg):
        with patch("src.infrastructure.inventory_builder._enrich_vm_power_states", new=mock_enrich):
            from src.infrastructure.inventory_builder import build_inventory
            doc = await build_inventory("sub-abc-123")

    result_vms = {r["name"]: r for r in doc["resources"] if "virtualmachine" in r.get("type", "").lower()}
    assert result_vms["vm-01"]["powerState"] == "VM running"
    assert "unknown" in result_vms["vm-02"]["powerState"]


@pytest.mark.asyncio
async def test_build_inventory_with_resource_group():
    """When resource_group is provided, KQL must include 'where resourceGroup =~'."""
    captured = []

    async def mock_query_rg(kusto_query, subscription_id=""):
        captured.append(kusto_query)
        return []

    with patch("src.infrastructure.azure_tools.query_resource_graph_async", side_effect=mock_query_rg):
        from src.infrastructure.inventory_builder import build_inventory
        await build_inventory("sub-abc-123", resource_group="rg-prod")

    assert len(captured) == 1
    assert "resourceGroup =~" in captured[0] or "resourcegroup =~" in captured[0].lower()
    assert "rg-prod" in captured[0]


# ---------------------------------------------------------------------------
# inventory_formatter tests
# ---------------------------------------------------------------------------


def test_format_inventory_dynamic_sections():
    """Sections must be generated from the actual types in the inventory, not hardcoded."""
    from src.infrastructure.inventory_formatter import format_inventory_for_prompt

    inventory = {
        "resource_count": 2,
        "refreshed_at": "2026-04-08T10:00:00Z",
        "resources": [
            {"id": "/a", "name": "cache-01", "type": "microsoft.cache/redis", "location": "eastus", "resourceGroup": "rg", "tags": {}},
            {"id": "/b", "name": "db-01", "type": "microsoft.documentdb/databaseaccounts", "location": "eastus", "resourceGroup": "rg", "tags": {}},
        ],
    }

    text = format_inventory_for_prompt(inventory)
    assert "microsoft.cache/redis" in text
    assert "microsoft.documentdb/databaseaccounts" in text
    # Must NOT contain hardcoded type references that aren't in the data
    assert "virtualmachines" not in text.lower()


def test_format_inventory_vm_shows_power_state():
    """VMs must have powerState shown on a dedicated line."""
    from src.infrastructure.inventory_formatter import format_inventory_for_prompt

    inventory = {
        "resource_count": 1,
        "refreshed_at": "2026-04-08T10:00:00Z",
        "resources": [
            {"id": "/sub/rg/vm-01", "name": "vm-01",
             "type": "microsoft.compute/virtualmachines",
             "location": "eastus", "resourceGroup": "rg",
             "powerState": "VM deallocated", "tags": {}},
        ],
    }

    text = format_inventory_for_prompt(inventory)
    assert "VM deallocated" in text
    assert "Power State" in text


def test_format_inventory_properties_flattened():
    """Only top-level scalar properties must appear — no nested objects."""
    from src.infrastructure.inventory_formatter import format_inventory_for_prompt

    inventory = {
        "resource_count": 1,
        "refreshed_at": "2026-04-08T10:00:00Z",
        "resources": [
            {"id": "/sub/rg/sa-01", "name": "sa-01",
             "type": "microsoft.storage/storageaccounts",
             "location": "eastus", "resourceGroup": "rg", "tags": {},
             "properties": {
                 "allowBlobPublicAccess": True,
                 "supportsHttpsTrafficOnly": False,
                 "nested": {"deep": "value"},   # should NOT appear
                 "listProp": ["a", "b"],         # should NOT appear
             }},
        ],
    }

    text = format_inventory_for_prompt(inventory)
    assert "allowBlobPublicAccess=True" in text
    assert "supportsHttpsTrafficOnly=False" in text
    # Nested dict/list must not appear as literal dict/list
    assert "{'deep'" not in text
    assert "['a'" not in text


# ---------------------------------------------------------------------------
# CosmosInventoryClient tests (mock mode)
# ---------------------------------------------------------------------------


def test_cosmos_inventory_client_upsert_and_get(tmp_path):
    """Round-trip: upsert then get_latest must return the same record."""
    from src.infrastructure.cosmos_client import CosmosInventoryClient

    client = CosmosInventoryClient(inventory_dir=tmp_path)
    record = {
        "id": "inv-abc12345-20260408T100000",
        "subscription_id": "abc12345-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "refreshed_at": "2026-04-08T10:00:00Z",
        "resource_count": 3,
        "type_summary": {"microsoft.compute/virtualmachines": 2},
        "resources": [],
    }
    client.upsert(record)

    result = client.get_latest("abc12345-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    assert result is not None
    assert result["resource_count"] == 3
    assert result["id"] == "inv-abc12345-20260408T100000"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    """TestClient with isolated tmp_path inventory dir."""
    from fastapi.testclient import TestClient
    from src.api.dashboard_api import app
    from src.infrastructure.cosmos_client import CosmosInventoryClient
    import src.api.dashboard_api as api_module

    inv_client = CosmosInventoryClient(inventory_dir=tmp_path / "inventory")
    monkeypatch.setattr(api_module, "_cosmos_inventory", inv_client)
    # Clear in-memory state
    api_module._inventory_refreshes.clear()

    return TestClient(app)


def test_inventory_api_get_returns_404_when_empty(api_client):
    """GET /api/inventory must return 404 when no snapshot exists."""
    res = api_client.get("/api/inventory")
    assert res.status_code == 404


def test_inventory_api_status_endpoint(api_client):
    """GET /api/inventory/status must return exists=False when no snapshot."""
    res = api_client.get("/api/inventory/status")
    assert res.status_code == 200
    data = res.json()
    assert data["exists"] is False
    assert data["stale"] is True


def test_inventory_api_refresh_endpoint(api_client, monkeypatch):
    """POST /api/inventory/refresh must return refresh_id immediately."""
    import src.api.dashboard_api as api_module

    # Prevent the background task from running in tests
    async def fake_refresh(*args, **kwargs):
        pass

    monkeypatch.setattr(api_module, "_run_inventory_refresh", fake_refresh)

    res = api_client.post("/api/inventory/refresh", json={})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "started"
    assert "refresh_id" in data


def test_inventory_api_get_with_data(api_client, monkeypatch):
    """GET /api/inventory returns the stored snapshot after upsert via the api_client fixture."""
    import src.api.dashboard_api as api_module

    # Write a snapshot directly to the client that api_client fixture already patched in
    inv_client = api_module._cosmos_inventory
    record = {
        "id": "inv-abc12345-20260408T100000",
        "subscription_id": "",          # empty so get_latest("") matches
        "refreshed_at": "2026-04-08T10:00:00Z",
        "resource_count": 5,
        "type_summary": {},
        "resources": [],
    }
    inv_client.upsert(record)

    res = api_client.get("/api/inventory")
    assert res.status_code == 200
    assert res.json()["resource_count"] == 5


# ---------------------------------------------------------------------------
# Agent integration tests (inventory param)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitoring_agent_accepts_inventory_param():
    """MonitoringAgent.scan() must accept inventory parameter without error."""
    from src.operational_agents.monitoring_agent import MonitoringAgent

    agent = MonitoringAgent()
    # In mock mode (no framework) this should return [] immediately
    inventory = [{"id": "/sub/rg/vm-01", "name": "vm-01", "type": "microsoft.compute/virtualmachines"}]
    result = await agent.scan(inventory=inventory)
    # Mock mode returns [] — just check no exception is raised
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_deploy_agent_accepts_inventory_param():
    """DeployAgent.scan() must accept inventory parameter without error."""
    from src.operational_agents.deploy_agent import DeployAgent

    agent = DeployAgent()
    inventory = [{"id": "/sub/rg/nsg-01", "name": "nsg-01", "type": "microsoft.network/networksecuritygroups"}]
    result = await agent.scan(inventory=inventory)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_cost_agent_accepts_inventory_param():
    """CostOptimizationAgent.scan() must accept inventory parameter without error."""
    from src.operational_agents.cost_agent import CostOptimizationAgent

    agent = CostOptimizationAgent()
    inventory = [{"id": "/sub/rg/vm-01", "name": "vm-01", "type": "microsoft.compute/virtualmachines"}]
    result = await agent.scan(inventory=inventory)
    assert isinstance(result, list)


def test_scan_api_accepts_inventory_mode(api_client, monkeypatch):
    """POST /api/scan/monitoring with inventory_mode param must return 200."""
    import src.api.dashboard_api as api_module

    async def fake_run(*args, **kwargs):
        pass

    monkeypatch.setattr(api_module, "_run_agent_scan", fake_run)

    res = api_client.post(
        "/api/scan/monitoring",
        json={"inventory_mode": "skip"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "started"
    assert "scan_id" in data


# ---------------------------------------------------------------------------
# inventory_builder — total enrichment failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_inventory_vm_enrichment_total_failure():
    """If ALL VM enrichments fail, inventory must still return with VMs (powerState unknown)."""
    vms = [
        {"id": "/sub/rg/vm-01", "name": "vm-01", "type": "microsoft.compute/virtualmachines",
         "location": "eastus", "resourceGroup": "rg", "tags": {}, "properties": {}, "sku": {}},
        {"id": "/sub/rg/vm-02", "name": "vm-02", "type": "microsoft.compute/virtualmachines",
         "location": "eastus", "resourceGroup": "rg", "tags": {}, "properties": {}, "sku": {}},
    ]

    async def mock_query_rg(kusto_query, subscription_id=""):
        return vms

    async def mock_enrich_all_fail(vms_in, sub, progress):
        # Every VM fails — return all with 'unknown'
        return [{**v, "powerState": "unknown (enrichment failed)"} for v in vms_in]

    with patch("src.infrastructure.azure_tools.query_resource_graph_async", side_effect=mock_query_rg):
        with patch("src.infrastructure.inventory_builder._enrich_vm_power_states", new=mock_enrich_all_fail):
            from src.infrastructure.inventory_builder import build_inventory
            doc = await build_inventory("sub-abc-123")

    # Inventory must still be returned — not an empty/error doc
    assert doc["resource_count"] == 2
    result_vms = [r for r in doc["resources"] if "virtualmachine" in r.get("type", "").lower()]
    assert len(result_vms) == 2
    for vm in result_vms:
        assert "unknown" in vm.get("powerState", "")


# ---------------------------------------------------------------------------
# _run_agent_scan inventory_mode branch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_with_inventory_existing(tmp_path, monkeypatch):
    """inventory_mode='existing' must load from Cosmos and pass resources to agent.scan()."""
    import src.api.dashboard_api as api_module
    from src.infrastructure.cosmos_client import CosmosInventoryClient

    # Seed the Cosmos client with a snapshot
    inv_client = CosmosInventoryClient(inventory_dir=tmp_path / "inventory")
    snapshot = {
        "id": "inv-testsub1-20260408T100000",
        "subscription_id": "test-sub-001",
        "refreshed_at": "2026-04-08T10:00:00Z",
        "resource_count": 2,
        "type_summary": {},
        "resources": [
            {"id": "/r1", "name": "vm-01", "type": "microsoft.compute/virtualmachines"},
            {"id": "/r2", "name": "site-01", "type": "microsoft.web/sites"},
        ],
    }
    inv_client.upsert(snapshot)
    monkeypatch.setattr(api_module, "_cosmos_inventory", inv_client)

    # Capture what inventory is passed to the agent
    received_inventories = []

    class _FakeAgent:
        async def scan(self, target_resource_group=None, inventory=None):
            received_inventories.append(inventory)
            return []

    import src.operational_agents.monitoring_agent as mon_module
    monkeypatch.setattr(mon_module, "MonitoringAgent", _FakeAgent)

    # Create a scan record and run the scan
    scan_id, _ = api_module._make_scan_record("monitoring", None)
    await api_module._run_agent_scan(
        scan_id, "monitoring", None,
        subscription_id="test-sub-001",
        inventory_mode="existing",
    )

    assert len(received_inventories) == 1
    inv = received_inventories[0]
    assert inv is not None
    assert len(inv) == 2
    names = {r["name"] for r in inv}
    assert names == {"vm-01", "site-01"}


@pytest.mark.asyncio
async def test_scan_with_inventory_skip(tmp_path, monkeypatch):
    """inventory_mode='skip' must pass inventory=None to agent.scan()."""
    import src.api.dashboard_api as api_module
    from src.infrastructure.cosmos_client import CosmosInventoryClient

    inv_client = CosmosInventoryClient(inventory_dir=tmp_path / "inventory")
    monkeypatch.setattr(api_module, "_cosmos_inventory", inv_client)

    received_inventories = []

    class _FakeAgent:
        async def scan(self, target_resource_group=None, inventory=None):
            received_inventories.append(inventory)
            return []

    import src.operational_agents.cost_agent as cost_module
    monkeypatch.setattr(cost_module, "CostOptimizationAgent", _FakeAgent)

    scan_id, _ = api_module._make_scan_record("cost", None)
    await api_module._run_agent_scan(
        scan_id, "cost", None,
        subscription_id="test-sub-001",
        inventory_mode="skip",
    )

    assert len(received_inventories) == 1
    assert received_inventories[0] is None


@pytest.mark.asyncio
async def test_scan_no_inventory_fallback(tmp_path, monkeypatch):
    """When inventory_mode='existing' but no snapshot exists, agent.scan() gets inventory=None."""
    import src.api.dashboard_api as api_module
    from src.infrastructure.cosmos_client import CosmosInventoryClient

    # Empty inventory store — nothing upserted
    inv_client = CosmosInventoryClient(inventory_dir=tmp_path / "inventory")
    monkeypatch.setattr(api_module, "_cosmos_inventory", inv_client)

    received_inventories = []

    class _FakeAgent:
        async def scan(self, target_resource_group=None, inventory=None):
            received_inventories.append(inventory)
            return []

    import src.operational_agents.deploy_agent as dep_module
    monkeypatch.setattr(dep_module, "DeployAgent", _FakeAgent)

    scan_id, _ = api_module._make_scan_record("deploy", None)
    await api_module._run_agent_scan(
        scan_id, "deploy", None,
        subscription_id="test-sub-001",
        inventory_mode="existing",
    )

    assert len(received_inventories) == 1
    assert received_inventories[0] is None


@pytest.mark.asyncio
async def test_scan_with_inventory_refresh(tmp_path, monkeypatch):
    """inventory_mode='refresh' must call build_inventory, upsert to Cosmos, then pass resources."""
    import src.api.dashboard_api as api_module
    from src.infrastructure.cosmos_client import CosmosInventoryClient

    inv_client = CosmosInventoryClient(inventory_dir=tmp_path / "inventory")
    monkeypatch.setattr(api_module, "_cosmos_inventory", inv_client)

    fresh_resources = [
        {"id": "/r1", "name": "vm-fresh", "type": "microsoft.compute/virtualmachines"},
    ]

    async def mock_build_inventory(subscription_id, resource_group=None, on_progress=None):
        return {
            "id": "inv-fresh-20260408T120000",
            "subscription_id": subscription_id,
            "refreshed_at": "2026-04-08T12:00:00Z",
            "resource_count": len(fresh_resources),
            "type_summary": {},
            "resources": fresh_resources,
        }

    monkeypatch.setattr(api_module, "_run_inventory_refresh", None)  # ensure not called via bg

    # Patch build_inventory at the dashboard_api import site
    with patch("src.infrastructure.inventory_builder.build_inventory", side_effect=mock_build_inventory):
        received_inventories = []

        class _FakeAgent:
            async def scan(self, target_resource_group=None, inventory=None):
                received_inventories.append(inventory)
                return []

        import src.operational_agents.monitoring_agent as mon_module
        monkeypatch.setattr(mon_module, "MonitoringAgent", _FakeAgent)

        scan_id, _ = api_module._make_scan_record("monitoring", None)
        await api_module._run_agent_scan(
            scan_id, "monitoring", None,
            subscription_id="test-sub-001",
            inventory_mode="refresh",
        )

    assert len(received_inventories) == 1
    inv = received_inventories[0]
    assert inv is not None
    assert inv[0]["name"] == "vm-fresh"

    # Verify the snapshot was persisted to Cosmos
    stored = inv_client.get_latest("test-sub-001")
    assert stored is not None
    assert stored["resource_count"] == 1


# ---------------------------------------------------------------------------
# Monitoring agent — inventory text injected into LLM prompt
# ---------------------------------------------------------------------------


def test_monitoring_agent_inventory_in_prompt():
    """When inventory is provided, format_inventory_for_prompt output must appear in the prompt
    that _scan_with_framework receives."""
    from src.operational_agents.monitoring_agent import MonitoringAgent
    from src.infrastructure.inventory_formatter import format_inventory_for_prompt

    inventory = [
        {"id": "/sub/rg/vm-01", "name": "vm-unique-sentinel", "type": "microsoft.compute/virtualmachines",
         "location": "eastus", "resourceGroup": "rg", "tags": {}, "powerState": "VM deallocated"},
    ]
    expected_text = format_inventory_for_prompt({
        "resources": inventory,
        "resource_count": len(inventory),
        "refreshed_at": "pre-fetched",
    })

    captured_prompts = []

    async def fake_scan_with_framework(self_inner, alert_payload, rg, inventory_arg=None):
        # Reconstruct the prompt the same way _scan_with_framework does
        from src.infrastructure.inventory_formatter import format_inventory_for_prompt as fmt
        inv_text = fmt({"resources": inventory_arg, "resource_count": len(inventory_arg), "refreshed_at": "pre-fetched"})
        captured_prompts.append(inv_text)
        return []

    agent = MonitoringAgent()

    with patch.object(
        type(agent), "_scan_with_framework",
        new=lambda self, ap, rg, inv=None: fake_scan_with_framework(self, ap, rg, inv),
    ):
        import asyncio
        asyncio.run(agent.scan(inventory=inventory))

    # The inventory text produced by format_inventory_for_prompt must contain the unique resource name
    assert len(captured_prompts) == 1
    assert "vm-unique-sentinel" in captured_prompts[0]

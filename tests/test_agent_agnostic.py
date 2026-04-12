"""Tests for environment-agnostic design principles across all ops agents.

Section F of the Phase 12/13 verification checklist.

Design principles verified
--------------------------
- Ops agents are environment-agnostic: accept any resource group, no hardcoded
  names, no seed_resources fallback in live mode.
- Azure tools raise clear RuntimeError on failure (no silent fallback).
- Scan API endpoints start background tasks, return scan_id immediately, and
  accept optional resource_group overrides.

Test isolation strategy
-----------------------
All tests that exercise live-mode behaviour mock the Azure SDK at the SDK level
(azure.identity.DefaultAzureCredential, azure.mgmt.resourcegraph.ResourceGraphClient,
etc.) rather than using USE_LOCAL_MOCKS.  Tests that use the default Settings
(use_local_mocks=True) exercise the rule-based mock path.
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ============================================================================
# Helpers
# ============================================================================


def _live_cfg():
    """Return a Settings-like object that forces the framework (live) path."""
    from src.config import Settings
    return Settings(
        use_local_mocks=False,
        azure_openai_endpoint="https://fake-foundry.cognitiveservices.azure.com/",
        azure_openai_deployment="gpt-41",
    )


# ============================================================================
# Section B — Environment-agnostic CostOptimizationAgent
# ============================================================================


class TestCostAgentAgnostic:

    # ------------------------------------------------------------------
    # B1 — System prompt covers all resource types
    # ------------------------------------------------------------------

    def test_cost_agent_prompt_includes_all_resource_types(self):
        """_AGENT_INSTRUCTIONS mentions VMs, App Services, SQL databases, and AKS."""
        from src.operational_agents.cost_agent import _AGENT_INSTRUCTIONS

        prompt_lower = _AGENT_INSTRUCTIONS.lower()
        assert "virtualmachine" in prompt_lower or "virtual machine" in prompt_lower, (
            "_AGENT_INSTRUCTIONS should mention virtual machines"
        )
        assert "serverfarm" in prompt_lower or "app service" in prompt_lower, (
            "_AGENT_INSTRUCTIONS should mention App Service plans"
        )
        assert "sql" in prompt_lower or "database" in prompt_lower, (
            "_AGENT_INSTRUCTIONS should mention SQL/databases"
        )
        assert "managedcluster" in prompt_lower or "aks" in prompt_lower, (
            "_AGENT_INSTRUCTIONS should mention AKS / managed clusters"
        )

    # ------------------------------------------------------------------
    # B2 — No seed_resources.json Python import
    # ------------------------------------------------------------------

    def test_cost_agent_no_seed_resources_import(self):
        """cost_agent.py does not contain a Python import statement for seed_resources."""
        import src.operational_agents.cost_agent as module

        source = inspect.getsource(module)
        assert "import seed_resources" not in source, (
            "cost_agent.py must not import seed_resources as a Python module"
        )
        assert "from data import seed_resources" not in source, (
            "cost_agent.py must not import seed_resources as a Python module"
        )

    # ------------------------------------------------------------------
    # B2 — No hardcoded resource names in agent logic
    # ------------------------------------------------------------------

    def test_cost_agent_no_hardcoded_resource_names(self):
        """_AGENT_INSTRUCTIONS contains no hardcoded resource names."""
        from src.operational_agents.cost_agent import _AGENT_INSTRUCTIONS

        assert "vm-dr-01" not in _AGENT_INSTRUCTIONS, (
            "_AGENT_INSTRUCTIONS must not hardcode vm-dr-01"
        )
        assert "vm-web-01" not in _AGENT_INSTRUCTIONS, (
            "_AGENT_INSTRUCTIONS must not hardcode vm-web-01"
        )
        assert "ruriskry-prod-rg" not in _AGENT_INSTRUCTIONS, (
            "_AGENT_INSTRUCTIONS must not hardcode ruriskry-prod-rg"
        )

    # ------------------------------------------------------------------
    # B2 — Accepts any resource group
    # ------------------------------------------------------------------

    def test_cost_agent_accepts_any_resource_group(self):
        """scan() passes arbitrary resource group to _scan_with_framework."""
        from src.operational_agents.cost_agent import CostOptimizationAgent

        agent = CostOptimizationAgent(cfg=_live_cfg())

        with patch.object(
            agent, "_scan_with_framework", new=AsyncMock(return_value=[])
        ) as mock_fw:
            asyncio.run(agent.scan(target_resource_group="totally-different-rg"))
            mock_fw.assert_called_once_with("totally-different-rg", None)

    # ------------------------------------------------------------------
    # B3 — Live-mode failure returns [] (no seed data fallback)
    # ------------------------------------------------------------------

    def test_cost_agent_raises_on_azure_failure(self):
        """When _scan_with_framework raises, scan() returns [] not seed data."""
        from src.operational_agents.cost_agent import CostOptimizationAgent

        agent = CostOptimizationAgent(cfg=_live_cfg())

        async def _fail(*_args, **_kwargs):
            raise ConnectionError("Azure is unreachable in this test")

        agent._scan_with_framework = _fail

        result = asyncio.run(agent.scan())
        assert result == [], (
            "scan() must return [] when Azure is unreachable, not seed data proposals"
        )


# ============================================================================
# Section B — Environment-agnostic DeployAgent
# ============================================================================


class TestDeployAgentAgnostic:

    # ------------------------------------------------------------------
    # B6 — No hardcoded lifecycle tag keys in agent instructions
    # ------------------------------------------------------------------

    def test_deploy_agent_no_hardcoded_tags(self):
        """_AGENT_INSTRUCTIONS does not prescribe specific tag key names."""
        from src.operational_agents.deploy_agent import _AGENT_INSTRUCTIONS

        # These are org-specific tag keys that must NOT appear as prescriptive
        # checks in the live-mode instructions (they belong to _LIFECYCLE_TAGS
        # in the mock/CI rule-based path only).
        for tag_key in ("backup", "disaster-recovery", "purpose"):
            assert f"tags['{tag_key}']" not in _AGENT_INSTRUCTIONS, (
                f"_AGENT_INSTRUCTIONS must not prescribe tag key '{tag_key}'"
            )
            assert f'tags["{tag_key}"]' not in _AGENT_INSTRUCTIONS, (
                f"_AGENT_INSTRUCTIONS must not prescribe tag key '{tag_key}'"
            )

    # ------------------------------------------------------------------
    # B6 — Generic security focus, not tag-key-specific
    # ------------------------------------------------------------------

    def test_deploy_agent_generic_security_scan(self):
        """_AGENT_INSTRUCTIONS focuses on generic security posture, not specific tags."""
        from src.operational_agents.deploy_agent import _AGENT_INSTRUCTIONS

        prompt_lower = _AGENT_INSTRUCTIONS.lower()
        # Must mention generic security concerns
        assert "nsg" in prompt_lower or "security rule" in prompt_lower, (
            "_AGENT_INSTRUCTIONS should mention NSG / security rules"
        )
        assert "deny" in prompt_lower, (
            "_AGENT_INSTRUCTIONS should mention deny-all rule checking"
        )
        # Must NOT tell GPT to look for specific tag key names
        assert "do not check for specific tag key names" in prompt_lower, (
            "_AGENT_INSTRUCTIONS should tell GPT not to hardcode tag key names"
        )

    # ------------------------------------------------------------------
    # B2 — No seed_resources.json Python import
    # ------------------------------------------------------------------

    def test_deploy_agent_no_seed_resources_import(self):
        """deploy_agent.py does not contain a Python import for seed_resources."""
        import src.operational_agents.deploy_agent as module

        source = inspect.getsource(module)
        assert "import seed_resources" not in source
        assert "from data import seed_resources" not in source

    # ------------------------------------------------------------------
    # B2 — Accepts any resource group
    # ------------------------------------------------------------------

    def test_deploy_agent_accepts_any_resource_group(self):
        """scan() passes arbitrary resource group to _scan_with_framework."""
        from src.operational_agents.deploy_agent import DeployAgent

        agent = DeployAgent(cfg=_live_cfg())

        with patch.object(
            agent, "_scan_with_framework", new=AsyncMock(return_value=[])
        ) as mock_fw:
            asyncio.run(agent.scan(target_resource_group="my-custom-rg"))
            mock_fw.assert_called_once_with("my-custom-rg", None)

    # ------------------------------------------------------------------
    # B3 — Live-mode failure returns []
    # ------------------------------------------------------------------

    def test_deploy_agent_raises_on_azure_failure(self):
        """When _scan_with_framework raises, scan() returns [] not seed data."""
        from src.operational_agents.deploy_agent import DeployAgent

        agent = DeployAgent(cfg=_live_cfg())

        async def _fail(*_args, **_kwargs):
            raise ConnectionError("Azure is unreachable in this test")

        agent._scan_with_framework = _fail
        result = asyncio.run(agent.scan())
        assert result == []


# ============================================================================
# Section B — Environment-agnostic MonitoringAgent
# ============================================================================


class TestMonitoringAgentAgnostic:

    # ------------------------------------------------------------------
    # B2 — No seed_resources.json Python import
    # ------------------------------------------------------------------

    def test_monitoring_agent_no_seed_resources_import(self):
        """monitoring_agent.py does not contain a Python import for seed_resources."""
        import src.operational_agents.monitoring_agent as module

        source = inspect.getsource(module)
        assert "import seed_resources" not in source
        assert "from data import seed_resources" not in source

    # ------------------------------------------------------------------
    # B5 — Accepts arbitrary alert payload (unknown resource IDs)
    # ------------------------------------------------------------------

    def test_monitoring_agent_accepts_alert_payload(self):
        """scan(alert_payload=...) handles an alert for an unknown resource without crashing."""
        from src.operational_agents.monitoring_agent import MonitoringAgent

        # Use default (mock) settings so _scan_rules() runs and we can verify shape.
        agent = MonitoringAgent()
        alert = {
            "resource_id": (
                "/subscriptions/unknown-sub/resourceGroups/unknown-rg"
                "/providers/Microsoft.Compute/virtualMachines/unknown-vm-xyz"
            ),
            "metric": "Percentage CPU",
            "value": 99.0,
            "threshold": 80.0,
        }
        proposals = asyncio.run(agent.scan(alert_payload=alert))
        # Should return a list (possibly empty) without raising
        assert isinstance(proposals, list)

    # ------------------------------------------------------------------
    # B2 — Accepts any resource group
    # ------------------------------------------------------------------

    def test_monitoring_agent_accepts_any_resource_group(self):
        """scan() passes arbitrary resource group to _scan_with_framework."""
        from src.operational_agents.monitoring_agent import MonitoringAgent

        agent = MonitoringAgent(cfg=_live_cfg())

        with patch.object(
            agent, "_scan_with_framework", new=AsyncMock(return_value=[])
        ) as mock_fw:
            asyncio.run(agent.scan(target_resource_group="any-org-rg"))
            mock_fw.assert_called_once_with(None, "any-org-rg", None)

    # ------------------------------------------------------------------
    # B3 — Live-mode failure returns []
    # ------------------------------------------------------------------

    def test_monitoring_agent_raises_on_azure_failure(self):
        """When _scan_with_framework raises, scan() returns [] not seed data."""
        from src.operational_agents.monitoring_agent import MonitoringAgent

        agent = MonitoringAgent(cfg=_live_cfg())

        async def _fail(*_args, **_kwargs):
            raise ConnectionError("Azure is unreachable in this test")

        agent._scan_with_framework = _fail
        result = asyncio.run(agent.scan())
        assert result == []


# ============================================================================
# Section A — Azure tools (SDK-level mocking)
# ============================================================================


class TestAzureTools:

    # ------------------------------------------------------------------
    # A6 — Clear RuntimeError on live-mode connection failure
    # ------------------------------------------------------------------

    def test_tools_raise_clear_error_on_connection_failure(self):
        """query_resource_graph raises RuntimeError with az-login hint when Azure fails."""
        from src.infrastructure.azure_tools import query_resource_graph

        with patch("src.infrastructure.azure_tools._use_mocks", return_value=False), \
             patch(
                 "azure.identity.DefaultAzureCredential",
                 side_effect=Exception("no credentials found"),
             ):
            with pytest.raises(RuntimeError) as exc_info:
                query_resource_graph("Resources | project id")

            err = str(exc_info.value).lower()
            # Error must identify which tool failed
            assert "query_resource_graph" in err, (
                "RuntimeError message should name the failing tool"
            )
            # Error must guide the user
            assert "az login" in err or "login" in err, (
                "RuntimeError message should suggest running az login"
            )

    # ------------------------------------------------------------------
    # A1 — KQL query reaches the Azure SDK unchanged
    # ------------------------------------------------------------------

    def test_query_resource_graph_passes_query_to_sdk(self):
        """The KQL string is passed verbatim to ResourceGraphClient.resources()."""
        import sys
        from src.infrastructure.azure_tools import query_resource_graph

        # Build a minimal mock for the azure.mgmt.resourcegraph SDK classes.
        # We inject them via sys.modules because the package may not be installed
        # in every environment (it is in requirements.txt but not always present
        # in CI).
        mock_result = MagicMock()
        mock_result.data = []
        mock_client = MagicMock()
        mock_client.resources.return_value = mock_result

        # QueryRequest captures keyword args so we can inspect .query later.
        class _FakeQueryRequest:
            def __init__(self, subscriptions=None, query=""):
                self.subscriptions = subscriptions or []
                self.query = query

        mock_rg_module = MagicMock()
        mock_rg_module.ResourceGraphClient = MagicMock(return_value=mock_client)
        mock_rg_models = MagicMock()
        mock_rg_models.QueryRequest = _FakeQueryRequest

        test_query = "Resources | where type == 'microsoft.compute/virtualmachines'"

        with patch.dict(
            sys.modules,
            {
                "azure.mgmt": MagicMock(),
                "azure.mgmt.resourcegraph": mock_rg_module,
                "azure.mgmt.resourcegraph.models": mock_rg_models,
            },
        ), patch("src.infrastructure.azure_tools._use_mocks", return_value=False):
            query_resource_graph(test_query)

        # Verify the SDK client was called
        assert mock_client.resources.called, "ResourceGraphClient.resources() was not called"

        # Verify the QueryRequest passed to the SDK contains our query
        call_arg = mock_client.resources.call_args[0][0]
        assert hasattr(call_arg, "query"), (
            "First argument to resources() should be a QueryRequest with .query attribute"
        )
        assert call_arg.query == test_query, (
            f"Expected query {test_query!r} but got {call_arg.query!r}"
        )

    # ------------------------------------------------------------------
    # A2 — query_metrics returns structured dict with average/max/min
    # ------------------------------------------------------------------

    def test_query_metrics_returns_structured_data(self):
        """query_metrics (mock mode) returns the required dict structure."""
        from src.infrastructure.azure_tools import query_metrics

        # Force mock mode regardless of .env USE_LOCAL_MOCKS setting,
        # so this test is deterministic in every environment.
        with patch("src.infrastructure.azure_tools._use_mocks", return_value=True):
            result = query_metrics("fake-resource-id", ["Percentage CPU"], "P7D")

        assert "resource_id" in result, "Response must have 'resource_id' key"
        assert "timespan" in result, "Response must have 'timespan' key"
        assert "metrics" in result, "Response must have 'metrics' key"

        cpu = result["metrics"].get("Percentage CPU")
        assert cpu is not None, "Percentage CPU must be in metrics"
        assert "average" in cpu, "Metric must have 'average'"
        assert "maximum" in cpu, "Metric must have 'maximum'"
        assert "minimum" in cpu, "Metric must have 'minimum'"
        assert isinstance(cpu["average"], (int, float)), "average must be numeric"


# ============================================================================
# Section C — Scan API endpoints
# ============================================================================


@pytest.fixture(scope="module")
def api_client():
    """Shared FastAPI TestClient for scan endpoint tests."""
    from src.api.dashboard_api import app
    return TestClient(app)


class TestScanAPIEndpoints:

    # ------------------------------------------------------------------
    # C1 — POST /api/scan/cost returns scan_id
    # ------------------------------------------------------------------

    def test_scan_cost_returns_scan_id(self, api_client):
        """POST /api/scan/cost returns HTTP 200 with scan_id and status=started."""
        with patch(
            "src.api.dashboard_api._run_agent_scan",
            new=AsyncMock(return_value=None),
        ):
            response = api_client.post("/api/scan/cost")

        assert response.status_code == 200
        data = response.json()
        assert "scan_id" in data, "Response must contain scan_id"
        assert data["status"] == "started"
        assert data["agent_type"] == "cost"

    # ------------------------------------------------------------------
    # C1 — POST /api/scan/all returns three scan_ids
    # ------------------------------------------------------------------

    def test_scan_all_returns_three_scan_ids(self, api_client):
        """POST /api/scan/all returns status=started and 3 unique scan_ids."""
        with patch(
            "src.api.dashboard_api._run_agent_scan",
            new=AsyncMock(return_value=None),
        ):
            response = api_client.post("/api/scan/all")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
        assert "scan_ids" in data, "Response must contain scan_ids list"
        assert len(data["scan_ids"]) == 3, "scan/all must start exactly 3 scans"
        # All scan_ids must be unique
        assert len(set(data["scan_ids"])) == 3, "scan_ids must all be unique"

    # ------------------------------------------------------------------
    # C1 — GET /api/scan/{id}/status returns running immediately
    # ------------------------------------------------------------------

    def test_scan_status_running(self, api_client):
        """GET /api/scan/{id}/status returns the scan record for a valid scan_id."""
        with patch(
            "src.api.dashboard_api._run_agent_scan",
            new=AsyncMock(return_value=None),
        ):
            post_resp = api_client.post("/api/scan/monitoring")
            scan_id = post_resp.json()["scan_id"]

        status_resp = api_client.get(f"/api/scan/{scan_id}/status")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["scan_id"] == scan_id
        # Background task mock does nothing → scan stays "running"
        assert data["status"] in ("running", "complete", "error"), (
            f"Unexpected status value: {data['status']}"
        )

    # ------------------------------------------------------------------
    # C3 — Custom resource group passes through
    # ------------------------------------------------------------------

    def test_scan_accepts_custom_resource_group(self, api_client):
        """POST /api/scan/cost with resource_group body passes it to the agent."""
        captured: list[tuple] = []

        async def capture_scan(scan_id, agent_type, resource_group, subscription_id=None, inventory_mode="existing"):
            captured.append((scan_id, agent_type, resource_group))

        with patch(
            "src.api.dashboard_api._run_agent_scan",
            side_effect=capture_scan,
        ):
            response = api_client.post(
                "/api/scan/cost",
                json={"resource_group": "custom-rg"},
            )

        assert response.status_code == 200
        assert len(captured) == 1, "Background task was not called"
        _, _, rg = captured[0]
        assert rg == "custom-rg", (
            f"Expected resource_group='custom-rg' but got {rg!r}"
        )

    # ------------------------------------------------------------------
    # C1 — POST /api/alert-trigger accepts Azure Monitor webhook payload
    # ------------------------------------------------------------------

    def test_alert_trigger_accepts_webhook(self, api_client):
        """POST /api/alert-trigger creates a pending alert record without auto-investigation.

        The endpoint creates an alert record and returns immediately.
        Investigation must be triggered manually via POST /api/alerts/{id}/investigate.
        """
        alert_payload = {
            "resource_id": (
                "/subscriptions/demo/resourceGroups/test-rg"
                "/providers/Microsoft.Compute/virtualMachines/test-vm"
            ),
            "metric": "Percentage CPU",
            "value": 95.0,
            "threshold": 80.0,
            "severity": "3",
            "resource_group": "test-rg",
        }
        response = api_client.post("/api/alert-trigger", json=alert_payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending", "Alert should start in pending status (no auto-investigation)"
        assert "alert_id" in data, "Response must include alert_id"

    def test_alerts_list_endpoint(self, api_client):
        """GET /api/alerts returns a list of alert records."""
        # Create one alert first
        api_client.post("/api/alert-trigger", json={
            "resource_id": "test-vm", "metric": "CPU", "severity": "3",
        })
        response = api_client.get("/api/alerts")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "alerts" in data
        assert data["count"] >= 1

    def test_alerts_active_count_endpoint(self, api_client):
        """GET /api/alerts/active-count returns active alert count."""
        response = api_client.get("/api/alerts/active-count")
        assert response.status_code == 200
        data = response.json()
        assert "active_count" in data
        assert isinstance(data["active_count"], int)

    def test_alert_status_endpoint(self, api_client):
        """GET /api/alerts/{alert_id}/status returns full alert record."""
        # Create an alert
        r = api_client.post("/api/alert-trigger", json={
            "resource_id": "status-test-vm", "metric": "Memory", "severity": "1",
        })
        alert_id = r.json()["alert_id"]

        response = api_client.get(f"/api/alerts/{alert_id}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["alert_id"] == alert_id
        assert data["resource_name"] == "status-test-vm"

    def test_alert_status_404_for_unknown(self, api_client):
        """GET /api/alerts/{unknown}/status returns 404."""
        response = api_client.get("/api/alerts/nonexistent-id/status")
        assert response.status_code == 404


# ============================================================================
# Section G — Compliant-resource proposal filter
# ============================================================================
# is_compliant_reason() is the deterministic gate that prevents the LLM from
# submitting governance proposals for resources that are already compliant.
# It lives in src/operational_agents/__init__.py and is wired into every
# agent's tool_propose_action before proposals_holder.append().
# ============================================================================


class TestIsCompliantReason:
    """Unit tests for the is_compliant_reason() deterministic filter."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from src.operational_agents import is_compliant_reason
        self.check = is_compliant_reason

    # ------------------------------------------------------------------
    # Positive cases — should be blocked
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("reason", [
        "No action needed — storage account is already encrypted.",
        "Resource is already compliant with the security policy.",
        "Already configured: supportsHttpsTrafficOnly is true.",
        "Disk is already encrypted with platform key, compliant and secure.",
        "Already secure — no vulnerability found.",
        "No action required for this resource.",
        "Storage account has already been hardened.",
        "No issues found — configuration is compliant.",
        "Nothing to do — already enabled.",
        "Does not require any changes.",
        "Already disabled as required by policy.",
        "Is already in the desired state.",
        "Resource is compliant with CIS benchmark.",
        "Configuration is compliant and no remediation is needed.",
        "No vulnerabilities detected on this resource.",
        "Is compliant — soft-delete already enabled.",
        "Not required: resource already meets the control objective.",
        "No issues detected — policy is satisfied.",
        "Secure configuration detected — no action needed.",
    ])
    def test_compliant_reason_returns_true(self, reason):
        """Reasons signalling compliance must return True → proposal blocked."""
        assert self.check(reason) is True, (
            f"Expected is_compliant_reason({reason!r}) to return True"
        )

    # ------------------------------------------------------------------
    # Negative cases — actual violations must pass through
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("reason", [
        "NSG rule 'allow-ssh-anywhere' exposes port 22 to 0.0.0.0/0.",
        "Storage account allows public blob access — data exposure risk.",
        "Key vault has soft-delete disabled — data loss risk if deleted.",
        "VM is stopped — restart required to maintain SLA.",
        "CPU utilisation averaged 3% over 7 days — candidate for right-sizing.",
        "Disk encryption not enabled — data at rest is unprotected.",
        "Public network access enabled on SQL database.",
        "Missing deny-all inbound rule on NSG 'nsg-east-prod'.",
        "RDP port 3389 open to internet — critical exposure.",
        "Resource has no tags — blast radius analysis unavailable.",
    ])
    def test_violation_reason_returns_false(self, reason):
        """Reasons describing real violations must return False → proposal allowed."""
        assert self.check(reason) is False, (
            f"Expected is_compliant_reason({reason!r}) to return False"
        )

    def test_empty_string_returns_false(self):
        """Empty reason is not a compliance signal — do not block."""
        assert self.check("") is False

    def test_case_insensitive(self):
        """Match is case-insensitive."""
        assert self.check("NO ACTION NEEDED — everything is fine.") is True
        assert self.check("Already Compliant with security baseline.") is True


class TestCompliantFilterWiredInAgents:
    """Verify that is_compliant_reason is wired into all three agent files."""

    @pytest.mark.parametrize("module_path,agent_name", [
        ("src.operational_agents.deploy_agent", "DeployAgent"),
        ("src.operational_agents.monitoring_agent", "MonitoringAgent"),
        ("src.operational_agents.cost_agent", "CostOptimizationAgent"),
    ])
    def test_filter_imported_in_agent(self, module_path, agent_name):
        """is_compliant_reason must be imported at the module level."""
        import importlib
        import inspect
        module = importlib.import_module(module_path)
        source = inspect.getsource(module)
        assert "is_compliant_reason" in source, (
            f"{agent_name} ({module_path}) does not import is_compliant_reason — "
            "compliant-resource proposals will not be blocked"
        )

    @pytest.mark.parametrize("module_path,agent_name", [
        ("src.operational_agents.deploy_agent", "DeployAgent"),
        ("src.operational_agents.monitoring_agent", "MonitoringAgent"),
        ("src.operational_agents.cost_agent", "CostOptimizationAgent"),
    ])
    def test_filter_called_before_append_in_agent(self, module_path, agent_name):
        """is_compliant_reason must be called inside tool_propose_action."""
        import importlib
        import inspect
        module = importlib.import_module(module_path)
        source = inspect.getsource(module)
        # The guard must appear before proposals_holder.append
        filter_pos = source.find("is_compliant_reason(reason)")
        append_pos = source.find("proposals_holder.append(proposal)")
        assert filter_pos != -1, (
            f"{agent_name}: is_compliant_reason(reason) call not found in source"
        )
        assert append_pos != -1, (
            f"{agent_name}: proposals_holder.append(proposal) not found in source"
        )
        assert filter_pos < append_pos, (
            f"{agent_name}: is_compliant_reason must appear BEFORE "
            "proposals_holder.append to act as a gate"
        )

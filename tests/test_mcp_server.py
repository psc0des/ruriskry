"""Tests for the RuriSkry MCP server tool: skry_evaluate_action.

Covers:
- nsg_change_direction passthrough to ProposedAction (Phase 22F)
- Basic sanity: return dict contains expected keys
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.mcp_server.server as server_module
from src.mcp_server.server import skry_evaluate_action
from src.core.models import (
    ActionTarget,
    ActionType,
    GovernanceVerdict,
    ProposedAction,
    SRIBreakdown,
    SRIVerdict,
    Urgency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_verdict(action: ProposedAction) -> GovernanceVerdict:
    """Build a minimal GovernanceVerdict for mocking the pipeline."""
    return GovernanceVerdict(
        action_id="test-action-id",
        timestamp=datetime.now(timezone.utc),
        proposed_action=action,
        skry_risk_index=SRIBreakdown(
            sri_infrastructure=10.0,
            sri_policy=20.0,
            sri_historical=15.0,
            sri_cost=5.0,
            sri_composite=12.5,
        ),
        decision=SRIVerdict.APPROVED,
        reason="Test verdict — low risk.",
    )


def _make_pipeline_mock():
    """Return a mock pipeline where evaluate() captures the ProposedAction."""
    captured: dict = {}

    async def _evaluate(action: ProposedAction) -> GovernanceVerdict:
        captured["action"] = action
        return _make_verdict(action)

    mock = MagicMock()
    mock.evaluate = _evaluate
    mock._captured = captured
    return mock


def _make_tracker_mock():
    """Return a mock DecisionTracker with a no-op record()."""
    mock = MagicMock()
    mock.record = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# TestSkryEvaluateActionNsgDirection
# ---------------------------------------------------------------------------

class TestSkryEvaluateActionNsgDirection:
    """Verify that nsg_change_direction is passed through to ProposedAction."""

    async def test_open_direction_passed_to_pipeline(self, monkeypatch):
        pipeline = _make_pipeline_mock()
        monkeypatch.setattr(server_module, "_pipeline", pipeline)
        monkeypatch.setattr(server_module, "_tracker", _make_tracker_mock())

        await skry_evaluate_action(
            resource_id="nsg-east",
            resource_type="Microsoft.Network/networkSecurityGroups",
            action_type="modify_nsg",
            agent_id="test-agent",
            reason="Opening SSH to 0.0.0.0/0",
            nsg_change_direction="open",
        )

        assert pipeline._captured["action"].nsg_change_direction == "open"

    async def test_no_direction_defaults_to_none(self, monkeypatch):
        pipeline = _make_pipeline_mock()
        monkeypatch.setattr(server_module, "_pipeline", pipeline)
        monkeypatch.setattr(server_module, "_tracker", _make_tracker_mock())

        await skry_evaluate_action(
            resource_id="nsg-east",
            resource_type="Microsoft.Network/networkSecurityGroups",
            action_type="modify_nsg",
            agent_id="test-agent",
            reason="Modifying NSG rules",
        )

        assert pipeline._captured["action"].nsg_change_direction is None

    async def test_restrict_direction_passed_to_pipeline(self, monkeypatch):
        pipeline = _make_pipeline_mock()
        monkeypatch.setattr(server_module, "_pipeline", pipeline)
        monkeypatch.setattr(server_module, "_tracker", _make_tracker_mock())

        await skry_evaluate_action(
            resource_id="nsg-east",
            resource_type="Microsoft.Network/networkSecurityGroups",
            action_type="modify_nsg",
            agent_id="deploy-agent",
            reason="Restricting SSH source to corporate IP range",
            nsg_change_direction="restrict",
        )

        assert pipeline._captured["action"].nsg_change_direction == "restrict"


# ---------------------------------------------------------------------------
# TestSkryEvaluateActionSanity
# ---------------------------------------------------------------------------

class TestSkryEvaluateActionSanity:
    """Basic sanity: the returned dict contains the expected top-level keys."""

    async def test_returns_expected_keys(self, monkeypatch):
        pipeline = _make_pipeline_mock()
        monkeypatch.setattr(server_module, "_pipeline", pipeline)
        monkeypatch.setattr(server_module, "_tracker", _make_tracker_mock())

        result = await skry_evaluate_action(
            resource_id="vm-prod-01",
            resource_type="Microsoft.Compute/virtualMachines",
            action_type="scale_down",
            agent_id="cost-agent",
            reason="CPU utilisation below 5% for 14 days",
        )

        assert "action_id" in result
        assert "decision" in result
        assert "reason" in result
        assert "sri_composite" in result
        assert "sri_breakdown" in result
        assert set(result["sri_breakdown"].keys()) == {
            "infrastructure", "policy", "historical", "cost"
        }
        assert "thresholds" in result

    async def test_invalid_action_type_returns_error(self, monkeypatch):
        monkeypatch.setattr(server_module, "_pipeline", _make_pipeline_mock())
        monkeypatch.setattr(server_module, "_tracker", _make_tracker_mock())

        result = await skry_evaluate_action(
            resource_id="vm-01",
            resource_type="Microsoft.Compute/virtualMachines",
            action_type="not_a_real_action",
            agent_id="test-agent",
            reason="Testing invalid action type",
        )

        assert "error" in result
        assert "Invalid parameter" in result["error"]

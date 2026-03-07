"""Producer contract tests for DeployAgent.

Verifies that every ProposedAction produced by DeployAgent has
nsg_change_direction set correctly:
  - MODIFY_NSG proposals → "restrict" (remediation-only agent)
  - All other action types → None

Phase 22H: enforce the ADR declared in Phase 22F/22G so that future
scope changes cannot silently omit the field.
"""

import pytest

from src.core.models import ActionType
from src.operational_agents.deploy_agent import DeployAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def agent():
    """DeployAgent in mock-resource mode (no Azure credentials needed)."""
    return DeployAgent()


# ---------------------------------------------------------------------------
# TestDeployAgentNsgDirectionContract
# ---------------------------------------------------------------------------

class TestDeployAgentNsgDirectionContract:
    """All MODIFY_NSG proposals from DeployAgent must set direction='restrict'.

    ADR (Phase 22F): DeployAgent is remediation-only — it detects dangerous
    NSG rules and proposes to restrict them. If this agent ever proposes an
    opening change, both this contract test and the governance policy engine
    (POL-SEC-002 CRITICAL) must be updated to reflect the new scope.
    """

    def test_demo_proposals_modify_nsg_have_restrict_direction(self, agent):
        """All MODIFY_NSG entries in _demo_proposals() declare direction='restrict'."""
        proposals = agent._demo_proposals()
        nsg_proposals = [p for p in proposals if p.action_type == ActionType.MODIFY_NSG]
        assert nsg_proposals, "Expected at least one MODIFY_NSG demo proposal"
        for p in nsg_proposals:
            assert p.nsg_change_direction == "restrict", (
                f"Demo MODIFY_NSG proposal has wrong direction: "
                f"{p.nsg_change_direction!r} (expected 'restrict')"
            )

    def test_demo_proposals_non_nsg_have_none_direction(self, agent):
        """Non-NSG demo proposals have nsg_change_direction=None."""
        proposals = agent._demo_proposals()
        non_nsg = [p for p in proposals if p.action_type != ActionType.MODIFY_NSG]
        for p in non_nsg:
            assert p.nsg_change_direction is None, (
                f"Non-NSG proposal {p.action_type.value!r} unexpectedly has "
                f"nsg_change_direction={p.nsg_change_direction!r}"
            )

    def test_rule_based_nsg_proposals_have_restrict_direction(self, agent):
        """_detect_nsg_without_deny_all() proposals declare direction='restrict'.

        This test catches the Phase 22G bug: the rule-based scan path produced
        MODIFY_NSG proposals without nsg_change_direction, silently bypassing
        POL-SEC-003 detection of "unclassified NSG change direction".
        """
        proposals = agent._detect_nsg_without_deny_all()
        # May be empty if no NSG resources in seed data; only check if non-empty
        for p in proposals:
            assert p.action_type == ActionType.MODIFY_NSG
            assert p.nsg_change_direction == "restrict", (
                f"Rule-based MODIFY_NSG proposal has wrong direction: "
                f"{p.nsg_change_direction!r} (expected 'restrict')"
            )

    def test_scan_rules_all_modify_nsg_have_restrict_direction(self, agent):
        """Full rule-based scan: every MODIFY_NSG proposal has direction='restrict'."""
        proposals = agent._scan_rules()
        nsg_proposals = [p for p in proposals if p.action_type == ActionType.MODIFY_NSG]
        for p in nsg_proposals:
            assert p.nsg_change_direction == "restrict", (
                f"Scan rule MODIFY_NSG proposal missing restrict direction: "
                f"resource={p.target.resource_id!r}, direction={p.nsg_change_direction!r}"
            )

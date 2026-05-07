"""Tests for Phase 38C: few-shot observability.

Covers:
1. test_few_shot_examples_used_populated_on_borderline_rerun
2. test_few_shot_examples_used_empty_on_non_borderline
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_verdict(sri: float, action_id: str = "action-001") -> MagicMock:
    v = MagicMock()
    v.skry_risk_index.sri_composite = sri
    v.triage_tier = 2
    v.triage_mode = "full"
    v.action_id = action_id
    v.decision.value = "approved_if"
    v.few_shot_examples_used = []
    return v


def _make_pipeline_for_rerun():
    """Create a minimal pipeline stub for testing the borderline rerun path."""
    from src.core.pipeline import RuriSkryPipeline

    pipeline = RuriSkryPipeline.__new__(RuriSkryPipeline)
    blast_r = MagicMock()
    blast_r.sri_infrastructure = 20.0
    policy_r = MagicMock()
    policy_r.sri_policy = 25.0
    policy_r.violations = []
    hist_r = MagicMock()
    hist_r.sri_historical = 20.0
    fin_r = MagicMock()
    fin_r.sri_cost = 10.0

    pipeline._blast = MagicMock()
    pipeline._blast.evaluate = AsyncMock(return_value=blast_r)
    pipeline._policy = MagicMock()
    pipeline._policy.evaluate = AsyncMock(return_value=policy_r)
    pipeline._historical = MagicMock()
    pipeline._historical.evaluate = AsyncMock(return_value=hist_r)
    pipeline._financial = MagicMock()
    pipeline._financial.evaluate = AsyncMock(return_value=fin_r)

    refined = _make_verdict(29.0, action_id="action-001")
    refined.few_shot_examples_used = []
    pipeline._engine = MagicMock()
    pipeline._engine.evaluate = MagicMock(return_value=refined)

    return pipeline, refined


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_few_shot_examples_used_populated_on_borderline_rerun():
    """When borderline rerun fires, few_shot_examples_used is populated."""
    pipeline, refined_verdict = _make_pipeline_for_rerun()

    first_verdict = _make_verdict(29.0)  # borderline (near 30)
    action = MagicMock()
    action.action_type.value = "restart_service"
    action.target.resource_id = "vm-01"
    action.target.resource_type = "microsoft.compute/virtualmachines"
    action.reason = "restart"

    examples = [
        {"seed_id": "seed-001", "is_seed": True, "is_validated": True, "summary_text": "test 1"},
        {"seed_id": "seed-002", "is_seed": True, "is_validated": True, "summary_text": "test 2"},
    ]

    with patch("src.core.few_shot_retrieval.retrieve_similar_validated", new=AsyncMock(return_value=examples)):
        result = await pipeline._maybe_rerun_borderline(action, first_verdict, {}, False)

    # The rerun should populate few_shot_examples_used with seed IDs
    assert result.few_shot_examples_used == ["seed-001", "seed-002"]


@pytest.mark.asyncio
async def test_few_shot_examples_used_empty_on_non_borderline():
    """Non-borderline verdict: few_shot_examples_used stays empty."""
    pipeline, _ = _make_pipeline_for_rerun()

    first_verdict = _make_verdict(50.0)  # clearly in middle of ESCALATED band
    first_verdict.few_shot_examples_used = []
    action = MagicMock()

    with patch("src.core.few_shot_retrieval.retrieve_similar_validated", new=AsyncMock()) as mock_retrieve:
        result = await pipeline._maybe_rerun_borderline(action, first_verdict, {}, False)

    assert result is first_verdict
    assert result.few_shot_examples_used == []
    assert not mock_retrieve.called

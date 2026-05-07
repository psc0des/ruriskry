"""Tests for Phase 38B: borderline detection + pipeline rerun path.

Covers:
1. test_is_borderline_detects_each_boundary (20/30/60 ± 3)
2. test_is_borderline_returns_false_when_clearly_inside_band
3. test_borderline_path_invokes_rerun
4. test_non_borderline_path_skips_rerun
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.governance_engine import is_borderline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_verdict(sri: float) -> MagicMock:
    v = MagicMock()
    v.skry_risk_index.sri_composite = sri
    v.triage_tier = 2
    v.triage_mode = "full"
    v.action_id = "action-001"
    v.decision.value = "escalated"
    v.few_shot_examples_used = []
    return v


# ---------------------------------------------------------------------------
# Tests: borderline detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sri", [17.5, 18.0, 19.0, 20.0, 21.0, 22.0, 23.0])
def test_is_borderline_detects_boundary_20(sri):
    """SRI within ±3 of boundary 20 (APPROVED/APPROVED_IF) is borderline."""
    verdict = _make_verdict(sri)
    assert is_borderline(verdict) is True


@pytest.mark.parametrize("sri", [27.5, 28.0, 29.0, 30.0, 31.0, 32.0, 33.0])
def test_is_borderline_detects_boundary_30(sri):
    """SRI within ±3 of boundary 30 (APPROVED_IF/ESCALATED) is borderline."""
    verdict = _make_verdict(sri)
    assert is_borderline(verdict) is True


@pytest.mark.parametrize("sri", [57.5, 58.0, 59.0, 60.0, 61.0, 62.0, 63.0])
def test_is_borderline_detects_boundary_60(sri):
    """SRI within ±3 of boundary 60 (ESCALATED/DENIED) is borderline."""
    verdict = _make_verdict(sri)
    assert is_borderline(verdict) is True


@pytest.mark.parametrize("sri", [5.0, 10.0, 14.0, 35.0, 50.0, 70.0, 90.0])
def test_is_borderline_returns_false_when_clearly_inside_band(sri):
    """SRI clearly in the middle of a band is NOT borderline."""
    verdict = _make_verdict(sri)
    assert is_borderline(verdict) is False


# ---------------------------------------------------------------------------
# Tests: pipeline rerun integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_borderline_path_invokes_rerun():
    """When verdict is borderline and examples found, rerun fires with examples."""
    from src.core.pipeline import RuriSkryPipeline

    pipeline = RuriSkryPipeline.__new__(RuriSkryPipeline)
    pipeline._blast = MagicMock()
    pipeline._policy = MagicMock()
    pipeline._historical = MagicMock()
    pipeline._financial = MagicMock()
    pipeline._engine = MagicMock()

    blast_r = MagicMock()
    blast_r.sri_infrastructure = 20.0
    policy_r = MagicMock()
    policy_r.sri_policy = 25.0
    policy_r.violations = []
    hist_r = MagicMock()
    hist_r.sri_historical = 20.0
    fin_r = MagicMock()
    fin_r.sri_cost = 10.0

    pipeline._blast.evaluate = AsyncMock(return_value=blast_r)
    pipeline._policy.evaluate = AsyncMock(return_value=policy_r)
    pipeline._historical.evaluate = AsyncMock(return_value=hist_r)
    pipeline._financial.evaluate = AsyncMock(return_value=fin_r)

    refined_verdict = _make_verdict(30.0)
    refined_verdict.few_shot_examples_used = []
    pipeline._engine.evaluate = MagicMock(return_value=refined_verdict)

    first_verdict = _make_verdict(29.0)  # borderline (near 30)
    action = MagicMock()
    action.action_type.value = "restart_service"
    action.target.resource_id = "vm-01"
    action.target.resource_type = "microsoft.compute/virtualmachines"
    action.reason = "restart"

    examples = [{"seed_id": "seed-001", "is_seed": True, "is_validated": True, "summary_text": "test"}]

    with patch("src.core.few_shot_retrieval.retrieve_similar_validated", new=AsyncMock(return_value=examples)):
        result = await pipeline._maybe_rerun_borderline(action, first_verdict, {}, False)

    # Rerun should have been triggered
    assert pipeline._blast.evaluate.called
    call_kwargs = pipeline._blast.evaluate.call_args.kwargs
    assert call_kwargs.get("few_shot_examples") == examples


@pytest.mark.asyncio
async def test_non_borderline_path_skips_rerun():
    """Non-borderline verdict skips rerun entirely."""
    from src.core.pipeline import RuriSkryPipeline

    pipeline = RuriSkryPipeline.__new__(RuriSkryPipeline)
    pipeline._blast = MagicMock()
    pipeline._blast.evaluate = AsyncMock()

    first_verdict = _make_verdict(50.0)  # clearly in the middle — not borderline
    action = MagicMock()

    with patch("src.core.few_shot_retrieval.retrieve_similar_validated", new=AsyncMock()) as mock_retrieve:
        result = await pipeline._maybe_rerun_borderline(action, first_verdict, {}, False)

    # No rerun, original verdict returned
    assert result is first_verdict
    assert not mock_retrieve.called
    assert not pipeline._blast.evaluate.called

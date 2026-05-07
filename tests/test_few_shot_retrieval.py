"""Tests for Phase 38B: few-shot retrieval.

Covers:
1. test_retrieval_returns_top_k_by_similarity
2. test_retrieval_returns_empty_on_search_failure
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.few_shot_retrieval import retrieve_similar_validated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    action_type: str = "restart_service",
    resource_id: str = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-01",
    resource_type: str = "microsoft.compute/virtualmachines",
    reason: str = "VM needs restart",
) -> MagicMock:
    action = MagicMock()
    action.action_type.value = action_type
    action.target.resource_id = resource_id
    action.target.resource_type = resource_type
    action.reason = reason
    return action


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieval_returns_top_k_by_similarity():
    """Returns up to K examples from the search client."""
    examples = [
        {"seed_id": f"seed-{i}", "verdict": "approved", "is_seed": True, "is_validated": True}
        for i in range(5)
    ]
    sc = MagicMock()
    sc.search_validated_similar = MagicMock(return_value=examples[:3])

    with patch("src.core.decision_embedder.embed_text", new=AsyncMock(return_value=[0.0] * 1536)):
        results = await retrieve_similar_validated(_make_action(), k=3, search_client=sc)

    assert len(results) == 3
    assert sc.search_validated_similar.called
    call_args = sc.search_validated_similar.call_args
    assert call_args.args[1] == 3  # k=3


@pytest.mark.asyncio
async def test_retrieval_returns_empty_on_search_failure():
    """AI Search failure → graceful degradation returns empty list."""
    sc = MagicMock()
    sc.search_validated_similar = MagicMock(side_effect=ConnectionError("Search down"))

    with patch("src.core.decision_embedder.embed_text", new=AsyncMock(return_value=[0.0] * 1536)):
        results = await retrieve_similar_validated(_make_action(), k=3, search_client=sc)

    assert results == []


@pytest.mark.asyncio
async def test_retrieval_embed_failure_returns_empty():
    """Embedding failure → graceful degradation returns empty list."""
    async def _raise_embed(*a, **kw):
        raise RuntimeError("OpenAI down")

    with patch("src.core.decision_embedder.embed_text", new=AsyncMock(side_effect=_raise_embed)):
        results = await retrieve_similar_validated(_make_action(), k=3)

    assert results == []

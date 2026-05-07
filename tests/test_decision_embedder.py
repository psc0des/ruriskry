"""Tests for Phase 38A: decision embedder.

Covers:
1. test_decision_embedder_produces_1536_dim_vector
2. test_decision_embedder_deterministic_text_builder
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from src.core.decision_embedder import build_embedding_text, embed_text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_decision_embedder_deterministic_text_builder():
    """build_embedding_text produces the expected structured format."""
    record = {
        "action_type": "restart_service",
        "resource_type": "microsoft.compute/virtualmachines",
        "resource_id": "/subscriptions/sub/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-01",
        "triage_tier": 3,
        "action_reason": "VM is deallocated",
    }
    text = build_embedding_text(record)
    assert "action_type=restart_service" in text
    assert "resource_type=microsoft.compute/virtualmachines" in text
    assert "criticality=critical production" in text
    assert "reason=VM is deallocated" in text


def test_decision_embedder_text_stable_for_same_input():
    """Same record always produces the same text (deterministic)."""
    record = {
        "action_type": "delete_resource",
        "resource_type": "microsoft.compute/virtualmachines",
        "resource_id": "vm-dev",
        "action_reason": "Unused dev VM",
    }
    assert build_embedding_text(record) == build_embedding_text(record)


@pytest.mark.asyncio
async def test_decision_embedder_produces_1536_dim_vector():
    """embed_text returns exactly 1536 floats in mock mode."""
    from src.config import Settings
    cfg = Settings(use_local_mocks=True)
    vector = await embed_text("test text", cfg=cfg)
    assert isinstance(vector, list)
    assert len(vector) == 1536
    assert all(isinstance(v, float) for v in vector)

"""Tests for Phase 38A: seed bank loader.

Covers:
1. test_seed_bank_loads_on_first_run
2. test_seed_bank_idempotent
3. test_seed_bank_load_failure_non_fatal
4. test_seed_bank_schema
5. test_seed_bank_coverage
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.seed_bank_loader import load_seed_bank_if_needed, _SEED_BANK_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"seed_id", "action_type", "resource_type", "summary_text", "verdict", "sri_composite", "outcome_reason"}

COVERAGE_MATRIX = {
    ("delete_resource",  "approved"),
    ("delete_resource",  "approved_if"),
    ("delete_resource",  "escalated"),
    ("delete_resource",  "denied"),
    ("restart_service",  "approved"),
    ("restart_service",  "approved_if"),
    ("restart_service",  "escalated"),
    ("restart_service",  "denied"),
    ("update_config",    "approved"),
    ("update_config",    "approved_if"),
    ("update_config",    "escalated"),
    ("update_config",    "denied"),
    ("modify_nsg",       "approved"),
    ("modify_nsg",       "approved_if"),
    ("modify_nsg",       "escalated"),
    ("modify_nsg",       "denied"),
    ("scale_up",         "approved"),
    ("scale_up",         "escalated"),
    ("scale_down",       "approved"),
    ("scale_down",       "approved_if"),
    ("scale_down",       "escalated"),
}


def _mock_search_client(existing_seeds: int = 0):
    sc = MagicMock()
    sc.count_seeds = MagicMock(return_value=existing_seeds)
    sc.upsert_few_shot_example = MagicMock()
    return sc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_seed_bank_schema():
    """Every example in the seed bank has all required keys."""
    assert _SEED_BANK_PATH.exists(), f"Seed bank not found at {_SEED_BANK_PATH}"
    bank = json.loads(_SEED_BANK_PATH.read_text(encoding="utf-8"))
    examples = bank.get("examples", [])
    assert len(examples) >= 30, f"Expected ≥30 examples, got {len(examples)}"
    for ex in examples:
        missing = REQUIRED_KEYS - set(ex.keys())
        assert not missing, f"Example {ex.get('seed_id')} missing keys: {missing}"


def test_seed_bank_coverage():
    """At least 1 example per (action_type, verdict) pair from the coverage matrix."""
    bank = json.loads(_SEED_BANK_PATH.read_text(encoding="utf-8"))
    examples = bank.get("examples", [])
    present_pairs = {(ex["action_type"], ex["verdict"]) for ex in examples}
    missing_pairs = COVERAGE_MATRIX - present_pairs
    assert not missing_pairs, f"Seed bank missing coverage for: {missing_pairs}"


@pytest.mark.asyncio
async def test_seed_bank_loads_on_first_run():
    """Fresh install: count_seeds=0 → uploads all examples."""
    sc = _mock_search_client(existing_seeds=0)

    with patch("src.core.seed_bank_loader._safe_count_seeds", new=AsyncMock(return_value=0)):
        with patch("src.core.seed_bank_loader._safe_upsert", new=AsyncMock()) as mock_upsert:
            with patch("src.core.decision_embedder.embed_text", new=AsyncMock(return_value=[0.0] * 1536)):
                count = await load_seed_bank_if_needed(sc)

    assert count > 0
    assert mock_upsert.called


@pytest.mark.asyncio
async def test_seed_bank_idempotent():
    """Already loaded: count_seeds>0 → no upload, returns 0."""
    sc = _mock_search_client(existing_seeds=40)

    with patch("src.core.seed_bank_loader._safe_count_seeds", new=AsyncMock(return_value=40)):
        count = await load_seed_bank_if_needed(sc)

    assert count == 0
    sc.upsert_few_shot_example.assert_not_called()


@pytest.mark.asyncio
async def test_seed_bank_load_failure_non_fatal():
    """AI Search down → log + return 0, no exception propagated."""
    sc = _mock_search_client()

    async def _raise(*a, **kw):
        raise ConnectionError("AI Search unreachable")

    with patch("src.core.seed_bank_loader._safe_count_seeds", new=AsyncMock(side_effect=ConnectionError("down"))):
        count = await load_seed_bank_if_needed(sc)  # must not raise

    assert count == 0

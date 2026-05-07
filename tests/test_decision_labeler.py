"""Tests for Phase 36B: DecisionLabeler background task.

Covers:
1. test_labeler_marks_aged_decisions
2. test_labeler_skips_already_labeled
3. test_labeler_idempotent
4. test_labeler_handles_empty_container  (OSS critical)
5. test_labeler_skips_denied_decisions
6. test_labeler_skips_decisions_in_window
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.core.decision_labeler import DecisionLabeler, CORRELATION_WINDOW_DAYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(
    decision_id: str,
    days_ago: int = 10,
    outcome_label=None,
    decision: str = "approved",
) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "action_id": decision_id,
        "id": decision_id,
        "timestamp": ts,
        "decision": decision,
        "outcome_label": outcome_label,
        "correlated_alert_ids": [],
    }


def _make_tracker(records: list[dict]):
    dt = MagicMock()
    dt.get_recent.return_value = records
    updated: list[str] = []

    def _update(decision_id, label, alert_ids):
        updated.append(decision_id)

    dt.update_outcome_label.side_effect = _update
    dt._labeled_ids = updated
    return dt


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_labeler_marks_aged_decisions():
    """Aged APPROVED/ESCALATED decisions without a label get labeled no_incident_observed."""
    records = [
        _make_decision("d-001", days_ago=CORRELATION_WINDOW_DAYS + 1),
        _make_decision("d-002", days_ago=CORRELATION_WINDOW_DAYS + 5, decision="escalated"),
    ]
    dt = _make_tracker(records)
    labeler = DecisionLabeler(dt)

    count = await labeler._poll()

    assert count == 2
    assert dt.update_outcome_label.call_count == 2
    calls = {c.kwargs["decision_id"] for c in dt.update_outcome_label.call_args_list}
    assert "d-001" in calls
    assert "d-002" in calls
    for c in dt.update_outcome_label.call_args_list:
        assert c.kwargs["label"] == "no_incident_observed"


@pytest.mark.asyncio
async def test_labeler_skips_already_labeled():
    """Decisions that already have a label are not re-labeled."""
    records = [
        _make_decision("d-001", days_ago=10, outcome_label="incident_correlated"),
        _make_decision("d-002", days_ago=10, outcome_label="no_incident_observed"),
    ]
    dt = _make_tracker(records)
    labeler = DecisionLabeler(dt)

    count = await labeler._poll()

    assert count == 0
    assert not dt.update_outcome_label.called


@pytest.mark.asyncio
async def test_labeler_idempotent():
    """Running the labeler twice produces the same results (second run labels 0)."""
    records = [_make_decision("d-001", days_ago=10)]
    dt = _make_tracker(records)
    labeler = DecisionLabeler(dt)

    count1 = await labeler._poll()
    assert count1 == 1

    # Simulate second run: the record now has outcome_label set
    records[0]["outcome_label"] = "no_incident_observed"
    count2 = await labeler._poll()
    assert count2 == 0


@pytest.mark.asyncio
async def test_labeler_handles_empty_container():
    """A fresh OSS install with zero decisions is a no-op — does not crash."""
    dt = _make_tracker([])  # empty container
    labeler = DecisionLabeler(dt)

    count = await labeler._poll()  # must not raise

    assert count == 0
    assert not dt.update_outcome_label.called


@pytest.mark.asyncio
async def test_labeler_skips_denied_decisions():
    """DENIED decisions are skipped — we blocked them, no incident is expected."""
    records = [
        _make_decision("d-denied", days_ago=10, decision="denied"),
    ]
    dt = _make_tracker(records)
    labeler = DecisionLabeler(dt)

    count = await labeler._poll()

    assert count == 0
    assert not dt.update_outcome_label.called


@pytest.mark.asyncio
async def test_labeler_skips_decisions_in_window():
    """Recent decisions (inside the 7-day window) are not labeled yet."""
    records = [
        _make_decision("d-recent", days_ago=3),  # only 3 days old
    ]
    dt = _make_tracker(records)
    labeler = DecisionLabeler(dt)

    count = await labeler._poll()

    assert count == 0
    assert not dt.update_outcome_label.called

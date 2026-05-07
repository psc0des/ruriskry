"""Tests for Phase 36C: GET /api/metrics/accuracy endpoint.

Covers:
1. test_metrics_accuracy_empty_state_shape
2. test_metrics_accuracy_partial_state
3. test_metrics_accuracy_populated_state
4. test_metrics_accuracy_confusion_matrix_correctness
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.dashboard_api import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_labeled_record(
    decision_id: str,
    decision: str,
    outcome_label: str,
    days_ago: int = 5,
    action_type: str = "restart_service",
) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "id": decision_id,
        "action_id": decision_id,
        "timestamp": ts,
        "decision": decision,
        "outcome_label": outcome_label,
        "action_type": action_type,
        "sri_composite": 35.0,
    }


def _mock_labeled(records):
    """Patch CosmosDecisionClient.get_labeled to return given records."""
    return patch(
        "src.api.dashboard_api._get_tracker",
        return_value=_tracker_with_labeled(records),
    )


def _tracker_with_labeled(records):
    tracker = MagicMock()
    cosmos = MagicMock()
    cosmos.get_labeled.return_value = records
    tracker._cosmos = cosmos
    return tracker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_metrics_accuracy_empty_state_shape():
    """Zero labeled decisions → empty_state: true with null precision/recall/f1."""
    client = TestClient(app)
    with _mock_labeled([]):
        resp = client.get("/api/metrics/accuracy")
    assert resp.status_code == 200
    data = resp.json()

    assert data["empty_state"] is True
    assert data["empty_state_reason"] == "no_labeled_decisions_yet"
    assert data["total_labeled"] == 0
    assert data["precision"] is None
    assert data["recall"] is None
    assert data["f1"] is None
    # Confusion matrix should exist with zero counts
    cm = data["confusion_matrix"]
    assert cm["tp"] == 0 and cm["tn"] == 0 and cm["fp"] == 0 and cm["fn"] == 0
    # by_predicted_verdict must be present (same shape)
    bpv = data["by_predicted_verdict"]
    for v in ("approved", "approved_if", "escalated", "denied"):
        assert v in bpv
        assert bpv[v]["incident_correlated"] == 0


def test_metrics_accuracy_partial_state():
    """Some labeled decisions → empty_state: false, metrics computed."""
    records = [
        _make_labeled_record("d-1", "approved", "no_incident_observed"),
        _make_labeled_record("d-2", "escalated", "incident_correlated"),
    ]
    client = TestClient(app)
    with _mock_labeled(records):
        resp = client.get("/api/metrics/accuracy")
    assert resp.status_code == 200
    data = resp.json()

    assert data["empty_state"] is False
    assert data["total_labeled"] == 2


def test_metrics_accuracy_confusion_matrix_correctness():
    """Confusion matrix cells are computed correctly.

    Scenario:
      - 3 APPROVED → no incident  → TN = 3
      - 1 APPROVED → incident     → FN = 1
      - 2 ESCALATED → incident    → TP = 2
      - 1 ESCALATED → no incident → FP = 1
    """
    records = [
        _make_labeled_record("d-1", "approved", "no_incident_observed"),
        _make_labeled_record("d-2", "approved", "no_incident_observed"),
        _make_labeled_record("d-3", "approved", "no_incident_observed"),
        _make_labeled_record("d-4", "approved", "incident_correlated"),  # FN
        _make_labeled_record("d-5", "escalated", "incident_correlated"),  # TP
        _make_labeled_record("d-6", "escalated", "incident_correlated"),  # TP
        _make_labeled_record("d-7", "escalated", "no_incident_observed"),  # FP
    ]
    client = TestClient(app)
    with _mock_labeled(records):
        resp = client.get("/api/metrics/accuracy")
    data = resp.json()
    cm = data["confusion_matrix"]

    assert cm["tp"] == 2  # 2 ESCALATED predicted incident
    assert cm["tn"] == 3  # 3 APPROVED safe
    assert cm["fp"] == 1  # 1 ESCALATED over-flagged
    assert cm["fn"] == 1  # 1 APPROVED missed risk

    # Precision = TP / (TP+FP) = 2 / 3
    assert abs(data["precision"] - round(2 / 3, 3)) < 0.001
    # Recall = TP / (TP+FN) = 2 / 3
    assert abs(data["recall"] - round(2 / 3, 3)) < 0.001
    # F1 ≈ 0.667
    assert data["f1"] is not None
    assert data["f1"] > 0


def test_metrics_accuracy_populated_state_no_empty():
    """When there are labeled records, empty_state must be false."""
    records = [
        _make_labeled_record("d-1", "denied", "no_incident_observed"),
    ]
    client = TestClient(app)
    with _mock_labeled(records):
        resp = client.get("/api/metrics/accuracy")
    data = resp.json()
    assert data["empty_state"] is False

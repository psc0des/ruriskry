"""Tests for Phase 36A: decision-alert forward correlator.

Covers:
1. test_correlator_links_alert_to_recent_decision
2. test_correlator_respects_window
3. test_correlator_skips_resource_mismatch
4. test_correlator_links_multiple_decisions_on_same_resource
5. test_correlator_idempotent
6. test_alert_normalizer_calls_correlator
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.core.decision_alert_correlator import correlate_alert_to_decisions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RESOURCE_ID = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-web-01"


def _make_decision(
    decision_id: str,
    resource_id: str = RESOURCE_ID,
    days_ago: int = 1,
    outcome_label=None,
    correlated_alert_ids=None,
) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "action_id": decision_id,
        "id": decision_id,
        "resource_id": resource_id,
        "timestamp": ts,
        "decision": "approved",
        "outcome_label": outcome_label,
        "correlated_alert_ids": correlated_alert_ids or [],
    }


def _make_alert(
    alert_id: str = "alert-001",
    resource_id: str = RESOURCE_ID,
) -> dict:
    return {
        "alert_id": alert_id,
        "resource_id": resource_id,
        "metric": "Percentage CPU",
    }


def _make_trackers(decisions: list[dict], initial_alert: dict | None = None):
    """Return (decision_tracker_mock, alert_tracker_mock) with canned data."""
    dt = MagicMock()
    dt.get_by_resource.return_value = decisions

    updated_decisions: dict[str, dict] = {}

    def _update_label(decision_id, label, alert_ids):
        updated_decisions[decision_id] = {"label": label, "alert_ids": alert_ids}

    dt.update_outcome_label.side_effect = _update_label
    dt._updated = updated_decisions

    at = MagicMock()
    updated_alerts: dict[str, list] = {}

    def _update_correlated(alert_id, decision_ids):
        updated_alerts[alert_id] = decision_ids

    at.update_correlated_decisions.side_effect = _update_correlated
    at._updated = updated_alerts

    return dt, at


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_correlator_links_alert_to_recent_decision():
    """An alert on a resource that had a recent decision links both records."""
    decision = _make_decision("d-001", days_ago=2)
    dt, at = _make_trackers([decision])
    alert = _make_alert("a-001")

    linked = correlate_alert_to_decisions(alert, dt, at)

    assert linked == ["d-001"]
    assert dt.update_outcome_label.called
    call_args = dt.update_outcome_label.call_args
    assert call_args.kwargs["label"] == "incident_correlated"
    assert "a-001" in call_args.kwargs["alert_ids"]
    assert at.update_correlated_decisions.called
    at_call = at.update_correlated_decisions.call_args
    assert "d-001" in at_call.kwargs["decision_ids"]


def test_correlator_respects_window():
    """Decisions older than 7 days are NOT linked."""
    old_decision = _make_decision("d-old", days_ago=8)
    dt, at = _make_trackers([old_decision])
    alert = _make_alert("a-001")

    linked = correlate_alert_to_decisions(alert, dt, at, window_days=7)

    assert linked == []
    assert not dt.update_outcome_label.called
    assert not at.update_correlated_decisions.called


def test_correlator_skips_resource_mismatch():
    """A decision on a different resource_id is not linked."""
    different_resource = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-other"
    decision = _make_decision("d-other", resource_id=different_resource, days_ago=1)
    # get_by_resource would normally filter, but our mock returns it — test the
    # exact-match logic in correlate_alert_to_decisions.
    dt, at = _make_trackers([decision])
    alert = _make_alert("a-001", resource_id=RESOURCE_ID)

    linked = correlate_alert_to_decisions(alert, dt, at)

    assert linked == []
    assert not dt.update_outcome_label.called


def test_correlator_links_multiple_decisions_on_same_resource():
    """Two recent decisions on the same resource are both linked."""
    d1 = _make_decision("d-001", days_ago=1)
    d2 = _make_decision("d-002", days_ago=3)
    dt, at = _make_trackers([d1, d2])
    alert = _make_alert("a-001")

    linked = correlate_alert_to_decisions(alert, dt, at)

    assert set(linked) == {"d-001", "d-002"}
    assert dt.update_outcome_label.call_count == 2
    at_call = at.update_correlated_decisions.call_args
    assert "d-001" in at_call.kwargs["decision_ids"]
    assert "d-002" in at_call.kwargs["decision_ids"]


def test_correlator_idempotent():
    """Re-ingesting the same alert_id does not duplicate the backref."""
    decision = _make_decision(
        "d-001",
        days_ago=1,
        correlated_alert_ids=["a-001"],  # already linked
    )
    dt, at = _make_trackers([decision])
    alert = _make_alert("a-001")

    linked = correlate_alert_to_decisions(alert, dt, at)

    # Should still return the decision_id (it's matched)
    assert "d-001" in linked
    # But update_outcome_label should NOT be called again (alert already present)
    assert not dt.update_outcome_label.called


def test_correlator_returns_empty_when_no_resource_id():
    """Alert with empty resource_id silently returns []."""
    dt = MagicMock()
    at = MagicMock()
    alert = {"alert_id": "a-001", "resource_id": ""}

    linked = correlate_alert_to_decisions(alert, dt, at)

    assert linked == []
    assert not dt.get_by_resource.called


def test_alert_normalizer_calls_correlator(tmp_path):
    """Verify the alert-trigger endpoint calls the correlator after persist."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch as _patch
    from src.api.dashboard_api import app

    with _patch("src.core.decision_alert_correlator.correlate_alert_to_decisions") as mock_corr:
        mock_corr.return_value = []
        client = TestClient(app)

        payload = {
            "data": {
                "essentials": {
                    "alertId": "/subscriptions/sub/providers/Microsoft.AlertsManagement/alerts/test-alert",
                    "alertRule": "cpu-high",
                    "severity": "Sev3",
                    "signalType": "Metric",
                    "monitorCondition": "Fired",
                    "monitoringService": "Platform",
                    "firedDateTime": "2024-01-01T00:00:00Z",
                    "alertTargetIDs": [
                        "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-test"
                    ],
                }
            }
        }
        resp = client.post("/api/alert-trigger", json=payload)
        # Endpoint should succeed (200) and correlator should have been called
        assert resp.status_code == 200
        assert mock_corr.called

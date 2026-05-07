"""Phase 36A — Forward correlation: link ingested alerts to recent decisions.

When an alert fires on a resource, we query governance-decisions for any
verdict on the same resource_id within the last 7 days. Both records get
backreference fields updated and the decision gets ``outcome_label =
"incident_correlated"``.

This is the forward half of the loop. The backward labeler (decision_labeler.py)
closes the loop by marking aged decisions that never saw a correlated alert.

Design notes
------------
- Window is 7 days by default, configurable via ALERT_CORRELATION_WINDOW_DAYS.
- Exact resource_id match only — fuzzy matching causes false positives that
  corrupt the accuracy metrics we're building toward.
- Idempotent: re-ingesting the same alert does not add duplicate backref entries.
- All storage calls are delegated to decision_tracker and alert_tracker so
  this module never touches Cosmos directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default correlation window: decisions older than this aren't linked to an alert.
_DEFAULT_WINDOW_DAYS: int = 7


def correlate_alert_to_decisions(
    alert: dict[str, Any],
    decision_tracker,
    alert_tracker,
    window_days: int = _DEFAULT_WINDOW_DAYS,
) -> list[str]:
    """Link an ingested alert to recent decisions on the same resource.

    Queries governance-decisions for verdicts on ``alert["resource_id"]``
    within the last ``window_days`` days. For each match, sets
    ``outcome_label = "incident_correlated"`` on the decision and adds
    backreference fields to both records.

    This function is synchronous — it is called from the synchronous section
    of the alert-trigger endpoint after the alert record is persisted.

    Args:
        alert: Normalised alert dict (must have ``alert_id`` and ``resource_id``).
        decision_tracker: DecisionTracker instance (provides get_by_resource).
        alert_tracker: AlertTracker instance (provides upsert).
        window_days: Correlation window in days (default 7).

    Returns:
        List of decision_ids (action_ids) that were linked to this alert.
        Returns [] if no matches or if resource_id is empty.
    """
    alert_id = alert.get("alert_id", "")
    resource_id = alert.get("resource_id", "")

    if not resource_id:
        logger.debug("correlator: no resource_id on alert %s — skipping", alert_id[:8] if alert_id else "?")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    cutoff_iso = cutoff.isoformat()

    # Query all decisions for this resource (get a generous limit — unlikely
    # to have hundreds of decisions on one resource within 7 days).
    candidates = decision_tracker.get_by_resource(resource_id, limit=200)

    # Filter to the correlation window and exact resource_id match.
    window_decisions = [
        d for d in candidates
        if d.get("resource_id", "") == resource_id
        and d.get("timestamp", "") >= cutoff_iso
    ]

    if not window_decisions:
        logger.debug(
            "correlator: no decisions within %dd for resource %s (alert %s)",
            window_days,
            resource_id.split("/")[-1] if "/" in resource_id else resource_id,
            alert_id[:8] if alert_id else "?",
        )
        return []

    linked_ids: list[str] = []
    for decision in window_decisions:
        decision_id = decision.get("action_id") or decision.get("id", "")
        if not decision_id:
            continue

        # Idempotency: don't add the alert_id twice if alert is replayed.
        existing_alerts = decision.get("correlated_alert_ids", [])
        if alert_id in existing_alerts:
            logger.debug(
                "correlator: alert %s already linked to decision %s — skipping",
                alert_id[:8],
                decision_id[:8],
            )
            linked_ids.append(decision_id)
            continue

        # Update the decision record: add outcome_label + alert backref.
        decision_tracker.update_outcome_label(
            decision_id=decision_id,
            label="incident_correlated",
            alert_ids=existing_alerts + [alert_id],
        )
        linked_ids.append(decision_id)

    if linked_ids:
        # Update the alert record: add decision backrefs.
        alert_tracker.update_correlated_decisions(
            alert_id=alert_id,
            decision_ids=linked_ids,
        )
        logger.info(
            "correlator: linked alert %s to %d decision(s) on resource %s",
            alert_id[:8] if alert_id else "?",
            len(linked_ids),
            resource_id.split("/")[-1] if "/" in resource_id else resource_id,
        )

    return linked_ids

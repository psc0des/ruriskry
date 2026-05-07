"""Phase 36B — Backward labeler: mark aged decisions with no correlated alert.

Runs every 6 hours as a background asyncio task. For every decision that:
  - is older than CORRELATION_WINDOW_DAYS (7 days), AND
  - has outcome_label == None (not yet labeled)

…sets outcome_label = "no_incident_observed" and labeled_at = now.

Special case: DENIED decisions where the verdict was never executed are
not interesting for confusion-matrix purposes (we never let the action
run, so no incident is expected). Those are skipped.

OSS contract: a fresh install with an empty decisions container is a
complete no-op — the labeler reads 0 records and exits the poll cleanly.

Usage (mirrors ConditionWatcher pattern):
    labeler = DecisionLabeler(decision_tracker)
    asyncio.create_task(labeler.run())   # started in FastAPI lifespan
    labeler.stop()                       # called during shutdown
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

POLL_INTERVAL_S: int = 6 * 3600   # 6 hours
CORRELATION_WINDOW_DAYS: int = 7


class DecisionLabeler:
    """Async background task that labels aged governance decisions.

    For each unlabeled decision older than the correlation window, sets
    ``outcome_label = "no_incident_observed"`` so the metrics endpoint can
    count it without time arithmetic at read time.

    Args:
        decision_tracker: DecisionTracker instance that provides storage.
    """

    def __init__(self, decision_tracker) -> None:
        self._tracker = decision_tracker
        self._running = False

    async def run(self) -> None:
        """Poll loop — runs until stop() is called."""
        self._running = True
        logger.info(
            "DecisionLabeler: started (interval=%dh, window=%dd)",
            POLL_INTERVAL_S // 3600,
            CORRELATION_WINDOW_DAYS,
        )
        while self._running:
            try:
                labeled = await self._poll()
                if labeled:
                    logger.info("DecisionLabeler: labeled %d decisions", labeled)
            except Exception as exc:  # noqa: BLE001
                logger.error("DecisionLabeler: poll error — %s", exc)
            await asyncio.sleep(POLL_INTERVAL_S)
        logger.info("DecisionLabeler: stopped")

    def stop(self) -> None:
        """Signal the labeler loop to exit after the current sleep."""
        self._running = False

    async def _poll(self) -> int:
        """Label all aged, unlabeled decisions. Returns count labeled."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=CORRELATION_WINDOW_DAYS)
        cutoff_iso = cutoff.isoformat()

        # Fetch a generous slice — in production this is at most ~thousands per 6h run.
        records = self._tracker.get_recent(limit=10_000)

        # Fresh OSS install: empty container is a no-op.
        if not records:
            return 0

        labeled = 0
        for record in records:
            # Skip if already labeled.
            if record.get("outcome_label") is not None:
                continue

            # Skip decisions inside the correlation window (too recent to label).
            ts = record.get("timestamp", "")
            if ts >= cutoff_iso:
                continue

            # Skip DENIED decisions that were never executed — we blocked them,
            # so no incident is expected. Only label if decision was APPROVED,
            # APPROVED_IF, or ESCALATED (or if executed flag is present).
            decision = record.get("decision", "").lower()
            if decision == "denied":
                continue

            decision_id = record.get("action_id") or record.get("id", "")
            if not decision_id:
                continue

            self._tracker.update_outcome_label(
                decision_id=decision_id,
                label="no_incident_observed",
                alert_ids=record.get("correlated_alert_ids", []),
            )
            labeled += 1

        return labeled

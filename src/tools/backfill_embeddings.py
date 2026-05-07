"""Phase 38A — Backfill CLI: embed existing governance decisions.

One-shot CLI to embed any decisions that lack embeddings and upsert them
into the AI Search ``governance-decisions`` index. Idempotent — safe to
re-run. Skips decisions that already have an ``embedding`` field set.

Usage:
    python -m src.tools.backfill_embeddings [--limit N] [--dry-run]

Options:
    --limit N    Max decisions to process (default: all)
    --dry-run    Print what would be uploaded without actually doing it
"""

from __future__ import annotations

import asyncio
import argparse
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def backfill(limit: int | None = None, dry_run: bool = False) -> int:
    """Walk all governance-decisions records, embed any without embedding.

    Idempotent: records with ``embedding`` already set are skipped.

    Args:
        limit: Maximum records to process. None = process all.
        dry_run: If True, log what would happen without writing.

    Returns:
        Count of records successfully embedded.
    """
    from src.core.decision_tracker import DecisionTracker  # noqa: PLC0415
    from src.core.decision_embedder import build_embedding_text, embed_text  # noqa: PLC0415
    from src.infrastructure.search_client import AzureSearchClient  # noqa: PLC0415

    tracker = DecisionTracker()
    search = AzureSearchClient()

    records = tracker.get_recent(limit=limit or 10_000)
    if not records:
        logger.info("backfill: no decision records found")
        return 0

    logger.info("backfill: found %d records total", len(records))
    embedded_count = 0
    skipped = 0

    for record in records:
        if record.get("embedding"):
            skipped += 1
            continue

        decision_id = record.get("action_id") or record.get("id", "")
        if not decision_id:
            continue

        text = build_embedding_text(record)
        if dry_run:
            logger.info("backfill [dry-run]: would embed %s: %s", decision_id[:8], text[:80])
            embedded_count += 1
            continue

        try:
            vector = await embed_text(text)

            # Determine is_validated
            is_validated = (
                record.get("outcome_label") is not None
            )

            doc = {
                "decision_id": decision_id,
                "embedding": vector,
                "action_type": record.get("action_type", "unknown"),
                "resource_type": (record.get("resource_type") or "").lower(),
                "verdict": record.get("decision", "unknown"),
                "sri_composite": record.get("sri_composite", 0.0),
                "summary_text": text,
                "is_validated": is_validated,
                "is_seed": False,
                "outcome_reason": record.get("verdict_reason", ""),
            }
            search.upsert_few_shot_example(doc)

            # Also update the Cosmos record with the embedding
            record["embedding"] = vector
            record["is_validated"] = is_validated
            tracker._cosmos.upsert(record)

            embedded_count += 1
            logger.info("backfill: embedded %s", decision_id[:8])
        except Exception as exc:  # noqa: BLE001
            logger.warning("backfill: failed %s — %s", decision_id[:8], exc)

    logger.info(
        "backfill complete: %d embedded, %d skipped (already had embedding)",
        embedded_count,
        skipped,
    )
    return embedded_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Max records to process")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args()

    count = asyncio.run(backfill(limit=args.limit, dry_run=args.dry_run))
    print(f"Backfill finished: {count} records processed.")


if __name__ == "__main__":
    main()

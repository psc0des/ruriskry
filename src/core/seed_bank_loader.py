"""Phase 38A — Idempotent seed bank loader.

Uploads the curated few-shot seed examples from ``data/few_shot_seed_bank.json``
into the AI Search ``governance-decisions`` index on startup. Idempotent:
every restart re-checks whether seeds are present and skips the upload if
they are. Failure is non-fatal — the system works without seed examples,
just less helpful on day 1.

OSS contract: a fresh install logs ``seed_bank: uploaded N examples`` once.
Subsequent restarts log ``seed_bank: already present — skipping``.

Usage:
    from src.core.seed_bank_loader import load_seed_bank_if_needed
    asyncio.create_task(load_seed_bank_if_needed(search_client))
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SEED_BANK_PATH = Path(__file__).parent.parent.parent / "data" / "few_shot_seed_bank.json"


async def load_seed_bank_if_needed(search_client) -> int:
    """Upload seed examples to AI Search if not already present.

    Idempotent: checks ``count_seeds()`` before any upload. If seeds are
    already in the index (from a previous startup), this is a fast no-op.

    Args:
        search_client: AzureSearchClient instance.

    Returns:
        Count of examples uploaded (0 if already present or no file found).
    """
    if not _SEED_BANK_PATH.exists():
        logger.warning("seed_bank: %s not found — skipping seed load", _SEED_BANK_PATH)
        return 0

    try:
        existing = await _safe_count_seeds(search_client)
        if existing > 0:
            logger.info(
                "seed_bank: already present (%d seeds) — skipping",
                existing,
            )
            return 0

        bank = json.loads(_SEED_BANK_PATH.read_text(encoding="utf-8"))
        examples = bank.get("examples", [])
        if not examples:
            logger.warning("seed_bank: file found but examples list is empty")
            return 0

        from src.core.decision_embedder import embed_text  # noqa: PLC0415

        uploaded = 0
        for ex in examples:
            try:
                vector = await embed_text(ex["summary_text"])
                doc = {
                    **ex,
                    "embedding": vector,
                    "is_seed": True,
                    "is_validated": True,
                }
                await _safe_upsert(search_client, doc)
                uploaded += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "seed_bank: failed to upload %s: %s",
                    ex.get("seed_id", "?"),
                    exc,
                )

        logger.info("seed_bank: uploaded %d examples", uploaded)
        return uploaded

    except Exception as exc:  # noqa: BLE001
        logger.warning("seed_bank: load failed (%s) — continuing without seeds", exc)
        return 0


async def _safe_count_seeds(search_client) -> int:
    """Count seeds, returning 0 on any error."""
    try:
        import asyncio  # noqa: PLC0415
        return await asyncio.to_thread(search_client.count_seeds)
    except Exception as exc:  # noqa: BLE001
        logger.debug("seed_bank: count_seeds failed (%s) — assuming 0", exc)
        return 0


async def _safe_upsert(search_client, doc: dict) -> None:
    """Upsert one document, swallowing errors."""
    import asyncio  # noqa: PLC0415
    await asyncio.to_thread(search_client.upsert_few_shot_example, doc)

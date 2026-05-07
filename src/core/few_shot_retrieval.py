"""Phase 38B — Retrieve similar validated/seed examples for few-shot injection.

Queries AI Search for the top-K most similar validated or seed examples for
a given action. Uses cosine similarity on the 1536-dim embedding vector.

Retrieval is intentionally simple:
- Filter to ``is_validated=true OR is_seed=true``
- Pure cosine similarity ranking — no reranking, no keyword boost
- As the operator accumulates real validated decisions, those naturally
  outrank seeds for their specific environment (because the vectors are
  closer to their actual resource patterns)

Returns ``[]`` on any failure — retrieval must never block governance.

Usage:
    from src.core.few_shot_retrieval import retrieve_similar_validated
    examples = await retrieve_similar_validated(action, k=3)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.models import ProposedAction

logger = logging.getLogger(__name__)

_DEFAULT_K: int = 3


async def retrieve_similar_validated(
    action: "ProposedAction",
    k: int = _DEFAULT_K,
    search_client=None,
) -> list[dict[str, Any]]:
    """Return the top-K most similar validated or seed examples for this action.

    Embeds the action text and searches the ``governance-decisions`` AI Search
    index, filtering to ``is_validated=true OR is_seed=true``.

    Args:
        action: The ProposedAction to find examples for.
        k: Number of examples to return (default 3).
        search_client: AzureSearchClient to use. Defaults to a fresh singleton.

    Returns:
        List of dicts, each representing one few-shot example. Empty on
        failure or when no similar examples are found.
    """
    try:
        return await _retrieve(action, k, search_client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("few_shot_retrieval: failed (%s) — returning empty list", exc)
        return []


async def _retrieve(
    action: "ProposedAction",
    k: int,
    search_client=None,
) -> list[dict[str, Any]]:
    import asyncio  # noqa: PLC0415
    from src.core.decision_embedder import build_embedding_text, embed_text  # noqa: PLC0415

    # Build the text to embed for this action
    action_record = {
        "action_type": action.action_type.value,
        "resource_type": action.target.resource_type or "",
        "resource_id": action.target.resource_id or "",
        "triage_tier": getattr(action, "triage_tier", None),
        "action_reason": action.reason or "",
    }
    text = build_embedding_text(action_record)
    vector = await embed_text(text)

    # Get the search client
    if search_client is None:
        from src.infrastructure.search_client import AzureSearchClient  # noqa: PLC0415
        search_client = AzureSearchClient()

    results = await asyncio.to_thread(
        search_client.search_validated_similar,
        vector,
        k,
    )
    return results

"""Phase 38A — Decision embedder: build structured text + call Azure OpenAI embeddings.

Every governance decision gets embedded on write. The 1536-dim vector is
stored in the ``governance-decisions`` AI Search index and used by the
few-shot retrieval path when a borderline decision is detected.

Design choices
--------------
- Model: ``text-embedding-3-small`` (1536-dim). Cheap, fast, adequate.
  Hardcoded — if we ever change models, all stored embeddings become
  incomparable. Document the assumption rather than hiding it in config.
- Text: a short structured summary of the action (not the full verdict).
  Long text dilutes vector similarity toward generic language.
- Mock mode: returns a deterministic 1536-dim zero vector. Real similarity
  ranking is not needed in tests — only that the shape is correct.
- Failure: non-fatal. If the embedding API is down, the decision is still
  persisted; it just won't participate in retrieval until the next
  backfill run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.config import settings as _default_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_EMBEDDING_DIM: int = 1536


def build_embedding_text(record: dict[str, Any]) -> str:
    """Build the short structured text that gets embedded.

    Format (deliberately concise — long text dilutes semantic similarity):

        action_type=restart_service
        resource_type=microsoft.compute/virtualmachines
        criticality=critical production
        tags=tier:web,owner:platform
        reason=VM is deallocated, requires restart for availability

    Works from a raw decision record dict (as stored in Cosmos) so it can
    be used both at write time and during backfill of existing records.
    """
    parts: list[str] = []

    action_type = record.get("action_type", "unknown")
    parts.append(f"action_type={action_type}")

    resource_type = (record.get("resource_type") or "").lower() or "unknown"
    parts.append(f"resource_type={resource_type}")

    # Derive criticality from triage_tier (phase 26 onward) or fallback heuristic
    tier = record.get("triage_tier")
    if tier == 3:
        crit = "critical production"
    elif tier == 2:
        rid = record.get("resource_id", "").lower()
        crit = "production" if "prod" in rid else "non-production"
    else:
        rid = record.get("resource_id", "").lower()
        crit = "non-production" if any(kw in rid for kw in ["dev", "test", "stage", "staging"]) else "production"
    parts.append(f"criticality={crit}")

    # Tags (not stored on raw decisions — omit if absent)
    tags = record.get("tags")
    if isinstance(tags, dict) and tags:
        tag_str = ",".join(f"{k}:{v}" for k, v in sorted(tags.items()))
        parts.append(f"tags={tag_str}")

    reason = (record.get("action_reason") or "")[:200]
    if reason:
        parts.append(f"reason={reason}")

    return " ".join(parts)


async def embed_text(text: str, cfg=None) -> list[float]:
    """Embed a short text string using Azure OpenAI text-embedding-3-small.

    Returns a 1536-dim float vector.

    In mock mode (USE_LOCAL_MOCKS=true or no Azure OpenAI endpoint), returns
    a deterministic zero vector so callers always get the right shape without
    network access.

    Args:
        text: The text to embed. Should be short and structured.
        cfg: Settings override (for tests).

    Returns:
        List of 1536 floats.

    Raises:
        Exception: Only propagated if the caller explicitly wraps it.
            Callers should treat failure as non-fatal (log + continue).
    """
    _cfg = cfg or _default_settings
    if _cfg.use_local_mocks or not _cfg.azure_openai_endpoint:
        return _mock_embedding(text)

    from openai import AsyncAzureOpenAI  # type: ignore[import]  # noqa: PLC0415
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider  # type: ignore[import]  # noqa: PLC0415

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    client = AsyncAzureOpenAI(
        azure_endpoint=_cfg.azure_openai_endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2024-02-01",
    )
    response = await client.embeddings.create(
        model=_cfg.azure_embedding_deployment,
        input=text,
    )
    vector: list[float] = response.data[0].embedding
    await client.close()
    return vector


def _mock_embedding(text: str) -> list[float]:
    """Deterministic mock embedding — all zeros. Shape is correct (1536-dim)."""
    return [0.0] * _EMBEDDING_DIM

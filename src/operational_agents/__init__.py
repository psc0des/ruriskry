"""Shared helpers for operational agents."""

import re

# Phrases in a proposal reason that indicate the resource is already compliant.
# If ANY of these appear, the proposal is a false positive and must be rejected
# regardless of what the LLM instructions say.  This is a deterministic gate —
# it cannot be overridden by LLM non-determinism or instruction drift.
_COMPLIANCE_PHRASES: tuple[str, ...] = (
    "no action needed",
    "no action required",
    "already compliant",
    "already configured",
    "already encrypted",
    "already secure",
    "already enabled",
    "already disabled",
    "already hardened",
    "already been",
    "is compliant",
    "is already",
    "no issues found",
    "no issues detected",
    "nothing to do",
    "resource is compliant",
    "configuration is compliant",
    "compliant and secure",
    "secure configuration",
    "no vulnerability",
    "no vulnerabilities",
    "not required",
    "does not require",
)

_COMPLIANCE_RE = re.compile(
    "|".join(re.escape(p) for p in _COMPLIANCE_PHRASES),
    re.IGNORECASE,
)


def is_compliant_reason(reason: str) -> bool:
    """Return True if the reason text signals the resource is already compliant.

    Used as a deterministic gate in every agent's tool_propose_action to block
    false-positive proposals that the LLM submits despite instructions.

    Args:
        reason: The free-text reason string the LLM passed to propose_action.

    Returns:
        True if the reason contains a compliance phrase → proposal should be
        rejected. False if no compliance phrase found → proposal is valid.
    """
    return bool(_COMPLIANCE_RE.search(reason))

# Rearchitecture: Governance Agents from "LLM as Narrator" to "LLM as Decision Maker"

## The Problem

All 4 governance agents (Policy, Blast Radius, Historical, Financial) follow an identical anti-pattern:

1. The LLM (GPT-4.1) receives the proposed action
2. The LLM calls a **deterministic tool** (`evaluate_policy_rules`, `evaluate_blast_radius_rules`, etc.)
3. The tool computes the score using fixed formulas — the LLM has zero influence on the number
4. The LLM writes a 2-3 sentence summary (narration) that gets appended to `reasoning`
5. The **pre-computed score** from the tool is returned unchanged

**The LLM adds no intelligence to the governance decision.** It is a narrator, not a decision maker. The score is 100% deterministic — the same inputs always produce the same output regardless of what the LLM thinks.

### Real-world consequence

When our Deploy Agent detected an SSH rule open to `*` (source `0.0.0.0/0`) and proposed `modify_nsg` to fix it, the Policy Agent's deterministic engine matched a `reason_pattern` regex against the word "SSH" in the action's reason text and returned CRITICAL severity. The Governance Engine auto-DENIED the fix — **the system blocked the remediation of the very security issue it detected.**

A truly intelligent governance agent would have understood: "Yes, this matches a security policy about open SSH. But the ops agent is trying to **fix** this problem, not **create** it. I should allow the remediation."

The current architecture cannot do this because the LLM never sees the policies, never understands intent, and never decides scores.

---

## Target Architecture

### Before (current)
```
Ops Agent proposes action
    |
    v
Governance Agent (LLM) --calls--> Deterministic Tool --returns--> Fixed Score
    |
    v
LLM writes summary paragraph (score unchanged)
    |
    v
GovernanceDecisionEngine applies thresholds
```

### After (target)
```
Ops Agent proposes action
    |
    v
Deterministic Tool runs FIRST --produces--> Baseline Score + Violation List
    |
    v
LLM receives: action + ops agent reasoning + policies + baseline score + all context
    |
    v
LLM REASONS about whether the baseline is correct given intent & context
    |
    v
LLM outputs structured JSON: { adjusted_score, adjustments[], reasoning }
    |
    v
Guardrails: adjusted score must be within +/-30 of baseline (safety net)
    |
    v
GovernanceDecisionEngine uses the LLM-adjusted score
```

### Key principles

1. **Deterministic rules become the baseline, not the final answer** — they still run first and catch obvious violations
2. **The LLM is the decision maker** — it can adjust scores up or down with justification
3. **Guardrails prevent hallucination** — the LLM cannot move the score more than 30 points from the deterministic baseline
4. **The LLM must output structured JSON** — not free-form text; we parse `adjusted_score` programmatically
5. **Mock mode is unchanged** — when `USE_LOCAL_MOCKS=true`, only deterministic rules run (tests pass as-is)
6. **Fallback on LLM failure** — if the LLM call fails or returns unparseable output, use the deterministic baseline

---

## Step-by-Step Implementation

### Step 1: Define the LLM Output Schema

Create a shared Pydantic model that all 4 agents will use for the LLM's structured output.

**File: `src/core/models.py`** — add near the existing result models:

```python
class GovernanceAdjustment(BaseModel):
    """A single score adjustment made by the LLM governance agent."""
    reason: str          # Why the adjustment was made
    delta: float         # Points added (positive) or removed (negative)
    policy_id: str | None = None  # Which policy this relates to (if applicable)

class LLMGovernanceOutput(BaseModel):
    """Structured output from an LLM governance agent."""
    adjusted_score: float                    # The LLM's recommended score (0-100)
    adjustments: list[GovernanceAdjustment]  # Each adjustment with justification
    reasoning: str                           # Free-form reasoning paragraph
    confidence: float = 0.8                  # 0-1, how confident the LLM is
```

---

### Step 2: Rearchitect PolicyComplianceAgent (Primary Target)

This is the most impactful agent to change because it has the `reason_pattern` problem.

**File: `src/governance_agents/policy_agent.py`**

#### 2a. Change `_AGENT_INSTRUCTIONS`

Replace the current instructions (lines 88-101) that tell the LLM to "call the tool first, then write a summary" with instructions that give the LLM decision-making authority:

```python
_AGENT_INSTRUCTIONS = """\
You are RuriSkry's Policy Compliance Governance Agent — an expert in cloud
governance with the authority to ADJUST compliance scores based on contextual reasoning.

## Your role
You receive a proposed infrastructure action along with a BASELINE compliance
score computed by deterministic policy rules. Your job is to reason about whether
that baseline score is appropriate given the FULL CONTEXT, including:

- The ops agent's INTENT (why it proposed this action)
- Whether the action REMEDIATES a problem vs. CREATES one
- The specific policies violated and whether they truly apply
- Edge cases the deterministic rules cannot handle

## Process
1. Call the `evaluate_policy_rules` tool to get the deterministic baseline score.
2. Review the baseline violations carefully.
3. For each violation, reason about whether it truly applies given the context:
   - Is the ops agent trying to FIX the issue the policy is designed to prevent?
   - Is the policy matching on a DESCRIPTION of a problem rather than the CREATION of one?
   - Are there mitigating factors (tags, environment, time) that the rules missed?
4. Output your decision as a JSON object using the `submit_governance_decision` tool.

## Adjustment rules
- You may adjust the baseline score by at most +/-30 points
- Adjustments MUST have clear justification
- When an ops agent is REMEDIATING a known issue, you should consider reducing the score
- When context suggests HIGHER risk than rules detected, you should increase the score
- If the baseline is correct, set adjusted_score = baseline score with no adjustments

## Critical: Remediation Intent Detection
If the ops agent's reason text DESCRIBES a security problem it found and wants to fix,
that is REMEDIATION INTENT — not a policy violation. For example:
- "Found SSH port 22 open to 0.0.0.0/0, restricting source" = REMEDIATION (lower score)
- "Opening SSH port 22 to 0.0.0.0/0" = CREATION of violation (keep/raise score)

Always distinguish between describing a problem to fix it vs. describing a problem to create it.
"""
```

#### 2b. Add `submit_governance_decision` tool

Inside `_evaluate_with_framework()`, after the existing `evaluate_policy_rules` tool, add a second tool that captures the LLM's structured decision:

```python
llm_decision_holder: list[dict] = []

@af.tool(
    name="submit_governance_decision",
    description=(
        "Submit your governance decision after reviewing the baseline score. "
        "adjusted_score must be within +/-30 of the baseline. "
        "Each adjustment must have a reason."
    ),
)
async def submit_governance_decision(
    adjusted_score: float,
    adjustments_json: str = "[]",
    reasoning: str = "",
    confidence: float = 0.8,
) -> str:
    """Record the LLM's governance decision."""
    import json as _json
    adjustments = _json.loads(adjustments_json) if adjustments_json else []
    llm_decision_holder.append({
        "adjusted_score": adjusted_score,
        "adjustments": adjustments,
        "reasoning": reasoning,
        "confidence": confidence,
    })
    return "Decision recorded."
```

#### 2c. Change the prompt sent to the LLM

Currently (lines 244-249), the prompt only sends the action JSON and metadata. Change it to include the policies, the ops agent's reasoning, and explicit instructions:

```python
# Build rich context for the LLM
policies_summary = json.dumps(self._policies, indent=2)
meta_str = json.dumps(resource_metadata or {})

prompt = (
    f"## Proposed Action\n{action.model_dump_json()}\n\n"
    f"## Ops Agent's Reasoning\n{action.reason}\n\n"
    f"## Resource Metadata\n{meta_str}\n\n"
    f"## Organization Policies\n{policies_summary}\n\n"
    "INSTRUCTIONS: First call evaluate_policy_rules to get the baseline score. "
    "Then reason about each violation. Then call submit_governance_decision "
    "with your adjusted score."
)
```

#### 2d. Apply the LLM adjustment with guardrails

After the agent runs, apply the LLM's decision to the baseline result:

```python
if result_holder and llm_decision_holder:
    base = result_holder[-1]
    decision = llm_decision_holder[-1]

    # Guardrail: clamp adjustment to +/-30 of baseline
    baseline = base.sri_policy
    adjusted = decision["adjusted_score"]
    clamped = max(0, min(100, max(baseline - 30, min(baseline + 30, adjusted))))

    enriched_reasoning = (
        base.reasoning
        + f"\n\nLLM Governance Analysis (GPT-4.1):\n"
        + decision.get("reasoning", "")
        + f"\n\nBaseline: {baseline:.1f} -> Adjusted: {clamped:.1f}"
    )
    if decision.get("adjustments"):
        for adj in decision["adjustments"]:
            enriched_reasoning += f"\n  - {adj.get('reason', '')}: {adj.get('delta', 0):+.0f} pts"

    return PolicyResult(
        sri_policy=clamped,
        violations=base.violations,
        total_policies_checked=base.total_policies_checked,
        policies_passed=base.policies_passed,
        reasoning=enriched_reasoning,
    )
```

#### 2e. Keep mock mode unchanged

The `evaluate()` method already returns `self._evaluate_rules()` directly when `self._use_framework` is False. **Do not change this path.** All existing tests use mock mode and must pass unchanged.

---

### Step 3: Rearchitect BlastRadiusAgent

**File: `src/governance_agents/blast_radius_agent.py`**

Apply the same pattern as Step 2 but with blast-radius-specific context:

#### 3a. New `_AGENT_INSTRUCTIONS`

```python
_AGENT_INSTRUCTIONS = """\
You are RuriSkry's Blast Radius Governance Agent — an expert in infrastructure
dependency analysis with the authority to ADJUST risk scores.

## Your role
You receive a proposed action and a BASELINE blast radius score from deterministic
analysis. You reason about whether the score reflects true risk given context.

## Process
1. Call `evaluate_blast_radius_rules` to get the baseline.
2. Reason about:
   - Is the action's blast radius overstated because affected resources are already degraded?
   - Are the SPOFs truly single points of failure, or do they have redundancy the graph missed?
   - Is this a routine maintenance action on a critical resource (lower risk than score suggests)?
   - Is the ops agent performing emergency remediation (justify faster approval)?
3. Call `submit_governance_decision` with your adjusted score.

## Adjustment rules
- Max +/-30 from baseline
- Emergency remediations on critical infrastructure may warrant score reduction
- Routine restarts of non-critical services may warrant reduction
- Actions affecting more services than the graph shows may warrant increase
"""
```

#### 3b. Add `submit_governance_decision` tool (same pattern as Step 2b)

#### 3c. Send enriched prompt with the ops agent's reason text

#### 3d. Apply guardrails (same `max(baseline - 30, min(baseline + 30, adjusted))` pattern)

---

### Step 4: Rearchitect HistoricalPatternAgent

**File: `src/governance_agents/historical_agent.py`**

#### 4a. New `_AGENT_INSTRUCTIONS`

```python
_AGENT_INSTRUCTIONS = """\
You are RuriSkry's Historical Pattern Governance Agent — an expert in incident
forensics with authority to ADJUST historical risk scores.

## Your role
You receive a baseline score from incident similarity matching. You reason about
whether past incidents are truly relevant to this specific action.

## Key reasoning dimensions
- Is the matched incident about the SAME failure mode, or just superficially similar?
- Has the infrastructure changed since the incident (making it less relevant)?
- Is the ops agent specifically trying to PREVENT a recurrence of the matched incident?
- Is the similarity score inflated by keyword overlap without semantic relevance?

## Process
1. Call `evaluate_historical_rules` to get baseline.
2. Examine each similar incident and reason about true relevance.
3. Call `submit_governance_decision` with adjusted score.

## Adjustment rules
- Max +/-30 from baseline
- If the ops agent is remediating the EXACT issue from a past incident, reduce score
- If the past incident is only superficially similar, reduce score
- If you find the incidents are MORE relevant than the similarity suggests, increase score
"""
```

#### 4b-4d. Same pattern: add `submit_governance_decision` tool, enrich prompt with incident details, apply guardrails.

**Important**: The `_governance_history_boost()` method is deterministic and should remain unchanged. The LLM adjustment is applied ON TOP of the governance-boosted baseline.

---

### Step 5: Rearchitect FinancialImpactAgent

**File: `src/governance_agents/financial_agent.py`**

#### 5a. New `_AGENT_INSTRUCTIONS`

```python
_AGENT_INSTRUCTIONS = """\
You are RuriSkry's Financial Governance Agent — an expert in cloud FinOps with
authority to ADJUST financial risk scores.

## Your role
You receive a baseline financial risk score and cost analysis. You reason about
whether the financial risk is accurately captured.

## Key reasoning dimensions
- Is the cost estimate based on actual data or uncertain heuristics?
- Is the over-optimisation risk real, or are the "dependent services" actually inactive?
- For cost-saving actions: does the saving justify the operational risk?
- For cost-increasing actions: is the spend justified by security or reliability needs?

## Process
1. Call `evaluate_financial_rules` to get baseline.
2. Reason about cost certainty, over-optimisation, and business justification.
3. Call `submit_governance_decision` with adjusted score.

## Adjustment rules
- Max +/-30 from baseline
- Security remediations that increase cost should get reduced financial risk scores
- Cost savings with uncertain estimates should get slightly increased scores
- Over-optimisation risk on truly critical services should be increased
"""
```

#### 5b-5d. Same pattern as other agents.

---

### Step 6: GovernanceDecisionEngine Changes

**File: `src/core/governance_engine.py`**

The GovernanceDecisionEngine itself needs **minimal changes**. It already works with numeric scores from each agent. Since the LLM-adjusted scores are still 0-100 floats, the weighted average and threshold logic works unchanged.

**One change needed**: The critical-policy-violation auto-DENIED rule (lines 183-194) currently checks `policy.violations` and auto-denies on CRITICAL severity. This should be **softened** to respect the LLM's reasoning:

```python
# BEFORE (current):
critical = [v for v in policy.violations if v.severity == PolicySeverity.CRITICAL]
if critical:
    return (SRIVerdict.DENIED, f"DENIED — critical policy violation(s)...")

# AFTER:
# Only auto-DENY on critical violations if the LLM did NOT reduce the policy score.
# If the LLM analyzed the violations and still assigned a high score, the violations
# are real. If the LLM reduced the score, it determined the violations don't truly apply.
critical = [v for v in policy.violations if v.severity == PolicySeverity.CRITICAL]
if critical and policy.sri_policy >= 40:
    # LLM either agreed with the critical violations or was not consulted (mock mode)
    ids = ", ".join(v.policy_id for v in critical)
    return (
        SRIVerdict.DENIED,
        f"DENIED — critical policy violation(s) detected: {ids}. "
        "Critical violations block execution regardless of composite SRI score.",
    )
```

The threshold of 40 is chosen because a single CRITICAL violation contributes 40 points in the deterministic engine. If the LLM reduced `sri_policy` below 40 despite a critical violation existing, it means the LLM determined the violation doesn't truly apply in this context.

---

### Step 7: Extract Common LLM Decision Pattern

Since all 4 agents follow the same "get baseline -> LLM reasons -> apply guardrails" pattern, extract a shared helper to avoid code duplication.

**File: `src/governance_agents/_llm_governance.py`** (new file)

```python
"""Shared utilities for LLM-driven governance score adjustment."""

import json
import logging

logger = logging.getLogger(__name__)

# Maximum points the LLM can adjust from the deterministic baseline
MAX_ADJUSTMENT = 30


def clamp_score(baseline: float, adjusted: float) -> float:
    """Clamp the LLM-adjusted score to within +/-MAX_ADJUSTMENT of baseline."""
    floor = max(0.0, baseline - MAX_ADJUSTMENT)
    ceiling = min(100.0, baseline + MAX_ADJUSTMENT)
    return round(max(floor, min(ceiling, adjusted)), 2)


def format_adjustments(baseline: float, clamped: float, adjustments: list[dict], llm_reasoning: str) -> str:
    """Format the LLM's adjustments into a human-readable reasoning block."""
    lines = [
        f"\nLLM Governance Analysis (GPT-4.1):",
        llm_reasoning,
        f"\nBaseline: {baseline:.1f} -> Adjusted: {clamped:.1f}",
    ]
    for adj in adjustments:
        lines.append(f"  - {adj.get('reason', '')}: {adj.get('delta', 0):+.0f} pts")
    return "\n".join(lines)


def parse_llm_decision(decision_holder: list[dict], baseline: float) -> tuple[float, str]:
    """Parse the LLM's decision, apply guardrails, return (clamped_score, adjustment_text).

    Returns (baseline, "") if the LLM didn't submit a decision.
    """
    if not decision_holder:
        return baseline, ""

    decision = decision_holder[-1]
    adjusted = decision.get("adjusted_score", baseline)
    clamped = clamp_score(baseline, adjusted)
    adjustments = decision.get("adjustments", [])
    reasoning = decision.get("reasoning", "")

    text = format_adjustments(baseline, clamped, adjustments, reasoning)
    return clamped, text
```

Each agent's `_evaluate_with_framework()` then calls:
```python
from src.governance_agents._llm_governance import parse_llm_decision

# After agent.run():
if result_holder:
    base = result_holder[-1]
    baseline_score = base.sri_policy  # or sri_infrastructure, etc.
    adjusted_score, adjustment_text = parse_llm_decision(llm_decision_holder, baseline_score)

    return PolicyResult(
        sri_policy=adjusted_score,
        ...
        reasoning=base.reasoning + adjustment_text,
    )
```

---

### Step 8: Update Tests

**Key principle: existing tests MUST pass unchanged.** All existing tests use mock mode (`USE_LOCAL_MOCKS=true`), which skips the LLM entirely and uses only deterministic rules. The LLM path is only active in live mode.

**New tests to add** (in `tests/test_governance_agents_llm.py` or similar):

1. **Test guardrail clamping** — verify `clamp_score()` with various baseline/adjusted combinations
2. **Test parse_llm_decision** — verify it returns baseline when no decision submitted
3. **Test format_adjustments** — verify output format
4. **Test critical-violation softening** — verify that `governance_engine.py` respects reduced `sri_policy` score:
   - Critical violation + `sri_policy >= 40` -> DENIED (LLM agreed with violations)
   - Critical violation + `sri_policy < 40` -> falls through to composite threshold (LLM overrode)
5. **Integration test** — mock the LLM to return a specific `submit_governance_decision` call and verify the end-to-end flow

**Run command:** `python -m pytest tests/ -x -q`

---

## Implementation Order

1. **`src/core/models.py`** — Add `GovernanceAdjustment` + `LLMGovernanceOutput` models
2. **`src/governance_agents/_llm_governance.py`** — Create shared utilities
3. **`src/governance_agents/policy_agent.py`** — Rearchitect (highest impact)
4. **`src/core/governance_engine.py`** — Soften critical-violation auto-DENY
5. **Run tests** — all 606 existing tests must pass
6. **`src/governance_agents/blast_radius_agent.py`** — Rearchitect
7. **`src/governance_agents/historical_agent.py`** — Rearchitect
8. **`src/governance_agents/financial_agent.py`** — Rearchitect
9. **Run tests** — all tests must still pass
10. **Add new LLM-specific tests** in `tests/test_governance_agents_llm.py`
11. **Run full suite** — `python -m pytest tests/ -x -q`
12. **Mandatory Doc Sync** — After all code changes are complete and tests pass, update these files:
    - **`README.md`** — update feature list to mention LLM-driven governance (not just deterministic)
    - **`CONTEXT.md`** — update governance agent descriptions, mention LLM-as-decision-maker architecture
    - **`STATUS.md`** — update current phase, test count, what changed
    - **`docs/ARCHITECTURE.md`** — update the governance agent table/section: LLM now adjusts scores, not just narrates; mention `_llm_governance.py` shared utilities; update the decision flow diagram if one exists
    - **`docs/SETUP.md`** — no change expected (same Azure OpenAI config), but verify
    - **`docs/API.md`** — no change expected (no new endpoints), but verify
    - **`learning/`** — create `learning/43-llm-governance-rearchitecture.md` documenting: what changed, the "LLM as narrator vs decision maker" pattern, guardrail clamping, structured output from LLMs, and the remediation-intent detection concept

---

## What NOT to Change

- **Mock mode behavior** — `_evaluate_rules()` methods are untouched; all existing tests pass
- **Deterministic scoring formulas** — they remain as the baseline; the LLM adjusts, not replaces
- **`result_holder` pattern** — keep the closure-based tool result capture
- **`run_with_throttle()`** — keep the existing rate limiting
- **Agent Framework setup** — keep the `DefaultAzureCredential`, `OpenAIResponsesClient`, `client.as_agent()` pattern
- **Score semantics** — 0-100 scale, same meaning, same thresholds in GovernanceDecisionEngine
- **Async patterns** — keep `asyncio.to_thread()` for sync SDK calls, keep async-first evaluate()

---

## Summary of Architecture Shift

| Aspect | Before | After |
|--------|--------|-------|
| LLM role | Narrator (writes summary) | Decision maker (adjusts scores) |
| Score source | 100% deterministic tool | Deterministic baseline + LLM adjustment |
| LLM sees policies | No | Yes (full policy JSON in prompt) |
| LLM sees ops agent intent | No | Yes (action.reason + context) |
| Remediation detection | Impossible | LLM reasons about intent vs. creation |
| Guardrails | None needed (LLM had no power) | +/-30 point clamp from baseline |
| Mock mode | Deterministic only | Deterministic only (unchanged) |
| Fallback on LLM error | Return deterministic result | Return deterministic result (unchanged) |
| Critical violation handling | Auto-DENY always | Auto-DENY only if LLM agrees (sri_policy >= 40) |

---

## Phase 22B — Post-Testing Fixes

Testing identified 4 issues with the Phase 22 implementation. All are valid.
Fix them in this exact order, running tests after each step.

### Fix 1 (High): Violation list contradicts LLM-overridden score

**Problem:** When the LLM reduces `sri_policy` from 40 to 10, the `PolicyResult.violations`
list still contains the CRITICAL violation unchanged. The audit trail shows
"APPROVED" alongside "CRITICAL violation POL-DR-001 fully applies" — a semantic contradiction.

**Do NOT delete violations.** They were legitimately detected by the deterministic engine.
Instead, annotate them with the LLM's disposition.

**Step 1a: Add `llm_override` field to `PolicyViolation`**

File: `src/core/models.py` (around line 99)

```python
class PolicyViolation(BaseModel):
    """A governance policy violation detected by the Policy Agent."""
    policy_id: str
    name: str
    rule: str
    severity: PolicySeverity
    llm_override: str | None = None  # e.g. "Remediation intent — violation does not apply"
```

`llm_override` is `None` by default (mock mode, no LLM). When the LLM determines a violation
doesn't truly apply, this field explains why. The violation stays in the list for audit
purposes, but consumers know it was overridden.

**Step 1b: Update `parse_llm_decision` to return adjustments list**

File: `src/governance_agents/_llm_governance.py`

Change `parse_llm_decision` to return the raw adjustments list as a third element:

```python
def parse_llm_decision(
    decision_holder: list[dict],
    baseline: float,
) -> tuple[float, str, list[dict]]:
    """Parse the LLM's submitted decision, apply guardrails.

    Returns (clamped_score, adjustment_text, adjustments_list).
    Returns (baseline, "", []) if the LLM did not submit a decision.
    """
    if not decision_holder:
        return baseline, "", []

    decision = decision_holder[-1]
    adjusted = float(decision.get("adjusted_score", baseline))
    clamped = clamp_score(baseline, adjusted)
    adjustments = decision.get("adjustments", [])
    reasoning = decision.get("reasoning", "")

    if clamped != adjusted:
        logger.info(
            "LLM governance adjustment clamped: %.1f -> %.1f (baseline %.1f, max drift %d)",
            adjusted, clamped, baseline, MAX_ADJUSTMENT,
        )

    text = format_adjustment_text(baseline, clamped, adjustments, reasoning)
    return clamped, text, adjustments
```

**Step 1c: Annotate violations in PolicyComplianceAgent**

File: `src/governance_agents/policy_agent.py`

After calling `parse_llm_decision`, if the LLM reduced the score, annotate each violation
that has a matching adjustment:

```python
if result_holder:
    base = result_holder[-1]
    adjusted_score, adjustment_text, adjustments = parse_llm_decision(
        llm_decision_holder, base.sri_policy
    )

    # Annotate violations with LLM override reasons
    violations = base.violations
    if adjusted_score < base.sri_policy and adjustments:
        # Build a lookup: policy_id -> reason from adjustments
        override_reasons = {
            adj.get("policy_id"): adj.get("reason", "LLM override")
            for adj in adjustments
            if adj.get("policy_id")
        }
        # Also build a generic override reason if no policy_id-specific ones
        generic_reason = adjustments[0].get("reason", "LLM override") if adjustments else None

        annotated = []
        for v in violations:
            override = override_reasons.get(v.policy_id) or generic_reason
            annotated.append(PolicyViolation(
                policy_id=v.policy_id,
                name=v.name,
                rule=v.rule,
                severity=v.severity,
                llm_override=override,
            ))
        violations = annotated

    return PolicyResult(
        sri_policy=adjusted_score,
        violations=violations,
        total_policies_checked=base.total_policies_checked,
        policies_passed=base.policies_passed,
        reasoning=base.reasoning + adjustment_text,
    )
```

**Step 1d: Update ALL 4 agents' `parse_llm_decision` call sites**

The other 3 agents (blast_radius, historical, financial) also call `parse_llm_decision`.
Update them to accept the third return value. They don't have violations to annotate,
so just unpack and discard:

```python
adjusted_score, adjustment_text, _ = parse_llm_decision(
    llm_decision_holder, base.sri_infrastructure  # or sri_historical, sri_cost
)
```

**Step 1e: Update `_AGENT_INSTRUCTIONS` in policy_agent.py**

Add a note telling the LLM to include `policy_id` in its adjustments so we can match
overrides to specific violations:

Add this to the end of the "Adjustment rules" section in `_AGENT_INSTRUCTIONS`:
```
- When overriding a specific policy violation, include its policy_id in your adjustment
  (e.g. {"reason": "Remediation intent", "delta": -40, "policy_id": "POL-DR-001"})
```

**Step 1f: Update `governance_engine.py` critical-violation check**

The current check `if critical and policy.sri_policy >= 40` works but doesn't look at
`llm_override`. Make it more precise — only count violations that were NOT overridden:

```python
critical = [
    v for v in policy.violations
    if v.severity == PolicySeverity.CRITICAL and not v.llm_override
]
if critical:
    ids = ", ".join(v.policy_id for v in critical)
    return (
        SRIVerdict.DENIED,
        f"DENIED — critical policy violation(s) detected: {ids}. "
        "Critical violations block execution regardless of composite SRI score.",
    )
```

This replaces the `sri_policy >= 40` check with a cleaner semantic: "auto-DENY only if
there are critical violations the LLM did NOT override." Remove the `and policy.sri_policy >= 40`
condition — the `llm_override` field now carries that information directly.

**Step 1g: Update test**

Update `test_critical_violation_id_appears_in_reason` in `tests/test_governance_engine.py`.
It currently uses `sri_policy=40` to satisfy the threshold. Change it to use `llm_override=None`
(the default) — no LLM override means the violation stands:

```python
def test_critical_violation_id_appears_in_reason(self, engine):
    """The denying policy ID must be named in the reason string."""
    action = _make_action()
    blast = BlastRadiusResult(sri_infrastructure=0)
    policy_r = PolicyResult(
        sri_policy=40,
        violations=[_critical_violation("POL-DR-001")],  # llm_override=None by default
    )
    hist = HistoricalResult(sri_historical=0)
    fin = FinancialResult(sri_cost=0)
    verdict = engine.evaluate(action, blast, policy_r, hist, fin)
    assert "POL-DR-001" in verdict.reason
```

Add a NEW test for the override case:

```python
def test_critical_violation_with_llm_override_not_auto_denied(self, engine):
    """CRITICAL violation with llm_override set → NOT auto-DENIED."""
    action = _make_action()
    blast = BlastRadiusResult(sri_infrastructure=0)
    overridden = PolicyViolation(
        policy_id="POL-DR-001",
        name="DR Protection",
        rule="test",
        severity=PolicySeverity.CRITICAL,
        llm_override="Remediation intent — ops agent fixing the issue",
    )
    policy_r = PolicyResult(sri_policy=10, violations=[overridden])
    hist = HistoricalResult(sri_historical=0)
    fin = FinancialResult(sri_cost=0)
    verdict = engine.evaluate(action, blast, policy_r, hist, fin)
    # composite = 10×0.25 = 2.5 → APPROVED (not auto-DENIED)
    assert verdict.decision == SRIVerdict.APPROVED
```

**Run tests:** `python -m pytest tests/ -x -q`

---

### Fix 2 (Medium): Validate LLM output against Pydantic models

**Problem:** `GovernanceAdjustment` and `LLMGovernanceOutput` exist in `models.py` but are
never used for validation. The agents capture raw dicts and `parse_llm_decision` parses dicts
directly. The models are dead code.

**Step 2a: Use the models in `parse_llm_decision`**

File: `src/governance_agents/_llm_governance.py`

Import and validate:

```python
from src.core.models import GovernanceAdjustment, LLMGovernanceOutput


def parse_llm_decision(
    decision_holder: list[dict],
    baseline: float,
) -> tuple[float, str, list[dict]]:
    if not decision_holder:
        return baseline, "", []

    raw = decision_holder[-1]

    # Validate against the Pydantic schema — malformed LLM output falls back to baseline
    try:
        decision = LLMGovernanceOutput(
            adjusted_score=float(raw.get("adjusted_score", baseline)),
            adjustments=[
                GovernanceAdjustment(**adj) for adj in raw.get("adjustments", [])
                if isinstance(adj, dict) and "reason" in adj and "delta" in adj
            ],
            reasoning=str(raw.get("reasoning", "")),
            confidence=float(raw.get("confidence", 0.8)),
        )
    except Exception as exc:
        logger.warning("LLM decision failed validation: %s — using baseline %.1f", exc, baseline)
        return baseline, "", []

    clamped = clamp_score(baseline, decision.adjusted_score)
    adj_dicts = [a.model_dump() for a in decision.adjustments]

    if clamped != decision.adjusted_score:
        logger.info(
            "LLM governance adjustment clamped: %.1f -> %.1f (baseline %.1f, max drift %d)",
            decision.adjusted_score, clamped, baseline, MAX_ADJUSTMENT,
        )

    text = format_adjustment_text(baseline, clamped, adj_dicts, decision.reasoning)
    return clamped, text, adj_dicts
```

This means:
- Malformed adjustments (missing `reason` or `delta`) are silently filtered out
- Completely invalid output (wrong types) falls back to baseline
- The Pydantic models are now the actual validation boundary

**Step 2b: Add `policy_id` field to `GovernanceAdjustment` if not already present**

Check `src/core/models.py` — it already has `policy_id: Optional[str] = None`. Good.
No change needed here.

**Run tests:** `python -m pytest tests/ -x -q`

---

### Fix 3 (Medium): Add integration tests for the live agent path

**Problem:** No test mocks the full agent flow to verify that `submit_governance_decision`
is registered and that an adjusted score flows through to the result.

**Step 3a: Add integration tests**

File: `tests/test_llm_governance.py` — add a new test class:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

class TestAgentLivePathIntegration:
    """Mock the Agent Framework to verify the full live path: tool registration + score adjustment."""

    @pytest.fixture
    def mock_settings(self):
        """Settings that enable the framework path (use_local_mocks=False)."""
        s = MagicMock()
        s.use_local_mocks = False
        s.azure_openai_endpoint = "https://fake.openai.azure.com"
        s.azure_openai_deployment = "gpt-4.1"
        return s

    def test_policy_agent_registers_submit_tool_and_applies_adjustment(self, mock_settings):
        """PolicyComplianceAgent in live mode registers submit_governance_decision
        and returns the LLM-adjusted score."""
        from src.governance_agents.policy_agent import PolicyComplianceAgent

        agent = PolicyComplianceAgent(cfg=mock_settings)

        # Mock the entire framework path
        with patch("src.governance_agents.policy_agent.AsyncAzureOpenAI"), \
             patch("src.governance_agents.policy_agent.DefaultAzureCredential"), \
             patch("src.governance_agents.policy_agent.get_bearer_token_provider"), \
             patch("src.governance_agents.policy_agent.OpenAIResponsesClient") as mock_client_cls, \
             patch("src.governance_agents.policy_agent.run_with_throttle") as mock_throttle, \
             patch("src.governance_agents.policy_agent.af") as mock_af:

            # Track what tools get registered
            registered_tools = []
            mock_af.tool = lambda **kwargs: lambda fn: (registered_tools.append((kwargs["name"], fn)), fn)[1]

            # Make as_agent return a mock agent
            mock_agent = MagicMock()
            mock_client_cls.return_value.as_agent.return_value = mock_agent

            # When run_with_throttle is called, simulate:
            # 1. The LLM calling evaluate_policy_rules
            # 2. The LLM calling submit_governance_decision
            async def simulate_agent_run(run_fn, prompt):
                # Find the registered tools
                eval_tool = next(fn for name, fn in registered_tools if name == "evaluate_policy_rules")
                submit_tool = next(fn for name, fn in registered_tools if name == "submit_governance_decision")

                # Simulate tool calls
                await eval_tool(action_json=action.model_dump_json())
                await submit_tool(
                    adjusted_score=15.0,
                    adjustments_json='[{"reason": "Remediation intent", "delta": -25, "policy_id": "POL-DR-001"}]',
                    reasoning="Ops agent is fixing the issue, not creating it",
                    confidence=0.9,
                )

            mock_throttle.side_effect = simulate_agent_run

            # Build a test action
            action = _make_action()
            action.reason = "Found SSH port 22 open to 0.0.0.0/0, restricting to corporate IP"

            result = asyncio.run(agent.evaluate(action, resource_metadata={"tags": {}, "environment": "production"}))

            # Verify submit_governance_decision was registered
            tool_names = [name for name, fn in registered_tools]
            assert "evaluate_policy_rules" in tool_names
            assert "submit_governance_decision" in tool_names

            # Verify the adjusted score was applied (baseline for this action is deterministic,
            # LLM adjusted to 15.0, which should be within +/-30 of baseline)
            assert result.sri_policy != 40.0  # Not the raw deterministic score
            # The exact value depends on clamping, but it should be <= baseline
```

**Note:** This test is complex because it mocks the Agent Framework imports. If the imports
fail (because `agent_framework` isn't installed in the test environment), wrap the test class
with `@pytest.mark.skipif` or catch `ImportError` in the test setup. The key assertion is:
- Both tools are registered
- The adjusted score flows through to the result

If mocking the imports is too fragile, an alternative simpler test:

```python
def test_policy_agent_framework_path_calls_parse_llm_decision(self):
    """Verify that _evaluate_with_framework calls parse_llm_decision."""
    # This test verifies the wiring without mocking the full Agent Framework.
    # It patches _evaluate_with_framework to confirm the method exists and
    # the tool names are correct.
    from src.governance_agents.policy_agent import PolicyComplianceAgent
    import inspect

    source = inspect.getsource(PolicyComplianceAgent._evaluate_with_framework)
    assert "submit_governance_decision" in source
    assert "parse_llm_decision" in source
    assert "llm_decision_holder" in source
```

Choose the approach that works in your test environment. The simpler `inspect.getsource`
test is less valuable but guaranteed to work without `agent_framework` installed.

**Run tests:** `python -m pytest tests/ -x -q`

---

### Fix 4 (Low): Fix adjustment text when clamping occurs

**Problem:** If the LLM requests `-50` and clamping reduces the effective change to `-30`,
the adjustment text still shows `-50 pts` for the individual entry.

**Step 4a: Update `format_adjustment_text` to show clamping note**

File: `src/governance_agents/_llm_governance.py`

```python
def format_adjustment_text(
    baseline: float,
    clamped: float,
    adjustments: list[dict],
    llm_reasoning: str,
) -> str:
    """Format the LLM's decision into a human-readable reasoning block."""
    lines = [
        "\nLLM Governance Analysis (GPT-4.1):",
        llm_reasoning,
        f"\nBaseline score: {baseline:.1f} -> LLM-adjusted score: {clamped:.1f}",
    ]

    # Sum of requested deltas
    requested_total = sum(adj.get("delta", 0) for adj in adjustments)
    actual_delta = clamped - baseline
    for adj in adjustments:
        delta = adj.get("delta", 0)
        reason = adj.get("reason", "")
        lines.append(f"  - {reason}: {delta:+.0f} pts")

    # If clamping changed the effective total, note it
    if abs(requested_total) > 0 and abs(actual_delta - requested_total) > 0.01:
        lines.append(
            f"  (Guardrail applied: requested total {requested_total:+.0f} pts, "
            f"effective {actual_delta:+.0f} pts due to +/-{MAX_ADJUSTMENT} pt clamp)"
        )

    return "\n".join(lines)
```

**Step 4b: Add a test for the clamping note**

File: `tests/test_llm_governance.py`

```python
def test_clamping_note_when_adjustment_exceeds_max(self):
    """When clamping reduces the effective delta, a note is appended."""
    adjustments = [{"reason": "Extreme remediation", "delta": -50}]
    text = format_adjustment_text(50.0, 20.0, adjustments, "reasoning")
    assert "Guardrail applied" in text
    assert "requested total -50" in text
    assert "effective -30" in text

def test_no_clamping_note_when_within_range(self):
    """No guardrail note when the adjustment is within bounds."""
    adjustments = [{"reason": "Minor reduction", "delta": -10}]
    text = format_adjustment_text(50.0, 40.0, adjustments, "reasoning")
    assert "Guardrail" not in text
```

**Run tests:** `python -m pytest tests/ -x -q`

---

### Fix Implementation Order

1. **Fix 4** (Low) — smallest, no dependencies → `_llm_governance.py` format fix + tests
2. **Fix 2** (Medium) — validate with Pydantic models → `_llm_governance.py` parse rewrite
3. **Fix 1** (High) — violation annotation → `models.py`, `policy_agent.py`, `governance_engine.py`, all 4 agents, tests
4. **Fix 3** (Medium) — integration tests → `tests/test_llm_governance.py`
5. **Run full suite** — `python -m pytest tests/ -x -q` — all tests must pass
6. **Mandatory Doc Sync** — update `STATUS.md` (test count, Phase 22B), `learning/43-llm-governance-rearchitecture.md` (add the fixes)

### What These Fixes Achieve

| Finding | Before | After |
|---------|--------|-------|
| Violations contradict score | "APPROVED" + "CRITICAL violation fully applies" | "APPROVED" + "CRITICAL violation (LLM override: remediation intent)" |
| Models are dead code | `GovernanceAdjustment` / `LLMGovernanceOutput` unused | Used as validation boundary in `parse_llm_decision` |
| No live-path test | Only helper tests | Integration test verifies tool registration + score flow |
| Misleading adjustment text | Shows `-50 pts` when only `-30` took effect | Shows `-50 pts` + "(Guardrail: effective -30 pts)" |

---

## Phase 22C — Post-Testing Fixes (Round 2)

Three findings from the testing team. Fix 1 is High priority and a genuine security guardrail gap.

### Fix 1 (High): Generic override reason suppresses ALL critical violations

**Problem:** In `policy_agent.py:325-341`, when the LLM omits `policy_id` from its adjustments,
`override_by_id` is empty, and `generic_reason` (from `adj_list[0]["reason"]`) is applied to
*every* violation via the `or generic_reason` fallback:

```python
llm_override=override_by_id.get(v.policy_id) or generic_reason,
```

This means a single "Remediation intent detected" note with no `policy_id` overrides ALL critical
violations — even unrelated ones. The `GovernanceDecisionEngine` treats any violation with
`llm_override` set as non-blocking (`not v.llm_override`), so one generic note suppresses all
auto-DENY behavior.

**Example attack:** Two violations — POL-DR-001 (disaster recovery, truly remediated) and
POL-SEC-001 (unrelated security concern). LLM says `{"reason": "Remediation intent", "delta": -25}`
without `policy_id`. Both violations get `llm_override="Remediation intent"`, and both are skipped
by the governance engine's critical-violation check.

**Fix:** The generic reason fallback MUST NOT apply to CRITICAL-severity violations. A CRITICAL
violation can only be overridden with a policy_id-specific reason. This is defense-in-depth:
even if the LLM "forgets" to include `policy_id`, critical violations remain blocking.

**Step 1a: Extract violation annotation into a testable helper**

File: `src/governance_agents/_llm_governance.py` — add a new function:

```python
def annotate_violations(
    violations: list,
    adj_list: list[dict],
    baseline: float,
    adjusted_score: float,
) -> list:
    """Annotate violations with LLM override reasons from adjustments.

    CRITICAL-severity violations are ONLY overridden when the LLM provided a
    policy_id-specific adjustment targeting that exact violation. The generic
    fallback reason (from the first adjustment) only applies to non-CRITICAL
    violations. This is a guardrail: the LLM must explicitly name the critical
    policy it is overriding.

    Args:
        violations: List of PolicyViolation instances from deterministic evaluation.
        adj_list: Validated adjustment dicts from parse_llm_decision.
        baseline: The deterministic baseline score.
        adjusted_score: The clamped adjusted score.

    Returns:
        New list of PolicyViolation instances with llm_override set where applicable.
    """
    if adjusted_score >= baseline or not adj_list:
        return violations

    # Import here to avoid circular dependency
    from src.core.models import PolicyViolation, PolicySeverity

    override_by_id = {
        adj["policy_id"]: adj["reason"]
        for adj in adj_list
        if adj.get("policy_id")
    }
    generic_reason = adj_list[0].get("reason") if adj_list else None

    result = []
    for v in violations:
        specific = override_by_id.get(v.policy_id)
        if specific:
            # LLM explicitly targeted this violation by policy_id
            override = specific
        elif v.severity == PolicySeverity.CRITICAL:
            # CRITICAL violations require explicit policy_id to override.
            # Generic reason is NOT sufficient — this is a safety guardrail.
            override = None
        else:
            # Non-critical: allow generic reason as override
            override = generic_reason
        result.append(PolicyViolation(
            policy_id=v.policy_id,
            name=v.name,
            rule=v.rule,
            severity=v.severity,
            llm_override=override,
        ))
    return result
```

**Step 1b: Update policy_agent.py to use the helper**

File: `src/governance_agents/policy_agent.py` — replace the inline annotation block (lines 320-341):

Replace:
```python
            # Annotate violations where the LLM determined the violation doesn't
            # truly apply (e.g. ops agent is remediating, not creating the issue).
            # Violations are never removed — they stay in the audit trail — but
            # llm_override marks why the score was reduced despite the violation.
            violations = base.violations
            if adjusted_score < base.sri_policy and adj_list:
                override_by_id = {
                    adj["policy_id"]: adj["reason"]
                    for adj in adj_list
                    if adj.get("policy_id")
                }
                generic_reason = adj_list[0].get("reason") if adj_list else None
                violations = [
                    PolicyViolation(
                        policy_id=v.policy_id,
                        name=v.name,
                        rule=v.rule,
                        severity=v.severity,
                        llm_override=override_by_id.get(v.policy_id) or generic_reason,
                    )
                    for v in base.violations
                ]
```

With:
```python
            # Annotate violations with LLM override reasons.
            # CRITICAL violations require explicit policy_id targeting — generic
            # reasons only apply to non-CRITICAL violations (safety guardrail).
            violations = annotate_violations(
                base.violations, adj_list, base.sri_policy, adjusted_score
            )
```

Also add the import at the top of `_evaluate_with_framework`, near the existing `parse_llm_decision` import:
```python
        from src.governance_agents._llm_governance import parse_llm_decision, annotate_violations
```

Note: this import is already inside `_evaluate_with_framework` (lazy import pattern). Just add
`annotate_violations` to the existing import statement. The import currently reads:
```python
        from src.governance_agents._llm_governance import parse_llm_decision
```
Change it to:
```python
        from src.governance_agents._llm_governance import parse_llm_decision, annotate_violations
```

Also **remove** the `PolicyViolation` import that was used in the inline block — it was imported
for the inline list comprehension. After extracting to `annotate_violations`, the import is no
longer needed at that call site (it's handled inside the helper). Check whether `PolicyViolation`
is imported elsewhere in the file; if the only usage was the inline annotation, remove it.

**Step 1c: Add tests**

File: `tests/test_llm_governance.py` — add a new test class and update imports:

Add `annotate_violations` to the existing import from `_llm_governance`:
```python
from src.governance_agents._llm_governance import (
    MAX_ADJUSTMENT,
    annotate_violations,
    clamp_score,
    format_adjustment_text,
    parse_llm_decision,
)
```

New test class:
```python
# ---------------------------------------------------------------------------
# annotate_violations — CRITICAL override guardrail
# ---------------------------------------------------------------------------

class TestAnnotateViolations:
    """Verify the safety guardrail: CRITICAL violations require policy_id-specific override."""

    def test_no_adjustment_returns_unchanged(self):
        """When score is not reduced, violations are returned as-is."""
        violations = [_critical_violation("POL-DR-001")]
        result = annotate_violations(violations, [], baseline=40.0, adjusted_score=40.0)
        assert result[0].llm_override is None

    def test_specific_policy_id_overrides_critical(self):
        """CRITICAL violation IS overridden when LLM provides matching policy_id."""
        violations = [_critical_violation("POL-DR-001")]
        adj_list = [{"reason": "Remediation intent", "delta": -25, "policy_id": "POL-DR-001"}]
        result = annotate_violations(violations, adj_list, baseline=40.0, adjusted_score=15.0)
        assert result[0].llm_override == "Remediation intent"

    def test_generic_reason_does_NOT_override_critical(self):
        """CRITICAL violation is NOT overridden when LLM omits policy_id (generic reason)."""
        violations = [_critical_violation("POL-DR-001")]
        adj_list = [{"reason": "Remediation intent", "delta": -25}]  # no policy_id
        result = annotate_violations(violations, adj_list, baseline=40.0, adjusted_score=15.0)
        assert result[0].llm_override is None  # CRITICAL stays blocking

    def test_generic_reason_overrides_non_critical(self):
        """Non-CRITICAL violations CAN be overridden with generic reason."""
        v = PolicyViolation(
            policy_id="POL-CHG-001", name="Change Window", rule="Test",
            severity=PolicySeverity.MEDIUM,
        )
        adj_list = [{"reason": "After-hours justified", "delta": -10}]
        result = annotate_violations([v], adj_list, baseline=30.0, adjusted_score=20.0)
        assert result[0].llm_override == "After-hours justified"

    def test_mixed_violations_only_targeted_critical_overridden(self):
        """Two CRITICAL violations: one targeted by policy_id, one not."""
        v1 = _critical_violation("POL-DR-001")   # Will be targeted
        v2 = _critical_violation("POL-SEC-001")   # NOT targeted
        adj_list = [{"reason": "DR test procedure", "delta": -25, "policy_id": "POL-DR-001"}]
        result = annotate_violations([v1, v2], adj_list, baseline=80.0, adjusted_score=55.0)
        assert result[0].llm_override == "DR test procedure"   # targeted → overridden
        assert result[1].llm_override is None                  # untargeted → stays blocking

    def test_mixed_severity_generic_skips_critical_overrides_medium(self):
        """Generic reason overrides MEDIUM but not CRITICAL."""
        v_crit = _critical_violation("POL-DR-001")
        v_med = PolicyViolation(
            policy_id="POL-CHG-001", name="Change Window", rule="Test",
            severity=PolicySeverity.MEDIUM,
        )
        adj_list = [{"reason": "Remediation intent", "delta": -20}]  # no policy_id
        result = annotate_violations([v_crit, v_med], adj_list, baseline=55.0, adjusted_score=35.0)
        assert result[0].llm_override is None                    # CRITICAL: not overridden
        assert result[1].llm_override == "Remediation intent"    # MEDIUM: overridden

    def test_empty_adj_list_returns_unchanged(self):
        """Empty adj_list means no LLM decision — violations unchanged."""
        violations = [_critical_violation("POL-DR-001")]
        result = annotate_violations(violations, [], baseline=40.0, adjusted_score=15.0)
        assert result[0].llm_override is None

    def test_score_increase_returns_unchanged(self):
        """When LLM INCREASES the score, no overrides are applied."""
        violations = [_critical_violation("POL-DR-001")]
        adj_list = [{"reason": "Higher risk", "delta": 10, "policy_id": "POL-DR-001"}]
        result = annotate_violations(violations, adj_list, baseline=40.0, adjusted_score=50.0)
        assert result[0].llm_override is None
```

**Run tests:** `python -m pytest tests/ -x -q`

---

### Fix 2 (Medium): Behavioral integration test for the live path

**Problem:** The `inspect.getsource` tests (Phase 22B Fix 3) verify wiring via string matching
but cannot catch behavioral bugs — e.g., if `parse_llm_decision` result is assigned to the wrong
variable or `annotate_violations` is called with wrong arguments.

**Approach:** Now that the violation annotation logic is extracted into `annotate_violations`
(Fix 1 above), we can test the behavioral contract without mocking the Agent Framework:

1. Test `annotate_violations` directly (already done in Fix 1 tests above).
2. Add one behavioral test that proves the policy agent's `_evaluate_with_framework` method
   calls `annotate_violations` (via `inspect.getsource`), and that the helper is the same
   function tested in `TestAnnotateViolations`.

File: `tests/test_llm_governance.py` — add to `TestAgentLivePathIntegration`:

```python
    def test_policy_agent_uses_annotate_violations_helper(self):
        """Policy agent delegates violation annotation to annotate_violations helper."""
        import inspect
        from src.governance_agents.policy_agent import PolicyComplianceAgent

        source = inspect.getsource(PolicyComplianceAgent._evaluate_with_framework)
        assert "annotate_violations" in source
        # Confirm inline annotation logic was removed
        assert "override_by_id" not in source
        assert "generic_reason" not in source

    def test_annotate_violations_is_same_function_as_tested(self):
        """The annotate_violations imported by policy_agent is the one we test."""
        from src.governance_agents._llm_governance import annotate_violations as tested_fn
        # Verify the function is callable and has the expected signature
        import inspect
        sig = inspect.signature(tested_fn)
        params = list(sig.parameters.keys())
        assert "violations" in params
        assert "adj_list" in params
        assert "baseline" in params
        assert "adjusted_score" in params
```

**Run tests:** `python -m pytest tests/ -x -q`

---

### Fix 3 (Low): Update stale module and class docstrings

**Problem:** The policy agent's module docstring (line 11-13) still says the LLM "synthesises a
plain-English compliance summary," and the class docstring (line 139-140) says "synthesise a
compliance narrative." Both describe the old narrator pattern.

**Step 3a: Update module docstring**

File: `src/governance_agents/policy_agent.py`

Replace lines 11-13:
```python
The LLM agent calls our deterministic ``evaluate_policy_rules`` tool,
which checks all governance policies and returns structured violation
data.  The LLM synthesises a plain-English compliance summary.
```

With:
```python
The LLM agent calls our deterministic ``evaluate_policy_rules`` tool,
which checks all governance policies and returns structured violation
data.  The LLM then acts as a decision-maker: it evaluates the context
(ops agent intent, remediation vs. creation) and calls
``submit_governance_decision`` with an adjusted score and justification.
The adjusted score is guardrail-clamped to +/-30 pts of the baseline.
```

**Step 3b: Update class docstring**

File: `src/governance_agents/policy_agent.py`

Replace lines 139-140:
```python
    In live mode the Microsoft Agent Framework drives GPT-4.1 to call the
    deterministic tool and synthesise a compliance narrative.
```

With:
```python
    In live mode the Microsoft Agent Framework drives GPT-4.1 to call the
    deterministic tool, evaluate context (remediation intent, policy applicability),
    and submit an adjusted score via ``submit_governance_decision``.
```

**Run tests:** `python -m pytest tests/ -x -q` (docstring changes should not break any tests)

---

### Fix Implementation Order

1. **Fix 1** (High) — extract `annotate_violations`, CRITICAL guardrail → `_llm_governance.py`, `policy_agent.py`, tests
2. **Fix 2** (Medium) — behavioral wiring tests → `tests/test_llm_governance.py`
3. **Fix 3** (Low) — docstring updates → `policy_agent.py`
4. **Run full suite** — `python -m pytest tests/ -x -q` — all tests must pass
5. **Mandatory Doc Sync** — update `STATUS.md` (test count), `learning/43-llm-governance-rearchitecture.md` (add Phase 22C)

### What These Fixes Achieve

| Finding | Before | After |
|---------|--------|-------|
| Generic override suppresses all CRITICAL | One "remediation intent" note overrides all violations | CRITICAL violations require explicit policy_id targeting |
| No behavioral live-path test | String matching only | `annotate_violations` tested behaviorally + wiring verified |
| Stale docstrings | "synthesises a compliance summary" | "evaluates context and submits adjusted score" |

---

## Phase 22D — Mocked End-to-End Live-Path Test

One finding from the testing team. Finding 2 (Low) was acknowledged as an intentional design
choice, not a bug — the CRITICAL `policy_id` requirement is a deliberate safety guardrail.

### Fix 1 (Medium): Mocked behavioral test for the full live path

**Problem:** All existing live-path tests use `inspect.getsource` (string matching) or test
extracted helpers in isolation. No test proves the actual runtime flow:
`_evaluate_with_framework()` → tool calls → `parse_llm_decision` → `annotate_violations` →
`PolicyResult` with adjusted score and overridden violations.

**Approach:** Mock the Agent Framework module (which may not be installed in test env) and
`run_with_throttle`. The mock `run_with_throttle` simulates the LLM by calling the captured
tool functions directly, filling `result_holder` and `llm_decision_holder`. The rest of the
function runs for real: `parse_llm_decision`, `annotate_violations`, `PolicyResult` construction.

This tests the complete data flow from LLM submission through to the returned result, without
needing `agent_framework` installed or any real Azure/OpenAI connections.

**Step 1a: Add the test**

File: `tests/test_llm_governance.py` — add a new test class. Place it after `TestAnnotateViolations`
and before `TestAgentLivePathIntegration`.

Add these imports at the top of the file (alongside the existing ones):
```python
import asyncio
import json
import sys
from unittest.mock import MagicMock, patch
```

New test class:
```python
# ---------------------------------------------------------------------------
# Mocked end-to-end live-path behavioral test
# ---------------------------------------------------------------------------

class TestPolicyAgentLivePathBehavior:
    """Mocked end-to-end test of PolicyComplianceAgent._evaluate_with_framework.

    Mocks agent_framework (may not be installed) and run_with_throttle (skips
    real LLM call). The mock simulates the LLM calling both tools, then asserts
    that the returned PolicyResult has the adjusted score, annotated violations,
    and LLM reasoning text.
    """

    def test_live_path_returns_adjusted_score_and_annotated_violations(self):
        """Full runtime flow: tool calls → parse → annotate → PolicyResult."""
        from src.governance_agents.policy_agent import PolicyComplianceAgent

        # --- Mock agent_framework (may not be installed) ---
        captured_tools = {}

        def mock_tool(**kwargs):
            def decorator(fn):
                captured_tools[kwargs["name"]] = fn
                return fn
            return decorator

        mock_af = MagicMock()
        mock_af.tool = mock_tool
        mock_af_openai = MagicMock()

        # --- Settings for live mode ---
        mock_settings = MagicMock()
        mock_settings.use_local_mocks = False
        mock_settings.azure_openai_endpoint = "https://fake.openai.azure.com"
        mock_settings.azure_openai_deployment = "gpt-4.1"

        agent = PolicyComplianceAgent(cfg=mock_settings)
        action = _make_action()
        action.reason = "Found SSH port 22 open to 0.0.0.0/0, restricting to corporate range"
        metadata = {"tags": {}, "environment": "production"}

        # Get deterministic baseline so we can set a valid adjusted score
        baseline = agent._evaluate_rules(action, metadata)
        target = max(0.0, baseline.sri_policy - 20.0)

        # Find a critical violation to target (if any)
        crit = next(
            (v for v in baseline.violations if v.severity == PolicySeverity.CRITICAL),
            None,
        )

        adjustments = []
        if crit:
            adjustments.append({
                "reason": "Remediation intent — ops agent fixing open SSH",
                "delta": target - baseline.sri_policy,
                "policy_id": crit.policy_id,
            })
        else:
            adjustments.append({
                "reason": "Remediation intent",
                "delta": target - baseline.sri_policy,
            })

        async def mock_run(run_fn, prompt):
            await captured_tools["evaluate_policy_rules"](
                action_json=action.model_dump_json()
            )
            await captured_tools["submit_governance_decision"](
                adjusted_score=target,
                adjustments_json=json.dumps(adjustments),
                reasoning="Ops agent is remediating open SSH, not creating the issue",
                confidence=0.9,
            )

        with patch.dict(sys.modules, {
            "agent_framework": mock_af,
            "agent_framework.openai": mock_af_openai,
        }), patch(
            "src.infrastructure.llm_throttle.run_with_throttle",
            side_effect=mock_run,
        ):
            result = asyncio.run(
                agent.evaluate(action, resource_metadata=metadata)
            )

        # --- Assertions ---

        # 1. Score was adjusted, not the raw baseline
        assert result.sri_policy == target
        assert result.sri_policy < baseline.sri_policy

        # 2. Targeted critical violation has llm_override set
        if crit:
            matched = [v for v in result.violations if v.policy_id == crit.policy_id]
            assert len(matched) == 1
            assert matched[0].llm_override == "Remediation intent — ops agent fixing open SSH"

        # 3. Reasoning includes LLM analysis text from format_adjustment_text
        assert "LLM Governance Analysis" in result.reasoning

        # 4. Violation count unchanged (violations annotated, never removed)
        assert len(result.violations) == len(baseline.violations)

    def test_live_path_no_submission_falls_back_to_baseline(self):
        """If the LLM never calls submit_governance_decision, baseline is returned."""
        from src.governance_agents.policy_agent import PolicyComplianceAgent

        captured_tools = {}

        def mock_tool(**kwargs):
            def decorator(fn):
                captured_tools[kwargs["name"]] = fn
                return fn
            return decorator

        mock_af = MagicMock()
        mock_af.tool = mock_tool
        mock_af_openai = MagicMock()

        mock_settings = MagicMock()
        mock_settings.use_local_mocks = False
        mock_settings.azure_openai_endpoint = "https://fake.openai.azure.com"
        mock_settings.azure_openai_deployment = "gpt-4.1"

        agent = PolicyComplianceAgent(cfg=mock_settings)
        action = _make_action()
        metadata = {"tags": {}, "environment": "production"}

        baseline = agent._evaluate_rules(action, metadata)

        async def mock_run(run_fn, prompt):
            # LLM calls evaluate but never submits a decision
            await captured_tools["evaluate_policy_rules"](
                action_json=action.model_dump_json()
            )

        with patch.dict(sys.modules, {
            "agent_framework": mock_af,
            "agent_framework.openai": mock_af_openai,
        }), patch(
            "src.infrastructure.llm_throttle.run_with_throttle",
            side_effect=mock_run,
        ):
            result = asyncio.run(
                agent.evaluate(action, resource_metadata=metadata)
            )

        # Without LLM submission, score should be the deterministic baseline
        assert result.sri_policy == baseline.sri_policy
        # No violations should have llm_override
        for v in result.violations:
            assert v.llm_override is None

    def test_live_path_generic_reason_does_not_override_critical(self):
        """Generic adjustment (no policy_id) does NOT override CRITICAL violations."""
        from src.governance_agents.policy_agent import PolicyComplianceAgent

        captured_tools = {}

        def mock_tool(**kwargs):
            def decorator(fn):
                captured_tools[kwargs["name"]] = fn
                return fn
            return decorator

        mock_af = MagicMock()
        mock_af.tool = mock_tool
        mock_af_openai = MagicMock()

        mock_settings = MagicMock()
        mock_settings.use_local_mocks = False
        mock_settings.azure_openai_endpoint = "https://fake.openai.azure.com"
        mock_settings.azure_openai_deployment = "gpt-4.1"

        agent = PolicyComplianceAgent(cfg=mock_settings)
        action = _make_action()
        action.reason = "Found SSH port 22 open to 0.0.0.0/0, restricting source"
        metadata = {"tags": {}, "environment": "production"}

        baseline = agent._evaluate_rules(action, metadata)
        target = max(0.0, baseline.sri_policy - 20.0)

        # Adjustment with NO policy_id — generic reason only
        adjustments = [{"reason": "Remediation intent", "delta": target - baseline.sri_policy}]

        async def mock_run(run_fn, prompt):
            await captured_tools["evaluate_policy_rules"](
                action_json=action.model_dump_json()
            )
            await captured_tools["submit_governance_decision"](
                adjusted_score=target,
                adjustments_json=json.dumps(adjustments),
                reasoning="Generic remediation note",
                confidence=0.9,
            )

        with patch.dict(sys.modules, {
            "agent_framework": mock_af,
            "agent_framework.openai": mock_af_openai,
        }), patch(
            "src.infrastructure.llm_throttle.run_with_throttle",
            side_effect=mock_run,
        ):
            result = asyncio.run(
                agent.evaluate(action, resource_metadata=metadata)
            )

        # Score IS adjusted (generic reason is allowed for score adjustment)
        assert result.sri_policy == target

        # But CRITICAL violations must NOT be overridden (safety guardrail)
        for v in result.violations:
            if v.severity == PolicySeverity.CRITICAL:
                assert v.llm_override is None, (
                    f"CRITICAL violation {v.policy_id} should NOT be overridden by generic reason"
                )
```

**Run tests:** `python -m pytest tests/ -x -q`

---

### Fix Implementation Order

1. **Fix 1** (Medium) — mocked end-to-end live path test → `tests/test_llm_governance.py`
2. **Run full suite** — `python -m pytest tests/ -x -q` — all tests must pass
3. **Mandatory Doc Sync** — update `STATUS.md` (test count), `learning/43-llm-governance-rearchitecture.md` (add Phase 22D)

### What This Fix Achieves

| Finding | Before | After |
|---------|--------|-------|
| No mocked end-to-end live-path test | Helper tests + source inspection only | 3 behavioral tests prove: adjusted score flows through, violations annotated correctly, CRITICAL guardrail holds, LLM-no-submit falls back to baseline |

---

## Phase 22E — Restore Dangerous-Port Detection with Structured Intent

### Context

Two critical/high findings from the testing team expose a regression:

1. **Critical:** `POL-SEC-002` and `POL-SEC-003` were deleted (commit `ced7977`) because their
   `reason_pattern` regex matched the agent's *description* of a problem rather than its *intent*
   to fix it. The deletion fixed the immediate blockage but removed all dangerous-port detection.
   Evaluating `modify_nsg` with reason "Opening SSH port 22 to 0.0.0.0/0 for emergency admin
   access" now returns only `POL-SEC-001` (HIGH) — no CRITICAL violation.

2. **High:** The live-path behavioral test in `TestPolicyAgentLivePathBehavior` branches on
   `if crit:` because there is no guaranteed CRITICAL violation without POL-SEC-002. The test
   passes but doesn't prove the remediation scenario it was written for.

### Root cause

Intent (open vs restrict) is buried in free-form `reason` text. The `reason_pattern` regex
couldn't tell "Found SSH open, restricting source" from "Opening SSH to 0.0.0.0/0". Deleting
the policy was the wrong fix — the right fix is a structured field.

### Architecture goal (restated from the top of this document)

The LLM should distinguish **fixing** the issue from **creating** it. POL-SEC-002 should detect
the dangerous condition; the LLM decides whether the action is remediation or creation. Deleting
POL-SEC-002 bypasses the hard part by removing the detection entirely.

---

### Fix 1 (Critical): Add `nsg_change_direction` to ProposedAction

**Step 1a: Update `src/core/models.py`**

Add one field to `ProposedAction`:

```python
class ProposedAction(BaseModel):
    agent_id: str
    action_type: ActionType
    target: ActionTarget
    reason: str
    urgency: Urgency = Urgency.LOW
    projected_savings_monthly: Optional[float] = None
    nsg_change_direction: Optional[str] = None  # "open" | "restrict" — set by NSG agents
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

No `Literal` typing — keep it as `Optional[str]` to avoid import overhead and allow future
values ("update", "delete-rule", etc.). The policy condition just string-compares.

**Step 1b: Add condition handler to `src/governance_agents/policy_agent.py`**

In `_check_policy`, after the `reason_pattern` block (around line 430), add:

```python
        # -- NSG change direction ----------------------------------------
        # Fires only when the agent explicitly declared the change opens access.
        # If nsg_change_direction is None or "restrict", this condition is False
        # and the policy does NOT fire — remediation proposals are not blocked.
        if "nsg_change_direction" in conditions:
            checks.append(
                getattr(action, "nsg_change_direction", None) == conditions["nsg_change_direction"]
            )
```

Also update the module-level docstring condition list (around line 40):
```
* nsg_change_direction — action.nsg_change_direction equals the required value ("open" | "restrict")
```

**Step 1c: Restore POL-SEC-002 in `data/policies.json`**

Add back between POL-SEC-001 and POL-CHG-001:

```json
  {
    "id": "POL-SEC-002",
    "name": "Internet-Exposed Dangerous Ports",
    "description": "NSG modifications that OPEN SSH (22), RDP (3389), WinRM (5985/5986), Telnet (23), or FTP (21) to unrestricted sources are prohibited (CIS Azure 6.1/6.2). This policy only fires when the proposing agent explicitly declares nsg_change_direction='open'. Remediation proposals (direction='restrict') are never blocked by this rule.",
    "severity": "critical",
    "conditions": {
      "blocked_actions": ["modify_nsg"],
      "nsg_change_direction": "open"
    },
    "override_requires": "security_team_review",
    "category": "security"
  },
```

**Step 1d: Update `src/operational_agents/deploy_agent.py`**

The deploy agent always detects bad security state and proposes to *restrict* it. Add
`nsg_change_direction="restrict"` to every `ProposedAction` it builds for `modify_nsg`.

There are two places — the live `propose_action` tool callback (around line 373) and the
`_demo_proposals` method (around line 430).

Replace the live callback's `ProposedAction(...)` construction:
```python
            proposal = ProposedAction(
                agent_id=_AGENT_ID,
                action_type=action_type_enum,
                target=ActionTarget(
                    resource_id=resource_id,
                    resource_type=resource_type or _NSG_RESOURCE_TYPE,
                    resource_group=resource_group or None,
                ),
                reason=reason,
                urgency=urgency_enum,
                nsg_change_direction="restrict" if action_type_enum == ActionType.MODIFY_NSG else None,
            )
```

Replace the first `_demo_proposals` entry (the MODIFY_NSG one) similarly:
```python
            ProposedAction(
                agent_id=_AGENT_ID,
                action_type=ActionType.MODIFY_NSG,
                target=ActionTarget(
                    resource_id="nsg-demo-prod",
                    resource_type="Microsoft.Network/networkSecurityGroups",
                ),
                reason=(
                    "[DEMO] Port 22 (SSH) open to 0.0.0.0/0 on nsg-demo-prod. "
                    "No deny-all inbound rule at priority 4096. "
                    "Recommend adding deny-all rule to reduce attack surface."
                ),
                urgency=Urgency.HIGH,
                nsg_change_direction="restrict",
            ),
```

**Step 1e: Add paired tests to `tests/test_policy_compliance.py`**

Add a new test class (or add to an existing NSG test class):

```python
class TestNsgChangeDirectionPolicy:
    """POL-SEC-002 fires only when nsg_change_direction='open'."""

    def _nsg_action(self, direction: str | None, reason: str = "NSG change") -> ProposedAction:
        return ProposedAction(
            agent_id="test",
            action_type=ActionType.MODIFY_NSG,
            target=ActionTarget(
                resource_id="/subscriptions/x/resourceGroups/rg/providers/"
                            "Microsoft.Network/networkSecurityGroups/nsg-1",
                resource_type="Microsoft.Network/networkSecurityGroups",
            ),
            reason=reason,
            urgency=Urgency.HIGH,
            nsg_change_direction=direction,
        )

    def test_open_direction_triggers_critical_pol_sec_002(self, agent):
        """OPENING dangerous ports → POL-SEC-002 CRITICAL fires."""
        action = self._nsg_action("open", "Opening SSH port 22 to 0.0.0.0/0 for emergency access")
        result = agent.evaluate(action, resource_metadata={"tags": {}, "environment": "production"})
        ids = [v.policy_id for v in result.violations]
        assert "POL-SEC-002" in ids
        crit = [v for v in result.violations if v.policy_id == "POL-SEC-002"]
        assert crit[0].severity == PolicySeverity.CRITICAL

    def test_restrict_direction_does_not_trigger_pol_sec_002(self, agent):
        """RESTRICTING dangerous ports (remediation) → POL-SEC-002 does NOT fire."""
        action = self._nsg_action("restrict", "Found SSH open to 0.0.0.0/0, restricting to corporate range")
        result = agent.evaluate(action, resource_metadata={"tags": {}, "environment": "production"})
        ids = [v.policy_id for v in result.violations]
        assert "POL-SEC-002" not in ids

    def test_no_direction_does_not_trigger_pol_sec_002(self, agent):
        """direction=None (unspecified) → POL-SEC-002 does NOT fire (safe default)."""
        action = self._nsg_action(None, "Modifying NSG rule")
        result = agent.evaluate(action, resource_metadata={"tags": {}, "environment": "production"})
        ids = [v.policy_id for v in result.violations]
        assert "POL-SEC-002" not in ids

    def test_paired_sri_scores_differ(self, agent):
        """Opening SSH scores higher (more risk) than restricting SSH."""
        open_action = self._nsg_action("open", "Opening SSH port 22 to 0.0.0.0/0")
        restrict_action = self._nsg_action("restrict", "Restricting SSH port 22 from 0.0.0.0/0")
        open_result = agent.evaluate(open_action, resource_metadata={"tags": {}, "environment": "production"})
        restrict_result = agent.evaluate(restrict_action, resource_metadata={"tags": {}, "environment": "production"})
        assert open_result.sri_policy > restrict_result.sri_policy
```

Note: these tests need a `agent` fixture (the `PolicyComplianceAgent` instance). Check the
existing `test_policy_compliance.py` fixture name (likely `agent` or `policy_agent`) and use
the same name.

---

### Fix 2 (High): Remove `if crit:` branch from live-path behavioral test

**Step 2a: Update `tests/test_llm_governance.py`**

In `TestPolicyAgentLivePathBehavior.test_live_path_returns_adjusted_score_and_annotated_violations`,
replace the action and remove the conditional:

Replace the action setup:
```python
        action = _make_action()
        action.reason = "Found SSH port 22 open to 0.0.0.0/0, restricting to corporate range"
```

With:
```python
        action = _make_action()
        action.reason = "Opening SSH port 22 to 0.0.0.0/0 for emergency admin access"
        action.nsg_change_direction = "open"   # guarantees POL-SEC-002 CRITICAL fires
```

Replace the crit-finding block and the conditional assertion:
```python
        # Get deterministic baseline so we can set a valid adjusted score
        baseline = agent._evaluate_rules(action, metadata)
        target = max(0.0, baseline.sri_policy - 20.0)

        # Find a critical violation to target (if any)
        crit = next(
            (v for v in baseline.violations if v.severity == PolicySeverity.CRITICAL),
            None,
        )

        adjustments = []
        if crit:
            adjustments.append({
                "reason": "Remediation intent — ops agent fixing open SSH",
                "delta": target - baseline.sri_policy,
                "policy_id": crit.policy_id,
            })
        else:
            adjustments.append({
                "reason": "Remediation intent",
                "delta": target - baseline.sri_policy,
            })
```

With:
```python
        # Get deterministic baseline — POL-SEC-002 CRITICAL is guaranteed by direction="open"
        baseline = agent._evaluate_rules(action, metadata)
        target = max(0.0, baseline.sri_policy - 20.0)

        crit = next(v for v in baseline.violations if v.severity == PolicySeverity.CRITICAL)
        adjustments = [{
            "reason": "Ops agent is remediating open SSH, not creating the exposure",
            "delta": target - baseline.sri_policy,
            "policy_id": crit.policy_id,
        }]
```

And replace the conditional assertion at the bottom:
```python
        if crit:
            matched = [v for v in result.violations if v.policy_id == crit.policy_id]
            assert len(matched) == 1
            assert matched[0].llm_override == "Remediation intent — ops agent fixing open SSH"
```

With the unconditional version:
```python
        matched = [v for v in result.violations if v.policy_id == crit.policy_id]
        assert len(matched) == 1
        assert matched[0].llm_override == "Ops agent is remediating open SSH, not creating the exposure"
```

Also update `test_live_path_generic_reason_does_not_override_critical` to use
`nsg_change_direction="open"` for the same reason — guarantees CRITICAL exists to test against:

```python
        action = _make_action()
        action.reason = "Found SSH port 22 open to 0.0.0.0/0, restricting source"
        action.nsg_change_direction = "open"   # forces CRITICAL so generic-reason guardrail is meaningful
```

---

### Fix Implementation Order

1. **Fix 1a** — add `nsg_change_direction` to `ProposedAction` in `models.py`
2. **Fix 1b** — add `nsg_change_direction` condition handler in `policy_agent.py`
3. **Fix 1c** — restore `POL-SEC-002` in `data/policies.json`
4. **Fix 1d** — update `deploy_agent.py` to set `nsg_change_direction="restrict"`
5. **Fix 1e** — add paired tests to `test_policy_compliance.py`
6. **Run tests:** `python -m pytest tests/ -x -q`
7. **Fix 2a** — update live-path behavioral test to use `nsg_change_direction="open"`, remove `if crit:`
8. **Run tests:** `python -m pytest tests/ -x -q`
9. **Mandatory Doc Sync** — `STATUS.md` (test count), `learning/43-llm-governance-rearchitecture.md`

### What These Fixes Achieve

| Finding | Before | After |
|---------|--------|-------|
| Dangerous-port detection deleted | "Opening SSH to *" returns only POL-SEC-001 (HIGH) | POL-SEC-002 (CRITICAL) fires when `nsg_change_direction="open"` |
| Remediation still allowed | ✓ (but only because policy was deleted) | ✓ because direction="restrict" skips POL-SEC-002 entirely |
| Live-path test has `if crit:` branch | Test passes even when CRITICAL never fires | `nsg_change_direction="open"` guarantees CRITICAL — unconditional assertions |
| Intent buried in reason text | `reason_pattern` regex matched description, not intent | Structured field: agent declares intent; policy reads fact, not prose |

---

## Phase 22F — MCP Server `nsg_change_direction` Passthrough + ADR

### Testing Team Findings

**Finding 1 (High):** `skry_evaluate_action` in `src/mcp_server/server.py` constructs `ProposedAction`
without `nsg_change_direction`. Any external agent (Claude Desktop, GitHub Copilot, etc.) that
calls `skry_evaluate_action(action_type="modify_nsg", ...)` will always get `nsg_change_direction=None`,
meaning POL-SEC-002 never fires regardless of what the agent is actually doing. An external agent
could describe opening SSH to `0.0.0.0/0` and receive only POL-SEC-001 (HIGH), not the intended
POL-SEC-002 (CRITICAL).

**Finding 2 (Medium):** Deploy agent sets `nsg_change_direction="restrict"` based on
`action_type == MODIFY_NSG` alone, without inspecting the proposed change content.

---

### Assessment

**Finding 1 — Valid.** The MCP server is the primary external API surface. The fix is small and
backward-compatible: add `nsg_change_direction: str | None = None` as an optional parameter to
`skry_evaluate_action`, then pass it to `ProposedAction`.

**Finding 2 — Intentional by design (Architecture Decision Record).**

The deploy agent's role is narrowly scoped: it scans for dangerous security misconfigurations and
proposes to *remediate* them. It never proposes to open ports. Setting `nsg_change_direction="restrict"`
unconditionally for all `MODIFY_NSG` proposals is correct because:

1. The deploy agent is the only governance-internal source of `modify_nsg` actions.
2. It only ever detects `allow-ssh-anywhere` style rules and proposes to restrict them.
3. There is no code path in `deploy_agent.py` that would open a port.

If a future ops agent ever proposes *opening* a port for a legitimate reason (e.g. a firewall-rule
provisioner), it must set `nsg_change_direction="open"` explicitly — that is the intended design.
The `None` default is safe because POL-SEC-001 (HIGH) still catches all `modify_nsg` actions for
human review regardless of direction.

This is documented here as an ADR so future contributors understand the invariant: **"restrict" is
always correct for the deploy agent; any agent that opens ports must declare "open".**

---

### Fix: Add `nsg_change_direction` to `skry_evaluate_action`

**File:** `src/mcp_server/server.py`

**Step 1 — Add parameter to function signature (after `proposed_sku`):**

```python
@mcp.tool()
async def skry_evaluate_action(
    resource_id: str,
    resource_type: str,
    action_type: str,
    agent_id: str,
    reason: str,
    urgency: str = "medium",
    current_monthly_cost: float | None = None,
    current_sku: str | None = None,
    proposed_sku: str | None = None,
    nsg_change_direction: str | None = None,
) -> dict:
```

**Step 2 — Add to docstring Args section (after `proposed_sku`):**

```
        nsg_change_direction: For ``modify_nsg`` actions only. ``"open"`` if
            the change adds or broadens inbound access (triggers CRITICAL
            dangerous-port check). ``"restrict"`` or ``None`` if the change
            restricts or remediates access (no CRITICAL trigger).
```

**Step 3 — Pass to `ProposedAction` constructor (add after `urgency` line):**

```python
        action = ProposedAction(
            agent_id=agent_id,
            action_type=ActionType(action_type),
            target=ActionTarget(
                resource_id=resource_id,
                resource_type=resource_type,
                current_monthly_cost=current_monthly_cost,
                current_sku=current_sku,
                proposed_sku=proposed_sku,
            ),
            reason=reason,
            urgency=Urgency(urgency),
            nsg_change_direction=nsg_change_direction,
        )
```

---

### Tests to Add

Add to `tests/test_mcp_server.py` (or create the file if it doesn't exist) in a new class
`TestSkryEvaluateActionNsgDirection`:

**Test 1 — `nsg_change_direction="open"` is passed through to `ProposedAction`:**
```python
async def test_open_direction_passed_to_pipeline(monkeypatch):
    captured = {}
    async def mock_evaluate(action):
        captured["action"] = action
        return _make_verdict(action)
    monkeypatch.setattr(_get_pipeline(), "evaluate", mock_evaluate)

    await skry_evaluate_action(
        resource_id="nsg-east",
        resource_type="Microsoft.Network/networkSecurityGroups",
        action_type="modify_nsg",
        agent_id="test-agent",
        reason="Opening SSH to 0.0.0.0/0",
        nsg_change_direction="open",
    )
    assert captured["action"].nsg_change_direction == "open"
```

**Test 2 — `nsg_change_direction=None` (omitted) is passed through as None:**
```python
async def test_no_direction_defaults_to_none(monkeypatch):
    # same as above but without nsg_change_direction kwarg
    assert captured["action"].nsg_change_direction is None
```

**Test 3 — `"restrict"` is passed through:**
```python
async def test_restrict_direction_passed_to_pipeline(monkeypatch):
    assert captured["action"].nsg_change_direction == "restrict"
```

If `tests/test_mcp_server.py` does not exist, create it with:
- Module-level mock fixture for `_pipeline` singleton (monkeypatch `src.mcp_server.server._pipeline`)
- The 3 tests above
- One existing sanity test that a basic `modify_nsg` call returns expected keys

---

### Implementation Order

1. Edit `src/mcp_server/server.py`: add parameter, docstring, pass to ProposedAction
2. Add/update `tests/test_mcp_server.py`: 3 direction passthrough tests
3. Run: `python -m pytest tests/ -x -q`
4. Update `docs/API.md`: add `nsg_change_direction` to the MCP tool parameter table
5. Update `STATUS.md` (test count), `learning/43-llm-governance-rearchitecture.md`

---

### What This Fix Achieves

| Finding | Before | After |
|---------|--------|-------|
| MCP external caller with `modify_nsg` + dangerous intent | POL-SEC-002 never fires (direction=None) | External agent can pass `direction="open"` → CRITICAL fires |
| Existing callers that omit `nsg_change_direction` | ✓ unchanged — None is safe default | ✓ unchanged — backward-compatible optional parameter |
| Deploy agent correctness | ✓ already sets "restrict" | ✓ unchanged — ADR documents this as intentional |
| Test coverage of MCP tool | Not tested | 3 direction passthrough tests |

---

### Sonnet Prompt

```
Read rearchitecture.md Phase 22F (the last section, starting at "## Phase 22F").

Follow ONLY the steps in that section. Do not change anything else.

Summary of changes:
1. src/mcp_server/server.py — add `nsg_change_direction: str | None = None` optional parameter,
   update docstring, pass to ProposedAction constructor
2. tests/test_mcp_server.py — check if file exists; if yes, add TestSkryEvaluateActionNsgDirection
   class with 3 tests; if no, create the file with those 3 tests + module setup
3. Run: python -m pytest tests/ -x -q — all tests must pass
4. Mandatory Doc Sync: docs/API.md (add nsg_change_direction to MCP tool docs),
   STATUS.md (update test count), learning/43-llm-governance-rearchitecture.md (append Phase 22F section)

After completing all steps, confirm: "Phase 22F complete — N tests passing."
```

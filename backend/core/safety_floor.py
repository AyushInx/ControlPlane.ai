"""
safety_floor.py — Safety Floor (§12)

Narrow, policy-defined override for CRITICAL severity + high-confidence
signals in explicitly configured safety-floor categories.

BINDING:
  - Narrow, explicitly configured — NOT a blanket rule for any PII or any unsafe-content flag.
  - Most PII detections are NOT safety-floor cases — they follow normal profile-driven policy.
  - Safety floor confidence threshold is POLICY-CONFIGURABLE (from plan.safety_floor_confidence_threshold).
  - The policy rule is deterministic once threshold is crossed.
  - Underlying classifiers remain probabilistic.
  - Safety floor checks FIRST in Decision Engine (Rule 1) and is not subject to profile-specific softening.

FIX NOTE (this revision) — see ANALYSIS_AND_FIXES.md:
  Category membership used to be inferred by substring-matching each
  signal's free-text `reason` field — including a literal check for
  "credential_exposure" (with an underscore) that pii_evaluator never
  actually produced (its prose said "credential exposure", with a space),
  so that check path was dead. Separately, the safety-evaluator branch
  matched on a generic "safety-floor category" phrase that several
  different categories all happened to share in their prose, which quietly
  made "explicit_violence" and "profanity_slurs" ride along as
  floor-eligible any time "prohibited_unsafe_content" was configured —
  not because policy said so, but because of how the sentence was worded.

  This is now a direct, exact-match check against RiskSignal.risk_category,
  which every evaluator sets explicitly. A category is floor-eligible if
  and only if it's listed in plan.safety_floor_categories — genuinely
  policy-driven, and it can't silently drift out of sync with prose again.
  `is_safety_floor_category` is exported (no leading underscore) so
  risk_aggregator.py can reuse the exact same check instead of maintaining
  its own copy — see that file's notes for why that mattered.
"""

from __future__ import annotations
from typing import List, Optional

from backend.core.schemas import RiskSignal, EvaluationPlan, Severity, Action, RiskType


def is_safety_floor_category(sig: RiskSignal, plan: EvaluationPlan) -> bool:
    """
    True if `sig` belongs to a policy-defined safety-floor category (§12).

    A signal qualifies purely by having its risk_category listed in
    plan.safety_floor_categories (e.g. policy.yaml:
    safety_floor_categories: [credential_exposure, prohibited_unsafe_content]).
    Evaluators can introduce new categories freely — nothing here needs to
    change to recognize them; add the category name to policy.yaml instead.
    """
    return bool(sig.risk_category) and sig.risk_category in plan.safety_floor_categories


def check_safety_floor(
    signals: List[RiskSignal],
    plan: EvaluationPlan,
) -> Optional[RiskSignal]:
    """
    Check if any signal qualifies for the Safety Floor override (§12).

    Conditions (ALL must hold):
      1. plan.safety_floor is True (enabled in policy)
      2. signal.severity == CRITICAL
      3. signal.confidence >= plan.safety_floor_confidence_threshold (policy-configurable)
      4. signal.risk_category is listed in plan.safety_floor_categories

    Returns:
      The highest-risk qualifying RiskSignal (ties broken by confidence) if
      the safety floor fires, else None. Picking the worst qualifying
      signal — rather than the first one found in evaluator-run order, as
      before — keeps this deterministic regardless of which evaluator
      happens to run first.

    Action determination (per §12):
      - exposure-type risks (pii / credential) → Redact
      - unsafe-content risks (safety) → Block
    """
    if not plan.safety_floor:
        return None

    candidates = [
        sig for sig in signals
        if sig.severity == Severity.CRITICAL.value
        and sig.confidence >= plan.safety_floor_confidence_threshold
        and is_safety_floor_category(sig, plan)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.risk_score, s.confidence))


def get_safety_floor_action(triggering_signal: RiskSignal) -> str:
    """
    Determine the action for a safety-floor trigger (§12).
    Exposure-type risks (pii) → Redact.
    Unsafe-content risks → Block.
    """
    if triggering_signal.risk_type == RiskType.PII.value:
        return Action.REDACT.value
    return Action.BLOCK.value

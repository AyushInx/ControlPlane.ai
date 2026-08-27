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
"""

from __future__ import annotations
from typing import List, Optional

from backend.core.schemas import RiskSignal, EvaluationPlan, Severity


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
      4. signal belongs to a policy-defined safety-floor category

    Returns:
      The triggering RiskSignal if safety floor fires, else None.

    Action determination (per §12):
      - exposure-type risks (pii / credential) → Redact
      - unsafe-content risks (safety) → Block
    """
    if not plan.safety_floor:
        return None

    for sig in signals:
        if sig.severity != Severity.CRITICAL.value:
            continue
        if sig.confidence < plan.safety_floor_confidence_threshold:
            continue

        # Check if this signal belongs to a safety-floor category
        if _is_safety_floor_category(sig, plan):
            return sig

    return None


def _is_safety_floor_category(sig: RiskSignal, plan: EvaluationPlan) -> bool:
    """
    Determine if a signal belongs to a policy-defined safety-floor category.
    Categories are configured in policy.yaml under safety_floor_categories.
    """
    # Credential/secret exposure (PII evaluator marks these in reason)
    if sig.risk_type == "pii" and "credential_exposure" in plan.safety_floor_categories:
        if "credential_exposure" in sig.reason or any(
            kw in sig.reason.lower()
            for kw in ("credential", "api_key", "password", "bearer_token", "aws_key")
        ):
            return True

    # Prohibited unsafe content (Safety evaluator marks these in reason)
    if sig.risk_type == "safety" and "prohibited_unsafe_content" in plan.safety_floor_categories:
        if "prohibited_unsafe_content" in sig.reason or "safety-floor category" in sig.reason:
            return True

    return False


def get_safety_floor_action(triggering_signal: RiskSignal) -> str:
    """
    Determine the action for a safety-floor trigger (§12).
    Exposure-type risks → Redact.
    Unsafe-content risks → Block.
    """
    if triggering_signal.risk_type == "pii":
        return "redact"
    return "block"

"""
decision_engine.py — CORE 3: Uncertainty-Aware Decision Engine (§11)

Decision = f(risk severity, assessment confidence, evidence status,
             use-case context, policy, session state)

Confidence is an INPUT TO A RULE, never a multiplier on risk.
Rules are evaluated IN ORDER (1 → 6).

BINDING:
  - severity and confidence are ALWAYS separate — never multiplied.
  - UNSUPPORTED / UNKNOWN is NEVER treated as FALSE.
  - Every decision names the specific rule that fired.
  - Rule 6 escalates an otherwise-Allow decision, independent of current turn's severity.
"""

from __future__ import annotations
from typing import List

from backend.core.schemas import (
    RiskSignal, AggregatedResult, EvaluationPlan, DecisionResult,
    EvidenceStatus, Severity, Action
)
from backend.core.safety_floor import check_safety_floor, get_safety_floor_action

# ---------------------------------------------------------------------------
# Prototype heuristic: "high confidence" dividing line
# Clearly labeled as illustrative — not in spec as a specific number.
# ---------------------------------------------------------------------------
_HIGH_CONFIDENCE_THRESHOLD = 0.65


def _is_high_confidence(confidence: float) -> bool:
    return confidence >= _HIGH_CONFIDENCE_THRESHOLD


def _is_uncertain_evidence(evidence_status: str) -> bool:
    return evidence_status in (
        EvidenceStatus.UNSUPPORTED.value,
        EvidenceStatus.PARTIALLY_SUPPORTED.value,
    )


# ---------------------------------------------------------------------------
# Main decision function
# ---------------------------------------------------------------------------

def decide(
    aggregated: AggregatedResult,
    plan: EvaluationPlan,
    session_risk_before: float,
    session_risk_after: float,
) -> DecisionResult:
    """
    Apply the 6 decision rules in order (§11).

    Returns DecisionResult with:
      - action: the intervention
      - rule_fired: which rule produced this decision (1–6)
      - reason: human-readable explanation naming the specific rule
      - contributing_signals: all signals considered
      - dominant_signal: the signal that drove the decision
      - policy_version: for audit traceability
    """

    # ── Rule 1: Safety floor check (FIRST — overrides everything below) ─────
    sf_trigger = check_safety_floor(aggregated.signals, plan)
    if sf_trigger is not None:
        action = get_safety_floor_action(sf_trigger)
        return DecisionResult(
            action=action,
            rule_fired=1,
            reason=(
                f"Rule 1 fired: Safety floor triggered. "
                f"Signal risk_type={sf_trigger.risk_type}, "
                f"severity={sf_trigger.severity}, "
                f"confidence={sf_trigger.confidence:.2f} >= "
                f"policy safety_floor_confidence_threshold={plan.safety_floor_confidence_threshold}. "
                f"Policy-defined safety-floor category. "
                f"Action='{action}' (exposure-type → Redact; unsafe-content → Block). "
                f"This override is NOT subject to profile-specific softening (§12)."
            ),
            contributing_signals=aggregated.signals,
            dominant_signal=sf_trigger,
            policy_version=plan.policy_version,
        )

    # No signals at all → Allow
    if not aggregated.signals or aggregated.dominant_signal is None:
        return DecisionResult(
            action=Action.ALLOW.value,
            rule_fired=5,
            reason=(
                "Rule 5 fired: No risk signals detected. "
                "Allow — decision still logged and contributes to session state (§11)."
            ),
            contributing_signals=[],
            dominant_signal=None,
            policy_version=plan.policy_version,
        )

    dominant = aggregated.dominant_signal
    severity = dominant.severity
    confidence = dominant.confidence
    evidence_status = dominant.evidence_status
    risk_score = dominant.risk_score

    is_high_or_critical = severity in (Severity.HIGH.value, Severity.CRITICAL.value)
    is_high_conf = _is_high_confidence(confidence)
    is_low_conf = not is_high_conf
    is_uncertain = _is_uncertain_evidence(evidence_status)
    is_contradicted = evidence_status == EvidenceStatus.CONTRADICTED.value
    is_clearly_violating = evidence_status in (
        EvidenceStatus.CONTRADICTED.value, EvidenceStatus.SUPPORTED.value
    )

    # ── Rule 2: HIGH/CRITICAL + high confidence + CONTRADICTED / clearly violating ─
    if is_high_or_critical and is_high_conf and is_clearly_violating:
        if risk_score >= plan.block_threshold:
            # Action type depends on risk: exposure-type → Redact, unsafe-content → Block
            action = "redact" if dominant.risk_type == "pii" else "block"
            return DecisionResult(
                action=action,
                rule_fired=2,
                reason=(
                    f"Rule 2 fired: {severity} severity, high confidence "
                    f"(confidence={confidence:.2f} >= threshold {_HIGH_CONFIDENCE_THRESHOLD}), "
                    f"evidence_status={evidence_status}. "
                    f"risk_score={risk_score:.2f} >= block_threshold={plan.block_threshold}. "
                    f"Action='{action}' (exposure-type risks → Redact; "
                    f"unsafe-content risks → Block) per §11 Rule 2."
                ),
                contributing_signals=aggregated.signals,
                dominant_signal=dominant,
                policy_version=plan.policy_version,
            )

    # ── Rule 3: HIGH/CRITICAL + (low confidence OR uncertain evidence) ───────
    if is_high_or_critical and (is_low_conf or is_uncertain):
        action = plan.low_confidence_action
        uncertainty_reason = []
        if is_low_conf:
            uncertainty_reason.append(
                f"low confidence (confidence={confidence:.2f} < {_HIGH_CONFIDENCE_THRESHOLD})"
            )
        if is_uncertain:
            uncertainty_reason.append(f"uncertain evidence (evidence_status={evidence_status})")

        return DecisionResult(
            action=action,
            rule_fired=3,
            reason=(
                f"Rule 3 fired: {severity} severity with "
                f"{' and '.join(uncertainty_reason)}. "
                f"This is potentially severe risk, but uncertain — "
                f"UNSUPPORTED ≠ FALSE; LOW CONFIDENCE ≠ LOW RISK (§8). "
                f"Under profile '{plan.profile_name}', "
                f"low_confidence_action='{action}' (§11 Rule 3)."
            ),
            contributing_signals=aggregated.signals,
            dominant_signal=dominant,
            policy_version=plan.policy_version,
        )

    # ── Rule 4: MEDIUM severity above human_review_threshold ─────────────────
    if severity == Severity.MEDIUM.value and risk_score >= plan.human_review_threshold:
        return DecisionResult(
            action=Action.FLAG.value,
            rule_fired=4,
            reason=(
                f"Rule 4 fired: MEDIUM severity, "
                f"risk_score={risk_score:.2f} >= human_review_threshold={plan.human_review_threshold}. "
                f"Flag for review per profile '{plan.profile_name}' (§11 Rule 4)."
            ),
            contributing_signals=aggregated.signals,
            dominant_signal=dominant,
            policy_version=plan.policy_version,
        )

    # ── Rule 5: LOW severity (or MEDIUM below threshold) → Allow ─────────────
    initial_allow = DecisionResult(
        action=Action.ALLOW.value,
        rule_fired=5,
        reason=(
            f"Rule 5 fired: {severity} severity "
            f"(risk_score={risk_score:.2f}). "
            f"Allow — logged and contributes to session state (§11 Rule 5)."
        ),
        contributing_signals=aggregated.signals,
        dominant_signal=dominant,
        policy_version=plan.policy_version,
    )

    # ── Rule 6: Session-accumulated risk escalates an otherwise-Allow ─────────
    # Independent of the current turn's own severity (§11 Rule 6).
    if session_risk_after >= plan.session_risk_threshold:
        return DecisionResult(
            action=Action.HUMAN_REVIEW.value,
            rule_fired=6,
            reason=(
                f"Rule 6 fired: Session-accumulated risk "
                f"{session_risk_after:.3f} >= session_risk_threshold={plan.session_risk_threshold}. "
                f"Escalating an otherwise-Allow decision "
                f"independent of the current turn's own severity "
                f"(current turn: {severity}, risk_score={risk_score:.2f}) (§11 Rule 6, §13)."
            ),
            contributing_signals=aggregated.signals,
            dominant_signal=dominant,
            policy_version=plan.policy_version,
        )

    return initial_allow

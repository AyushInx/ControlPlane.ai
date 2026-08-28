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

FIX NOTES (this revision) — see ANALYSIS_AND_FIXES.md for the full writeup
and a worked example:
  - `high_confidence_threshold` is now read from the profile's policy
    (plan.high_confidence_threshold) instead of a single hardcoded module
    constant, so different use-case profiles can require different
    confidence bars before acting (defaults to 0.65 — the old hardcoded
    value — if a profile's policy.yaml entry omits it).
  - THE HEADLINE FIX: the evidence-status gate used to require
    evidence_status in (CONTRADICTED, SUPPORTED) before Rule 2 could fire.
    But NOT_APPLICABLE — the value every non-hallucination evaluator (pii,
    safety, prompt_injection) always reports, since "evidence" isn't a
    meaningful concept for a regex/pattern match — was never in that set.
    That meant Rule 2 could, in practice, only ever fire for hallucination
    findings with CONTRADICTED evidence. A CRITICAL-severity, 0.95-confidence
    SSN or credit-card detection, or a CRITICAL hate-speech match, fell
    through every single rule and was silently Allowed. Confirmed by
    running the original code against exactly that input before writing
    this fix — see ANALYSIS_AND_FIXES.md.
    Fixed: a signal is now "resolved" (not uncertain) whenever its
    evidence_status is anything other than UNSUPPORTED / PARTIALLY_SUPPORTED
    — which correctly includes NOT_APPLICABLE.
  - Rule 2 no longer falls through silently when risk_score is below
    block_threshold. It still fires (rule_fired=2) but returns FLAG instead
    of dropping through Rules 3–5 to a bare, untagged Allow — so a
    confidently and clearly assessed HIGH/CRITICAL finding is never
    returned with zero intervention, even under a lenient profile.
  - Action string literals ("redact", "block") now consistently go through
    the Action enum instead of being hand-typed, matching how the rest of
    this function already handles Action.ALLOW / Action.FLAG / etc.
"""

from __future__ import annotations

from backend.core.schemas import (
    EvaluationPlan, AggregatedResult, DecisionResult,
    EvidenceStatus, Severity, Action, RiskType,
)
from backend.core.safety_floor import check_safety_floor, get_safety_floor_action

# Fallback only — used if a plan somehow lacks the field despite the
# Pydantic default (defensive, shouldn't normally trigger).
_DEFAULT_HIGH_CONFIDENCE_THRESHOLD = 0.65


def _is_high_confidence(confidence: float, plan: EvaluationPlan) -> bool:
    threshold = plan.high_confidence_threshold
    if threshold is None:
        threshold = _DEFAULT_HIGH_CONFIDENCE_THRESHOLD
    return confidence >= threshold


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
                f"Signal risk_type={sf_trigger.risk_type}, risk_category={sf_trigger.risk_category}, "
                f"severity={sf_trigger.severity}, "
                f"confidence={sf_trigger.confidence:.2f} >= "
                f"policy safety_floor_confidence_threshold={plan.safety_floor_confidence_threshold}. "
                f"'{sf_trigger.risk_category}' is a policy-defined safety-floor category. "
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
    is_high_conf = _is_high_confidence(confidence, plan)
    is_low_conf = not is_high_conf
    is_uncertain = _is_uncertain_evidence(evidence_status)
    # "Resolved" = the evidence dimension does not leave this assessment
    # uncertain. True both when evidence clearly settled the question
    # (SUPPORTED / CONTRADICTED, from the groundedness evaluator) AND when
    # the evidence dimension simply doesn't apply (NOT_APPLICABLE — every
    # pii / safety / prompt_injection signal). Only UNSUPPORTED /
    # PARTIALLY_SUPPORTED represent genuine uncertainty. See fix notes above.
    is_resolved = not is_uncertain

    # ── Rule 2: HIGH/CRITICAL + high confidence + resolved evidence ─────────
    if is_high_or_critical and is_high_conf and is_resolved:
        if risk_score >= plan.block_threshold:
            action = Action.REDACT.value if dominant.risk_type == RiskType.PII.value else Action.BLOCK.value
            return DecisionResult(
                action=action,
                rule_fired=2,
                reason=(
                    f"Rule 2 fired: {severity} severity, high confidence "
                    f"(confidence={confidence:.2f} >= threshold {plan.high_confidence_threshold}), "
                    f"evidence_status={evidence_status}. "
                    f"risk_score={risk_score:.2f} >= block_threshold={plan.block_threshold}. "
                    f"Action='{action}' (exposure-type risks → Redact; "
                    f"unsafe-content risks → Block) per §11 Rule 2."
                ),
                contributing_signals=aggregated.signals,
                dominant_signal=dominant,
                policy_version=plan.policy_version,
            )
        else:
            # Confidently and clearly assessed as HIGH/CRITICAL, but this
            # profile's block_threshold wasn't crossed. Previously this fell
            # through Rules 3-5 to a bare, untagged Allow — now it's flagged
            # instead of silently dropped.
            return DecisionResult(
                action=Action.FLAG.value,
                rule_fired=2,
                reason=(
                    f"Rule 2 fired (below block threshold): {severity} severity, high confidence "
                    f"(confidence={confidence:.2f}), evidence_status={evidence_status}. "
                    f"risk_score={risk_score:.2f} < block_threshold={plan.block_threshold} for profile "
                    f"'{plan.profile_name}' — not severe enough to Block/Redact outright under this "
                    f"profile's tolerance, but confidently and clearly assessed as {severity}. "
                    f"Flagged rather than silently allowed (§11 Rule 2)."
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
                f"low confidence (confidence={confidence:.2f} < {plan.high_confidence_threshold})"
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

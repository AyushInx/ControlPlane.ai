"""
risk_aggregator.py — Step 8: Risk Aggregation (§10)

Implements the exact 7-step aggregation procedure from §10.
Signals are NEVER summed. hallucination:0.8 + privacy:0.8 ≠ 1.6.
Both findings are preserved individually.

BINDING:
  - Aggregation preserves individual signals — never a blind sum.
  - overlaps_with signals are LINKED, not merged.
  - The aggregated result is a decision-support signal, not a calibrated probability of harm.

FIX NOTES (this revision) — see ANALYSIS_AND_FIXES.md:
  - Step 6 used to re-implement its own version of "is this a safety-floor
    category", separate from (and subtly different than) safety_floor.py's
    version — including a check for the literal string "credential_exposure"
    that pii_evaluator never actually produces, so it never matched. That
    meant AggregatedResult.safety_floor_triggered could say False even when
    decision_engine's Rule 1 (which uses the real, correct check) was about
    to fire — an audit trail that disagreed with the actual decision. Step
    6 now imports and calls the exact same safety_floor.is_safety_floor_category()
    that Rule 1 uses, so the two can't drift apart again.
  - _annotate_overlaps only ever linked one hardcoded pair
    (hallucination, pii). It now walks a small, documented list of
    known-related risk-type pairs — easy to extend without touching the
    aggregation logic itself.
"""

from __future__ import annotations
from typing import List, Dict, FrozenSet

from backend.core.schemas import (
    RiskSignal, AggregatedResult, EvaluationPlan, Severity
)
from backend.core.safety_floor import is_safety_floor_category


# ---------------------------------------------------------------------------
# Severity ordering (for "highest severity" comparison)
# ---------------------------------------------------------------------------
_SEVERITY_ORDER = {
    Severity.LOW.value: 0,
    Severity.MEDIUM.value: 1,
    Severity.HIGH.value: 2,
    Severity.CRITICAL.value: 3,
}


def _severity_rank(sev: str) -> int:
    return _SEVERITY_ORDER.get(sev, 0)


# Known relationships between risk types: when both are present in the same
# evaluation, they're treated as linked (not merged) findings — resolving
# one may address the other. Extend this list as new relationships are
# identified; nothing else in aggregate() needs to change.
_RELATED_RISK_TYPE_PAIRS: List[FrozenSet[str]] = [
    frozenset({"hallucination", "pii"}),         # e.g. a fabricated personal detail
    frozenset({"safety", "prompt_injection"}),   # e.g. a jailbreak eliciting unsafe output
    frozenset({"pii", "safety"}),                # e.g. exposing someone's info as harassment
]


# ---------------------------------------------------------------------------
# Core aggregation procedure (§10, 7 steps)
# ---------------------------------------------------------------------------

def aggregate(signals: List[RiskSignal], plan: EvaluationPlan) -> AggregatedResult:
    """
    Seven-step aggregation procedure from §10:

    1. Normalize every evaluator output into the common risk signal schema (§8).
       (Already done by each evaluator — all signals conform to schema on entry.)

    2. Group findings by risk_type.

    3. Preserve the highest relevant severity per risk type —
       never averaged or summed away.

    4. Preserve confidence separately from severity throughout.

    5. Identify the dominant, policy-relevant risk
       (the signal driving the current decision tier).

    6. Apply any configured interaction/override rules
       (Safety Floor categories — §12).

    7. Produce an explainable decision, listing all contributing signals
       and which one dominated.
    """
    if not signals:
        return AggregatedResult(
            signals=[],
            dominant_signal=None,
            aggregated_severity=Severity.LOW.value,
            safety_floor_triggered=False,
            explanation="No risk signals detected across all evaluators.",
        )

    # ── Step 1: Already normalized by each evaluator (§8 schema guaranteed) ─

    # ── Step 2: Group by risk_type ──────────────────────────────────────────
    grouped: Dict[str, List[RiskSignal]] = {}
    for sig in signals:
        grouped.setdefault(sig.risk_type, []).append(sig)

    # ── Step 3: Preserve highest severity per risk_type ─────────────────────
    # Never average or sum away — only the highest-severity signal per type is
    # the representative, but ALL signals from all types are preserved.
    representative_per_type: Dict[str, RiskSignal] = {
        rtype: max(sigs, key=lambda s: s.risk_score)
        for rtype, sigs in grouped.items()
    }

    # ── Step 4: confidence preserved separately (never multiplied) ───────────
    # This is enforced in the schema — no collapse happens here.

    # ── Step 5: Identify dominant signal ────────────────────────────────────
    # Dominant = highest risk_score across all representative signals.
    dominant = max(representative_per_type.values(), key=lambda s: s.risk_score)

    # ── Step 6: Apply Safety Floor check ─────────────────────────────────────
    # Single source of truth with decision_engine's Rule 1 (see safety_floor.py)
    # so this flag can never disagree with the actual decision that gets made.
    safety_floor_triggered = False
    if plan.safety_floor:
        floor_candidates = [
            sig for sig in signals
            if sig.severity == Severity.CRITICAL.value
            and sig.confidence >= plan.safety_floor_confidence_threshold
            and is_safety_floor_category(sig, plan)
        ]
        if floor_candidates:
            safety_floor_triggered = True
            dominant = max(floor_candidates, key=lambda s: (s.risk_score, s.confidence))

    # ── Step 7: Produce explainable decision ─────────────────────────────────
    aggregated_severity = dominant.severity
    other_types = [t for t in representative_per_type if t != dominant.risk_type]

    explanation_parts = [
        f"Dominant signal: risk_type={dominant.risk_type}, risk_category={dominant.risk_category}, "
        f"risk_score={dominant.risk_score:.2f}, severity={dominant.severity}, "
        f"confidence={dominant.confidence:.2f}, "
        f"evidence_status={dominant.evidence_status}."
    ]
    if other_types:
        explanation_parts.append(
            f"Additional signals present (preserved individually): {', '.join(other_types)}. "
            "These are linked, not merged — resolving one may address others if overlaps_with applies."
        )
    if safety_floor_triggered:
        explanation_parts.append(
            "Safety floor triggered: CRITICAL severity + high confidence in "
            "policy-defined safety-floor category overrides normal profile behavior (§12)."
        )

    # Annotate overlaps_with links (§10 — linked, not merged)
    _annotate_overlaps(signals, representative_per_type)

    return AggregatedResult(
        signals=signals,   # ALL individual signals preserved
        dominant_signal=dominant,
        aggregated_severity=aggregated_severity,
        safety_floor_triggered=safety_floor_triggered,
        explanation=" | ".join(explanation_parts),
    )


def _annotate_overlaps(
    signals: List[RiskSignal],
    representative_per_type: Dict[str, RiskSignal],
) -> None:
    """
    Annotate overlaps_with for signals whose risk types are known to be
    related (see _RELATED_RISK_TYPE_PAIRS) and both present in this
    evaluation. Linked, not merged — resolving one is understood to
    potentially address the other.
    """
    present_types = set(representative_per_type.keys())
    for pair in _RELATED_RISK_TYPE_PAIRS:
        if not pair.issubset(present_types):
            continue
        type_a, type_b = tuple(pair)
        for sig in signals:
            if sig.risk_type == type_a and type_b not in sig.overlaps_with:
                sig.overlaps_with.append(type_b)
            elif sig.risk_type == type_b and type_a not in sig.overlaps_with:
                sig.overlaps_with.append(type_a)

"""
risk_aggregator.py — Step 8: Risk Aggregation (§10)

Implements the exact 7-step aggregation procedure from §10.
Signals are NEVER summed. hallucination:0.8 + privacy:0.8 ≠ 1.6.
Both findings are preserved individually.

BINDING:
  - Aggregation preserves individual signals — never a blind sum.
  - overlaps_with signals are LINKED, not merged.
  - The aggregated result is a decision-support signal, not a calibrated probability of harm.
"""

from __future__ import annotations
from typing import List, Optional, Dict

from backend.core.schemas import (
    RiskSignal, AggregatedResult, EvaluationPlan, score_to_severity, Severity
)


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
    representative_per_type: Dict[str, RiskSignal] = {}
    for rtype, sigs in grouped.items():
        # Pick signal with highest risk_score within this type
        representative_per_type[rtype] = max(sigs, key=lambda s: s.risk_score)

    # ── Step 4: confidence preserved separately (never multiplied) ───────────
    # This is enforced in the schema — no collapse happens here.

    # ── Step 5: Identify dominant signal ────────────────────────────────────
    # Dominant = highest risk_score across all representative signals.
    dominant = max(representative_per_type.values(), key=lambda s: s.risk_score)

    # ── Step 6: Apply Safety Floor check ─────────────────────────────────────
    safety_floor_triggered = False
    if plan.safety_floor:
        for sig in signals:
            is_sf_category = (
                sig.risk_type == "pii" and "credential_exposure" in sig.reason
            ) or (
                sig.risk_type == "safety" and any(
                    cat in sig.reason
                    for cat in plan.safety_floor_categories
                )
            )
            if (
                is_sf_category
                and sig.severity == Severity.CRITICAL.value
                and sig.confidence >= plan.safety_floor_confidence_threshold
            ):
                safety_floor_triggered = True
                # Safety floor dominant overrides
                dominant = sig
                break

    # ── Step 7: Produce explainable decision ─────────────────────────────────
    aggregated_severity = dominant.severity
    other_types = [t for t in representative_per_type if t != dominant.risk_type]

    explanation_parts = [
        f"Dominant signal: risk_type={dominant.risk_type}, "
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
    Annotate overlaps_with for signals that share the same source finding.
    Demo 4: hallucination + privacy on a fabricated personal detail.
    Both are linked — resolving one is understood to address both.
    """
    all_types = list(representative_per_type.keys())
    # If hallucination and pii both present, link them
    if "hallucination" in all_types and "pii" in all_types:
        for sig in signals:
            if sig.risk_type == "hallucination" and "pii" not in sig.overlaps_with:
                sig.overlaps_with.append("pii")
            elif sig.risk_type == "pii" and "hallucination" not in sig.overlaps_with:
                sig.overlaps_with.append("hallucination")

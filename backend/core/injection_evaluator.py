"""
injection_evaluator.py — Step 6: Prompt-Injection Heuristic (§9)

Two-phase check per §9:
  1. Pre-flight: detect jailbreak/injection patterns in the incoming prompt
     (gates/redacts the input before it reaches the model)
  2. Output re-check: detect injected-instruction leakage in the model output

Both phases use the same detector instance (shared per §16 note).
Returns risk_type=prompt_injection signals.

FIX NOTE (this revision) — see ANALYSIS_AND_FIXES.md:
  No functional bug found in this file specifically. Signals now carry a
  structured `risk_category` (the pattern label, e.g. "ignore_previous")
  for consistency with the other evaluators, and so downstream
  audit/analytics can filter by category without parsing `reason` prose.
  None of these categories are safety-floor-eligible today; that's a
  policy.yaml decision if you ever want one to be.
"""

from __future__ import annotations
import re
from typing import List, Tuple

from backend.core.evaluator_base import BaseEvaluator, EvalContext
from backend.core.schemas import RiskSignal, EvidenceStatus, score_to_severity

# ---------------------------------------------------------------------------
# Injection pattern registry
# Format: (label, pattern, risk_score, confidence)
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS: List[Tuple[str, re.Pattern, float, float]] = [
    # Direct instruction injection
    (
        "ignore_previous",
        re.compile(
            r'\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+'
            r'(?:instructions?|guidelines?|rules?|context|prompt)\b',
            re.I
        ),
        0.82, 0.88
    ),
    # System prompt override
    (
        "system_override",
        re.compile(
            r'\b(?:new\s+instructions?|override\s+(?:instructions?|system)|'
            r'act as if|pretend (?:you are|to be)|your new role is|'
            r'system prompt:\s|<\s*system\s*>)\b',
            re.I
        ),
        0.80, 0.85
    ),
    # Role-play jailbreak
    (
        "roleplay_jailbreak",
        re.compile(
            r'\b(?:you are now|from now on you|DAN|do anything now|'
            r'jailbreak|unlock your (?:full|true) potential|no\s+restrictions? mode)\b',
            re.I
        ),
        0.78, 0.82
    ),
    # Data exfiltration attempt
    (
        "exfiltration",
        re.compile(
            r'\b(?:print\s+(?:your\s+)?(?:system\s+prompt|instructions?|training data)|'
            r'reveal\s+(?:your\s+)?(?:confidential|hidden|secret)\s+(?:instructions?|data)|'
            r'what\s+(?:are|were)\s+your\s+(?:original\s+)?instructions?)\b',
            re.I
        ),
        0.75, 0.80
    ),
    # Leakage in output (injected instruction executed)
    (
        "output_leakage",
        re.compile(
            r'(?:as\s+instructed\s+by\s+the\s+user|following\s+the\s+override|'
            r'based\s+on\s+the\s+new\s+instructions?|since\s+you\s+told\s+me\s+to\s+ignore)',
            re.I
        ),
        0.85, 0.78
    ),
]


class InjectionEvaluator(BaseEvaluator):
    """
    Prompt-injection heuristic evaluator (§9).

    Pre-flight stage: evaluates the incoming prompt.
    Output stage: evaluates the model output for injected-instruction leakage.

    Pre-flight and output-stage checks share one InjectionEvaluator instance —
    same principle as the shared PII evaluator instance.
    """

    @property
    def name(self) -> str:
        return "injection"

    def evaluate(self, context: EvalContext, stage: str = "output") -> List[RiskSignal]:
        text = context.prompt if stage == "preflight" else context.model_output
        signals: List[RiskSignal] = []

        for label, pattern, risk_score, base_confidence in _INJECTION_PATTERNS:
            # output_leakage pattern only relevant on output stage
            if label == "output_leakage" and stage == "preflight":
                continue

            matches = pattern.findall(text)
            if not matches:
                continue

            confidence = min(0.95, base_confidence + 0.02 * (len(matches) - 1))
            sev = score_to_severity(risk_score)

            reason = (
                f"Prompt-injection pattern '{label}' detected in {stage} "
                f"({len(matches)} match(es)). "
                f"{'Pre-flight gate — input may be redacted before model call.' if stage == 'preflight' else 'Output re-check — injected-instruction leakage detected in model output.'} "
                f"confidence={confidence:.2f} (heuristic, probabilistic)."
            )

            signals.append(RiskSignal(
                risk_type="prompt_injection",
                risk_category=label,
                risk_score=risk_score,
                severity=sev.value,
                confidence=round(confidence, 3),
                evidence_status=EvidenceStatus.NOT_APPLICABLE.value,
                verified=False,
                evidence=[f"Stage: {stage}; pattern: '{label}'; match(es): {matches[:3]}"],
                overlaps_with=[],
                reason=reason,
            ))

        return signals

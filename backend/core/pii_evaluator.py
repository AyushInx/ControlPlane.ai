"""
pii_evaluator.py — Step 4: PII/Entity Detector (§9)

Two detection strategies with different confidence characteristics:
  1. Deterministic regex patterns (SSN, CC, email, phone, credentials)
     → high confidence (≈0.95) by construction
     → evidence_status = NOT_APPLICABLE
  2. Optional spaCy NER (PERSON, ORG entities)
     → probabilistic confidence (≈0.55)
     → evidence_status = NOT_APPLICABLE

BINDING:
  - PII detection does NOT automatically mean Block.
  - Routine PII follows normal profile-driven policy.
  - Only credential/secret exposure patterns → severity=CRITICAL → eligible for Safety Floor.
  - evidence_status = NOT_APPLICABLE for all PII findings (pattern match needs no external evidence).
"""

from __future__ import annotations
import re
from typing import List, Tuple

from backend.core.evaluator_base import BaseEvaluator, EvalContext
from backend.core.schemas import RiskSignal, EvidenceStatus, score_to_severity

# ---------------------------------------------------------------------------
# Optional spaCy import
# ---------------------------------------------------------------------------
try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    SPACY_AVAILABLE = True
except Exception:
    SPACY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Regex patterns
# Format: (name, compiled_pattern, risk_score, is_safety_floor_category)
# ---------------------------------------------------------------------------
_PATTERNS: List[Tuple[str, re.Pattern, float, bool]] = [
    # Credentials / secrets → CRITICAL (safety-floor eligible)
    ("api_key",      re.compile(r'\b(?:sk-|pk-|api[_-]?key[_-]?)[A-Za-z0-9_\-]{16,}\b', re.I), 0.92, True),
    ("password",     re.compile(r'\b(?:password|passwd|pwd)\s*[:=]\s*\S+', re.I), 0.90, True),
    ("bearer_token", re.compile(r'\bBearer\s+[A-Za-z0-9\-._~+/]+=*', re.I), 0.92, True),
    ("aws_key",      re.compile(r'\bAKIA[0-9A-Z]{16}\b'), 0.95, True),

    # High-sensitivity PII → HIGH
    ("ssn",          re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), 0.88, False),
    ("credit_card",  re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b'), 0.85, False),
    ("passport",     re.compile(r'\b[A-Z]{1,2}[0-9]{6,9}\b'), 0.72, False),

    # Medium-sensitivity PII → MEDIUM
    ("email",        re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), 0.45, False),
    ("phone_us",     re.compile(r'\b(?:\+1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'), 0.42, False),
    ("ip_address",   re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), 0.35, False),
]


def _redact_text(text: str, pattern: re.Pattern, placeholder: str) -> str:
    return pattern.sub(f"[REDACTED:{placeholder}]", text)


class PIIEvaluator(BaseEvaluator):
    """PII/Entity Detector — regex (deterministic) + optional spaCy NER."""

    @property
    def name(self) -> str:
        return "pii"

    def evaluate(self, context: EvalContext, stage: str = "output") -> List[RiskSignal]:
        text = context.prompt if stage == "preflight" else context.model_output
        signals: List[RiskSignal] = []

        # 1. Deterministic regex patterns
        for label, pattern, base_score, is_safety_floor in _PATTERNS:
            matches = pattern.findall(text)
            if not matches:
                continue

            risk_score = base_score
            sev = score_to_severity(risk_score)

            # Map to risk_type category
            if is_safety_floor:
                risk_cat = "credential_exposure"
                reason = (
                    f"Credential/secret pattern '{label}' detected "
                    f"({len(matches)} match(es)). severity=CRITICAL — "
                    "policy-defined safety-floor category (§12). "
                    "Note: routine PII findings follow normal policy; "
                    "only credential exposure invokes the safety floor."
                )
            else:
                risk_cat = label
                reason = (
                    f"PII pattern '{label}' detected ({len(matches)} match(es)). "
                    "Follows normal profile-driven policy — "
                    "PII detection does NOT automatically mean Block (§9)."
                )

            signals.append(RiskSignal(
                risk_type="pii",
                risk_score=risk_score,
                severity=sev.value,
                confidence=0.95,    # high confidence by construction (deterministic pattern)
                evidence_status=EvidenceStatus.NOT_APPLICABLE.value,
                verified=False,     # pattern match, not evidence-verified
                evidence=[],
                overlaps_with=[],
                reason=reason,
            ))

        # 2. Optional spaCy NER — probabilistic, lower confidence
        if SPACY_AVAILABLE:
            doc = _nlp(text)
            ner_entity_types = {"PERSON", "ORG"}
            found_types = {ent.label_ for ent in doc.ents if ent.label_ in ner_entity_types}

            if found_types:
                signals.append(RiskSignal(
                    risk_type="pii",
                    risk_score=0.38,     # MEDIUM — NER-inferred entity
                    severity=score_to_severity(0.38).value,
                    confidence=0.55,     # probabilistic, lower than pattern match (§9)
                    evidence_status=EvidenceStatus.NOT_APPLICABLE.value,
                    verified=False,
                    evidence=[],
                    overlaps_with=[],
                    reason=(
                        f"spaCy NER detected entity types: {found_types}. "
                        "NER-based inference carries lower confidence than "
                        "deterministic pattern matching (§9)."
                    ),
                ))

        return signals

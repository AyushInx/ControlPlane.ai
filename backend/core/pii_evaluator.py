"""
pii_evaluator.py — Step 4: PII/Entity Detector (§9)

Two detection strategies with different confidence characteristics:
  1. Deterministic regex patterns (SSN, CC, email, phone, credentials)
     → high confidence (≈0.95) by construction
     → evidence_status = NOT_APPLICABLE
  2. Optional spaCy NER (PERSON, ORG entities), only at evaluation_depth
     "standard"/"deep" — see fix notes below
     → probabilistic confidence (≈0.55)
     → evidence_status = NOT_APPLICABLE

BINDING:
  - PII detection does NOT automatically mean Block.
  - Routine PII follows normal profile-driven policy.
  - Only credential/secret exposure patterns → severity=CRITICAL → eligible for Safety Floor.
  - evidence_status = NOT_APPLICABLE for all PII findings (pattern match needs no external evidence).

FIX NOTES (this revision) — see ANALYSIS_AND_FIXES.md:
  - The spaCy model used to load at *import* time, so simply importing this
    module paid the full model-load cost even for profiles that never run
    the NER pass. It's now lazily loaded on first use.
  - The NER pass ran unconditionally, at every evaluation_depth — including
    "fast", which policy_engine.py documents as "deterministic PII
    patterns... No evidence retrieval. Minimal latency." Running spaCy NER
    on every fast-tier request contradicted that. NER is now skipped when
    evaluation_depth == "fast".
  - Each signal now carries a structured `risk_category` (e.g.
    "credential_exposure", "ssn") instead of a per-pattern boolean that
    only affected wording — see safety_floor.py for why that mattered.
    Safety-floor eligibility is now decided the same way everywhere: by
    checking whether the category is listed in policy's
    safety_floor_categories, at the point the reason text is generated too,
    so wording and gating can never disagree.
  - Removed `_redact_text`: it was defined but never called anywhere in
    this file. If actual text redaction (replacing the matched span in the
    output before it's returned) isn't already implemented in your
    orchestration layer, that's a real gap worth checking — detecting PII
    and deciding "redact" doesn't by itself mask anything in the response.
"""

from __future__ import annotations
import re
from typing import List, Tuple

from backend.core.evaluator_base import BaseEvaluator, EvalContext
from backend.core.schemas import RiskSignal, EvidenceStatus, score_to_severity

# ---------------------------------------------------------------------------
# Optional spaCy import — library import stays eager (cheap, just tells us
# whether the package is installed); the actual model load is lazy (see
# _get_nlp), since that's the expensive part.
# ---------------------------------------------------------------------------
try:
    import spacy
    SPACY_AVAILABLE = True
except Exception:
    SPACY_AVAILABLE = False

_nlp = None
_nlp_load_failed = False


def _get_nlp():
    """Lazily load and cache the spaCy model. Returns None if unavailable."""
    global _nlp, _nlp_load_failed
    if not SPACY_AVAILABLE or _nlp_load_failed:
        return None
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except Exception:
            _nlp_load_failed = True
            return None
    return _nlp


# ---------------------------------------------------------------------------
# Regex patterns
# Format: (name, compiled_pattern, risk_score, risk_category)
# The 4 credential patterns share risk_category="credential_exposure" (the
# category policy.yaml lists under safety_floor_categories). Every other
# pattern's risk_category is just its own name — none of them are
# safety-floor cases by default, but that's a policy.yaml decision, not
# something hardcoded here.
# ---------------------------------------------------------------------------
_PATTERNS: List[Tuple[str, re.Pattern, float, str]] = [
    # Credentials / secrets → CRITICAL, safety-floor category
    ("api_key",      re.compile(r'\b(?:sk-|pk-|api[_-]?key[_-]?)[A-Za-z0-9_\-]{16,}\b', re.I), 0.92, "credential_exposure"),
    ("password",     re.compile(r'\b(?:password|passwd|pwd)\s*[:=]\s*\S+', re.I), 0.90, "credential_exposure"),
    ("bearer_token", re.compile(r'\bBearer\s+[A-Za-z0-9\-._~+/]+=*', re.I), 0.92, "credential_exposure"),
    ("aws_key",      re.compile(r'\bAKIA[0-9A-Z]{16}\b'), 0.95, "credential_exposure"),

    # High-sensitivity PII → HIGH/CRITICAL, own categories
    ("ssn",          re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), 0.88, "ssn"),
    ("credit_card",  re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b'), 0.85, "credit_card"),
    # NOTE: broad by design — 1-2 capital letters + 6-9 digits also matches
    # many non-passport identifiers (order numbers, product codes, etc).
    # Left as-is to avoid changing detection recall; if false positives show
    # up in review, consider requiring a nearby keyword like "passport".
    ("passport",     re.compile(r'\b[A-Z]{1,2}[0-9]{6,9}\b'), 0.72, "passport"),

    # Medium-sensitivity PII → MEDIUM
    ("email",        re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), 0.45, "email"),
    ("phone_us",     re.compile(r'\b(?:\+1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'), 0.42, "phone_us"),
    ("ip_address",   re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), 0.35, "ip_address"),
]


class PIIEvaluator(BaseEvaluator):
    """PII/Entity Detector — regex (deterministic) + optional spaCy NER."""

    @property
    def name(self) -> str:
        return "pii"

    def evaluate(self, context: EvalContext, stage: str = "output") -> List[RiskSignal]:
        text = context.prompt if stage == "preflight" else context.model_output
        signals: List[RiskSignal] = []
        floor_categories = context.plan.safety_floor_categories

        # 1. Deterministic regex patterns — run at every depth
        for label, pattern, base_score, risk_category in _PATTERNS:
            matches = pattern.findall(text)
            if not matches:
                continue

            risk_score = base_score
            sev = score_to_severity(risk_score)
            is_floor_eligible = risk_category in floor_categories

            if is_floor_eligible:
                reason = (
                    f"Credential/secret pattern '{label}' detected "
                    f"({len(matches)} match(es)). severity=CRITICAL — "
                    f"'{risk_category}' is a policy-defined safety-floor category (§12). "
                    "Note: routine PII findings follow normal policy; "
                    "only credential exposure invokes the safety floor."
                )
            else:
                reason = (
                    f"PII pattern '{label}' detected ({len(matches)} match(es)). "
                    "Follows normal profile-driven policy — "
                    "PII detection does NOT automatically mean Block (§9)."
                )

            signals.append(RiskSignal(
                risk_type="pii",
                risk_category=risk_category,
                risk_score=risk_score,
                severity=sev.value,
                confidence=0.95,    # high confidence by construction (deterministic pattern)
                evidence_status=EvidenceStatus.NOT_APPLICABLE.value,
                verified=False,     # pattern match, not evidence-verified
                evidence=[f"pattern:{label}"],   # pattern name only — never the matched value itself
                overlaps_with=[],
                reason=reason,
            ))

        # 2. Optional spaCy NER — probabilistic, lower confidence.
        # Skipped at "fast" depth to honor its documented minimal-latency,
        # deterministic-patterns-only contract (§6).
        if context.plan.evaluation_depth != "fast":
            nlp = _get_nlp()
            if nlp is not None:
                doc = nlp(text)
                ner_entity_types = {"PERSON", "ORG"}
                found_types = {ent.label_ for ent in doc.ents if ent.label_ in ner_entity_types}

                if found_types:
                    signals.append(RiskSignal(
                        risk_type="pii",
                        risk_category="ner_entity",
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

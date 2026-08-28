"""
groundedness_evaluator.py — Step 5: Groundedness / Evidence Evaluator (§9)

Implements the hallucination check via two cases:

  Case A — trusted evidence exists:
    claim extraction → embedding similarity + NLI-style classification
    → SUPPORTED / CONTRADICTED / PARTIALLY_SUPPORTED
    → confidence derived from similarity score
    → deterministic and reproducible (primary implementation)

  Case B — no reliable evidence exists:
    → evidence_status = UNSUPPORTED
    → confidence reflects assessment uncertainty
    → NEVER writes FALSE — reports "claim could not be verified"

  An AI-as-judge pass is documented as a possible future extension (would
  be labeled "model-based heuristic assessment", could never set
  evidence_status to SUPPORTED, could only adjust confidence within the
  UNSUPPORTED state) — it is NOT implemented in this revision, since it
  needs an LLM client wired in that isn't part of these files. The system
  is fully functional without it, exactly as originally documented; adding
  it later is additive, not a required fix.

BINDING:
  UNSUPPORTED ≠ FALSE.
  ControlPlane never says "no source found, therefore hallucination."

FIX NOTES (this revision) — see ANALYSIS_AND_FIXES.md:
  - The sentence-transformers model used to load at *import* time, so
    simply importing this module paid the full model-load cost even for
    profiles that never reach "standard"/"deep" depth (groundedness isn't
    eligible at "fast"). It's now lazily loaded on first use.
  - `evaluation_depth` was accepted as a parameter on `_case_a` but never
    actually referenced anywhere in its body — "deep" and "standard"
    evaluated identically, contradicting policy_engine's own documented
    claim that "evaluation_depth drives real behavior — it is not just a
    label." The per-turn claim cap (previously a fixed `[:5]`) is now
    depth-aware: "deep" analyzes more claims per turn than "standard".
  - Case A used to collapse every claim's findings down to a single
    returned signal (the worst one), discarding the rest before they ever
    reached risk_aggregator — undercutting the "all individual signals are
    preserved" principle the rest of the system relies on. It now returns
    one signal per evaluated claim; risk_aggregator picks the
    representative while keeping the others for audit.
"""

from __future__ import annotations
import re
from typing import List, Tuple

from backend.core.evaluator_base import BaseEvaluator, EvalContext
from backend.core.schemas import RiskSignal, EvidenceStatus, score_to_severity

# ---------------------------------------------------------------------------
# Optional sentence-transformers import — library import stays eager
# (cheap); the actual model load is lazy (see _get_st_model).
# ---------------------------------------------------------------------------
try:
    from sentence_transformers import SentenceTransformer, util as st_util
    ST_AVAILABLE = True
except Exception:
    ST_AVAILABLE = False

_ST_MODEL = None
_ST_MODEL_LOAD_FAILED = False
_ST_MODEL_NAME = "all-MiniLM-L6-v2"

# NLI-style classification thresholds (illustrative prototype values — §8 caveat)
_SUPPORTED_SIMILARITY = 0.65
_PARTIAL_SIMILARITY = 0.35

# How many claims to evaluate per turn, by evaluation_depth. "deep" spends
# more effort per turn on stronger claim-level analysis, matching what
# policy_engine.derive_evaluation_plan documents for the "deep" tier.
_MAX_CLAIMS_BY_DEPTH = {
    "fast": 3,        # groundedness isn't eligible at "fast" today, kept
                       # defined in case that ever changes.
    "standard": 5,
    "deep": 8,
}
_DEFAULT_MAX_CLAIMS = 5


def _get_st_model():
    """Lazily load and cache the sentence-transformers model. Returns None if unavailable."""
    global _ST_MODEL, _ST_MODEL_LOAD_FAILED
    if not ST_AVAILABLE or _ST_MODEL_LOAD_FAILED:
        return None
    if _ST_MODEL is None:
        try:
            _ST_MODEL = SentenceTransformer(_ST_MODEL_NAME)
        except Exception:
            _ST_MODEL_LOAD_FAILED = True
            return None
    return _ST_MODEL


def _max_claims_for_depth(depth: str) -> int:
    return _MAX_CLAIMS_BY_DEPTH.get(depth, _DEFAULT_MAX_CLAIMS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_claims(text: str, max_claims: int = _DEFAULT_MAX_CLAIMS) -> List[str]:
    """
    Simple claim extraction: split on sentence boundaries.
    Returns sentences that look like factual statements (contain a verb + noun).
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    claims = []
    for s in sentences:
        s = s.strip()
        if len(s) > 20 and not s.startswith(("I ", "We ", "You ")):
            claims.append(s)
    return claims[:max_claims]


def _cosine_similarity(a, b) -> float:
    """Cosine similarity between two embedding tensors or lists."""
    try:
        score = st_util.cos_sim(a, b).item()
        return float(score)
    except Exception:
        return 0.0


def _nli_classify(similarity: float, claim: str, evidence: str) -> Tuple[str, float]:
    """
    Lightweight NLI-style classification using similarity + negation heuristics.
    Returns (evidence_status, confidence).
    """
    claim_keywords = set(re.findall(r'\b\w{4,}\b', claim.lower()))
    evidence_lower = evidence.lower()

    negation_patterns = [
        r'\b(?:not|never|no|false|incorrect|wrong|contrary|dispute|contradict)\b'
    ]
    has_negation = any(re.search(p, evidence_lower) for p in negation_patterns)
    has_keyword_overlap = bool(claim_keywords & set(re.findall(r'\b\w{4,}\b', evidence_lower)))

    if similarity >= _SUPPORTED_SIMILARITY:
        if has_negation:
            return EvidenceStatus.CONTRADICTED.value, min(0.85, similarity)
        return EvidenceStatus.SUPPORTED.value, min(0.92, similarity + 0.1)
    elif similarity >= _PARTIAL_SIMILARITY:
        if has_negation and has_keyword_overlap:
            return EvidenceStatus.CONTRADICTED.value, 0.60
        return EvidenceStatus.PARTIALLY_SUPPORTED.value, similarity
    else:
        return EvidenceStatus.UNSUPPORTED.value, max(0.20, similarity)


class GroundednessEvaluator(BaseEvaluator):
    """Groundedness / Evidence evaluator — Cases A and B (§9)."""

    @property
    def name(self) -> str:
        return "groundedness"

    def evaluate(self, context: EvalContext, stage: str = "output") -> List[RiskSignal]:
        # Groundedness evaluates model output only (not preflight)
        if stage == "preflight":
            return []

        text = context.model_output
        evidence_doc = context.trusted_evidence
        depth = context.plan.evaluation_depth

        claims = _extract_claims(text, max_claims=_max_claims_for_depth(depth))
        if not claims:
            return []

        model = _get_st_model() if evidence_doc else None
        if evidence_doc and model is not None:
            # ── Case A: trusted evidence available ─────────────────────────
            return self._case_a(claims, evidence_doc, model)
        # ── Case B: no reliable evidence ───────────────────────────────────
        return self._case_b(claims)

    def _case_a(self, claims: List[str], evidence_doc: str, model) -> List[RiskSignal]:
        """
        Case A: evidence exists → embed + NLI classify.
        Returns one signal per claim — risk_aggregator picks the worst as
        the representative while preserving the rest for audit (§10 Step 3).
        Deterministic and reproducible (primary implementation).
        """
        evidence_embedding = model.encode(evidence_doc, convert_to_tensor=True)
        results: List[RiskSignal] = []

        for claim in claims:
            claim_embedding = model.encode(claim, convert_to_tensor=True)
            sim = _cosine_similarity(claim_embedding, evidence_embedding)
            ev_status, confidence = _nli_classify(sim, claim, evidence_doc)

            # risk_score: high when CONTRADICTED, low when SUPPORTED
            if ev_status == EvidenceStatus.CONTRADICTED.value:
                risk_score = 0.72
            elif ev_status == EvidenceStatus.PARTIALLY_SUPPORTED.value:
                risk_score = 0.45
            else:  # SUPPORTED
                risk_score = 0.10

            verified = ev_status == EvidenceStatus.SUPPORTED.value and confidence >= 0.70

            results.append(RiskSignal(
                risk_type="hallucination",
                risk_category=f"hallucination_{ev_status.lower()}",
                risk_score=risk_score,
                severity=score_to_severity(risk_score).value,
                confidence=round(confidence, 3),
                evidence_status=ev_status,
                verified=verified,
                evidence=[f"Similarity={sim:.3f}; evidence excerpt: {evidence_doc[:200]}..."],
                overlaps_with=[],
                reason=(
                    f"Claim: '{claim[:80]}...' — "
                    f"evidence_status={ev_status}, similarity={sim:.3f}. "
                    f"{'Verified against trusted source.' if verified else 'Assessment based on embedding similarity + NLI heuristic (§9 Case A).'}"
                ),
            ))

        return results

    def _case_b(self, claims: List[str]) -> List[RiskSignal]:
        """
        Case B: no reliable evidence.
        Returns UNSUPPORTED — NEVER writes FALSE.
        'Claim could not be verified against available evidence.'
        """
        return [RiskSignal(
            risk_type="hallucination",
            risk_category="hallucination_unsupported",
            risk_score=0.55,
            severity=score_to_severity(0.55).value,
            confidence=0.28,     # low confidence — assessment uncertainty (§9)
            evidence_status=EvidenceStatus.UNSUPPORTED.value,
            verified=False,
            evidence=[],
            overlaps_with=[],
            reason=(
                "Claim could not be verified against available evidence. "
                "UNSUPPORTED ≠ FALSE — ControlPlane cannot verify this claim "
                "either way without a trusted source document (§7, §9 Case B). "
                f"Claim sample: '{claims[0][:100] if claims else 'N/A'}...' "
                f"({len(claims)} claim(s) evaluated)."
            ),
        )]

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

  Optional: AI-as-judge pass
    → labeled "model-based heuristic assessment"
    → can NEVER set evidence_status to SUPPORTED
    → can only adjust confidence within the UNSUPPORTED state
    → system is fully functional without it

BINDING:
  UNSUPPORTED ≠ FALSE.
  ControlPlane never says "no source found, therefore hallucination."
"""

from __future__ import annotations
import re
from typing import List, Optional, Tuple

from backend.core.evaluator_base import BaseEvaluator, EvalContext
from backend.core.schemas import RiskSignal, EvidenceStatus, score_to_severity

# ---------------------------------------------------------------------------
# Optional sentence-transformers import
# ---------------------------------------------------------------------------
try:
    from sentence_transformers import SentenceTransformer, util as st_util
    import torch
    _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    ST_AVAILABLE = True
except Exception:
    ST_AVAILABLE = False
    _ST_MODEL = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_claims(text: str) -> List[str]:
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
    return claims[:5]  # cap at 5 claims to limit latency


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

    Thresholds (illustrative prototype values — §8 caveat):
      similarity >= 0.65 → SUPPORTED
      similarity >= 0.35 → PARTIALLY_SUPPORTED
      similarity < 0.35  → UNSUPPORTED (not enough evidence either way)
      + negation check   → CONTRADICTED
    """
    # Check for negation signals in evidence relative to claim keywords
    claim_keywords = set(re.findall(r'\b\w{4,}\b', claim.lower()))
    evidence_lower = evidence.lower()

    negation_patterns = [
        r'\b(?:not|never|no|false|incorrect|wrong|contrary|dispute|contradict)\b'
    ]
    has_negation = any(re.search(p, evidence_lower) for p in negation_patterns)
    has_keyword_overlap = bool(claim_keywords & set(re.findall(r'\b\w{4,}\b', evidence_lower)))

    if similarity >= 0.65:
        if has_negation:
            return EvidenceStatus.CONTRADICTED.value, min(0.85, similarity)
        return EvidenceStatus.SUPPORTED.value, min(0.92, similarity + 0.1)
    elif similarity >= 0.35:
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
        signals: List[RiskSignal] = []

        claims = _extract_claims(text)
        if not claims:
            return []

        if evidence_doc and ST_AVAILABLE and _ST_MODEL is not None:
            # ── Case A: trusted evidence available ─────────────────────────
            signals.extend(
                self._case_a(claims, evidence_doc, context.plan.evaluation_depth)
            )
        else:
            # ── Case B: no reliable evidence ───────────────────────────────
            signals.extend(self._case_b(claims))

        return signals

    def _case_a(
        self,
        claims: List[str],
        evidence_doc: str,
        depth: str,
    ) -> List[RiskSignal]:
        """
        Case A: evidence exists → embed + NLI classify.
        Returns SUPPORTED / CONTRADICTED / PARTIALLY_SUPPORTED.
        Deterministic and reproducible (primary implementation).
        """
        # Encode claims and evidence
        evidence_embedding = _ST_MODEL.encode(evidence_doc, convert_to_tensor=True)
        results = []

        for claim in claims:
            claim_embedding = _ST_MODEL.encode(claim, convert_to_tensor=True)
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

        # Return the highest-risk signal (others fold in via risk_aggregator)
        if results:
            return [max(results, key=lambda s: s.risk_score)]
        return []

    def _case_b(self, claims: List[str]) -> List[RiskSignal]:
        """
        Case B: no reliable evidence.
        Returns UNSUPPORTED — NEVER writes FALSE.
        'Claim could not be verified against available evidence.'
        """
        return [RiskSignal(
            risk_type="hallucination",
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
                f"Claim sample: '{claims[0][:100] if claims else 'N/A'}...'"
            ),
        )]

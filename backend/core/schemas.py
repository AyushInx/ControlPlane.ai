"""
schemas.py — Shared Pydantic models for ControlPlane.ai (§8, §14, §15)

All evaluators, the decision engine, and the API share these schemas.
RiskSignal is the canonical signal shape — never deviate from it.

BINDING: risk_score and confidence are ALWAYS separate fields.
         severity × confidence is NEVER computed.
         evidence_status UNSUPPORTED is NEVER displayed or stored as FALSE.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RiskType(str, Enum):
    PII = "pii"
    HALLUCINATION = "hallucination"
    SAFETY = "safety"
    PROMPT_INJECTION = "prompt_injection"


class Severity(str, Enum):
    """
    Severity bands (§8 — illustrative prototype bands, not scientifically calibrated):
      LOW      → risk_score 0.00 – 0.29
      MEDIUM   → risk_score 0.30 – 0.59
      HIGH     → risk_score 0.60 – 0.79
      CRITICAL → risk_score 0.80 – 1.00
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EvidenceStatus(str, Enum):
    """
    Epistemic boundary states (§7).
    UNSUPPORTED ≠ FALSE. UNKNOWN ≠ FALSE.
    """
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"          # ← NEVER display or store as FALSE
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Action(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_FLAG = "allow_with_flag"
    EDIT_SOFTEN = "edit_soften"
    REDACT = "redact"
    FLAG = "flag"
    HUMAN_REVIEW = "human_review"
    BLOCK = "block"


class EvaluationDepth(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


# ---------------------------------------------------------------------------
# Severity helper
# ---------------------------------------------------------------------------

def score_to_severity(score: float) -> Severity:
    """Map a risk_score to a Severity band per §8."""
    if score < 0.30:
        return Severity.LOW
    elif score < 0.60:
        return Severity.MEDIUM
    elif score < 0.80:
        return Severity.HIGH
    else:
        return Severity.CRITICAL


# ---------------------------------------------------------------------------
# Core signal schema (§8)
# ---------------------------------------------------------------------------

class RiskSignal(BaseModel):
    """
    The canonical risk signal emitted by every evaluator (§8).
    All 9 fields are always present.

    BINDING CONSTRAINTS:
      - risk_score describes severity IF the assessment is correct; independent of confidence.
      - confidence is a separate dimension; it qualifies assessment reliability, not severity.
      - risk_score=0.90, confidence=0.25 does NOT become risk=0.225.
      - evidence_status UNSUPPORTED is NEVER equivalent to FALSE.
    """
    risk_type: str                      # pii | hallucination | safety | prompt_injection
    risk_score: float = Field(ge=0.0, le=1.0)   # severity of risk IF assessment is correct
    severity: str                       # LOW | MEDIUM | HIGH | CRITICAL (from score_to_severity)
    confidence: float = Field(ge=0.0, le=1.0)   # evaluator's confidence in its OWN assessment
    evidence_status: str                # SUPPORTED | CONTRADICTED | PARTIALLY_SUPPORTED | UNSUPPORTED | NOT_APPLICABLE
    verified: bool                      # True only when sufficient trusted evidence exists
    evidence: List[str] = []            # source snippets / citations
    overlaps_with: List[str] = []       # other risk_types this finding also implicates
    reason: str                         # human-readable explanation of the assessment


# ---------------------------------------------------------------------------
# Policy / evaluation plan
# ---------------------------------------------------------------------------

class UseCasePolicy(BaseModel):
    """Single profile policy loaded from policy.yaml (§6)."""
    profile_name: str
    risk_tolerance: str
    latency_budget_ms: int
    evaluation_depth: str
    enabled_evaluators: List[str]
    low_confidence_action: str
    human_review_threshold: float
    block_threshold: float
    session_risk_threshold: float
    decay_factor: float
    risk_weight: float
    safety_floor: bool
    safety_floor_confidence_threshold: float
    safety_floor_categories: List[str]
    policy_version: str


class EvaluationPlan(BaseModel):
    """
    Output of policy_engine.derive_evaluation_plan (§6, §16).
    Carries BOTH the evaluator list/depth AND the decision thresholds
    those evaluators will later be judged against — not merely thresholds.
    """
    profile_name: str
    enabled_evaluators: List[str]       # which evaluators actually run
    evaluation_depth: str               # fast | standard | deep
    latency_budget_ms: int              # target budget (not a guarantee)
    # Decision thresholds
    human_review_threshold: float
    block_threshold: float
    session_risk_threshold: float
    low_confidence_action: str
    safety_floor: bool
    safety_floor_confidence_threshold: float
    safety_floor_categories: List[str]
    decay_factor: float
    risk_weight: float
    policy_version: str


# ---------------------------------------------------------------------------
# Evaluation request / response
# ---------------------------------------------------------------------------

class EvaluationRequest(BaseModel):
    request_id: Optional[str] = None
    session_id: str
    profile: str                        # customer_facing_chatbot | internal_copilot | regulated_decision_support
    prompt: str
    model_output: str
    trusted_evidence: Optional[str] = None   # source document for groundedness Case A
    model_id: str = "mock-llm-v1"


class AggregatedResult(BaseModel):
    """Output of risk_aggregator (§10)."""
    signals: List[RiskSignal]           # ALL individual signals preserved
    dominant_signal: Optional[RiskSignal] = None
    aggregated_severity: str
    safety_floor_triggered: bool = False
    explanation: str                    # which signal dominated and why


class DecisionResult(BaseModel):
    """Output of decision_engine (§11)."""
    action: str                         # allow | allow_with_flag | edit_soften | redact | flag | human_review | block
    rule_fired: int                     # 1–6 (which rule produced this decision)
    reason: str                         # references the specific rule that fired
    contributing_signals: List[RiskSignal]
    dominant_signal: Optional[RiskSignal] = None
    policy_version: str


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

class SessionState(BaseModel):
    """Stored per session_id (§13)."""
    session_id: str
    profile: str
    session_risk: float
    turn_count: int
    history: List[Dict[str, Any]] = []  # per-turn: {turn, risk_score, weighted, session_risk_after}
    created_at: str
    updated_at: str


class SessionUpdateResult(BaseModel):
    session_risk_before: float
    session_risk_after: float
    weighted_turn_risk: float
    threshold_crossed: bool
    session_risk_threshold: float


# ---------------------------------------------------------------------------
# Human review queue item (§14) — all 11 fields
# ---------------------------------------------------------------------------

class ReviewQueueItem(BaseModel):
    review_id: str
    session_id: str
    request: str
    model_output: str
    use_case_profile: str
    policy_version: str
    risk_signals: List[RiskSignal]
    session_risk: float
    escalation_reason: str
    recommended_action: str
    reviewer_action: Optional[str] = None   # None | "approve" | "edit" | "reject"
    created_at: Optional[str] = None
    reviewed_at: Optional[str] = None


class ReviewActionRequest(BaseModel):
    reviewer_action: str   # approve | edit | reject
    reviewer_note: Optional[str] = None


# ---------------------------------------------------------------------------
# Audit record (§15) — all 15 fields
# ---------------------------------------------------------------------------

class AuditRecord(BaseModel):
    timestamp: str
    request_id: str
    session_id: str
    use_case_profile: str
    policy_version: str
    model_id: str
    latency_ms: float
    signals: List[RiskSignal]           # all evaluator outputs, individual, preserved
    aggregated_severity: str
    confidence: float                   # confidence of dominant signal
    evidence_status: str                # evidence_status of dominant signal
    session_risk_before: float
    session_risk_after: float
    final_action: str
    decision_reason: str                # references the specific rule that fired


# ---------------------------------------------------------------------------
# API response
# ---------------------------------------------------------------------------

class EvaluationResponse(BaseModel):
    request_id: str
    session_id: str
    profile: str
    decision: DecisionResult
    signals: List[RiskSignal]
    aggregated_severity: str
    session_risk_before: float
    session_risk_after: float
    audit_record: AuditRecord
    review_queue_item: Optional[ReviewQueueItem] = None

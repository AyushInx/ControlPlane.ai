"""
audit_logger.py — CORE 4: Full Audit Logger (§15)

Writes a complete audit record for every decision.
Every field from §15 worked example is present.
Every decision must be answerable with "why did ControlPlane make this decision?"

FIX NOTE (this revision) — see ANALYSIS_AND_FIXES.md:
  Small cleanups only: the "no dominant signal" fallback used a bare
  "NOT_APPLICABLE" string literal instead of EvidenceStatus.NOT_APPLICABLE.value
  (harmless today since they're equal, but one typo away from silently
  diverging from the schema); `profile`/`action` filters were typed as
  `str = None`, which Optional[str] now says correctly; and an unused
  `RiskSignal` import was removed.
"""

from __future__ import annotations
import json
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from backend.core.schemas import (
    AuditRecord, DecisionResult, AggregatedResult,
    SessionUpdateResult, EvaluationPlan, EvidenceStatus,
)
from backend.db.database import AuditLogModel


def write_audit_record(
    request_id: str,
    session_id: str,
    profile: str,
    plan: EvaluationPlan,
    model_id: str,
    latency_ms: float,
    aggregated: AggregatedResult,
    session_update: SessionUpdateResult,
    decision: DecisionResult,
    timestamp: str,
    db: DBSession,
) -> AuditRecord:
    """
    Write a full audit record to the database and return it (§15).

    All 15 fields per §15 are present:
      timestamp, request_id, session_id, use_case_profile, policy_version,
      model_id, latency_ms, signals, aggregated_severity, confidence,
      evidence_status, session_risk_before, session_risk_after,
      final_action, decision_reason.
    """
    dominant = aggregated.dominant_signal
    confidence = dominant.confidence if dominant else 0.0
    evidence_status = dominant.evidence_status if dominant else EvidenceStatus.NOT_APPLICABLE.value

    record = AuditRecord(
        timestamp=timestamp,
        request_id=request_id,
        session_id=session_id,
        use_case_profile=profile,
        policy_version=plan.policy_version,
        model_id=model_id,
        latency_ms=round(latency_ms, 2),
        signals=aggregated.signals,
        aggregated_severity=aggregated.aggregated_severity,
        confidence=round(confidence, 3),
        evidence_status=evidence_status,
        session_risk_before=round(session_update.session_risk_before, 4),
        session_risk_after=round(session_update.session_risk_after, 4),
        final_action=decision.action,
        decision_reason=decision.reason,
    )

    # Persist to SQLite
    db_record = AuditLogModel(
        request_id=request_id,
        session_id=session_id,
        timestamp=timestamp,
        use_case_profile=profile,
        policy_version=plan.policy_version,
        model_id=model_id,
        latency_ms=record.latency_ms,
        signals_json=json.dumps([s.model_dump() for s in aggregated.signals]),
        aggregated_severity=aggregated.aggregated_severity,
        confidence=record.confidence,
        evidence_status=evidence_status,
        session_risk_before=record.session_risk_before,
        session_risk_after=record.session_risk_after,
        final_action=decision.action,
        decision_reason=decision.reason,
    )
    db.add(db_record)
    db.commit()

    return record


def get_audit_log(
    db: DBSession,
    limit: int = 50,
    offset: int = 0,
    profile: Optional[str] = None,
    action: Optional[str] = None,
) -> List[dict]:
    """Return paginated audit records from the database."""
    query = db.query(AuditLogModel)
    if profile:
        query = query.filter(AuditLogModel.use_case_profile == profile)
    if action:
        query = query.filter(AuditLogModel.final_action == action)
    records = query.order_by(AuditLogModel.id.desc()).offset(offset).limit(limit).all()

    result = []
    for r in records:
        result.append({
            "id": r.id,
            "request_id": r.request_id,
            "session_id": r.session_id,
            "timestamp": r.timestamp,
            "use_case_profile": r.use_case_profile,
            "policy_version": r.policy_version,
            "model_id": r.model_id,
            "latency_ms": r.latency_ms,
            "aggregated_severity": r.aggregated_severity,
            "confidence": r.confidence,
            "evidence_status": r.evidence_status,
            "session_risk_before": r.session_risk_before,
            "session_risk_after": r.session_risk_after,
            "final_action": r.final_action,
            "decision_reason": r.decision_reason,
            "signals": json.loads(r.signals_json or "[]"),
        })
    return result

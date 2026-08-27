"""
review_queue.py — Step 12: Human Review Queue (§14)

Purpose: demonstrate high-stakes + uncertain → human review,
NOT uncertain → automatic block.

ReviewQueueItem has all 11 fields from §14.
Reviewer actions: Approve / Edit / Reject.
"""

from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from backend.core.schemas import ReviewQueueItem, RiskSignal
from backend.db.database import ReviewQueueModel


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue(
    session_id: str,
    request: str,
    model_output: str,
    use_case_profile: str,
    policy_version: str,
    risk_signals: List[RiskSignal],
    session_risk: float,
    escalation_reason: str,
    recommended_action: str,
    db: DBSession,
) -> ReviewQueueItem:
    """
    Add a new item to the human review queue with all §14 fields.
    """
    review_id = f"rev_{uuid.uuid4().hex[:8]}"
    created_at = _now_iso()

    item = ReviewQueueItem(
        review_id=review_id,
        session_id=session_id,
        request=request,
        model_output=model_output,
        use_case_profile=use_case_profile,
        policy_version=policy_version,
        risk_signals=risk_signals,
        session_risk=session_risk,
        escalation_reason=escalation_reason,
        recommended_action=recommended_action,
        reviewer_action=None,
        created_at=created_at,
        reviewed_at=None,
    )

    db_item = ReviewQueueModel(
        review_id=review_id,
        session_id=session_id,
        request=request,
        model_output=model_output,
        use_case_profile=use_case_profile,
        policy_version=policy_version,
        risk_signals_json=json.dumps([s.model_dump() for s in risk_signals]),
        session_risk=session_risk,
        escalation_reason=escalation_reason,
        recommended_action=recommended_action,
        reviewer_action=None,
        created_at=created_at,
        reviewed_at=None,
    )
    db.add(db_item)
    db.commit()

    return item


def get_queue(db: DBSession, pending_only: bool = True) -> List[dict]:
    """Return review queue items. pending_only=True filters unreviewed."""
    query = db.query(ReviewQueueModel)
    if pending_only:
        query = query.filter(ReviewQueueModel.reviewer_action.is_(None))
    items = query.order_by(ReviewQueueModel.id.desc()).all()

    result = []
    for r in items:
        result.append({
            "review_id": r.review_id,
            "session_id": r.session_id,
            "request": r.request,
            "model_output": r.model_output,
            "use_case_profile": r.use_case_profile,
            "policy_version": r.policy_version,
            "risk_signals": json.loads(r.risk_signals_json or "[]"),
            "session_risk": r.session_risk,
            "escalation_reason": r.escalation_reason,
            "recommended_action": r.recommended_action,
            "reviewer_action": r.reviewer_action,
            "created_at": r.created_at,
            "reviewed_at": r.reviewed_at,
            "reviewer_note": r.reviewer_note,
        })
    return result


def submit_action(
    review_id: str,
    reviewer_action: str,
    reviewer_note: Optional[str],
    db: DBSession,
) -> Optional[dict]:
    """Record Approve / Edit / Reject for a queue item."""
    valid_actions = {"approve", "edit", "reject"}
    if reviewer_action.lower() not in valid_actions:
        raise ValueError(f"reviewer_action must be one of {valid_actions}")

    record = db.query(ReviewQueueModel).filter(
        ReviewQueueModel.review_id == review_id
    ).first()
    if record is None:
        return None

    record.reviewer_action = reviewer_action.lower()
    record.reviewer_note = reviewer_note
    record.reviewed_at = _now_iso()
    db.commit()

    return {
        "review_id": review_id,
        "reviewer_action": record.reviewer_action,
        "reviewed_at": record.reviewed_at,
        "reviewer_note": reviewer_note,
    }

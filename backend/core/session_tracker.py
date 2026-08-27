"""
session_tracker.py — CORE 4: Session-Level Risk Tracker (§13)

Configurable rolling session-risk score accumulated across turns.
Uses exact decay-weighted formula from §13.
All parameters (decay_factor, risk_weight, session_risk_threshold)
are read from policy config — never hardcoded.

BINDING:
  - Trigger condition: whenever session_risk_new >= session_risk_threshold.
  - NOT a hardcoded "three turns" rule.
  - weighted_turn_risk and session_risk_new use exact variable names from §13.

Formula (§13):
  weighted_turn_risk = risk_score × risk_weight
  session_risk_new = min(1.0, session_risk_old × decay_factor + weighted_turn_risk)
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session as DBSession

from backend.core.schemas import EvaluationPlan, SessionUpdateResult
from backend.db.database import SessionModel, get_db_session


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def get_or_create_session(
    session_id: str,
    profile: str,
    db: DBSession,
) -> SessionModel:
    """Load existing session or create a new one at session_risk=0.0."""
    record = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if record is None:
        record = SessionModel(
            session_id=session_id,
            profile=profile,
            session_risk=0.0,
            turn_count=0,
            history="[]",
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
    return record


def update_session_risk(
    session_id: str,
    profile: str,
    risk_score: float,
    plan: EvaluationPlan,
    db: DBSession,
) -> SessionUpdateResult:
    """
    Apply the §13 decay formula and persist updated session risk.

    Formula (exact from §13):
      weighted_turn_risk = risk_score × risk_weight
      session_risk_new = min(1.0, session_risk_old × decay_factor + weighted_turn_risk)

    All parameters from plan (policy config), not hardcoded.
    """
    import json

    record = get_or_create_session(session_id, profile, db)
    session_risk_before = record.session_risk

    # §13 exact formula
    weighted_turn_risk = risk_score * plan.risk_weight
    session_risk_new = min(
        1.0,
        session_risk_before * plan.decay_factor + weighted_turn_risk
    )

    threshold_crossed = session_risk_new >= plan.session_risk_threshold

    # Update history
    history = json.loads(record.history or "[]")
    history.append({
        "turn": record.turn_count + 1,
        "risk_score": round(risk_score, 4),
        "weighted_turn_risk": round(weighted_turn_risk, 4),
        "session_risk_before": round(session_risk_before, 4),
        "session_risk_after": round(session_risk_new, 4),
        "threshold_crossed": threshold_crossed,
        "timestamp": _now_iso(),
    })

    record.session_risk = round(session_risk_new, 6)
    record.turn_count += 1
    record.history = json.dumps(history)
    record.updated_at = _now_iso()
    db.commit()

    return SessionUpdateResult(
        session_risk_before=session_risk_before,
        session_risk_after=session_risk_new,
        weighted_turn_risk=weighted_turn_risk,
        threshold_crossed=threshold_crossed,
        session_risk_threshold=plan.session_risk_threshold,
    )


def get_session_state(session_id: str, db: DBSession) -> Optional[Dict[str, Any]]:
    """Return full session state dict for API /sessions/{session_id}."""
    import json
    record = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if record is None:
        return None
    return {
        "session_id": record.session_id,
        "profile": record.profile,
        "session_risk": record.session_risk,
        "turn_count": record.turn_count,
        "history": json.loads(record.history or "[]"),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }

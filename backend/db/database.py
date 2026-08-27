"""
database.py — SQLite setup via SQLAlchemy (§18)

Tables:
  - audit_log    — full audit records (§15)
  - review_queue — human review items (§14)
  - sessions     — session risk state (§13)
"""

from __future__ import annotations
import os
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ---------------------------------------------------------------------------
# Database location
# ---------------------------------------------------------------------------
_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "controlplane.db"
)
_DB_URL = f"sqlite:///{os.path.abspath(_DB_PATH)}"

engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String, index=True)
    session_id = Column(String, index=True)
    timestamp = Column(String)
    use_case_profile = Column(String, index=True)
    policy_version = Column(String)
    model_id = Column(String)
    latency_ms = Column(Float)
    signals_json = Column(Text)          # List[RiskSignal] as JSON
    aggregated_severity = Column(String, index=True)
    confidence = Column(Float)
    evidence_status = Column(String)
    session_risk_before = Column(Float)
    session_risk_after = Column(Float)
    final_action = Column(String, index=True)
    decision_reason = Column(Text)


class ReviewQueueModel(Base):
    __tablename__ = "review_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(String, unique=True, index=True)
    session_id = Column(String, index=True)
    request = Column(Text)
    model_output = Column(Text)
    use_case_profile = Column(String)
    policy_version = Column(String)
    risk_signals_json = Column(Text)     # List[RiskSignal] as JSON
    session_risk = Column(Float)
    escalation_reason = Column(Text)
    recommended_action = Column(String)
    reviewer_action = Column(String, nullable=True)
    created_at = Column(String)
    reviewed_at = Column(String, nullable=True)
    reviewer_note = Column(Text, nullable=True)


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, unique=True, index=True)
    profile = Column(String)
    session_risk = Column(Float, default=0.0)
    turn_count = Column(Integer, default=0)
    history = Column(Text, default="[]")  # JSON list of per-turn records
    created_at = Column(String)
    updated_at = Column(String)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_db_session() -> Session:
    """Dependency injection helper — returns a new DB session."""
    return SessionLocal()

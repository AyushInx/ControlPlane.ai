"""
main.py — Step 1: FastAPI Backend (§16, §25)

Pipeline order inside POST /evaluate (per §16 architecture):
  Input + Use-Case Context
    → Policy Engine (→ EvaluationPlan)
    → Pre-flight checks (injection + PII on prompt)
    → [Mock] Foundation Model (output provided in request)
    → Output interception
    → Parallel evaluators (per EvaluationPlan)
    → Risk Signal Normalization (§8 schema — done by each evaluator)
    → Risk Aggregator (§10)
    → Session Risk State update (§13)
    → Decision Engine (§11)
    → Allow / Modify / Flag / Human Review / Block
    → Audit + Explanation (§15)

NOTE: Pre-flight and output-stage PII checks share one pii_evaluator instance (§16).
"""

from __future__ import annotations
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session as DBSession

from backend.core.schemas import (
    EvaluationRequest, EvaluationResponse, ReviewActionRequest,
    AggregatedResult, DecisionResult
)
from backend.core import policy_engine, risk_aggregator, decision_engine
from backend.core import audit_logger, review_queue, session_tracker
from backend.core.pii_evaluator import PIIEvaluator
from backend.core.groundedness_evaluator import GroundednessEvaluator
from backend.core.safety_evaluator import SafetyEvaluator
from backend.core.injection_evaluator import InjectionEvaluator
from backend.core.evaluator_base import EvalContext
from backend.db.database import init_db, get_db_session
from backend.demos import scenarios as demo_scenarios

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ControlPlane.ai",
    description=(
        "Context-aware, uncertainty-aware AI risk decision layer "
        "for enterprise foundation-model deployments. "
        "Round 2 — Accenture Innovation Challenge 2026."
    ),
    version="0.1-demo",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Evaluator registry (shared instances — §16: one PII detector for both stages)
# ---------------------------------------------------------------------------
_EVALUATORS = {
    "pii": PIIEvaluator(),
    "groundedness": GroundednessEvaluator(),
    "safety": SafetyEvaluator(),
    "injection": InjectionEvaluator(),
}


@app.on_event("startup")
def on_startup():
    init_db()


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------
def get_db():
    db = get_db_session()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Core pipeline function (shared by /evaluate and /demos endpoints)
# ---------------------------------------------------------------------------

def run_pipeline(
    req: EvaluationRequest,
    db: DBSession,
    injected_signals: list = None,  # pre-computed signals for deterministic demos
) -> EvaluationResponse:
    start_time = time.time()
    request_id = req.request_id or f"req_{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now(timezone.utc).isoformat()

    # ── CORE 1: Policy Engine ───────────────────────────────────────────────
    policy = policy_engine.get_active_policy(req.profile)
    plan = policy_engine.derive_evaluation_plan(policy)

    # ── Evaluation context ──────────────────────────────────────────────────
    ctx = EvalContext(
        prompt=req.prompt,
        model_output=req.model_output,
        trusted_evidence=req.trusted_evidence,
        plan=plan,
        session_id=req.session_id,
        request_id=request_id,
    )

    # ── Pre-flight checks (on prompt) ───────────────────────────────────────
    preflight_signals = []
    if "injection" in plan.enabled_evaluators:
        preflight_signals.extend(
            _EVALUATORS["injection"].evaluate(ctx, stage="preflight")
        )
    if "pii" in plan.enabled_evaluators:
        preflight_signals.extend(
            _EVALUATORS["pii"].evaluate(ctx, stage="preflight")
        )

    # ── Output evaluation ───────────────────────────────────────────────────
    output_signals = []
    for evaluator_name in plan.enabled_evaluators:
        evaluator = _EVALUATORS.get(evaluator_name)
        if evaluator is not None:
            sigs = evaluator.evaluate(ctx, stage="output")
            output_signals.extend(sigs)

    all_signals = preflight_signals + output_signals

    # If injected_signals provided (deterministic demo mode), use them instead.
    # This implements "no reliance on a live model happening to fail in a specific way" (§25).
    if injected_signals:
        from backend.core.schemas import RiskSignal as RS
        all_signals = [RS(**s) if isinstance(s, dict) else s for s in injected_signals]

    # ── Risk Aggregation (§10) ──────────────────────────────────────────────
    aggregated = risk_aggregator.aggregate(all_signals, plan)

    # ── Session Risk Update (§13) ────────────────────────────────────────────
    dominant_score = (
        aggregated.dominant_signal.risk_score
        if aggregated.dominant_signal else 0.0
    )
    session_update = session_tracker.update_session_risk(
        session_id=req.session_id,
        profile=req.profile,
        risk_score=dominant_score,
        plan=plan,
        db=db,
    )

    # ── Decision Engine (§11) ───────────────────────────────────────────────
    decision = decision_engine.decide(
        aggregated=aggregated,
        plan=plan,
        session_risk_before=session_update.session_risk_before,
        session_risk_after=session_update.session_risk_after,
    )

    latency_ms = (time.time() - start_time) * 1000

    # ── Audit Logger (§15) ──────────────────────────────────────────────────
    audit_record = audit_logger.write_audit_record(
        request_id=request_id,
        session_id=req.session_id,
        profile=req.profile,
        plan=plan,
        model_id=req.model_id,
        latency_ms=latency_ms,
        aggregated=aggregated,
        session_update=session_update,
        decision=decision,
        timestamp=timestamp,
        db=db,
    )

    # ── Human Review Queue (§14) ────────────────────────────────────────────
    rq_item = None
    if decision.action == "human_review":
        escalation_reason = decision.reason
        rq_item = review_queue.enqueue(
            session_id=req.session_id,
            request=req.prompt,
            model_output=req.model_output,
            use_case_profile=req.profile,
            policy_version=plan.policy_version,
            risk_signals=aggregated.signals,
            session_risk=session_update.session_risk_after,
            escalation_reason=escalation_reason,
            recommended_action="human_review",
            db=db,
        )

    return EvaluationResponse(
        request_id=request_id,
        session_id=req.session_id,
        profile=req.profile,
        decision=decision,
        signals=aggregated.signals,
        aggregated_severity=aggregated.aggregated_severity,
        session_risk_before=session_update.session_risk_before,
        session_risk_after=session_update.session_risk_after,
        audit_record=audit_record,
        review_queue_item=rq_item,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/evaluate", response_model=EvaluationResponse, tags=["Core"])
def evaluate(req: EvaluationRequest, db: DBSession = Depends(get_db)):
    """
    Main evaluation endpoint.
    Accepts request + use-case profile, runs full pipeline,
    returns decision + audit record.
    """
    return run_pipeline(req, db)


@app.get("/sessions/{session_id}", tags=["Core"])
def get_session(session_id: str, db: DBSession = Depends(get_db)):
    """Return session risk state for a given session_id."""
    state = session_tracker.get_session_state(session_id, db)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return state


@app.get("/audit", tags=["Audit"])
def get_audit(
    limit: int = 50,
    offset: int = 0,
    profile: Optional[str] = None,
    action: Optional[str] = None,
    db: DBSession = Depends(get_db),
):
    """Paginated audit log. Filterable by profile and/or action."""
    return audit_logger.get_audit_log(db, limit=limit, offset=offset, profile=profile, action=action)


@app.get("/review-queue", tags=["Review"])
def get_review_queue(pending_only: bool = True, db: DBSession = Depends(get_db)):
    """Return pending human review items (all 11 §14 fields)."""
    return review_queue.get_queue(db, pending_only=pending_only)


@app.patch("/review-queue/{review_id}", tags=["Review"])
def submit_review(
    review_id: str,
    body: ReviewActionRequest,
    db: DBSession = Depends(get_db),
):
    """Submit reviewer action: approve / edit / reject."""
    result = review_queue.submit_action(
        review_id=review_id,
        reviewer_action=body.reviewer_action,
        reviewer_note=body.reviewer_note,
        db=db,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Review item '{review_id}' not found")
    return result


@app.get("/policy", tags=["Policy"])
def get_policy():
    """Return current active policy YAML (all profiles, read-only)."""
    return {
        "policy_version": policy_engine.get_policy_version(),
        "profiles": policy_engine.get_all_profiles(),
    }


@app.get("/demos", tags=["Demos"])
def list_demos():
    """List all available demo scenarios."""
    return demo_scenarios.list_scenarios()


@app.post("/demos/{scenario_id}", tags=["Demos"])
def run_demo(scenario_id: int, db: DBSession = Depends(get_db)):
    """
    Run a deterministic demo scenario (1–5).
    All scenarios are hardcoded and reproducible on repeat runs.
    """
    scenario = demo_scenarios.get_scenario(scenario_id)
    results = []

    if scenario_id == 5:
        # Multi-turn scenario — inject exact per-turn risk_scores from §19
        # to guarantee session formula produces 0.28 → 0.41 → 0.60 exactly.
        turns = scenario["turns"]
        profile = scenario["profile"]
        session_id = scenario["session_id"]
        for turn_data in turns:
            req = EvaluationRequest(
                session_id=session_id,
                profile=profile,
                prompt=turn_data["prompt"],
                model_output=turn_data["model_output"],
                trusted_evidence=turn_data.get("trusted_evidence"),
                model_id=turn_data.get("model_id", "mock-llm-v1"),
            )
            # Inject a signal with the exact risk_score from §13 illustrative trace
            exact_risk_score = turn_data.get("injected_risk_score", 0.40)
            injected = [{
                "risk_type": "hallucination",
                "risk_score": exact_risk_score,
                "severity": "MEDIUM" if exact_risk_score < 0.60 else "HIGH",
                "confidence": 0.38,
                "evidence_status": "UNSUPPORTED",
                "verified": False,
                "evidence": [],
                "overlaps_with": [],
                "reason": f"[Demo 5 Turn {turn_data['turn']} — Deterministic] "
                           f"Claim could not be verified. risk_score={exact_risk_score} per §13 illustrative trace.",
            }]
            result = run_pipeline(req, db, injected_signals=injected)
            results.append({
                "turn": turn_data["turn"],
                "response": result.model_dump(),
                "expected": {
                    "session_risk_after": turn_data.get("expected_session_risk_after"),
                    "action": turn_data.get("expected_action"),
                    "rule": turn_data.get("expected_rule"),
                },
            })

    if scenario_id == 1:
        # Demo 1: use injected_signals for deterministic outcome
        injected = scenario.get("injected_signals", [])
        for run_data in scenario["runs"]:
            req = EvaluationRequest(
                session_id=run_data["session_id"],
                profile=run_data["profile"],
                prompt=run_data["prompt"],
                model_output=run_data["model_output"],
                trusted_evidence=run_data.get("trusted_evidence"),
                model_id=run_data.get("model_id", "mock-llm-v1"),
            )
            result = run_pipeline(req, db, injected_signals=injected)
            results.append({
                "profile": run_data["profile"],
                "response": result.model_dump(),
                "expected": {
                    "action": run_data.get("expected_action"),
                    "rule": run_data.get("expected_rule"),
                    "severity": run_data.get("expected_severity"),
                },
            })

    elif scenario_id == 3:
        # Demo 3: Safety floor — runs live (safety evaluator will produce CRITICAL + high conf)
        for run_data in scenario["runs"]:
            req = EvaluationRequest(
                session_id=run_data["session_id"],
                profile=run_data["profile"],
                prompt=run_data["prompt"],
                model_output=run_data["model_output"],
                trusted_evidence=run_data.get("trusted_evidence"),
                model_id=run_data.get("model_id", "mock-llm-v1"),
            )
            result = run_pipeline(req, db)
            results.append({
                "profile": run_data["profile"],
                "response": result.model_dump(),
            })

    elif scenario_id in (2, 4):
        # Single or labeled runs
        for run_data in scenario["runs"]:
            req = EvaluationRequest(
                session_id=run_data["session_id"],
                profile=run_data["profile"],
                prompt=run_data["prompt"],
                model_output=run_data["model_output"],
                trusted_evidence=run_data.get("trusted_evidence"),
                model_id=run_data.get("model_id", "mock-llm-v1"),
            )
            result = run_pipeline(req, db)
            results.append({
                "label": run_data.get("label", run_data.get("profile")),
                "response": result.model_dump(),
            })

    return {
        "scenario_id": scenario_id,
        "name": scenario["name"],
        "description": scenario["description"],
        "results": results,
    }


@app.get("/health", tags=["System"])
def health():
    return {
        "status": "ok",
        "policy_version": policy_engine.get_policy_version(),
        "version": "0.1-demo",
    }

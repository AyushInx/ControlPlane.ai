"""
policy_engine.py — CORE 1: Context-Aware Policy Engine (§6, §16)

Loads policy.yaml, caches it with version tracking, and derives the
EvaluationPlan (which evaluators run, at what depth, plus decision thresholds).

BINDING: Never branches on profile name in application logic.
         get_active_policy() reads config only.
         EvaluationPlan carries BOTH evaluator list/depth AND decision thresholds.

FIX NOTES (this revision) — see ANALYSIS_AND_FIXES.md:
  - Policy YAML used to be cached forever after the first read (the
    docstring even said so: "Re-reads on first call only") — editing
    policy.yaml while the process was running had no effect until a full
    restart. It's now reloaded automatically whenever the file's mtime
    changes (one cheap stat() call per lookup), so policy edits take effect
    on the next request without a restart.
  - `high_confidence_threshold` is now read per-profile (falling back to
    0.65 if a profile's YAML entry omits it) and threaded through
    EvaluationPlan — see decision_engine.py for why this was the one major
    decision input that wasn't previously policy-driven.
  - Removed an unused `from functools import lru_cache` import — nothing in
    this file used it (and applying it to get_active_policy would actually
    have defeated the mtime-reload fix above, by caching stale
    UseCasePolicy objects independently of the file-content cache below).
"""

from __future__ import annotations
import os
import yaml
from typing import Dict, Any

from backend.core.schemas import UseCasePolicy, EvaluationPlan

# ---------------------------------------------------------------------------
# Policy file location
# ---------------------------------------------------------------------------

_POLICY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "policy.yaml"
)

# ---------------------------------------------------------------------------
# Load + cache, reloading whenever the file's mtime changes
# ---------------------------------------------------------------------------

_policy_cache: Dict[str, Any] = {}
_policy_version: str = ""
_policy_mtime: float = 0.0


def _load_policy_file() -> Dict[str, Any]:
    """Load and cache policy YAML, reloading automatically on file change."""
    global _policy_cache, _policy_version, _policy_mtime

    try:
        current_mtime = os.path.getmtime(_POLICY_PATH)
    except OSError:
        # File transiently unavailable — serve what's cached, if anything.
        current_mtime = _policy_mtime

    if not _policy_cache or current_mtime != _policy_mtime:
        with open(_POLICY_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        _policy_version = raw.get("policy_version", "unknown")
        _policy_cache = raw
        _policy_mtime = current_mtime

    return _policy_cache


def get_policy_version() -> str:
    _load_policy_file()
    return _policy_version


def get_all_profiles() -> Dict[str, Any]:
    """Return the raw policy dict for all profiles (for API /policy endpoint)."""
    return _load_policy_file()


# ---------------------------------------------------------------------------
# CORE 1 API
# ---------------------------------------------------------------------------

def get_active_policy(profile_name: str) -> UseCasePolicy:
    """
    Load active policy for a named profile.
    BINDING: Reads config only — never branches on profile_name in logic.
    """
    raw = _load_policy_file()
    policy_version = raw.get("policy_version", "unknown")

    if profile_name not in raw:
        available = [k for k in raw.keys() if k != "policy_version"]
        raise ValueError(
            f"Unknown profile '{profile_name}'. Available: {available}"
        )

    p = raw[profile_name]
    return UseCasePolicy(
        profile_name=profile_name,
        risk_tolerance=p["risk_tolerance"],
        latency_budget_ms=p["latency_budget_ms"],
        evaluation_depth=p["evaluation_depth"],
        enabled_evaluators=p["enabled_evaluators"],
        low_confidence_action=p["low_confidence_action"],
        human_review_threshold=p["human_review_threshold"],
        block_threshold=p["block_threshold"],
        session_risk_threshold=p["session_risk_threshold"],
        high_confidence_threshold=p.get("high_confidence_threshold", 0.65),
        decay_factor=p["decay_factor"],
        risk_weight=p["risk_weight"],
        safety_floor=p["safety_floor"],
        safety_floor_confidence_threshold=p.get("safety_floor_confidence_threshold", 0.80),
        safety_floor_categories=p.get("safety_floor_categories", []),
        policy_version=policy_version,
    )


def derive_evaluation_plan(policy: UseCasePolicy) -> EvaluationPlan:
    """
    Derive the full EvaluationPlan from a UseCasePolicy (§6, §16).

    evaluation_depth drives real behavior — it is not just a label:
      fast     → deterministic PII patterns, safety heuristic, injection heuristic.
                 No evidence retrieval, no NER pass. Minimal latency.
      standard → everything in fast + groundedness/evidence retrieval when source available,
                 + PII NER pass.
      deep     → same evaluator set as standard; each evaluator that has a tunable
                 thoroughness knob uses it (e.g. groundedness analyzes more claims
                 per turn — see groundedness_evaluator._max_claims_for_depth).

    Evaluator-SET parity between "standard" and "deep" is intentional: this
    system has four evaluator types today, and all four already run at both
    tiers. "deep" instead asks each evaluator to work harder where it can,
    rather than running different evaluators altogether.

    The EvaluationPlan carries BOTH:
      - Which evaluators run and at what depth
      - The decision thresholds those evaluators will be judged against
    """
    depth = policy.evaluation_depth
    requested = set(policy.enabled_evaluators)

    # Depth controls which evaluators are eligible at all (§6)
    if depth == "fast":
        # fast: pii, safety, injection only — no groundedness
        eligible = {"pii", "safety", "injection"}
    elif depth == "standard":
        # standard: fast + groundedness
        eligible = {"pii", "safety", "injection", "groundedness"}
    else:
        # deep: all
        eligible = {"pii", "safety", "injection", "groundedness"}

    # Final evaluator list = intersection of requested and eligible
    active_evaluators = list(requested & eligible)

    return EvaluationPlan(
        profile_name=policy.profile_name,
        enabled_evaluators=active_evaluators,
        evaluation_depth=depth,
        latency_budget_ms=policy.latency_budget_ms,
        human_review_threshold=policy.human_review_threshold,
        block_threshold=policy.block_threshold,
        session_risk_threshold=policy.session_risk_threshold,
        high_confidence_threshold=policy.high_confidence_threshold,
        low_confidence_action=policy.low_confidence_action,
        safety_floor=policy.safety_floor,
        safety_floor_confidence_threshold=policy.safety_floor_confidence_threshold,
        safety_floor_categories=policy.safety_floor_categories,
        decay_factor=policy.decay_factor,
        risk_weight=policy.risk_weight,
        policy_version=policy.policy_version,
    )

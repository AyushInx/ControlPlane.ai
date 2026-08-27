"""
evaluator_base.py — Shared evaluator interface (§8, Step 3)

All evaluators inherit BaseEvaluator and implement evaluate().
The common contract ensures every evaluator emits List[RiskSignal]
conforming to the §8 schema.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional

from backend.core.schemas import RiskSignal, EvaluationPlan


class EvalContext:
    """
    Context passed to every evaluator.
    Contains the full request context needed for evaluation.
    """
    def __init__(
        self,
        prompt: str,
        model_output: str,
        trusted_evidence: Optional[str],
        plan: EvaluationPlan,
        session_id: str,
        request_id: str,
    ):
        self.prompt = prompt
        self.model_output = model_output
        self.trusted_evidence = trusted_evidence   # None → Case B (UNSUPPORTED)
        self.plan = plan
        self.session_id = session_id
        self.request_id = request_id


class BaseEvaluator(ABC):
    """
    Abstract base for all evaluators.
    All evaluators conform to this interface (§8, §25 Step 3).

    BINDING CONSTRAINTS on all implementations:
      - Return List[RiskSignal] using the §8 schema (all 9 fields).
      - Never multiply risk_score × confidence.
      - Never write evidence_status=UNSUPPORTED as FALSE.
      - Use score_to_severity() for severity bands.
    """

    @abstractmethod
    def evaluate(
        self,
        context: EvalContext,
        stage: str = "output",  # "preflight" | "output"
    ) -> List[RiskSignal]:
        """
        Run evaluation and return risk signals.

        Args:
            context: Full evaluation context (prompt, output, evidence, plan).
            stage: "preflight" to evaluate the incoming prompt;
                   "output" to evaluate the model output.

        Returns:
            List of RiskSignal conforming to §8.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Evaluator identifier (matches enabled_evaluators list in policy)."""
        ...

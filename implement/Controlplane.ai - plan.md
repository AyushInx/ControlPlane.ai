*A context-aware, uncertainty-aware AI risk decision layer for enterprise foundation-model deployments.*
*Round 2 — Accenture Innovation Challenge 2026*

---

## 1. Executive Summary

ControlPlane.ai sits between enterprise applications and foundation models (GPT, Claude, Llama, or any API-served model) and turns AI oversight into a decision problem, not just a detection problem. Every model output is evaluated for risk — hallucination, PII/privacy exposure, unsafe content — but risk detection is never the final word. ControlPlane separates **how severe a risk would be** from **how confident it is in that assessment**, checks what **evidence** actually supports the claim, and combines all of that with the **use case's policy** to produce an explainable, auditable action: allow, modify, flag, escalate to human review, or block.

The same underlying framework runs for every use case. What changes is configuration, not code — a customer-facing chatbot, an internal copilot, and a regulated decision-support tool each get different thresholds, different evaluation depth, and different behavior under uncertainty, from the same pipeline.

## 2. Problem

Enterprises run generative AI across many use cases simultaneously — customer-facing chatbots, internal copilots, decision-support tools embedded in regulated workflows — and each carries a different risk signature depending on the model, the data it draws on, and how its output is used downstream. AI systems can fail silently: producing outputs that look reliable but are fabricated, biased, privacy-leaking, or simply wrong, discovered only after a user or downstream process has already acted on them.

A single, one-size-fits-all checking approach does not fit this reality. Different use cases have different risk tolerance and latency budgets. Hallucination, bias, and privacy risk frequently overlap in the same output. There is often no reliable real-time ground truth to verify a claim against. Over-flagging causes alert fatigue and encourages bypassing; under-flagging creates real liability. Multi-turn conversations and AI agents compound risk across turns. Regulatory expectations vary and evolve. And because enterprises consume foundation models via API rather than owning them, any checking layer fundamentally operates at the input/output boundary, not inside the model.

## 3. Round 2 Design Thesis

**The same underlying control framework behaves differently depending on use-case context.**

The same AI output may be:
- allowed with a caveat for an internal copilot,
- softened/edited for a customer-facing chatbot,
- routed to human review for a regulated decision-support tool.

This behavior is driven entirely by **policy and configuration** — risk tolerance, evaluation depth, latency budget, intervention strategy, low-confidence behavior, and human-review requirements are all policy outputs, not hardcoded branches per use case.

ControlPlane.ai is a decision layer — not a generic LLM observability platform, a general-purpose moderation system, a compliance engine, a foundation model, a chatbot, or a model-training platform. It governs how outputs from any of those systems get released, using context and evidence.

ControlPlane.ai does not claim to have invented configurable guardrails — configurable thresholds and tiered actions exist elsewhere. Its novelty is in the **combination**:

1. Context-aware policy that changes evaluation depth and intervention, not just a threshold
2. Strict separation of **risk severity** from **assessment confidence**
3. Evidence-aware reasoning that never treats absence of evidence as proof of falsehood
4. Uncertainty-aware decisions — confidence and evidence status are first-class decision inputs
5. Overlapping-risk handling that preserves each finding instead of collapsing them
6. Session-level cumulative risk across multi-turn interactions
7. Fully explainable, auditable decisions tied to a versioned policy

## 4. Core Principles

Binding on every component described below:

- Use-case behavior comes from **configuration**, never hardcoded per-profile branches in application code.
- **Risk severity and assessment confidence are separate values and are never multiplied or otherwise collapsed into one number.** Confidence describes how much to trust the assessment; it does not shrink or inflate the risk itself. **Low confidence ≠ low risk.**
- **UNKNOWN is not FALSE.** Absence of evidence is a distinct state from contradicted or unsafe content.
- Evidence is optional. The system must degrade gracefully — into an explicit uncertainty state — when no reliable evidence exists, rather than guessing.
- A risk type (e.g., PII) is never special-cased into an automatic action; every signal, regardless of type, is routed through the same severity/confidence/evidence-driven Decision Engine, with only a narrow, explicitly configured Safety Floor as the exception.
- Every decision produces a human-readable explanation and records the policy version that produced it.
- Session-level risk state is tracked separately from per-turn risk signals, using a configurable, non-hardcoded accumulation rule.
- Overlapping risk signals are preserved individually; they are never blindly summed.
- The prototype makes no production-grade accuracy claims. Thresholds and accumulation values are illustrative and clearly labeled as such.
- Demo scenarios are deterministic and reproducible — no reliance on a live model happening to fail in a specific way.
- The system stays simple enough to run locally as a hackathon prototype.

## 5. Context / Use-Case Profiles

Three illustrative profiles, matching the reference use cases in the official problem statement.

### Customer-Facing Chatbot
| Attribute | Value |
|---|---|
| Risk tolerance | Low (external-facing, reputational exposure) |
| Latency budget | Tight — fast checks only |
| Evaluation depth | `fast` — deterministic/lightweight checks prioritized; evidence retrieval skipped |
| Low-confidence behavior | Edit/soften rather than hard-block, to protect UX |
| Human-review threshold | High — reserved for clear, high-confidence violations |
| Block threshold | High — hard blocks are the exception |
| Intervention strategy | Edit first, escalate rarely |
| Safety floor | Always active |

### Internal Copilot
| Attribute | Value |
|---|---|
| Risk tolerance | Medium — a human employee is already in the loop |
| Latency budget | Relaxed |
| Evaluation depth | `standard` — fast checks plus evidence retrieval when available |
| Low-confidence behavior | Allow with a visible caveat/flag; let the employee judge |
| Human-review threshold | Moderate |
| Block threshold | High, but flags/caveats are frequent |
| Intervention strategy | Inform, don't obstruct |
| Safety floor | Always active |

### Regulated Decision-Support
| Attribute | Value |
|---|---|
| Risk tolerance | Very low — consequential, compliance-relevant decisions |
| Latency budget | Loose — deeper evaluation is acceptable |
| Evaluation depth | `deep` — full evidence evaluation, all evaluators run |
| Low-confidence behavior | Human review by default — uncertainty on a consequential claim is itself the trigger |
| Human-review threshold | Low — escalates easily |
| Block threshold | Lower than other profiles |
| Intervention strategy | Human review is the default path for anything not clearly clean |
| Safety floor | Always active |

## 6. Policy Model

Policy is versioned configuration, not code. The Decision Engine reads active policy at request time; it never branches on use-case name directly. Policy determines risk tolerance, latency budget, evaluation depth, which evaluators run, low-confidence behavior, human-review and block thresholds, session-risk parameters, and safety-floor participation.

```yaml
policy_version: v0.1-demo

customer_facing_chatbot:
  risk_tolerance: low
  latency_budget_ms: 300
  evaluation_depth: fast
  enabled_evaluators: [pii, safety, injection]
  low_confidence_action: edit_soften
  human_review_threshold: 0.65
  block_threshold: 0.85
  session_risk_threshold: 0.70
  decay_factor: 0.6
  risk_weight: 0.7
  safety_floor: true

internal_copilot:
  risk_tolerance: medium
  latency_budget_ms: 1500
  evaluation_depth: standard
  enabled_evaluators: [pii, safety, groundedness]
  low_confidence_action: allow_with_flag
  human_review_threshold: 0.80
  block_threshold: 0.90
  session_risk_threshold: 0.75
  decay_factor: 0.6
  risk_weight: 0.7
  safety_floor: true

regulated_decision_support:
  risk_tolerance: very_low
  latency_budget_ms: 5000
  evaluation_depth: deep
  enabled_evaluators: [pii, safety, groundedness, injection]
  low_confidence_action: human_review
  human_review_threshold: 0.40
  block_threshold: 0.75
  session_risk_threshold: 0.60
  decay_factor: 0.6
  risk_weight: 0.7
  safety_floor: true
```

**Illustrative prototype policy thresholds — intended for demonstration and calibration, not production risk calibration.**

### Evaluation Depth

`evaluation_depth` is a real mechanism, not a label — it changes which evaluators actually run and how much analysis each performs:

- **fast** — deterministic PII patterns, safety heuristic, prompt-injection heuristic. Minimal latency; no evidence retrieval.
- **standard** — everything in `fast`, plus groundedness/evidence retrieval when a source document is available.
- **deep** — all applicable evaluators, evidence retrieval, stronger claim-level analysis, additional verification passes where practical.

```
Use-Case Context
      |
      v
Policy Engine
      |
      v
Evaluation Plan   (which evaluators run, at what depth - derived from
      |             evaluation_depth + enabled_evaluators)
      v
Evaluators
      |
      v
Risk Signals
      |
      v
Decision
```

`latency_budget_ms` is a target evaluation budget that motivates this choice of depth — not a guarantee that every evaluator completes within that window.

## 7. Epistemic Boundary

ControlPlane distinguishes what it knows from what it merely infers. Every risk assessment carries an `evidence_status`:

- **SUPPORTED** — available evidence backs the claim
- **CONTRADICTED** — available evidence conflicts with the claim
- **PARTIALLY_SUPPORTED** — evidence backs part of the claim, or backs it with caveats
- **UNSUPPORTED** (used interchangeably with **UNKNOWN** throughout this document) — no reliable evidence is available
- **NOT_APPLICABLE** — evidence-based verification doesn't apply to this risk type (e.g., a PII pattern match doesn't need external evidence)

**UNKNOWN is not FALSE.** The absence of supporting evidence does not mean a claim is wrong — it means ControlPlane cannot verify it either way. ControlPlane never presents uncertainty as factual verification.

This is a core design principle, not an edge case. It is the direct answer to the Round 2 complexity that reliable real-time ground truth often does not exist.

## 8. Risk Signal Model

Every evaluator emits a signal in this shape:

```json
{
  "risk_type": "hallucination",
  "risk_score": 0.72,
  "severity": "HIGH",
  "confidence": 0.31,
  "evidence_status": "UNSUPPORTED",
  "verified": false,
  "evidence": [],
  "overlaps_with": ["privacy"],
  "reason": "Claim could not be verified against available evidence"
}
```

| Field | Meaning |
|---|---|
| `risk_type` | Category of risk (extensible — MVP implements `pii`, `hallucination`, `safety`, `prompt_injection`) |
| `risk_score` | Normalized severity score, 0.0-1.0, describing how severe the risk would be **if the assessment is correct**. **Independent of confidence — never confidence-adjusted.** |
| `severity` | Categorical interpretation of `risk_score`: `LOW` (0.00-0.29) / `MEDIUM` (0.30-0.59) / `HIGH` (0.60-0.79) / `CRITICAL` (0.80-1.00). **Illustrative prototype bands, not scientifically calibrated.** |
| `confidence` | How confident the evaluator is that its own assessment is correct, 0.0-1.0 — a separate dimension from severity |
| `evidence_status` | `SUPPORTED` / `CONTRADICTED` / `PARTIALLY_SUPPORTED` / `UNSUPPORTED` / `NOT_APPLICABLE` — see Section 7 |
| `verified` | `true` only when sufficient trusted evidence exists for this specific assessment; `false` otherwise, including all `UNSUPPORTED` cases |
| `evidence` | Source snippets/citations backing the assessment, if any |
| `overlaps_with` | Other risk types this same finding also implicates |
| `reason` | Short human-readable explanation of the assessment |

**Confidence qualifies the reliability of the risk assessment; it does not reduce the underlying severity of the risk.**

`risk_score = 0.90, confidence = 0.25` must **not** become `risk = 0.225`. It means: *potentially severe risk, but low confidence in the assessment.* The policy layer decides what to do with that combination — not the signal itself.

**UNSUPPORTED ≠ FALSE. UNKNOWN ≠ FALSE. LOW CONFIDENCE ≠ LOW RISK.**

## 9. Detection & Evaluation

Four evaluator modules produce risk signals. All operate at the input/output layer — none require access to model internals, consistent with API-only foundation-model access.

**PII/Entity Detector** — combines two detection strategies with different confidence characteristics:
- High-specificity deterministic patterns (e.g., SSN-like formats, credit-card-like formats) → high confidence by construction.
- NER-based entity inference (e.g., person names, organizations) → probabilistic confidence, generally lower than pattern matches.

A PII finding is a risk signal like any other: it carries severity, confidence, and evidence_status, and is routed through the same policy-driven Decision Engine (Section 11) as any other risk type. Routine PII findings follow normal profile behavior (Detect → Redact → Allow, per policy). **PII detection does not automatically mean Block** — only specific, policy-defined critical categories (e.g., credential/secret exposure) invoke the Safety Floor (Section 12).

**Groundedness/Evidence Evaluator** — the hallucination check, and the direct answer to "no reliable ground truth":
- **Case A — trusted evidence exists:** claim extraction → evidence retrieval → evidence comparison → `SUPPORTED` / `CONTRADICTED` / `PARTIALLY_SUPPORTED`, via embedding similarity + lightweight NLI. This is deterministic and reproducible, and is the primary implementation.
- **Case B — no reliable evidence exists:** → `UNSUPPORTED`. ControlPlane does not say "no source found, therefore hallucination" — it says *"claim could not be verified against available evidence."* Confidence reflects assessment uncertainty, not claim truth.

An **AI-as-judge** pass is an optional additional heuristic (a second model call assessing plausibility/self-consistency), explicitly labeled `"model-based heuristic assessment"` in the evidence record. It is **never treated as ground truth** and can never set `evidence_status` to `SUPPORTED` — it can only adjust confidence within the `UNSUPPORTED` state. The prototype's core groundedness mechanism (Case A/B above) works without depending on an AI judge; the judge is an optional enhancement, not a dependency.

**Safety/Toxicity Evaluator** — heuristic/classifier-based check for clearly unsafe or policy-violating content. The underlying classifiers are probabilistic; high-confidence hits at `CRITICAL` severity are what can trigger the Safety Floor (Section 12).

**Prompt-Injection Heuristic** — pre-flight check on the incoming prompt, plus a lightweight re-check on the output for injected-instruction leakage.

## 10. Risk Aggregation

Signals are never summed. `hallucination: risk_score=0.8` + `privacy: risk_score=0.8` does **not** become `1.6`. Both findings are preserved individually.

**Prototype aggregation procedure (deterministic, not statistically sophisticated):**

1. Normalize every evaluator's output into the common risk signal schema (Section 8).
2. Group findings by `risk_type`.
3. Preserve the highest relevant `severity` per risk type — never averaged or summed away.
4. Preserve `confidence` separately from severity throughout.
5. Identify the dominant, policy-relevant risk (the signal driving the current decision tier).
6. Apply any configured interaction/override rules (e.g., Safety Floor categories — Section 12).
7. Produce an explainable decision, listing all contributing signals and which one dominated.

Signals sharing an `overlaps_with` relationship are **linked, not merged** — both appear in the decision record, and resolving one (e.g., redacting a fabricated personal detail) is understood to address both.

**The aggregated result is a decision-support signal, not a calibrated probability of harm.**

## 11. Decision Engine

```
Decision = f(
    risk severity,
    assessment confidence,
    evidence status,
    use-case context,
    policy,
    session state
)
```

Confidence is an **input to a rule**, never a multiplier on risk. Rules are evaluated in order:

1. **Safety floor check first** (Section 12) — a `CRITICAL` severity, high-confidence signal in a policy-defined safety-floor category overrides everything below.
2. **HIGH or CRITICAL severity + high confidence + evidence CONTRADICTED or clearly policy-violating** → Block or Edit/Redact (action type depends on the risk — exposure-type risks are typically redacted, unsafe-content risks are typically blocked), per `policy.block_threshold`.
3. **HIGH or CRITICAL severity + (low confidence OR evidence_status in {UNSUPPORTED, PARTIALLY_SUPPORTED})** → follow `policy.low_confidence_action` for the active profile. This is where "potentially severe risk, but uncertain" gets resolved — e.g. Regulated → Human Review; Chatbot → edit/soften; Copilot → allow with flag.
4. **MEDIUM severity above `policy.human_review_threshold`** → Flag or Human Review, per profile.
5. **LOW severity** → Allow, but still logged and contributed to session state (Section 13).
6. Session-accumulated risk (Section 13) can escalate an otherwise-Allow decision independent of the current turn's own severity.

**Illustrative outcome table** (actual routing depends on the active profile's configuration — this shows the shape of the logic, not fixed behavior):

| Severity | Confidence | Evidence Status | Typical Region |
|---|---|---|---|
| Critical | High | Contradicted / safety-floor category | Safety floor - Block/Redact, all profiles |
| High | High | Supported/Contradicted | Block or Edit - clear violation |
| High | Low | Unsupported | Escalate per profile - often Human Review |
| Medium | High | Supported | Flag or Edit |
| Medium | Low | Unsupported | Allow-with-caveat or Flag, profile-dependent |
| Low | Any | Any | Allow - logged, feeds session state |

## 12. Safety Floor

Certain high-confidence, policy-defined critical violations can override normal profile behavior.

- **Normal policy:** use-case context determines the intervention for a given severity/confidence/evidence combination (Sections 5-6, 11).
- **Safety floor:** a small, policy-defined set of critical categories — e.g., credential/secret exposure, prohibited unsafe content, other policy-flagged critical sensitive-data exposure — can trigger Block/Redact at `CRITICAL` severity and high confidence, regardless of profile.

Routine risk findings, including most PII detections, are **not** safety-floor cases — they follow normal profile-driven policy like any other risk signal (Sections 9, 11). The safety floor is a narrow, explicitly configured override, not a blanket rule that any PII or any unsafe-content flag bypasses context.

The underlying classifiers remain probabilistic — this does not claim deterministic detection. What is deterministic is the **policy rule**: once a safety-floor category is flagged at sufficient confidence, it is checked first in the Decision Engine (rule 1) and is not subject to profile-specific softening.

## 13. Session-Level Risk

A **configurable rolling session-risk score** accumulates risk signals across turns within a session, tracked separately from per-turn risk, using a decay-weighted running total:

```
weighted_turn_risk = risk_score x risk_weight

session_risk_new = min(
    1.0,
    session_risk_old x decay_factor + weighted_turn_risk
)
```

Where `decay_factor`, `risk_weight`, and `session_risk_threshold` are configurable per policy (Section 6).

**Illustrative trace** (regulated profile: `decay_factor=0.6`, `risk_weight=0.7`, `session_risk_threshold=0.60`):
```
Turn 1: risk_score=0.40 -> weighted=0.28 -> session_risk = 0.00x0.6 + 0.28 = 0.28
Turn 2: risk_score=0.35 -> weighted=0.245 -> session_risk = 0.28x0.6 + 0.245 = 0.41
Turn 3: risk_score=0.50 -> weighted=0.35  -> session_risk = 0.41x0.6 + 0.35  = 0.60
                                                    -> crosses session_risk_threshold -> HUMAN REVIEW
```

This is a prototype accumulation heuristic, not a calibrated probability of future harm. The demo uses a short conversation for convenience — the mechanism itself is threshold- and configuration-driven, **not a hardcoded "three turns" rule**: review triggers whenever accumulated risk crosses the configured `session_risk_threshold`, however many turns that takes.

## 14. Human Review

A real, if lightweight, MVP capability — not just an action label. The purpose is to demonstrate **high-stakes + uncertain → human review**, not **uncertain → automatic block**.

**Review queue item:**
```json
{
  "review_id": "rev_0001",
  "session_id": "sess_042",
  "request": "...",
  "model_output": "...",
  "use_case_profile": "regulated_decision_support",
  "policy_version": "v0.1-demo",
  "risk_signals": [
    { "risk_type": "hallucination", "risk_score": 0.72, "severity": "HIGH", "confidence": 0.31, "evidence_status": "UNSUPPORTED", "reason": "Claim could not be verified against available evidence" }
  ],
  "session_risk": 0.41,
  "escalation_reason": "High-severity claim with low assessment confidence under a low-tolerance profile",
  "recommended_action": "human_review",
  "reviewer_action": null
}
```

Reviewer actions supported: **Approve**, **Edit**, **Reject**. No sophisticated authentication or enterprise IAM is required — the queue exists to prove uncertainty gets escalated with full context, not silently allowed or blindly blocked.

## 15. Audit & Explainability

Every decision writes a full audit record: timestamp, request ID, session ID, use-case profile, policy version, model identifier, latency, all evaluator results, aggregated risk severity, confidence, evidence status, evidence/provenance, session risk (before and after), final action, and decision reason (references the specific rule that fired).

**Worked example:**
```json
{
  "timestamp": "2026-08-27T10:14:02Z",
  "request_id": "req_1093",
  "session_id": "sess_042",
  "use_case_profile": "regulated_decision_support",
  "policy_version": "v0.1-demo",
  "model_id": "mock-llm-v1",
  "latency_ms": 1120,
  "signals": [
    { "risk_type": "hallucination", "risk_score": 0.72, "severity": "HIGH", "confidence": 0.31, "evidence_status": "UNSUPPORTED", "reason": "Claim could not be verified against available evidence", "overlaps_with": [] }
  ],
  "aggregated_severity": "HIGH",
  "session_risk_before": 0.28,
  "session_risk_after": 0.41,
  "final_action": "human_review",
  "decision_reason": "Rule 3 fired: high severity, low confidence, no supporting evidence, under a low-tolerance profile whose low_confidence_action is human_review."
}
```

Any decision must be answerable with *"why did ControlPlane make this decision?"* — this record is that answer.

## 16. Architecture

```
Enterprise Application
        |
        v
Request + Use-Case Context
        |
        v
ControlPlane Gateway
        |
        v
Policy Engine
        |
        v
Evaluation Plan            (which evaluators run, at what depth - Section 6)
        |
        +-----------------------+
        |                       |
        v                       v
Pre-flight Checks          Foundation Model
(PII, injection -               |
 gates/redacts the input)       v
                          Output Interception
                                 |
                                 v
                    Parallel Risk Evaluators
                                 |
                +----------------+----------------+
                |                |                |
                v                v                v
              PII         Groundedness         Safety
           Evaluator        Evaluator         Evaluator
                |                |                |
                +----------------+----------------+
                                 |
                                 v
                  Risk Signal Normalization    (common schema - Section 8)
                                 |
                                 v
                          Risk Aggregator       (Section 10)
                                 |
                                 v
                          Session Risk State    (Section 13)
                                 |
                                 v
                          Decision Engine       (Section 11 - reads current
                                 |               signals + session state + policy)
                                 v
              Allow / Modify / Flag / Human Review / Block
                                 |
                                 v
                       Audit + Explanation      (Section 15)
```

Kept intentionally simple for a hackathon prototype — no duplicate detection logic across stages; pre-flight and output-stage PII checks share one detector rather than reimplementing it twice. The Policy Engine's output is not merely thresholds — it is a full **Evaluation Plan** (which evaluators to run, at what depth) plus the decision thresholds those evaluators will later be judged against.

## 17. MVP Scope

Structured around four core mechanisms. Detection modules (PII, safety, groundedness) are **evaluator implementations that feed Core 2** — not separate top-level mechanisms.

**CORE 1 — Context-Aware Policy Engine**
Input: use-case context → Output: active policy + evaluation plan (enabled evaluators, evaluation depth — Section 6)

**CORE 2 — Evidence-Aware Risk Evaluation**
Input: model output + optional trusted evidence → Output: severity + confidence + evidence_status per risk type (Sections 8-9)

**CORE 3 — Uncertainty-Aware Decision Engine**
Input: risk signals + context policy + confidence + evidence + session state → Output: allow / modify / flag / review / block (Section 11)

**CORE 4 — Session + Audit State**
Input: signals across turns → Output: cumulative session risk (Section 13) + traceable decision history (Section 15)

## 18. Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python + FastAPI |
| Frontend | Streamlit |
| Storage | SQLite |
| Configuration | YAML |
| Model | Mocked/reproducible demo mode, with an optional live-model API toggle |
| PII | Regex (deterministic, high confidence) + optional spaCy NER (probabilistic, lower confidence) |
| Groundedness | sentence-transformers similarity + lightweight NLI where practical — the primary, deterministic implementation |
| AI judge | Optional fallback/demo enhancement only — the prototype must remain functional without it |

Explicitly out of scope: Kubernetes, microservices, distributed queues, complex cloud infrastructure, production IAM/enterprise auth, model-training pipelines (see Section 24).

## 19. Demo Scenarios

Each demo shows the full chain: **Input → Model Output → Evaluators → Risk Signals → Confidence → Evidence Status → Policy → Decision → Explanation**

**Demo 1 — Same Input, Different Policy** *(headline demo)*
Identical output containing an unsupported claim, run through two profiles. Internal Copilot: severity `HIGH`, confidence low, evidence `UNSUPPORTED` → `allow_with_flag` → **Allow + Caveat**. Regulated Decision-Support: same signal → `human_review` → **Human Review**. Direct proof that one framework produces genuinely different, policy-driven behavior on identical input.

**Demo 2 — Ground Truth Exists vs. Does Not**
With a trusted source document → `SUPPORTED`/`CONTRADICTED`, high confidence. Without one → `UNSUPPORTED`, confidence reflects uncertainty. The system never claims a statement is verified true or false without evidence — it reports "claim could not be verified," not "hallucination confirmed."

**Demo 3 — Safety Floor**
A high-confidence, policy-defined critical violation (e.g., credential/secret exposure) → **Redact/Block** under every profile — Section 12's narrow override, not a blanket rule for all PII or all unsafe-content flags.

**Demo 4 — Overlapping Risks**
A fabricated personal detail about a person produces two linked signals, `hallucination` and `privacy`, each listing the other in `overlaps_with`. Aggregator shows both; one corrective action resolves both without double-counting.

**Demo 5 — Session Compounding**
Three turns with risk_score 0.40, 0.35, 0.50 accumulate via the decay-weighted formula (Section 13) to session_risk = 0.60, crossing the Regulated profile's `session_risk_threshold` → **Human Review** on the third turn. The mechanism is threshold-driven: review triggers whenever accumulated risk crosses the configured threshold, not because a fixed number of turns occurred.

## 20. Acceptance Criteria

The prototype succeeds if all of the following hold:

- **Context** — The same model output produces different decisions under at least two use-case profiles (Demo 1).
- **Configuration** — Changing policy configuration changes behavior without modifying Decision Engine code.
- **Uncertainty** — High severity + low confidence remains high severity; confidence never mathematically reduces risk (Sections 8, 11).
- **Evidence** — No-evidence cases are represented as `UNSUPPORTED`/`UNKNOWN`, never as `FALSE` (Section 7).
- **Overlap** — Multiple risk types can coexist in one decision without naive score addition (Section 10, Demo 4).
- **Evaluation Depth** — Different profiles activate different evaluator sets/depths (Section 6).
- **Session** — Risk accumulates across turns and can cross a configurable threshold (Section 13, Demo 5).
- **Human Review** — Escalated cases appear in a review queue with full context (Section 14).
- **Audit** — Every decision has a traceable audit record (Section 15).
- **Safety Floor** — Qualifying critical violations override normal policy behavior (Section 12, Demo 3).

## 21. Round 2 Complexity → Design Response

| Round 2 Complexity | Design Response | Prototype Evidence |
|---|---|---|
| Different risk tolerance / latency budgets per use case | Context-aware policy engine + configurable evaluation depth | Demo 1; Sections 5-6 |
| Hallucination/bias/privacy risk overlap | Independent signals + overlap-aware aggregation, never naive summing | Demo 4; Section 10 |
| No reliable real-time ground truth | Evidence status + explicit UNKNOWN/UNSUPPORTED state + uncertainty-aware decisioning | Demo 2; Sections 7, 9, 11 |
| Over-flagging vs. under-flagging | Context-specific thresholds + confidence-aware escalation, not one global threshold | Demo 1, 3; Section 11 |
| Multi-turn / agentic compounding risk | Session-level cumulative risk state, decay-weighted and configurable | Demo 5; Section 13 |
| Regulatory variation across geography/industry, evolving over time | Versioned, configurable policies rather than hardcoded legal rules | Section 6 |
| Foundation models accessed via API only | All evaluation happens at the input/output layer — no dependency on model internals | Sections 9, 16 |

## 22. Novelty / Differentiation

**Core statement:** ControlPlane.ai does not treat risk detection as the final decision. It separates risk severity from confidence in the assessment, combines that uncertainty with use-case policy and available evidence, and produces a context-specific intervention.

1. **Context-aware evaluation planning** — policy determines not just thresholds but which evaluators run and at what depth
2. **Separation of severity and confidence** — two dimensions feed the decision, never collapsed into one number
3. **Evidence-aware uncertainty** — the system distinguishes what it has verified from what it merely suspects
4. **Policy-driven intervention** — the same signal produces different actions depending on configured policy, not code
5. **Overlap-aware risk representation** — one fact can trigger multiple risk categories without double-counting or losing information
6. **Session-level state** — risk isn't purely evaluated per-message
7. **Explainable, versioned decisions** — every action is traceable to a specific policy version and rule

ControlPlane.ai combines these dimensions into one context-aware decision framework. No individual mechanism here is claimed to be unprecedented; the claim is about the combination operating consistently across every decision the system makes.

## 23. Assumptions & Limitations

- Enterprise data and demo traffic used in the prototype are simulated; no real proprietary data is used.
- All policy thresholds, evaluation-depth assignments, and session-accumulation constants are illustrative, not empirically calibrated.
- Model-based evaluators (AI-as-judge, LLM-based groundedness) are heuristics, not ground truth.
- Lack of reliable ground truth fundamentally limits how confidently factual claims can be verified — a stated constraint of the problem, not a gap unique to this prototype.
- The prototype provides no legal or regulatory compliance guarantee.
- Session-risk accumulation is a demonstration mechanism, not a validated risk model.
- False-positive/false-negative tradeoffs require empirical tuning against real outcomes; the prototype does not claim a tuned operating point.
- Production calibration of thresholds and accumulation rules would require historical outcome data, human-review feedback, and organizational governance — none of which exist in a hackathon prototype.

## 24. Explicitly Not Building

- Real regulatory/legal compliance engine
- Model retraining / production feedback-loop learning
- Full agent action-interception framework
- Production-grade authentication / enterprise IAM
- Production scaling, autoscaling, Kubernetes, or distributed infrastructure
- Real enterprise system integrations or real proprietary enterprise data
- More than three use-case profiles

Feedback loops and regulatory adaptivity are described as future architecture (Section 26), not implemented in the prototype.

## 25. Implementation Contract

Build, in this order:

1. FastAPI backend
2. Policy configuration system (Section 6) — including evaluation plan derivation
3. Evaluator interface (common input/output contract, Section 8)
4. PII evaluator (pattern-based + optional NER, Section 9)
5. Groundedness/evidence evaluator (Section 9, Cases A & B) — deterministic primary path, optional AI-judge enhancement
6. Safety evaluator
7. Risk signal schema (Section 8) — shared by all evaluators
8. Risk aggregator (Section 10)
9. Decision engine (Section 11) + Safety floor (Section 12)
10. Session risk tracker with decay formula (Section 13)
11. Audit logger (Section 15)
12. Human review queue (Section 14)
13. Streamlit dashboard (live trace, risk breakdown, decision reasoning, profile switcher, audit log, review queue)
14. Reproducible demo scenarios (Section 19)

**Data flow, end to end:** Input → Evaluation Plan → evaluation → normalized signal → aggregation → session update → policy decision → action → audit. This document is intended to be sufficient on its own to implement that flow.

**Binding constraints while building:**
- Use-case behavior comes from config, never hardcoded per-profile branches.
- `severity` and `confidence` are separate fields, never multiplied together.
- `UNSUPPORTED`/`UNKNOWN` must never be written or displayed as `FALSE`.
- `risk_type == pii` does not automatically trigger Block — routine PII follows normal policy; only policy-defined safety-floor categories override context.
- Every evaluator conforms to the shared risk signal schema (Section 8).
- Every decision writes a full audit record including `policy_version` and `latency_ms`.
- Aggregation preserves individual signals — never a blind sum.
- Session risk uses the configured decay formula (Section 13) — not a hardcoded turn count.
- All demo scenarios must be deterministic and reproducible on repeat runs.
- The system must run without an AI judge; AI-as-judge is optional.

## 26. Future Extensions

Not part of the Round 2 prototype — included to show the design generalizes toward broader adoption.

- **Feedback loops:** use human-review outcomes (Approve/Edit/Reject) to recalibrate thresholds and session-accumulation weights over time.
- **Regulatory adaptivity:** versioned policy packs scoped by geography/industry, swapped without code changes.
- **Deeper agent-action interception:** evaluate and gate downstream actions an agent takes, not just generated text.
- **Real enterprise data integration:** connect evidence retrieval to actual internal knowledge bases rather than simulated source documents.
- **Expanded evaluator set:** dedicated bias detectors, jailbreak/adversarial-prompt classifiers.
- **Session-risk decay/windowing:** time- or turn-based decay tuning beyond the prototype's fixed constants.
- **Production hardening:** authentication, scaling, monitoring, and access control appropriate to real deployment.
READMEEOF
echo "Written: $(wc -l < /mnt/user-data/outputs/README.md) lines"
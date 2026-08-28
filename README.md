# ControlPlane.ai

*A context-aware, uncertainty-aware AI risk decision layer for enterprise foundation-model deployments.*
*Round 2 — Accenture Innovation Challenge 2026*

---

## Quick Start

### 1. Install dependencies

```bash
cd c:\ML\ControlPanel.ai
pip install -r requirements.txt
```

Optional (for NER-based PII detection):
```bash
pip install spacy
python -m spacy download en_core_web_sm
```

> **Note:** Both `sentence-transformers` and `spacy` are lazy-loaded on first use to ensure fast cold starts and zero overhead for profiles that don't need them. The system fully functions without them.

### 2. Start both servers

```bash
python run.py
```

Or start separately:

```bash
# Terminal 1 — Backend (FastAPI)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend (Streamlit)
streamlit run frontend/app.py --server.port 8501
```

### 3. Open

- **Dashboard:** http://localhost:8501
- **API docs:** http://localhost:8000/docs
- **API base:** http://localhost:8000

---

## Running Demos

In the dashboard, click any **Demo** button in the Live Trace tab, or via API:

```bash
curl -X POST http://localhost:8000/demos/1   # Same Input, Different Policy
curl -X POST http://localhost:8000/demos/2   # Ground Truth Exists vs. Does Not
curl -X POST http://localhost:8000/demos/3   # Safety Floor
curl -X POST http://localhost:8000/demos/4   # Overlapping Risks
curl -X POST http://localhost:8000/demos/5   # Session Compounding
```

---

## Project Structure

```
ControlPanel.ai/
├── run.py                         # Start both servers
├── requirements.txt
├── backend/
│   ├── main.py                    # FastAPI + all 7 endpoints
│   ├── config/
│   │   └── policy.yaml            # Versioned policy (§6)
│   ├── core/
│   │   ├── schemas.py             # RiskSignal (10 fields), AuditRecord (15), ReviewQueueItem (11)
│   │   ├── policy_engine.py       # CORE 1 — loads policy, derives EvaluationPlan
│   │   ├── evaluator_base.py      # Shared evaluator interface
│   │   ├── pii_evaluator.py       # PII: regex (high conf) + spaCy NER (optional)
│   │   ├── groundedness_evaluator.py  # Case A (evidence) + Case B (UNSUPPORTED)
│   │   ├── safety_evaluator.py    # Safety/toxicity heuristic
│   │   ├── injection_evaluator.py # Prompt injection: pre-flight + output
│   │   ├── risk_aggregator.py     # §10 seven-step aggregation
│   │   ├── decision_engine.py     # CORE 3 — 6 rules in order (§11)
│   │   ├── safety_floor.py        # §12 narrow override
│   │   ├── session_tracker.py     # §13 decay formula
│   │   ├── audit_logger.py        # §15 full audit record
│   │   └── review_queue.py        # §14 human review queue
│   ├── db/
│   │   └── database.py            # SQLite (audit_log, review_queue, sessions)
│   └── demos/
│       └── scenarios.py           # 5 deterministic demo scenarios (§19)
├── frontend/
│   └── app.py                     # Streamlit: 6 tabs per §25
└── controlplane.db                # Auto-created SQLite database
```

---

## Core Principles (Binding)

| Constraint | Enforcement |
|---|---|
| No hardcoded per-profile branches | `policy_engine.py` reads config only (and hot-reloads on edits) |
| `severity` × `confidence` = never | Separate fields, never multiplied anywhere |
| UNSUPPORTED ≠ FALSE | Never stored or displayed as FALSE |
| PII ≠ auto-Block | Routine PII follows normal policy |
| Safety Floor is Policy-Driven | `safety_floor.py` checks exact `risk_category` against policy |
| All evaluators → same §8 schema | `BaseEvaluator` enforces interface |
| Every decision → full audit record | `audit_logger.py` always writes all 15 fields |
| Aggregation preserves individual signals | `risk_aggregator.py` never sums and retains all claims |
| Session risk from config formula | `session_tracker.py` reads decay_factor, risk_weight from policy |
| Demos are deterministic | All inputs hardcoded in `scenarios.py` |
| System runs without AI judge | `groundedness_evaluator.py` fully functional in Case B |

---

## Policy Version

`v0.1-demo` — Illustrative prototype thresholds. Not production risk calibration.

---

*ControlPlane.ai is a decision layer, not a detection system. It governs how outputs from any foundation model get released, using context, evidence, and configurable policy.*

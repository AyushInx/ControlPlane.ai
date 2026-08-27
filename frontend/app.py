"""
app.py — Step 13: Streamlit Dashboard (§25)

Six tabs matching the exact §25 implementation contract:
  1. Live Trace         — Input + profile selector → full pipeline trace
  2. Risk Breakdown     — Per-signal: severity/confidence as SEPARATE dimensions
  3. Decision Reasoning — Which rule fired, contributing signals, policy version
  4. Profile Switcher   — Same input → two profiles → different decisions
  5. Audit Log          — All past decisions, filterable
  6. Review Queue       — Pending items with Approve / Edit / Reject actions

BINDING:
  - UNSUPPORTED is NEVER displayed as FALSE — displayed as "UNSUPPORTED" or "Cannot verify"
  - Severity and confidence always shown as separate visual elements
  - Never combine / multiply them in any display calculation
"""

import streamlit as st
import requests
import json
from typing import Dict, Any, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BACKEND_URL = "http://localhost:8000"

st.set_page_config(
    page_title="ControlPlane.ai — AI Risk Decision Layer",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — dark mode, severity colors, premium design
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* ── Base ── */
    .stApp { background-color: #FAFAFC; color: #18181B; }
    .main .block-container { padding: 1.5rem 2rem; max-width: 1400px; }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #FFFFFF 0%, #FAFAFC 100%);
        border-right: 1px solid #E4E4E7;
    }

    /* ── Typography ── */
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; }

    /* ── Cards ── */
    .cp-card {
        background: #FFFFFF;
        border: 1px solid #E4E4E7;
        border-radius: 14px;
        padding: 1.2rem 1.5rem;
        margin: 0.6rem 0;
        box-shadow: 0 4px 16px rgba(0,0,0,0.03);
        color: #18181B;
    }
    .cp-card-accent {
        background: linear-gradient(135deg, #FAF5FF 0%, #F3E8FF 100%);
        border: 1px solid #DDD6FE;
        border-radius: 14px;
        padding: 1.2rem 1.5rem;
        margin: 0.6rem 0;
        box-shadow: 0 4px 16px rgba(0,0,0,0.03);
        color: #18181B;
    }

    /* ── Severity badges ── */
    .badge-low      { background:#ecfdf5; color:#059669; border:1px solid #d1fae5; border-radius:6px; padding:2px 10px; font-size:0.78rem; font-weight:600; font-family:'JetBrains Mono',monospace; }
    .badge-medium   { background:#fffbeb; color:#d97706; border:1px solid #fef3c7; border-radius:6px; padding:2px 10px; font-size:0.78rem; font-weight:600; font-family:'JetBrains Mono',monospace; }
    .badge-high     { background:#fff7ed; color:#ea580c; border:1px solid #ffedd5; border-radius:6px; padding:2px 10px; font-size:0.78rem; font-weight:600; font-family:'JetBrains Mono',monospace; }
    .badge-critical { background:#fef2f2; color:#dc2626; border:1px solid #fee2e2; border-radius:6px; padding:2px 10px; font-size:0.78rem; font-weight:600; font-family:'JetBrains Mono',monospace; }

    /* ── Action badges ── */
    .action-allow          { background:#ecfdf5; color:#059669; border:1px solid #d1fae5; border-radius:6px; padding:3px 12px; font-size:0.82rem; font-weight:600; }
    .action-allow_with_flag{ background:#f0f9ff; color:#0284c7; border:1px solid #e0f2fe; border-radius:6px; padding:3px 12px; font-size:0.82rem; font-weight:600; }
    .action-edit_soften    { background:#fffbeb; color:#d97706; border:1px solid #fef3c7; border-radius:6px; padding:3px 12px; font-size:0.82rem; font-weight:600; }
    .action-flag           { background:#fff7ed; color:#ea580c; border:1px solid #ffedd5; border-radius:6px; padding:3px 12px; font-size:0.82rem; font-weight:600; }
    .action-human_review   { background:#f3e8ff; color:#6d28d9; border:1px solid #ddd6fe; border-radius:6px; padding:3px 12px; font-size:0.82rem; font-weight:600; }
    .action-redact         { background:#fff7ed; color:#ea580c; border:1px solid #ffedd5; border-radius:6px; padding:3px 12px; font-size:0.82rem; font-weight:600; }
    .action-block          { background:#fef2f2; color:#dc2626; border:1px solid #fee2e2; border-radius:6px; padding:3px 12px; font-size:0.82rem; font-weight:600; }

    /* ── Evidence chips ── */
    .ev-supported         { background:#ecfdf5; color:#059669; border:1px solid #d1fae5; border-radius:4px; padding:1px 8px; font-size:0.75rem; font-family:'JetBrains Mono',monospace; }
    .ev-contradicted      { background:#fef2f2; color:#dc2626; border:1px solid #fee2e2; border-radius:4px; padding:1px 8px; font-size:0.75rem; font-family:'JetBrains Mono',monospace; }
    .ev-partially         { background:#fffbeb; color:#d97706; border:1px solid #fef3c7; border-radius:4px; padding:1px 8px; font-size:0.75rem; font-family:'JetBrains Mono',monospace; }
    .ev-unsupported       { background:#f3e8ff; color:#6d28d9; border:1px solid #ddd6fe; border-radius:4px; padding:1px 8px; font-size:0.75rem; font-family:'JetBrains Mono',monospace; }
    .ev-not_applicable    { background:#f4f4f5; color:#71717a; border:1px solid #e4e4e7; border-radius:4px; padding:1px 8px; font-size:0.75rem; font-family:'JetBrains Mono',monospace; }

    /* ── Metric boxes ── */
    .metric-box {
        background:#FFFFFF; border:1px solid #E4E4E7; border-radius:12px;
        padding:0.8rem 1rem; text-align:center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.02);
    }
    .metric-box .label { font-size:0.72rem; color:#71717A; text-transform:uppercase; letter-spacing:0.08em; font-weight:500; }
    .metric-box .value { font-size:1.6rem; font-weight:700; color:#6D28D9; line-height:1.2; }

    /* ── Risk bar container ── */
    .risk-bar-container { margin: 4px 0; }
    .risk-bar-label { font-size:0.72rem; color:#71717A; display:flex; justify-content:space-between; font-weight:500; }
    .risk-bar-track { background:#E4E4E7; border-radius:4px; height:8px; width:100%; margin-top:4px; }
    .risk-bar-fill  { border-radius:4px; height:8px; transition:width 0.4s ease; }

    /* ── Section headers ── */
    .section-header {
        font-size:1.1rem; font-weight:600; color:#18181B;
        border-bottom:1px solid #E4E4E7;
        padding-bottom:0.5rem; margin:1.2rem 0 0.8rem 0;
    }

    /* ── Rule pill ── */
    .rule-pill {
        display:inline-block;
        background: #F3E8FF;
        border:1px solid #DDD6FE;
        color:#6D28D9; border-radius:20px;
        padding:4px 14px; font-size:0.82rem; font-weight:600;
        font-family:'JetBrains Mono',monospace;
    }

    /* ── Signal card ── */
    .signal-card {
        background:#FFFFFF; border:1px solid #E4E4E7; border-radius:14px;
        padding:1rem 1.2rem; margin:0.5rem 0;
        box-shadow: 0 4px 16px rgba(0,0,0,0.03);
    }

    /* ── Constraint notice ── */
    .constraint-notice {
        background:#F0F9FF; border-left:3px solid #0284C7;
        border-radius:0 8px 8px 0; padding:0.6rem 1rem;
        font-size:0.8rem; color:#0284C7; margin:0.4rem 0;
    }

    /* ── Unsupported warning ── */
    .unsupported-notice {
        background:#FAF5FF; border-left:3px solid #8B5CF6;
        border-radius:0 8px 8px 0; padding:0.6rem 1rem;
        font-size:0.82rem; color:#6D28D9; margin:0.4rem 0;
    }

    /* ── Override default button ── */
    .stButton > button {
        background: #6D28D9;
        color:white; border:none; border-radius:10px;
        font-weight:600; padding:0.5rem 1.5rem;
        transition: all 200ms ease;
    }
    .stButton > button:hover { background: #8B5CF6; transform:translateY(-1px); box-shadow: 0 4px 12px rgba(109, 40, 217, 0.2); }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] { background:transparent; border-bottom:1px solid #E4E4E7; }
    .stTabs [data-baseweb="tab"] { color:#71717A; font-weight:500; }
    .stTabs [aria-selected="true"] { color:#6D28D9; border-bottom:2px solid #6D28D9; background:transparent; }

    /* ── Selectbox and Inputs ── */
    .stSelectbox > div > div { background:#FFFFFF; border-color:#E4E4E7; color:#18181B; border-radius:8px; }
    .stSelectbox > div > div:focus-within { border-color:#8B5CF6; box-shadow: 0 0 0 1px #8B5CF6; }
    .stTextInput > div > div > input { background:#FFFFFF; border-color:#E4E4E7; color:#18181B; border-radius:8px; }
    .stTextInput > div > div > input:focus { border-color:#8B5CF6; box-shadow: 0 0 0 1px #8B5CF6; }
    .stTextArea > div > div > textarea { background:#FFFFFF; border-color:#E4E4E7; color:#18181B; border-radius:8px; }
    .stTextArea > div > div > textarea:focus { border-color:#8B5CF6; box-shadow: 0 0 0 1px #8B5CF6; }

    /* Hide streamlit branding ── */
    #MainMenu { visibility:hidden; }
    footer { visibility:hidden; }
    header { visibility:hidden; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def severity_badge(sev: str) -> str:
    cls = f"badge-{sev.lower()}"
    return f'<span class="{cls}">{sev}</span>'


def action_badge(action: str) -> str:
    cls = f"action-{action.lower()}"
    label = action.upper().replace("_", " ")
    return f'<span class="{cls}">{label}</span>'


def evidence_chip(ev_status: str) -> str:
    cls_map = {
        "SUPPORTED": "ev-supported",
        "CONTRADICTED": "ev-contradicted",
        "PARTIALLY_SUPPORTED": "ev-partially",
        "UNSUPPORTED": "ev-unsupported",
        "NOT_APPLICABLE": "ev-not_applicable",
    }
    # BINDING: UNSUPPORTED is NEVER displayed as FALSE
    display_map = {
        "SUPPORTED": "SUPPORTED",
        "CONTRADICTED": "CONTRADICTED",
        "PARTIALLY_SUPPORTED": "PARTIALLY SUPPORTED",
        "UNSUPPORTED": "UNSUPPORTED",      # ← Never "FALSE" or "unverified=false"
        "NOT_APPLICABLE": "N/A",
    }
    cls = cls_map.get(ev_status, "ev-not_applicable")
    label = display_map.get(ev_status, ev_status)
    return f'<span class="{cls}">{label}</span>'


def score_bar(label: str, value: float, color: str = "#6D28D9") -> str:
    pct = int(value * 100)
    return f"""
    <div class="risk-bar-container">
      <div class="risk-bar-label">
        <span>{label}</span><span style="color:#18181B;font-weight:600">{value:.2f}</span>
      </div>
      <div class="risk-bar-track">
        <div class="risk-bar-fill" style="width:{pct}%;background:{color}"></div>
      </div>
    </div>"""


def severity_color(sev: str) -> str:
    return {"LOW": "#059669", "MEDIUM": "#d97706", "HIGH": "#ea580c", "CRITICAL": "#dc2626"}.get(sev, "#52525B")


def call_api(method: str, path: str, **kwargs) -> Optional[Dict]:
    try:
        url = f"{BACKEND_URL}{path}"
        resp = getattr(requests, method)(url, timeout=30, **kwargs)
        if resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"API error {resp.status_code}: {resp.text[:300]}")
            return None
    except requests.exceptions.ConnectionError:
        st.error(
            "⚠️ Cannot connect to backend. "
            "Start it with: `uvicorn backend.main:app --reload --port 8000`"
        )
        return None
    except Exception as e:
        st.error(f"Request error: {e}")
        return None


def render_signal_card(sig: dict, index: int = 0):
    """Render a single RiskSignal as a styled card."""
    sev = sig.get("severity", "LOW")
    ev_status = sig.get("evidence_status", "NOT_APPLICABLE")
    risk_score = sig.get("risk_score", 0.0)
    confidence = sig.get("confidence", 0.0)
    overlaps = sig.get("overlaps_with", [])

    sev_color = severity_color(sev)

    overlaps_html = ""
    if overlaps:
        overlaps_html = f"""<div style="margin-top:0.4rem;font-size:0.75rem;color:#52525B;">
            🔗 overlaps_with: {', '.join(f'<code style="color:#6D28D9">{o}</code>' for o in overlaps)}
        </div>"""

    # BINDING: severity and confidence are ALWAYS displayed as separate visual elements
    st.markdown(f"""
    <div class="signal-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem;">
        <span style="font-weight:600;color:#18181B;font-family:'JetBrains Mono',monospace;font-size:0.9rem;">
          {sig.get('risk_type','').upper()}
        </span>
        <div style="display:flex;gap:6px;align-items:center;">
          {severity_badge(sev)}
          {evidence_chip(ev_status)}
        </div>
      </div>
      {score_bar("RISK SCORE (severity — independent of confidence)", risk_score, sev_color)}
      {score_bar("CONFIDENCE (evaluator's assessment reliability — separate dimension)", confidence, "#8B5CF6")}
      <div style="font-size:0.78rem;color:#52525B;margin-top:0.5rem;line-height:1.5;">
        {sig.get('reason','')}</div>
      {overlaps_html}
    </div>
    """, unsafe_allow_html=True)

    # BINDING notice on UNSUPPORTED
    if ev_status == "UNSUPPORTED":
        st.markdown("""
        <div class="unsupported-notice">
          ℹ️ <strong>UNSUPPORTED ≠ FALSE</strong> — 
          ControlPlane cannot verify this claim either way. 
          This is not a confirmation of hallucination — it is an absence of evidence (§7).
        </div>""", unsafe_allow_html=True)


def render_decision_result(result: dict):
    """Render a decision result with full trace."""
    decision = result.get("decision", {})
    action = decision.get("action", "allow")
    rule_fired = decision.get("rule_fired", 0)
    reason = decision.get("reason", "")
    agg_sev = result.get("aggregated_severity", "LOW")
    sr_before = result.get("session_risk_before", 0.0)
    sr_after = result.get("session_risk_after", 0.0)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-box">
          <div class="label">Decision</div>
          <div style="margin-top:0.3rem">{action_badge(action)}</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-box">
          <div class="label">Aggregated Severity</div>
          <div style="margin-top:0.3rem">{severity_badge(agg_sev)}</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-box">
          <div class="label">Session Risk</div>
          <div class="value" style="color:{severity_color('HIGH' if sr_after > 0.6 else 'MEDIUM' if sr_after > 0.3 else 'LOW')}">{sr_after:.3f}</div>
        </div>""", unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="metric-box">
          <div class="label">Rule Fired</div>
          <div class="value">#{rule_fired}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown(f"""
    <div class="cp-card-accent" style="margin-top:0.8rem;">
      <div style="font-size:0.72rem;color:#52525B;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.4rem;">
        Decision Reason
      </div>
      <span class="rule-pill">Rule {rule_fired}</span>
      <p style="color:#18181B;margin-top:0.6rem;font-size:0.88rem;line-height:1.6;">{reason}</p>
    </div>""", unsafe_allow_html=True)

    # Session risk progression
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(score_bar("Session Risk Before", sr_before, "#52525B"), unsafe_allow_html=True)
    with col_b:
        st.markdown(score_bar("Session Risk After", sr_after, severity_color(
            "CRITICAL" if sr_after > 0.8 else "HIGH" if sr_after > 0.6 else "MEDIUM" if sr_after > 0.3 else "LOW"
        )), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("""
    <div style="text-align:center;padding:1rem 0 1.5rem 0;">
      <div style="font-size:2rem;">🛡️</div>
      <div style="font-size:1.2rem;font-weight:700;color:#18181B;">ControlPlane.ai</div>
      <div style="font-size:0.72rem;color:#52525B;margin-top:0.2rem;">
        AI Risk Decision Layer<br>
        Round 2 — Accenture Innovation Challenge 2026
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Backend status
    health = call_api("get", "/health")
    if health:
        st.markdown(f"""
        <div style="background:#ecfdf5;border:1px solid #059669;border-radius:8px;
                    padding:0.5rem 1rem;font-size:0.78rem;color:#059669;margin-bottom:1rem;">
          ✅ Backend connected · {health.get('policy_version','—')}
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background:#fef2f2;border:1px solid #dc2626;border-radius:8px;
                    padding:0.5rem 1rem;font-size:0.78rem;color:#dc2626;margin-bottom:1rem;">
          ❌ Backend offline
        </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div style="font-size:0.72rem;color:#52525B;margin-top:1rem;line-height:1.6;">
      <strong style="color:#18181B;">Core Principles</strong><br>
      • LOW CONFIDENCE ≠ LOW RISK<br>
      • UNSUPPORTED ≠ FALSE<br>
      • Severity × Confidence = Never<br>
      • Behavior from config, not code<br>
      • Every decision names its rule
    </div>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Main tabs (exact 6 from §25 implementation contract)
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 Live Trace",
    "📊 Risk Breakdown",
    "⚖️ Decision Reasoning",
    "🔄 Profile Switcher",
    "📋 Audit Log",
    "👤 Review Queue",
])

# ===========================================================================
# TAB 1 — Live Trace
# ===========================================================================
with tab1:
    st.markdown('<div class="section-header">Live Evaluator — Full Pipeline Trace</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="constraint-notice">
      Input text + profile → runs full pipeline → shows full trace:
      signals, severity/confidence breakdown, evidence status, decision + reason, audit record.
    </div>""", unsafe_allow_html=True)

    col_l, col_r = st.columns([2, 1])
    with col_l:
        prompt_text = st.text_area(
            "Prompt / User Input",
            value="What is the Q3 revenue forecast for our APAC division?",
            height=80,
            key="lt_prompt",
        )
        model_output_text = st.text_area(
            "Model Output (text to evaluate)",
            value=(
                "Our internal models project Q3 2026 APAC revenue at $4.2B, "
                "representing 34.7% market share. This is based on proprietary "
                "analysis validated by our executive team with 99.8% confidence."
            ),
            height=100,
            key="lt_output",
        )
        trusted_evidence_text = st.text_area(
            "Trusted Evidence (optional — leave blank for UNSUPPORTED case)",
            value="",
            height=60,
            key="lt_evidence",
            placeholder="Paste a source document here to enable groundedness Case A evaluation...",
        )

    with col_r:
        profile = st.selectbox(
            "Use-Case Profile",
            ["customer_facing_chatbot", "internal_copilot", "regulated_decision_support"],
            key="lt_profile",
            format_func=lambda x: {
                "customer_facing_chatbot": "🤖 Customer Chatbot",
                "internal_copilot": "💼 Internal Copilot",
                "regulated_decision_support": "⚖️ Regulated Decision-Support",
            }[x],
        )
        session_id = st.text_input("Session ID", value="live-session-001", key="lt_session")
        st.markdown("""
        <div style="background:#FFFFFF;border:1px solid #E4E4E7;border-radius:8px;padding:0.8rem;margin-top:0.5rem;font-size:0.75rem;color:#52525B;">
          <strong style="color:#18181B;">Pipeline (§16):</strong><br>
          Policy Engine → Pre-flight → Model Output →
          Evaluators → Aggregation → Session Update →
          Decision → Audit
        </div>""", unsafe_allow_html=True)

    run_col, _ = st.columns([1, 3])
    with run_col:
        run_eval = st.button("▶ Evaluate", key="lt_run")

    if run_eval:
        payload = {
            "session_id": session_id,
            "profile": profile,
            "prompt": prompt_text,
            "model_output": model_output_text,
            "trusted_evidence": trusted_evidence_text if trusted_evidence_text.strip() else None,
            "model_id": "mock-llm-v1",
        }
        with st.spinner("Running evaluation pipeline..."):
            result = call_api("post", "/evaluate", json=payload)

        if result:
            st.success("Evaluation complete")
            render_decision_result(result)

            st.markdown('<div class="section-header">Risk Signals</div>', unsafe_allow_html=True)
            signals = result.get("signals", [])
            if not signals:
                st.info("No risk signals detected.")
            for i, sig in enumerate(signals):
                render_signal_card(sig, i)

            # Audit record expander
            with st.expander("📄 Full Audit Record (§15)", expanded=False):
                st.code(json.dumps(result.get("audit_record", {}), indent=2), language="json")

            if result.get("review_queue_item"):
                st.markdown("""
                <div style="background:#F3E8FF;border:1px solid #6D28D9;border-radius:8px;
                            padding:0.8rem 1.2rem;margin-top:0.5rem;">
                  <strong style="color:#6D28D9;">👤 Added to Human Review Queue</strong><br>
                  <span style="font-size:0.82rem;color:#52525B;">
                    High-stakes + uncertain → human review, not automatic block (§14).
                  </span>
                </div>""", unsafe_allow_html=True)

    # Demo scenarios quick-run
    st.markdown('<div class="section-header">Quick Demo Scenarios</div>', unsafe_allow_html=True)
    demo_cols = st.columns(5)
    demo_names = [
        "1: Policy", "2: Evidence", "3: Safety Floor",
        "4: Overlaps", "5: Session"
    ]
    for i, (col, name) in enumerate(zip(demo_cols, demo_names)):
        with col:
            if st.button(f"▶ Demo {name}", key=f"demo_btn_{i+1}"):
                with st.spinner(f"Running Demo {i+1}..."):
                    demo_result = call_api("post", f"/demos/{i+1}")
                if demo_result:
                    st.session_state[f"demo_result_{i+1}"] = demo_result

    for i in range(1, 6):
        key = f"demo_result_{i}"
        if key in st.session_state:
            with st.expander(f"Demo {i} Results", expanded=True):
                dr = st.session_state[key]
                st.markdown(f"**{dr.get('name','')}**")
                st.caption(dr.get("description", ""))
                for res in dr.get("results", []):
                    label = res.get("profile") or res.get("label") or f"Turn {res.get('turn','')}"
                    st.markdown(f"---\n##### {label}")
                    resp = res.get("response", {})
                    if resp:
                        render_decision_result(resp)
                        for sig in resp.get("signals", []):
                            render_signal_card(sig)


# ===========================================================================
# TAB 2 — Risk Breakdown
# ===========================================================================
with tab2:
    st.markdown('<div class="section-header">Risk Breakdown — Severity & Confidence as Separate Dimensions</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="constraint-notice">
      BINDING (§8): risk_score = 0.90, confidence = 0.25 does NOT become risk = 0.225.
      Severity describes how bad the risk WOULD BE if the assessment is correct.
      Confidence describes how reliable the assessment IS.
      They are always displayed as two independent dimensions — never combined.
    </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div class="cp-card" style="margin-bottom:1rem;">
      <strong>Run any evaluation in the Live Trace tab to see signals here.</strong><br>
      Or use the demo scenarios below.
    </div>""", unsafe_allow_html=True)

    # Manual signal explorer
    st.markdown("#### Signal Explorer")
    exp_cols = st.columns(4)
    with exp_cols[0]:
        ex_risk_score = st.slider("Risk Score (severity if correct)", 0.0, 1.0, 0.72, 0.01, key="ex_rs")
    with exp_cols[1]:
        ex_confidence = st.slider("Confidence (assessment reliability)", 0.0, 1.0, 0.31, 0.01, key="ex_conf")
    with exp_cols[2]:
        ex_ev = st.selectbox("Evidence Status", [
            "SUPPORTED","CONTRADICTED","PARTIALLY_SUPPORTED","UNSUPPORTED","NOT_APPLICABLE"
        ], index=3, key="ex_ev")
    with exp_cols[3]:
        ex_rtype = st.selectbox("Risk Type", ["hallucination","pii","safety","prompt_injection"], key="ex_rtype")

    # Determine severity band
    if ex_risk_score < 0.30:
        ex_sev = "LOW"
    elif ex_risk_score < 0.60:
        ex_sev = "MEDIUM"
    elif ex_risk_score < 0.80:
        ex_sev = "HIGH"
    else:
        ex_sev = "CRITICAL"

    mock_signal = {
        "risk_type": ex_rtype,
        "risk_score": ex_risk_score,
        "severity": ex_sev,
        "confidence": ex_confidence,
        "evidence_status": ex_ev,
        "verified": ex_confidence >= 0.70 and ex_ev == "SUPPORTED",
        "evidence": [],
        "overlaps_with": [],
        "reason": (
            f"Explorer signal: risk_score={ex_risk_score:.2f} → severity={ex_sev}. "
            f"Confidence={ex_confidence:.2f} (independent dimension — never multiplied). "
            f"Evidence status: {ex_ev}."
        ),
    }
    render_signal_card(mock_signal)

    # Show the §11 decision table
    st.markdown("#### §11 Illustrative Outcome Table")
    table_data = {
        "Severity": ["CRITICAL","HIGH","HIGH","MEDIUM","MEDIUM","LOW"],
        "Confidence": ["High","High","Low","High","Low","Any"],
        "Evidence Status": ["Contradicted / safety-floor","Supported/Contradicted","Unsupported","Supported","Unsupported","Any"],
        "Typical Decision Region": [
            "🔴 Safety floor — Block/Redact (all profiles)",
            "🔴 Block or Edit — clear violation",
            "🟡 Escalate per profile (often Human Review)",
            "🟠 Flag or Edit",
            "🟢 Allow-with-caveat or Flag",
            "🟢 Allow — logged, feeds session state",
        ],
    }
    import pandas as pd
    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 3 — Decision Reasoning
# ===========================================================================
with tab3:
    st.markdown('<div class="section-header">Decision Reasoning — Rules, Evidence, Policy Version</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="constraint-notice">
      Every decision names the specific rule that fired and references the policy version.
      Any decision must be answerable with "why did ControlPlane make this decision?" (§15)
    </div>""", unsafe_allow_html=True)

    # Show the 6 rules
    rules = [
        ("Rule 1", "Safety Floor", "CRITICAL severity + high confidence + policy-defined safety-floor category → Block/Redact (overrides ALL below, regardless of profile)", "#dc2626"),
        ("Rule 2", "Clear Violation", "HIGH/CRITICAL + high confidence + evidence CONTRADICTED or clearly violating → Block or Edit/Redact per block_threshold. Exposure-type → Redact; unsafe-content → Block.", "#ea580c"),
        ("Rule 3", "Uncertain High Risk", "HIGH/CRITICAL + (low confidence OR UNSUPPORTED/PARTIALLY_SUPPORTED) → follow policy.low_confidence_action. Chatbot=edit_soften, Copilot=allow_with_flag, Regulated=human_review.", "#d97706"),
        ("Rule 4", "Medium Flag", "MEDIUM severity above policy.human_review_threshold → Flag or Human Review per profile.", "#d97706"),
        ("Rule 5", "Low Allow", "LOW severity → Allow. Still logged. Contributes to session state.", "#059669"),
        ("Rule 6", "Session Escalation", "Session-accumulated risk >= session_risk_threshold → Escalate an otherwise-Allow decision, INDEPENDENT of current turn's own severity.", "#6D28D9"),
    ]

    for rule_id, name, desc, color in rules:
        st.markdown(f"""
        <div class="signal-card" style="border-left:3px solid {color};">
          <div style="display:flex;gap:12px;align-items:flex-start;">
            <span style="font-family:'JetBrains Mono',monospace;font-weight:700;color:{color};
                         font-size:0.85rem;min-width:60px;">{rule_id}</span>
            <div>
              <strong style="color:#18181B;">{name}</strong>
              <p style="color:#52525B;font-size:0.83rem;margin:0.3rem 0 0 0;line-height:1.5;">{desc}</p>
            </div>
          </div>
        </div>""", unsafe_allow_html=True)

    st.markdown("#### Recent Decisions from Audit Log")
    audit_data = call_api("get", "/audit?limit=10")
    if audit_data:
        for rec in audit_data[:5]:
            rule_n = "?"
            reason = rec.get("decision_reason", "")
            if "Rule 1" in reason: rule_n = "1"
            elif "Rule 2" in reason: rule_n = "2"
            elif "Rule 3" in reason: rule_n = "3"
            elif "Rule 4" in reason: rule_n = "4"
            elif "Rule 5" in reason: rule_n = "5"
            elif "Rule 6" in reason: rule_n = "6"

            st.markdown(f"""
            <div class="signal-card">
              <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:0.5rem;">
                <code style="color:#6D28D9;font-size:0.78rem;">{rec.get('request_id','')}</code>
                <div style="display:flex;gap:6px;">
                  {severity_badge(rec.get('aggregated_severity','LOW'))}
                  {action_badge(rec.get('final_action','allow'))}
                  <span class="rule-pill">Rule {rule_n}</span>
                </div>
              </div>
              <div style="font-size:0.78rem;color:#52525B;">
                Profile: <code style="color:#6D28D9">{rec.get('use_case_profile','')}</code> ·
                Policy: <code style="color:#6D28D9">{rec.get('policy_version','')}</code> ·
                Latency: <code style="color:#6D28D9">{rec.get('latency_ms',0):.0f}ms</code>
              </div>
              <div style="font-size:0.8rem;color:#18181B;margin-top:0.5rem;line-height:1.5;">{reason[:200]}...</div>
            </div>""", unsafe_allow_html=True)


# ===========================================================================
# TAB 4 — Profile Switcher
# ===========================================================================
with tab4:
    st.markdown('<div class="section-header">Profile Switcher — Same Input, Different Policy</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="constraint-notice">
      Demo 1: Identical model output evaluated under two profiles.
      Behavior changes because of POLICY CONFIGURATION — not code branches.
      This is the §3 Design Thesis: one framework, context-driven behavior.
    </div>""", unsafe_allow_html=True)

    ps_output = st.text_area(
        "Model Output (identical input for both profiles)",
        value=(
            "Based on our proprietary analysis, ControlTech holds 34.7% market share "
            "in APAC as of Q2 2026, making it the undisputed market leader in "
            "enterprise AI governance solutions with a YoY growth rate of 127%."
        ),
        height=100,
        key="ps_output",
    )
    ps_prompt = st.text_input(
        "Prompt", value="What is our market position in APAC?", key="ps_prompt"
    )

    pc1, pc2 = st.columns(2)
    with pc1:
        ps_profile1 = st.selectbox(
            "Profile A",
            ["customer_facing_chatbot", "internal_copilot", "regulated_decision_support"],
            index=1,
            key="ps_p1",
            format_func=lambda x: {"customer_facing_chatbot":"🤖 Customer Chatbot","internal_copilot":"💼 Internal Copilot","regulated_decision_support":"⚖️ Regulated"}[x],
        )
    with pc2:
        ps_profile2 = st.selectbox(
            "Profile B",
            ["customer_facing_chatbot", "internal_copilot", "regulated_decision_support"],
            index=2,
            key="ps_p2",
            format_func=lambda x: {"customer_facing_chatbot":"🤖 Customer Chatbot","internal_copilot":"💼 Internal Copilot","regulated_decision_support":"⚖️ Regulated"}[x],
        )

    if st.button("▶ Compare Profiles", key="ps_run"):
        results_ps = {}
        for pid, prof in [("A", ps_profile1), ("B", ps_profile2)]:
            payload = {
                "session_id": f"profile-switch-{pid}-{ps_profile1[:3]}-{ps_profile2[:3]}",
                "profile": prof,
                "prompt": ps_prompt,
                "model_output": ps_output,
                "trusted_evidence": None,
                "model_id": "mock-llm-v1",
            }
            with st.spinner(f"Evaluating Profile {pid}..."):
                r = call_api("post", "/evaluate", json=payload)
            results_ps[pid] = (prof, r)

        col_a, col_b = st.columns(2)
        for col, (pid, (prof, r)) in zip([col_a, col_b], results_ps.items()):
            with col:
                profile_labels = {
                    "customer_facing_chatbot": "🤖 Customer Chatbot",
                    "internal_copilot": "💼 Internal Copilot",
                    "regulated_decision_support": "⚖️ Regulated Decision-Support",
                }
                st.markdown(f"#### Profile {pid}: {profile_labels.get(prof, prof)}")
                if r:
                    decision = r.get("decision", {})
                    action = decision.get("action", "allow")
                    rule = decision.get("rule_fired", 0)
                    reason = decision.get("reason", "")

                    st.markdown(f"""
                    <div class="cp-card" style="border-left:3px solid {severity_color(r.get('aggregated_severity','LOW'))};">
                      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:0.6rem;">
                        {action_badge(action)}
                        {severity_badge(r.get('aggregated_severity','LOW'))}
                        <span class="rule-pill">Rule {rule}</span>
                      </div>
                      <p style="font-size:0.83rem;color:#52525B;line-height:1.5;">{reason[:300]}</p>
                    </div>""", unsafe_allow_html=True)

                    for sig in r.get("signals", []):
                        render_signal_card(sig)


# ===========================================================================
# TAB 5 — Audit Log
# ===========================================================================
with tab5:
    st.markdown('<div class="section-header">Audit Log — All Decisions (§15)</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="constraint-notice">
      Every decision writes a full audit record with all 15 fields: timestamp, request_id,
      session_id, profile, policy_version, model_id, latency_ms, signals, aggregated_severity,
      confidence, evidence_status, session_risk_before/after, final_action, decision_reason.
    </div>""", unsafe_allow_html=True)

    al_col1, al_col2, al_col3 = st.columns(3)
    with al_col1:
        al_profile = st.selectbox(
            "Filter by Profile",
            ["All", "customer_facing_chatbot", "internal_copilot", "regulated_decision_support"],
            key="al_profile",
        )
    with al_col2:
        al_action = st.selectbox(
            "Filter by Action",
            ["All", "allow", "allow_with_flag", "edit_soften", "redact", "flag", "human_review", "block"],
            key="al_action",
        )
    with al_col3:
        al_limit = st.number_input("Max records", value=20, min_value=5, max_value=100, key="al_limit")

    if st.button("🔄 Refresh", key="al_refresh"):
        st.session_state["al_data"] = None

    params = f"?limit={al_limit}"
    if al_profile != "All":
        params += f"&profile={al_profile}"
    if al_action != "All":
        params += f"&action={al_action}"

    audit_records = call_api("get", f"/audit{params}")
    if audit_records:
        if not audit_records:
            st.info("No audit records yet. Run some evaluations first.")
        else:
            import pandas as pd
            rows = []
            for rec in audit_records:
                rows.append({
                    "Request ID": rec.get("request_id",""),
                    "Timestamp": rec.get("timestamp","")[:19].replace("T"," "),
                    "Profile": rec.get("use_case_profile",""),
                    "Policy": rec.get("policy_version",""),
                    "Severity": rec.get("aggregated_severity",""),
                    "Action": rec.get("final_action",""),
                    "Confidence": f"{rec.get('confidence',0):.2f}",
                    "Evidence": rec.get("evidence_status",""),
                    "SR Before": f"{rec.get('session_risk_before',0):.3f}",
                    "SR After": f"{rec.get('session_risk_after',0):.3f}",
                    "Latency ms": f"{rec.get('latency_ms',0):.0f}",
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Expandable detail view
            for rec in audit_records[:3]:
                with st.expander(f"📄 {rec.get('request_id','')} — {rec.get('final_action','')}"):
                    st.markdown(f"""
                    **Decision Reason:** {rec.get('decision_reason','')}

                    **Policy Version:** `{rec.get('policy_version','')}` ·
                    **Model:** `{rec.get('model_id','')}` ·
                    **Latency:** `{rec.get('latency_ms',0):.0f}ms`
                    """)
                    for sig in rec.get("signals", []):
                        render_signal_card(sig)


# ===========================================================================
# TAB 6 — Review Queue
# ===========================================================================
with tab6:
    st.markdown('<div class="section-header">Human Review Queue (§14)</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="constraint-notice">
      Purpose: high-stakes + uncertain → human review. NOT uncertain → automatic block.
      Reviewer actions: Approve / Edit / Reject. Full context provided for every item.
    </div>""", unsafe_allow_html=True)

    rq_pending_only = st.checkbox("Show pending only", value=True, key="rq_pending")
    if st.button("🔄 Refresh Queue", key="rq_refresh"):
        pass  # forces re-run

    queue_items = call_api("get", f"/review-queue?pending_only={str(rq_pending_only).lower()}")
    if queue_items is not None:
        if not queue_items:
            st.info("No items in review queue. Run Demo 1 or Demo 5 to generate human-review cases.")
        else:
            st.markdown(f"**{len(queue_items)} item(s) in queue**")
            for item in queue_items:
                sev_signals = item.get("risk_signals", [])
                dominant_sev = max((s.get("severity","LOW") for s in sev_signals),
                                   key=lambda s: {"LOW":0,"MEDIUM":1,"HIGH":2,"CRITICAL":3}.get(s,0),
                                   default="LOW")

                with st.expander(
                    f"{'⏳' if not item.get('reviewer_action') else '✅'} "
                    f"{item.get('review_id','')} — {item.get('use_case_profile','')} "
                    f"— {item.get('recommended_action','').upper()}",
                    expanded=not item.get("reviewer_action"),
                ):
                    col_m1, col_m2, col_m3 = st.columns(3)
                    with col_m1:
                        st.markdown(f"""
                        <div class="metric-box">
                          <div class="label">Session Risk</div>
                          <div class="value">{item.get('session_risk',0):.3f}</div>
                        </div>""", unsafe_allow_html=True)
                    with col_m2:
                        st.markdown(f"""
                        <div class="metric-box">
                          <div class="label">Dominant Severity</div>
                          <div style="margin-top:0.3rem">{severity_badge(dominant_sev)}</div>
                        </div>""", unsafe_allow_html=True)
                    with col_m3:
                        st.markdown(f"""
                        <div class="metric-box">
                          <div class="label">Recommended</div>
                          <div style="margin-top:0.3rem">{action_badge(item.get('recommended_action','human_review'))}</div>
                        </div>""", unsafe_allow_html=True)

                    st.markdown(f"""
                    <div class="cp-card" style="margin-top:0.6rem;">
                      <div style="font-size:0.72rem;color:#52525B;margin-bottom:0.3rem;">ESCALATION REASON</div>
                      <p style="color:#18181B;font-size:0.85rem;line-height:1.5;">{item.get('escalation_reason','')}</p>
                    </div>""", unsafe_allow_html=True)

                    col_req, col_out = st.columns(2)
                    with col_req:
                        st.markdown("**Request**")
                        st.markdown(f"""<div class="cp-card" style="font-size:0.82rem;color:#52525B;">{item.get('request','')}</div>""", unsafe_allow_html=True)
                    with col_out:
                        st.markdown("**Model Output**")
                        st.markdown(f"""<div class="cp-card" style="font-size:0.82rem;color:#52525B;">{item.get('model_output','')[:300]}...</div>""", unsafe_allow_html=True)

                    st.markdown("**Risk Signals**")
                    for sig in item.get("risk_signals", []):
                        render_signal_card(sig)

                    # Reviewer actions
                    if not item.get("reviewer_action"):
                        st.markdown("---")
                        action_col1, action_col2, action_col3, note_col = st.columns([1, 1, 1, 3])
                        review_id = item.get("review_id", "")
                        reviewer_note = note_col.text_input("Note (optional)", key=f"note_{review_id}")
                        with action_col1:
                            if st.button("✅ Approve", key=f"approve_{review_id}"):
                                r = call_api("patch", f"/review-queue/{review_id}",
                                           json={"reviewer_action": "approve", "reviewer_note": reviewer_note})
                                if r:
                                    st.success("Approved")
                                    st.rerun()
                        with action_col2:
                            if st.button("✏️ Edit", key=f"edit_{review_id}"):
                                r = call_api("patch", f"/review-queue/{review_id}",
                                           json={"reviewer_action": "edit", "reviewer_note": reviewer_note})
                                if r:
                                    st.success("Marked for Edit")
                                    st.rerun()
                        with action_col3:
                            if st.button("❌ Reject", key=f"reject_{review_id}"):
                                r = call_api("patch", f"/review-queue/{review_id}",
                                           json={"reviewer_action": "reject", "reviewer_note": reviewer_note})
                                if r:
                                    st.success("Rejected")
                                    st.rerun()
                    else:
                        action_color = {"approve": "#059669", "edit": "#d97706", "reject": "#dc2626"}.get(
                            item.get("reviewer_action",""), "#52525B"
                        )
                        st.markdown(f"""
                        <div style="background:#FFFFFF;border:1px solid {action_color};border-radius:8px;
                                    padding:0.6rem 1rem;font-size:0.82rem;color:{action_color};">
                          ✓ Reviewed: {item.get('reviewer_action','').upper()} at {item.get('reviewed_at','')[:19]}
                          {f" — Note: {item.get('reviewer_note')}" if item.get('reviewer_note') else ""}
                        </div>""", unsafe_allow_html=True)

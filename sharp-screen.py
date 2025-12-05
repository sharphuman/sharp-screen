import streamlit as st
import pandas as pd
import json
import os
import time
from anthropic import Anthropic
from openai import OpenAI
from pypdf import PdfReader
from docx import Document

# --- CONFIGURATION ---
APP_VERSION = "v2.1"
st.set_page_config(page_title="Sharp Screen", page_icon="🎯", layout="wide")

# --- SHARP-STANDARDS: CSS PALETTE ---
st.markdown("""
<style>
    /* MAIN BACKGROUND */
    .stApp { background-color: #0e1117; color: #e0e0e0; }
    
    /* INPUTS */
    .stTextArea textarea, .stTextInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1c1c1c !important;
        color: #00e5ff !important;
        border: 1px solid #333 !important;
        font-family: 'Helvetica Neue', sans-serif !important;
    }
    
    /* UPLOADER (SQUARE & CENTERED) */
    div[data-testid="stFileUploader"] section {
        background-color: #161b22;
        border: 2px dashed #00e5ff; 
        border-radius: 10px;
        min-height: 120px !important; 
        display: flex; align-items: center; justify-content: center;
    }
    div[data-testid="stFileUploader"] section:hover { border-color: #39ff14; }

    /* HEADERS */
    h1, h2, h3 {
        background: -webkit-linear-gradient(45deg, #00e5ff, #d500f9);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700 !important;
    }
    
    /* BUTTONS (NEON GREEN GRADIENT) */
    div[data-testid="stButton"] button {
        background: linear-gradient(45deg, #00e5ff, #00ffab) !important;
        color: #000000 !important;
        border: none !important;
        font-weight: 800 !important;
        text-transform: uppercase;
        transition: transform 0.2s;
    }
    div[data-testid="stButton"] button:hover {
        transform: scale(1.02);
        box-shadow: 0 0 15px #00ffab;
    }
    
    /* METRICS & STATUS */
    div[data-testid="stMetricValue"] {
        color: #39ff14 !important; 
        font-family: monospace;
        font-size: 1.4rem !important;
    }
    .status-box {
        background-color: #1c1c1c;
        border-left: 3px solid #00e5ff;
        padding: 10px;
        font-family: monospace;
        color: #aaa;
        font-size: 0.9rem;
    }
    
    .stAlert { background-color: #1c1c1c; border: 1px solid #333; color: #00e5ff; }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'analysis_result' not in st.session_state: st.session_state.analysis_result = None
if 'transcript_text' not in st.session_state: st.session_state.transcript_text = ""
if 'cv_text' not in st.session_state: st.session_state.cv_text = ""
if 'jd_text' not in st.session_state: st.session_state.jd_text = ""
if 'processing_log' not in st.session_state: st.session_state.processing_log = "System Ready."
if 'total_cost' not in st.session_state: st.session_state.total_cost = 0.0
if 'costs' not in st.session_state: st.session_state.costs = {"OpenAI (Audio)": 0.0, "Anthropic (Intel)": 0.0}

# --- SECRETS ---
try:
    ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
except:
    st.error("❌ Missing API Keys. Check secrets.toml")
    st.stop()

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- SHARP-STANDARDS: UTILITIES ---

def update_status(msg):
    st.session_state.processing_log = msg
    # No rerun here to avoid loop, just state update

def track_cost(provider, amount):
    st.session_state.costs[provider] += amount
    st.session_state.total_cost += amount

def extract_text_from_file(file):
    try:
        file_type = file.name.split('.')[-1].lower()
        if file_type in ['mp3', 'm4a', 'wav', 'mp4', 'mpeg', 'mpga']:
            return transcribe_audio(file)
        elif file_type == 'pdf':
            reader = PdfReader(file)
            return "\n".join([page.extract_text() for page in reader.pages])
        elif file_type == 'docx':
            doc = Document(file)
            return "\n".join([para.text for para in doc.paragraphs])
        elif file_type in ['txt', 'md']:
            return file.read().decode("utf-8")
        return "Unsupported format."
    except Exception as e:
        return f"Error extracting {file.name}: {str(e)}"

def transcribe_audio(file):
    try:
        transcript = openai_client.audio.transcriptions.create(model="whisper-1", file=file)
        track_cost("OpenAI (Audio)", 0.06) 
        return transcript.text
    except Exception as e:
        return f"Whisper Error: {str(e)}"

def clean_json_response(txt):
    txt = txt.strip()
    if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
    elif "```" in txt: txt = txt.split("```")[1].split("```")[0]
    return txt.strip()

def analyze_forensic(transcript, cv_text, jd_text):
    system_prompt = f"""
    You are a FORENSIC Talent Auditor. Evaluate the hiring interaction with extreme detail.
    
    **DATA POINTS:**
    1. **JD (The Standard):** What is required.
    2. **CV (The Claim):** What the candidate says they did.
    3. **TRANSCRIPT (The Evidence):** What actually happened.

    **MISSION:**
    Determine if the candidate is a "Paper Tiger" (Good CV, Bad Interview) or the "Real Deal".

    **OUTPUT JSON STRUCTURE (Strict):**
    {{
        "executive_summary": "A high-level narrative paragraph for the Hiring Manager. Summarize the candidate's fit, main risks, and final recommendation. Be direct.",
        "candidate": {{
            "name": "Name",
            "scores": {{
                "cv_match_score": 0, 
                "interview_performance_score": 0,
                "technical_depth": 0,
                "culture_fit": 0
            }},
            "fit_analysis": {{
                "gap_analysis": "Compare CV claims vs Interview proof. Did they struggle to explain things listed on their CV?",
                "jd_vs_transcript": "Specifically analyze if their SPOKEN answers demonstrated the requirements listed in the JD."
            }},
            "strengths": ["Detailed bullet"],
            "red_flags": ["Detailed bullet"],
            "verdict": "Strong Hire / Hire / Risky / No Hire"
        }},
        "recruiter": {{
            "scores": {{
                "question_quality": 0,
                "jd_coverage": 0
            }},
            "missed_opportunities": ["List critical JD requirements the recruiter failed to vet"],
            "coaching_tip": "Actionable advice."
        }}
    }}
    """

    user_msg = f"JD: {jd_text[:15000]}\nCV: {cv_text[:15000]}\nTRANSCRIPT: {transcript[:50000]}"

    try:
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            temperature=0.1, 
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}]
        )
        track_cost("Anthropic (Intel)", 0.03) 
        return json.loads(clean_json_response(message.content[0].text))
    except Exception as e:
        return {"error": str(e)}

def render_neon_progress(label, score, max_score=10):
    pct = (score / max_score) * 100
    color = "#ff4b4b" # Red
    if score >= 5: color = "#ffa700" # Orange
    if score >= 7: color = "#39ff14" # Green
    if score >= 9: color = "#00e5ff" # Cyan (Elite)

    st.markdown(f"""
    <div style="margin-bottom: 12px;">
        <div style="display: flex; justify-content: space-between; font-size: 0.9rem;">
            <span style="color: #e0e0e0;">{label}</span>
            <span style="color: {color}; font-weight: bold;">{score}/10</span>
        </div>
        <div style="background-color: #222; height: 8px; border-radius: 4px; margin-top: 4px;">
            <div style="background-color: {color}; width: {pct}%; height: 100%; border-radius: 4px; box-shadow: 0 0 6px {color};"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- LAYOUT ---

# SHARP-STANDARDS: TOP RIGHT HEADER
c_title, c_meta = st.columns([3, 1])

with c_title:
    st.title("🎯 Sharp Screen")
    st.caption("Context-Aware Interview Intelligence")

with c_meta:
    # Version & Cost
    st.markdown(f"<div style='text-align: right; color: #666;'>{APP_VERSION}</div>", unsafe_allow_html=True)
    st.metric("Session Cost", f"${st.session_state.total_cost:.4f}")
    
    # SHARP-STANDARDS: "WORKING" TILE
    # This looks complicated but just echoes the log state
    st.markdown(f"""
    <div class="status-box">
        <span style="color: #00e5ff;">● SYSTEM ACTIVE</span><br>
        <span style="font-size: 0.8rem;">{st.session_state.processing_log}</span>
    </div>
    """, unsafe_allow_html=True)

# INPUTS
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("### 1. JD")
    jd_file = st.file_uploader("Job Description", type=['pdf','docx','txt','md'], key="jd", label_visibility="collapsed")
with c2:
    st.markdown("### 2. CV")
    cv_file = st.file_uploader("Candidate CV", type=['pdf','docx','txt','md'], key="cv", label_visibility="collapsed")
with c3:
    st.markdown("### 3. Transcript")
    call_file = st.file_uploader("Interview Audio/Text", type=['mp3','wav','m4a','pdf','docx','txt','md'], key="call", label_visibility="collapsed")

st.write("")
start_btn = st.button("Start Forensic Audit", type="primary", use_container_width=True)

if start_btn:
    if not (jd_file and cv_file and call_file):
        st.warning("⚠️ Please upload ALL 3 files.")
    else:
        try:
            # Use st.status for the fancy dropdown loading effect
            with st.status("🚀 Initiating Sharp-Screen Protocol...", expanded=True) as status:
                
                st.write("📂 Ingesting unstructured data streams...")
                update_status("Vectorizing Documents...")
                st.session_state.jd_text = extract_text_from_file(jd_file)
                st.session_state.cv_text = extract_text_from_file(cv_file)
                st.session_state.transcript_text = extract_text_from_file(call_file)
                
                st.write("🔍 Triangulating semantic fit...")
                update_status("Running Gap Analysis...")
                
                st.write("⚖️ Auditing Interviewer Bias & Coverage...")
                
                res = analyze_forensic(st.session_state.transcript_text, st.session_state.cv_text, st.session_state.jd_text)
                st.session_state.analysis_result = res
                
                update_status("Forensic Audit Compiled.")
                status.update(label="✅ Intelligence Ready", state="complete", expanded=False)
                
        except Exception as e:
            st.error(f"Critical Error: {e}")
            st.stop()

# --- DASHBOARD ---
if st.session_state.analysis_result:
    r = st.session_state.analysis_result
    if "error" in r:
        st.error(r['error'])
    else:
        cand = r['candidate']
        rec = r['recruiter']

        # EXECUTIVE SUMMARY
        st.divider()
        st.markdown("### 📢 Executive Summary")
        st.info(r['executive_summary'])
        st.divider()

        c_cand, c_rec = st.columns(2)
        
        # CANDIDATE AUDIT
        with c_cand:
            st.subheader(f"👤 {cand['name']}")
            st.caption(f"Verdict: **{cand['verdict']}**")
            
            with st.container(border=True):
                s = cand['scores']
                st.markdown("#### 📐 Fit Analysis")
                render_neon_progress("📄 Paper Fit (CV vs JD)", s['cv_match_score'])
                render_neon_progress("🗣️ Actual Fit (Interview vs JD)", s['interview_performance_score'])
                
                st.markdown("#### 🧠 Deep Dive")
                render_neon_progress("Technical Depth", s['technical_depth'])
                render_neon_progress("Culture Fit", s['culture_fit'])
                
            with st.expander("🔎 View Gap Analysis", expanded=True):
                st.markdown("**CV vs Reality:**")
                st.write(cand['fit_analysis']['gap_analysis'])
                st.markdown("**Transcript vs JD:**")
                st.write(cand['fit_analysis']['jd_vs_transcript'])

            st.markdown("#### 🚩 Flags & Risks")
            if cand.get('red_flags'):
                for f in cand['red_flags']: st.warning(f"{f}")
            else:
                st.success("No major red flags detected.")

        # RECRUITER AUDIT
        with c_rec:
            st.subheader("🎧 Recruiter Audit")
            with st.container(border=True):
                rs = rec['scores']
                render_neon_progress("Question Quality", rs['question_quality'])
                render_neon_progress("JD Coverage", rs['jd_coverage'])
                
                st.markdown("---")
                st.markdown("#### ⚠️ Missed Topics")
                if rec['missed_opportunities']:
                    for m in rec['missed_opportunities']: st.markdown(f"❌ {m}")
                else:
                    st.success("Excellent coverage.")
                
                st.info(f"**💡 Coach's Tip:** {rec['coaching_tip']}")

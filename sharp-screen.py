import streamlit as st
import pandas as pd
import json
import os
from anthropic import Anthropic
from pypdf import PdfReader
from docx import Document

# ==============================================================================
# 🧠 SHARP-STANDARDS PROTOCOL (Screen v2.2)
# ==============================================================================

APP_VERSION = "v2.2"
st.set_page_config(page_title="Sharp Screen", page_icon="📋", layout="wide")

# --- CSS: SHARP PALETTE ---
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
    
    /* UPLOADER */
    div[data-testid="stFileUploader"] section {
        background-color: #161b22;
        border: 2px dashed #00e5ff; 
        border-radius: 10px;
        min-height: 120px !important; 
        display: flex; align-items: center; justify-content: center;
    }
    div[data-testid="stFileUploader"] section:hover { border-color: #00ffab; }

    /* HEADERS */
    h1, h2, h3 {
        background: -webkit-linear-gradient(45deg, #00e5ff, #d500f9);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700 !important;
    }
    
    /* BUTTONS */
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
    
    /* STATUS BOX */
    .status-box {
        background-color: #1c1c1c;
        border-left: 3px solid #00e5ff;
        padding: 10px;
        font-family: monospace;
        color: #aaa;
        font-size: 0.9rem;
    }
    
    div[data-testid="stMetricValue"] { color: #39ff14 !important; font-family: monospace; }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'screen_results' not in st.session_state: st.session_state.screen_results = []
if 'total_cost' not in st.session_state: st.session_state.total_cost = 0.0
if 'processing_log' not in st.session_state: st.session_state.processing_log = "Ready for Batch."

# --- SECRETS & AUTH (FIXED) ---
anthropic_key = None

# 1. Try Streamlit Secrets
if "ANTHROPIC_API_KEY" in st.secrets:
    anthropic_key = st.secrets["ANTHROPIC_API_KEY"]
# 2. Try Environment Variables (Fallback)
elif "ANTHROPIC_API_KEY" in os.environ:
    anthropic_key = os.environ["ANTHROPIC_API_KEY"]

# 3. Hard Stop if Missing
if not anthropic_key:
    st.error("❌ Critical Error: `ANTHROPIC_API_KEY` not found in secrets.toml or environment variables.")
    st.stop()

# Initialize Client with Verified Key
client = Anthropic(api_key=anthropic_key)

# --- UTILITIES ---

def update_status(msg):
    st.session_state.processing_log = msg

def track_cost(amount):
    st.session_state.total_cost += amount

def extract_text(file):
    try:
        if file.name.endswith('.pdf'):
            reader = PdfReader(file)
            return "\n".join([p.extract_text() for p in reader.pages])
        elif file.name.endswith('.docx'):
            return "\n".join([p.text for p in Document(file).paragraphs])
        elif file.name.endswith('.txt'):
            return file.read().decode("utf-8")
        return ""
    except: return ""

def analyze_cv(cv_text, jd_text, filename):
    system_prompt = f"""
    You are an Expert Technical Recruiter. Screen this CV against the Job Description.

    **JOB DESCRIPTION:**
    {jd_text[:5000]}

    **CANDIDATE CV:**
    {cv_text[:10000]}

    **TASK:**
    Score the candidate (0-100) based on strict requirements match.
    
    **OUTPUT JSON:**
    {{
        "candidate_name": "Extract Name or Filename",
        "match_score": 0,
        "summary": "1 sentence summary of fit.",
        "key_skills_found": ["Skill 1", "Skill 2"],
        "missing_skills": ["Missing 1", "Missing 2"],
        "red_flags": ["Flag 1" or null],
        "verdict": "Interview / Maybe / Reject"
    }}
    """
    
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            temperature=0.1,
            messages=[{"role": "user", "content": system_prompt}]
        )
        track_cost(0.01) # Approx cost per CV
        
        txt = msg.content[0].text
        if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
        elif "```" in txt: txt = txt.split("```")[1].split("```")[0]
        return json.loads(txt.strip())
    except Exception as e:
        return {"candidate_name": filename, "match_score": 0, "summary": f"Error: {e}", "verdict": "Error"}

# --- LAYOUT ---

c_title, c_meta = st.columns([3, 1])
with c_title:
    st.title("📋 Sharp Screen")
    st.caption("Bulk Resume Ranking & Intelligence")
with c_meta:
    st.markdown(f"<div style='text-align: right; color: #666;'>{APP_VERSION}</div>", unsafe_allow_html=True)
    st.metric("Session Cost", f"${st.session_state.total_cost:.4f}")
    st.markdown(f"<div class='status-box'><span style='color: #39ff14;'>● SYSTEM ACTIVE</span><br>{st.session_state.processing_log}</div>", unsafe_allow_html=True)

# INPUTS
c1, c2 = st.columns([1, 2])
with c1:
    st.markdown("### 1. The Standard (JD)")
    jd_file = st.file_uploader("Upload Job Description", type=['pdf','docx','txt'], key="jd")
with c2:
    st.markdown("### 2. The Applicants (CVs)")
    cv_files = st.file_uploader("Upload Resumes (Bulk)", type=['pdf','docx','txt'], accept_multiple_files=True, key="cvs")

st.write("")
if st.button("Start Bulk Screening", type="primary", use_container_width=True):
    if not jd_file or not cv_files:
        st.warning("⚠️ Please upload both a JD and at least one CV.")
    else:
        st.session_state.screen_results = []
        
        with st.status("🚀 Processing Batch...", expanded=True) as status:
            update_status("Reading Job Description...")
            jd_text = extract_text(jd_file)
            
            total = len(cv_files)
            for i, cv in enumerate(cv_files):
                update_status(f"Analyzing {i+1}/{total}: {cv.name}...")
                st.write(f"📄 Reading {cv.name}...")
                
                cv_text = extract_text(cv)
                if cv_text:
                    res = analyze_cv(cv_text, jd_text, cv.name)
                    st.session_state.screen_results.append(res)
            
            update_status("Batch Complete.")
            status.update(label="✅ Ranking Complete!", state="complete", expanded=False)

# --- LEADERBOARD ---
if st.session_state.screen_results:
    st.divider()
    st.subheader("🏆 Candidate Leaderboard")
    
    sorted_results = sorted(st.session_state.screen_results, key=lambda x: x.get('match_score', 0), reverse=True)
    
    df_data = []
    for r in sorted_results:
        df_data.append({
            "Name": r.get('candidate_name', 'Unknown'),
            "Score": r.get('match_score', 0),
            "Verdict": r.get('verdict', 'N/A'),
            "Summary": r.get('summary', ''),
            "Missing": ", ".join(r.get('missing_skills', []))
        })
    
    df = pd.DataFrame(df_data)
    
    st.dataframe(
        df,
        column_config={
            "Score": st.column_config.ProgressColumn("Fit Score", format="%d", min_value=0, max_value=100),
            "Verdict": st.column_config.TextColumn("Recommendation"),
        },
        use_container_width=True,
        hide_index=True
    )
    
    with st.expander("🔍 Detailed Breakdown"):
        for r in sorted_results:
            st.markdown(f"**{r.get('candidate_name')}** ({r.get('match_score')}/100)")
            st.caption(r.get('summary'))
            c_a, c_b = st.columns(2)
            with c_a:
                st.success(f"**Skills:** {', '.join(r.get('key_skills_found', []))}")
            with c_b:
                st.error(f"**Missing:** {', '.join(r.get('missing_skills', []))}")
            st.divider()

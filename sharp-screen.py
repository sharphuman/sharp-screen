import streamlit as st
import pandas as pd
import pdfplumber
import docx
from docx import Document
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import io
import json
import zipfile
import urllib.parse
import requests
import random
from fpdf import FPDF

# --- CONFIGURATION ---
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
GMAIL_USER = st.secrets.get("GMAIL_USER")
GMAIL_APP_PASSWORD = st.secrets.get("GMAIL_APP_PASSWORD")
SLACK_WEBHOOK = st.secrets.get("SLACK_WEBHOOK_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

# --- HELPER: FILE PROCESSING ---
def read_file_content(file_obj, filename):
    text = ""
    filename = filename.lower()
    try:
        if filename.endswith(".pdf"):
            with pdfplumber.open(file_obj) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t: text += t + "\n"
        elif filename.endswith(".docx"):
            doc = docx.Document(file_obj)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif filename.endswith(".txt"):
            text = str(file_obj.read(), "utf-8", errors='ignore')
    except Exception as e:
        return f"Error reading {filename}: {e}"
    return text[:4000]

def process_uploaded_files(uploaded_files):
    processed_docs = []
    for uploaded_file in uploaded_files:
        if uploaded_file.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(uploaded_file) as z:
                    for filename in z.namelist():
                        if "__MACOSX" in filename or filename.endswith("/"): continue
                        if filename.lower().endswith(('.pdf', '.docx', '.txt')):
                            with z.open(filename) as f:
                                file_content = io.BytesIO(f.read())
                                text = read_file_content(file_content, filename)
                                processed_docs.append({"name": filename, "text": text})
            except: pass
        else:
            text = read_file_content(uploaded_file, uploaded_file.name)
            processed_docs.append({"name": uploaded_file.name, "text": text})
    return processed_docs

# --- HELPER: DATA GENERATOR (DYNAMIC) ---
def create_pdf(content):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    # Handle unicode characters by replacing them with closest ascii or removing
    safe_content = content.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, safe_content)
    return pdf.output(dest='S').encode('latin-1')

def create_docx(content):
    doc = Document()
    for line in content.split('\n'):
        doc.add_paragraph(line)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def generate_dummy_data(jd_text=None):
    """
    Generates test resumes in mixed formats (PDF, DOCX, TXT). 
    If JD is provided -> Uses AI to generate custom matching/mismatching candidates.
    If JD is missing -> Uses default Infrastructure profiles.
    """
    zip_buffer = io.BytesIO()
    resumes_data = []

    # OPTION A: AI GENERATION (If JD exists)
    if jd_text and len(jd_text) > 50:
        try:
            # 1. Ask GPT to create 5 archetypes based on the JD
            prompt = f"""
            Analyze this Job Description:
            {jd_text[:1500]}
            
            Create 5 distinct fake candidate resumes (plain text format) for testing a ranking algorithm:
            1. "The Star" (Perfect match, great tenure).
            2. "The Stretch" (Good skills, but junior/missing one key thing).
            3. "The Job Hopper" (Great skills, but 4 jobs in 2 years).
            4. "The Pivot" (Good soft skills, but wrong technical background).
            5. "The Mismatch" (Completely wrong role).
            
            Output strict JSON with a list of objects under key "resumes":
            {{
                "resumes": [
                    {{ "filename": "Candidate_Star", "content": "Name: ... \\nSummary:..." }},
                    ...
                ]
            }}
            """
            response = client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}]
            )
            data = json.loads(response.choices[0].message.content)
            resumes_data = data.get('resumes', [])
            
            # We replicate the 5 personas to make a list of 15 files
            expanded_resumes = []
            for i in range(1, 16):
                template = resumes_data[(i - 1) % len(resumes_data)]
                new_name = f"Applicant_{i}_{template['filename']}"
                new_content = template['content'].replace("Name:", f"Name: Applicant_{i}")
                expanded_resumes.append({"filename": new_name, "content": new_content})
            resumes_data = expanded_resumes

        except Exception as e:
            print(f"AI Generation failed: {e}")

    # OPTION B: HARDCODED FALLBACK (Infrastructure focus)
    if not resumes_data:
        # 1. The "Perfect" Architecture Profile
        perfect_bio = """
        SUMMARY: Senior Infrastructure Consultant with 15 years of experience specializing in Active Directory, Azure Identity, and VMware. 
        Led 5 major M&A consolidation projects using Quest Migration Manager. MCSE and VCP Certified.
        
        EXPERIENCE:
        - Global Bank (2018-Present): Lead Architect. Migrated 40k users to Azure AD. Implemented Tier 0 Admin Security.
        - Healthcare Org (2014-2018): Senior Engineer. Managed 500+ ESXi hosts and VDI environment.
        
        SKILLS: Active Directory, Azure AD Connect, Quest Migration Manager, PowerShell (Advanced), VMware vSphere 7.0.
        """

        # 2. The "Junior/Support" Profile (Low Match)
        junior_bio = """
        SUMMARY: IT Support Specialist looking to move into Engineering. 3 years experience in Helpdesk.
        
        EXPERIENCE:
        - Local School (2021-Present): IT Support. Reset passwords in Active Directory. Installed Printers.
        - Best Buy (2019-2021): Geek Squad. Fixed laptops.
        
        SKILLS: Windows 10, Basic AD User Management, Office 365 Support, Troubleshooting.
        """

        # 3. The "Job Hopper" (Red Flag)
        hopper_bio = """
        SUMMARY: Systems Engineer available immediately.
        
        EXPERIENCE:
        - Tech Corp (Jan 2024 - Mar 2024): Contract. Active Directory cleanup.
        - Finance Inc (Sept 2023 - Dec 2023): SysAdmin. Left due to culture.
        - Startup X (May 2023 - Aug 2023): Cloud Engineer. Company ran out of money.
        - MSP LLC (Jan 2023 - Apr 2023): L2 Support.
        
        SKILLS: AD, DNS, DHCP, Windows Server 2019.
        """
        
        for i in range(1, 21):
            roll = random.randint(1, 10)
            if roll <= 3: 
                content = f"Name: Candidate_{i} (Architect)\nEmail: arch{i}@test.com\nLocation: Nashville, TN\n{perfect_bio}"
                fname = f"Resume_{i}_Architect"
            elif roll <= 7: 
                content = f"Name: Candidate_{i} (Junior)\nEmail: jr{i}@test.com\nLocation: Remote\n{junior_bio}"
                fname = f"Resume_{i}_Support"
            else: 
                content = f"Name: Candidate_{i} (Risk)\nEmail: risk{i}@test.com\nLocation: London, UK\n{hopper_bio}"
                fname = f"Resume_{i}_Hopper"
            resumes_data.append({"filename": fname, "content": content})

    # Create ZIP with mixed file types
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, resume in enumerate(resumes_data):
            # Round-robin format selection: PDF, DOCX, TXT
            format_type = i % 3
            base_name = resume['filename'].replace('.txt', '') # clean any extensions from AI
            
            if format_type == 0: # PDF
                pdf_bytes = create_pdf(resume['content'])
                zf.writestr(f"{base_name}.pdf", pdf_bytes)
            elif format_type == 1: # DOCX
                docx_bytes = create_docx(resume['content'])
                zf.writestr(f"{base_name}.docx", docx_bytes)
            else: # TXT
                zf.writestr(f"{base_name}.txt", resume['content'])
            
    zip_buffer.seek(0)
    return zip_buffer

# --- HELPER: INTEGRATIONS ---
def create_mailto_link(to_email, subject, body):
    params = {"subject": subject, "body": body}
    query_string = urllib.parse.urlencode(params).replace("+", "%20")
    return f"mailto:{to_email}?{query_string}"

def send_slack_notification(message):
    if not SLACK_WEBHOOK:
        return False, "Webhook URL not configured in Secrets."
    try:
        response = requests.post(SLACK_WEBHOOK, json={"text": message})
        if response.status_code == 200:
            return True, "Success"
        else:
            return False, f"Slack API Error: {response.status_code} - {response.text}"
    except Exception as e:
        return False, f"Connection Error: {e}"

# --- AI ANALYSIS ---
def analyze_candidate(candidate_text, jd_text, filename):
    prompt = f"""
    You are a Senior Technical Recruiter. Evaluate this candidate.
    
    JOB DESCRIPTION:
    {jd_text[:2000]}
    
    CANDIDATE CV:
    {candidate_text[:3000]}
    
    TASK:
    1. EXTRACT CONTACT INFO: Email, Phone, Location, LinkedIn.
    2. SCORE (0-100): Strict match.
    3. SUMMARY: 2 sentences.
    4. RED FLAGS: Gaps, hopping, missing skills.
    
    5. KNOWLEDGE CHECK (The "Knock-out" Test):
       - Identify TOP 3 HARD SKILLS.
       - Create 3 "Trivia" questions to test competence.
       - Provide the CORRECT ANSWER.
    
    6. BEHAVIORAL DEEP DIVE:
       - Q1: "Describe a time you had to DEPLOY or DESIGN..." (Contextualize).
       - Q2: "Describe a time you had to SOLVE a complex problem..." (Contextualize).
    
    7. EXTRAS: Manager Blurb, Outreach Email, Blind Profile.
    
    OUTPUT JSON KEYS: 
    "email", "phone", "linkedin", "location",
    "score", "summary", "pros", "cons", 
    "tech_q1", "tech_a1", "tech_q2", "tech_a2", "tech_q3", "tech_a3", 
    "beh_q1", "beh_q2",
    "manager_blurb", "outreach_email", "blind_summary"
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}]
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"score": 0, "summary": "Error", "email": ""}

# --- EMAIL REPORT ---
def send_summary_email(user_email, df, jd_title):
    msg = MIMEMultipart()
    msg['Subject'] = f"Sharp Screen Report: {jd_title}"
    msg['From'] = GMAIL_USER
    msg['To'] = user_email
    
    top_5 = df.head(5)[['Score', 'Name', 'Email', 'Location', 'Summary']].to_html(index=False)
    msg.attach(MIMEText(f"<h3>Sharp Screen Results</h3>{top_5}", 'html'))
    
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    part = MIMEApplication(excel_buffer.getvalue(), Name="Screening_Report.xlsx")
    part['Content-Disposition'] = 'attachment; filename="Screening_Report.xlsx"'
    msg.attach(part)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except: return False

# --- UI ---
st.set_page_config(page_title="Sharp Screen", page_icon="⚖️", layout="wide")

# --- INITIALIZE SESSION STATE ---
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None
if 'top_candidate' not in st.session_state:
    st.session_state.top_candidate = None

# --- DISCLAIMER / BETA NOTICE ---
with st.expander("⚠️ DISCLAIMER & BETA NOTICE (Read First)", expanded=False):
    st.warning("""
    **This tool is currently in BETA.** 1. **AI Assistance Only:** This tool uses Artificial Intelligence to analyze text. It is designed to assist human recruiters, not replace them. AI can make mistakes or "hallucinate" facts.
    2. **No Hiring Decisions:** Do not use this tool as the sole basis for hiring or rejecting a candidate. Always verify critical information manually.
    3. **Data Privacy:** Do not upload sensitive PII (Personally Identifiable Information) unless you have authorization. Files are processed in memory and not permanently stored.
    4. **No Warranty:** This software is provided "as is" without warranty of any kind.
    """)

# --- HEADER & VALUE PROP ---
st.title("⚖️ Sharp Screen")
st.caption("Intelligent Candidate Analysis & Interview Prep")

st.info("""
**Executive Summary:**
Sharp Screen turns the manual grind of resume reviewing into a strategic advantage. 
Instead of keyword-matching, our AI reads resumes like a human expert—detecting context, spotting red flags, 
and generating custom interview scripts—so you can focus on the conversation, not the CTRL+F.
""")

with st.container():
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown("🚀 **Bulk Processing**<br>ZIP / PDF Support", unsafe_allow_html=True)
    with c2: st.markdown("🧠 **Knowledge Check**<br>Auto-generated Trivia", unsafe_allow_html=True)
    with c3: st.markdown("💬 **Behavioral**<br>Custom Interview Prompts", unsafe_allow_html=True)
    with c4: st.markdown("📞 **Contact Extraction**<br>Auto-finds Email/Phone", unsafe_allow_html=True)

st.divider()

# --- SIDEBAR INPUTS ---
with st.sidebar:
    st.header("1. The Job")
    jd_input_method = st.radio("Input Method", ["Paste Text", "Upload File"])
    
    jd_text = ""
    if jd_input_method == "Paste Text":
        jd_text = st.text_area("Paste JD Here", height=300, placeholder="Paste your Job Description...")
    else:
        jd_file = st.file_uploader("Upload JD", type=["pdf", "docx", "txt"])
        if jd_file:
            jd_text = read_file_content(jd_file, jd_file.name)

    st.divider()
    st.header("2. Settings")
    email_recipient = st.text_input("Email Report To", "judd@sharphuman.com")
    
    st.markdown("---")
    st.subheader("🛠️ Demo Tools")
    
    # DOWNLOAD TEST DATA BUTTON (DYNAMIC)
    if st.button("📥 Generate & Download Test Data"):
        if jd_text:
             with st.spinner("AI is inventing candidates for your job..."):
                test_data = generate_dummy_data(jd_text)
                st.download_button(
                    label="💾 Click to Save ZIP",
                    data=test_data,
                    file_name="custom_test_candidates.zip",
                    mime="application/zip"
                )
        else:
            # Fallback for no JD
             test_data = generate_dummy_data(None)
             st.download_button(
                label="📥 Download Default Infrastructure CVs",
                data=test_data,
                file_name="default_infra_candidates.zip",
                mime="application/zip"
            )

    st.markdown("---")
    if SLACK_WEBHOOK:
        st.success("✅ Slack Integrated")
    else:
        st.caption("🚫 Slack Not Configured")

    # Clear Button
    if st.button("Reset / Clear All"):
        st.session_state.analysis_results = None
        st.session_state.top_candidate = None
        st.rerun()

# --- MAIN UPLOAD ---
st.subheader("2. Upload Candidates")
uploaded_files = st.file_uploader(
    "Upload CVs (PDF, DOCX) or a ZIP file", 
    type=["pdf", "docx", "zip", "txt"], 
    accept_multiple_files=True
)

if st.button("Run Screening Analysis", type="primary"):
    if not jd_text or not uploaded_files:
        st.error("Missing Data. Please upload a JD and at least one CV.")
    else:
        with st.spinner("Unpacking files & Warming up AI..."):
            docs = process_uploaded_files(uploaded_files)
        
        st.success(f"Queue: {len(docs)} candidates. Processing now...")
        
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, doc in enumerate(docs):
            status_text.text(f"Screening: {doc['name']}...")
            
            a = analyze_candidate(doc['text'], jd_text, doc['name'])
            
            results.append({
                "Score": a.get('score', 0),
                "Name": doc['name'],
                "Email": a.get('email', 'N/A'),
                "Phone": a.get('phone', 'N/A'),
                "Location": a.get('location', 'N/A'),
                "LinkedIn": a.get('linkedin', ''),
                "Summary": a.get('summary', ''),
                "Strengths": a.get('pros', ''),
                "Red Flags": a.get('cons', ''),
                "Manager Blurb": a.get('manager_blurb', ''),
                "Outreach Email": a.get('outreach_email', ''),
                "Blind Summary": a.get('blind_summary', ''),
                "TQ1": a.get('tech_q1', ''), "TA1": a.get('tech_a1', ''),
                "TQ2": a.get('tech_q2', ''), "TA2": a.get('tech_a2', ''),
                "TQ3": a.get('tech_q3', ''), "TA3": a.get('tech_a3', ''),
                "BQ1": a.get('beh_q1', ''), "BQ2": a.get('beh_q2', '')
            })
            progress_bar.progress((i + 1) / len(docs))
            
        status_text.text("Finalizing...")
        
        # Save to Session State
        df = pd.DataFrame(results).sort_values(by="Score", ascending=False)
        st.session_state.analysis_results = df
        st.session_state.top_candidate = df.iloc[0]
        
        # Send Email Report Immediately
        if email_recipient:
            if send_summary_email(email_recipient, df, "Screening Report"):
                st.toast("Report Sent!", icon="📧")
        
        st.rerun()

# --- DISPLAY RESULTS (FROM SESSION STATE) ---
if st.session_state.analysis_results is not None:
    
    df = st.session_state.analysis_results
    best = st.session_state.top_candidate
    
    st.balloons()
    st.success(f"🏆 Top Candidate: **{best['Name']}** ({best['Score']}%)")
    
    # --- RESULTS CARDS ---
    for index, row in df.iterrows():
        with st.expander(f"{row['Score']}% - {row['Name']}"):
            
            # CONTACT HEADER
            st.markdown(f"**📍 {row['Location']}** | 📧 {row['Email']} | 📞 {row['Phone']}")
            st.divider()

            # ANALYSIS
            c1, c2 = st.columns([1, 1])
            with c1:
                st.success(f"**✅ Strengths:**\n\n{row['Strengths']}")
            with c2:
                st.error(f"**🚩 Red Flags:**\n\n{row['Red Flags']}")
            
            st.divider()
            
            # TABS
            tab1, tab2, tab3, tab4, tab5 = st.tabs(["🧠 Knowledge Check", "🗣️ Behavioral", "💬 Slack", "📧 Outreach", "🙈 Blind Profile"])
            
            with tab1:
                st.caption("Ask these to test technical competence:")
                st.markdown(f"**Q1:** {row['TQ1']}")
                st.info(f"**Answer:** {row['TA1']}")
                
                st.markdown(f"**Q2:** {row['TQ2']}")
                st.info(f"**Answer:** {row['TA2']}")
                
                st.markdown(f"**Q3:** {row['TQ3']}")
                st.info(f"**Answer:** {row['TA3']}")

            with tab2:
                st.caption("Deep dive questions based on their resume:")
                st.markdown(f"**1. Deployment/Design:**\n> {row['BQ1']}")
                st.markdown(f"**2. Complex Problem:**\n> {row['BQ2']}")
            
            with tab3:
                st.caption("Copy/Paste to Hiring Manager:")
                st.code(row['Manager Blurb'], language="text")
                if st.button("Post to Slack", key=f"sl_{index}"):
                    success, msg = send_slack_notification(f"🔥 *New Candidate:* {row['Name']} ({row['Score']}%)\n{row['Manager Blurb']}")
                    if success:
                        st.toast("Posted!", icon="✅")
                    else:
                        st.error(msg)

            with tab4:
                st.caption("Personalized draft to candidate:")
                st.text_area("Copy Email:", value=row['Outreach Email'], height=150)
                
                # HTML BUTTON FOR MAILTO LINK (REMOVED target="_blank")
                mailto_link = create_mailto_link(row['Email'], f"Interview: {row['Name']}", row['Outreach Email'])
                
                st.markdown(f"""
                <a href="{mailto_link}" style="
                    display: inline-block;
                    padding: 0.5em 1em;
                    color: white;
                    background-color: #ff4b4b;
                    border-radius: 4px;
                    text-decoration: none;
                    font-weight: bold;">
                    📧 Open Draft in Outlook/Gmail
                </a>
                """, unsafe_allow_html=True)

            with tab5:
                st.caption("Bias-free summary for review:")
                st.text_area("Blind Summary:", value=row['Blind Summary'], height=150)

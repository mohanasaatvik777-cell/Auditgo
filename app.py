import os
import json
import streamlit as st
from run_agent import run_agent

st.set_page_config(page_title="Auditgo", page_icon="🔎", layout="wide")

st.title("Auditgo — AI-Powered SEO Audit Platform")
st.caption("Powered by BeautifulSoup, tldextract, phonenumbers, rank_bm25 & Groq")

url_input = st.text_input("Enter Website Target URL", placeholder="https://example.com")
query_input = st.text_input("Enter Question for Grounded Q&A (Optional)", placeholder="What are your business hours?")

if st.button("Run SEO Audit", type="primary"):
    if not url_input.strip():
        st.error("Please enter a valid target URL.")
    else:
        with st.spinner("Crawling site, auditing SEO, normalizing NAP, and verifying Q&A excerpts..."):
            try:
                output_dir = "outputs"
                results = run_agent(url=url_input.strip(), query=query_input.strip() if query_input else None, output_dir=output_dir)
                
                st.success("Audit Completed Successfully!")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.subheader("1. On-Page Audit (`audit.json`)")
                    st.json(results["audit"])
                    audit_json_bytes = json.dumps(results["audit"], indent=2).encode("utf-8")
                    st.download_button("Download audit.json", data=audit_json_bytes, file_name="audit.json", mime="application/json")
                    
                with col2:
                    st.subheader("2. NAP Report (`nap_report.json`)")
                    st.json(results["nap_report"])
                    nap_json_bytes = json.dumps(results["nap_report"], indent=2).encode("utf-8")
                    st.download_button("Download nap_report.json", data=nap_json_bytes, file_name="nap_report.json", mime="application/json")
                    
                with col3:
                    st.subheader("3. Grounded Q&A (`answer.json`)")
                    st.json(results["answer"])
                    answer_json_bytes = json.dumps(results["answer"], indent=2).encode("utf-8")
                    st.download_button("Download answer.json", data=answer_json_bytes, file_name="answer.json", mime="application/json")
                    
            except Exception as e:
                st.error(f"Audit failed: {e}")

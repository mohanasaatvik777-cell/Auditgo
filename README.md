# SEO Audit Agent

A production-grade, offline-first **SEO Audit Agent** command-line interface and web platform styled after **SARVAM AI UI**.

> **Statement of Zero Paid Services:** No paid API, tool, key, or subscription is used anywhere in this repository. All core logic uses free, local, open-source libraries (`httpx`, `beautifulsoup4`, `tldextract`, `phonenumbers`, `rank_bm25`) with optional free-tier Groq LLM support.

---

## Features

1. **Core Domain Crawler**: Normalizes URLs, enforces `tldextract` registrable domain matching, respects `robots.txt`, discovers `sitemap.xml`, and enforces configurable budget limits (max 150 pages, depth 4, 120s timeout) with SSRF loopback protection.
2. **On-Page SEO Auditor (`outputs/audit.json`)**: Detects missing/short/long title & meta descriptions, `<h1>` hierarchy issues, missing image alt attributes, broken internal links (404), `noindex` directives, missing canonicals, template-level duplicate content fingerprints, structured data signals, and sitemap mismatches.
3. **NAP Consistency Checker (`outputs/nap_report.json`)**: Extracts Name, Address, and Phone numbers from contact pages & JSON-LD. Normalizes phones to E.164 standard using `phonenumbers` library and addresses with standard abbreviations. Evaluates verdicts (`consistent`, `formatting_difference`, `mismatch`, `insufficient_evidence`).
4. **Grounded Website Q&A (`outputs/answer.json`)**: Indexes passages using BM25 (`rank_bm25`). Retrieves candidates against queries and enforces mandatory **verbatim raw HTML offset verification** before returning answers.
5. **SARVAM AI Styled Web Interface**: Sleek UI featuring sidebar navigation, hero search prompt container, category filter pills, interactive preset cards, live execution visualizer, and tabbed JSON inspector.

---

## Installation & Setup

```bash
# Clone repository and navigate to root directory
cd MINT-PROJECT

# Install dependencies
pip install -r requirements.txt

# (Optional) Set free-tier Groq API key in environment or .env file
# GROQ_API_KEY=your_free_groq_api_key
```

---

## Usage

### 1. Primary CLI Command
Run the agent CLI against any target URL and query:
```bash
python run_agent.py --url https://example.com --query "What are your business hours?"
```
This command outputs three JSON files in the `outputs/` directory:
- `outputs/audit.json`
- `outputs/nap_report.json`
- `outputs/answer.json`

### 2. Launch SARVAM AI Styled Web UI
```bash
python server.py
```
Open your browser at `http://127.0.0.1:8000` to interact with the Sarvam AI web dashboard.

### 3. Alternative Streamlit UI (Section 6)
```bash
streamlit run app.py
```

---

## Running Unit & Integration Tests

```bash
python -m pytest tests/ -v
```

---

## Project Directory Structure

```
.
├── crawler/            # Core HTTP fetcher, robots/sitemap parser, URL & SSRF utilities
├── seo/                # Question 1 On-Page SEO audit rules & aggregation logic
├── nap/                # Question 2 NAP consistency checker & E.164 phone normalization
├── qa/                 # Question 3 BM25 Q&A engine with mandatory offset verification
├── utils/              # LLM helper with Groq free-tier & graceful deterministic fallback
├── web/                # SARVAM AI reference frontend (HTML, CSS, JS)
├── fixtures/           # Local HTML test fixture site
├── tests/              # Pytest unit and integration test suite
├── outputs/            # Demo run output JSON files (audit.json, nap_report.json, answer.json)
├── run_agent.py        # Evaluator CLI entrypoint
├── server.py           # FastAPI Web UI server
├── app.py              # Streamlit Web UI wrapper
├── demo.md             # Demo run evidence details
└── README.md           # Documentation & instructions
```

# Demo Run Evidence & Documentation

## Target Demo URL & Query
- **Demo Target URL:** `http://127.0.0.1:8899/index.html` (Local test fixture server)
- **Demo Query:** `What are your support hours?`

## Reproduction Command
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the audit agent CLI
python run_agent.py --url http://127.0.0.1:8899/index.html --query "What are your support hours?"
```

## Generated Artifacts Summary

### 1. `outputs/audit.json`
Contains 9 high-confidence On-Page SEO findings including:
- Missing `alt` attributes on `<img>` tags (`index.html`)
- `<title>` too short (< 10 chars) on `about.html`
- Missing meta description on `about.html`
- Missing `<h1>` header on `about.html`
- Missing canonical tags & structured data signals
- Broken internal link pointing to non-existent page (`broken.html` returning 404)

### 2. `outputs/nap_report.json`
- Analyzed phone numbers across `index.html`, `about.html`, and `contact.html` (`+1 800 555 0199`, `+1 (800) 555-0199`, `+1-800-555-0199`).
- Successfully normalized all occurrences to E.164 standard: `+18005550199`.
- Verdict: `formatting_difference` with confidence `0.80`.

### 3. `outputs/answer.json`
- Query: `What are your support hours?`
- Verified Source URL: `http://127.0.0.1:8899/about.html`
- Verbatim Excerpt: `"Our support hours are Monday to Friday, 9:00 AM to 6:00 PM PST."` (Mandatory exact character offset verified).

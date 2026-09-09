import os
import json
import threading
import time
import pytest
from http.server import HTTPServer, SimpleHTTPRequestHandler
from run_agent import run_agent

PORT = 8899

class FixtureHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="fixtures", **kwargs)

@pytest.fixture(scope="module")
def fixture_server():
    server = HTTPServer(("127.0.0.1", PORT), FixtureHTTPHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    time.sleep(0.5) # Give server time to bind
    yield f"http://127.0.0.1:{PORT}/index.html"
    server.shutdown()

def test_full_integration_run(fixture_server, tmp_path):
    output_dir = str(tmp_path / "outputs")
    url = fixture_server
    query = "What are your support hours?"
    
    results = run_agent(url=url, query=query, output_dir=output_dir)
    
    # 1. Verify 3 JSON output files created
    audit_path = os.path.join(output_dir, "audit.json")
    nap_path = os.path.join(output_dir, "nap_report.json")
    answer_path = os.path.join(output_dir, "answer.json")
    
    assert os.path.exists(audit_path)
    assert os.path.exists(nap_path)
    assert os.path.exists(answer_path)
    
    # 2. Verify audit.json structure & findings
    with open(audit_path, "r", encoding="utf-8") as f:
        audit_data = json.load(f)
    assert isinstance(audit_data, list)
    metrics = [item["metric"] for item in audit_data]
    assert "images_missing_alt" in metrics or "title_too_short" in metrics or "broken_internal_link" in metrics
    
    # 3. Verify nap_report.json structure & E.164 phone
    with open(nap_path, "r", encoding="utf-8") as f:
        nap_data = json.load(f)
    assert isinstance(nap_data, list)
    phone_field = next((item for item in nap_data if item["field"] == "phone"), None)
    assert phone_field is not None
    assert len(phone_field["normalized_values"]) > 0
    assert "+18005550199" in phone_field["normalized_values"]
    
    # 4. Verify answer.json verbatim grounded answer
    with open(answer_path, "r", encoding="utf-8") as f:
        answer_data = json.load(f)
    assert answer_data["query"] == query
    assert answer_data["excerpt"] is not None
    assert "Monday to Friday" in answer_data["excerpt"]

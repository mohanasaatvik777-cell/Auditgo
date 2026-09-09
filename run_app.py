import os
import threading
import uvicorn
from http.server import HTTPServer, SimpleHTTPRequestHandler
from server import app

# Render injects PORT; fall back to 8000 locally
PORT_APP     = int(os.environ.get("PORT", 8000))
PORT_FIXTURE = 8899

class FixtureHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="fixtures", **kwargs)
    def log_message(self, format, *args):
        pass   # silence request logs

def start_fixture_server():
    server = HTTPServer(("127.0.0.1", PORT_FIXTURE), FixtureHTTPHandler)
    server.serve_forever()

if __name__ == "__main__":
    # Start local fixture server (demo HTML pages) in background thread
    t = threading.Thread(target=start_fixture_server, daemon=True)
    t.start()

    print("\n" + "="*60)
    print("Auditgo - AI-Powered SEO Audit Platform is Running!")
    print("="*60)
    print(f"Web Application UI:   http://0.0.0.0:{PORT_APP}")
    print(f"Test Fixture Domain:  http://127.0.0.1:{PORT_FIXTURE}/index.html")
    print("="*60 + "\n")

    # host=0.0.0.0 required for Render (and any containerised deployment)
    uvicorn.run(app, host="0.0.0.0", port=PORT_APP, log_level="info")

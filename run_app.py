import os
import time
import threading
import uvicorn
from http.server import HTTPServer, SimpleHTTPRequestHandler
from server import app

PORT_FIXTURE = 8899
PORT_APP = 8000

class FixtureHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="fixtures", **kwargs)
    def log_message(self, format, *args):
        pass

def start_fixture_server():
    server = HTTPServer(("127.0.0.1", PORT_FIXTURE), FixtureHTTPHandler)
    server.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=start_fixture_server, daemon=True)
    t.start()
    
    print("\n" + "="*60)
    print("Auditgo - AI-Powered SEO Audit Platform is Running!")
    print("="*60)
    print(f"Web Application UI:   http://127.0.0.1:{PORT_APP}")
    print(f"Test Fixture Domain:  http://127.0.0.1:{PORT_FIXTURE}/index.html")
    print("="*60 + "\n")
    
    uvicorn.run(app, host="127.0.0.1", port=PORT_APP, log_level="info")

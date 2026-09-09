import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from run_agent import run_agent

PORT = 8899

class FixtureHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="fixtures", **kwargs)

server = HTTPServer(("127.0.0.1", PORT), FixtureHTTPHandler)
thread = threading.Thread(target=server.serve_forever)
thread.daemon = True
thread.start()
time.sleep(0.5)

print("Running demo audit generation...")
run_agent(url=f"http://127.0.0.1:{PORT}/index.html", query="What are your support hours?", output_dir="outputs")
print("Demo outputs generated in outputs/")
server.shutdown()

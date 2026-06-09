"""MonsterBox local launcher server.

Serves the PWA build in docs/ on 127.0.0.1:8077 with NO console window (run via
pythonw / pyw). The app page sends a heartbeat to /__ping every few seconds; when
the app window is closed the heartbeats stop and this server shuts itself down a
few seconds later — so nothing is left running in the background.
"""
import http.server
import os
import socketserver
import sys
import threading
import time

PORT = 8077
ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
IDLE_TIMEOUT = 12.0          # seconds with no heartbeat before shutting down

_state = {"last_ping": time.time(), "seen": False}


class Handler(http.server.SimpleHTTPRequestHandler):
    def _ping(self):
        _state["last_ping"] = time.time()
        _state["seen"] = True
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path.startswith("/__ping"):
            return self._ping()
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/__ping"):
            return self._ping()
        return super().do_GET()

    def log_message(self, *args):
        pass   # stay silent (no console anyway)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _watchdog():
    while True:
        time.sleep(2)
        if _state["seen"] and (time.time() - _state["last_ping"] > IDLE_TIMEOUT):
            os._exit(0)


def main():
    if not os.path.isdir(DOCS):
        sys.exit(1)
    os.chdir(DOCS)
    try:
        httpd = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit(0)   # already running — Chrome will reuse the existing server
    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

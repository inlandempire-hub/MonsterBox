"""MonsterBox local launcher server.

Serves the PWA build in docs/ on 127.0.0.1:8077 with NO console window (run via
pythonw / pyw). The app page sends a heartbeat to /__ping every few seconds; when
the app window is closed the heartbeats stop and this server shuts itself down a
few seconds later — so nothing is left running in the background.
"""
import http.server
import os
import socketserver
import subprocess
import sys
import threading
import time

PORT = 8077
ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
SERVER_DIR = os.path.join(ROOT, "server")
API_PORT = 8090
IDLE_TIMEOUT = 12.0          # seconds with no heartbeat before shutting down

_state = {"last_ping": time.time(), "seen": False}
_backend = None              # the FastAPI API subprocess (started only if set up)


def _start_backend():
    """Launch the API backend hidden, if it's installed, so it lives and dies
    with this launcher (no separate window, nothing left running). The app is
    fully usable without it — login/sync just won't be available."""
    global _backend
    py = os.path.join(SERVER_DIR, ".venv", "Scripts", "pythonw.exe")
    if not os.path.isfile(py):
        py = os.path.join(SERVER_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(py):
        return   # backend not set up on this machine — serve the frontend only
    flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
    try:
        _backend = subprocess.Popen(
            [py, "-m", "uvicorn", "app.main:app", "--port", str(API_PORT)],
            cwd=SERVER_DIR, creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        _backend = None


def _stop_backend():
    global _backend
    if _backend is not None:
        try:
            _backend.terminate()
        except Exception:
            pass
        _backend = None


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
            _stop_backend()   # shut the API down with us
            os._exit(0)


def main():
    if not os.path.isdir(DOCS):
        sys.exit(1)
    os.chdir(DOCS)
    try:
        httpd = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit(0)   # already running — Chrome will reuse the existing server
    _start_backend()
    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_backend()


if __name__ == "__main__":
    main()

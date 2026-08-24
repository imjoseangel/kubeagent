import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_RESPONSES = {
    "/healthz": {"status": "ok"},
    "/readyz": {"status": "ready"},
}


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = _RESPONSES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        pass


def start_health_server(port: int) -> ThreadingHTTPServer:
    """Serve /healthz and /readyz from a dedicated thread and socket.

    This runs on its own OS thread with its own listening socket, entirely
    outside the FastAPI app's asyncio event loop — so liveness/readiness
    probes keep getting answered even if a long-running LLM or kubectl
    call were ever to stall that event loop.
    """
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="health-server"
    )
    thread.start()
    return server

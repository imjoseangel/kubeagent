import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.persistence.store import InvestigationStore


class Heartbeat:
    """Thread-safe "is the main event loop still ticking" signal.

    The main app calls `beat()` on a periodic asyncio task; the health
    server (running on its own thread) calls `age()` to decide whether
    that loop is still alive or has stalled.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_beat = time.monotonic()

    def beat(self) -> None:
        with self._lock:
            self._last_beat = time.monotonic()

    def age(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_beat


def _render_metrics(heartbeat: Heartbeat, store: InvestigationStore) -> str:
    lines = [
        "# HELP kubeagent_up Always 1 if the metrics endpoint responds.",
        "# TYPE kubeagent_up gauge",
        "kubeagent_up 1",
        "# HELP kubeagent_event_loop_heartbeat_age_seconds Seconds since "
        "the main event loop last confirmed it is running.",
        "# TYPE kubeagent_event_loop_heartbeat_age_seconds gauge",
        f"kubeagent_event_loop_heartbeat_age_seconds {heartbeat.age():.3f}",
        "# HELP kubeagent_investigations_total In-memory investigations "
        "by status.",
        "# TYPE kubeagent_investigations_total gauge",
    ]
    for status, count in store.counts_by_status().items():
        lines.append(
            f'kubeagent_investigations_total{{status="{status}"}} {count}'
        )
    return "\n".join(lines) + "\n"


def _make_handler(
    heartbeat: Heartbeat, store: InvestigationStore, stale_seconds: float
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/healthz", "/readyz"):
                self._serve_health()
            elif self.path == "/metrics":
                self._serve_metrics()
            else:
                self.send_response(404)
                self.end_headers()

        def _serve_health(self) -> None:
            age = heartbeat.age()
            body: dict[str, object]
            if age < stale_seconds:
                label = "ok" if self.path == "/healthz" else "ready"
                code, body = 200, {"status": label}
            else:
                code = 503
                body = {"status": "stalled", "age_seconds": round(age, 3)}
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _serve_metrics(self) -> None:
            payload = _render_metrics(heartbeat, store).encode()
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


def start_health_server(
    port: int,
    heartbeat: Heartbeat,
    store: InvestigationStore,
    stale_seconds: float,
) -> ThreadingHTTPServer:
    """Serve /healthz, /readyz and /metrics from a dedicated thread/socket.

    This runs on its own OS thread with its own listening socket, entirely
    outside the FastAPI app's asyncio event loop — so probes and metrics
    scrapes keep getting answered even if a long-running LLM or kubectl
    call were ever to stall that event loop. `/healthz` and `/readyz`
    still reflect the loop's real liveness via `heartbeat`: if it goes
    stale (the loop stopped ticking, not just busy), they flip to 503 so
    Kubernetes can actually restart a genuinely stuck pod.
    """
    handler = _make_handler(heartbeat, store, stale_seconds)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="health-server"
    )
    thread.start()
    return server

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.core.dependency_checks import CheckResult
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


class DependencyStatus:
    """Thread-safe cache of the latest dependency-check results.

    Populated by a periodic asyncio task on the main loop; read by the
    health server thread — `/readyz` never makes a live network call
    itself, it only ever reports the last cached outcome.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: dict[str, CheckResult] = {}

    def update(self, results: list[CheckResult]) -> None:
        with self._lock:
            for result in results:
                self._results[result.name] = result

    def snapshot(self) -> dict[str, CheckResult]:
        with self._lock:
            return dict(self._results)


_POD_NAME = socket.gethostname()


def _render_metrics(
    heartbeat: Heartbeat,
    store: InvestigationStore,
    dependencies: DependencyStatus,
) -> str:
    lines = [
        "# HELP kubeagent_up Always 1 if the metrics endpoint responds.",
        "# TYPE kubeagent_up gauge",
        "kubeagent_up 1",
        "# HELP kubeagent_event_loop_heartbeat_age_seconds Seconds since "
        "the main event loop last confirmed it is running.",
        "# TYPE kubeagent_event_loop_heartbeat_age_seconds gauge",
        f"kubeagent_event_loop_heartbeat_age_seconds {heartbeat.age():.3f}",
        "# HELP kubeagent_dependency_up Whether the last check of a "
        "dependency succeeded.",
        "# TYPE kubeagent_dependency_up gauge",
    ]
    for name, result in sorted(dependencies.snapshot().items()):
        lines.append(
            f'kubeagent_dependency_up{{dependency="{name}"}} {int(result.ok)}'
        )
    lines += [
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
    heartbeat: Heartbeat,
    store: InvestigationStore,
    dependencies: DependencyStatus,
    stale_seconds: float,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._serve_healthz()
            elif self.path == "/readyz":
                self._serve_readyz()
            elif self.path == "/metrics":
                self._serve_metrics()
            else:
                self.send_response(404)
                self.end_headers()

        def _serve_healthz(self) -> None:
            age = heartbeat.age()
            if age < stale_seconds:
                body: dict[str, object] = {"status": "ok", "pod": _POD_NAME}
                code = 200
            else:
                body = {
                    "status": "stalled",
                    "pod": _POD_NAME,
                    "age_seconds": round(age, 3),
                }
                code = 503
            self._write_json(code, body)

        def _serve_readyz(self) -> None:
            age = heartbeat.age()
            loop_ok = age < stale_seconds
            checks: dict[str, dict[str, object]] = {
                "loop": {
                    "ok": loop_ok,
                    "status": 200 if loop_ok else 503,
                    "message": (
                        "event loop heartbeat fresh"
                        if loop_ok
                        else f"heartbeat stale ({round(age, 3)}s)"
                    ),
                }
            }
            for name, result in sorted(dependencies.snapshot().items()):
                checks[name] = {
                    "ok": result.ok,
                    "status": result.status_code,
                    "message": result.message,
                }

            all_ok = all(check["ok"] for check in checks.values())
            body: dict[str, object] = {
                "status": "ready" if all_ok else "not_ready",
                "pod": _POD_NAME,
                "checks": checks,
            }
            self._write_json(200 if all_ok else 503, body)

        def _serve_metrics(self) -> None:
            payload = _render_metrics(heartbeat, store, dependencies).encode()
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _write_json(self, code: int, body: dict[str, object]) -> None:
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
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
    dependencies: DependencyStatus,
    stale_seconds: float,
) -> ThreadingHTTPServer:
    """Serve /healthz, /readyz and /metrics from a dedicated thread/socket.

    This runs on its own OS thread with its own listening socket, entirely
    outside the FastAPI app's asyncio event loop — so probes and metrics
    scrapes keep getting answered even if a long-running LLM or Kubernetes
    API call were ever to stall that event loop.

    `/healthz` (liveness) only reflects the loop's own heartbeat: a truly
    stalled loop should get the pod restarted, but an unreachable external
    dependency should not, since restarting fixes nothing there.
    `/readyz` (readiness) additionally reports the cached Kubernetes-API/LLM
    reachability checks (`app/core/dependency_checks.py`) — if either is
    down, the pod can't do its job right now and should be pulled out of
    rotation without being killed.
    """
    handler = _make_handler(heartbeat, store, dependencies, stale_seconds)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="health-server"
    )
    thread.start()
    return server

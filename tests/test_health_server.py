import json
import socket
import urllib.error
import urllib.request

from app.health_server import Heartbeat, start_health_server
from app.persistence.store import InvestigationStore


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(port: int, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=2
        ) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_healthz_and_readyz_report_ok_while_heartbeat_is_fresh() -> None:
    # GIVEN a health server with a freshly-beating heartbeat
    heartbeat = Heartbeat()
    server = start_health_server(
        _free_port(), heartbeat, InvestigationStore(), stale_seconds=10
    )
    port = server.server_address[1]
    try:
        # WHEN healthz and readyz are requested
        healthz_status, healthz_body = _get(port, "/healthz")
        readyz_status, readyz_body = _get(port, "/readyz")

        # THEN both report healthy, independently of the FastAPI app
        assert healthz_status == 200
        assert json.loads(healthz_body) == {"status": "ok"}
        assert readyz_status == 200
        assert json.loads(readyz_body) == {"status": "ready"}
    finally:
        server.shutdown()


def test_healthz_and_readyz_report_stalled_once_heartbeat_goes_stale() -> None:
    # GIVEN a heartbeat that hasn't beaten within the stale window
    heartbeat = Heartbeat()
    heartbeat._last_beat -= 999
    server = start_health_server(
        _free_port(), heartbeat, InvestigationStore(), stale_seconds=10
    )
    port = server.server_address[1]
    try:
        # WHEN healthz and readyz are requested
        healthz_status, healthz_body = _get(port, "/healthz")
        readyz_status, readyz_body = _get(port, "/readyz")

        # THEN both report the loop as stalled, so kubelet can act on it
        assert healthz_status == 503
        assert json.loads(healthz_body)["status"] == "stalled"
        assert readyz_status == 503
        assert json.loads(readyz_body)["status"] == "stalled"
    finally:
        server.shutdown()


def test_metrics_reports_heartbeat_age_and_investigation_counts() -> None:
    # GIVEN a store with investigations in different states
    store = InvestigationStore()
    store.create(namespace="staging")
    completed = store.create(namespace="staging")
    completed.status = completed.status.COMPLETED
    heartbeat = Heartbeat()
    server = start_health_server(
        _free_port(), heartbeat, store, stale_seconds=10
    )
    port = server.server_address[1]
    try:
        # WHEN /metrics is scraped
        status, body = _get(port, "/metrics")
        text = body.decode()

        # THEN it exposes the heartbeat age and per-status counts
        assert status == 200
        assert "kubeagent_up 1" in text
        assert "kubeagent_event_loop_heartbeat_age_seconds" in text
        assert 'kubeagent_investigations_total{status="running"} 1' in text
        assert 'kubeagent_investigations_total{status="completed"} 1' in text
        assert 'kubeagent_investigations_total{status="failed"} 0' in text
    finally:
        server.shutdown()


def test_unknown_path_returns_404() -> None:
    heartbeat = Heartbeat()
    server = start_health_server(
        _free_port(), heartbeat, InvestigationStore(), stale_seconds=10
    )
    port = server.server_address[1]
    try:
        status, _ = _get(port, "/nope")
        assert status == 404
    finally:
        server.shutdown()

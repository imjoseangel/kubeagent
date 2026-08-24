import json
import socket
import urllib.request

from app.health_server import start_health_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_healthz_and_readyz_served_off_the_main_app() -> None:
    # GIVEN the health server running on its own thread and port
    server = start_health_server(_free_port())
    port = server.server_address[1]
    try:
        # WHEN healthz and readyz are requested
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=2
        ) as resp:
            healthz = json.loads(resp.read())
            healthz_status = resp.status
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/readyz", timeout=2
        ) as resp:
            readyz = json.loads(resp.read())
            readyz_status = resp.status

        # THEN both respond independently of the FastAPI app
        assert healthz_status == 200
        assert healthz == {"status": "ok"}
        assert readyz_status == 200
        assert readyz == {"status": "ready"}
    finally:
        server.shutdown()

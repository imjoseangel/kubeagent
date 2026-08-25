from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.kube import format

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


def test_age_units() -> None:
    assert format.age(NOW - timedelta(days=3), NOW) == "3d"
    assert format.age(NOW - timedelta(hours=5), NOW) == "5h"
    assert format.age(NOW - timedelta(minutes=10), NOW) == "10m"
    assert format.age(NOW - timedelta(seconds=45), NOW) == "45s"
    assert format.age(None, NOW) == "<unknown>"


def _pod_crashloop() -> SimpleNamespace:
    waiting = SimpleNamespace(reason="CrashLoopBackOff")
    state = SimpleNamespace(waiting=waiting, terminated=None, running=None)
    last_state = SimpleNamespace(
        waiting=None,
        terminated=SimpleNamespace(reason="Error", exit_code=1),
        running=None,
    )
    cs = SimpleNamespace(
        name="app",
        ready=False,
        restart_count=5,
        image="nginx:1.25",
        state=state,
        last_state=last_state,
    )
    container = SimpleNamespace(
        name="app",
        image="nginx:1.25",
        resources=SimpleNamespace(
            limits={"cpu": "500m"}, requests={"cpu": "100m"}
        ),
        liveness_probe=SimpleNamespace(
            http_get=SimpleNamespace(path="/healthz", port=8080),
            tcp_socket=None,
            initial_delay_seconds=5,
            period_seconds=10,
        ),
        readiness_probe=None,
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name="web-1",
            namespace="staging",
            creation_timestamp=NOW - timedelta(hours=2),
        ),
        spec=SimpleNamespace(containers=[container], node_name="node-1"),
        status=SimpleNamespace(
            phase="Running",
            pod_ip="10.1.2.3",
            container_statuses=[cs],
        ),
    )


def test_pods_table_surfaces_crashloop_over_phase() -> None:
    table = format.pods_table([_pod_crashloop()], NOW)
    assert "NAME" in table
    # Waiting reason beats the raw 'Running' phase in the STATUS column.
    assert "CrashLoopBackOff" in table
    assert "0/1" in table
    assert "web-1" in table


def test_pods_table_empty() -> None:
    assert "No pods found" in format.pods_table([], NOW)


def test_describe_pod_includes_events_and_containers() -> None:
    event = SimpleNamespace(
        last_timestamp=NOW - timedelta(minutes=1),
        event_time=None,
        metadata=SimpleNamespace(creation_timestamp=NOW),
        type="Warning",
        reason="BackOff",
        involved_object=SimpleNamespace(kind="Pod", name="web-1"),
        message="Back-off restarting failed container",
        count=7,
    )
    out = format.describe_pod(_pod_crashloop(), [event], NOW)
    assert "Name:      web-1" in out
    assert "Restart Count: 5" in out
    assert "Liveness: http-get /healthz:8080" in out
    assert "BackOff" in out
    assert "(x7)" in out


def test_events_table_empty() -> None:
    assert format.events_table([], NOW) == "<none>"

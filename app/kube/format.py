"""Render typed Kubernetes API objects into the compact text the LLM reads.

The diagnostic tools used to hand the model raw `kubectl` stdout. Now that
data comes back as typed objects from the API client, these helpers rebuild
equivalent human-readable summaries — close enough to `kubectl get`/`describe`
that the agent prompts and the model's learned expectations still hold.

Timestamps are compared against a caller-supplied `now` so the formatting
stays pure and unit-testable (no hidden clock reads).
"""

from datetime import UTC, datetime
from typing import Any

# These helpers are deliberately duck-typed (`Any`): they accept the client's
# V1Pod/V1ContainerState/CoreV1Event models at runtime, and the same shape
# from lightweight test doubles. Kubernetes stamps timestamps as
# timezone-aware UTC; keep our reference the same so subtraction never raises
# on a naive/aware mismatch.


def now_utc() -> datetime:
    return datetime.now(UTC)


def _tabulate(
    headers: list[str],
    rows: list[list[str]],
    indent: str = "",
    gutter: int = 2,
) -> str:
    """Render aligned columns kubectl-style, sizing each column to its data.

    Fixed-width formatting (`{:<40}`) collapses the gutter to zero the moment
    a cell overruns its width — real pod and event names routinely do — so
    columns run together (`fcz7q1/1`). Sizing every column to the widest cell
    in it (plus a constant gutter, last column left ragged) keeps the gap no
    matter how long a name is.
    """
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def render(cells: list[str]) -> str:
        parts = [
            cell + " " * (widths[i] - len(cell) + gutter)
            for i, cell in enumerate(cells[:-1])
        ]
        parts.append(cells[-1])
        return indent + "".join(parts)

    return "\n".join(render(row) for row in [headers, *rows])


def age(created: datetime | None, now: datetime | None = None) -> str:
    """Compact age like kubectl's AGE column: 3d / 5h / 10m / 45s."""
    if created is None:
        return "<unknown>"
    if now is None:
        now = now_utc()
    seconds = max(0, int((now - created).total_seconds()))
    if seconds >= 86400:
        return f"{seconds // 86400}d"
    if seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _container_status_phrase(state: Any) -> str:
    """Turn a V1ContainerState into e.g. 'Waiting: CrashLoopBackOff'."""
    if state is None:
        return "Unknown"
    if getattr(state, "waiting", None):
        reason = state.waiting.reason or "Waiting"
        return f"Waiting: {reason}"
    if getattr(state, "terminated", None):
        term = state.terminated
        parts = [f"Terminated: {term.reason or 'Completed'}"]
        if term.exit_code is not None:
            parts.append(f"exit={term.exit_code}")
        return " ".join(parts)
    if getattr(state, "running", None):
        return "Running"
    return "Unknown"


def _pod_display_status(pod: Any) -> str:
    """Pick the most informative status, like kubectl's STATUS column.

    A pod whose phase is 'Running' but whose container is stuck in
    CrashLoopBackOff should read as 'CrashLoopBackOff', not 'Running' — that
    waiting reason is the whole point of the investigation.
    """
    statuses = (pod.status.container_statuses or []) if pod.status else []
    for cs in statuses:
        waiting = getattr(cs.state, "waiting", None) if cs.state else None
        if waiting and waiting.reason:
            return waiting.reason
    for cs in statuses:
        term = getattr(cs.state, "terminated", None) if cs.state else None
        if term and term.reason and term.reason != "Completed":
            return term.reason
    return (pod.status.phase if pod.status else None) or "Unknown"


def pods_table(pods: list[Any], now: datetime | None = None) -> str:
    """Render a pod list like `kubectl get pods -o wide`."""
    headers = ["NAME", "READY", "STATUS", "RESTARTS", "AGE", "IP", "NODE"]
    if not pods:
        return _tabulate(headers, []) + "\nNo pods found in this namespace."

    rows = []
    for pod in pods:
        statuses = (pod.status.container_statuses or []) if pod.status else []
        total = len(pod.spec.containers) if pod.spec else len(statuses)
        ready = sum(1 for cs in statuses if cs.ready)
        restarts = sum(cs.restart_count for cs in statuses)
        created = pod.metadata.creation_timestamp
        pod_ip = (pod.status.pod_ip if pod.status else None) or "<none>"
        node = (pod.spec.node_name if pod.spec else None) or "<none>"
        rows.append(
            [
                pod.metadata.name,
                f"{ready}/{total}",
                _pod_display_status(pod),
                str(restarts),
                age(created, now),
                pod_ip,
                node,
            ]
        )
    return _tabulate(headers, rows)


def _resources(resources: Any) -> str:
    if resources is None:
        return "limits: <none>, requests: <none>"
    limits = getattr(resources, "limits", None) or {}
    requests = getattr(resources, "requests", None) or {}

    def fmt(d: dict) -> str:
        return ", ".join(f"{k}={v}" for k, v in sorted(d.items())) or "<none>"

    return f"limits: {fmt(limits)}, requests: {fmt(requests)}"


def _probe(name: str, probe: Any) -> str | None:
    if probe is None:
        return None
    kind = "<custom>"
    if getattr(probe, "http_get", None):
        path = probe.http_get.path or "/"
        port = probe.http_get.port
        kind = f"http-get {path}:{port}"
    elif getattr(probe, "tcp_socket", None):
        kind = f"tcp-socket :{probe.tcp_socket.port}"
    elif getattr(probe, "_exec", None) or getattr(probe, "exec", None):
        kind = "exec"
    delay = probe.initial_delay_seconds or 0
    period = probe.period_seconds or 10
    return f"    {name}: {kind} delay={delay}s period={period}s"


def describe_pod(
    pod: Any, events: list[Any], now: datetime | None = None
) -> str:
    """Rebuild the high-signal parts of `kubectl describe pod`."""
    meta = pod.metadata
    spec = pod.spec
    status = pod.status
    node = (spec.node_name if spec else None) or "<none>"
    pod_ip = (status.pod_ip if status else None) or "<none>"

    lines = [
        f"Name:      {meta.name}",
        f"Namespace: {meta.namespace}",
        f"Node:      {node}",
        f"Status:    {_pod_display_status(pod)}",
        f"IP:        {pod_ip}",
        f"Age:       {age(meta.creation_timestamp, now)}",
        "Containers:",
    ]

    status_by_name = {}
    for cs in (status.container_statuses or []) if status else []:
        status_by_name[cs.name] = cs

    for container in spec.containers if spec else []:
        cs = status_by_name.get(container.name)
        lines.append(f"  {container.name}:")
        lines.append(f"    Image: {container.image}")
        if cs is not None:
            lines.append(f"    State: {_container_status_phrase(cs.state)}")
            if getattr(cs, "last_state", None) and (
                getattr(cs.last_state, "terminated", None)
                or getattr(cs.last_state, "waiting", None)
            ):
                lines.append(
                    f"    Last State: "
                    f"{_container_status_phrase(cs.last_state)}"
                )
            lines.append(f"    Ready: {cs.ready}")
            lines.append(f"    Restart Count: {cs.restart_count}")
        lines.append(f"    Resources: {_resources(container.resources)}")
        for probe_line in (
            _probe("Liveness", container.liveness_probe),
            _probe("Readiness", container.readiness_probe),
        ):
            if probe_line:
                lines.append(probe_line)

    lines.append("Events:")
    lines.append(events_table(events, now, indent="  "))
    return "\n".join(lines)


def events_table(
    events: list[Any], now: datetime | None = None, indent: str = ""
) -> str:
    """Render events newest-last like `kubectl get events`."""
    if not events:
        return f"{indent}<none>"

    def event_ts(ev: Any) -> datetime | None:
        return (
            ev.last_timestamp
            or ev.event_time
            or ev.metadata.creation_timestamp
        )

    def sort_key(ev: Any) -> datetime:
        return event_ts(ev) or datetime.min.replace(tzinfo=UTC)

    headers = ["AGE", "TYPE", "REASON", "OBJECT", "MESSAGE"]
    rows = []
    for ev in sorted(events, key=sort_key):
        ts = event_ts(ev)
        obj = ev.involved_object
        obj_ref = f"{obj.kind}/{obj.name}" if obj and obj.name else "<unknown>"
        count = f" (x{ev.count})" if ev.count and ev.count > 1 else ""
        message = (ev.message or "").replace("\n", " ")
        rows.append(
            [
                age(ts, now),
                ev.type or "",
                ev.reason or "",
                obj_ref,
                f"{message}{count}",
            ]
        )
    return _tabulate(headers, rows, indent=indent)

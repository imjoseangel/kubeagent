"""Read-only Kubernetes API calls, returned as formatted text.

Each function performs one typed apiserver request through `app.kube.client`
and renders the result with `app.kube.format`, returning the same compact
text the diagnostic tools used to get from `kubectl` stdout. Apiserver-level
failures (404 for a missing pod, 403 from RBAC, etc.) are caught and turned
into a short `API ERROR: ...` line so the agent sees the failure as tool
output rather than crashing the investigation loop.

These are synchronous/blocking; callers wrap them in `asyncio.to_thread`.
"""

import json
from collections.abc import Callable
from typing import Any

from kubernetes.client.exceptions import ApiException

from app.kube import client, format

_MAX_LOG_CHARS = 6000
_MAX_DEPLOYMENT_CHARS = 4000


def _api_error(exc: ApiException) -> str:
    reason = (exc.reason or "").strip()
    detail = ""
    try:
        body = json.loads(exc.body) if exc.body else {}
        detail = body.get("message", "")
    except (ValueError, TypeError):
        detail = (exc.body or "")[:300]
    text = f"API ERROR ({exc.status}): {reason}"
    if detail:
        text += f" — {detail}"
    return text


def _guarded[T](call: Callable[[], T]) -> T | str:
    try:
        return call()
    except ApiException as exc:
        return _api_error(exc)


def list_pods(namespace: str) -> str:
    result = _guarded(
        lambda: client.core_v1().list_namespaced_pod(namespace).items
    )
    if isinstance(result, str):
        return result
    return format.pods_table(result)


def describe_pod(namespace: str, pod: str) -> str:
    pod_obj = _guarded(
        lambda: client.core_v1().read_namespaced_pod(pod, namespace)
    )
    if isinstance(pod_obj, str):
        return pod_obj
    events = _guarded(
        lambda: (
            client.core_v1()
            .list_namespaced_event(
                namespace,
                field_selector=f"involvedObject.name={pod}",
            )
            .items
        )
    )
    # A failure fetching events shouldn't sink the whole describe.
    event_items = [] if isinstance(events, str) else events
    return format.describe_pod(pod_obj, event_items)


def pod_logs(
    namespace: str,
    pod: str,
    previous: bool = False,
    container: str | None = None,
) -> str:
    out = _guarded(
        lambda: client.core_v1().read_namespaced_pod_log(
            name=pod,
            namespace=namespace,
            container=container,
            previous=previous,
            tail_lines=200,
        )
    )
    return out[:_MAX_LOG_CHARS]


def list_events(namespace: str) -> str:
    result = _guarded(
        lambda: client.core_v1().list_namespaced_event(namespace).items
    )
    if isinstance(result, str):
        return result
    return format.events_table(result)


def deployment_detail(namespace: str, deployment: str) -> str:
    """Deployment status plus revision history from its ReplicaSets.

    Mirrors what `kubectl rollout history` / `get deployment -o json` gave
    the agent: enough to see the current revision, image, replica counts,
    and how many prior revisions exist.
    """
    dep = _guarded(
        lambda: client.apps_v1().read_namespaced_deployment(
            deployment, namespace
        )
    )
    if isinstance(dep, str):
        return dep

    api = client.apps_v1().api_client
    dep_dict = api.sanitize_for_serialization(dep)
    revisions = _revision_history(namespace, dep)

    summary = {
        "name": dep.metadata.name,
        "namespace": dep.metadata.namespace,
        "revision": (dep.metadata.annotations or {}).get(
            "deployment.kubernetes.io/revision"
        ),
        "replicas": {
            "desired": dep.spec.replicas,
            "ready": dep.status.ready_replicas if dep.status else None,
            "available": dep.status.available_replicas if dep.status else None,
            "updated": dep.status.updated_replicas if dep.status else None,
        },
        "images": [c.image for c in dep.spec.template.spec.containers],
        "revision_history": revisions,
        "conditions": [
            {"type": c.type, "status": c.status, "reason": c.reason}
            for c in (dep.status.conditions or [] if dep.status else [])
        ],
        "spec_template": dep_dict.get("spec", {}).get("template"),
    }
    return json.dumps(summary, indent=2, default=str)[:_MAX_DEPLOYMENT_CHARS]


def _revision_history(namespace: str, deployment: Any) -> list[dict]:
    """List this deployment's ReplicaSets with their revision numbers."""
    rs_list = _guarded(
        lambda: client.apps_v1().list_namespaced_replica_set(namespace).items
    )
    if isinstance(rs_list, str):
        return []
    dep_uid = deployment.metadata.uid
    revisions = []
    for rs in rs_list:
        owners = rs.metadata.owner_references or []
        if not any(o.uid == dep_uid for o in owners):
            continue
        revisions.append(
            {
                "revision": (rs.metadata.annotations or {}).get(
                    "deployment.kubernetes.io/revision"
                ),
                "replicaset": rs.metadata.name,
                "replicas": rs.spec.replicas,
                "images": [c.image for c in rs.spec.template.spec.containers],
            }
        )
    revisions.sort(key=lambda r: int(r["revision"] or 0))
    return revisions

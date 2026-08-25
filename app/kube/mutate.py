"""The only cluster-mutating path in kubeagent.

Not a generic passthrough: exactly two operations exist — a rolling restart
and a rollback to the previous revision — and this module is only ever
reached from `app/agents/write_tools.py` *after* an operator approval has
resolved. There is no code path that lets the LLM reach it directly.

Both operations are expressed as native apiserver requests (a strategic-merge
patch and a revision replace), so no `kubectl rollout` binary is involved.
"""

from datetime import UTC, datetime
from typing import Any

from kubernetes.client.exceptions import ApiException

from app.kube import client
from app.kube.safety import KubeAccessDenied

ALLOWED_ACTIONS = {"restart", "undo"}

# The same annotation key `kubectl rollout restart` uses, so a restart
# triggered by kubeagent is indistinguishable from a human's and interops
# with anyone still driving the deployment by hand.
_RESTART_ANNOTATION = "kubectl.kubernetes.io/restartedAt"
_REVISION_ANNOTATION = "deployment.kubernetes.io/revision"


def kube_mutate(
    action: str,
    deployment: str,
    namespace: str,
    allowed_namespaces: list[str],
) -> str:
    """Perform `restart` or `undo` on a deployment via the API server."""
    if action not in ALLOWED_ACTIONS:
        raise KubeAccessDenied(f"rollout action '{action}' is not permitted")
    if namespace not in allowed_namespaces:
        raise KubeAccessDenied(f"namespace '{namespace}' is not in scope")

    try:
        if action == "restart":
            return _restart(deployment, namespace)
        return _undo(deployment, namespace)
    except ApiException as exc:
        return f"COMMAND FAILED: {(exc.reason or 'API error').strip()[:600]}"


def _restart(deployment: str, namespace: str) -> str:
    """Trigger a rolling restart by stamping the pod template annotation."""
    stamp = datetime.now(UTC).isoformat()
    patch = {
        "spec": {
            "template": {
                "metadata": {"annotations": {_RESTART_ANNOTATION: stamp}}
            }
        }
    }
    client.apps_v1().patch_namespaced_deployment(deployment, namespace, patch)
    return (
        f"deployment.apps/{deployment} restarted "
        f"(rolling restart triggered at {stamp})"
    )


def _undo(deployment: str, namespace: str) -> str:
    """Roll back to the previous revision's pod template.

    Reproduces `kubectl rollout undo`: find the ReplicaSet one revision
    below the deployment's current revision and re-apply its pod template.
    """
    apps = client.apps_v1()
    dep = apps.read_namespaced_deployment(deployment, namespace)

    def revision(obj: Any) -> int:
        annotations = obj.metadata.annotations or {}
        return int(annotations.get(_REVISION_ANNOTATION, 0))

    current = revision(dep)
    owned = [
        rs
        for rs in apps.list_namespaced_replica_set(namespace).items
        if any(
            o.uid == dep.metadata.uid
            for o in (rs.metadata.owner_references or [])
        )
    ]

    previous = [rs for rs in owned if revision(rs) < current]
    if not previous:
        return (
            f"COMMAND FAILED: no previous revision found for "
            f"deployment.apps/{deployment} to roll back to"
        )
    target = max(previous, key=revision)

    template = target.spec.template
    # Drop the pod-template-hash the ReplicaSet controller injects; the
    # deployment controller recomputes it for the new revision.
    if template.metadata and template.metadata.labels:
        template.metadata.labels.pop("pod-template-hash", None)

    # The client serializes nested model objects in the patch body itself.
    patch = {"spec": {"template": template}}
    apps.patch_namespaced_deployment(deployment, namespace, patch)
    return (
        f"deployment.apps/{deployment} rolled back to revision "
        f"{revision(target)} (from {current})"
    )

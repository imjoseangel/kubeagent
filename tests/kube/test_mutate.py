from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from app.kube.mutate import kube_mutate
from app.kube.safety import KubeAccessDenied


def test_invalid_action_is_denied() -> None:
    with pytest.raises(KubeAccessDenied):
        kube_mutate("delete", "web", "kubeagent", ["kubeagent"])


def test_namespace_outside_allowlist_is_denied() -> None:
    with pytest.raises(KubeAccessDenied):
        kube_mutate("restart", "web", "prod", ["kubeagent"])


def test_restart_patches_template_annotation() -> None:
    apps = MagicMock()
    with patch("app.kube.mutate.client.apps_v1", return_value=apps):
        out = kube_mutate("restart", "web", "kubeagent", ["kubeagent"])

    apps.patch_namespaced_deployment.assert_called_once()
    args = apps.patch_namespaced_deployment.call_args.args
    assert args[0] == "web" and args[1] == "kubeagent"
    annotations = args[2]["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in annotations
    assert "restarted" in out


def _replicaset(uid: str, revision: str) -> SimpleNamespace:
    template = SimpleNamespace(
        metadata=SimpleNamespace(labels={"pod-template-hash": "abc"})
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(
            annotations={"deployment.kubernetes.io/revision": revision},
            owner_references=[SimpleNamespace(uid=uid)],
        ),
        spec=SimpleNamespace(template=template),
    )


def test_undo_rolls_back_to_previous_revision() -> None:
    apps = MagicMock()
    dep = SimpleNamespace(
        metadata=SimpleNamespace(
            uid="dep-uid",
            annotations={"deployment.kubernetes.io/revision": "3"},
        )
    )
    apps.read_namespaced_deployment.return_value = dep
    apps.list_namespaced_replica_set.return_value = SimpleNamespace(
        items=[
            _replicaset("dep-uid", "1"),
            _replicaset("dep-uid", "2"),
            _replicaset("dep-uid", "3"),
            _replicaset("other-uid", "9"),  # different owner, ignored
        ]
    )

    with patch("app.kube.mutate.client.apps_v1", return_value=apps):
        out = kube_mutate("undo", "web", "kubeagent", ["kubeagent"])

    # Rolls back to revision 2 (highest below current 3) and strips the hash
    apps.patch_namespaced_deployment.assert_called_once()
    patched_template = apps.patch_namespaced_deployment.call_args.args[2][
        "spec"
    ]["template"]
    assert "pod-template-hash" not in patched_template.metadata.labels
    assert "revision 2" in out


def test_undo_does_not_mutate_the_fetched_replicaset() -> None:
    apps = MagicMock()
    dep = SimpleNamespace(
        metadata=SimpleNamespace(
            uid="dep-uid",
            annotations={"deployment.kubernetes.io/revision": "3"},
        )
    )
    apps.read_namespaced_deployment.return_value = dep
    previous = _replicaset("dep-uid", "2")
    apps.list_namespaced_replica_set.return_value = SimpleNamespace(
        items=[previous, _replicaset("dep-uid", "3")]
    )

    with patch("app.kube.mutate.client.apps_v1", return_value=apps):
        kube_mutate("undo", "web", "kubeagent", ["kubeagent"])

    # The patch strips the hash from a copy; the source object keeps it, so a
    # failed patch can't leave cached cluster state half-modified.
    assert previous.spec.template.metadata.labels["pod-template-hash"] == "abc"


def test_undo_with_no_previous_revision_reports_failure() -> None:
    apps = MagicMock()
    dep = SimpleNamespace(
        metadata=SimpleNamespace(
            uid="dep-uid",
            annotations={"deployment.kubernetes.io/revision": "1"},
        )
    )
    apps.read_namespaced_deployment.return_value = dep
    apps.list_namespaced_replica_set.return_value = SimpleNamespace(
        items=[_replicaset("dep-uid", "1")]
    )

    with patch("app.kube.mutate.client.apps_v1", return_value=apps):
        out = kube_mutate("undo", "web", "kubeagent", ["kubeagent"])

    apps.patch_namespaced_deployment.assert_not_called()
    assert "no previous revision" in out


def test_apiserver_failure_is_reported_not_raised() -> None:
    apps = MagicMock()
    apps.patch_namespaced_deployment.side_effect = ApiException(
        status=409, reason="Conflict"
    )
    with patch("app.kube.mutate.client.apps_v1", return_value=apps):
        out = kube_mutate("restart", "web", "kubeagent", ["kubeagent"])

    # An apiserver error becomes tool output, not an exception that would
    # crash the agent loop mid-remediation.
    assert out.startswith("COMMAND FAILED")
    assert "Conflict" in out

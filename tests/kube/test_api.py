from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kubernetes.client.exceptions import ApiException

from app.kube import api


def _core(**methods: object) -> MagicMock:
    core = MagicMock()
    for name, value in methods.items():
        getattr(core, name).return_value = value
    return core


def test_list_pods_formats_items() -> None:
    core = MagicMock()
    core.list_namespaced_pod.return_value = SimpleNamespace(items=[])
    with patch("app.kube.api.client.core_v1", return_value=core):
        out = api.list_pods("staging")
    assert "No pods found" in out


def test_list_pods_translates_api_exception() -> None:
    core = MagicMock()
    core.list_namespaced_pod.side_effect = ApiException(
        status=403, reason="Forbidden"
    )
    with patch("app.kube.api.client.core_v1", return_value=core):
        out = api.list_pods("staging")
    assert out.startswith("API ERROR (403)")
    assert "Forbidden" in out


def test_pod_logs_truncates() -> None:
    core = MagicMock()
    core.read_namespaced_pod_log.return_value = "x" * 10000
    with patch("app.kube.api.client.core_v1", return_value=core):
        out = api.pod_logs("staging", "web-1", previous=True, container="app")
    assert len(out) == api._MAX_LOG_CHARS
    core.read_namespaced_pod_log.assert_called_once_with(
        name="web-1",
        namespace="staging",
        container="app",
        previous=True,
        tail_lines=200,
    )


def test_describe_pod_survives_event_fetch_failure() -> None:
    core = MagicMock()
    core.read_namespaced_pod.return_value = SimpleNamespace(
        metadata=SimpleNamespace(
            name="web-1", namespace="staging", creation_timestamp=None
        ),
        spec=SimpleNamespace(containers=[], node_name="node-1"),
        status=SimpleNamespace(
            phase="Running", pod_ip="1.2.3.4", container_statuses=[]
        ),
    )
    core.list_namespaced_event.side_effect = ApiException(
        status=403, reason="Forbidden"
    )
    with patch("app.kube.api.client.core_v1", return_value=core):
        out = api.describe_pod("staging", "web-1")
    # Pod detail still renders; events section falls back to <none>.
    assert "Name:      web-1" in out
    assert "Events:" in out

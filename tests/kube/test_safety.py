from unittest.mock import MagicMock, patch

import pytest

from app.kube.safety import KubectlDenied, kubectl


def _fake_result(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_forbidden_verb_is_denied_before_any_subprocess_call() -> None:
    with patch("app.kube.safety.subprocess.run") as mocked_run:
        with pytest.raises(KubectlDenied):
            kubectl(["delete", "pod", "web-1"], "staging", ["staging"])

    mocked_run.assert_not_called()


def test_forbidden_operation_anywhere_in_args_is_denied() -> None:
    with patch("app.kube.safety.subprocess.run") as mocked_run:
        with pytest.raises(KubectlDenied):
            kubectl(["get", "pods", "exec"], "staging", ["staging"])

    mocked_run.assert_not_called()


def test_secrets_are_denied() -> None:
    with patch("app.kube.safety.subprocess.run") as mocked_run:
        with pytest.raises(KubectlDenied):
            kubectl(["get", "secrets"], "staging", ["staging"])

    mocked_run.assert_not_called()


def test_namespace_outside_allowlist_is_denied() -> None:
    with patch("app.kube.safety.subprocess.run") as mocked_run:
        with pytest.raises(KubectlDenied):
            kubectl(["get", "pods"], "prod", ["staging"])

    mocked_run.assert_not_called()


def test_allowed_call_builds_expected_argv() -> None:
    with patch(
        "app.kube.safety.subprocess.run",
        return_value=_fake_result(stdout="pod-a  Running"),
    ) as mocked_run:
        out = kubectl(["get", "pods"], "staging", ["staging"])

    mocked_run.assert_called_once_with(
        ["kubectl", "get", "pods", "-n", "staging"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert out == "pod-a  Running"


def test_call_without_namespace_skips_namespace_flag() -> None:
    with patch(
        "app.kube.safety.subprocess.run",
        return_value=_fake_result(stdout="ok"),
    ) as mocked_run:
        kubectl(["get", "pods"], None, [])

    mocked_run.assert_called_once_with(
        ["kubectl", "get", "pods"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_command_failure_returns_truncated_stderr() -> None:
    with patch(
        "app.kube.safety.subprocess.run",
        return_value=_fake_result(returncode=1, stderr="not found"),
    ):
        out = kubectl(["get", "pods"], "staging", ["staging"])

    assert out == "COMMAND FAILED: not found"

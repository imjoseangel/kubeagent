import pytest

from app.kube.safety import KubeAccessDenied, ensure_namespace_allowed


def test_namespace_in_allowlist_is_permitted() -> None:
    # WHEN a namespace inside the allowlist is checked THEN it does not raise
    ensure_namespace_allowed("staging", ["staging", "default"])


def test_namespace_outside_allowlist_is_denied() -> None:
    with pytest.raises(KubeAccessDenied):
        ensure_namespace_allowed("prod", ["staging"])


def test_empty_allowlist_denies_every_namespace() -> None:
    # Fail closed: an empty allowlist means nothing is reachable.
    with pytest.raises(KubeAccessDenied):
        ensure_namespace_allowed("staging", [])


def test_none_namespace_is_permitted() -> None:
    # A None namespace (cluster-scoped/version probe) skips the check.
    ensure_namespace_allowed(None, [])

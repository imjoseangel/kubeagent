"""Direct Kubernetes API access.

Every cluster call in kubeagent goes through the official `kubernetes`
Python client, which talks to the apiserver over HTTPS. No `kubectl` (or any
other) binary is ever invoked — the previous subprocess-based approach also
required a `kubectl` binary that the runtime container image never shipped.

Configuration is loaded lazily and cached: in-cluster first (from the mounted
ServiceAccount token at `/var/run/secrets/kubernetes.io/serviceaccount`),
falling back to the local kubeconfig so the standalone example and local
development keep working against whatever context is active.
"""

import threading

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

_lock = threading.Lock()
_loaded = False


def _ensure_config_loaded() -> None:
    """Load kube config exactly once, in-cluster first then kubeconfig."""
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config()
        _loaded = True


def core_v1() -> client.CoreV1Api:
    """CoreV1Api client for pods, pod logs, and events."""
    _ensure_config_loaded()
    return client.CoreV1Api()


def apps_v1() -> client.AppsV1Api:
    """AppsV1Api client for deployments and replicasets."""
    _ensure_config_loaded()
    return client.AppsV1Api()


def version_api() -> client.VersionApi:
    """VersionApi client, used only for the apiserver reachability probe."""
    _ensure_config_loaded()
    return client.VersionApi()

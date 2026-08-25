import asyncio
from dataclasses import dataclass

import httpx
from kubernetes.client.exceptions import ApiException

from app.core.config import settings
from app.kube import client


@dataclass
class CheckResult:
    name: str
    ok: bool
    status_code: int
    message: str


async def check_kube_api() -> CheckResult:
    """Verify the Kubernetes API is reachable.

    Hits `/version` via the client's `VersionApi`, which every cluster's
    default bootstrap RBAC (`system:discovery`) grants to any authenticated
    caller — this proves apiserver reachability without depending on
    kubeagent's own read/write RBAC grants, and needs no `kubectl` binary.
    """

    def _run() -> str:
        return client.version_api().get_code().git_version

    try:
        version = await asyncio.to_thread(_run)
    except ApiException as exc:
        return CheckResult(
            "kube_api", False, exc.status or 503, (exc.reason or "")[:200]
        )
    except Exception as exc:  # noqa: BLE001 - report any connectivity failure
        return CheckResult("kube_api", False, 503, str(exc)[:200])

    return CheckResult(
        "kube_api", True, 200, f"Kubernetes API reachable ({version})"
    )


async def check_llm() -> CheckResult:
    """Verify the configured LiteLLM endpoint is network-reachable.

    Any HTTP response — even a non-2xx one — counts as reachable, since
    this checks host/network connectivity rather than authentication.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(settings.litellm_base_url)
    except httpx.HTTPError as exc:
        return CheckResult("llm", False, 503, str(exc)[:200])

    return CheckResult(
        "llm",
        True,
        response.status_code,
        "LiteLLM endpoint reachable",
    )

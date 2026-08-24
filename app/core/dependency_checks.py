import asyncio
import subprocess
from dataclasses import dataclass

import httpx

from app.core.config import settings


@dataclass
class CheckResult:
    name: str
    ok: bool
    status_code: int
    message: str


async def check_kubectl() -> CheckResult:
    """Verify the Kubernetes API is reachable.

    Hits `/version`, which every cluster's default bootstrap RBAC
    (`system:discovery`) grants to any authenticated caller — this proves
    apiserver reachability without depending on kubeagent's own
    read/write RBAC grants.
    """

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["kubectl", "get", "--raw", "/version", "--request-timeout=3s"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    try:
        result = await asyncio.to_thread(_run)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("kubectl", False, 503, str(exc)[:200])

    if result.returncode == 0:
        return CheckResult("kubectl", True, 200, "Kubernetes API reachable")
    return CheckResult(
        "kubectl", False, 503, result.stderr.strip()[:200] or "unknown error"
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

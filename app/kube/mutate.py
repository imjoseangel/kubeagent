import subprocess

from app.kube.safety import KubectlDenied

# Not a generic kubectl passthrough: exactly two command shapes exist, and
# this function is only ever called from app/agents/write_tools.py *after*
# an operator approval has resolved. There is no code path that lets the
# LLM reach this directly.
ALLOWED_ACTIONS = {"restart", "undo"}


def kubectl_mutate(
    action: str,
    deployment: str,
    namespace: str,
    allowed_namespaces: list[str],
    timeout: int = 30,
) -> str:
    """Run `kubectl rollout <action> deployment/<deployment> -n <ns>`."""
    if action not in ALLOWED_ACTIONS:
        raise KubectlDenied(f"rollout action '{action}' is not permitted")
    if namespace not in allowed_namespaces:
        raise KubectlDenied(f"namespace '{namespace}' is not in scope")

    cmd = [
        "kubectl",
        "rollout",
        action,
        f"deployment/{deployment}",
        "-n",
        namespace,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode != 0:
        return f"COMMAND FAILED: {result.stderr.strip()[:600]}"
    return result.stdout[:2000]

import subprocess

# Read verbs only. Nothing reachable through this function can mutate
# cluster state — mutation goes through the separate, far narrower
# app/kube/mutate.py path instead.
ALLOWED_VERBS = {"get", "describe", "logs", "top", "events"}
FORBIDDEN = {
    "delete",
    "exec",
    "edit",
    "apply",
    "patch",
    "replace",
    "cp",
    "attach",
    "port-forward",
}


class KubectlDenied(Exception):
    """Raised when a call falls outside the permitted read-only surface."""


def kubectl(
    args: list[str],
    namespace: str | None,
    allowed_namespaces: list[str],
    timeout: int = 20,
) -> str:
    """Run one read-only kubectl command and return truncated stdout.

    `allowed_namespaces` is passed in explicitly (rather than read from
    global settings) so this function stays easy to unit test and so the
    standalone example script can reuse the same logic without importing
    from `app`.
    """
    if not args or args[0] not in ALLOWED_VERBS:
        raise KubectlDenied(f"verb '{args[0] if args else ''}' is not permitted")
    if FORBIDDEN & set(args):
        raise KubectlDenied("forbidden operation in arguments")
    if any("secret" in a.lower() for a in args):
        raise KubectlDenied("secrets are out of scope for this agent")

    cmd = ["kubectl", *args]
    if namespace:
        if namespace not in allowed_namespaces:
            raise KubectlDenied(f"namespace '{namespace}' is not in scope")
        cmd += ["-n", namespace]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode != 0:
        return f"COMMAND FAILED: {result.stderr.strip()[:600]}"
    return result.stdout[:6000]

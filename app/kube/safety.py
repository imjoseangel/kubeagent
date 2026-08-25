"""Access policy for cluster calls.

With the move to the typed Kubernetes API client, most of the old
string-parsing safety surface disappears: the read path only ever calls
pod/deployment/event/log endpoints, so there is no verb to allow-list, no
`secrets` request to intercept, and no shell to escape. The one policy that
still matters is namespace scoping — kubeagent must never touch a namespace
outside its configured allowlist — so that is what this module enforces.

Mutation lives behind an entirely separate, far narrower path
(`app/kube/mutate.py`) and is additionally gated on human approval.
"""


class KubeAccessDenied(Exception):
    """Raised when a call falls outside kubeagent's permitted scope."""


def ensure_namespace_allowed(
    namespace: str | None, allowed_namespaces: list[str]
) -> None:
    """Fail closed unless `namespace` is in the configured allowlist.

    An empty allowlist means no namespace is reachable. `allowed_namespaces`
    is passed in explicitly (rather than read from global settings) so this
    stays trivially unit-testable and the standalone example can reuse it.
    """
    if namespace is None:
        return
    if namespace not in allowed_namespaces:
        raise KubeAccessDenied(f"namespace '{namespace}' is not in scope")

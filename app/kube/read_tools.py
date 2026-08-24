import asyncio
from collections.abc import Callable
from typing import Any

from llama_index.core.tools import BaseTool, FunctionTool

from app.agents.steer import Trail
from app.kube.envelope import envelope
from app.kube.safety import KubectlDenied, kubectl


def make_read_tools(
    trail: Trail, namespace: str, allowed_namespaces: list[str]
) -> list[BaseTool | Callable[..., Any]]:
    """Build the diagnostic-ladder tools for one investigation.

    Returned as fresh closures (rather than module-level functions) so each
    investigation's `Trail` and target namespace stay isolated from every
    other concurrently running investigation.
    """

    async def get_pods() -> dict:
        """List pods with status, restart counts, and age. Start every
        investigation here to identify which pods are unhealthy."""
        try:
            out = await asyncio.to_thread(
                kubectl,
                ["get", "pods", "-o", "wide"],
                namespace,
                allowed_namespaces,
            )
        except KubectlDenied as exc:
            return envelope("get_pods", "Denied.", {}, str(exc))
        note = trail.record("get_pods")
        return envelope("get_pods", out + note, {"namespace": namespace})

    async def describe_pod(pod: str) -> dict:
        """Show a pod's full detail including its Events, container exit
        codes, resource limits, and probe configuration. Use this second —
        the Events section names most failure causes directly."""
        try:
            out = await asyncio.to_thread(
                kubectl,
                ["describe", "pod", pod],
                namespace,
                allowed_namespaces,
            )
        except KubectlDenied as exc:
            return envelope("describe_pod", "Denied.", {}, str(exc))
        note = trail.record(f"describe_pod:{pod}")
        return envelope("describe_pod", out + note, {"pod": pod})

    async def get_logs(
        pod: str, previous: bool = False, container: str | None = None
    ) -> dict:
        """Fetch the last 200 log lines from a pod. Set previous=True to
        read the logs of a container that already crashed, which is
        required for CrashLoopBackOff and OOMKilled investigations."""
        args = ["logs", pod, "--tail=200"]
        if previous:
            args.append("--previous")
        if container:
            args += ["-c", container]
        try:
            out = await asyncio.to_thread(
                kubectl, args, namespace, allowed_namespaces
            )
        except KubectlDenied as exc:
            return envelope("get_logs", "Denied.", {}, str(exc))
        note = trail.record(f"get_logs:{pod}:previous={previous}")
        return envelope(
            "get_logs", out + note, {"pod": pod, "previous": previous}
        )

    async def get_events() -> dict:
        """List recent namespace events, newest last. Use this for
        scheduling failures, image pull errors, and volume mount
        problems."""
        try:
            out = await asyncio.to_thread(
                kubectl,
                ["get", "events", "--sort-by=.lastTimestamp"],
                namespace,
                allowed_namespaces,
            )
        except KubectlDenied as exc:
            return envelope("get_events", "Denied.", {}, str(exc))
        note = trail.record("get_events")
        return envelope("get_events", out + note, {"namespace": namespace})

    async def get_rollout_history(deployment: str) -> dict:
        """Show revision history for a deployment. Use this when a
        workload was previously healthy and the failure looks like it
        followed a change."""
        try:
            out = await asyncio.to_thread(
                kubectl,
                ["get", "deployment", deployment, "-o", "json"],
                namespace,
                allowed_namespaces,
            )
        except KubectlDenied as exc:
            return envelope("get_rollout_history", "Denied.", {}, str(exc))
        note = trail.record(f"get_rollout_history:{deployment}")
        return envelope(
            "get_rollout_history",
            out[:4000] + note,
            {"deployment": deployment},
        )

    return [
        FunctionTool.from_defaults(fn=get_pods, name="get_pods"),
        FunctionTool.from_defaults(fn=describe_pod, name="describe_pod"),
        FunctionTool.from_defaults(fn=get_logs, name="get_logs"),
        FunctionTool.from_defaults(fn=get_events, name="get_events"),
        FunctionTool.from_defaults(
            fn=get_rollout_history, name="get_rollout_history"
        ),
    ]

import asyncio
from collections.abc import Callable
from typing import Any

from llama_index.core.tools import BaseTool, FunctionTool

from app.agents.hitl import ApprovalStore
from app.agents.steer import Trail
from app.kube.envelope import envelope
from app.kube.mutate import kubectl_mutate
from app.kube.safety import KubectlDenied
from app.persistence.store import InvestigationStore
from app.schemas import InvestigationStatus


def make_write_tools(
    investigation_id: str,
    namespace: str,
    allowed_namespaces: list[str],
    trail: Trail,
    approval_store: ApprovalStore,
    investigation_store: InvestigationStore,
    approval_timeout_seconds: int,
) -> list[BaseTool | Callable[..., Any]]:
    """Build the two gated remediation tools for one investigation.

    Each call pauses the agent loop behind `ApprovalStore` until an
    operator decides via `POST /diagnose/{id}/decisions`, or the approval
    times out (treated as a rejection).
    """

    async def _gated_rollout(action: str, deployment: str) -> dict:
        tool_name = (
            "restart_deployment"
            if action == "restart"
            else "rollback_deployment"
        )
        investigation = investigation_store.get(investigation_id)
        pending = approval_store.request(
            investigation_id,
            tool_name,
            {"deployment": deployment, "namespace": namespace},
        )
        if investigation is not None:
            investigation.status = InvestigationStatus.AWAITING_APPROVAL
        note = trail.record(f"{tool_name}:{deployment}")

        try:
            decision, reason = await asyncio.wait_for(
                pending.future, timeout=approval_timeout_seconds
            )
        except TimeoutError:
            approval_store.discard(investigation_id)
            if investigation is not None:
                investigation.status = InvestigationStatus.RUNNING
            return envelope(
                tool_name,
                f"No decision received within {approval_timeout_seconds}s "
                "— treated as rejected." + note,
                {"deployment": deployment, "approved": False},
            )

        if investigation is not None:
            investigation.status = InvestigationStatus.RUNNING

        if decision != "approve":
            reason_note = f" Reason: {reason}" if reason else ""
            return envelope(
                tool_name,
                f"Operator rejected this action.{reason_note}" + note,
                {"deployment": deployment, "approved": False},
            )

        try:
            out = await asyncio.to_thread(
                kubectl_mutate,
                action,
                deployment,
                namespace,
                allowed_namespaces,
            )
        except KubectlDenied as exc:
            return envelope(tool_name, "Denied.", {}, str(exc))
        return envelope(
            tool_name, out + note, {"deployment": deployment, "approved": True}
        )

    async def restart_deployment(deployment: str) -> dict:
        """Trigger a rolling restart of a deployment. This CHANGES cluster
        state and requires human approval before it runs."""
        return await _gated_rollout("restart", deployment)

    async def rollback_deployment(deployment: str) -> dict:
        """Roll a deployment back to its previous revision. This CHANGES
        cluster state and requires human approval before it runs."""
        return await _gated_rollout("undo", deployment)

    return [
        FunctionTool.from_defaults(
            fn=restart_deployment, name="restart_deployment"
        ),
        FunctionTool.from_defaults(
            fn=rollback_deployment, name="rollback_deployment"
        ),
    ]

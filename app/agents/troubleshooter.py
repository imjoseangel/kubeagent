from llama_index.core.agent.workflow import (
    AgentOutput,
    AgentWorkflow,
    FunctionAgent,
)

from app.agents.hitl import approval_store
from app.agents.prompts import SYSTEM_PROMPT
from app.agents.steer import Trail
from app.agents.write_tools import make_write_tools
from app.core.config import settings
from app.core.llm import build_llm
from app.kube.read_tools import make_read_tools
from app.persistence.store import store
from app.schemas import InvestigationStatus


def build_agent(investigation_id: str, namespace: str) -> FunctionAgent:
    investigation = store.get(investigation_id)
    shared_steps = investigation.trail if investigation is not None else None
    trail = Trail(max_hops=settings.kube_max_hops, steps=shared_steps)
    read_tools = make_read_tools(
        trail, namespace, settings.kube_allowed_namespaces
    )
    write_tools = make_write_tools(
        investigation_id,
        namespace,
        settings.kube_allowed_namespaces,
        trail,
        approval_store,
        store,
        settings.approval_timeout_seconds,
    )
    return FunctionAgent(
        name="Troubleshooter",
        description="Autonomous Kubernetes troubleshooting investigator.",
        system_prompt=SYSTEM_PROMPT,
        llm=build_llm(),
        tools=read_tools + write_tools,
        can_handoff_to=[],
    )


async def run_investigation(
    investigation_id: str, namespace: str, focus: str | None
) -> None:
    """Drive one investigation's agent loop to completion.

    Runs as a background asyncio task so a write tool's approval wait
    (app/agents/write_tools.py) can genuinely suspend the loop across
    separate HTTP requests without any workflow serialization.
    """
    investigation = store.get(investigation_id)
    if investigation is None:
        return

    user_msg = f"Investigate namespace {namespace!r}."
    if focus:
        user_msg += f" Focus hint from the operator: {focus}"

    try:
        agent = build_agent(investigation_id, namespace)
        workflow = AgentWorkflow(agents=[agent], root_agent="Troubleshooter")
        handler = workflow.run(user_msg=user_msg, max_iterations=40)

        final_content = ""
        async for ev in handler.stream_events():
            if (
                isinstance(ev, AgentOutput)
                and ev.response
                and ev.response.content
            ):
                final_content = ev.response.content
        await handler

        investigation.result = final_content
        investigation.status = InvestigationStatus.COMPLETED
    except Exception as exc:  # noqa: BLE001 - surface any failure on the investigation
        investigation.status = InvestigationStatus.FAILED
        investigation.error = str(exc)[:600]

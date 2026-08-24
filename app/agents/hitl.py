import asyncio
import datetime as dt
from dataclasses import dataclass


@dataclass
class PendingApproval:
    investigation_id: str
    tool_name: str
    arguments: dict
    requested_at: str
    future: asyncio.Future


class ApprovalStore:
    """In-memory, `asyncio.Future`-based human approval gate.

    LlamaIndex has no equivalent of LangChain's `HumanInTheLoopMiddleware`,
    so a write tool that needs approval calls `request()`, gets back a
    `PendingApproval`, and `await`s its future. Because the investigation
    runs as a background task rather than inline in a request/response
    cycle, the agent loop genuinely pauses mid tool-call and resumes
    in-process once `POST /diagnose/{id}/decisions` calls `resolve()`.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}

    def request(
        self, investigation_id: str, tool_name: str, arguments: dict
    ) -> PendingApproval:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        pending = PendingApproval(
            investigation_id=investigation_id,
            tool_name=tool_name,
            arguments=arguments,
            requested_at=dt.datetime.now(dt.UTC).isoformat(),
            future=future,
        )
        self._pending[investigation_id] = pending
        return pending

    def get(self, investigation_id: str) -> PendingApproval | None:
        return self._pending.get(investigation_id)

    def resolve(
        self, investigation_id: str, decision: str, reason: str | None = None
    ) -> bool:
        pending = self._pending.pop(investigation_id, None)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result((decision, reason))
        return True

    def discard(self, investigation_id: str) -> None:
        """Drop a pending approval that timed out without a decision."""
        self._pending.pop(investigation_id, None)


approval_store = ApprovalStore()

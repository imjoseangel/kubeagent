import datetime as dt
import uuid
from dataclasses import dataclass, field

from app.schemas import InvestigationStatus


@dataclass
class Investigation:
    id: str
    namespace: str
    status: InvestigationStatus = InvestigationStatus.RUNNING
    trail: list[str] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    created_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.UTC).isoformat()
    )


class InvestigationStore:
    """In-memory investigation registry.

    No database — investigations live for the process lifetime, matching
    the scope of a reference service (the boilerplate template itself keeps
    A2A task state in an `InMemoryTaskStore`).
    """

    def __init__(self) -> None:
        self._investigations: dict[str, Investigation] = {}

    def create(self, namespace: str) -> Investigation:
        investigation = Investigation(
            id=str(uuid.uuid4()), namespace=namespace
        )
        self._investigations[investigation.id] = investigation
        return investigation

    def get(self, investigation_id: str) -> Investigation | None:
        return self._investigations.get(investigation_id)

    def list_all(self) -> list[Investigation]:
        return sorted(
            self._investigations.values(),
            key=lambda i: i.created_at,
            reverse=True,
        )


store = InvestigationStore()

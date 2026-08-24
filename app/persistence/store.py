import datetime as dt
import threading
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
        self._lock = threading.Lock()

    def create(self, namespace: str) -> Investigation:
        investigation = Investigation(
            id=str(uuid.uuid4()), namespace=namespace
        )
        with self._lock:
            self._investigations[investigation.id] = investigation
        return investigation

    def get(self, investigation_id: str) -> Investigation | None:
        with self._lock:
            return self._investigations.get(investigation_id)

    def list_all(self) -> list[Investigation]:
        with self._lock:
            investigations = list(self._investigations.values())
        return sorted(investigations, key=lambda i: i.created_at, reverse=True)

    def counts_by_status(self) -> dict[InvestigationStatus, int]:
        with self._lock:
            investigations = list(self._investigations.values())
        counts = dict.fromkeys(InvestigationStatus, 0)
        for investigation in investigations:
            counts[investigation.status] += 1
        return counts


store = InvestigationStore()

from enum import StrEnum

from pydantic import BaseModel, Field


class InvestigationStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class DiagnoseRequest(BaseModel):
    namespace: str = Field(
        ..., description="Namespace to investigate. Must be allowlisted."
    )
    focus: str | None = Field(
        default=None,
        description="Optional free-text hint (e.g. a pod or deployment name).",
    )


class DiagnoseResponse(BaseModel):
    id: str
    status: InvestigationStatus


class InvestigationSummary(BaseModel):
    id: str
    namespace: str
    status: InvestigationStatus
    created_at: str


class PendingApprovalView(BaseModel):
    tool_name: str
    arguments: dict
    requested_at: str


class InvestigationDetail(BaseModel):
    id: str
    namespace: str
    status: InvestigationStatus
    trail: list[str]
    pending_approval: PendingApprovalView | None = None
    result: str | None = None
    error: str | None = None


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class DecisionRequest(BaseModel):
    decision: Decision
    reason: str | None = None

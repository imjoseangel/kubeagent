from enum import StrEnum

from pydantic import BaseModel, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    role: Role = Field(..., description="Role of the message author.")
    content: str = Field(..., description="Message content.")


class ChatCompletionRequest(BaseModel):
    messages: list[Message] = Field(
        ...,
        description=("Conversation history. Must end with a `user` message."),
    )
    enable_temperature: bool = Field(
        default=False,
        description=(
            "If True, forward `temperature` to the upstream model. "
            "Enable only when the target model is known to accept it."
        ),
    )


class ChatCompletionResponse(BaseModel):
    model: str
    content: str
    role: str


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

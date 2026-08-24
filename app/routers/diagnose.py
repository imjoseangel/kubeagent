import asyncio

from fastapi import APIRouter, HTTPException, status

from app.agents.hitl import approval_store
from app.agents.troubleshooter import run_investigation
from app.dependencies import settings_dependency
from app.persistence.store import store
from app.schemas import (
    DecisionRequest,
    DiagnoseRequest,
    DiagnoseResponse,
    InvestigationDetail,
    InvestigationSummary,
    PendingApprovalView,
)

router = APIRouter(prefix="/diagnose", tags=["diagnose"])


@router.get(path="", response_model=list[InvestigationSummary])
async def list_diagnoses() -> list[InvestigationSummary]:
    return [
        InvestigationSummary(
            id=investigation.id,
            namespace=investigation.namespace,
            status=investigation.status,
            created_at=investigation.created_at,
        )
        for investigation in store.list_all()
    ]


@router.post(
    path="",
    response_model=DiagnoseResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_diagnosis(
    request: DiagnoseRequest, settings: settings_dependency
) -> DiagnoseResponse:
    if request.namespace not in settings.kube_allowed_namespaces:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"namespace '{request.namespace}' is not in scope",
        )
    investigation = store.create(namespace=request.namespace)
    asyncio.create_task(
        run_investigation(investigation.id, request.namespace, request.focus)
    )
    return DiagnoseResponse(id=investigation.id, status=investigation.status)


@router.get(path="/{investigation_id}", response_model=InvestigationDetail)
async def get_diagnosis(investigation_id: str) -> InvestigationDetail:
    investigation = store.get(investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="investigation not found",
        )

    pending = approval_store.get(investigation_id)
    pending_view = (
        PendingApprovalView(
            tool_name=pending.tool_name,
            arguments=pending.arguments,
            requested_at=pending.requested_at,
        )
        if pending is not None
        else None
    )
    return InvestigationDetail(
        id=investigation.id,
        namespace=investigation.namespace,
        status=investigation.status,
        trail=investigation.trail,
        pending_approval=pending_view,
        result=investigation.result,
        error=investigation.error,
    )


@router.post(
    path="/{investigation_id}/decisions",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def decide(investigation_id: str, decision: DecisionRequest) -> None:
    investigation = store.get(investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="investigation not found",
        )
    resolved = approval_store.resolve(
        investigation_id, decision.decision.value, decision.reason
    )
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no pending approval for this investigation",
        )

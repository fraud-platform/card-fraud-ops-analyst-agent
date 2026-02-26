"""Investigation routes for agentic API."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import RequireOpsRead, RequireOpsRun
from app.persistence.investigation_repository import InvestigationRepository
from app.schemas.v1.investigations import (
    InvestigationDetailResponse,
    InvestigationListResponse,
    InvestigationResponse,
    InvestigationSummary,
    RunRequest,
)
from app.services.investigation_service import InvestigationService
from app.templates.trace_viewer import render_trace_html

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.get("", response_model=InvestigationListResponse)
async def list_investigations(
    _auth: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    transaction_id: str | None = Query(None),
):
    """List investigations with optional filters."""
    repo = InvestigationRepository(session)
    investigations = await repo.list(
        limit=limit,
        offset=offset,
        status=status,
        transaction_id=transaction_id,
    )
    total = await repo.count(status=status, transaction_id=transaction_id)
    return InvestigationListResponse(
        investigations=[
            InvestigationSummary(
                investigation_id=inv["id"],
                transaction_id=inv["transaction_id"],
                status=inv["status"],
                severity=inv.get("severity", "LOW"),
                started_at=inv.get("started_at"),
                completed_at=inv.get("completed_at"),
            )
            for inv in investigations
        ],
        total=total,
    )


@router.post("/run", response_model=InvestigationResponse)
async def run_investigation(
    request: RunRequest,
    _auth: RequireOpsRun,
    session: AsyncSession = Depends(get_session),
):
    """Start a new fraud investigation."""
    service = InvestigationService(session)
    result = await service.run_investigation(
        transaction_id=request.transaction_id,
        mode=request.mode,
    )
    return InvestigationResponse(**_map_state_to_response(result))


@router.get("/{investigation_id}", response_model=InvestigationDetailResponse)
async def get_investigation(
    investigation_id: str,
    _auth: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
):
    """Get full investigation details."""
    service = InvestigationService(session)
    result = await service.get_investigation(investigation_id)
    return InvestigationDetailResponse(**result)


@router.get("/{investigation_id}/trace", response_class=HTMLResponse)
async def get_investigation_trace(
    investigation_id: str,
    _auth: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
):
    """Get HTML trace viewer for investigation."""
    service = InvestigationService(session)
    result = await service.get_investigation(investigation_id)
    html = render_trace_html(result)
    return HTMLResponse(content=html)


@router.post("/{investigation_id}/resume", response_model=InvestigationResponse)
async def resume_investigation(
    investigation_id: str,
    _auth: RequireOpsRun,
    session: AsyncSession = Depends(get_session),
):
    """Resume a failed or interrupted investigation."""
    service = InvestigationService(session)
    result = await service.resume_investigation(investigation_id)
    return InvestigationResponse(**_map_state_to_response(result))


@router.get("/{investigation_id}/rule-draft")
async def get_rule_draft(
    investigation_id: str,
    _auth: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
):
    """Get rule draft for an investigation."""
    from app.persistence.rule_draft_repository import RuleDraftRepository

    repo = RuleDraftRepository(session)
    draft = await repo.get_by_investigation(investigation_id)
    if draft is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"No rule draft found for investigation {investigation_id}")
    return draft


def _map_state_to_response(state: dict) -> dict:
    """Map InvestigationState dict to response fields."""
    started = state.get("started_at", "")
    completed = state.get("completed_at")
    total_ms = None
    if started and completed:
        try:
            t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(completed.replace("Z", "+00:00"))
            total_ms = int((t1 - t0).total_seconds() * 1000)
        except ValueError, TypeError:
            pass

    return {
        "investigation_id": state["investigation_id"],
        "transaction_id": state["transaction_id"],
        "status": state.get("status", "UNKNOWN"),
        "severity": state.get("severity", "LOW"),
        "model_mode": state.get("model_mode", "agentic"),
        "confidence_score": state.get("confidence_score", 0.0),
        "step_count": state.get("step_count", 0),
        "max_steps": state.get("max_steps", 20),
        "planner_decisions": state.get("planner_decisions", []),
        "tool_executions": state.get("tool_executions", []),
        "recommendations": state.get("recommendations", []),
        "started_at": started,
        "completed_at": completed,
        "total_duration_ms": total_ms,
    }

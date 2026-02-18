"""Investigation routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import RequireOpsRead, RequireOpsRun
from app.schemas.v1.investigations import DetailResponse, RunRequest, RunResponse
from app.services.investigation_service import InvestigationService

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post("/run", response_model=RunResponse)
async def run_investigation(
    request: RunRequest,
    user: RequireOpsRun,
    session: AsyncSession = Depends(get_session),
):
    """Run an investigation for a transaction."""
    service = InvestigationService(session)
    result = await service.run_investigation(
        mode=request.mode.value,
        transaction_id=request.transaction_id,
        case_id=request.case_id,
    )
    return result


@router.get("/{run_id}", response_model=DetailResponse)
async def get_investigation(
    run_id: str,
    user: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
):
    """Get investigation details by run ID."""
    service = InvestigationService(session)
    result = await service.get_investigation(run_id)

    if result is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Investigation not found: {run_id}")

    return DetailResponse(**result)

"""Rule draft routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import RequireOpsDraft
from app.schemas.v1.rule_drafts import CreateRequest, ExportRequest, RuleDraftResponse
from app.services.rule_draft_service import RuleDraftService

router = APIRouter(prefix="/rule-drafts", tags=["rule-drafts"])


@router.post("", response_model=RuleDraftResponse, status_code=201)
async def create_rule_draft(
    request: CreateRequest,
    user: RequireOpsDraft,
    session: AsyncSession = Depends(get_session),
):
    """Create rule draft from recommendation."""
    service = RuleDraftService(session)
    result = await service.create_draft(
        recommendation_id=request.recommendation_id,
        package_version=request.package_version,
        dry_run=request.dry_run,
    )
    return result


@router.post("/{rule_draft_id}/export", response_model=RuleDraftResponse)
async def export_rule_draft(
    rule_draft_id: str,
    request: ExportRequest,
    user: RequireOpsDraft,
    session: AsyncSession = Depends(get_session),
):
    """Export rule draft to rule management."""
    service = RuleDraftService(session)
    result = await service.export_draft(
        rule_draft_id=rule_draft_id,
        target=request.target,
        target_endpoint=request.target_endpoint,
    )
    return result

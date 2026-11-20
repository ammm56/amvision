"""训练和转换提交结果的确认接口。"""

from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    require_principal,
    require_scopes,
)
from backend.service.api.deps.db import get_session_factory
from backend.service.application.project_access import require_explicit_project_access
from backend.service.application.tasks.model_submission import (
    ModelSubmissionIdentity,
    model_submission_identity,
    resolve_model_submission,
)
from backend.service.infrastructure.db.session import SessionFactory

model_submissions_router = APIRouter(tags=["model-submissions"])


async def track_model_submission(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    submission_id: Annotated[UUID | None, Header(alias="X-Model-Submission-Id")] = None,
) -> AsyncIterator[None]:
    """向本次任务创建传递可选的回执编号，兼容未传编号的客户端。"""
    if submission_id is None:
        yield
        return
    token = model_submission_identity.set(
        ModelSubmissionIdentity(str(submission_id), principal.principal_id),
    )
    try:
        yield
    finally:
        model_submission_identity.reset(token)


class ModelSubmissionResolveBody(BaseModel):
    """发起提交时所用的项目。"""

    project_id: str = Field(min_length=1, max_length=128)


class ModelSubmissionResolveResponse(BaseModel):
    """已创建时提供稳定的任务编号。"""

    status: Literal["accepted", "not_created"]
    task_id: str | None = None


@model_submissions_router.post(
    "/model-submissions/{submission_id}/resolve", response_model=ModelSubmissionResolveResponse,
)
def resolve_submission(
    submission_id: UUID,
    body: ModelSubmissionResolveBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> ModelSubmissionResolveResponse:
    """确认本次提交；若事务尚未创建任务，则关闭原提交。"""
    require_explicit_project_access(
        visible_project_ids=principal.project_ids, project_id=body.project_id,
    )
    task_id = resolve_model_submission(
        session_factory, body.project_id, principal.principal_id, str(submission_id),
    )
    return ModelSubmissionResolveResponse(
        status="accepted" if task_id else "not_created", task_id=task_id,
    )

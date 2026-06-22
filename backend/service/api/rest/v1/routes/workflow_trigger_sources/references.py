"""WorkflowTriggerSource 相关资源摘要。"""

from __future__ import annotations

from fastapi import Request

from backend.service.application.errors import ResourceNotFoundError
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.api.rest.v1.routes.workflow_trigger_sources.services import (
    build_workflow_json_service_from_request,
    require_session_factory,
)


def try_build_runtime_reference_summary(
    *,
    request: Request,
    workflow_runtime_id: str,
) -> dict[str, object] | None:
    """按需读取 runtime 一跳摘要，不存在时返回 None。"""

    unit_of_work = SqlAlchemyUnitOfWork(require_session_factory(request).create_session())
    try:
        workflow_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(
            workflow_runtime_id
        )
    finally:
        unit_of_work.close()
    if workflow_runtime is None:
        return None
    return {
        "workflow_runtime_id": workflow_runtime.workflow_runtime_id,
        "project_id": workflow_runtime.project_id,
        "application_id": workflow_runtime.application_id,
        "display_name": workflow_runtime.display_name,
        "desired_state": workflow_runtime.desired_state,
        "observed_state": workflow_runtime.observed_state,
        "created_at": workflow_runtime.created_at,
        "updated_at": workflow_runtime.updated_at,
        "created_by": workflow_runtime.created_by,
        "updated_by": read_resource_updated_by(workflow_runtime.metadata),
    }


def try_build_application_reference_summary(
    *,
    request: Request,
    project_id: str,
    application_id: str,
) -> dict[str, object] | None:
    """按需读取 application 一跳摘要，不存在时返回 None。"""

    workflow_service = build_workflow_json_service_from_request(request)
    try:
        summary = workflow_service.get_application_summary(
            project_id=project_id,
            application_id=application_id,
        )
    except ResourceNotFoundError:
        return None
    return {
        "project_id": summary.project_id,
        "application_id": summary.application_id,
        "display_name": summary.display_name,
        "description": summary.description,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "created_by": summary.created_by,
        "updated_by": summary.updated_by,
        "template_id": summary.template_id,
        "template_version": summary.template_version,
    }


def read_resource_updated_by(metadata: dict[str, object]) -> str | None:
    """从资源 metadata 中读取最近修改主体。"""

    updated_by = metadata.get("updated_by")
    if not isinstance(updated_by, str):
        return None
    normalized_updated_by = updated_by.strip()
    return normalized_updated_by or None


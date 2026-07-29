"""Workflow 模型 session scope 的稳定命名规则。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


WORKFLOW_PREVIEW_MODEL_SESSION_SCOPE_PREFIX = "preview:"
WORKFLOW_RUNTIME_MODEL_SESSION_SCOPE_PREFIX = "runtime:"


def build_workflow_preview_model_session_scope_id(
    *,
    project_id: str,
    application_id: str,
) -> str:
    """按 Project 和 Workflow App 构造稳定的编辑态 Preview scope。"""

    normalized_project_id = _require_scope_part(project_id, field_name="project_id")
    normalized_application_id = _require_scope_part(
        application_id,
        field_name="application_id",
    )
    return (
        f"{WORKFLOW_PREVIEW_MODEL_SESSION_SCOPE_PREFIX}"
        f"{normalized_project_id}:{normalized_application_id}"
    )


def is_workflow_preview_model_session_scope(scope_id: str) -> bool:
    """判断 scope 是否属于 API 进程内的编辑态 Preview。"""

    return str(scope_id).strip().startswith(
        WORKFLOW_PREVIEW_MODEL_SESSION_SCOPE_PREFIX
    )


def _require_scope_part(value: object, *, field_name: str) -> str:
    """校验 scope 组成字段，避免空值或分隔符造成 scope 冲突。"""

    normalized_value = str(value or "").strip()
    if not normalized_value:
        raise InvalidRequestError(
            f"构造 Workflow model session scope 时 {field_name} 不能为空"
        )
    if ":" in normalized_value:
        raise InvalidRequestError(
            f"构造 Workflow model session scope 时 {field_name} 不能包含冒号",
            details={field_name: normalized_value},
        )
    return normalized_value


__all__ = [
    "WORKFLOW_PREVIEW_MODEL_SESSION_SCOPE_PREFIX",
    "WORKFLOW_RUNTIME_MODEL_SESSION_SCOPE_PREFIX",
    "build_workflow_preview_model_session_scope_id",
    "is_workflow_preview_model_session_scope",
]

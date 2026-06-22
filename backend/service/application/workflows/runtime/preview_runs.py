"""Workflow preview run 请求与过滤工具。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.contracts.workflows.resource_semantics import (
    WORKFLOW_PREVIEW_RUN_DEFAULT_RETENTION_HOURS,
    WORKFLOW_PREVIEW_RUN_STATES,
    WORKFLOW_PREVIEW_RUN_TERMINAL_STATES,
    WorkflowPreviewRunState,
)
from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.workflows.workflow_runtime_records import WorkflowPreviewRun


@dataclass(frozen=True)
class WorkflowPreviewRunCreateRequest:
    """描述一次 preview run 创建请求。"""

    project_id: str
    application_ref_id: str | None = None
    execution_policy_id: str | None = None
    application: FlowApplication | None = None
    template: WorkflowGraphTemplate | None = None
    input_bindings: dict[str, object] | None = None
    execution_metadata: dict[str, object] | None = None
    timeout_seconds: int | None = None
    wait_mode: str = "sync"


def normalize_preview_run_create_request(
    request: WorkflowPreviewRunCreateRequest,
) -> WorkflowPreviewRunCreateRequest:
    """规范化 preview run 创建请求。"""

    project_id = request.project_id.strip()
    if not project_id:
        raise InvalidRequestError("project_id 不能为空")
    if request.timeout_seconds is not None and request.timeout_seconds <= 0:
        raise InvalidRequestError("timeout_seconds 必须大于 0")
    wait_mode = request.wait_mode.strip().lower()
    if wait_mode not in {"sync", "async"}:
        raise InvalidRequestError(
            "wait_mode 只支持 sync 或 async",
            details={"wait_mode": request.wait_mode},
        )
    return WorkflowPreviewRunCreateRequest(
        project_id=project_id,
        application_ref_id=_normalize_optional_str(request.application_ref_id),
        execution_policy_id=_normalize_optional_str(request.execution_policy_id),
        application=request.application,
        template=request.template,
        input_bindings=dict(request.input_bindings or {}),
        execution_metadata=dict(request.execution_metadata or {}),
        timeout_seconds=request.timeout_seconds,
        wait_mode=wait_mode,
    )


def filter_preview_runs(
    preview_runs: tuple[WorkflowPreviewRun, ...],
    *,
    state: WorkflowPreviewRunState | str | None,
    created_from: str | None,
    created_to: str | None,
) -> tuple[WorkflowPreviewRun, ...]:
    """按状态和创建时间过滤 preview run 列表。"""

    normalized_state = _normalize_optional_str(str(state) if state is not None else None)
    if normalized_state is not None and normalized_state not in WORKFLOW_PREVIEW_RUN_STATES:
        raise InvalidRequestError(
            "preview run state 过滤条件无效",
            details={"state": normalized_state},
        )
    created_from_at = _parse_optional_iso_datetime_text(created_from, field_name="created_from")
    created_to_at = _parse_optional_iso_datetime_text(created_to, field_name="created_to")
    if created_from_at is not None and created_to_at is not None and created_from_at > created_to_at:
        raise InvalidRequestError(
            "created_from 不能大于 created_to",
            details={"created_from": created_from, "created_to": created_to},
        )

    filtered_preview_runs: list[WorkflowPreviewRun] = []
    for preview_run in preview_runs:
        if normalized_state is not None and preview_run.state != normalized_state:
            continue
        preview_created_at = _parse_required_iso_datetime_text(
            preview_run.created_at,
            field_name="preview_run.created_at",
        )
        if created_from_at is not None and preview_created_at < created_from_at:
            continue
        if created_to_at is not None and preview_created_at > created_to_at:
            continue
        filtered_preview_runs.append(preview_run)
    return tuple(filtered_preview_runs)


def build_preview_run_retention_until() -> str:
    """返回 preview run 默认保留截止时间。"""

    return (
        datetime.now(timezone.utc)
        + timedelta(hours=WORKFLOW_PREVIEW_RUN_DEFAULT_RETENTION_HOURS)
    ).isoformat().replace("+00:00", "Z")


def preview_run_needs_cancel_before_delete(preview_run: WorkflowPreviewRun) -> bool:
    """判断删除 preview run 前是否需要先取消执行。"""

    return preview_run.state not in WORKFLOW_PREVIEW_RUN_TERMINAL_STATES


def _normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _parse_optional_iso_datetime_text(value: str | None, *, field_name: str) -> datetime | None:
    """把可选 ISO8601 文本解析为 UTC datetime。"""

    normalized_value = _normalize_optional_str(value)
    if normalized_value is None:
        return None
    return _parse_required_iso_datetime_text(normalized_value, field_name=field_name)


def _parse_required_iso_datetime_text(value: str, *, field_name: str) -> datetime:
    """把 ISO8601 文本解析为带时区的 UTC datetime。"""

    try:
        parsed_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidRequestError(
            f"{field_name} 不是有效的 ISO8601 时间",
            details={field_name: value},
        ) from exc
    if parsed_value.tzinfo is None:
        parsed_value = parsed_value.replace(tzinfo=timezone.utc)
    return parsed_value.astimezone(timezone.utc)

"""Workflow app runtime 请求与状态工具。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.worker.health import WorkflowRuntimeWorkerState
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime


@dataclass(frozen=True)
class WorkflowAppRuntimeCreateRequest:
    """描述一次 app runtime 创建请求。"""

    project_id: str
    application_id: str
    execution_policy_id: str | None = None
    display_name: str = ""
    request_timeout_seconds: int | None = None
    heartbeat_interval_seconds: int | None = None
    heartbeat_timeout_seconds: int | None = None
    metadata: dict[str, object] | None = None


def normalize_app_runtime_create_request(
    request: WorkflowAppRuntimeCreateRequest,
) -> WorkflowAppRuntimeCreateRequest:
    """规范化 app runtime 创建请求。"""

    project_id = request.project_id.strip()
    application_id = request.application_id.strip()
    if not project_id:
        raise InvalidRequestError("project_id 不能为空")
    if not application_id:
        raise InvalidRequestError("application_id 不能为空")
    if request.request_timeout_seconds is not None and request.request_timeout_seconds <= 0:
        raise InvalidRequestError("request_timeout_seconds 必须大于 0")
    heartbeat_interval_seconds = request.heartbeat_interval_seconds
    heartbeat_timeout_seconds = request.heartbeat_timeout_seconds
    if heartbeat_interval_seconds is not None and heartbeat_interval_seconds <= 0:
        raise InvalidRequestError("heartbeat_interval_seconds 必须大于 0")
    if heartbeat_timeout_seconds is not None and heartbeat_timeout_seconds <= 0:
        raise InvalidRequestError("heartbeat_timeout_seconds 必须大于 0")
    resolved_heartbeat_interval_seconds = heartbeat_interval_seconds or 5
    resolved_heartbeat_timeout_seconds = heartbeat_timeout_seconds or max(
        resolved_heartbeat_interval_seconds * 3,
        15,
    )
    if resolved_heartbeat_timeout_seconds <= resolved_heartbeat_interval_seconds:
        raise InvalidRequestError(
            "heartbeat_timeout_seconds 必须大于 heartbeat_interval_seconds",
            details={
                "heartbeat_interval_seconds": resolved_heartbeat_interval_seconds,
                "heartbeat_timeout_seconds": resolved_heartbeat_timeout_seconds,
            },
        )
    return WorkflowAppRuntimeCreateRequest(
        project_id=project_id,
        application_id=application_id,
        execution_policy_id=_normalize_optional_str(request.execution_policy_id),
        display_name=request.display_name.strip(),
        request_timeout_seconds=request.request_timeout_seconds,
        heartbeat_interval_seconds=resolved_heartbeat_interval_seconds,
        heartbeat_timeout_seconds=resolved_heartbeat_timeout_seconds,
        metadata=dict(request.metadata or {}),
    )


def with_runtime_resource_updated_by(
    metadata: dict[str, object],
    updated_by: str | None,
) -> dict[str, object]:
    """把 runtime 资源最近修改主体写入 metadata。"""

    payload = dict(metadata)
    normalized_updated_by = _normalize_optional_str(updated_by)
    if normalized_updated_by is not None:
        payload["updated_by"] = normalized_updated_by
    return payload


def apply_worker_state(
    workflow_app_runtime: WorkflowAppRuntime,
    runtime_state: WorkflowRuntimeWorkerState,
) -> WorkflowAppRuntime:
    """把 worker 返回状态回写到 WorkflowAppRuntime。"""

    return replace(
        workflow_app_runtime,
        observed_state=runtime_state.observed_state,
        worker_process_id=runtime_state.process_id,
        heartbeat_at=runtime_state.heartbeat_at,
        loaded_snapshot_fingerprint=runtime_state.loaded_snapshot_fingerprint,
        last_error=runtime_state.last_error,
        health_summary=dict(runtime_state.health_summary),
    )


def _normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None

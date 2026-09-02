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
    application_id: str | None = None
    workflow_app_version_id: str | None = None
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
    application_id = _normalize_optional_str(request.application_id)
    workflow_app_version_id = _normalize_optional_str(request.workflow_app_version_id)
    if not project_id:
        raise InvalidRequestError("project_id 不能为空")
    if (application_id is None) == (workflow_app_version_id is None):
        raise InvalidRequestError(
            "application_id 与 workflow_app_version_id 必须且只能提供一个"
        )
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
        workflow_app_version_id=workflow_app_version_id,
        execution_policy_id=_normalize_optional_str(request.execution_policy_id),
        display_name=request.display_name.strip(),
        request_timeout_seconds=request.request_timeout_seconds,
        heartbeat_interval_seconds=resolved_heartbeat_interval_seconds,
        heartbeat_timeout_seconds=resolved_heartbeat_timeout_seconds,
        metadata=dict(request.metadata or {}),
    )


@dataclass(frozen=True)
class WorkflowAppRuntimeSelectVersionRequest:
    """描述 Runtime 停机选择版本请求。"""

    workflow_app_version_id: str
    expected_generation: int
    allow_breaking_contract: bool = False
    breaking_change_reason: str | None = None


def normalize_select_version_request(
    request: WorkflowAppRuntimeSelectVersionRequest,
) -> WorkflowAppRuntimeSelectVersionRequest:
    """规范化 Runtime 选版请求。"""

    workflow_app_version_id = request.workflow_app_version_id.strip()
    if not workflow_app_version_id:
        raise InvalidRequestError("workflow_app_version_id 不能为空")
    if request.expected_generation < 0:
        raise InvalidRequestError("expected_generation 不能小于 0")
    reason = _normalize_optional_str(request.breaking_change_reason)
    if request.allow_breaking_contract and reason is None:
        raise InvalidRequestError("允许破坏性契约更新时必须填写原因")
    return WorkflowAppRuntimeSelectVersionRequest(
        workflow_app_version_id=workflow_app_version_id,
        expected_generation=request.expected_generation,
        allow_breaking_contract=request.allow_breaking_contract,
        breaking_change_reason=reason,
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
        worker_instance_id=runtime_state.instance_id,
        worker_process_id=runtime_state.process_id,
        heartbeat_at=runtime_state.heartbeat_at,
        loaded_snapshot_fingerprint=runtime_state.loaded_snapshot_fingerprint,
        last_error=runtime_state.last_error,
        health_summary=dict(runtime_state.health_summary),
    )


def apply_observed_worker_health(
    workflow_app_runtime: WorkflowAppRuntime,
    runtime_state: WorkflowRuntimeWorkerState,
) -> WorkflowAppRuntime:
    """合并现场 worker 健康状态，并保留无进程启动失败的诊断信息。

    worker manager 在没有活动进程时只能观测到 ``stopped``。如果 Runtime
    最近一次启动已经以 ``failed`` 落库，直接使用该现场状态会遮蔽失败原因，
    也会让控制面误以为 Runtime 已完成正常停止。此时保留持久化失败状态；
    显式 Stop 仍会通过正常状态迁移把记录更新为 ``stopped``。
    """

    if (
        workflow_app_runtime.observed_state == "failed"
        and runtime_state.observed_state == "stopped"
        and runtime_state.current_run_id is None
    ):
        runtime_state = replace(
            runtime_state,
            observed_state="failed",
            last_error=workflow_app_runtime.last_error,
        )
    return apply_worker_state(workflow_app_runtime, runtime_state)


def _normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None

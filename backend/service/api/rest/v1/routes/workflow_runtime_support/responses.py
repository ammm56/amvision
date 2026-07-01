"""workflow runtime 路由响应构建。"""

from __future__ import annotations

from backend.contracts.workflows import (
    WorkflowAppRuntimeEventContract,
    WorkflowAppRuntimeInstanceContract,
    WorkflowAppRuntimeContract,
    WorkflowExecutionPolicyContract,
    WorkflowPreviewRunEventContract,
    WorkflowPreviewRunContract,
    WorkflowPreviewRunSummaryContract,
    WorkflowRunContract,
    WorkflowRunEventContract,
)
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowAppRuntimeEvent,
    WorkflowExecutionPolicy,
    WorkflowPreviewRun,
    WorkflowPreviewRunEvent,
    WorkflowRun,
    WorkflowRunEvent,
)


def build_preview_run_contract(preview_run: WorkflowPreviewRun) -> WorkflowPreviewRunContract:
    """把 WorkflowPreviewRun 领域对象转换为公开规则。"""

    return WorkflowPreviewRunContract(
        preview_run_id=preview_run.preview_run_id,
        project_id=preview_run.project_id,
        application_id=preview_run.application_id,
        source_kind=preview_run.source_kind,
        application_snapshot_object_key=preview_run.application_snapshot_object_key,
        template_snapshot_object_key=preview_run.template_snapshot_object_key,
        state=preview_run.state,
        created_at=preview_run.created_at,
        started_at=preview_run.started_at,
        finished_at=preview_run.finished_at,
        created_by=preview_run.created_by,
        timeout_seconds=preview_run.timeout_seconds,
        outputs=dict(preview_run.outputs),
        template_outputs=dict(preview_run.template_outputs),
        node_records=[dict(item) for item in preview_run.node_records],
        error_message=preview_run.error_message,
        retention_until=preview_run.retention_until,
        metadata=dict(preview_run.metadata),
    )


def build_preview_run_summary_contract(
    preview_run: WorkflowPreviewRun,
) -> WorkflowPreviewRunSummaryContract:
    """把 WorkflowPreviewRun 领域对象转换为摘要规则。"""

    return WorkflowPreviewRunSummaryContract(
        preview_run_id=preview_run.preview_run_id,
        project_id=preview_run.project_id,
        application_id=preview_run.application_id,
        source_kind=preview_run.source_kind,
        state=preview_run.state,
        created_at=preview_run.created_at,
        started_at=preview_run.started_at,
        finished_at=preview_run.finished_at,
        created_by=preview_run.created_by,
        timeout_seconds=preview_run.timeout_seconds,
        error_message=preview_run.error_message,
        retention_until=preview_run.retention_until,
    )


def build_preview_run_event_contract(
    preview_run_event: WorkflowPreviewRunEvent,
) -> WorkflowPreviewRunEventContract:
    """把 preview run 事件转换为公开规则。"""

    return WorkflowPreviewRunEventContract(
        preview_run_id=preview_run_event.preview_run_id,
        sequence=preview_run_event.sequence,
        event_type=preview_run_event.event_type,
        created_at=preview_run_event.created_at,
        message=preview_run_event.message,
        payload=dict(preview_run_event.payload),
    )


def build_workflow_app_runtime_contract(
    workflow_app_runtime: WorkflowAppRuntime,
    *,
    workflow_service: LocalWorkflowJsonService | None = None,
) -> WorkflowAppRuntimeContract:
    """把 WorkflowAppRuntime 领域对象转换为公开规则。"""

    application_summary = None
    template_summary = None
    if workflow_service is not None:
        application_summary = try_build_application_reference_summary_contract(
            workflow_service=workflow_service,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
        )
        if application_summary is not None:
            template_summary = try_build_template_reference_summary_contract(
                workflow_service=workflow_service,
                project_id=application_summary["project_id"],
                template_id=application_summary["template_id"],
                template_version=application_summary["template_version"],
            )

    return WorkflowAppRuntimeContract(
        workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
        project_id=workflow_app_runtime.project_id,
        application_id=workflow_app_runtime.application_id,
        display_name=workflow_app_runtime.display_name,
        application_snapshot_object_key=workflow_app_runtime.application_snapshot_object_key,
        template_snapshot_object_key=workflow_app_runtime.template_snapshot_object_key,
        execution_policy_snapshot_object_key=workflow_app_runtime.execution_policy_snapshot_object_key,
        desired_state=workflow_app_runtime.desired_state,
        observed_state=workflow_app_runtime.observed_state,
        request_timeout_seconds=workflow_app_runtime.request_timeout_seconds,
        heartbeat_interval_seconds=workflow_app_runtime.heartbeat_interval_seconds,
        heartbeat_timeout_seconds=workflow_app_runtime.heartbeat_timeout_seconds,
        created_at=workflow_app_runtime.created_at,
        updated_at=workflow_app_runtime.updated_at,
        created_by=workflow_app_runtime.created_by,
        updated_by=read_resource_updated_by(workflow_app_runtime.metadata),
        application_summary=application_summary,
        template_summary=template_summary,
        last_started_at=workflow_app_runtime.last_started_at,
        last_stopped_at=workflow_app_runtime.last_stopped_at,
        heartbeat_at=workflow_app_runtime.heartbeat_at,
        worker_process_id=workflow_app_runtime.worker_process_id,
        loaded_snapshot_fingerprint=workflow_app_runtime.loaded_snapshot_fingerprint,
        last_error=workflow_app_runtime.last_error,
        health_summary=dict(workflow_app_runtime.health_summary),
        metadata=dict(workflow_app_runtime.metadata),
    )


def build_workflow_app_runtime_event_contract(
    workflow_app_runtime_event: WorkflowAppRuntimeEvent,
) -> WorkflowAppRuntimeEventContract:
    """把 app runtime 事件转换为公开规则。"""

    return WorkflowAppRuntimeEventContract(
        workflow_runtime_id=workflow_app_runtime_event.workflow_runtime_id,
        sequence=workflow_app_runtime_event.sequence,
        event_type=workflow_app_runtime_event.event_type,
        created_at=workflow_app_runtime_event.created_at,
        message=workflow_app_runtime_event.message,
        payload=dict(workflow_app_runtime_event.payload),
    )


def try_build_application_reference_summary_contract(
    *,
    workflow_service: LocalWorkflowJsonService,
    project_id: str,
    application_id: str,
) -> dict[str, object] | None:
    """按需读取 application 一跳摘要，不存在时返回 None。"""

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


def try_build_template_reference_summary_contract(
    *,
    workflow_service: LocalWorkflowJsonService,
    project_id: str,
    template_id: str,
    template_version: str,
) -> dict[str, object] | None:
    """按需读取 template 一跳摘要，不存在时返回 None。"""

    try:
        summary = workflow_service.get_template_version_summary(
            project_id=project_id,
            template_id=template_id,
            template_version=template_version,
        )
    except ResourceNotFoundError:
        return None
    return {
        "project_id": summary.project_id,
        "template_id": summary.template_id,
        "template_version": summary.template_version,
        "display_name": summary.display_name,
        "description": summary.description,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "created_by": summary.created_by,
        "updated_by": summary.updated_by,
    }


def read_resource_updated_by(metadata: dict[str, object]) -> str | None:
    """从资源 metadata 中读取最近修改主体。"""

    updated_by = metadata.get("updated_by")
    if not isinstance(updated_by, str):
        return None
    normalized_updated_by = updated_by.strip()
    return normalized_updated_by or None


def build_execution_policy_contract(execution_policy: WorkflowExecutionPolicy) -> WorkflowExecutionPolicyContract:
    """把 WorkflowExecutionPolicy 领域对象转换为公开规则。"""

    return WorkflowExecutionPolicyContract(
        execution_policy_id=execution_policy.execution_policy_id,
        project_id=execution_policy.project_id,
        display_name=execution_policy.display_name,
        policy_kind=execution_policy.policy_kind,
        default_timeout_seconds=execution_policy.default_timeout_seconds,
        max_run_timeout_seconds=execution_policy.max_run_timeout_seconds,
        trace_level=execution_policy.trace_level,
        retain_node_records_enabled=execution_policy.retain_node_records_enabled,
        retain_trace_enabled=execution_policy.retain_trace_enabled,
        created_at=execution_policy.created_at,
        updated_at=execution_policy.updated_at,
        created_by=execution_policy.created_by,
        metadata=dict(execution_policy.metadata),
    )


def build_workflow_run_contract(
    workflow_run: WorkflowRun,
    *,
    outputs: dict[str, object] | None = None,
    template_outputs: dict[str, object] | None = None,
    node_records: tuple[dict[str, object], ...] | list[dict[str, object]] | None = None,
) -> WorkflowRunContract:
    """把 WorkflowRun 领域对象转换为公开规则。"""

    return WorkflowRunContract(
        workflow_run_id=workflow_run.workflow_run_id,
        workflow_runtime_id=workflow_run.workflow_runtime_id,
        project_id=workflow_run.project_id,
        application_id=workflow_run.application_id,
        state=workflow_run.state,
        created_at=workflow_run.created_at,
        started_at=workflow_run.started_at,
        finished_at=workflow_run.finished_at,
        created_by=workflow_run.created_by,
        requested_timeout_seconds=workflow_run.requested_timeout_seconds,
        assigned_process_id=workflow_run.assigned_process_id,
        input_payload=dict(workflow_run.input_payload),
        outputs=dict(outputs) if outputs is not None else dict(workflow_run.outputs),
        template_outputs=(
            dict(template_outputs)
            if template_outputs is not None
            else dict(workflow_run.template_outputs)
        ),
        node_records=[dict(item) for item in (node_records if node_records is not None else workflow_run.node_records)],
        error_message=workflow_run.error_message,
        metadata=dict(workflow_run.metadata),
    )


def build_workflow_app_invoke_result_payload(
    workflow_run: WorkflowRun,
    *,
    outputs: dict[str, object],
) -> object:
    """构建 Workflow App 对外同步调用结果。

    App invoke 是外部系统调用面，默认只返回公开 App Result；WorkflowRun、
    template_outputs 和 node_records 属于平台调试/追踪信息，需要显式请求。
    """

    if workflow_run.state != "succeeded":
        payload: dict[str, object] = {
            "workflow_run_id": workflow_run.workflow_run_id,
            "state": workflow_run.state,
            "error_message": workflow_run.error_message,
        }
        error_details = dict(workflow_run.metadata).get("error_details")
        if error_details is not None:
            payload["error_details"] = error_details
        return payload

    if len(outputs) == 1:
        return next(iter(outputs.values()))
    return dict(outputs)


def build_workflow_run_event_contract(workflow_run_event: WorkflowRunEvent) -> WorkflowRunEventContract:
    """把 WorkflowRun 事件转换为公开规则。"""

    return WorkflowRunEventContract(
        workflow_run_id=workflow_run_event.workflow_run_id,
        workflow_runtime_id=workflow_run_event.workflow_runtime_id,
        sequence=workflow_run_event.sequence,
        event_type=workflow_run_event.event_type,
        created_at=workflow_run_event.created_at,
        message=workflow_run_event.message,
        payload=dict(workflow_run_event.payload),
    )


def build_workflow_app_runtime_instance_contract(
    runtime_instance: object,
) -> WorkflowAppRuntimeInstanceContract:
    """把 runtime instance 摘要转换为公开规则。"""

    return WorkflowAppRuntimeInstanceContract(
        instance_id=str(getattr(runtime_instance, "instance_id", "")),
        workflow_runtime_id=str(getattr(runtime_instance, "workflow_runtime_id", "")),
        state=str(getattr(runtime_instance, "state", "")),
        process_id=getattr(runtime_instance, "process_id", None),
        current_run_id=getattr(runtime_instance, "current_run_id", None),
        started_at=getattr(runtime_instance, "started_at", None),
        heartbeat_at=getattr(runtime_instance, "heartbeat_at", None),
        loaded_snapshot_fingerprint=getattr(runtime_instance, "loaded_snapshot_fingerprint", None),
        last_error=getattr(runtime_instance, "last_error", None),
        health_summary=dict(getattr(runtime_instance, "health_summary", {}) or {}),
    )

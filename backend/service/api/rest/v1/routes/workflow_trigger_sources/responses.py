"""WorkflowTriggerSource REST 响应构造。"""

from __future__ import annotations

from fastapi import Request

from backend.contracts.workflows import WorkflowTriggerSourceContract
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.api.rest.v1.routes.workflow_trigger_sources.references import (
    read_resource_updated_by,
    try_build_application_reference_summary,
    try_build_runtime_reference_summary,
)


def build_trigger_source_contract(
    trigger_source: WorkflowTriggerSource,
    *,
    request: Request,
) -> WorkflowTriggerSourceContract:
    """把领域对象转换为 REST 规则。"""

    runtime_summary = try_build_runtime_reference_summary(
        request=request,
        workflow_runtime_id=trigger_source.workflow_runtime_id,
    )
    application_summary = None
    if runtime_summary is not None:
        application_summary = try_build_application_reference_summary(
            request=request,
            project_id=runtime_summary["project_id"],
            application_id=runtime_summary["application_id"],
        )

    return WorkflowTriggerSourceContract(
        trigger_source_id=trigger_source.trigger_source_id,
        project_id=trigger_source.project_id,
        display_name=trigger_source.display_name,
        trigger_kind=trigger_source.trigger_kind,
        workflow_runtime_id=trigger_source.workflow_runtime_id,
        submit_mode=trigger_source.submit_mode,
        enabled=trigger_source.enabled,
        desired_state=trigger_source.desired_state,
        observed_state=trigger_source.observed_state,
        transport_config=dict(trigger_source.transport_config),
        match_rule=dict(trigger_source.match_rule),
        input_binding_mapping=dict(trigger_source.input_binding_mapping),
        result_mapping=dict(trigger_source.result_mapping)
        or {"result_binding": "workflow_result"},
        default_execution_metadata=dict(trigger_source.default_execution_metadata),
        ack_policy=trigger_source.ack_policy,
        result_mode=trigger_source.result_mode,
        reply_timeout_seconds=trigger_source.reply_timeout_seconds,
        debounce_window_ms=trigger_source.debounce_window_ms,
        idempotency_key_path=trigger_source.idempotency_key_path,
        last_triggered_at=trigger_source.last_triggered_at,
        last_error=trigger_source.last_error,
        health_summary=dict(trigger_source.health_summary),
        metadata=dict(trigger_source.metadata),
        created_at=trigger_source.created_at,
        updated_at=trigger_source.updated_at,
        created_by=trigger_source.created_by,
        updated_by=read_resource_updated_by(trigger_source.metadata),
        runtime_summary=runtime_summary,
        application_summary=application_summary,
    )


"""TriggerSource 结果回执构造器。"""

from __future__ import annotations

from backend.contracts.workflows import TriggerEventContract, TriggerResultContract
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    PreparedTriggerResult,
    build_public_prepared_result_payload,
)


class WorkflowResultDispatcher:
    """把 WorkflowRun 转换为协议中立 TriggerResultContract。"""

    def build_result(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        trigger_event: TriggerEventContract,
        workflow_run: WorkflowRun,
        response_outputs: dict[str, object] | None = None,
        prepared_trigger_result: dict[str, object] | None = None,
    ) -> TriggerResultContract:
        """构造一次触发调用的结果回执。

        参数：
        - trigger_source：触发源配置。
        - trigger_event：标准化后的触发事件。
        - workflow_run：WorkflowRuntime 返回的运行记录。
        - response_outputs：可选的未脱敏同步 outputs；仅用于协议直返。

        返回：
        - TriggerResultContract：协议中立结果回执。
        """

        metadata: dict[str, object] = {
            "workflow_runtime_id": workflow_run.workflow_runtime_id,
            "workflow_state": workflow_run.state,
            "ack_policy": trigger_source.ack_policy,
            "result_mode": trigger_source.result_mode,
        }
        if workflow_run.state != "succeeded":
            raw_error_details = workflow_run.metadata.get("error_details")
            if isinstance(raw_error_details, dict):
                error_details = dict(raw_error_details)
                metadata["error_details"] = error_details
                error_code = error_details.get("error_code")
                if isinstance(error_code, str) and error_code.strip():
                    metadata["error_code"] = error_code.strip()
            elif workflow_run.state == "timed_out":
                metadata["error_code"] = "operation_timeout"

        return TriggerResultContract(
            trigger_source_id=trigger_source.trigger_source_id,
            event_id=trigger_event.event_id,
            state=_map_run_state(workflow_run.state),
            workflow_run_id=workflow_run.workflow_run_id,
            response_payload=self._build_response_payload(
                trigger_source=trigger_source,
                workflow_run=workflow_run,
                response_outputs=response_outputs,
                prepared_trigger_result=prepared_trigger_result,
            ),
            error_message=workflow_run.error_message,
            metadata=metadata,
        )

    def _build_response_payload(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        workflow_run: WorkflowRun,
        response_outputs: dict[str, object] | None,
        prepared_trigger_result: dict[str, object] | None,
    ) -> dict[str, object]:
        """按 result_mapping 构造响应 payload。"""

        if trigger_source.result_mode == "event-only":
            return {}
        if trigger_source.result_mode == "accepted-then-query":
            return {
                "workflow_run_id": workflow_run.workflow_run_id,
                "workflow_state": workflow_run.state,
            }
        result_mapping = dict(trigger_source.result_mapping)
        raw_result_bindings = result_mapping.get("result_bindings")
        result_bindings = tuple(
            binding_id.strip()
            for binding_id in (
                raw_result_bindings
                if isinstance(raw_result_bindings, list | tuple)
                else ()
            )
            if isinstance(binding_id, str) and binding_id.strip()
        )
        effective_outputs = (
            dict(response_outputs)
            if isinstance(response_outputs, dict) and response_outputs
            else dict(workflow_run.outputs)
        )
        response_payload: dict[str, object] = {
            "workflow_run_id": workflow_run.workflow_run_id,
            "workflow_state": workflow_run.state,
        }
        # 失败、取消和超时没有成功态输出契约。此处必须保留 WorkflowRun 的
        # 原始终态与 error_message，不能再用“结果 binding 不存在”覆盖根因。
        if workflow_run.state != "succeeded":
            return response_payload
        missing_bindings = [
            binding_id
            for binding_id in result_bindings
            if binding_id not in effective_outputs
        ]
        if missing_bindings:
            from backend.service.application.errors import InvalidRequestError

            raise InvalidRequestError(
                "Workflow Trigger 选择的结果 binding 不存在",
                details={"missing_output_binding_ids": missing_bindings},
            )
        response_payload["results"] = {
            binding_id: effective_outputs[binding_id]
            for binding_id in result_bindings
        }
        if prepared_trigger_result is not None:
            prepared = PreparedTriggerResult.model_validate(prepared_trigger_result)
            response_payload.update(build_public_prepared_result_payload(prepared))
            return response_payload
        return response_payload


def _map_run_state(workflow_run_state: str) -> str:
    """把 WorkflowRun 状态映射为 TriggerResult 状态。"""

    if workflow_run_state == "succeeded":
        return "succeeded"
    if workflow_run_state == "timed_out":
        return "timed_out"
    if workflow_run_state in {"failed", "cancelled"}:
        return "failed"
    return "accepted"

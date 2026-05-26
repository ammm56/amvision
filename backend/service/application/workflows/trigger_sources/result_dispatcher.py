"""TriggerSource 结果回执构造器。"""

from __future__ import annotations

from backend.contracts.workflows import TriggerEventContract, TriggerResultContract
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
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

        return TriggerResultContract(
            trigger_source_id=trigger_source.trigger_source_id,
            event_id=trigger_event.event_id,
            state=_map_run_state(workflow_run.state),
            workflow_run_id=workflow_run.workflow_run_id,
            response_payload=self._build_response_payload(
                trigger_source=trigger_source,
                workflow_run=workflow_run,
                response_outputs=response_outputs,
            ),
            error_message=workflow_run.error_message,
            metadata={
                "workflow_runtime_id": workflow_run.workflow_runtime_id,
                "workflow_state": workflow_run.state,
            },
        )

    def _build_response_payload(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        workflow_run: WorkflowRun,
        response_outputs: dict[str, object] | None,
    ) -> dict[str, object]:
        """按 result_mapping 构造响应 payload。"""

        result_mapping = dict(trigger_source.result_mapping)
        result_binding = result_mapping.get("result_binding", "workflow_result")
        effective_outputs = (
            dict(response_outputs)
            if isinstance(response_outputs, dict) and response_outputs
            else dict(workflow_run.outputs)
        )
        response_payload: dict[str, object] = {
            "workflow_run_id": workflow_run.workflow_run_id,
            "workflow_state": workflow_run.state,
        }
        if isinstance(result_binding, str) and result_binding in effective_outputs:
            response_payload["result_binding"] = result_binding
            response_payload["result"] = effective_outputs[result_binding]
            return response_payload
        response_payload["outputs"] = effective_outputs
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

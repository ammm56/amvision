"""TriggerSource 到 WorkflowRuntime 的提交器。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.contracts.workflows import TriggerEventContract, TriggerResultContract
from backend.service.application.errors import ServiceError
from backend.service.application.workflows.runtime_service import (
    WorkflowRuntimeInvokeRequest,
    WorkflowRuntimeService,
)
from backend.service.application.workflows.trigger_sources.input_binding_mapper import (
    InputBindingMapper,
)
from backend.service.application.workflows.trigger_sources.result_dispatcher import (
    WorkflowResultDispatcher,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


@dataclass(frozen=True)
class WorkflowTriggerSubmitRequest:
    """描述一次 TriggerSource 提交请求。

    字段：
    - trigger_source：触发源配置。
    - trigger_event：标准化后的触发事件。
    - created_by：创建主体 id。
    """

    trigger_source: WorkflowTriggerSource
    trigger_event: TriggerEventContract
    created_by: str | None = None


class WorkflowSubmitter:
    """把标准化触发事件提交到 WorkflowRuntime。"""

    def __init__(
        self,
        *,
        runtime_service: WorkflowRuntimeService,
        input_binding_mapper: InputBindingMapper | None = None,
        result_dispatcher: WorkflowResultDispatcher | None = None,
    ) -> None:
        """初始化 WorkflowSubmitter。

        参数：
        - runtime_service：WorkflowRuntime 控制面服务。
        - input_binding_mapper：input binding 映射器。
        - result_dispatcher：结果回执构造器。
        """

        self.runtime_service = runtime_service
        self.input_binding_mapper = input_binding_mapper or InputBindingMapper()
        self.result_dispatcher = result_dispatcher or WorkflowResultDispatcher()

    def submit_event(
        self, request: WorkflowTriggerSubmitRequest
    ) -> TriggerResultContract:
        """提交一次标准化触发事件。

        参数：
        - request：TriggerSource 提交请求。

        返回：
        - TriggerResultContract：协议中立结果回执。
        """

        input_bindings = self.input_binding_mapper.map_input_bindings(
            trigger_source=request.trigger_source,
            trigger_event=request.trigger_event,
        )
        execution_request = WorkflowRuntimeInvokeRequest(
            input_bindings=input_bindings,
            execution_metadata=_build_execution_metadata(request),
            timeout_seconds=request.trigger_source.reply_timeout_seconds,
        )
        response_outputs: dict[str, object] | None = None
        try:
            if request.trigger_source.submit_mode == "sync":
                invoke_result = self.runtime_service.invoke_workflow_app_runtime_with_response(
                    request.trigger_source.workflow_runtime_id,
                    execution_request,
                    created_by=request.created_by,
                )
                workflow_run = invoke_result.workflow_run
                response_outputs = dict(invoke_result.raw_outputs)
            else:
                workflow_run = self.runtime_service.create_workflow_run(
                    request.trigger_source.workflow_runtime_id,
                    execution_request,
                    created_by=request.created_by,
                )
        except ServiceError as error:
            return TriggerResultContract(
                trigger_source_id=request.trigger_source.trigger_source_id,
                event_id=request.trigger_event.event_id,
                state="failed",
                error_message=error.message,
                metadata={
                    "error_code": error.code,
                    "error_details": dict(error.details),
                },
            )
        return self.result_dispatcher.build_result(
            trigger_source=request.trigger_source,
            trigger_event=request.trigger_event,
            workflow_run=workflow_run,
            response_outputs=response_outputs,
        )


def _build_execution_metadata(
    request: WorkflowTriggerSubmitRequest,
) -> dict[str, object]:
    """构造传入 WorkflowRuntime 的执行元数据。"""

    metadata = dict(request.trigger_source.default_execution_metadata)
    metadata.update(
        {
            "trigger_source_id": request.trigger_source.trigger_source_id,
            "trigger_kind": request.trigger_source.trigger_kind,
            "trigger_event_id": request.trigger_event.event_id,
        }
    )
    if request.trigger_event.trace_id is not None:
        metadata["trace_id"] = request.trigger_event.trace_id
    if request.trigger_event.idempotency_key is not None:
        metadata["idempotency_key"] = request.trigger_event.idempotency_key
    return metadata

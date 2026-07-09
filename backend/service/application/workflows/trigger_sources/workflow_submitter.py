"""TriggerSource 到 WorkflowRuntime 的提交器。"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from backend.contracts.workflows import TriggerEventContract, TriggerResultContract
from backend.service.application.errors import ServiceError
from backend.service.application.workflows.runtime.invokes import WorkflowRuntimeInvokeRequest
from backend.service.application.workflows.runtime_service import WorkflowRuntimeService
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

        submit_started_at = monotonic()
        mapping_started_at = monotonic()
        input_bindings = self.input_binding_mapper.map_input_bindings(
            trigger_source=request.trigger_source,
            trigger_event=request.trigger_event,
        )
        timings: dict[str, object] = {
            "trigger_map_input_bindings_ms": _elapsed_ms(mapping_started_at),
        }
        execution_request = WorkflowRuntimeInvokeRequest(
            input_bindings=input_bindings,
            execution_metadata=_build_execution_metadata(request),
            timeout_seconds=request.trigger_source.reply_timeout_seconds,
        )
        response_outputs: dict[str, object] | None = None
        try:
            if request.trigger_source.submit_mode == "sync":
                runtime_submit_started_at = monotonic()
                invoke_result = self.runtime_service.invoke_workflow_app_runtime_with_response(
                    request.trigger_source.workflow_runtime_id,
                    execution_request,
                    created_by=request.created_by,
                )
                timings["trigger_runtime_submit_ms"] = _elapsed_ms(runtime_submit_started_at)
                workflow_run = invoke_result.workflow_run
                response_outputs = dict(invoke_result.raw_outputs)
            else:
                runtime_submit_started_at = monotonic()
                workflow_run = self.runtime_service.create_workflow_run(
                    request.trigger_source.workflow_runtime_id,
                    execution_request,
                    created_by=request.created_by,
                )
                timings["trigger_runtime_submit_ms"] = _elapsed_ms(runtime_submit_started_at)
        except ServiceError as error:
            return TriggerResultContract(
                trigger_source_id=request.trigger_source.trigger_source_id,
                event_id=request.trigger_event.event_id,
                state="failed",
                error_message=error.message,
                metadata={
                    "error_code": error.code,
                    "error_details": dict(error.details),
                    "timings": {**timings, "trigger_submit_total_ms": _elapsed_ms(submit_started_at)},
                },
            )
        result_dispatch_started_at = monotonic()
        result = self.result_dispatcher.build_result(
            trigger_source=request.trigger_source,
            trigger_event=request.trigger_event,
            workflow_run=workflow_run,
            response_outputs=response_outputs,
        )
        timings["trigger_result_dispatch_ms"] = _elapsed_ms(result_dispatch_started_at)
        timings["trigger_submit_total_ms"] = _elapsed_ms(submit_started_at)
        timings.update(_read_workflow_run_timings(workflow_run.metadata))
        return result.model_copy(
            update={
                "metadata": _merge_trigger_result_diagnostics(
                    result.metadata,
                    timings,
                    node_timings=_read_workflow_run_node_timings(workflow_run.metadata),
                )
            }
        )


def _build_execution_metadata(
    request: WorkflowTriggerSubmitRequest,
) -> dict[str, object]:
    """构造传入 WorkflowRuntime 的执行元数据。"""

    metadata = dict(request.trigger_source.default_execution_metadata)
    if _is_high_speed_trigger_source(request.trigger_source):
        metadata.setdefault("trace_level", "none")
        metadata.setdefault("retain_trace_enabled", False)
        metadata.setdefault("retain_node_records_enabled", False)
        metadata.setdefault("retain_input_payload_enabled", False)
        metadata.setdefault("retain_outputs_enabled", False)
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


def _is_high_speed_trigger_source(trigger_source: WorkflowTriggerSource) -> bool:
    """判断 TriggerSource 是否属于默认不保留磁盘 trace 的高速入口。

    参数：
    - trigger_source：待判断的 TriggerSource。

    返回：
    - bool：属于高速入口时返回 True。
    """

    return trigger_source.trigger_kind.startswith("zeromq")


def _merge_trigger_result_timings(
    metadata: dict[str, object],
    timing_payload: dict[str, object],
) -> dict[str, object]:
    """把 TriggerSource 提交计时合并进结果 metadata。"""

    payload = dict(metadata)
    timings = dict(payload.get("timings")) if isinstance(payload.get("timings"), dict) else {}
    for key, value in timing_payload.items():
        if isinstance(value, bool):
            timings[str(key)] = value
            continue
        if isinstance(value, int | float | str) or value is None:
            timings[str(key)] = value
    payload["timings"] = timings
    return payload


def _merge_trigger_result_diagnostics(
    metadata: dict[str, object],
    timing_payload: dict[str, object],
    *,
    node_timings: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    """把 TriggerSource 提交计时和节点耗时摘要合并进结果 metadata。"""

    payload = _merge_trigger_result_timings(metadata, timing_payload)
    if node_timings:
        payload["node_timings"] = [dict(item) for item in node_timings]
    return payload


def _read_workflow_run_timings(metadata: dict[str, object]) -> dict[str, object]:
    """读取 WorkflowRun metadata 中可向协议结果返回的计时字段。"""

    raw_timings = metadata.get("timings")
    if not isinstance(raw_timings, dict):
        return {}
    return {f"workflow_{key}" if not str(key).startswith("workflow_") else str(key): value for key, value in raw_timings.items()}


def _read_workflow_run_node_timings(metadata: dict[str, object]) -> tuple[dict[str, object], ...]:
    """读取 WorkflowRun metadata 中可向协议结果返回的节点耗时摘要。"""

    raw_items = metadata.get("node_timings")
    if not isinstance(raw_items, list):
        return ()
    node_timings: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        node_id = item.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        timing: dict[str, object] = {"node_id": node_id}
        node_type_id = item.get("node_type_id")
        runtime_kind = item.get("runtime_kind")
        duration_ms = item.get("duration_ms")
        if isinstance(node_type_id, str) and node_type_id:
            timing["node_type_id"] = node_type_id
        if isinstance(runtime_kind, str) and runtime_kind:
            timing["runtime_kind"] = runtime_kind
        if isinstance(duration_ms, bool):
            duration_ms = None
        if isinstance(duration_ms, int | float):
            timing["duration_ms"] = float(duration_ms)
        node_timings.append(timing)
    return tuple(node_timings)


def _elapsed_ms(started_at: float) -> float:
    """把 monotonic 起点转换为毫秒耗时。"""

    return round((monotonic() - started_at) * 1000.0, 3)

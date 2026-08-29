"""WorkflowTriggerSource 协议中立组件测试。"""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from time import monotonic_ns
from types import SimpleNamespace
from uuid import uuid4

import pytest
import zmq

from backend.contracts.buffers.buffer_ref import BufferRef
from backend.contracts.buffers.lease_ownership import LeaseOwnershipReceipt
from backend.contracts.workflows import (
    InputBindingMappingItemContract,
    TriggerResultContract,
)
from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
)
from backend.nodes.core_nodes.support.deployment_model import run_direct_model_inference
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.trigger_sources import (
    InputBindingMapper,
    RawTriggerEvent,
    TriggerEventNormalizer,
    WorkflowResultDispatcher,
)
from backend.service.application.workflows.runtime_service import (
    WorkflowRuntimeSyncInvokeResult,
)
from backend.service.application.workflows.trigger_sources.trigger_source_supervisor import (
    TriggerSourceSupervisor,
)
from backend.service.application.workflows.trigger_sources.protocol_adapter import (
    WorkflowTriggerDispatchResult,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    PreparedLogicalAttachment,
    PreparedPhysicalPayload,
    PreparedTriggerResult,
    TRIGGER_RESPONSE_PLAN_METADATA_KEY,
    build_trigger_response_plan,
)
from backend.service.application.workflows.trigger_sources.workflow_submitter import (
    WorkflowSubmitter,
    WorkflowTriggerSubmitRequest,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY,
)
from backend.service.application.workflows.trigger_sources.zeromq_transport import (
    ZeroMqTriggerRuntimeConfig,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.integrations.modbus import (
    ModbusBitsReadResponse,
    PlcRegisterTriggerAdapter,
)
from backend.service.infrastructure.integrations.directory import (
    DirectoryPollTriggerAdapter,
    DirectoryWatchTriggerAdapter,
)
from backend.service.infrastructure.integrations.zeromq import ZeroMqTriggerAdapter


_ZEROMQ_RUNTIME_CONFIG = ZeroMqTriggerRuntimeConfig(
    buffer_ttl_seconds=330.0,
    buffer_ttl_safety_margin_seconds=30.0,
    receive_hwm=1,
    send_hwm=1,
    max_message_size_bytes=1024 * 1024 * 1024,
    poll_timeout_ms=100,
    startup_timeout_seconds=2.0,
    shutdown_timeout_seconds=10.0,
    transport_registry_max_entries=8,
    transport_registry_max_bytes=1024 * 1024 * 1024,
    transport_tracker_timeout_seconds=2.0,
    transport_reaper_poll_interval_seconds=0.001,
)


def _build_zeromq_adapter(
    local_buffer_writer: object,
    **runtime_overrides: object,
) -> ZeroMqTriggerAdapter:
    """使用显式运行配置构造 ZeroMQ adapter。"""

    runtime_config = replace(_ZEROMQ_RUNTIME_CONFIG, **runtime_overrides)
    return ZeroMqTriggerAdapter(
        local_buffer_writer=local_buffer_writer,
        runtime_config=runtime_config,
    )


def test_trigger_event_normalizer_and_input_binding_mapper_resolve_payload_paths() -> (
    None
):
    """验证事件标准化和 input binding 映射可以读取 payload 路径。"""

    trigger_source = _build_trigger_source(submit_mode="sync")
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(
            event_id="event-1",
            trace_id="trace-1",
            occurred_at="2026-05-13T00:00:00Z",
            payload={"request": {"id": "request-1", "image": "base64-image"}},
            metadata={"transport": "http"},
        ),
    )

    input_bindings = InputBindingMapper().map_input_bindings(
        trigger_source=trigger_source,
        trigger_event=trigger_event,
    )

    assert trigger_event.idempotency_key == "request-1"
    assert input_bindings == {
        "request_image_base64": "base64-image",
        "static_mode": "inspect",
    }


def test_input_binding_mapper_rejects_missing_required_source() -> None:
    """验证必填 input binding 来源缺失时返回请求错误。"""

    trigger_source = _build_trigger_source()
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(event_id="event-1", payload={"request": {"id": "request-1"}}),
    )

    with pytest.raises(InvalidRequestError) as error_info:
        InputBindingMapper().map_input_bindings(
            trigger_source=trigger_source,
            trigger_event=trigger_event,
        )

    assert error_info.value.details["binding_id"] == "request_image_base64"


def test_input_binding_mapper_prefers_source_over_null_response_value() -> None:
    """验证 REST 展示层补出的 value=null 不会覆盖有效 source。"""

    trigger_source = _build_trigger_source(
        input_binding_mapping={
            "request_image_ref": {
                "source": "payload.request_image_ref",
                "value": None,
                "required": True,
            }
        }
    )
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(
            event_id="event-1",
            payload={"request_image_ref": {"transport_kind": "buffer"}},
        ),
    )

    assert InputBindingMapper().map_input_bindings(
        trigger_source=trigger_source,
        trigger_event=trigger_event,
    ) == {"request_image_ref": {"transport_kind": "buffer"}}


def test_input_binding_mapper_rejects_ambiguous_source_and_static_value() -> None:
    """验证动态 source 与非空静态 value 不能形成两个事实源。"""

    trigger_source = _build_trigger_source(
        input_binding_mapping={
            "request_image_ref": {
                "source": "payload.request_image_ref",
                "value": {"transport_kind": "storage"},
            }
        }
    )
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(
            event_id="event-1",
            payload={"request_image_ref": {"transport_kind": "buffer"}},
        ),
    )

    with pytest.raises(InvalidRequestError, match="不能同时配置"):
        InputBindingMapper().map_input_bindings(
            trigger_source=trigger_source,
            trigger_event=trigger_event,
        )


def test_input_binding_mapping_contract_distinguishes_static_null_from_missing() -> None:
    """验证显式静态 null 与完全缺少映射值具有不同契约语义。"""

    static_null = InputBindingMappingItemContract.model_validate({"value": None})
    dynamic_source = InputBindingMappingItemContract.model_validate(
        {"source": "payload.request_image_ref", "value": None}
    )

    assert static_null.value is None
    assert dynamic_source.source == "payload.request_image_ref"
    with pytest.raises(ValueError, match="必须提供 source 或 value"):
        InputBindingMappingItemContract.model_validate({})
    with pytest.raises(ValueError, match="不能同时提供"):
        InputBindingMappingItemContract.model_validate(
            {
                "source": "payload.request_image_ref",
                "value": {"transport_kind": "storage"},
            }
        )


def test_trigger_source_supervisor_deduplicates_idempotency_key() -> None:
    """验证同一 TriggerSource 的相同幂等键只创建一次 WorkflowRun。"""

    trigger_source = _build_trigger_source()
    submitter = _FakeWorkflowSubmitter()
    supervisor = TriggerSourceSupervisor(
        adapters={"http-api": _FakeProtocolAdapter()},
        workflow_submitter=submitter,
    )
    raw_event = RawTriggerEvent(
        event_id="event-1",
        payload={"request": {"id": "same-key", "image": "base64-image"}},
    )

    first = supervisor.handle_trigger_event(
        trigger_source=trigger_source,
        raw_event=raw_event,
    )
    second = supervisor.handle_trigger_event(
        trigger_source=trigger_source,
        raw_event=replace(raw_event, event_id="event-2"),
    )

    assert first.workflow_run_id == "workflow-run-1"
    assert second.workflow_run_id == "workflow-run-1"
    assert second.metadata["idempotent_replay"] is True
    assert submitter.submit_count == 1


def test_trigger_source_supervisor_debounces_without_submitting() -> None:
    """验证 debounce 窗口内的第二条事件不会创建 WorkflowRun。"""

    trigger_source = replace(
        _build_trigger_source(),
        debounce_window_ms=1000,
        idempotency_key_path=None,
    )
    submitter = _FakeWorkflowSubmitter()
    supervisor = TriggerSourceSupervisor(
        adapters={"http-api": _FakeProtocolAdapter()},
        workflow_submitter=submitter,
    )

    supervisor.handle_trigger_event(
        trigger_source=trigger_source,
        raw_event=RawTriggerEvent(event_id="event-1", payload={}),
    )
    result = supervisor.handle_trigger_event(
        trigger_source=trigger_source,
        raw_event=RawTriggerEvent(event_id="event-2", payload={}),
    )

    assert result.state == "accepted"
    assert result.workflow_run_id is None
    assert result.metadata["debounced"] is True
    assert submitter.submit_count == 1


def test_input_binding_mapper_skips_missing_optional_source() -> None:
    """验证可选 input binding 来源缺失时不会向 runtime 传入 None。"""

    trigger_source = _build_trigger_source(
        input_binding_mapping={
            "request_image_base64": {
                "source": "payload.request_image_base64",
                "required": False,
            },
            "request_image_ref": {
                "source": "payload.request_image_ref",
                "required": False,
            },
        },
    )
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(
            event_id="event-1",
            payload={
                "request_image_ref": {
                    "transport_kind": "buffer",
                    "buffer_ref": _build_buffer_ref_payload(),
                }
            },
        ),
    )

    input_bindings = InputBindingMapper().map_input_bindings(
        trigger_source=trigger_source,
        trigger_event=trigger_event,
    )

    assert "request_image_base64" not in input_bindings
    assert input_bindings["request_image_ref"]["transport_kind"] == "buffer"


def test_workflow_result_dispatcher_prefers_configured_output_binding() -> None:
    """验证结果回执优先读取 result_mapping 指定的输出 binding。"""

    trigger_source = _build_trigger_source(submit_mode="sync")
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(event_id="event-1", payload={"request": {"id": "request-1"}}),
    )
    workflow_run = WorkflowRun(
        workflow_run_id="workflow-run-1",
        workflow_runtime_id="workflow-runtime-1",
        project_id="project-1",
        application_id="app-1",
        state="succeeded",
        outputs={"http_response": {"status_code": 200}},
    )

    trigger_result = WorkflowResultDispatcher().build_result(
        trigger_source=trigger_source,
        trigger_event=trigger_event,
        workflow_run=workflow_run,
    )

    assert trigger_result.state == "succeeded"
    assert trigger_result.response_payload["results"] == {
        "http_response": {"status_code": 200}
    }


def test_workflow_result_dispatcher_preserves_failed_run_root_error() -> None:
    """验证失败运行不会被成功态 result binding 校验覆盖根因。"""

    trigger_source = _build_trigger_source(submit_mode="sync")
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(event_id="event-1", payload={"request": {"id": "request-1"}}),
    )
    workflow_run = WorkflowRun(
        workflow_run_id="workflow-run-failed",
        workflow_runtime_id="workflow-runtime-1",
        project_id="project-1",
        application_id="app-1",
        state="failed",
        outputs={},
        error_message="原始节点执行错误",
        metadata={
            "error_details": {
                "error_code": "deployment_inference_busy",
                "deployment_instance_id": "deployment-1",
                "instance_count": 2,
            }
        },
    )

    trigger_result = WorkflowResultDispatcher().build_result(
        trigger_source=trigger_source,
        trigger_event=trigger_event,
        workflow_run=workflow_run,
    )

    assert trigger_result.state == "failed"
    assert trigger_result.error_message == "原始节点执行错误"
    assert trigger_result.metadata["error_code"] == "deployment_inference_busy"
    assert trigger_result.metadata["error_details"]["instance_count"] == 2
    assert trigger_result.response_payload == {
        "workflow_run_id": "workflow-run-failed",
        "workflow_state": "failed",
    }


def test_workflow_submitter_sync_reply_prefers_unsanitized_outputs() -> None:
    """验证 sync TriggerSource 回执优先返回未脱敏最终输出。"""

    trigger_source = _build_trigger_source(submit_mode="sync")
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(
            event_id="event-1",
            payload={"request": {"id": "request-1", "image": "base64-image"}},
        ),
    )

    trigger_result = WorkflowSubmitter(
        runtime_service=_FakeSyncRuntimeService()
    ).submit_event(
        WorkflowTriggerSubmitRequest(
            trigger_source=trigger_source, trigger_event=trigger_event
        )
    )

    result_body = trigger_result.response_payload["results"]["http_response"]["body"]
    assert trigger_result.state == "succeeded"
    assert result_body["data"]["detections"][0]["class_name"] == "box"
    assert result_body["data"]["annotated_image"]["image_base64"] == "YWJj"
    assert "image_base64_redacted" not in result_body["data"]["annotated_image"]


def test_workflow_submitter_allows_trigger_source_without_external_inputs() -> None:
    """验证无外部输入的 TriggerSource 可以触发图内读图或相机取图 workflow。"""

    trigger_source = _build_trigger_source(
        submit_mode="sync",
        input_binding_mapping={},
    )
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(
            event_id="event-1",
            payload={"job_id": "job-1"},
        ),
    )
    runtime_service = _CapturingSyncRuntimeService()

    trigger_result = WorkflowSubmitter(runtime_service=runtime_service).submit_event(
        WorkflowTriggerSubmitRequest(
            trigger_source=trigger_source, trigger_event=trigger_event
        )
    )

    assert trigger_result.state == "succeeded"
    assert runtime_service.last_request is not None
    assert runtime_service.last_request.input_bindings == {}
    assert runtime_service.last_execution_acquisition_mode == "reject"


def test_workflow_submitter_zeromq_defaults_to_no_trace() -> None:
    """验证 ZeroMQ TriggerSource 默认关闭 trace、诊断返回并使用最小记录模式。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        submit_mode="sync",
        input_binding_mapping={
            "request_image_ref": {"source": "payload.request_image_ref"}
        },
    )
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(
            event_id="event-1",
            payload={
                "request_image_ref": {
                    "transport_kind": "buffer",
                    "buffer_ref": _build_buffer_ref_payload(lease_id="lease-input-1"),
                }
            },
        ),
    )
    runtime_service = _CapturingSyncRuntimeService()

    trigger_result = WorkflowSubmitter(runtime_service=runtime_service).submit_event(
        WorkflowTriggerSubmitRequest(
            trigger_source=trigger_source, trigger_event=trigger_event
        )
    )

    execution_metadata = runtime_service.last_request.execution_metadata
    assert trigger_result.state == "succeeded"
    assert execution_metadata["trace_level"] == "none"
    assert execution_metadata["retain_trace_enabled"] is False
    assert execution_metadata["retain_node_records_enabled"] is False
    assert execution_metadata["workflow_run_record_mode"] == "minimal"
    assert execution_metadata["return_timing_metadata_enabled"] is False
    assert execution_metadata["return_node_timings_enabled"] is False
    assert runtime_service.last_execution_acquisition_mode == "reject"


def test_workflow_submitter_omits_diagnostics_by_default() -> None:
    """验证 TriggerResult 默认不返回 timings 和 node_timings。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        submit_mode="sync",
        input_binding_mapping={},
    )
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(event_id="event-1", payload={}),
    )

    trigger_result = WorkflowSubmitter(
        runtime_service=_DiagnosticSyncRuntimeService()
    ).submit_event(
        WorkflowTriggerSubmitRequest(
            trigger_source=trigger_source, trigger_event=trigger_event
        )
    )

    assert trigger_result.state == "succeeded"
    assert "timings" not in trigger_result.metadata
    assert "node_timings" not in trigger_result.metadata


def test_workflow_submitter_returns_diagnostics_when_enabled() -> None:
    """验证显式开启诊断后 TriggerResult 返回耗时摘要。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        submit_mode="sync",
        input_binding_mapping={},
        default_execution_metadata={
            "return_timing_metadata_enabled": True,
            "return_node_timings_enabled": True,
        },
    )
    trigger_event = TriggerEventNormalizer().normalize(
        trigger_source,
        RawTriggerEvent(event_id="event-1", payload={}),
    )

    trigger_result = WorkflowSubmitter(
        runtime_service=_DiagnosticSyncRuntimeService()
    ).submit_event(
        WorkflowTriggerSubmitRequest(
            trigger_source=trigger_source, trigger_event=trigger_event
        )
    )

    assert trigger_result.state == "succeeded"
    assert trigger_result.metadata["timings"]["trigger_submit_total_ms"] >= 0
    assert trigger_result.metadata["timings"]["workflow_worker_execute_ms"] == 12.5
    assert trigger_result.metadata["node_timings"] == [
        {
            "node_id": "detect",
            "node_type_id": "core.model.detection",
            "runtime_kind": "worker-task",
            "duration_ms": 10.0,
        }
    ]


def test_trigger_source_supervisor_submits_normalized_event() -> None:
    """验证 supervisor 可以标准化事件并提交给 WorkflowSubmitter。"""

    trigger_source = _build_trigger_source()
    submitter = _FakeWorkflowSubmitter()
    adapter = _FakeProtocolAdapter()
    supervisor = TriggerSourceSupervisor(
        adapters={"http-api": adapter},
        workflow_submitter=submitter,
    )

    supervisor.start_trigger_source(trigger_source)
    result = adapter.emit(
        trigger_source=trigger_source,
        raw_event=RawTriggerEvent(
            event_id="event-1",
            payload={"request": {"id": "request-1", "image": "base64-image"}},
        ),
    )
    health = supervisor.get_health("trigger-source-1")
    supervisor.stop_trigger_source("trigger-source-1")

    assert result.state == "accepted"
    assert submitter.last_request is not None
    assert submitter.last_request.trigger_event.idempotency_key == "request-1"
    assert health["managed"] is True
    assert health["request_count"] == 1
    assert health["success_count"] == 1
    assert adapter.stopped_trigger_source_id == "trigger-source-1"


def test_zeromq_trigger_adapter_maps_content_frame_to_buffer_ref_payload() -> None:
    """验证 ZeroMQ adapter 可以把 multipart 图片帧转换成 BufferRef payload。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        input_binding_mapping={
            "request_image_ref": {"source": "payload.request_image_ref"}
        },
        transport_config={
            "bind_endpoint": f"inproc://zeromq-trigger-test-{uuid4().hex}",
            "default_input_binding": "request_image_ref",
        },
    )
    local_buffer_writer = _FakeLocalBufferWriter()
    adapter = _build_zeromq_adapter(local_buffer_writer)
    submitter = _FakeWorkflowSubmitter()
    supervisor = TriggerSourceSupervisor(
        adapters={"zeromq-topic": _FakeProtocolAdapter(adapter_kind="zeromq-topic")},
        workflow_submitter=submitter,
    )

    adapter.start(trigger_source=trigger_source, event_handler=supervisor)
    try:
        result = adapter.handle_multipart_message(
            trigger_source=trigger_source,
            frames=[
                b'{"event_id":"event-1","media_type":"image/png","shape":[2,2,3]}',
                b"image-bytes",
            ],
            event_handler=supervisor,
        )
        adapter_health = adapter.get_health(trigger_source_id="trigger-source-1")
    finally:
        adapter.stop(trigger_source_id="trigger-source-1")

    assert result.state == "accepted"
    assert adapter_health["received_count"] == 1
    assert adapter_health["submitted_count"] == 1
    assert submitter.last_request is not None
    payload = submitter.last_request.trigger_event.payload
    image_payload = payload["request_image_ref"]
    assert image_payload["transport_kind"] == "buffer"
    assert image_payload["media_type"] == "image/png"
    assert image_payload["buffer_ref"]["format_id"] == "amvision.buffer-ref.v1"
    assert image_payload["buffer_ref"]["media_type"] == "image/png"
    assert local_buffer_writer.write_calls[0]["content"] == b"image-bytes"
    cleanup_items = submitter.last_request.trigger_source.default_execution_metadata[
        WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY
    ]
    assert cleanup_items == [
        {
            "resource_kind": "local_buffer_lease",
            "resource_id": "lease-1",
            "metadata": {},
        }
    ]


def test_zeromq_trigger_adapter_releases_unclaimed_replay_buffer() -> None:
    """验证幂等重放没有新建 WorkflowRun 时立即释放本次输入 lease。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        input_binding_mapping={
            "request_image_ref": {"source": "payload.request_image_ref"}
        },
        transport_config={"default_input_binding": "request_image_ref"},
    )
    local_buffer_writer = _FakeLocalBufferWriter()
    adapter = _build_zeromq_adapter(local_buffer_writer)

    class _ReplayHandler:
        def handle_trigger_event(self, *, trigger_source, raw_event):
            return WorkflowTriggerDispatchResult(
                trigger_result=TriggerResultContract(
                    trigger_source_id=trigger_source.trigger_source_id,
                    event_id=raw_event.event_id or "event-replay",
                    state="succeeded",
                    workflow_run_id="workflow-run-original",
                    metadata={"idempotent_replay": True},
                )
            )

    result = adapter.handle_multipart_message(
        trigger_source=trigger_source,
        frames=[b'{"event_id":"event-replay","media_type":"image/png"}', b"image"],
        event_handler=_ReplayHandler(),
    )

    assert result.metadata["idempotent_replay"] is True
    assert local_buffer_writer.released_leases == ["lease-1"]


def test_zeromq_bgr24_trigger_invokes_deployment_model_without_diagnostics_by_default() -> (
    None
):
    """验证 BGR24 高速触发默认不返回 workflow 和 deployment 诊断字段。"""

    trigger_result, runtime_service, local_buffer_writer = (
        _run_bgr24_deployment_trigger_smoke(return_diagnostics=False)
    )

    assert trigger_result.state == "succeeded"
    assert "timings" not in trigger_result.metadata
    assert "node_timings" not in trigger_result.metadata
    assert local_buffer_writer.write_calls[0]["media_type"] == "image/raw"
    assert local_buffer_writer.write_calls[0]["shape"] == (2, 2, 3)
    assert local_buffer_writer.write_calls[0]["dtype"] == "uint8"
    assert local_buffer_writer.write_calls[0]["layout"] == "HWC"
    assert local_buffer_writer.write_calls[0]["pixel_format"] == "bgr24"
    assert runtime_service.gateway.last_request is not None
    assert runtime_service.gateway.last_request.runtime_mode == "sync"
    assert runtime_service.gateway.last_request.input_image_bytes is None
    assert (
        runtime_service.gateway.last_request.image_payload["transport_kind"] == "buffer"
    )
    assert (
        runtime_service.gateway.last_request.image_payload["buffer_ref"]["media_type"]
        == "image/raw"
    )
    result_payload = trigger_result.response_payload["results"]["http_response"]
    assert result_payload["detections"]["items"][0]["class_name"] == "barcode"
    assert "timings" not in result_payload["detections"]["metadata"]
    assert "runtime_infer_ms" not in result_payload["runtime_session_info"]["metadata"]


def test_zeromq_bgr24_trigger_returns_diagnostics_when_enabled() -> None:
    """验证显式开启诊断后 BGR24 触发返回 workflow 和 deployment 耗时字段。"""

    trigger_result, runtime_service, _ = _run_bgr24_deployment_trigger_smoke(
        return_diagnostics=True
    )

    assert trigger_result.state == "succeeded"
    assert trigger_result.metadata["timings"]["trigger_submit_total_ms"] >= 0
    assert trigger_result.metadata["timings"]["workflow_worker_execute_ms"] == 3.5
    assert trigger_result.metadata["timings"]["zeromq_adapter_total_ms"] >= 0
    assert trigger_result.metadata["node_timings"] == [
        {
            "node_id": "deployment-detect",
            "node_type_id": "core.model.detection",
            "runtime_kind": "worker-task",
            "duration_ms": 3.5,
        }
    ]
    assert runtime_service.gateway.last_request is not None
    result_payload = trigger_result.response_payload["results"]["http_response"]
    assert (
        result_payload["detections"]["metadata"]["timings"]["runtime_infer_ms"] == 2.25
    )
    assert (
        result_payload["runtime_session_info"]["metadata"]["runtime_infer_ms"] == 2.25
    )


def test_zeromq_trigger_adapter_defaults_content_frame_to_image_ref_binding() -> None:
    """验证 ZeroMQ adapter 会把新双入口图默认写入 request_image_ref。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        input_binding_mapping={
            "request_image_base64": {
                "source": "payload.request_image_base64",
                "required": False,
            },
            "request_image_ref": {
                "source": "payload.request_image_ref",
                "required": False,
            },
        },
    )
    adapter = _build_zeromq_adapter(_FakeLocalBufferWriter())
    submitter = _FakeWorkflowSubmitter()
    supervisor = TriggerSourceSupervisor(
        adapters={"zeromq-topic": _FakeProtocolAdapter(adapter_kind="zeromq-topic")},
        workflow_submitter=submitter,
    )

    result = adapter.handle_multipart_message(
        trigger_source=trigger_source,
        frames=[b'{"event_id":"event-1","media_type":"image/png"}', b"image-bytes"],
        event_handler=supervisor,
    )

    assert result.state == "accepted"
    assert submitter.last_request is not None
    input_bindings = submitter.last_request.trigger_event.payload
    assert "request_image_base64" not in input_bindings
    assert input_bindings["request_image_ref"]["transport_kind"] == "buffer"


def test_zeromq_trigger_adapter_releases_buffer_when_submit_is_rejected() -> None:
    """验证提交在创建 WorkflowRun 前失败时会释放刚写入的输入 buffer。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        input_binding_mapping={
            "request_image_ref": {"source": "payload.request_image_ref"}
        },
        transport_config={"default_input_binding": "request_image_ref"},
    )
    local_buffer_writer = _FakeLocalBufferWriter()
    adapter = _build_zeromq_adapter(local_buffer_writer)
    supervisor = TriggerSourceSupervisor(
        adapters={"zeromq-topic": _FakeProtocolAdapter(adapter_kind="zeromq-topic")},
        workflow_submitter=_RejectingWorkflowSubmitter(),
    )

    result = adapter.handle_multipart_message(
        trigger_source=trigger_source,
        frames=[b'{"event_id":"event-1","media_type":"image/png"}', b"image-bytes"],
        event_handler=supervisor,
    )

    assert result.state == "failed"
    assert result.workflow_run_id is None
    assert local_buffer_writer.released_leases == ["lease-1"]


def test_zeromq_trigger_adapter_serves_req_rep_message() -> None:
    """验证 ZeroMQ adapter 线程可以接收 REQ multipart 并返回 JSON reply。"""

    endpoint = f"inproc://zeromq-trigger-live-{uuid4().hex}"
    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        input_binding_mapping={
            "request_image_ref": {"source": "payload.request_image_ref"}
        },
        transport_config={
            "bind_endpoint": endpoint,
            "default_input_binding": "request_image_ref",
        },
    )
    adapter = _build_zeromq_adapter(_FakeLocalBufferWriter())
    supervisor = TriggerSourceSupervisor(
        adapters={"zeromq-topic": _FakeProtocolAdapter(adapter_kind="zeromq-topic")},
        workflow_submitter=_FakeWorkflowSubmitter(),
    )
    context = zmq.Context.instance()
    socket = context.socket(zmq.REQ)
    socket.linger = 0
    socket.rcvtimeo = 2000
    socket.sndtimeo = 2000

    adapter.start(trigger_source=trigger_source, event_handler=supervisor)
    try:
        _wait_for_zeromq_adapter_running(adapter, "trigger-source-1")
        socket.connect(endpoint)
        socket.send_multipart(
            [
                b'{"event_id":"event-live","media_type":"image/png"}',
                b"image-bytes",
            ]
        )
        reply_frames = socket.recv_multipart()
        reply_payload = json.loads(reply_frames[0].decode("utf-8"))
        adapter_health = adapter.get_health(trigger_source_id="trigger-source-1")
    finally:
        socket.close(linger=0)
        adapter.stop(trigger_source_id="trigger-source-1")

    assert reply_payload["format_id"] == "amvision.workflow-trigger-result.v1"
    assert reply_payload["state"] == "accepted"
    assert reply_payload["event_id"] == "event-live"
    assert adapter_health["received_count"] == 1
    assert adapter_health["submitted_count"] == 1


def test_zeromq_trigger_adapter_sends_deduplicated_tracked_image_frames() -> None:
    """验证 Result v1 用一个物理 frame 服务多个逻辑 attachment 并在发送后释放。"""

    endpoint = f"inproc://zeromq-trigger-result-{uuid4().hex}"
    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        submit_mode="sync",
        input_binding_mapping={},
        transport_config={"bind_endpoint": endpoint},
    )
    image_bytes = b"encoded-result-image"
    buffer_writer = _FakeResultBufferWriter(image_bytes)
    adapter = _build_zeromq_adapter(buffer_writer)
    prepared = _build_prepared_zeromq_result(image_bytes)

    class _ImageResultHandler:
        def handle_trigger_event(self, *, trigger_source, raw_event):
            return WorkflowTriggerDispatchResult(
                trigger_result=TriggerResultContract(
                    trigger_source_id=trigger_source.trigger_source_id,
                    event_id=raw_event.event_id or "event-result",
                    state="succeeded",
                    workflow_run_id="workflow-run-result",
                    metadata={"timings": {"workflow_execute_ms": 1.0}},
                ),
                prepared_trigger_result=prepared,
            )

    context = zmq.Context.instance()
    socket = context.socket(zmq.REQ)
    socket.linger = 0
    socket.rcvtimeo = 2000
    socket.sndtimeo = 2000
    adapter.start(trigger_source=trigger_source, event_handler=_ImageResultHandler())
    try:
        socket.connect(endpoint)
        socket.send_multipart([b'{"event_id":"event-result"}'])
        reply_frames = socket.recv_multipart()
        manifest = json.loads(reply_frames[0].decode("utf-8"))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not buffer_writer.released_receipts:
            time.sleep(0.005)
        health = adapter.get_health(trigger_source_id=trigger_source.trigger_source_id)
    finally:
        socket.close(linger=0)
        adapter.stop(trigger_source_id=trigger_source.trigger_source_id)

    assert len(reply_frames) == 2
    assert reply_frames[1] == image_bytes
    assert manifest["format_id"] == "amvision.workflow-trigger-result.v1"
    assert manifest["response_payload"]["payloads"] == [
        {
            "payload_id": "physical-1",
            "delivery_kind": "zeromq-frame",
            "frame_index": 1,
            "media_type": "image/png",
            "content_length": len(image_bytes),
            "checksum_algorithm": "crc32",
            "checksum": "00000000",
            "width": None,
            "height": None,
            "shape": [],
            "dtype": None,
            "layout": None,
            "pixel_format": None,
        }
    ]
    attachments = manifest["response_payload"]["attachments"]
    assert [item["payload_id"] for item in attachments] == [
        "physical-1",
        "physical-1",
    ]
    assert buffer_writer.guard_enter_count == 1
    assert buffer_writer.guard_exit_count == 1
    assert len(buffer_writer.released_receipts) == 1
    assert health["transport_registry_active_count"] == 0
    assert manifest["metadata"]["timings"]["response_json_serialize_ms"] >= 0
    assert health["transport_timings"]["response_json_serialize_ms"] >= 0
    assert health["transport_timings"]["zeromq_attachment_send_ms"] >= 0
    assert health["transport_timings"]["tracker_cleanup_ms"] >= 0
    assert health["transport_timings"]["lease_reclaim_ms"] >= 0


def test_zeromq_error_reply_uses_unified_trigger_result_contract() -> None:
    """验证协议错误不再使用独立历史 error format。"""

    adapter = _build_zeromq_adapter(_FakeLocalBufferWriter())
    payload = json.loads(
        adapter.build_error_reply_frames(
            trigger_source_id="trigger-source-1",
            error=InvalidRequestError("bad envelope", details={"field": "payload"}),
        )[0].decode("utf-8")
    )

    assert payload["format_id"] == "amvision.workflow-trigger-result.v1"
    assert payload["state"] == "failed"
    assert payload["metadata"] == {
        "error_code": "invalid_request",
        "error_details": {"field": "payload"},
    }
    assert "amvision.zeromq-trigger-error.v1" not in json.dumps(payload)


def test_zeromq_health_classifies_workflow_deployment_busy_result() -> None:
    """验证模型节点满载结果能进入 ZeroMQ source-scoped busy 指标。"""

    endpoint = f"inproc://zeromq-trigger-busy-{uuid4().hex}"
    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        submit_mode="sync",
        input_binding_mapping={},
        transport_config={"bind_endpoint": endpoint},
    )
    adapter = _build_zeromq_adapter(_FakeLocalBufferWriter())

    class _BusyResultHandler:
        def handle_trigger_event(self, *, trigger_source, raw_event):
            return WorkflowTriggerDispatchResult(
                trigger_result=TriggerResultContract(
                    trigger_source_id=trigger_source.trigger_source_id,
                    event_id=raw_event.event_id or "event-busy",
                    state="failed",
                    error_message="当前 deployment 推理实例已满载",
                    metadata={"error_code": "deployment_inference_busy"},
                )
            )

    adapter.start(trigger_source=trigger_source, event_handler=_BusyResultHandler())
    try:
        result = adapter.handle_multipart_message(
            trigger_source=trigger_source,
            frames=[b'{"event_id":"event-busy"}'],
            event_handler=_BusyResultHandler(),
        )
        health = adapter.get_health(
            trigger_source_id=trigger_source.trigger_source_id
        )
    finally:
        adapter.stop(trigger_source_id=trigger_source.trigger_source_id)

    assert result.state == "failed"
    assert health["request_count"] == 1
    assert health["error_count"] == 1
    assert health["busy_count"] == 1
    assert health["capacity_reject_count"] == 0
    assert health["recent_error"]["error_code"] == "deployment_inference_busy"


def test_zeromq_image_reply_rejects_capacity_before_first_frame() -> None:
    """验证 transport registry 满载在发送前失败，并释放未交付 output lease。"""

    endpoint = f"inproc://zeromq-trigger-capacity-{uuid4().hex}"
    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        submit_mode="sync",
        input_binding_mapping={},
        transport_config={"bind_endpoint": endpoint},
    )
    image_bytes = b"encoded-result-image"
    buffer_writer = _FakeResultBufferWriter(image_bytes)
    adapter = _build_zeromq_adapter(
        buffer_writer,
        transport_registry_max_bytes=4,
    )
    prepared = _build_prepared_zeromq_result(image_bytes)

    class _ImageResultHandler:
        def handle_trigger_event(self, *, trigger_source, raw_event):
            return WorkflowTriggerDispatchResult(
                trigger_result=TriggerResultContract(
                    trigger_source_id=trigger_source.trigger_source_id,
                    event_id=raw_event.event_id or "event-capacity",
                    state="succeeded",
                ),
                prepared_trigger_result=prepared,
            )

    context = zmq.Context.instance()
    socket = context.socket(zmq.REQ)
    socket.linger = 0
    socket.rcvtimeo = 2000
    adapter.start(trigger_source=trigger_source, event_handler=_ImageResultHandler())
    try:
        socket.connect(endpoint)
        socket.send_multipart([b'{"event_id":"event-capacity"}'])
        reply_frames = socket.recv_multipart()
        reply = json.loads(reply_frames[0].decode("utf-8"))
    finally:
        socket.close(linger=0)
        adapter.stop(trigger_source_id=trigger_source.trigger_source_id)

    assert len(reply_frames) == 1
    assert reply["format_id"] == "amvision.workflow-trigger-result.v1"
    assert reply["state"] == "failed"
    assert reply["metadata"]["error_code"] == "zeromq_transport_capacity_exhausted"
    assert buffer_writer.guard_enter_count == 0
    assert len(buffer_writer.released_receipts) == 1


def test_zeromq_send_failure_closes_socket_before_tracker_cleanup() -> None:
    """验证部分发送异常不会在 libzmq tracker 完成前释放 reader guard。"""

    image_bytes = b"encoded-result-image"
    buffer_writer = _FakeResultBufferWriter(image_bytes)
    adapter = _build_zeromq_adapter(buffer_writer)
    prepared = _build_prepared_zeromq_result(image_bytes)
    dispatch_result = WorkflowTriggerDispatchResult(
        trigger_result=TriggerResultContract(
            trigger_source_id="trigger-source-1",
            event_id="event-send-failed",
            state="succeeded",
        ),
        prepared_trigger_result=prepared,
    )

    class _Tracker:
        def __init__(self) -> None:
            self.done = False

    class _Frame:
        def __init__(self, _view, *, copy, track) -> None:
            assert copy is False
            assert track is True
            self.tracker = _Tracker()

    class _ZeroMq:
        Frame = _Frame
        SNDMORE = 2

    class _FailingSocket:
        def __init__(self) -> None:
            self.closed = False

        def send(self, frame, *, flags, copy=None, track=None):
            if isinstance(frame, bytes):
                assert flags == _ZeroMq.SNDMORE
                return None
            assert flags == 0
            assert copy is False
            assert track is True
            raise RuntimeError("send failed")

        def close(self, *, linger) -> None:
            assert linger == 0
            self.closed = True

    socket = _FailingSocket()
    with pytest.raises(RuntimeError, match="send failed"):
        adapter._send_dispatch_result(
            socket=socket,
            zeromq=_ZeroMq(),
            dispatch_result=dispatch_result,
            socket_generation="socket-failure-1",
        )

    assert socket.closed is True
    assert buffer_writer.guard_enter_count == 1
    assert buffer_writer.guard_exit_count == 1
    assert len(buffer_writer.released_receipts) == 1
    assert adapter._transport_registry.snapshot()[
        "transport_registry_active_count"
    ] == 0
    assert adapter._transport_registry.wait_until_idle(timeout_seconds=1.0) is True


def test_zeromq_rebuilds_rep_socket_with_new_generation() -> None:
    """验证发送失败后替换 REP socket，而旧 tracker 可继续独立回收。"""

    adapter = _build_zeromq_adapter(_FakeLocalBufferWriter())

    class _Socket:
        def __init__(self) -> None:
            self.closed = False
            self.bound_endpoint: str | None = None

        def close(self, *, linger) -> None:
            assert linger == 0
            self.closed = True

        def bind(self, endpoint: str) -> None:
            self.bound_endpoint = endpoint

    old_socket = _Socket()
    replacement = _Socket()

    class _Context:
        def socket(self, socket_kind):
            assert socket_kind == 1
            return replacement

    class _Poller:
        def __init__(self) -> None:
            self.unregistered: list[object] = []
            self.registered: list[tuple[object, object]] = []

        def unregister(self, socket) -> None:
            self.unregistered.append(socket)

        def register(self, socket, event) -> None:
            self.registered.append((socket, event))

    zeromq = SimpleNamespace(
        REP=1,
        POLLIN=2,
        RCVHWM=3,
        SNDHWM=4,
        MAXMSGSIZE=5,
    )
    replacement.setsockopt = lambda option, value: None
    poller = _Poller()
    state = SimpleNamespace(
        bind_endpoint="inproc://replacement",
        socket_generation="socket-generation-old",
        lifecycle_lock=adapter._lock,
    )

    rebuilt = adapter._rebuild_rep_socket(
        zeromq=zeromq,
        context=_Context(),
        poller=poller,
        socket=old_socket,
        state=state,
    )

    assert rebuilt is replacement
    assert old_socket.closed is True
    assert poller.unregistered == [old_socket]
    assert poller.registered == [(replacement, zeromq.POLLIN)]
    assert replacement.bound_endpoint == state.bind_endpoint
    assert state.socket_generation.startswith("zeromq-socket-")
    assert state.socket_generation != "socket-generation-old"


def test_zeromq_stop_keeps_stopping_state_until_listener_exits() -> None:
    """验证阻塞 handler 不会让 stop 假报成功或提前释放 endpoint 状态。"""

    endpoint = f"inproc://zeromq-trigger-stop-{uuid4().hex}"
    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        submit_mode="sync",
        input_binding_mapping={},
        transport_config={"bind_endpoint": endpoint},
    )
    entered = Event()
    release = Event()

    class _BlockingHandler:
        def handle_trigger_event(self, *, trigger_source, raw_event):
            del raw_event
            entered.set()
            release.wait(timeout=2.0)
            return WorkflowTriggerDispatchResult(
                trigger_result=TriggerResultContract(
                    trigger_source_id=trigger_source.trigger_source_id,
                    event_id="event-stop",
                    state="accepted",
                )
            )

    adapter = _build_zeromq_adapter(
        _FakeLocalBufferWriter(),
        shutdown_timeout_seconds=0.05,
    )
    context = zmq.Context.instance()
    socket = context.socket(zmq.REQ)
    socket.linger = 0
    socket.rcvtimeo = 2000
    adapter.start(trigger_source=trigger_source, event_handler=_BlockingHandler())
    try:
        socket.connect(endpoint)
        socket.send_multipart([b'{"event_id":"event-stop"}'])
        assert entered.wait(timeout=1.0)
        with pytest.raises(OperationTimeoutError):
            adapter.stop(trigger_source_id=trigger_source.trigger_source_id)
        health = adapter.get_health(trigger_source_id=trigger_source.trigger_source_id)
        assert health["running"] is True
        assert health["stopping"] is True
        with pytest.raises(InvalidRequestError, match="已经启动"):
            adapter.start(
                trigger_source=trigger_source, event_handler=_BlockingHandler()
            )
        release.set()
        socket.recv_multipart()
        adapter.stop(trigger_source_id=trigger_source.trigger_source_id)
    finally:
        release.set()
        socket.close(linger=0)


def test_zeromq_trigger_rejects_extra_or_oversized_frames() -> None:
    """验证 multipart 帧数量和字节上限在写入 broker 前被拒绝。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
    )
    adapter = _build_zeromq_adapter(
        _FakeLocalBufferWriter(),
        max_message_size_bytes=16,
    )
    handler = TriggerSourceSupervisor(
        adapters={"zeromq-topic": _FakeProtocolAdapter(adapter_kind="zeromq-topic")},
        workflow_submitter=_FakeWorkflowSubmitter(),
    )

    with pytest.raises(InvalidRequestError, match="只能包含"):
        adapter.handle_multipart_message(
            trigger_source=trigger_source,
            frames=[b"{}", b"image", b"extra"],
            event_handler=handler,
        )
    with pytest.raises(InvalidRequestError, match="超过"):
        adapter.handle_multipart_message(
            trigger_source=trigger_source,
            frames=[b"{}", b"x" * 17],
            event_handler=handler,
        )


def test_zeromq_trigger_adapter_allows_envelope_only_event_without_input_frame() -> (
    None
):
    """验证 ZeroMQ 也可以只发事件 envelope，用于图内自行取图的 workflow。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        input_binding_mapping={},
    )
    adapter = _build_zeromq_adapter(_FakeLocalBufferWriter())
    submitter = _FakeWorkflowSubmitter()
    supervisor = TriggerSourceSupervisor(
        adapters={"zeromq-topic": _FakeProtocolAdapter(adapter_kind="zeromq-topic")},
        workflow_submitter=submitter,
    )

    result = adapter.handle_multipart_message(
        trigger_source=trigger_source,
        frames=[b'{"event_id":"event-no-image","payload":{"job_id":"job-1"}}'],
        event_handler=supervisor,
    )

    assert result.state == "accepted"
    assert submitter.last_request is not None
    assert submitter.last_request.trigger_event.payload == {"job_id": "job-1"}


def test_plc_register_trigger_adapter_polls_and_submits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 PLC trigger adapter 可以轮询寄存器并提交标准化事件。"""

    class _MatchedCoilClient:
        """测试用匹配成功的 Modbus client。"""

        def __init__(
            self, host: str, *, port: int, timeout: float, retries: int
        ) -> None:
            """记录连接参数。"""

            self.host = host
            self.port = port
            self.timeout = timeout
            self.retries = retries

        def close(self) -> None:
            """关闭测试 client。"""

        def read_coils(
            self,
            address: int,
            *,
            count: int,
            device_id: int,
        ) -> ModbusBitsReadResponse:
            """返回固定命中的 coil 响应。"""

            return ModbusBitsReadResponse(
                bits=[True],
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=1,
                function_code=1,
                retries=0,
            )

    monkeypatch.setattr(
        "backend.service.infrastructure.integrations.modbus.plc_register_trigger_adapter.ProjectModbusTcpClient",
        _MatchedCoilClient,
    )

    trigger_source = _build_trigger_source(
        trigger_kind="plc-register",
        input_binding_mapping={"request_signal": {"source": "payload.observed_value"}},
        transport_config={
            "driver": "modbus-tcp",
            "host": "127.0.0.1",
            "port": 502,
            "unit_id": 1,
            "register_address": "00001",
            "data_type": "bool",
            "poll_interval_ms": 20,
            "reconnect_interval_ms": 20,
        },
        match_rule={
            "operator": "eq",
            "expected_value": True,
            "stable_match_count": 1,
            "trigger_mode": "enter-match",
            "emit_initial_match": True,
        },
    )
    adapter = PlcRegisterTriggerAdapter()
    submitter = _FakeWorkflowSubmitter()
    supervisor = TriggerSourceSupervisor(
        adapters={"plc-register": _FakeProtocolAdapter(adapter_kind="plc-register")},
        workflow_submitter=submitter,
    )

    adapter.start(trigger_source=trigger_source, event_handler=supervisor)
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and submitter.last_request is None:
            time.sleep(0.01)
        health = adapter.get_health(trigger_source_id="trigger-source-1")
    finally:
        adapter.stop(trigger_source_id="trigger-source-1")

    assert submitter.last_request is not None
    assert submitter.last_request.trigger_event.payload["observed_value"] is True
    assert submitter.last_request.trigger_event.payload["register_address"] == "00001"
    assert submitter.last_request.trigger_event.payload["sequence_id"] == 1
    assert health["running"] is True
    assert health["match_count"] == 1
    assert health["submitted_count"] == 1


def test_plc_register_trigger_adapter_rejects_sync_submit_mode() -> None:
    """验证 PLC trigger adapter 当前拒绝 sync submit_mode。"""

    trigger_source = _build_trigger_source(
        trigger_kind="plc-register",
        submit_mode="sync",
        transport_config={
            "driver": "modbus-tcp",
            "host": "127.0.0.1",
            "register_address": "00001",
            "data_type": "bool",
        },
        match_rule={"operator": "eq", "expected_value": True},
    )
    adapter = PlcRegisterTriggerAdapter()

    with pytest.raises(InvalidRequestError) as error_info:
        adapter.start(
            trigger_source=trigger_source,
            event_handler=TriggerSourceSupervisor(
                adapters={
                    "plc-register": _FakeProtocolAdapter(adapter_kind="plc-register")
                },
                workflow_submitter=_FakeWorkflowSubmitter(),
            ),
        )

    assert error_info.value.details["submit_mode"] == "sync"


def test_directory_poll_trigger_adapter_polls_new_files_and_writes_checkpoint(
    tmp_path: Path,
) -> None:
    """验证 directory-poll adapter 会扫描新文件、提交事件并落 checkpoint。"""

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    first_file = incoming_dir / "sample-a.png"
    first_file.write_bytes(b"image-a")

    trigger_source = _build_trigger_source(
        trigger_kind="directory-poll",
        input_binding_mapping={"request_batch": {"source": "payload.files"}},
        transport_config={
            "directory_path": str(incoming_dir),
            "scan_interval_seconds": 0.05,
            "batch_size": 2,
            "min_stable_age_seconds": 0.0,
            "extensions": ["png"],
        },
    )
    adapter = DirectoryPollTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )
    submitter = _FakeWorkflowSubmitter()
    supervisor = TriggerSourceSupervisor(
        adapters={
            "directory-poll": _FakeProtocolAdapter(adapter_kind="directory-poll")
        },
        workflow_submitter=submitter,
    )

    adapter.start(trigger_source=trigger_source, event_handler=supervisor)
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and submitter.last_request is None:
            time.sleep(0.01)
        time.sleep(0.15)
        health = adapter.get_health(trigger_source_id="trigger-source-1")
    finally:
        adapter.stop(trigger_source_id="trigger-source-1")

    assert submitter.last_request is not None
    payload = submitter.last_request.trigger_event.payload
    assert payload["file_count"] == 1
    assert payload["files"][0]["file_name"] == "sample-a.png"
    assert payload["primary_file_path"] == str(first_file.resolve())
    assert health["running"] is True
    assert health["submitted_count"] == 1
    assert Path(health["checkpoint_path"]).is_file()


def test_directory_poll_trigger_adapter_uses_checkpoint_to_avoid_reprocessing(
    tmp_path: Path,
) -> None:
    """验证 directory-poll adapter 重启后不会重复处理已记录文件。"""

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    first_file = incoming_dir / "sample-a.png"
    first_file.write_bytes(b"image-a")

    trigger_source = _build_trigger_source(
        trigger_kind="directory-poll",
        input_binding_mapping={"request_batch": {"source": "payload.files"}},
        transport_config={
            "directory_path": str(incoming_dir),
            "scan_interval_seconds": 0.05,
            "batch_size": 1,
            "min_stable_age_seconds": 0.0,
            "extensions": ["png"],
        },
    )
    first_adapter = DirectoryPollTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )
    first_submitter = _FakeWorkflowSubmitter()
    first_supervisor = TriggerSourceSupervisor(
        adapters={
            "directory-poll": _FakeProtocolAdapter(adapter_kind="directory-poll")
        },
        workflow_submitter=first_submitter,
    )

    first_adapter.start(trigger_source=trigger_source, event_handler=first_supervisor)
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and first_submitter.last_request is None:
            time.sleep(0.01)
    finally:
        first_adapter.stop(trigger_source_id="trigger-source-1")

    assert first_submitter.last_request is not None

    second_adapter = DirectoryPollTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )
    second_submitter = _FakeWorkflowSubmitter()
    second_supervisor = TriggerSourceSupervisor(
        adapters={
            "directory-poll": _FakeProtocolAdapter(adapter_kind="directory-poll")
        },
        workflow_submitter=second_submitter,
    )

    second_adapter.start(trigger_source=trigger_source, event_handler=second_supervisor)
    try:
        time.sleep(0.2)
        health = second_adapter.get_health(trigger_source_id="trigger-source-1")
    finally:
        second_adapter.stop(trigger_source_id="trigger-source-1")

    assert second_submitter.last_request is None
    assert health["known_identity_count"] == 1
    assert health["submitted_count"] == 0


def test_directory_poll_trigger_adapter_rejects_sync_submit_mode(
    tmp_path: Path,
) -> None:
    """验证 directory-poll adapter 当前拒绝 sync submit_mode。"""

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    trigger_source = _build_trigger_source(
        trigger_kind="directory-poll",
        submit_mode="sync",
        transport_config={"directory_path": str(incoming_dir)},
    )
    adapter = DirectoryPollTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )

    with pytest.raises(InvalidRequestError) as error_info:
        adapter.start(
            trigger_source=trigger_source,
            event_handler=TriggerSourceSupervisor(
                adapters={
                    "directory-poll": _FakeProtocolAdapter(
                        adapter_kind="directory-poll"
                    )
                },
                workflow_submitter=_FakeWorkflowSubmitter(),
            ),
        )

    assert error_info.value.details["submit_mode"] == "sync"


def test_directory_watch_trigger_adapter_watches_new_files_and_writes_checkpoint(
    tmp_path: Path,
) -> None:
    """验证 directory-watch adapter 会监听新文件、提交事件并落 checkpoint。"""

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()

    trigger_source = _build_trigger_source(
        trigger_kind="directory-watch",
        input_binding_mapping={"request_batch": {"source": "payload.files"}},
        transport_config={
            "directory_path": str(incoming_dir),
            "batch_size": 2,
            "min_stable_age_seconds": 0.0,
            "extensions": ["png"],
            "force_polling": True,
            "poll_delay_ms": 20,
            "watch_timeout_ms": 100,
        },
    )
    adapter = DirectoryWatchTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )
    submitter = _FakeWorkflowSubmitter()
    supervisor = TriggerSourceSupervisor(
        adapters={
            "directory-watch": _FakeProtocolAdapter(adapter_kind="directory-watch")
        },
        workflow_submitter=submitter,
    )

    adapter.start(trigger_source=trigger_source, event_handler=supervisor)
    try:
        _wait_for_directory_watch_adapter_running(adapter, "trigger-source-1")
        first_file = incoming_dir / "sample-a.png"
        first_file.write_bytes(b"image-a")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and submitter.last_request is None:
            time.sleep(0.01)
        health = adapter.get_health(trigger_source_id="trigger-source-1")
    finally:
        adapter.stop(trigger_source_id="trigger-source-1")

    assert submitter.last_request is not None
    payload = submitter.last_request.trigger_event.payload
    assert payload["file_count"] == 1
    assert payload["files"][0]["file_name"] == "sample-a.png"
    assert payload["primary_file_path"] == str(first_file.resolve())
    assert health["running"] is True
    assert health["submitted_count"] == 1
    assert Path(health["checkpoint_path"]).is_file()


def test_directory_watch_trigger_adapter_uses_checkpoint_to_avoid_reprocessing(
    tmp_path: Path,
) -> None:
    """验证 directory-watch adapter 重启后不会重复处理同一路径文件。"""

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    first_file = incoming_dir / "sample-a.png"

    trigger_source = _build_trigger_source(
        trigger_kind="directory-watch",
        input_binding_mapping={"request_batch": {"source": "payload.files"}},
        transport_config={
            "directory_path": str(incoming_dir),
            "batch_size": 1,
            "min_stable_age_seconds": 0.0,
            "extensions": ["png"],
            "force_polling": True,
            "poll_delay_ms": 20,
            "watch_timeout_ms": 100,
        },
    )
    first_adapter = DirectoryWatchTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )
    first_submitter = _FakeWorkflowSubmitter()
    first_supervisor = TriggerSourceSupervisor(
        adapters={
            "directory-watch": _FakeProtocolAdapter(adapter_kind="directory-watch")
        },
        workflow_submitter=first_submitter,
    )

    first_adapter.start(trigger_source=trigger_source, event_handler=first_supervisor)
    try:
        _wait_for_directory_watch_adapter_running(first_adapter, "trigger-source-1")
        first_file.write_bytes(b"image-a")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and first_submitter.last_request is None:
            time.sleep(0.01)
    finally:
        first_adapter.stop(trigger_source_id="trigger-source-1")

    assert first_submitter.last_request is not None

    second_adapter = DirectoryWatchTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )
    second_submitter = _FakeWorkflowSubmitter()
    second_supervisor = TriggerSourceSupervisor(
        adapters={
            "directory-watch": _FakeProtocolAdapter(adapter_kind="directory-watch")
        },
        workflow_submitter=second_submitter,
    )

    second_adapter.start(trigger_source=trigger_source, event_handler=second_supervisor)
    try:
        _wait_for_directory_watch_adapter_running(second_adapter, "trigger-source-1")
        time.sleep(0.1)
        first_file.write_bytes(b"image-a-updated")
        time.sleep(0.4)
        health = second_adapter.get_health(trigger_source_id="trigger-source-1")
    finally:
        second_adapter.stop(trigger_source_id="trigger-source-1")

    assert second_submitter.last_request is None
    assert health["known_identity_count"] == 1
    assert health["pending_path_count"] == 0
    assert health["submitted_count"] == 0


def test_directory_watch_trigger_adapter_rejects_sync_submit_mode(
    tmp_path: Path,
) -> None:
    """验证 directory-watch adapter 当前拒绝 sync submit_mode。"""

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    trigger_source = _build_trigger_source(
        trigger_kind="directory-watch",
        submit_mode="sync",
        transport_config={"directory_path": str(incoming_dir)},
    )
    adapter = DirectoryWatchTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )

    with pytest.raises(InvalidRequestError) as error_info:
        adapter.start(
            trigger_source=trigger_source,
            event_handler=TriggerSourceSupervisor(
                adapters={
                    "directory-watch": _FakeProtocolAdapter(
                        adapter_kind="directory-watch"
                    )
                },
                workflow_submitter=_FakeWorkflowSubmitter(),
            ),
        )

    assert error_info.value.details["submit_mode"] == "sync"


def _build_trigger_source(
    *,
    trigger_kind: str = "http-api",
    submit_mode: str = "async",
    input_binding_mapping: dict[str, object] | None = None,
    transport_config: dict[str, object] | None = None,
    match_rule: dict[str, object] | None = None,
    default_execution_metadata: dict[str, object] | None = None,
) -> WorkflowTriggerSource:
    """构建测试使用的 WorkflowTriggerSource。"""

    result_mode = "sync-reply" if submit_mode == "sync" else "accepted-then-query"
    ack_policy = (
        "ack-after-run-finished"
        if submit_mode == "sync"
        else "ack-after-run-created"
    )
    response_plan = build_trigger_response_plan(
        trigger_source_id="trigger-source-1",
        trigger_kind=trigger_kind,
        workflow_runtime_id="workflow-runtime-1",
        workflow_runtime_revision_id="revision-1",
        workflow_app_version_id="version-1",
        workflow_runtime_generation=1,
        expected_snapshot_fingerprint="snapshot-1",
        contract_fingerprint="contract-1",
        submit_mode=submit_mode,
        result_mode=result_mode,
        ack_policy=ack_policy,
        reply_timeout_seconds=(30 if trigger_kind == "local-shared-memory" else None),
        response_ack_timeout_seconds=(
            30.0 if trigger_kind == "local-shared-memory" else None
        ),
        selected_output_payload_types={"http_response": "response-body.v1"},
    )

    return WorkflowTriggerSource(
        trigger_source_id="trigger-source-1",
        project_id="project-1",
        display_name="HTTP Baseline Trigger",
        trigger_kind=trigger_kind,
        workflow_runtime_id="workflow-runtime-1",
        submit_mode=submit_mode,
        transport_config=dict(transport_config or {}),
        match_rule=dict(match_rule or {}),
        input_binding_mapping=(
            input_binding_mapping
            if input_binding_mapping is not None
            else {
                "request_image_base64": {"source": "payload.request.image"},
                "static_mode": {"value": "inspect"},
            }
        ),
        result_mapping={"result_bindings": ["http_response"]},
        default_execution_metadata=dict(default_execution_metadata or {}),
        ack_policy=ack_policy,
        result_mode=result_mode,
        idempotency_key_path="payload.request.id",
        metadata={
            TRIGGER_RESPONSE_PLAN_METADATA_KEY: response_plan.model_dump(mode="json")
        },
        created_at="2026-05-13T00:00:00Z",
        updated_at="2026-05-13T00:00:00Z",
    )


def _run_bgr24_deployment_trigger_smoke(
    *,
    return_diagnostics: bool,
) -> tuple[
    TriggerResultContract,
    "_DeploymentModelWorkflowRuntimeService",
    "_FakeLocalBufferWriter",
]:
    """执行 BGR24 ZeroMQ -> WorkflowRuntime -> DeploymentInstance smoke。"""

    default_execution_metadata = (
        {
            "return_timing_metadata_enabled": True,
            "return_node_timings_enabled": True,
        }
        if return_diagnostics
        else {}
    )
    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        submit_mode="sync",
        input_binding_mapping={
            "request_image_ref": {"source": "payload.request_image_ref"}
        },
        transport_config={
            "bind_endpoint": f"inproc://zeromq-bgr24-deployment-{uuid4().hex}",
            "default_input_binding": "request_image_ref",
        },
        default_execution_metadata=default_execution_metadata,
    )
    local_buffer_writer = _FakeLocalBufferWriter()
    runtime_service = _DeploymentModelWorkflowRuntimeService()
    adapter = _build_zeromq_adapter(local_buffer_writer)
    supervisor = TriggerSourceSupervisor(
        adapters={"zeromq-topic": _FakeProtocolAdapter(adapter_kind="zeromq-topic")},
        workflow_submitter=WorkflowSubmitter(runtime_service=runtime_service),
    )
    bgr24_bytes = bytes(range(12))

    with _install_fake_published_inference_module():
        trigger_result = adapter.handle_multipart_message(
            trigger_source=trigger_source,
            frames=[
                json.dumps(
                    {
                        "event_id": "event-bgr24",
                        "trace_id": "trace-bgr24",
                        "media_type": "image/raw",
                        "shape": [2, 2, 3],
                        "dtype": "uint8",
                        "layout": "HWC",
                        "pixel_format": "bgr24",
                        "metadata": {"line_id": "line-a"},
                    }
                ).encode("utf-8"),
                bgr24_bytes,
            ],
            event_handler=supervisor,
        )
    return trigger_result, runtime_service, local_buffer_writer


@dataclass(frozen=True)
class _PublishedInferenceRequest:
    """测试用 PublishedInferenceRequest 最小形状。"""

    task_type: str
    deployment_instance_id: str
    image_payload: dict[str, object]
    input_image_bytes: bytes | None = None
    score_threshold: float | None = None
    top_k: int | None = None
    mask_threshold: float | None = None
    keypoint_confidence_threshold: float | None = None
    auto_start_process: bool = False
    runtime_mode: str = "sync"
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    extra_options: dict[str, object] | None = None
    trace_id: str | None = None
    execution_scope_id: str | None = None


@dataclass(frozen=True)
class _PublishedInferenceResult:
    """测试用 PublishedInferenceResult 最小形状。"""

    task_type: str
    deployment_instance_id: str
    latency_ms: float | None
    image_width: int
    image_height: int
    detections: tuple[dict[str, object], ...] = ()
    categories: tuple[dict[str, object], ...] = ()
    top_category: dict[str, object] | None = None
    instances: tuple[dict[str, object], ...] = ()
    preview_image_payload: dict[str, object] | None = None
    runtime_session_info: dict[str, object] | None = None
    metadata: dict[str, object] | None = None


class _FakePublishedInferenceModule:
    """供 deployment_model helper 延迟 import 使用的轻量模块替身。"""

    PublishedInferenceRequest = _PublishedInferenceRequest
    PublishedInferenceResult = _PublishedInferenceResult


class _install_fake_published_inference_module:
    """临时注入轻量 deployments 模块，避免测试环境加载 torch。"""

    module_name = "backend.service.application.deployments"

    def __enter__(self):
        """安装 fake module。"""

        self.previous_module = sys.modules.get(self.module_name)
        sys.modules[self.module_name] = _FakePublishedInferenceModule()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        """恢复原始 module。"""

        _ = exc_type, exc, traceback
        if self.previous_module is None:
            sys.modules.pop(self.module_name, None)
            return
        sys.modules[self.module_name] = self.previous_module


class _DeploymentModelWorkflowRuntimeService:
    """调用 deployment model helper 的 WorkflowRuntimeService 替身。"""

    def __init__(self) -> None:
        """初始化 fake gateway 和最后一次请求。"""

        self.gateway = _CapturingPublishedInferenceGateway()
        self.last_request = None

    def invoke_workflow_app_runtime_with_response(
        self,
        workflow_runtime_id: str,
        request,
        *,
        created_by: str | None,
        execution_acquisition_mode: str = "wait",
    ) -> WorkflowRuntimeSyncInvokeResult:
        """把 WorkflowRuntime invoke 转成一次 deployment detection 节点调用。"""

        _ = created_by, execution_acquisition_mode
        self.last_request = request
        inference_result, _ = run_direct_model_inference(
            WorkflowNodeExecutionRequest(
                node_id="deployment-detect",
                node_definition=NodeDefinition(
                    node_type_id="core.model.detection",
                    display_name="Detection",
                    category="core.model.inference",
                    implementation_kind=NODE_IMPLEMENTATION_CORE,
                    runtime_kind=NODE_RUNTIME_WORKER_TASK,
                ),
                parameters={
                    "deployment_instance_id": "deployment-1",
                    "score_threshold": 0.3,
                },
                input_values={
                    "image": request.input_bindings["request_image_ref"],
                },
                execution_metadata=dict(request.execution_metadata),
                runtime_context=_FakeWorkflowServiceNodeRuntimeContext(self.gateway),
            ),
            task_type="detection",
        )
        workflow_metadata = dict(request.execution_metadata)
        if workflow_metadata.get("return_timing_metadata_enabled") is True:
            workflow_metadata["timings"] = {"worker_execute_ms": 3.5}
        if workflow_metadata.get("return_node_timings_enabled") is True:
            workflow_metadata["node_timings"] = [
                {
                    "node_id": "deployment-detect",
                    "node_type_id": "core.model.detection",
                    "runtime_kind": "worker-task",
                    "duration_ms": 3.5,
                }
            ]
        outputs = {
            "http_response": {
                "status_code": 200,
                "detections": {
                    "items": list(inference_result.detections),
                    "metadata": dict(inference_result.metadata),
                },
                "runtime_session_info": dict(inference_result.runtime_session_info),
            }
        }
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=WorkflowRun(
                workflow_run_id="workflow-run-bgr24",
                workflow_runtime_id=workflow_runtime_id,
                project_id="project-1",
                application_id="app-1",
                state="succeeded",
                outputs=outputs,
                metadata=workflow_metadata,
            ),
            raw_outputs=outputs,
        )


class _CapturingPublishedInferenceGateway:
    """记录 PublishedInferenceRequest 并返回固定 detection 结果。"""

    def __init__(self) -> None:
        """初始化最后一次请求。"""

        self.last_request: _PublishedInferenceRequest | None = None

    def infer(self, request: _PublishedInferenceRequest) -> _PublishedInferenceResult:
        """返回包含 diagnostics 的固定推理结果。"""

        self.last_request = request
        return _PublishedInferenceResult(
            task_type=request.task_type,
            deployment_instance_id=request.deployment_instance_id,
            latency_ms=2.25,
            image_width=2,
            image_height=2,
            detections=(
                {
                    "class_id": 0,
                    "class_name": "barcode",
                    "score": 0.91,
                    "bbox": [0.0, 0.0, 2.0, 2.0],
                },
            ),
            runtime_session_info={
                "runtime_backend": "tensorrt",
                "metadata": {
                    "runtime_infer_ms": 2.25,
                    "instance_id": "worker-0",
                },
            },
            metadata={
                "instance_id": "worker-0",
                "timings": {
                    "runtime_infer_ms": 2.25,
                },
            },
        )


class _FakeWorkflowServiceNodeRuntimeContext:
    """满足 service node runtime context 形状的测试替身。"""

    session_factory = None
    dataset_storage = None

    def __init__(self, gateway: _CapturingPublishedInferenceGateway) -> None:
        """保存 PublishedInferenceGateway。"""

        self._gateway = gateway

    def build_task_service(self):
        """占位 task service builder。"""

    def build_dataset_import_service(self):
        """占位 dataset import service builder。"""

    def build_dataset_export_task_service(self):
        """占位 dataset export service builder。"""

    def build_training_task_service(self, *, task_type: str, model_type: str):
        """占位 training service builder。"""

        _ = task_type, model_type

    def build_conversion_task_service(self, *, task_type: str, model_type: str):
        """占位 conversion service builder。"""

        _ = task_type, model_type

    def build_validation_session_service(self, *, task_type: str):
        """占位 validation session service builder。"""

        _ = task_type

    def build_evaluation_task_service(self, *, task_type: str):
        """占位 evaluation service builder。"""

        _ = task_type

    def build_deployment_service(self, *, task_type: str):
        """占位 deployment service builder。"""

        _ = task_type

    def build_inference_task_service(self, *, task_type: str):
        """占位 inference service builder。"""

        _ = task_type

    def require_deployment_process_supervisor(
        self, *, task_type: str, runtime_mode: str
    ):
        """占位 deployment supervisor resolver。"""

        _ = task_type, runtime_mode

    def build_published_inference_gateway(self) -> _CapturingPublishedInferenceGateway:
        """返回测试用 PublishedInferenceGateway。"""

        return self._gateway


def _wait_for_zeromq_adapter_running(
    adapter: ZeroMqTriggerAdapter,
    trigger_source_id: str,
) -> None:
    """等待 ZeroMQ adapter 进入 running 状态。"""

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        health = adapter.get_health(trigger_source_id=trigger_source_id)
        if health.get("running") is True:
            return
        time.sleep(0.01)
    raise AssertionError(adapter.get_health(trigger_source_id=trigger_source_id))


def _wait_for_directory_watch_adapter_running(
    adapter: DirectoryWatchTriggerAdapter,
    trigger_source_id: str,
) -> None:
    """等待 Directory Watch adapter 进入 running 状态。"""

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        health = adapter.get_health(trigger_source_id=trigger_source_id)
        if health.get("running") is True:
            return
        time.sleep(0.01)
    raise AssertionError(adapter.get_health(trigger_source_id=trigger_source_id))


@dataclass
class _FakeWorkflowSubmitter:
    """测试用 WorkflowSubmitter 替身。"""

    last_request: WorkflowTriggerSubmitRequest | None = None
    submit_count: int = 0

    def submit_event(
        self, request: WorkflowTriggerSubmitRequest
    ) -> WorkflowTriggerDispatchResult:
        """记录提交请求并返回 accepted 结果。"""

        self.last_request = request
        self.submit_count += 1
        return WorkflowTriggerDispatchResult(
            trigger_result=TriggerResultContract(
                trigger_source_id=request.trigger_source.trigger_source_id,
                event_id=request.trigger_event.event_id,
                state="accepted",
                workflow_run_id="workflow-run-1",
            )
        )


class _FakeSyncRuntimeService:
    """测试用同步 WorkflowRuntimeService 替身。"""

    def invoke_workflow_app_runtime_with_response(
        self,
        workflow_runtime_id: str,
        request,
        *,
        created_by: str | None,
        execution_acquisition_mode: str = "wait",
    ) -> WorkflowRuntimeSyncInvokeResult:
        """返回已脱敏 WorkflowRun 与未脱敏最终输出。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：同步调用请求。
        - created_by：创建主体 id。

        返回：
        - WorkflowRuntimeSyncInvokeResult：测试用同步调用结果。
        """

        _ = workflow_runtime_id, created_by, execution_acquisition_mode
        assert request.input_bindings["request_image_base64"] == "base64-image"
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=WorkflowRun(
                workflow_run_id="workflow-run-sync-1",
                workflow_runtime_id="workflow-runtime-1",
                project_id="project-1",
                application_id="app-1",
                state="succeeded",
                outputs={
                    "http_response": {
                        "status_code": 200,
                        "body": {
                            "code": 0,
                            "message": "ok",
                            "data": {
                                "annotated_image": {
                                    "transport_kind": "inline-base64",
                                    "image_base64_redacted": True,
                                }
                            },
                        },
                    }
                },
            ),
            raw_outputs={
                "http_response": {
                    "status_code": 200,
                    "body": {
                        "code": 0,
                        "message": "ok",
                        "data": {
                            "annotated_image": {
                                "transport_kind": "inline-base64",
                                "media_type": "image/png",
                                "image_base64": "YWJj",
                            },
                            "detections": [
                                {
                                    "bbox_xyxy": [0.0, 0.0, 1.0, 1.0],
                                    "score": 0.95,
                                    "class_name": "box",
                                }
                            ],
                        },
                    },
                }
            },
        )


class _CapturingSyncRuntimeService(_FakeSyncRuntimeService):
    """记录同步调用请求的 WorkflowRuntimeService 替身。

    字段：
    - last_request：最近一次同步调用请求。
    """

    def __init__(self) -> None:
        """初始化请求记录。"""

        self.last_request = None
        self.last_execution_acquisition_mode: str | None = None

    def invoke_workflow_app_runtime_with_response(
        self,
        workflow_runtime_id: str,
        request,
        *,
        created_by: str | None,
        execution_acquisition_mode: str = "wait",
    ) -> WorkflowRuntimeSyncInvokeResult:
        """记录请求并返回固定成功结果。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：同步调用请求。
        - created_by：调用主体 id。

        返回：
        - WorkflowRuntimeSyncInvokeResult：固定成功调用结果。
        """

        _ = workflow_runtime_id, created_by
        self.last_request = request
        self.last_execution_acquisition_mode = execution_acquisition_mode
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=WorkflowRun(
                workflow_run_id="workflow-run-sync-1",
                workflow_runtime_id="workflow-runtime-1",
                project_id="project-1",
                application_id="app-1",
                state="succeeded",
                outputs={"http_response": {"status_code": 200}},
            ),
            raw_outputs={"http_response": {"status_code": 200}},
        )


class _DiagnosticSyncRuntimeService:
    """返回含诊断 metadata 的同步 WorkflowRuntimeService 替身。"""

    def invoke_workflow_app_runtime_with_response(
        self,
        workflow_runtime_id: str,
        request,
        *,
        created_by: str | None,
        execution_acquisition_mode: str = "wait",
    ) -> WorkflowRuntimeSyncInvokeResult:
        """返回带 timings 和 node_timings 的 WorkflowRun。"""

        _ = workflow_runtime_id, created_by, execution_acquisition_mode
        metadata = dict(request.execution_metadata)
        metadata["timings"] = {"worker_execute_ms": 12.5}
        metadata["node_timings"] = [
            {
                "node_id": "detect",
                "node_type_id": "core.model.detection",
                "runtime_kind": "worker-task",
                "duration_ms": 10.0,
            }
        ]
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=WorkflowRun(
                workflow_run_id="workflow-run-sync-1",
                workflow_runtime_id="workflow-runtime-1",
                project_id="project-1",
                application_id="app-1",
                state="succeeded",
                outputs={"http_response": {"status_code": 200}},
                metadata=metadata,
            ),
            raw_outputs={"http_response": {"status_code": 200}},
        )


class _RejectingWorkflowSubmitter:
    """返回创建前失败结果的 WorkflowSubmitter 替身。"""

    def submit_event(
        self, request: WorkflowTriggerSubmitRequest
    ) -> WorkflowTriggerDispatchResult:
        """模拟 WorkflowRun 创建前失败。

        参数：
        - request：TriggerSource 提交请求。

        返回：
        - TriggerResultContract：失败结果。
        """

        return WorkflowTriggerDispatchResult(
            trigger_result=TriggerResultContract(
                trigger_source_id=request.trigger_source.trigger_source_id,
                event_id=request.trigger_event.event_id,
                state="failed",
                error_message="runtime not running",
            )
        )


class _FakeProtocolAdapter:
    """测试用协议 adapter。"""

    def __init__(self, *, adapter_kind: str = "http-api") -> None:
        """初始化测试 adapter。"""

        self.adapter_kind = adapter_kind
        self.event_handler = None
        self.stopped_trigger_source_id: str | None = None

    def start(self, *, trigger_source: WorkflowTriggerSource, event_handler) -> None:
        """保存事件处理器。"""

        _ = trigger_source
        self.event_handler = event_handler

    def stop(self, *, trigger_source_id: str) -> None:
        """记录停止的 TriggerSource id。"""

        self.stopped_trigger_source_id = trigger_source_id

    def get_health(self, *, trigger_source_id: str) -> dict[str, object]:
        """返回测试 adapter health。"""

        return {
            "trigger_source_id": trigger_source_id,
            "running": self.event_handler is not None,
        }

    def emit(
        self, *, trigger_source: WorkflowTriggerSource, raw_event: RawTriggerEvent
    ) -> TriggerResultContract:
        """向保存的事件处理器发送事件。"""

        assert self.event_handler is not None
        return self.event_handler.handle_trigger_event(
            trigger_source=trigger_source, raw_event=raw_event
        )


class _FakeLocalBufferWriter:
    """测试用 LocalBufferBroker 写入器。"""

    def __init__(self) -> None:
        """初始化释放记录。"""

        self.released_leases: list[str] = []
        self.write_calls: list[dict[str, object]] = []

    def write_bytes(
        self,
        *,
        content: bytes,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> object:
        """返回固定 BufferRef 写入结果。"""

        self.write_calls.append(
            {
                "content": content,
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "media_type": media_type,
                "shape": shape,
                "dtype": dtype,
                "layout": layout,
                "pixel_format": pixel_format,
                "ttl_seconds": ttl_seconds,
                "trace_id": trace_id,
            }
        )
        return SimpleNamespace(
            buffer_ref=BufferRef(
                buffer_id="buffer-1",
                lease_id="lease-1",
                arena_id="local-buffer-main",
                descriptor_index=0,
                descriptor_generation=1,
                broker_epoch="epoch-1",
                offset=0,
                content_length=len(content),
                allocation_capacity_bytes=1024 * 1024,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
                media_type=media_type,
            )
        )

    def release(self, lease_id: str) -> None:
        """记录释放的 lease。"""

        self.released_leases.append(lease_id)


class _FakeResultBufferWriter(_FakeLocalBufferWriter):
    """测试 ZeroMQ output reader guard 与条件释放的内存写入器。"""

    def __init__(self, content: bytes) -> None:
        super().__init__()
        self.content = content
        self.guard_enter_count = 0
        self.guard_exit_count = 0
        self.released_receipts: list[LeaseOwnershipReceipt] = []

    @contextmanager
    def acquire_buffer_reader_guard(
        self,
        *,
        buffer_ref: BufferRef,
        deadline_ns: int,
    ):
        """记录 reader guard 生命周期。"""

        assert buffer_ref.lease_id == "result-lease-1"
        assert deadline_ns > monotonic_ns()
        self.guard_enter_count += 1
        try:
            yield
        finally:
            self.guard_exit_count += 1

    def read_buffer_ref_view(self, buffer_ref: BufferRef) -> memoryview:
        """返回图片结果的只读 view。"""

        assert buffer_ref.content_length == len(self.content)
        return memoryview(self.content)

    def conditional_release(self, *, receipt: LeaseOwnershipReceipt) -> str:
        """记录完整 identity fence 释放。"""

        self.released_receipts.append(receipt)
        return "released"


def _build_prepared_zeromq_result(content: bytes) -> PreparedTriggerResult:
    """构造两个逻辑 attachment 共享一个物理图片的 prepared result。"""

    deadline_ns = monotonic_ns() + 10_000_000_000
    buffer_ref = BufferRef(
        buffer_id="result-buffer-1",
        lease_id="result-lease-1",
        arena_id="local-buffer-main",
        descriptor_index=1,
        descriptor_generation=1,
        broker_epoch="epoch-1",
        offset=0,
        content_length=len(content),
        allocation_capacity_bytes=1024 * 1024,
        media_type="image/png",
    )
    receipt = LeaseOwnershipReceipt(
        arena_id=buffer_ref.arena_id,
        descriptor_index=buffer_ref.descriptor_index,
        descriptor_generation=buffer_ref.descriptor_generation,
        broker_epoch=buffer_ref.broker_epoch,
        lease_id=buffer_ref.lease_id,
        buffer_id=buffer_ref.buffer_id,
        lease_token="1" * 32,
        owner_token="2" * 32,
        owner_kind="workflow-trigger-response",
        owner_id="zeromq:trigger-source-1:event-result",
        deadline_ns=deadline_ns,
        offset=buffer_ref.offset,
        content_length=buffer_ref.content_length,
        allocation_capacity_bytes=buffer_ref.allocation_capacity_bytes,
        layout_fingerprint="3" * 64,
        guard_path="data/buffers/local-buffer-main.guard",
        publication_guard_offset=0,
        writer_guard_offset=1,
        reader_guard_offset=2,
        reader_guard_slots=8,
    )
    return PreparedTriggerResult(
        selected_results={"result": {"ok": True}},
        attachments=(
            PreparedLogicalAttachment(
                attachment_id="attachment-1",
                binding_id="image-a",
                item_index=0,
                binding_payload_type_id="image-ref.v1",
                payload_id="physical-1",
            ),
            PreparedLogicalAttachment(
                attachment_id="attachment-2",
                binding_id="image-b",
                item_index=0,
                binding_payload_type_id="image-ref.v1",
                payload_id="physical-1",
            ),
        ),
        physical_payloads=(
            PreparedPhysicalPayload(
                payload_id="physical-1",
                delivery_kind="local-buffer",
                media_type="image/png",
                content_length=len(content),
                checksum_algorithm="crc32",
                checksum="00000000",
                buffer_ref=buffer_ref.model_dump(mode="json"),
                ownership_receipt=receipt.model_dump(mode="json"),
            ),
        ),
    )


def _build_buffer_ref_payload(*, lease_id: str = "lease-1") -> dict[str, object]:
    """构造测试用 BufferRef payload。

    参数：
    - lease_id：测试使用的 lease id。

    返回：
    - dict[str, object]：JSON 可序列化的 BufferRef payload。
    """

    return BufferRef(
        buffer_id="buffer-1",
        lease_id=lease_id,
        arena_id="local-buffer-main",
        descriptor_index=0,
        descriptor_generation=1,
        broker_epoch="epoch-1",
        offset=0,
        content_length=10,
        allocation_capacity_bytes=1024 * 1024,
        media_type="image/png",
    ).model_dump(mode="json")

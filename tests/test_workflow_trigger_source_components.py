"""WorkflowTriggerSource 协议中立组件测试。"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import zmq

from backend.contracts.buffers.buffer_ref import BufferRef
from backend.contracts.workflows import TriggerResultContract
from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
)
from backend.nodes.core_nodes.support.deployment_model import run_direct_model_inference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.contracts import WorkflowNodeExecutionRequest
from backend.service.application.workflows.trigger_sources import (
    InputBindingMapper,
    RawTriggerEvent,
    TriggerEventNormalizer,
    WorkflowResultDispatcher,
)
from backend.service.application.workflows.runtime_service import WorkflowRuntimeSyncInvokeResult
from backend.service.application.workflows.trigger_sources.trigger_source_supervisor import (
    TriggerSourceSupervisor,
)
from backend.service.application.workflows.trigger_sources.workflow_submitter import (
    WorkflowSubmitter,
    WorkflowTriggerSubmitRequest,
)
from backend.service.application.workflows.trigger_sources.zeromq_transport import (
    DEFAULT_ZEROMQ_BUFFER_TTL_SECONDS,
    resolve_zeromq_buffer_ttl_seconds,
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


@pytest.mark.parametrize("invalid_value", [0, -1, True, "nan", "inf", "invalid"])
def test_zeromq_buffer_ttl_requires_positive_finite_number(invalid_value: object) -> None:
    """验证 ZeroMQ buffer TTL 默认存在且拒绝非正数和非有限数值。"""

    assert resolve_zeromq_buffer_ttl_seconds({}) == DEFAULT_ZEROMQ_BUFFER_TTL_SECONDS
    with pytest.raises(InvalidRequestError, match="buffer_ttl_seconds"):
        resolve_zeromq_buffer_ttl_seconds({"buffer_ttl_seconds": invalid_value})


def test_trigger_event_normalizer_and_input_binding_mapper_resolve_payload_paths() -> (
    None
):
    """验证事件标准化和 input binding 映射可以读取 payload 路径。"""

    trigger_source = _build_trigger_source()
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

    trigger_source = _build_trigger_source()
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
    assert trigger_result.response_payload["result_binding"] == "http_response"
    assert trigger_result.response_payload["result"] == {"status_code": 200}


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

    result_body = trigger_result.response_payload["result"]["body"]
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
        WorkflowTriggerSubmitRequest(trigger_source=trigger_source, trigger_event=trigger_event)
    )

    execution_metadata = runtime_service.last_request.execution_metadata
    assert trigger_result.state == "succeeded"
    assert execution_metadata["trace_level"] == "none"
    assert execution_metadata["retain_trace_enabled"] is False
    assert execution_metadata["retain_node_records_enabled"] is False
    assert execution_metadata["workflow_run_record_mode"] == "minimal"
    assert execution_metadata["return_timing_metadata_enabled"] is False
    assert execution_metadata["return_node_timings_enabled"] is False


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
        WorkflowTriggerSubmitRequest(trigger_source=trigger_source, trigger_event=trigger_event)
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
        WorkflowTriggerSubmitRequest(trigger_source=trigger_source, trigger_event=trigger_event)
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
            "buffer_ttl_seconds": 5,
            "pool_name": "image-640x640",
        },
    )
    local_buffer_writer = _FakeLocalBufferWriter()
    adapter = ZeroMqTriggerAdapter(local_buffer_writer=local_buffer_writer)
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
    assert image_payload["buffer_ref"]["format_id"] == "amvision.buffer-ref.v1"
    assert image_payload["buffer_ref"]["media_type"] == "image/png"
    assert local_buffer_writer.write_calls[0]["pool_name"] == "image-640x640"


def test_zeromq_bgr24_trigger_invokes_deployment_model_without_diagnostics_by_default() -> None:
    """验证 BGR24 高速触发默认不返回 workflow 和 deployment 诊断字段。"""

    trigger_result, runtime_service, local_buffer_writer = _run_bgr24_deployment_trigger_smoke(
        return_diagnostics=False
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
    assert runtime_service.gateway.last_request.image_payload["transport_kind"] == "buffer"
    assert runtime_service.gateway.last_request.image_payload["buffer_ref"]["media_type"] == "image/raw"
    result_payload = trigger_result.response_payload["result"]
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
    result_payload = trigger_result.response_payload["result"]
    assert result_payload["detections"]["metadata"]["timings"]["runtime_infer_ms"] == 2.25
    assert result_payload["runtime_session_info"]["metadata"]["runtime_infer_ms"] == 2.25


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
    adapter = ZeroMqTriggerAdapter(local_buffer_writer=_FakeLocalBufferWriter())
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
    adapter = ZeroMqTriggerAdapter(local_buffer_writer=local_buffer_writer)
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
    assert local_buffer_writer.released_leases == [("lease-1", None)]


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
    adapter = ZeroMqTriggerAdapter(local_buffer_writer=_FakeLocalBufferWriter())
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


def test_zeromq_trigger_adapter_allows_envelope_only_event_without_input_frame() -> None:
    """验证 ZeroMQ 也可以只发事件 envelope，用于图内自行取图的 workflow。"""

    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        input_binding_mapping={},
    )
    adapter = ZeroMqTriggerAdapter(local_buffer_writer=_FakeLocalBufferWriter())
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

        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
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
    adapter = DirectoryPollTriggerAdapter(dataset_storage_root_dir=str(tmp_path / "data"))
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
    adapter = DirectoryPollTriggerAdapter(dataset_storage_root_dir=str(tmp_path / "data"))

    with pytest.raises(InvalidRequestError) as error_info:
        adapter.start(
            trigger_source=trigger_source,
            event_handler=TriggerSourceSupervisor(
                adapters={
                    "directory-poll": _FakeProtocolAdapter(adapter_kind="directory-poll")
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
    adapter = DirectoryWatchTriggerAdapter(dataset_storage_root_dir=str(tmp_path / "data"))
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
    adapter = DirectoryWatchTriggerAdapter(dataset_storage_root_dir=str(tmp_path / "data"))

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
        result_mapping={"result_binding": "http_response"},
        default_execution_metadata=dict(default_execution_metadata or {}),
        idempotency_key_path="payload.request.id",
        created_at="2026-05-13T00:00:00Z",
        updated_at="2026-05-13T00:00:00Z",
    )


def _run_bgr24_deployment_trigger_smoke(
    *,
    return_diagnostics: bool,
) -> tuple[TriggerResultContract, "_DeploymentModelWorkflowRuntimeService", "_FakeLocalBufferWriter"]:
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
            "buffer_ttl_seconds": 5,
            "pool_name": "image-raw-bgr24",
        },
        default_execution_metadata=default_execution_metadata,
    )
    local_buffer_writer = _FakeLocalBufferWriter()
    runtime_service = _DeploymentModelWorkflowRuntimeService()
    adapter = ZeroMqTriggerAdapter(local_buffer_writer=local_buffer_writer)
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
    ) -> WorkflowRuntimeSyncInvokeResult:
        """把 WorkflowRuntime invoke 转成一次 deployment detection 节点调用。"""

        _ = created_by
        self.last_request = request
        inference_result, _ = run_direct_model_inference(
            WorkflowNodeExecutionRequest(
                node_id="deployment-detect",
                node_definition=NodeDefinition(
                    node_type_id="core.model.detection",
                    display_name="Detection",
                    category="model.inference",
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

    def require_deployment_process_supervisor(self, *, task_type: str, runtime_mode: str):
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

    def submit_event(
        self, request: WorkflowTriggerSubmitRequest
    ) -> TriggerResultContract:
        """记录提交请求并返回 accepted 结果。"""

        self.last_request = request
        return TriggerResultContract(
            trigger_source_id=request.trigger_source.trigger_source_id,
            event_id=request.trigger_event.event_id,
            state="accepted",
            workflow_run_id="workflow-run-1",
        )


class _FakeSyncRuntimeService:
    """测试用同步 WorkflowRuntimeService 替身。"""

    def invoke_workflow_app_runtime_with_response(
        self,
        workflow_runtime_id: str,
        request,
        *,
        created_by: str | None,
    ) -> WorkflowRuntimeSyncInvokeResult:
        """返回已脱敏 WorkflowRun 与未脱敏最终输出。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：同步调用请求。
        - created_by：创建主体 id。

        返回：
        - WorkflowRuntimeSyncInvokeResult：测试用同步调用结果。
        """

        _ = workflow_runtime_id, created_by
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

    def invoke_workflow_app_runtime_with_response(
        self,
        workflow_runtime_id: str,
        request,
        *,
        created_by: str | None,
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
    ) -> WorkflowRuntimeSyncInvokeResult:
        """返回带 timings 和 node_timings 的 WorkflowRun。"""

        _ = workflow_runtime_id, created_by
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
    ) -> TriggerResultContract:
        """模拟 WorkflowRun 创建前失败。

        参数：
        - request：TriggerSource 提交请求。

        返回：
        - TriggerResultContract：失败结果。
        """

        return TriggerResultContract(
            trigger_source_id=request.trigger_source.trigger_source_id,
            event_id=request.trigger_event.event_id,
            state="failed",
            error_message="runtime not running",
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

        self.released_leases: list[tuple[str, str | None]] = []
        self.write_calls: list[dict[str, object]] = []

    def write_bytes(
        self,
        *,
        content: bytes,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        pool_name: str | None = None,
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
                "pool_name": pool_name,
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
                path="data/buffers/pool-001.dat",
                offset=0,
                size=len(content),
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
                media_type=media_type,
                broker_epoch="epoch-1",
                generation=1,
            )
        )

    def release(self, lease_id: str, *, pool_name: str | None = None) -> None:
        """记录释放的 lease。

        参数：
        - lease_id：待释放的 lease id。
        - pool_name：可选 pool 名称。
        """

        self.released_leases.append((lease_id, pool_name))


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
        path="data/buffers/pool-001.dat",
        offset=0,
        size=10,
        media_type="image/png",
        broker_epoch="epoch-1",
        generation=1,
    ).model_dump(mode="json")

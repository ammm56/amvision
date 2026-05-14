"""WorkflowTriggerSource 协议中立组件测试。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
import zmq

from backend.contracts.buffers.buffer_ref import BufferRef
from backend.contracts.workflows import TriggerResultContract
from backend.service.application.errors import InvalidRequestError
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
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.integrations.zeromq import ZeroMqTriggerAdapter


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
        "request_image": "base64-image",
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

    assert error_info.value.details["binding_id"] == "request_image"


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

    trigger_result = WorkflowSubmitter(runtime_service=_FakeSyncRuntimeService()).submit_event(
        WorkflowTriggerSubmitRequest(trigger_source=trigger_source, trigger_event=trigger_event)
    )

    result_body = trigger_result.response_payload["result"]["body"]
    assert trigger_result.state == "succeeded"
    assert result_body["data"]["detections"][0]["class_name"] == "box"
    assert result_body["data"]["annotated_image"]["image_base64"] == "YWJj"
    assert "image_base64_redacted" not in result_body["data"]["annotated_image"]


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
        input_binding_mapping={"request_image": {"source": "payload.request_image"}},
        transport_config={
            "bind_endpoint": f"inproc://zeromq-trigger-test-{uuid4().hex}",
            "default_input_binding": "request_image",
            "buffer_ttl_seconds": 5,
        },
    )
    adapter = ZeroMqTriggerAdapter(local_buffer_writer=_FakeLocalBufferWriter())
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
    image_payload = payload["request_image"]
    assert image_payload["transport_kind"] == "buffer"
    assert image_payload["buffer_ref"]["format_id"] == "amvision.buffer-ref.v1"
    assert image_payload["buffer_ref"]["media_type"] == "image/png"


def test_zeromq_trigger_adapter_serves_req_rep_message() -> None:
    """验证 ZeroMQ adapter 线程可以接收 REQ multipart 并返回 JSON reply。"""

    endpoint = f"inproc://zeromq-trigger-live-{uuid4().hex}"
    trigger_source = _build_trigger_source(
        trigger_kind="zeromq-topic",
        input_binding_mapping={"request_image": {"source": "payload.request_image"}},
        transport_config={
            "bind_endpoint": endpoint,
            "default_input_binding": "request_image",
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


def _build_trigger_source(
    *,
    trigger_kind: str = "http-api",
    submit_mode: str = "async",
    input_binding_mapping: dict[str, object] | None = None,
    transport_config: dict[str, object] | None = None,
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
        input_binding_mapping=input_binding_mapping
        or {
            "request_image": {"source": "payload.request.image"},
            "static_mode": {"value": "inspect"},
        },
        result_mapping={"result_binding": "http_response"},
        idempotency_key_path="payload.request.id",
        created_at="2026-05-13T00:00:00Z",
        updated_at="2026-05-13T00:00:00Z",
    )


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
        assert request.input_bindings["request_image"] == "base64-image"
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

        _ = (content, owner_kind, owner_id, pool_name, ttl_seconds, trace_id)
        return SimpleNamespace(
            buffer_ref=BufferRef(
                buffer_id="buffer-1",
                lease_id="lease-1",
                path="data/buffers/pool-001.dat",
                offset=0,
                size=10,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
                media_type=media_type,
                broker_epoch="epoch-1",
                generation=1,
            )
        )

"""PublishedInferenceGateway 事件 dispatcher 与 workflow 节点接入测试。"""

from __future__ import annotations

import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep
from types import SimpleNamespace

from backend.contracts.buffers import BufferRef
from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.nodes.core_nodes.model.deployment.deployment_detection import (
    _deployment_detection_handler,
)
from backend.service.application.deployments import (
    DetectionDeploymentPublishedInferenceGateway,
    PublishedInferenceGatewayClient,
    PublishedInferenceGatewayDispatcher,
    PublishedInferenceGatewayEventChannel,
    PublishedInferenceRequest,
    PublishedInferenceResult,
)
from backend.service.application.models.inference.detection_inference_task_service import (
    run_detection_inference_task,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessExecution,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionDetection,
    DetectionPredictionExecutionResult,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE,
    list_registered_execution_cleanups,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from tests.api_test_support import build_test_jpeg_bytes


def test_published_inference_gateway_client_calls_parent_supervisor_with_event_dispatcher() -> (
    None
):
    """验证 gateway client 通过父进程事件 dispatcher 调用 backend-service 持有的 supervisor。"""

    context = multiprocessing.get_context("spawn")
    fake_supervisor = _FakeDeploymentSupervisor()
    gateway = DetectionDeploymentPublishedInferenceGateway(
        deployment_service=_FakeDeploymentService(),
        deployment_process_supervisor=fake_supervisor,
    )
    channel = PublishedInferenceGatewayEventChannel(
        request_queue=context.Queue(),
        response_queue=context.Queue(),
        request_timeout_seconds=3.0,
    )
    dispatcher = PublishedInferenceGatewayDispatcher(
        channel=channel,
        gateway=gateway,
    )
    dispatcher.start()
    try:
        client = PublishedInferenceGatewayClient(channel)
        buffer_ref = _build_buffer_ref()

        result = client.infer(
            PublishedInferenceRequest(
                task_type="detection",
                deployment_instance_id="deployment-1",
                image_payload={
                    "transport_kind": "buffer",
                    "buffer_ref": buffer_ref.model_dump(mode="json"),
                    "media_type": "image/jpeg",
                    "width": 64,
                    "height": 64,
                },
                score_threshold=0.41,
                auto_start_process=True,
            )
        )

        assert result.detections[0]["class_name"] == "defect"
        assert result.task_type == "detection"
        assert fake_supervisor.start_calls == ["deployment-1"]
        assert fake_supervisor.last_prediction_request is not None
        assert fake_supervisor.last_prediction_request.input_image_bytes is None
        assert fake_supervisor.last_prediction_request.input_image_payload is not None
        assert (
            fake_supervisor.last_prediction_request.input_image_payload[
                "transport_kind"
            ]
            == "buffer"
        )
        assert (
            fake_supervisor.last_prediction_request.input_image_payload["buffer_ref"][
                "lease_id"
            ]
            == "lease-1"
        )
        assert fake_supervisor.last_prediction_request.score_threshold == 0.41
    finally:
        client.close()
        dispatcher.stop()
        channel.request_queue.close()
        channel.request_queue.join_thread()
        channel.response_queue.close()
        channel.response_queue.join_thread()


def test_published_inference_gateway_client_correlates_out_of_order_responses() -> None:
    """验证并发请求乱序完成时，每个调用仍收到自己的响应。"""

    context = multiprocessing.get_context("spawn")
    channel = PublishedInferenceGatewayEventChannel(
        request_queue=context.Queue(),
        response_queue=context.Queue(),
        request_timeout_seconds=3.0,
    )
    dispatcher = PublishedInferenceGatewayDispatcher(
        channel=channel,
        gateway=_OutOfOrderPublishedInferenceGateway(),
    )
    dispatcher.start()
    client = PublishedInferenceGatewayClient(channel)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            slow_future = executor.submit(client.infer, _build_gateway_request("slow"))
            fast_future = executor.submit(client.infer, _build_gateway_request("fast"))
            slow_result = slow_future.result(timeout=3.0)
            fast_result = fast_future.result(timeout=3.0)

        assert slow_result.metadata["trace_id"] == "slow"
        assert fast_result.metadata["trace_id"] == "fast"
    finally:
        client.close()
        dispatcher.stop()
        channel.request_queue.close()
        channel.request_queue.join_thread()
        channel.response_queue.close()
        channel.response_queue.join_thread()


def test_published_inference_gateway_reuses_process_context_within_execution_scope() -> (
    None
):
    """验证同一 Workflow Run 的逐项推理只解析并检查一次 deployment。"""

    deployment_service = _FakeDeploymentService()
    deployment_supervisor = _FakeDeploymentSupervisor()
    gateway = DetectionDeploymentPublishedInferenceGateway(
        deployment_service=deployment_service,
        deployment_process_supervisor=deployment_supervisor,
    )
    request = PublishedInferenceRequest(
        task_type="detection",
        deployment_instance_id="deployment-1",
        image_payload={
            "transport_kind": "buffer",
            "buffer_ref": _build_buffer_ref().model_dump(mode="json"),
            "media_type": "image/jpeg",
            "width": 64,
            "height": 64,
        },
        auto_start_process=True,
        execution_scope_id="workflow-run-1",
    )

    first_result = gateway.infer(request)
    second_result = gateway.infer(request)

    assert first_result.detections == second_result.detections
    assert deployment_service.resolve_calls == 1
    assert deployment_supervisor.ensure_calls == 1
    assert deployment_supervisor.status_calls == 3
    assert deployment_supervisor.inference_calls == 2
    assert (
        first_result.metadata["timings"]["published_inference_gateway_context_reused"]
        is False
    )
    assert (
        second_result.metadata["timings"]["published_inference_gateway_context_reused"]
        is True
    )


def test_published_inference_gateway_prepares_concurrent_scope_once() -> None:
    """验证同一 run 首批并发分支通过 single-flight 只准备一次 deployment。"""

    class _SlowDeploymentService(_FakeDeploymentService):
        def resolve_process_config(self, deployment_instance_id: str) -> SimpleNamespace:
            sleep(0.05)
            return super().resolve_process_config(deployment_instance_id)

    deployment_service = _SlowDeploymentService()
    deployment_supervisor = _FakeDeploymentSupervisor()
    gateway = DetectionDeploymentPublishedInferenceGateway(
        deployment_service=deployment_service,
        deployment_process_supervisor=deployment_supervisor,
    )
    request = PublishedInferenceRequest(
        task_type="detection",
        deployment_instance_id="deployment-1",
        image_payload={
            "transport_kind": "buffer",
            "buffer_ref": _build_buffer_ref().model_dump(mode="json"),
            "media_type": "image/jpeg",
            "width": 64,
            "height": 64,
        },
        auto_start_process=True,
        execution_scope_id="workflow-run-first-concurrent",
    )

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = tuple(executor.map(gateway.infer, (request, request, request)))

    assert len(results) == 3
    assert deployment_service.resolve_calls == 1
    assert deployment_supervisor.ensure_calls == 1
    assert deployment_supervisor.inference_calls == 3


def test_yolox_detection_node_writes_memory_image_to_local_buffer_before_gateway_call() -> (
    None
):
    """验证 detection 节点会把 execution memory 图片转换为 BufferRef 后调用 gateway。"""

    source_bytes = build_test_jpeg_bytes()
    image_registry = ExecutionImageRegistry()
    registered_image = image_registry.register_image_bytes(
        content=source_bytes,
        media_type="image/jpeg",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )
    fake_writer = _FakeLocalBufferWriter()
    fake_gateway = _FakePublishedInferenceGateway()
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=object(),
        local_buffer_reader=fake_writer,
        published_inference_gateway=fake_gateway,
    )

    output = _deployment_detection_handler(
        WorkflowNodeExecutionRequest(
            node_id="detect",
            node_definition=object(),
            parameters={
                "deployment_instance_id": "deployment-1",
                "score_threshold": 0.52,
            },
            input_values={
                "image": build_memory_image_payload(
                    image_handle=registered_image.image_handle,
                    media_type="image/jpeg",
                    width=64,
                    height=64,
                )
            },
            execution_metadata={
                "execution_image_registry": image_registry,
                "local_buffer_reader": fake_writer,
                "workflow_run_id": "run-1",
                WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY: 90.0,
            },
            runtime_context=runtime_context,
        )
    )

    assert output["detections"]["items"][0]["class_name"] == "defect"
    assert fake_writer.last_content == source_bytes
    assert fake_writer.last_owner_id == "run-1:detect"
    assert fake_writer.last_ttl_seconds == 120.0
    assert fake_gateway.last_request is not None
    assert fake_gateway.last_request.input_image_bytes is None
    assert fake_gateway.last_request.image_payload["transport_kind"] == "buffer"
    assert (
        fake_gateway.last_request.image_payload["buffer_ref"]["lease_id"]
        == "lease-memory"
    )
    assert fake_gateway.last_request.score_threshold == 0.52


def test_yolox_detection_node_releases_local_buffer_lease_after_gateway_call() -> None:
    """验证 detection 节点完成同步推理后会立即释放临时 LocalBufferBroker lease。"""

    source_bytes = build_test_jpeg_bytes()
    image_registry = ExecutionImageRegistry()
    registered_image = image_registry.register_image_bytes(
        content=source_bytes,
        media_type="image/jpeg",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )
    fake_writer = _FakeLocalBufferWriter()
    fake_gateway = _FakePublishedInferenceGateway()
    execution_metadata = {
        "execution_image_registry": image_registry,
        "local_buffer_reader": fake_writer,
        "workflow_run_id": "run-1",
    }

    _deployment_detection_handler(
        WorkflowNodeExecutionRequest(
            node_id="detect",
            node_definition=object(),
            parameters={"deployment_instance_id": "deployment-1"},
            input_values={
                "image": build_memory_image_payload(
                    image_handle=registered_image.image_handle,
                    media_type="image/jpeg",
                    width=64,
                    height=64,
                )
            },
            execution_metadata=execution_metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=object(),
                dataset_storage=object(),
                local_buffer_reader=fake_writer,
                published_inference_gateway=fake_gateway,
            ),
        )
    )

    assert fake_writer.release_calls == [("lease-memory", "image-test")]
    assert not list_registered_execution_cleanups(execution_metadata)


def test_yolox_detection_node_registers_cleanup_when_local_buffer_release_fails() -> (
    None
):
    """验证临时 LocalBufferBroker lease 立即释放失败时会登记 workflow cleanup 兜底。"""

    source_bytes = build_test_jpeg_bytes()
    image_registry = ExecutionImageRegistry()
    registered_image = image_registry.register_image_bytes(
        content=source_bytes,
        media_type="image/jpeg",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )
    fake_writer = _FakeLocalBufferWriter()
    fake_writer.fail_release = True
    fake_gateway = _FakePublishedInferenceGateway()
    execution_metadata = {
        "execution_image_registry": image_registry,
        "local_buffer_reader": fake_writer,
        "workflow_run_id": "run-1",
    }

    _deployment_detection_handler(
        WorkflowNodeExecutionRequest(
            node_id="detect",
            node_definition=object(),
            parameters={"deployment_instance_id": "deployment-1"},
            input_values={
                "image": build_memory_image_payload(
                    image_handle=registered_image.image_handle,
                    media_type="image/jpeg",
                    width=64,
                    height=64,
                )
            },
            execution_metadata=execution_metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=object(),
                dataset_storage=object(),
                local_buffer_reader=fake_writer,
                published_inference_gateway=fake_gateway,
            ),
        )
    )

    cleanup_items = list_registered_execution_cleanups(execution_metadata)
    assert fake_writer.release_calls == [("lease-memory", "image-test")]
    assert len(cleanup_items) == 1
    assert (
        cleanup_items[0].resource_kind
        == WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE
    )
    assert cleanup_items[0].resource_id == "lease-memory"
    assert cleanup_items[0].metadata == {"pool_name": "image-test"}


def test_run_detection_inference_task_preserves_input_image_payload() -> None:
    """验证统一推理执行入口不会丢掉跨进程图片载荷。"""

    fake_supervisor = _FakeDeploymentSupervisor()

    run_detection_inference_task(
        deployment_process_supervisor=fake_supervisor,
        process_config=SimpleNamespace(deployment_instance_id="deployment-1"),
        input_uri=None,
        input_image_bytes=None,
        input_image_payload={
            "transport_kind": "buffer",
            "buffer_ref": _build_buffer_ref().model_dump(mode="json"),
            "media_type": "image/jpeg",
            "width": 64,
            "height": 64,
        },
        score_threshold=0.37,
        save_result_image=False,
        return_preview_image_base64=False,
        extra_options={},
    )

    assert fake_supervisor.last_prediction_request is not None
    assert fake_supervisor.last_prediction_request.input_uri is None
    assert fake_supervisor.last_prediction_request.input_image_bytes is None
    assert fake_supervisor.last_prediction_request.input_image_payload is not None
    assert (
        fake_supervisor.last_prediction_request.input_image_payload["transport_kind"]
        == "buffer"
    )
    assert (
        fake_supervisor.last_prediction_request.input_image_payload["buffer_ref"][
            "lease_id"
        ]
        == "lease-1"
    )


class _FakeDeploymentService:
    """返回固定 process_config 的测试 deployment service。"""

    def __init__(self) -> None:
        """初始化解析计数。"""

        self.resolve_calls = 0

    def resolve_process_config(self, deployment_instance_id: str) -> SimpleNamespace:
        """返回测试 process_config。"""

        self.resolve_calls += 1
        return SimpleNamespace(deployment_instance_id=deployment_instance_id)


class _FakeDeploymentSupervisor:
    """模拟 backend-service 持有的 deployment supervisor。"""

    def __init__(self) -> None:
        """初始化测试 supervisor。"""

        self.process_state = "stopped"
        self.start_calls: list[str] = []
        self.last_prediction_request = None
        self.ensure_calls = 0
        self.status_calls = 0
        self.inference_calls = 0

    def ensure_deployment(self, config: SimpleNamespace) -> None:
        """登记 deployment 配置。"""

        self.ensure_calls += 1
        self.last_config = config

    def get_status(self, config: SimpleNamespace) -> SimpleNamespace:
        """返回当前进程状态。"""

        self.status_calls += 1
        return SimpleNamespace(
            process_state=self.process_state,
            deployment_instance_id=config.deployment_instance_id,
        )

    def start_deployment(self, config: SimpleNamespace) -> SimpleNamespace:
        """模拟启动 deployment worker。"""

        self.process_state = "running"
        self.start_calls.append(config.deployment_instance_id)
        return self.get_status(config)

    def run_inference(
        self, *, config: SimpleNamespace, request
    ) -> DeploymentProcessExecution:
        """记录推理请求并返回固定结果。"""

        self.inference_calls += 1
        self.last_prediction_request = request
        return DeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="deployment-1:instance-0",
            execution_result=DetectionPredictionExecutionResult(
                detections=(
                    DetectionPredictionDetection(
                        bbox_xyxy=(4.0, 4.0, 24.0, 24.0),
                        score=0.97,
                        class_id=0,
                        class_name="defect",
                    ),
                ),
                latency_ms=7.5,
                image_width=64,
                image_height=64,
                preview_image_bytes=None,
                runtime_session_info=_build_runtime_session_info(),
            ),
        )


class _FakeLocalBufferWriter:
    """记录 memory 图片写入 LocalBufferBroker 的测试 writer。"""

    def __init__(self) -> None:
        """初始化测试 writer。"""

        self.last_content: bytes | None = None
        self.last_owner_id: str | None = None
        self.last_ttl_seconds: float | None = None
        self.release_calls: list[tuple[str, str | None]] = []
        self.fail_release = False

    def write_bytes(
        self,
        *,
        content: bytes,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        trace_id: str | None = None,
        **kwargs: object,
    ):
        """记录写入参数并返回固定 BufferRef。"""

        del owner_kind
        del trace_id
        self.last_content = content
        self.last_owner_id = owner_id
        ttl_seconds = kwargs.get("ttl_seconds")
        self.last_ttl_seconds = (
            float(ttl_seconds) if isinstance(ttl_seconds, int | float) else None
        )
        return SimpleNamespace(
            lease=SimpleNamespace(lease_id="lease-memory", pool_name="image-test"),
            buffer_ref=_build_buffer_ref(
                lease_id="lease-memory", media_type=media_type
            ),
        )

    def release(self, lease_id: str, *, pool_name: str | None = None) -> None:
        """记录 lease 释放参数。"""

        self.release_calls.append((lease_id, pool_name))
        if self.fail_release:
            raise RuntimeError("release failed")


class _FakePublishedInferenceGateway:
    """记录 detection 节点发出的 PublishedInferenceRequest。"""

    def __init__(self) -> None:
        """初始化测试 gateway。"""

        self.last_request: PublishedInferenceRequest | None = None

    def infer(self, request: PublishedInferenceRequest):
        """记录请求并返回固定结果。"""

        self.last_request = request
        return PublishedInferenceResult(
            task_type="detection",
            deployment_instance_id=request.deployment_instance_id,
            latency_ms=7.5,
            image_width=64,
            image_height=64,
            detections=(
                {
                    "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
                    "score": 0.97,
                    "class_id": 0,
                    "class_name": "defect",
                },
            ),
        )


class _OutOfOrderPublishedInferenceGateway:
    """让两个并发请求按相反顺序完成的测试 gateway。"""

    def __init__(self) -> None:
        """初始化双请求同步屏障。"""

        self._barrier = Barrier(2)

    def infer(self, request: PublishedInferenceRequest) -> PublishedInferenceResult:
        """等待两个请求同时进入，并让 slow 请求后完成。"""

        self._barrier.wait(timeout=2.0)
        if request.trace_id == "slow":
            sleep(0.05)
        return PublishedInferenceResult(
            task_type=request.task_type,
            deployment_instance_id=request.deployment_instance_id,
            latency_ms=1.0,
            image_width=64,
            image_height=64,
            metadata={"trace_id": request.trace_id or ""},
        )


def _build_gateway_request(trace_id: str) -> PublishedInferenceRequest:
    """构造并发 gateway 关联测试请求。"""

    return PublishedInferenceRequest(
        task_type="detection",
        deployment_instance_id=f"deployment-{trace_id}",
        image_payload={
            "transport_kind": "buffer",
            "buffer_ref": _build_buffer_ref(lease_id=f"lease-{trace_id}").model_dump(
                mode="json"
            ),
            "media_type": "image/jpeg",
            "width": 64,
            "height": 64,
        },
        trace_id=trace_id,
        execution_scope_id="workflow-run-concurrent",
    )


def _build_buffer_ref(
    *, lease_id: str = "lease-1", media_type: str = "image/jpeg"
) -> BufferRef:
    """构造测试使用的 BufferRef。"""

    return BufferRef(
        buffer_id="image-test:0",
        lease_id=lease_id,
        path="runtime/buffers/image-test/pool-001.dat",
        offset=0,
        size=16,
        media_type=media_type,
        broker_epoch="epoch-1",
        generation=1,
    )


def _build_runtime_session_info() -> DetectionRuntimeSessionInfo:
    """构造测试 runtime session info。"""

    return DetectionRuntimeSessionInfo(
        backend_name="fake",
        model_uri="models/model.onnx",
        device_name="cpu",
        input_spec=DetectionRuntimeTensorSpec(
            name="images", shape=(1, 3, 64, 64), dtype="float32"
        ),
        output_spec=DetectionRuntimeTensorSpec(
            name="detections", shape=(1, 7), dtype="float32"
        ),
    )

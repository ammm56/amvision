"""PublishedInferenceGateway 事件 dispatcher 与 workflow 节点接入测试。"""

from __future__ import annotations

import multiprocessing
from types import SimpleNamespace

from backend.contracts.buffers import BufferRef
from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.nodes.core_nodes.yolox_detection import _yolox_detection_handler
from backend.service.application.deployments import (
    PublishedInferenceGatewayClient,
    PublishedInferenceGatewayDispatcher,
    PublishedInferenceGatewayEventChannel,
    PublishedInferenceRequest,
    YoloXDeploymentPublishedInferenceGateway,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import YoloXDeploymentProcessExecution
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionDetection,
    YoloXPredictionExecutionResult,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE,
    list_registered_execution_cleanups,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.service_node_runtime import WorkflowServiceNodeRuntimeContext
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo
from tests.api_test_support import build_test_jpeg_bytes


def test_published_inference_gateway_client_calls_parent_supervisor_with_event_dispatcher() -> None:
    """验证 gateway client 通过父进程事件 dispatcher 调用 backend-service 持有的 supervisor。"""

    context = multiprocessing.get_context("spawn")
    fake_supervisor = _FakeDeploymentSupervisor()
    gateway = YoloXDeploymentPublishedInferenceGateway(
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
        assert fake_supervisor.start_calls == ["deployment-1"]
        assert fake_supervisor.last_prediction_request is not None
        assert fake_supervisor.last_prediction_request.input_image_bytes is None
        assert fake_supervisor.last_prediction_request.input_image_payload is not None
        assert fake_supervisor.last_prediction_request.input_image_payload["transport_kind"] == "buffer"
        assert fake_supervisor.last_prediction_request.input_image_payload["buffer_ref"]["lease_id"] == "lease-1"
        assert fake_supervisor.last_prediction_request.score_threshold == 0.41
    finally:
        dispatcher.stop()
        channel.request_queue.close()
        channel.request_queue.join_thread()
        channel.response_queue.close()
        channel.response_queue.join_thread()


def test_yolox_detection_node_writes_memory_image_to_local_buffer_before_gateway_call() -> None:
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

    output = _yolox_detection_handler(
        WorkflowNodeExecutionRequest(
            node_id="detect",
            node_definition=object(),
            parameters={"deployment_instance_id": "deployment-1", "score_threshold": 0.52},
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
            },
            runtime_context=runtime_context,
        )
    )

    assert output["detections"]["items"][0]["class_name"] == "defect"
    assert fake_writer.last_content == source_bytes
    assert fake_writer.last_owner_id == "run-1:detect"
    assert fake_gateway.last_request is not None
    assert fake_gateway.last_request.input_image_bytes is None
    assert fake_gateway.last_request.image_payload["transport_kind"] == "buffer"
    assert fake_gateway.last_request.image_payload["buffer_ref"]["lease_id"] == "lease-memory"
    assert fake_gateway.last_request.score_threshold == 0.52


def test_yolox_detection_node_registers_local_buffer_lease_cleanup() -> None:
    """验证 detection 节点写入 LocalBufferBroker 后会登记 lease cleanup。"""

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

    _yolox_detection_handler(
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
    assert len(cleanup_items) == 1
    assert cleanup_items[0].resource_kind == WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE
    assert cleanup_items[0].resource_id == "lease-memory"
    assert cleanup_items[0].metadata == {"pool_name": "image-small"}


class _FakeDeploymentService:
    """返回固定 process_config 的测试 deployment service。"""

    def resolve_process_config(self, deployment_instance_id: str) -> SimpleNamespace:
        """返回测试 process_config。"""

        return SimpleNamespace(deployment_instance_id=deployment_instance_id)


class _FakeDeploymentSupervisor:
    """模拟 backend-service 持有的 deployment supervisor。"""

    def __init__(self) -> None:
        """初始化测试 supervisor。"""

        self.process_state = "stopped"
        self.start_calls: list[str] = []
        self.last_prediction_request = None

    def ensure_deployment(self, config: SimpleNamespace) -> None:
        """登记 deployment 配置。"""

        self.last_config = config

    def get_status(self, config: SimpleNamespace) -> SimpleNamespace:
        """返回当前进程状态。"""

        return SimpleNamespace(process_state=self.process_state, deployment_instance_id=config.deployment_instance_id)

    def start_deployment(self, config: SimpleNamespace) -> SimpleNamespace:
        """模拟启动 deployment worker。"""

        self.process_state = "running"
        self.start_calls.append(config.deployment_instance_id)
        return self.get_status(config)

    def run_inference(self, *, config: SimpleNamespace, request) -> YoloXDeploymentProcessExecution:
        """记录推理请求并返回固定结果。"""

        self.last_prediction_request = request
        return YoloXDeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="deployment-1:instance-0",
            execution_result=YoloXPredictionExecutionResult(
                detections=(
                    YoloXPredictionDetection(
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

    def write_bytes(self, *, content: bytes, owner_kind: str, owner_id: str, media_type: str, trace_id: str | None = None):
        """记录写入参数并返回固定 BufferRef。"""

        del owner_kind
        del trace_id
        self.last_content = content
        self.last_owner_id = owner_id
        return SimpleNamespace(
            lease=SimpleNamespace(lease_id="lease-memory", pool_name="image-small"),
            buffer_ref=_build_buffer_ref(lease_id="lease-memory", media_type=media_type),
        )


class _FakePublishedInferenceGateway:
    """记录 detection 节点发出的 PublishedInferenceRequest。"""

    def __init__(self) -> None:
        """初始化测试 gateway。"""

        self.last_request: PublishedInferenceRequest | None = None

    def infer(self, request: PublishedInferenceRequest):
        """记录请求并返回固定结果。"""

        self.last_request = request
        return SimpleNamespace(
            detections=(
                {
                    "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
                    "score": 0.97,
                    "class_id": 0,
                    "class_name": "defect",
                },
            )
        )


def _build_buffer_ref(*, lease_id: str = "lease-1", media_type: str = "image/jpeg") -> BufferRef:
    """构造测试使用的 BufferRef。"""

    return BufferRef(
        buffer_id="image-small:0",
        lease_id=lease_id,
        path="runtime/buffers/image-small/pool-001.dat",
        offset=0,
        size=16,
        media_type=media_type,
        broker_epoch="epoch-1",
        generation=1,
    )


def _build_runtime_session_info() -> YoloXRuntimeSessionInfo:
    """构造测试 runtime session info。"""

    return YoloXRuntimeSessionInfo(
        backend_name="fake",
        model_uri="models/model.onnx",
        device_name="cpu",
        input_spec=RuntimeTensorSpec(name="images", shape=(1, 3, 64, 64), dtype="float32"),
        output_spec=RuntimeTensorSpec(name="detections", shape=(1, 7), dtype="float32"),
    )

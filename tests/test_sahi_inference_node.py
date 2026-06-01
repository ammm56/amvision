"""SAHI 大图推理节点测试。"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.nodes.core_nodes.sahi_inference import _sahi_inference_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.service_node_runtime import WorkflowServiceNodeRuntimeContext


def test_sahi_inference_node_translates_slice_detections_with_none_merge() -> None:
    """验证 SAHI 节点会按切片回映射 detection 坐标。"""

    source_bytes = _build_test_jpeg_bytes(width=100, height=100)
    image_registry = ExecutionImageRegistry()
    registered_image = image_registry.register_image_bytes(
        content=source_bytes,
        media_type="image/jpeg",
        width=100,
        height=100,
        created_by_node_id="fixture",
    )
    fake_gateway = _FakePublishedInferenceGateway(mode="full-window")
    output = _sahi_inference_handler(
        WorkflowNodeExecutionRequest(
            node_id="sahi",
            node_definition=SimpleNamespace(node_type_id="core.model.sahi-inference"),
            parameters={
                "deployment_instance_id": "deployment-1",
                "slice_wh": [60, 60],
                "overlap_wh": [20, 20],
                "merge_mode": "none",
            },
            input_values={
                "image": build_memory_image_payload(
                    image_handle=registered_image.image_handle,
                    media_type="image/jpeg",
                    width=100,
                    height=100,
                )
            },
            execution_metadata={"execution_image_registry": image_registry, "workflow_run_id": "run-1"},
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=object(),
                dataset_storage=object(),
                published_inference_gateway=fake_gateway,
            ),
        )
    )

    assert len(fake_gateway.requests) == 4
    assert all(request.image_payload["transport_kind"] == "memory" for request in fake_gateway.requests)
    assert all(request.input_image_bytes is not None for request in fake_gateway.requests)
    translated_bboxes = {tuple(item["bbox_xyxy"]) for item in output["detections"]["items"]}
    assert translated_bboxes == {
        (1.0, 2.0, 59.0, 58.0),
        (41.0, 2.0, 99.0, 58.0),
        (1.0, 42.0, 59.0, 98.0),
        (41.0, 42.0, 99.0, 98.0),
    }


def test_sahi_inference_node_applies_nms_for_boundary_duplicates() -> None:
    """验证 SAHI 节点会对跨切片重复框执行 NMS。"""

    source_bytes = _build_test_jpeg_bytes(width=120, height=60)
    image_registry = ExecutionImageRegistry()
    registered_image = image_registry.register_image_bytes(
        content=source_bytes,
        media_type="image/jpeg",
        width=120,
        height=60,
        created_by_node_id="fixture",
    )
    fake_gateway = _FakePublishedInferenceGateway(mode="boundary-duplicate")
    output = _sahi_inference_handler(
        WorkflowNodeExecutionRequest(
            node_id="sahi",
            node_definition=SimpleNamespace(node_type_id="core.model.sahi-inference"),
            parameters={
                "deployment_instance_id": "deployment-1",
                "slice_wh": [80, 60],
                "overlap_wh": [40, 0],
                "merge_mode": "nms",
                "iou_threshold": 0.5,
            },
            input_values={
                "image": build_memory_image_payload(
                    image_handle=registered_image.image_handle,
                    media_type="image/jpeg",
                    width=120,
                    height=60,
                )
            },
            execution_metadata={"execution_image_registry": image_registry},
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=object(),
                dataset_storage=object(),
                published_inference_gateway=fake_gateway,
            ),
        )
    )

    assert len(fake_gateway.requests) == 2
    assert len(output["detections"]["items"]) == 1
    assert output["detections"]["items"][0]["bbox_xyxy"] == [30.0, 10.0, 70.0, 40.0]
    assert output["detections"]["items"][0]["score"] == 0.95


def test_sahi_inference_node_supports_parallel_slice_execution() -> None:
    """验证 SAHI 节点在线程模式下仍能完成全部切片推理。"""

    source_bytes = _build_test_jpeg_bytes(width=96, height=64)
    image_registry = ExecutionImageRegistry()
    registered_image = image_registry.register_image_bytes(
        content=source_bytes,
        media_type="image/jpeg",
        width=96,
        height=64,
        created_by_node_id="fixture",
    )
    fake_gateway = _FakePublishedInferenceGateway(mode="full-window")
    output = _sahi_inference_handler(
        WorkflowNodeExecutionRequest(
            node_id="sahi",
            node_definition=SimpleNamespace(node_type_id="core.model.sahi-inference"),
            parameters={
                "deployment_instance_id": "deployment-1",
                "slice_wh": [48, 64],
                "overlap_wh": [0, 0],
                "merge_mode": "none",
                "thread_workers": 2,
            },
            input_values={
                "image": build_memory_image_payload(
                    image_handle=registered_image.image_handle,
                    media_type="image/jpeg",
                    width=96,
                    height=64,
                )
            },
            execution_metadata={"execution_image_registry": image_registry},
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=object(),
                dataset_storage=object(),
                published_inference_gateway=fake_gateway,
            ),
        )
    )

    assert len(fake_gateway.requests) == 2
    assert len(output["detections"]["items"]) == 2


class _FakePublishedInferenceGateway:
    """记录 SAHI 节点发出的切片推理请求。"""

    def __init__(self, *, mode: str) -> None:
        """初始化测试 gateway。"""

        self.mode = mode
        self.requests = []
        self._lock = Lock()

    def infer(self, request):
        """记录请求并返回按模式构造的检测结果。"""

        with self._lock:
            call_index = len(self.requests)
            self.requests.append(request)
        width = int(request.image_payload["width"])
        height = int(request.image_payload["height"])
        if self.mode == "boundary-duplicate":
            if call_index == 0:
                detections = (
                    {
                        "bbox_xyxy": [30.0, 10.0, 70.0, 40.0],
                        "score": 0.95,
                        "class_id": 0,
                        "class_name": "defect",
                    },
                )
            else:
                detections = (
                    {
                        "bbox_xyxy": [0.0, 10.0, 40.0, 40.0],
                        "score": 0.9,
                        "class_id": 0,
                        "class_name": "defect",
                    },
                )
        else:
            detections = (
                {
                    "bbox_xyxy": [1.0, 2.0, float(max(1, width - 1)), float(max(2, height - 2))],
                    "score": round(0.99 - (call_index * 0.01), 3),
                    "class_id": 0,
                    "class_name": "defect",
                },
            )
        return SimpleNamespace(detections=detections)


def _build_test_jpeg_bytes(*, width: int, height: int) -> bytes:
    """构造指定尺寸的测试 JPEG 图片。"""

    import cv2
    import numpy as np

    image = np.full((height, width, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    return encoded.tobytes()

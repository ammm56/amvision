"""五类通用模型 Batch 节点与结果 bridge 测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.contracts.buffers import BufferRef
from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.nodes.core_catalog import (
    get_core_workflow_node_definitions,
    get_core_workflow_payload_contracts,
)
from backend.nodes.core_nodes.logic.value.categories_batch_to_value_list import (
    CORE_NODE_SPEC as CATEGORIES_BRIDGE_SPEC,
)
from backend.nodes.core_nodes.logic.value.detections_batch_to_value_list import (
    CORE_NODE_SPEC as DETECTIONS_BRIDGE_SPEC,
)
from backend.nodes.core_nodes.logic.value.obbs_batch_to_value_list import (
    CORE_NODE_SPEC as OBBS_BRIDGE_SPEC,
)
from backend.nodes.core_nodes.logic.value.poses_batch_to_value_list import (
    CORE_NODE_SPEC as POSES_BRIDGE_SPEC,
)
from backend.nodes.core_nodes.logic.value.segments_batch_to_value_list import (
    CORE_NODE_SPEC as SEGMENTS_BRIDGE_SPEC,
)
from backend.nodes.core_nodes.model.deployment.deployment_classification_batch import (
    CORE_NODE_SPEC as CLASSIFICATION_BATCH_SPEC,
)
from backend.nodes.core_nodes.model.deployment.deployment_detection_batch import (
    CORE_NODE_SPEC as DETECTION_BATCH_SPEC,
)
from backend.nodes.core_nodes.model.deployment.deployment_obb_batch import (
    CORE_NODE_SPEC as OBB_BATCH_SPEC,
)
from backend.nodes.core_nodes.model.deployment.deployment_pose_batch import (
    CORE_NODE_SPEC as POSE_BATCH_SPEC,
)
from backend.nodes.core_nodes.model.deployment.deployment_segmentation_batch import (
    CORE_NODE_SPEC as SEGMENTATION_BATCH_SPEC,
)
from backend.service.application.deployments import (
    PublishedInferenceBatchRequest,
    PublishedInferenceBatchResult,
    PublishedInferenceResult,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from tests.api_test_support import build_test_jpeg_bytes


_BATCH_CASES = (
    (
        DETECTION_BATCH_SPEC,
        DETECTIONS_BRIDGE_SPEC,
        "detection",
        "detections_batch",
    ),
    (
        CLASSIFICATION_BATCH_SPEC,
        CATEGORIES_BRIDGE_SPEC,
        "classification",
        "categories_batch",
    ),
    (
        SEGMENTATION_BATCH_SPEC,
        SEGMENTS_BRIDGE_SPEC,
        "segmentation",
        "segments_batch",
    ),
    (POSE_BATCH_SPEC, POSES_BRIDGE_SPEC, "pose", "poses_batch"),
    (OBB_BATCH_SPEC, OBBS_BRIDGE_SPEC, "obb", "obbs_batch"),
)


def test_core_catalog_contains_five_batch_nodes_bridges_and_payloads() -> None:
    """验证五类 Batch 能力完整进入公开 node 和 payload 目录。"""

    node_ids = {
        definition.node_type_id for definition in get_core_workflow_node_definitions()
    }
    payload_ids = {
        contract.payload_type_id for contract in get_core_workflow_payload_contracts()
    }

    assert {
        "core.model.detection-batch",
        "core.model.classification-batch",
        "core.model.segmentation-batch",
        "core.model.pose-batch",
        "core.model.obb-batch",
        "core.logic.detections-batch-to-value-list",
        "core.logic.categories-batch-to-value-list",
        "core.logic.segments-batch-to-value-list",
        "core.logic.poses-batch-to-value-list",
        "core.logic.obbs-batch-to-value-list",
    } <= node_ids
    assert {
        "detections-batch.v1",
        "categories-batch.v1",
        "segments-batch.v1",
        "poses-batch.v1",
        "obbs-batch.v1",
    } <= payload_ids


@pytest.mark.parametrize(
    ("batch_spec", "bridge_spec", "task_type", "output_name"),
    _BATCH_CASES,
)
def test_model_batch_node_preserves_order_and_bridge_restores_typed_results(
    batch_spec: object,
    bridge_spec: object,
    task_type: str,
    output_name: str,
) -> None:
    """验证五类 Batch 同序输出、locator 清理和单项 result bridge。"""

    image_bytes = build_test_jpeg_bytes()
    image_registry = ExecutionImageRegistry()
    images = []
    for item_index in range(3):
        registered = image_registry.register_image_bytes(
            content=image_bytes,
            media_type="image/jpeg",
            width=64,
            height=64,
            created_by_node_id="fixture",
        )
        images.append(
            {
                **build_memory_image_payload(
                    image_handle=registered.image_handle,
                    media_type="image/jpeg",
                    width=64,
                    height=64,
                ),
                "crop_index": item_index + 1,
                "bbox_xyxy": [item_index, 0, item_index + 10, 10],
                "content_sha256": f"sha-{item_index}",
            }
        )
    writer = _UniqueLocalBufferWriter()
    gateway = _FakeBatchGateway()
    batch_request = WorkflowNodeExecutionRequest(
        node_id=f"{task_type}-batch",
        node_definition=batch_spec.node_definition,
        parameters={"deployment_instance_id": "deployment-batch"},
        input_values={"images": {"items": images, "count": len(images)}},
        execution_metadata={
            "execution_image_registry": image_registry,
            "local_buffer_reader": writer,
            "workflow_run_id": "workflow-batch-run",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
            local_buffer_reader=writer,
            published_inference_gateway=gateway,
        ),
    )

    batch_payload = batch_spec.handler(batch_request)[output_name]
    restored = bridge_spec.handler(
        WorkflowNodeExecutionRequest(
            node_id=f"{task_type}-bridge",
            node_definition=bridge_spec.node_definition,
            parameters={},
            input_values={output_name: batch_payload},
            execution_metadata={},
        )
    )["value"]["value"]

    assert batch_payload["count"] == 3
    assert [item["item_index"] for item in batch_payload["items"]] == [0, 1, 2]
    assert [item["item_id"] for item in batch_payload["items"]] == [
        "crop-1",
        "crop-2",
        "crop-3",
    ]
    assert [item["source"]["crop_index"] for item in batch_payload["items"]] == [
        1,
        2,
        3,
    ]
    assert len(restored) == 3
    assert gateway.last_request is not None
    assert len(gateway.last_request.requests) == 3
    assert all(
        item.image_payload["transport_kind"] == "buffer"
        for item in gateway.last_request.requests
    )
    assert writer.write_many_calls == 1
    assert writer.release_owner_calls == [
        ("workflow-runtime", f"workflow-batch-run:{task_type}-batch")
    ]
    assert writer.release_calls == []
    serialized = json.dumps(batch_payload, ensure_ascii=False)
    for forbidden in (
        "image_handle",
        "buffer_ref",
        "frame_ref",
        "local_path",
        "object_key",
        "image_base64",
    ):
        assert forbidden not in serialized


def test_batch_bridge_rejects_out_of_order_items_and_locator_leaks() -> None:
    """验证 bridge 不会静默接受乱序 item 或临时 locator。"""

    payload = {
        "format_id": "amvision.categories-batch.v1",
        "task_type": "classification",
        "result_payload_type_id": "categories.v1",
        "count": 1,
        "items": [
            {
                "item_index": 1,
                "item_id": "crop-1",
                "source": {},
                "result": {"count": 0, "items": [], "top_item": None},
            }
        ],
        "batch_latency_ms": 1.0,
        "metadata": {},
    }
    with pytest.raises(InvalidRequestError, match="item_index"):
        _invoke_bridge(CATEGORIES_BRIDGE_SPEC, "categories_batch", payload)

    payload["items"][0]["item_index"] = 0
    payload["items"][0]["source"] = {"nested": {"buffer_ref": {}}}
    with pytest.raises(InvalidRequestError, match="locator"):
        _invoke_bridge(CATEGORIES_BRIDGE_SPEC, "categories_batch", payload)


class _UniqueLocalBufferWriter:
    """为每个 Batch item 返回唯一 lease 的测试 writer。"""

    def __init__(self) -> None:
        self.next_index = 0
        self.release_calls: list[str] = []
        self.release_owner_calls: list[tuple[str | None, str | None]] = []
        self.write_many_calls = 0

    def write_bytes(self, *, media_type: str, **_: object) -> SimpleNamespace:
        """返回唯一的 BufferRef 和 lease。"""

        item_index = self.next_index
        self.next_index += 1
        lease_id = f"lease-{item_index}"
        return SimpleNamespace(
            lease=SimpleNamespace(lease_id=lease_id),
            buffer_ref=BufferRef(
                buffer_id=f"batch:{item_index}",
                lease_id=lease_id,
                arena_id="local-buffer-main",
                descriptor_index=item_index,
                descriptor_generation=1,
                broker_epoch="epoch-1",
                offset=item_index * 4096,
                content_length=1024,
                allocation_capacity_bytes=4096,
                media_type=media_type,
            ),
        )

    def release(self, lease_id: str) -> None:
        """记录 Batch finally 释放顺序。"""

        self.release_calls.append(lease_id)

    def write_many(
        self,
        *,
        items: tuple[dict[str, object], ...],
        **_: object,
    ) -> tuple[SimpleNamespace, ...]:
        """记录一次 Batch 写入并按输入顺序返回结果。"""

        self.write_many_calls += 1
        return tuple(
            self.write_bytes(media_type=str(item["media_type"]))
            for item in items
        )

    def release_owner(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        owner_id_prefix: str | None = None,
    ) -> int:
        """记录 Batch 以节点 owner 一次释放全部临时 lease。"""

        assert owner_id_prefix is None
        self.release_owner_calls.append((owner_kind, owner_id))
        return self.next_index


class _FakeBatchGateway:
    """按 task_type 返回三项标准推理结果的 fake gateway。"""

    def __init__(self) -> None:
        self.last_request: PublishedInferenceBatchRequest | None = None

    def infer_batch(
        self,
        request: PublishedInferenceBatchRequest,
    ) -> PublishedInferenceBatchResult:
        """返回与输入严格同序的任务结果。"""

        self.last_request = request
        task_type = request.requests[0].task_type
        results = tuple(
            _build_inference_result(task_type, item_index)
            for item_index in range(len(request.requests))
        )
        return PublishedInferenceBatchResult(
            task_type=task_type,
            deployment_instance_id="deployment-batch",
            instance_id="deployment-batch:instance-0",
            batch_latency_ms=27.0,
            results=results,
            metadata={"execution_mode": "sequential-reserved-instance"},
        )


def _build_inference_result(
    task_type: str,
    item_index: int,
) -> PublishedInferenceResult:
    """构造五类任务均满足现有单项 contract 的结果。"""

    common = {
        "task_type": task_type,
        "deployment_instance_id": "deployment-batch",
        "latency_ms": 9.0,
        "image_width": 64,
        "image_height": 64,
        "metadata": {"item_index": item_index},
    }
    if task_type == "detection":
        return PublishedInferenceResult(
            **common,
            detections=(
                {"bbox_xyxy": [1, 2, 10, 12], "score": 0.9},
            ),
        )
    if task_type == "classification":
        category = {
            "class_id": item_index,
            "class_name": f"class-{item_index}",
            "probability": 0.9,
        }
        return PublishedInferenceResult(
            **common,
            categories=(category,),
            top_category=category,
        )
    if task_type == "segmentation":
        return PublishedInferenceResult(
            **common,
            instances=(
                {
                    "bbox_xyxy": [1, 2, 10, 12],
                    "score": 0.9,
                    "segments": [[[1, 2], [10, 2], [10, 12], [1, 12]]],
                },
            ),
        )
    if task_type == "pose":
        return PublishedInferenceResult(
            **common,
            instances=(
                {
                    "score": 0.9,
                    "bbox_xyxy": [1, 2, 10, 12],
                    "keypoints": [{"x": 2.0, "y": 3.0, "confidence": 0.8}],
                    "kpt_shape": [1, 3],
                },
            ),
        )
    return PublishedInferenceResult(
        **common,
        instances=(
            {
                "score": 0.9,
                "bbox_xyxy": [1, 2, 10, 12],
                "angle": 10.0,
            },
        ),
    )


def _invoke_bridge(
    bridge_spec: object,
    input_name: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """执行一个 Batch bridge。"""

    return bridge_spec.handler(
        WorkflowNodeExecutionRequest(
            node_id="batch-bridge",
            node_definition=bridge_spec.node_definition,
            parameters={},
            input_values={input_name: payload},
            execution_metadata={},
        )
    )

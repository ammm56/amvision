"""Workflow value 与强类型视觉 payload 对称桥接测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows.workflow_graph import NODE_CONCURRENCY_THREAD_SAFE
from backend.nodes.core_catalog import get_core_workflow_node_definitions
from backend.nodes.core_nodes.logic.value.payload_to_value import (
    CORE_NODE_SPEC as PAYLOAD_TO_VALUE_SPEC,
)
from backend.nodes.core_nodes.logic.value.value_to_categories import (
    CORE_NODE_SPEC as VALUE_TO_CATEGORIES_SPEC,
)
from backend.nodes.core_nodes.logic.value.value_to_circles import (
    CORE_NODE_SPEC as VALUE_TO_CIRCLES_SPEC,
)
from backend.nodes.core_nodes.logic.value.value_to_detections import (
    CORE_NODE_SPEC as VALUE_TO_DETECTIONS_SPEC,
)
from backend.nodes.core_nodes.logic.value.value_to_image_refs import (
    CORE_NODE_SPEC as VALUE_TO_IMAGE_REFS_SPEC,
)
from backend.nodes.core_nodes.logic.value.value_to_obbs import (
    CORE_NODE_SPEC as VALUE_TO_OBBS_SPEC,
)
from backend.nodes.core_nodes.logic.value.value_to_poses import (
    CORE_NODE_SPEC as VALUE_TO_POSES_SPEC,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


IMAGE_REF = {
    "transport_kind": "memory",
    "image_handle": "image-1",
    "media_type": "image/raw",
    "width": 8,
    "height": 6,
    "shape": [6, 8],
    "dtype": "uint8",
    "layout": "HW",
    "pixel_format": "gray8",
}


def test_core_catalog_contains_all_symmetric_value_bridges() -> None:
    """验证全部规划的强类型恢复节点已经进入公开 core catalog。"""

    definitions = {
        definition.node_type_id: definition
        for definition in get_core_workflow_node_definitions()
    }
    expected_ids = {
        "core.logic.value-to-image-refs",
        "core.logic.value-to-circles",
        "core.logic.value-to-detections",
        "core.logic.value-to-categories",
        "core.logic.value-to-poses",
        "core.logic.value-to-obbs",
    }

    assert expected_ids <= set(definitions)
    assert all(
        definitions[node_type_id].concurrency_policy
        == NODE_CONCURRENCY_THREAD_SAFE
        for node_type_id in expected_ids
    )


def test_payload_to_value_supports_image_image_refs_and_circles() -> None:
    """验证 Parallel 前后的图片和圆结果都有显式 value bridge。"""

    image_value = _invoke(
        PAYLOAD_TO_VALUE_SPEC,
        input_values={"image": IMAGE_REF},
    )["value"]
    images_value = _invoke(
        PAYLOAD_TO_VALUE_SPEC,
        input_values={"images": {"items": [IMAGE_REF], "count": 1}},
    )["value"]
    circles_payload = {
        "source_image": IMAGE_REF,
        "count": 1,
        "items": [{"center_xy": [3.0, 4.0], "radius": 2.0}],
    }
    circles_value = _invoke(
        PAYLOAD_TO_VALUE_SPEC,
        input_values={"circles": circles_payload},
    )["value"]
    restored_circles = _invoke(
        VALUE_TO_CIRCLES_SPEC,
        input_values={"value": circles_value},
    )["circles"]

    assert image_value["value"] == IMAGE_REF
    assert images_value["value"]["items"] == [IMAGE_REF]
    assert restored_circles == circles_payload


def test_value_to_image_refs_accepts_split_list_partition_without_copying_image_body() -> None:
    """验证 Split List 分支中的数组可直接恢复为 image-refs.v1。"""

    second_image = {**IMAGE_REF, "image_handle": "image-2"}
    outputs = _invoke(
        VALUE_TO_IMAGE_REFS_SPEC,
        input_values={"value": {"value": [IMAGE_REF, second_image]}},
    )

    assert outputs["images"]["count"] == 2
    assert [item["image_handle"] for item in outputs["images"]["items"]] == [
        "image-1",
        "image-2",
    ]
    assert "image_base64" not in outputs["images"]["items"][0]


@pytest.mark.parametrize(
    ("node_spec", "output_name", "payload"),
    (
        (
            VALUE_TO_DETECTIONS_SPEC,
            "detections",
            {
                "source_image": IMAGE_REF,
                "count": 1,
                "items": [{"bbox_xyxy": [1, 2, 4, 5], "score": 0.9}],
            },
        ),
        (
            VALUE_TO_CATEGORIES_SPEC,
            "categories",
            {
                "source_image": IMAGE_REF,
                "count": 1,
                "items": [{"class_id": 2, "class_name": "ok", "probability": 0.8}],
                "top_item": {"class_id": 2, "class_name": "ok", "probability": 0.8},
            },
        ),
        (
            VALUE_TO_POSES_SPEC,
            "poses",
            {
                "source_image": IMAGE_REF,
                "count": 1,
                "items": [
                    {
                        "pose_id": "pose-1",
                        "score": 0.7,
                        "bbox_xyxy": [1, 2, 4, 5],
                        "keypoints": [{"x": 2.0, "y": 3.0, "confidence": 0.9}],
                    }
                ],
            },
        ),
        (
            VALUE_TO_OBBS_SPEC,
            "obbs",
            {
                "source_image": IMAGE_REF,
                "count": 1,
                "items": [
                    {
                        "obb_id": "obb-1",
                        "score": 0.6,
                        "bbox_xyxy": [1, 2, 4, 5],
                        "angle": 15.0,
                    }
                ],
            },
        ),
    ),
)
def test_model_result_value_bridges_preserve_standard_payloads(
    node_spec: object,
    output_name: str,
    payload: dict[str, object],
) -> None:
    """验证四类模型单项 payload 可无损恢复并继续接现有节点。"""

    outputs = _invoke(
        node_spec,
        input_values={"value": {"value": payload}},
    )

    assert outputs[output_name] == payload
    assert outputs["summary"]["value"]["count"] == 1


def test_typed_value_bridge_rejects_count_mismatch() -> None:
    """验证桥接不会静默修正上游损坏的 count。"""

    with pytest.raises(InvalidRequestError, match="count 与 items 数量一致"):
        _invoke(
            VALUE_TO_DETECTIONS_SPEC,
            input_values={
                "value": {
                    "value": {
                        "count": 2,
                        "items": [{"bbox_xyxy": [1, 2, 4, 5], "score": 0.9}],
                    }
                }
            },
        )


def _invoke(
    node_spec: object,
    *,
    input_values: dict[str, object],
) -> dict[str, object]:
    """执行一个 CoreNodeSpec handler。"""

    handler = node_spec.handler
    assert handler is not None
    return handler(
        WorkflowNodeExecutionRequest(
            node_id="bridge",
            node_definition=node_spec.node_definition,
            parameters={},
            input_values=input_values,
            execution_metadata={},
        )
    )

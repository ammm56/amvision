"""value.v1 与强类型结果 payload 的通用桥接实现。"""

from __future__ import annotations

from collections.abc import Callable
from numbers import Real
from typing import Any

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    extract_value_by_path,
    require_value_payload,
)
from backend.nodes.parameter_utils import is_empty_parameter
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


PayloadValidator = Callable[[object, str], dict[str, object]]
ItemValidator = Callable[[object, str, int], dict[str, object]]


def build_value_to_payload_node_spec(
    *,
    node_type_id: str,
    display_name: str,
    output_name: str,
    output_display_name: str,
    payload_type_id: str,
    description: str,
    validator: PayloadValidator,
    capability_tag: str,
    category: str = "core.logic.transform",
) -> CoreNodeSpec:
    """构造一个显式 value.v1 到强类型 payload 的无状态桥接节点。"""

    def handle_value_to_payload(
        request: WorkflowNodeExecutionRequest,
    ) -> dict[str, object]:
        """解包 value、执行目标契约校验，并返回独立的 JSON 容器。"""

        value_root = require_value_payload(
            request.input_values.get("value"),
            field_name="value",
        )["value"]
        raw_path = request.parameters.get("path")
        candidate = (
            value_root
            if is_empty_parameter(raw_path)
            else extract_value_by_path(
                root=value_root,
                path=_require_path(raw_path, node_type_id=node_type_id),
            )
        )
        normalized_payload = validator(candidate, request.node_id)
        raw_items = normalized_payload.get("items")
        count = len(raw_items) if isinstance(raw_items, list) else 0
        return {
            output_name: normalized_payload,
            "summary": build_value_payload(
                {
                    "payload_type_id": payload_type_id,
                    "count": count,
                    "source_image_attached": isinstance(
                        normalized_payload.get("source_image"), dict
                    ),
                }
            ),
        }

    return CoreNodeSpec(
        node_definition=NodeDefinition(
            node_type_id=node_type_id,
            display_name=display_name,
            category=category,
            description=description,
            implementation_kind=NODE_IMPLEMENTATION_CORE,
            runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
            concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
            input_ports=(
                NodePortDefinition(
                    name="value",
                    display_name="Value",
                    payload_type_id="value.v1",
                ),
            ),
            output_ports=(
                NodePortDefinition(
                    name=output_name,
                    display_name=output_display_name,
                    payload_type_id=payload_type_id,
                ),
                NodePortDefinition(
                    name="summary",
                    display_name="Summary",
                    payload_type_id="value.v1",
                ),
            ),
            parameter_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "title": "Path",
                        "description": "可选点分路径；为空时直接使用 value.value。",
                    }
                },
            },
            capability_tags=(
                "logic.transform",
                "payload.bridge",
                capability_tag,
            ),
        ),
        handler=handle_value_to_payload,
    )


def require_image_refs_payload(payload: object, node_id: str) -> dict[str, object]:
    """校验 image-refs.v1；同时接受 Split List 产生的 image-ref 数组。"""

    if isinstance(payload, list):
        source_payload: dict[str, object] = {"items": payload}
    elif isinstance(payload, dict):
        source_payload = payload
    else:
        raise InvalidRequestError(
            "Value To Image Refs 要求 value 必须是 image-ref 数组或 image-refs 对象",
            details={"node_id": node_id},
        )
    raw_items = source_payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            "Value To Image Refs 要求 items 必须是数组",
            details={"node_id": node_id},
        )
    normalized = dict(source_payload)
    normalized["items"] = [require_image_payload(item) for item in raw_items]
    normalized["count"] = len(raw_items)
    source_image = source_payload.get("source_image")
    if source_image is not None:
        normalized["source_image"] = require_image_payload(source_image)
    return normalized


def require_detections_payload(payload: object, node_id: str) -> dict[str, object]:
    """校验 detections.v1 并保留公开扩展字段。"""

    return _require_items_payload(
        payload,
        node_id=node_id,
        contract_name="detections.v1",
        item_validator=_validate_detection_item,
    )


def require_categories_payload(payload: object, node_id: str) -> dict[str, object]:
    """校验 categories.v1 并保留公开扩展字段。"""

    normalized = _require_items_payload(
        payload,
        node_id=node_id,
        contract_name="categories.v1",
        item_validator=_validate_category_item,
    )
    top_item = normalized.get("top_item")
    if top_item is not None:
        normalized["top_item"] = _validate_category_item(
            top_item,
            node_id,
            0,
        )
    return normalized


def require_poses_payload(payload: object, node_id: str) -> dict[str, object]:
    """校验 poses.v1 并保留公开扩展字段。"""

    return _require_items_payload(
        payload,
        node_id=node_id,
        contract_name="poses.v1",
        item_validator=_validate_pose_item,
    )


def require_obbs_payload(payload: object, node_id: str) -> dict[str, object]:
    """校验 obbs.v1 并保留公开扩展字段。"""

    return _require_items_payload(
        payload,
        node_id=node_id,
        contract_name="obbs.v1",
        item_validator=_validate_obb_item,
    )


def require_circles_payload(payload: object, node_id: str) -> dict[str, object]:
    """校验 circles.v1 并保留公开扩展字段。"""

    return _require_items_payload(
        payload,
        node_id=node_id,
        contract_name="circles.v1",
        item_validator=_validate_circle_item,
    )


def _require_items_payload(
    payload: object,
    *,
    node_id: str,
    contract_name: str,
    item_validator: ItemValidator,
) -> dict[str, object]:
    """执行通用 items/count/source_image 契约校验。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            f"Value bridge 要求 {contract_name} 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            f"Value bridge 要求 {contract_name}.items 必须是数组",
            details={"node_id": node_id},
        )
    raw_count = payload.get("count")
    if raw_count is not None and (
        isinstance(raw_count, bool)
        or not isinstance(raw_count, int)
        or raw_count != len(raw_items)
    ):
        raise InvalidRequestError(
            f"Value bridge 要求 {contract_name}.count 与 items 数量一致",
            details={
                "node_id": node_id,
                "count": raw_count,
                "item_count": len(raw_items),
            },
        )
    normalized = dict(payload)
    normalized["items"] = [
        item_validator(item, node_id, index)
        for index, item in enumerate(raw_items, start=1)
    ]
    normalized["count"] = len(raw_items)
    source_image = payload.get("source_image")
    if source_image is not None:
        normalized["source_image"] = require_image_payload(source_image)
    return normalized


def _validate_detection_item(
    item: object,
    node_id: str,
    item_index: int,
) -> dict[str, object]:
    """校验单项 detection。"""

    normalized = _require_item_object(item, "detection", node_id, item_index)
    _require_number_list(normalized.get("bbox_xyxy"), 4, "bbox_xyxy", node_id, item_index)
    _require_number(normalized.get("score"), "score", node_id, item_index)
    return normalized


def _validate_category_item(
    item: object,
    node_id: str,
    item_index: int,
) -> dict[str, object]:
    """校验单项 classification category。"""

    normalized = _require_item_object(item, "category", node_id, item_index)
    class_id = normalized.get("class_id")
    if isinstance(class_id, bool) or not isinstance(class_id, int):
        _raise_item_error("class_id 必须是整数", node_id, item_index)
    _require_number(normalized.get("probability"), "probability", node_id, item_index)
    return normalized


def _validate_pose_item(
    item: object,
    node_id: str,
    item_index: int,
) -> dict[str, object]:
    """校验单项 pose。"""

    normalized = _require_item_object(item, "pose", node_id, item_index)
    _require_number(normalized.get("score"), "score", node_id, item_index)
    bbox = normalized.get("bbox_xyxy")
    if bbox not in (None, []):
        _require_number_list(bbox, 4, "bbox_xyxy", node_id, item_index)
    keypoints = normalized.get("keypoints", [])
    if not isinstance(keypoints, list):
        _raise_item_error("keypoints 必须是数组", node_id, item_index)
    for keypoint_index, keypoint in enumerate(keypoints, start=1):
        keypoint_payload = _require_item_object(
            keypoint,
            "keypoint",
            node_id,
            keypoint_index,
        )
        _require_number(keypoint_payload.get("x"), "keypoint.x", node_id, item_index)
        _require_number(keypoint_payload.get("y"), "keypoint.y", node_id, item_index)
    normalized["keypoints"] = [dict(item) for item in keypoints]
    return normalized


def _validate_obb_item(
    item: object,
    node_id: str,
    item_index: int,
) -> dict[str, object]:
    """校验单项 OBB。"""

    normalized = _require_item_object(item, "obb", node_id, item_index)
    _require_number(normalized.get("score"), "score", node_id, item_index)
    _require_number_list(normalized.get("bbox_xyxy"), 4, "bbox_xyxy", node_id, item_index)
    angle = normalized.get("angle")
    if angle is not None:
        _require_number(angle, "angle", node_id, item_index)
    return normalized


def _validate_circle_item(
    item: object,
    node_id: str,
    item_index: int,
) -> dict[str, object]:
    """校验单项 circle。"""

    normalized = _require_item_object(item, "circle", node_id, item_index)
    _require_number_list(normalized.get("center_xy"), 2, "center_xy", node_id, item_index)
    _require_number(normalized.get("radius"), "radius", node_id, item_index)
    return normalized


def _require_item_object(
    item: object,
    item_name: str,
    node_id: str,
    item_index: int,
) -> dict[str, object]:
    """校验并浅复制单项对象。"""

    if not isinstance(item, dict):
        _raise_item_error(f"{item_name} 必须是对象", node_id, item_index)
    return dict(item)


def _require_number_list(
    value: object,
    length: int,
    field_name: str,
    node_id: str,
    item_index: int,
) -> list[float]:
    """校验固定长度数值数组。"""

    if not isinstance(value, list) or len(value) != length:
        _raise_item_error(
            f"{field_name} 必须是长度为 {length} 的数组",
            node_id,
            item_index,
        )
    for item in value:
        _require_number(item, field_name, node_id, item_index)
    return [float(item) for item in value]


def _require_number(
    value: object,
    field_name: str,
    node_id: str,
    item_index: int,
) -> float:
    """校验有限性由生产结果生成器保证的基础数值字段。"""

    if isinstance(value, bool) or not isinstance(value, Real):
        _raise_item_error(f"{field_name} 必须是数值", node_id, item_index)
    return float(value)


def _raise_item_error(message: str, node_id: str, item_index: int) -> Any:
    """抛出带稳定 item 定位信息的桥接错误。"""

    raise InvalidRequestError(
        f"Value bridge {message}",
        details={"node_id": node_id, "item_index": item_index},
    )


def _require_path(raw_path: object, *, node_type_id: str) -> str:
    """读取可选点分路径。"""

    if not isinstance(raw_path, str) or not raw_path.strip():
        raise InvalidRequestError(
            "Value bridge 的 path 必须是非空字符串",
            details={"node_type_id": node_type_id},
        )
    return raw_path.strip()


__all__ = [
    "build_value_to_payload_node_spec",
    "require_categories_payload",
    "require_circles_payload",
    "require_detections_payload",
    "require_image_refs_payload",
    "require_obbs_payload",
    "require_poses_payload",
]

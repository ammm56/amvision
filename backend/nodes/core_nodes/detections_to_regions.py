"""detections.v1 转 regions.v1 适配节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._region_node_support import (
    build_class_distribution,
    build_regions_payload,
)
from backend.nodes.core_nodes._roi_node_support import (
    bbox_area,
    bbox_to_polygon_xy,
    normalize_bbox_xyxy,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "detections-to-regions"


def _detections_to_regions_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把标准 detections.v1 结果规整成 regions.v1。"""

    detections_payload = _require_detections_payload(
        request.input_values.get("detections"), node_id=request.node_id
    )
    source_image = _resolve_source_image(request, detections_payload=detections_payload)
    region_id_prefix = _read_region_id_prefix(
        request.parameters.get("region_id_prefix")
    )
    class_id_default = _read_class_id_default(
        request.parameters.get("class_id_default")
    )
    class_name_default = _read_class_name_default(
        request.parameters.get("class_name_default")
    )

    region_items = [
        _build_region_item(
            detection_item=detection_item,
            item_index=item_index,
            region_id_prefix=region_id_prefix,
            class_id_default=class_id_default,
            class_name_default=class_name_default,
        )
        for item_index, detection_item in enumerate(
            detections_payload["items"], start=1
        )
    ]

    return {
        "regions": build_regions_payload(
            source_image=source_image,
            selected_frame_index=None,
            items=region_items,
        ),
        "summary": build_value_payload(
            {
                "original_count": len(detections_payload["items"]),
                "region_count": len(region_items),
                "region_id_prefix": region_id_prefix,
                "class_id_default": class_id_default,
                "class_name_default": class_name_default,
                "source_image_attached": source_image is not None,
                "class_distribution": build_class_distribution(region_items),
            }
        ),
    }


def _require_detections_payload(payload: object, *, node_id: str) -> dict[str, object]:
    """校验 detections.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "detections-to-regions 节点要求 detections payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            "detections-to-regions 节点要求 detections.items 必须是数组",
            details={"node_id": node_id},
        )
    normalized_items = [
        _normalize_detection_item(raw_item, node_id=node_id, item_index=item_index)
        for item_index, raw_item in enumerate(raw_items, start=1)
    ]
    return {
        "source_image": payload.get("source_image"),
        "items": tuple(normalized_items),
    }


def _normalize_detection_item(
    raw_item: object, *, node_id: str, item_index: int
) -> dict[str, object]:
    """规范化单个 detection item。"""

    if not isinstance(raw_item, dict):
        raise InvalidRequestError(
            "detections-to-regions 节点要求每个 detection item 都必须是对象",
            details={"node_id": node_id, "item_index": item_index},
        )
    bbox_xyxy = normalize_bbox_xyxy(
        raw_item.get("bbox_xyxy"), field_name="bbox_xyxy", node_id=node_id
    )
    score = raw_item.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise InvalidRequestError(
            "detections-to-regions 节点要求 detection.score 必须是数值",
            details={"node_id": node_id, "item_index": item_index, "score": score},
        )
    normalized_item: dict[str, object] = {
        "bbox_xyxy": bbox_xyxy,
        "score": float(score),
    }
    if raw_item.get("class_id") is not None:
        class_id = raw_item.get("class_id")
        if isinstance(class_id, bool) or not isinstance(class_id, int):
            raise InvalidRequestError(
                "detections-to-regions 节点要求 detection.class_id 必须是整数",
                details={
                    "node_id": node_id,
                    "item_index": item_index,
                    "class_id": class_id,
                },
            )
        normalized_item["class_id"] = int(class_id)
    if raw_item.get("class_name") is not None:
        class_name = raw_item.get("class_name")
        if not isinstance(class_name, str):
            raise InvalidRequestError(
                "detections-to-regions 节点要求 detection.class_name 必须是字符串",
                details={
                    "node_id": node_id,
                    "item_index": item_index,
                    "class_name": class_name,
                },
            )
        normalized_item["class_name"] = class_name
    for optional_text_field in (
        "region_id",
        "detection_id",
        "track_id",
        "prompt_id",
        "state",
        "source_prompt_text",
    ):
        if raw_item.get(optional_text_field) is not None:
            normalized_item[optional_text_field] = str(
                raw_item.get(optional_text_field)
            )
    for optional_number_field in ("timestamp_ms",):
        if raw_item.get(optional_number_field) is not None:
            optional_value = raw_item.get(optional_number_field)
            if (
                isinstance(optional_value, bool)
                or not isinstance(optional_value, (int, float))
                or float(optional_value) < 0
            ):
                raise InvalidRequestError(
                    f"detections-to-regions 节点要求 detection.{optional_number_field} 必须是非负数",
                    details={
                        "node_id": node_id,
                        "item_index": item_index,
                        optional_number_field: optional_value,
                    },
                )
            normalized_item[optional_number_field] = float(optional_value)
    for optional_int_field in ("frame_index",):
        if raw_item.get(optional_int_field) is not None:
            optional_value = raw_item.get(optional_int_field)
            if (
                isinstance(optional_value, bool)
                or not isinstance(optional_value, int)
                or optional_value < 0
            ):
                raise InvalidRequestError(
                    f"detections-to-regions 节点要求 detection.{optional_int_field} 必须是非负整数",
                    details={
                        "node_id": node_id,
                        "item_index": item_index,
                        optional_int_field: optional_value,
                    },
                )
            normalized_item[optional_int_field] = int(optional_value)
    for optional_list_field in (
        "source_prompt_positive_texts",
        "source_prompt_negative_texts",
    ):
        if raw_item.get(optional_list_field) is not None:
            normalized_item[optional_list_field] = _read_string_list(
                raw_item.get(optional_list_field),
                node_id=node_id,
                item_index=item_index,
                field_name=optional_list_field,
            )
    return normalized_item


def _build_region_item(
    *,
    detection_item: dict[str, object],
    item_index: int,
    region_id_prefix: str,
    class_id_default: int,
    class_name_default: str | None,
) -> dict[str, object]:
    """把 detection item 转成标准 region item。"""

    bbox_xyxy = list(detection_item["bbox_xyxy"])
    class_id = int(detection_item.get("class_id", class_id_default))
    class_name = _resolve_class_name(
        detection_item=detection_item,
        class_id=class_id,
        class_name_default=class_name_default,
    )
    region_item: dict[str, object] = {
        "region_id": _resolve_region_id(
            detection_item=detection_item,
            item_index=item_index,
            region_id_prefix=region_id_prefix,
        ),
        "score": float(detection_item["score"]),
        "class_id": class_id,
        "class_name": class_name,
        "bbox_xyxy": bbox_xyxy,
        "polygon_xy": bbox_to_polygon_xy(bbox_xyxy),
        "area": bbox_area(bbox_xyxy),
    }
    for optional_field in (
        "track_id",
        "prompt_id",
        "state",
        "frame_index",
        "timestamp_ms",
        "source_prompt_text",
        "source_prompt_positive_texts",
        "source_prompt_negative_texts",
    ):
        if optional_field in detection_item:
            region_item[optional_field] = detection_item[optional_field]
    return region_item


def _resolve_source_image(
    request: WorkflowNodeExecutionRequest,
    *,
    detections_payload: dict[str, object],
) -> dict[str, object] | None:
    """优先从显式 image 输入，否则从 detections.source_image 读取 source_image。"""

    if request.input_values.get("image") is not None:
        return require_image_payload(request.input_values.get("image"))
    source_image = detections_payload.get("source_image")
    if isinstance(source_image, dict):
        return require_image_payload(source_image)
    return None


def _resolve_region_id(
    *, detection_item: dict[str, object], item_index: int, region_id_prefix: str
) -> str:
    """解析 region_id。"""

    for field_name in ("region_id", "detection_id"):
        raw_value = detection_item.get(field_name)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return f"{region_id_prefix}-{item_index}"


def _resolve_class_name(
    *,
    detection_item: dict[str, object],
    class_id: int,
    class_name_default: str | None,
) -> str:
    """解析 class_name。"""

    raw_class_name = detection_item.get("class_name")
    if isinstance(raw_class_name, str) and raw_class_name.strip():
        return raw_class_name.strip()
    if class_name_default is not None:
        return class_name_default
    return f"class-{class_id}"


def _read_region_id_prefix(raw_value: object) -> str:
    """读取 region_id 前缀。"""

    if raw_value is None:
        return "det"
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            "detections-to-regions 节点的 region_id_prefix 必须是非空字符串"
        )
    return raw_value.strip()


def _read_class_id_default(raw_value: object) -> int:
    """读取缺省 class_id。"""

    if raw_value is None:
        return -1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(
            "detections-to-regions 节点的 class_id_default 必须是整数"
        )
    return int(raw_value)


def _read_class_name_default(raw_value: object) -> str | None:
    """读取缺省 class_name。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(
            "detections-to-regions 节点的 class_name_default 必须是字符串"
        )
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_string_list(
    raw_value: object,
    *,
    node_id: str,
    item_index: int,
    field_name: str,
) -> list[str]:
    """读取字符串数组字段。"""

    if not isinstance(raw_value, list):
        raise InvalidRequestError(
            f"detections-to-regions 节点要求 detection.{field_name} 必须是字符串数组",
            details={"node_id": node_id, "item_index": item_index},
        )
    normalized_values: list[str] = []
    for value_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, str):
            raise InvalidRequestError(
                f"detections-to-regions 节点要求 detection.{field_name} 必须全部是字符串",
                details={
                    "node_id": node_id,
                    "item_index": item_index,
                    "value_index": value_index,
                },
            )
        normalized_values.append(item_value)
    return normalized_values


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.detections-to-regions",
        display_name="Detections To Regions",
        category="vision.region",
        description="把 detections.v1 里的 bbox 检测结果转成标准 regions.v1，供 ROI、面积、落位和工业规则节点直接复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
            ),
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
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
                "region_id_prefix": {
                    "type": "string",
                    "title": "Region ID 前缀",
                    "default": "det",
                },
                "class_id_default": {
                    "type": "integer",
                    "title": "缺省 Class ID",
                    "default": -1,
                },
                "class_name_default": {
                    "type": "string",
                    "title": "缺省 Class Name",
                },
            },
        },
        capability_tags=(
            "vision.region",
            "vision.region.bridge",
            "inspection.precheck",
        ),
    ),
    handler=_detections_to_regions_handler,
)

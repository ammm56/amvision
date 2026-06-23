"""segments.v1 转 regions.v1 适配节点。"""

from __future__ import annotations

from collections import Counter

import cv2
import numpy as np

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import (
    build_class_distribution,
    build_regions_payload,
)
from backend.nodes.core_nodes.support.roi import (
    bbox_area,
    bbox_to_polygon_xy,
    normalize_bbox_xyxy,
    normalize_polygon_xy,
    polygon_area,
    polygon_bbox_xyxy,
)
from backend.nodes.runtime_support import (
    load_image_bytes_from_payload,
    require_image_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "segments-to-regions"


def _segments_to_regions_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把标准 segments.v1 结果规整成 regions.v1。"""

    segments_payload = _require_segments_payload(
        request.input_values.get("segments"),
        node_id=request.node_id,
    )
    source_image = _resolve_source_image(request, segments_payload=segments_payload)
    region_id_prefix = _read_region_id_prefix(
        request.parameters.get("region_id_prefix")
    )
    class_id_default = _read_class_id_default(
        request.parameters.get("class_id_default")
    )
    class_name_default = _read_class_name_default(
        request.parameters.get("class_name_default")
    )

    geometry_source_counter: Counter[str] = Counter()
    fragmented_mask_region_ids: list[str] = []
    region_items: list[dict[str, object]] = []
    for item_index, segment_item in enumerate(segments_payload["items"], start=1):
        (
            region_item,
            geometry_source,
            mask_fragment_count,
        ) = _build_region_item(
            request,
            segment_item=segment_item,
            item_index=item_index,
            source_image=source_image,
            region_id_prefix=region_id_prefix,
            class_id_default=class_id_default,
            class_name_default=class_name_default,
        )
        geometry_source_counter[geometry_source] += 1
        if geometry_source == "mask-image" and mask_fragment_count > 1:
            fragmented_mask_region_ids.append(str(region_item["region_id"]))
        region_items.append(region_item)

    return {
        "regions": build_regions_payload(
            source_image=source_image,
            selected_frame_index=segments_payload.get("selected_frame_index"),
            items=region_items,
        ),
        "summary": build_value_payload(
            {
                "original_count": len(segments_payload["items"]),
                "region_count": len(region_items),
                "region_id_prefix": region_id_prefix,
                "class_id_default": class_id_default,
                "class_name_default": class_name_default,
                "source_image_attached": source_image is not None,
                "geometry_source_counts": dict(
                    sorted(geometry_source_counter.items(), key=lambda item: item[0])
                ),
                "fragmented_mask_segment_count": len(fragmented_mask_region_ids),
                "fragmented_mask_region_ids": fragmented_mask_region_ids,
                "class_distribution": build_class_distribution(region_items),
            }
        ),
    }


def _require_segments_payload(payload: object, *, node_id: str) -> dict[str, object]:
    """校验 segments.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "segments-to-regions 节点要求 segments payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            "segments-to-regions 节点要求 segments.items 必须是数组",
            details={"node_id": node_id},
        )
    selected_frame_index = payload.get("selected_frame_index")
    if selected_frame_index is not None and (
        isinstance(selected_frame_index, bool)
        or not isinstance(selected_frame_index, int)
        or selected_frame_index < 0
    ):
        raise InvalidRequestError(
            "segments-to-regions 节点要求 segments.selected_frame_index 必须是非负整数",
            details={"node_id": node_id, "selected_frame_index": selected_frame_index},
        )
    normalized_items = [
        _normalize_segment_item(raw_item, node_id=node_id, item_index=item_index)
        for item_index, raw_item in enumerate(raw_items, start=1)
    ]
    return {
        "source_image": payload.get("source_image"),
        "selected_frame_index": selected_frame_index,
        "items": tuple(normalized_items),
    }


def _normalize_segment_item(
    raw_item: object,
    *,
    node_id: str,
    item_index: int,
) -> dict[str, object]:
    """规范化单个 segment item。"""

    if not isinstance(raw_item, dict):
        raise InvalidRequestError(
            "segments-to-regions 节点要求每个 segment item 都必须是对象",
            details={"node_id": node_id, "item_index": item_index},
        )
    score = raw_item.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise InvalidRequestError(
            "segments-to-regions 节点要求 segment.score 必须是数值",
            details={"node_id": node_id, "item_index": item_index, "score": score},
        )
    normalized_item: dict[str, object] = {
        "score": float(score),
    }
    if raw_item.get("bbox_xyxy") is not None:
        normalized_item["bbox_xyxy"] = normalize_bbox_xyxy(
            raw_item.get("bbox_xyxy"),
            field_name="bbox_xyxy",
            node_id=node_id,
        )
    if raw_item.get("polygon_xy") is not None:
        normalized_item["polygon_xy"] = normalize_polygon_xy(
            raw_item.get("polygon_xy"),
            field_name="polygon_xy",
            node_id=node_id,
        )
    if raw_item.get("mask_image") is not None:
        normalized_item["mask_image"] = require_image_payload(
            raw_item.get("mask_image")
        )
    if not any(
        field_name in normalized_item
        for field_name in ("mask_image", "polygon_xy", "bbox_xyxy")
    ):
        raise InvalidRequestError(
            "segments-to-regions 节点要求每个 segment 至少包含 mask_image、polygon_xy 或 bbox_xyxy 之一",
            details={"node_id": node_id, "item_index": item_index},
        )
    if raw_item.get("class_id") is not None:
        class_id = raw_item.get("class_id")
        if isinstance(class_id, bool) or not isinstance(class_id, int):
            raise InvalidRequestError(
                "segments-to-regions 节点要求 segment.class_id 必须是整数",
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
                "segments-to-regions 节点要求 segment.class_name 必须是字符串",
                details={
                    "node_id": node_id,
                    "item_index": item_index,
                    "class_name": class_name,
                },
            )
        normalized_item["class_name"] = class_name
    for optional_text_field in (
        "region_id",
        "segment_id",
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
                    f"segments-to-regions 节点要求 segment.{optional_number_field} 必须是非负数",
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
                    f"segments-to-regions 节点要求 segment.{optional_int_field} 必须是非负整数",
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
    request: WorkflowNodeExecutionRequest,
    *,
    segment_item: dict[str, object],
    item_index: int,
    source_image: dict[str, object] | None,
    region_id_prefix: str,
    class_id_default: int,
    class_name_default: str | None,
) -> tuple[dict[str, object], str, int]:
    """把 segment item 转成标准 region item。"""

    bbox_xyxy: list[float]
    polygon_xy: list[list[float]]
    area: int
    geometry_source: str
    mask_fragment_count = 0

    if "mask_image" in segment_item:
        bbox_xyxy, polygon_xy, area, mask_fragment_count = _extract_mask_geometry(
            request,
            mask_payload=segment_item["mask_image"],
            source_image=source_image,
        )
        geometry_source = "mask-image"
    elif "polygon_xy" in segment_item:
        polygon_xy = [list(point) for point in segment_item["polygon_xy"]]
        bbox_xyxy = polygon_bbox_xyxy(polygon_xy)
        area = polygon_area(polygon_xy)
        if area <= 0:
            raise InvalidRequestError(
                "segments-to-regions 节点要求 polygon_xy 形成的区域面积必须大于 0",
                details={"item_index": item_index},
            )
        geometry_source = "polygon"
    else:
        bbox_xyxy = list(segment_item["bbox_xyxy"])
        polygon_xy = bbox_to_polygon_xy(bbox_xyxy)
        area = bbox_area(bbox_xyxy)
        if area <= 0:
            raise InvalidRequestError(
                "segments-to-regions 节点要求 bbox_xyxy 形成的区域面积必须大于 0",
                details={"item_index": item_index},
            )
        geometry_source = "bbox"

    class_id = int(segment_item.get("class_id", class_id_default))
    class_name = _resolve_class_name(
        segment_item=segment_item,
        class_id=class_id,
        class_name_default=class_name_default,
    )
    region_item: dict[str, object] = {
        "region_id": _resolve_region_id(
            segment_item=segment_item,
            item_index=item_index,
            region_id_prefix=region_id_prefix,
        ),
        "score": float(segment_item["score"]),
        "class_id": class_id,
        "class_name": class_name,
        "bbox_xyxy": bbox_xyxy,
        "polygon_xy": polygon_xy,
        "area": area,
    }
    if "mask_image" in segment_item:
        region_item["mask_image"] = dict(segment_item["mask_image"])
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
        if optional_field in segment_item:
            region_item[optional_field] = segment_item[optional_field]
    return region_item, geometry_source, mask_fragment_count


def _extract_mask_geometry(
    request: WorkflowNodeExecutionRequest,
    *,
    mask_payload: dict[str, object],
    source_image: dict[str, object] | None,
) -> tuple[list[float], list[list[float]], int, int]:
    """从 mask_image 提取 bbox、polygon 和 area。"""

    _normalized_payload, image_bytes = load_image_bytes_from_payload(
        request,
        image_payload=mask_payload,
    )
    image_matrix = cv2.imdecode(
        np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
    )
    if image_matrix is None:
        raise InvalidRequestError("segments-to-regions 节点无法解码 segment.mask_image")
    binary_mask = (image_matrix > 0).astype(np.uint8)
    area = int(np.count_nonzero(binary_mask))
    if area <= 0:
        raise InvalidRequestError(
            "segments-to-regions 节点要求 segment.mask_image 不能为空"
        )
    mask_height, mask_width = binary_mask.shape
    _validate_mask_alignment(
        source_image=source_image,
        mask_width=mask_width,
        mask_height=mask_height,
    )
    ys, xs = np.nonzero(binary_mask)
    bbox_xyxy = [
        float(np.min(xs)),
        float(np.min(ys)),
        float(np.max(xs) + 1),
        float(np.max(ys) + 1),
    ]
    fragment_count = int(cv2.connectedComponents(binary_mask, connectivity=8)[0] - 1)
    contours, _hierarchy = cv2.findContours(
        binary_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        contour_points = largest_contour.reshape(-1, 2).tolist()
        if len(contour_points) >= 3:
            polygon_xy = [
                [float(point_x), float(point_y)] for point_x, point_y in contour_points
            ]
            return bbox_xyxy, polygon_xy, area, fragment_count
    return bbox_xyxy, bbox_to_polygon_xy(bbox_xyxy), area, fragment_count


def _validate_mask_alignment(
    *,
    source_image: dict[str, object] | None,
    mask_width: int,
    mask_height: int,
) -> None:
    """校验 mask_image 与 source_image 的尺寸是否一致。"""

    if not isinstance(source_image, dict):
        return
    source_width = source_image.get("width")
    source_height = source_image.get("height")
    if (
        isinstance(source_width, int)
        and source_width > 0
        and isinstance(source_height, int)
        and source_height > 0
        and (source_width != mask_width or source_height != mask_height)
    ):
        raise InvalidRequestError(
            "segments-to-regions 节点要求 segment.mask_image 与 source_image 尺寸一致",
            details={
                "source_width": source_width,
                "source_height": source_height,
                "mask_width": mask_width,
                "mask_height": mask_height,
            },
        )


def _resolve_source_image(
    request: WorkflowNodeExecutionRequest,
    *,
    segments_payload: dict[str, object],
) -> dict[str, object] | None:
    """优先从显式 image 输入，否则从 segments.source_image 读取 source_image。"""

    if request.input_values.get("image") is not None:
        return require_image_payload(request.input_values.get("image"))
    source_image = segments_payload.get("source_image")
    if isinstance(source_image, dict):
        return require_image_payload(source_image)
    return None


def _resolve_region_id(
    *,
    segment_item: dict[str, object],
    item_index: int,
    region_id_prefix: str,
) -> str:
    """解析 region_id。"""

    for field_name in ("region_id", "segment_id"):
        raw_value = segment_item.get(field_name)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return f"{region_id_prefix}-{item_index}"


def _resolve_class_name(
    *,
    segment_item: dict[str, object],
    class_id: int,
    class_name_default: str | None,
) -> str:
    """解析 class_name。"""

    raw_class_name = segment_item.get("class_name")
    if isinstance(raw_class_name, str) and raw_class_name.strip():
        return raw_class_name.strip()
    if class_name_default is not None:
        return class_name_default
    return f"class-{class_id}"


def _read_region_id_prefix(raw_value: object) -> str:
    """读取 region_id 前缀。"""

    if raw_value is None:
        return "seg"
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            "segments-to-regions 节点的 region_id_prefix 必须是非空字符串"
        )
    return raw_value.strip()


def _read_class_id_default(raw_value: object) -> int:
    """读取缺省 class_id。"""

    if raw_value is None:
        return -1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(
            "segments-to-regions 节点的 class_id_default 必须是整数"
        )
    return int(raw_value)


def _read_class_name_default(raw_value: object) -> str | None:
    """读取缺省 class_name。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(
            "segments-to-regions 节点的 class_name_default 必须是字符串"
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
            f"segments-to-regions 节点要求 segment.{field_name} 必须是字符串数组",
            details={"node_id": node_id, "item_index": item_index},
        )
    normalized_values: list[str] = []
    for value_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, str):
            raise InvalidRequestError(
                f"segments-to-regions 节点要求 segment.{field_name} 必须全部是字符串",
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
        node_type_id="core.vision.segments-to-regions",
        display_name="Segments To Regions",
        category="vision.region",
        description="把 segments.v1 里的 mask、polygon 或 bbox 分割结果转成标准 regions.v1，供面积、连续性、ROI 和工业规则节点直接复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="segments",
                display_name="Segments",
                payload_type_id="segments.v1",
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
                    "default": "seg",
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
            "vision.segmentation",
            "inspection.precheck",
        ),
    ),
    handler=_segments_to_regions_handler,
)

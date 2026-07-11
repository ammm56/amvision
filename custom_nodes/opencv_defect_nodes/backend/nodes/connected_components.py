"""Connected Components 节点实现。"""

from __future__ import annotations

from backend.nodes import register_image_bytes
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import (
    build_class_distribution,
    build_regions_payload,
)
from backend.nodes.core_nodes.support.roi import bbox_to_polygon_xy
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_connected_components_connectivity,
    require_non_negative_float,
    require_positive_int,
    require_uint8_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.connected-components"


def _read_optional_non_negative_float(raw_value: object, *, field_name: str) -> float | None:
    """读取可选非负浮点参数。"""

    if raw_value in {None, ""}:
        return None
    return require_non_negative_float(raw_value, field_name=field_name)


def _read_region_id_prefix(raw_value: object) -> str:
    """读取 region_id 前缀。"""

    if raw_value is None:
        return "cc"
    return str(raw_value).strip() or "cc"


def _read_class_id_default(raw_value: object) -> int:
    """读取缺省 class_id。"""

    if raw_value is None:
        return -1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("connected-components 节点的 class_id_default 必须是整数")
    return int(raw_value)


def _read_class_name_default(raw_value: object) -> str:
    """读取缺省 class_name。"""

    if raw_value is None:
        return "component"
    normalized_value = str(raw_value).strip()
    return normalized_value or "component"


def _read_score_default(raw_value: object) -> float:
    """读取缺省 score。"""

    if raw_value is None:
        return 1.0
    return require_non_negative_float(raw_value, field_name="score_default")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把二值前景图规整成结构化缺陷区域。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    raw_source_image = request.input_values.get("source_image")
    source_image = require_image_payload(raw_source_image) if raw_source_image is not None else dict(image_payload)

    raw_foreground_threshold = request.parameters.get("foreground_threshold")
    foreground_threshold = (
        0
        if raw_foreground_threshold in {None, ""}
        else require_uint8_int(raw_foreground_threshold, field_name="foreground_threshold")
    )
    raw_connectivity = request.parameters.get("connectivity")
    connectivity = 8 if raw_connectivity in {None, ""} else normalize_connected_components_connectivity(raw_connectivity)
    min_area = _read_optional_non_negative_float(request.parameters.get("min_area"), field_name="min_area")
    max_area = _read_optional_non_negative_float(request.parameters.get("max_area"), field_name="max_area")
    raw_max_components = request.parameters.get("max_components")
    max_components = None if raw_max_components in {None, ""} else require_positive_int(raw_max_components, field_name="max_components")
    region_id_prefix = _read_region_id_prefix(request.parameters.get("region_id_prefix"))
    class_id_default = _read_class_id_default(request.parameters.get("class_id_default"))
    class_name_default = _read_class_name_default(request.parameters.get("class_name_default"))
    score_default = _read_score_default(request.parameters.get("score_default"))

    binary_mask = (image_matrix > foreground_threshold).astype(np_module.uint8)
    label_count, labels_matrix, stats, _centroids = cv2_module.connectedComponentsWithStats(
        binary_mask,
        connectivity=connectivity,
    )
    component_items: list[tuple[int, int, dict[str, object]]] = []
    rejected_component_labels: list[int] = []
    for label_index in range(1, int(label_count)):
        area = int(stats[label_index, cv2_module.CC_STAT_AREA])
        if min_area is not None and float(area) < min_area:
            rejected_component_labels.append(label_index)
            continue
        if max_area is not None and float(area) > max_area:
            rejected_component_labels.append(label_index)
            continue
        component_mask = (labels_matrix == label_index).astype(np_module.uint8)
        bbox_left = int(stats[label_index, cv2_module.CC_STAT_LEFT])
        bbox_top = int(stats[label_index, cv2_module.CC_STAT_TOP])
        bbox_width = int(stats[label_index, cv2_module.CC_STAT_WIDTH])
        bbox_height = int(stats[label_index, cv2_module.CC_STAT_HEIGHT])
        bbox_xyxy = [
            float(bbox_left),
            float(bbox_top),
            float(bbox_left + bbox_width),
            float(bbox_top + bbox_height),
        ]
        contours, _hierarchy = cv2_module.findContours(
            component_mask,
            cv2_module.RETR_EXTERNAL,
            cv2_module.CHAIN_APPROX_SIMPLE,
        )
        if contours:
            largest_contour = max(contours, key=cv2_module.contourArea)
            polygon_xy = [
                [float(point_x), float(point_y)]
                for point_x, point_y in largest_contour.reshape(-1, 2).tolist()
            ]
        else:
            polygon_xy = [[float(point[0]), float(point[1])] for point in bbox_to_polygon_xy(bbox_xyxy)]
        encoded_mask_bytes = bytes(
            encode_png_image_bytes(
                request,
                image_matrix=(component_mask * 255).astype(np_module.uint8),
                error_message="OpenCV connected-components 无法编码组件 mask",
            )
        )
        mask_payload = register_image_bytes(
            request,
            content=encoded_mask_bytes,
            media_type="image/png",
            width=int(component_mask.shape[1]),
            height=int(component_mask.shape[0]),
            created_by_node_id=request.node_id,
        )
        component_items.append(
            (
                label_index,
                area,
                {
                    "score": float(score_default),
                    "class_id": int(class_id_default),
                    "class_name": class_name_default,
                    "bbox_xyxy": bbox_xyxy,
                    "polygon_xy": polygon_xy,
                    "mask_image": mask_payload,
                    "area": int(area),
                    "component_label": int(label_index),
                },
            )
        )

    component_items.sort(key=lambda current_item: (-current_item[1], current_item[0]))
    if max_components is not None:
        component_items = component_items[:max_components]

    region_items: list[dict[str, object]] = []
    for item_index, (label_index, _area, region_item) in enumerate(component_items, start=1):
        normalized_region_item = dict(region_item)
        normalized_region_item["region_id"] = f"{region_id_prefix}-{item_index}"
        normalized_region_item["component_label"] = int(label_index)
        region_items.append(normalized_region_item)

    return {
        "regions": build_regions_payload(
            source_image=source_image,
            selected_frame_index=None,
            items=region_items,
        ),
        "summary": build_value_payload(
            {
                "foreground_threshold": int(foreground_threshold),
                "connectivity": int(connectivity),
                "original_component_count": max(0, int(label_count) - 1),
                "region_count": len(region_items),
                "rejected_component_count": len(rejected_component_labels),
                "rejected_component_labels": rejected_component_labels,
                "min_area": min_area,
                "max_area": max_area,
                "max_components": max_components,
                "region_id_prefix": region_id_prefix,
                "class_id_default": class_id_default,
                "class_name_default": class_name_default,
                "score_default": score_default,
                "total_area": sum(int(item["area"]) for item in region_items),
                "class_distribution": build_class_distribution(region_items),
            }
        ),
    }

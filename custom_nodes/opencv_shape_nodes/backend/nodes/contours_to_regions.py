"""Contours To Regions 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import (
    build_class_distribution,
    build_regions_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    compute_contour_metrics_from_points,
    require_contours_payload,
    require_non_negative_float,
    require_opencv_imports,
    resolve_contours_source_image,
)


NODE_TYPE_ID = "custom.opencv.contours-to-regions"


def _read_region_id_prefix(raw_value: object) -> str:
    """读取 region_id 前缀。"""

    if raw_value is None:
        return "ctr"
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("contours-to-regions 节点的 region_id_prefix 必须是非空字符串")
    return raw_value.strip()


def _read_class_id_default(raw_value: object) -> int:
    """读取缺省 class_id。"""

    if raw_value is None:
        return -1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("contours-to-regions 节点的 class_id_default 必须是整数")
    return int(raw_value)


def _read_class_name_default(raw_value: object) -> str:
    """读取缺省 class_name。"""

    if raw_value is None:
        return "contour"
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("contours-to-regions 节点的 class_name_default 必须是非空字符串")
    return raw_value.strip()


def _read_score_default(raw_value: object) -> float:
    """读取缺省 score。"""

    if raw_value is None:
        return 1.0
    return require_non_negative_float(raw_value, field_name="score_default")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 contours.v1 规整成标准 regions.v1。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    source_image = resolve_contours_source_image(
        contours_payload=contours_payload,
        image_payload=request.input_values.get("image"),
    )
    region_id_prefix = _read_region_id_prefix(request.parameters.get("region_id_prefix"))
    class_id_default = _read_class_id_default(request.parameters.get("class_id_default"))
    class_name_default = _read_class_name_default(request.parameters.get("class_name_default"))
    score_default = _read_score_default(request.parameters.get("score_default"))

    region_items: list[dict[str, object]] = []
    skipped_contour_indexes: list[int] = []
    for item_index, contour_item in enumerate(contours_payload["items"], start=1):
        contour_metrics = compute_contour_metrics_from_points(
            points=contour_item["points"],
            cv2_module=cv2_module,
            np_module=np_module,
        )
        area = max(0, int(round(float(contour_metrics["area"]))))
        if area <= 0:
            skipped_contour_indexes.append(int(contour_item["contour_index"]))
            continue
        region_items.append(
            {
                "region_id": f"{region_id_prefix}-{item_index}",
                "score": float(score_default),
                "class_id": int(class_id_default),
                "class_name": class_name_default,
                "bbox_xyxy": [float(value) for value in contour_metrics["bbox_xyxy"]],
                "polygon_xy": [
                    [float(point[0]), float(point[1])]
                    for point in contour_item["points"]
                ],
                "area": area,
                "contour_index": int(contour_item["contour_index"]),
                "point_count": int(contour_item["point_count"]),
            }
        )

    return {
        "regions": build_regions_payload(
            source_image=source_image,
            selected_frame_index=None,
            items=region_items,
        ),
        "summary": build_value_payload(
            {
                "original_count": len(contours_payload["items"]),
                "region_count": len(region_items),
                "skipped_count": len(skipped_contour_indexes),
                "skipped_contour_indexes": skipped_contour_indexes,
                "region_id_prefix": region_id_prefix,
                "class_id_default": class_id_default,
                "class_name_default": class_name_default,
                "score_default": score_default,
                "source_image_attached": source_image is not None,
                "total_area": sum(int(item["area"]) for item in region_items),
                "class_distribution": build_class_distribution(region_items),
            }
        ),
    }

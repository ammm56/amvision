"""Contour To ROI 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import (
    build_roi_payload,
    normalize_bbox_xyxy,
    normalize_polygon_xy,
    polygon_area,
    polygon_bbox_xyxy,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.geometry import contour_points_to_matrix
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import (
    require_contours_payload,
    resolve_contours_source_image,
)
from custom_nodes._opencv_shared.backend.runtime.validators import require_non_negative_int


NODE_TYPE_ID = "custom.opencv.contour-to-roi"


def _read_contour_index(raw_value: object) -> int:
    """读取 contours.items 中的序号，默认使用第一个 contour。"""

    if raw_value in {None, ""}:
        return 0
    return int(require_non_negative_int(raw_value, field_name="contour_index"))


def _read_roi_kind(raw_value: object) -> str:
    """读取 ROI 类型。"""

    if raw_value in {None, ""}:
        return "polygon"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("contour-to-roi 节点的 roi_kind 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"polygon", "bbox"}:
        raise InvalidRequestError("contour-to-roi 节点的 roi_kind 仅支持 polygon 或 bbox")
    return normalized_value


def _read_require_quad(raw_value: object) -> bool:
    """读取是否强制要求四点轮廓。"""

    if raw_value in {None, ""}:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("contour-to-roi 节点的 require_quad 必须是布尔值")
    return raw_value


def _read_polygon_mode(raw_value: object) -> str:
    """读取 polygon 生成方式。"""

    if raw_value in {None, ""}:
        return "contour-points"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("contour-to-roi 节点的 polygon_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"contour-points", "min-area-rect", "bbox"}:
        raise InvalidRequestError(
            "contour-to-roi 节点的 polygon_mode 仅支持 contour-points、min-area-rect 或 bbox"
        )
    return normalized_value


def _read_text(raw_value: object, *, default_value: str) -> str:
    """读取可选文本参数。"""

    if raw_value in {None, ""}:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("contour-to-roi 节点的文本参数必须是非空字符串")
    return raw_value.strip()


def _build_bbox_polygon(bbox_xyxy: list[float]) -> list[list[float]]:
    """把 bbox 转成四点 polygon。"""

    return [
        [bbox_xyxy[0], bbox_xyxy[1]],
        [bbox_xyxy[2], bbox_xyxy[1]],
        [bbox_xyxy[2], bbox_xyxy[3]],
        [bbox_xyxy[0], bbox_xyxy[3]],
    ]


def _build_polygon_points(
    *,
    source_points: list[list[float]],
    bbox_xyxy: object,
    polygon_mode: str,
) -> list[list[float]]:
    """按配置把 contour 转成可供 ROI 使用的 polygon 点集。"""

    if polygon_mode == "contour-points":
        return source_points
    if polygon_mode == "bbox":
        normalized_bbox = normalize_bbox_xyxy(bbox_xyxy, field_name="bbox_xyxy")
        return _build_bbox_polygon(normalized_bbox)

    cv2_module, np_module = require_opencv_imports()
    contour_matrix = contour_points_to_matrix(
        points=[[int(round(point[0])), int(round(point[1]))] for point in source_points],
        np_module=np_module,
    )
    rotated_rect = cv2_module.minAreaRect(contour_matrix)
    box_points = cv2_module.boxPoints(rotated_rect).tolist()
    return [[round(float(point[0]), 4), round(float(point[1]), 4)] for point in box_points]


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把一个 contour item 转换为正式 roi.v1。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 roi.v1 与 value.v1 摘要的输出。
    """

    contours_payload = require_contours_payload(request.input_values.get("contours"))
    contour_index = _read_contour_index(request.parameters.get("contour_index"))
    roi_kind = _read_roi_kind(request.parameters.get("roi_kind"))
    require_quad = _read_require_quad(request.parameters.get("require_quad"))
    polygon_mode = _read_polygon_mode(request.parameters.get("polygon_mode"))
    roi_id_prefix = _read_text(request.parameters.get("roi_id_prefix"), default_value="contour-roi")
    display_name_prefix = _read_text(
        request.parameters.get("display_name_prefix"),
        default_value="Contour ROI",
    )

    contour_items = contours_payload["items"]
    if not contour_items:
        raise InvalidRequestError("contour-to-roi 节点要求 contours.items 不能为空")
    if contour_index >= len(contour_items):
        raise InvalidRequestError(
            "contour-to-roi 节点的 contour_index 超出范围",
            details={"contour_index": contour_index, "count": len(contour_items)},
        )

    contour_item = contour_items[contour_index]
    source_points = normalize_polygon_xy(
        contour_item.get("points"),
        field_name="contour.points",
        node_id=request.node_id,
    )
    points = _build_polygon_points(
        source_points=source_points,
        bbox_xyxy=contour_item.get("bbox_xyxy"),
        polygon_mode=polygon_mode,
    )
    if require_quad and len(points) != 4:
        raise InvalidRequestError(
            "contour-to-roi 节点当前要求 contour.points 必须是四点轮廓",
            details={
                "node_id": request.node_id,
                "contour_index": contour_index,
                "point_count": len(points),
            },
        )

    bbox_xyxy = normalize_bbox_xyxy(
        contour_item.get("bbox_xyxy"),
        field_name="bbox_xyxy",
        node_id=request.node_id,
    ) if roi_kind == "bbox" else polygon_bbox_xyxy(points)
    polygon_xy = _build_bbox_polygon(bbox_xyxy) if roi_kind == "bbox" else points
    area = int(round(polygon_area(polygon_xy)))
    contour_original_index = int(contour_item["contour_index"])
    source_image = resolve_contours_source_image(
        contours_payload=contours_payload,
        image_payload=request.input_values.get("image"),
    )
    roi_payload = build_roi_payload(
        roi_id=f"{roi_id_prefix}-{contour_original_index}",
        display_name=f"{display_name_prefix} {contour_original_index}",
        roi_kind=roi_kind,
        bbox_xyxy=bbox_xyxy,
        polygon_xy=polygon_xy,
        area=area,
        source_image=source_image,
    )

    return {
        "roi": roi_payload,
        "summary": build_value_payload(
            {
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_kind,
                "contour_index": contour_original_index,
                "selected_index": contour_index,
                "source_point_count": len(source_points),
                "point_count": len(points),
                "polygon_mode": polygon_mode,
                "bbox_xyxy": roi_payload["bbox_xyxy"],
                "area": area,
                "source_image_attached": source_image is not None,
            }
        ),
    }

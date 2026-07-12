"""contours.v1 payload 校验、规范化和几何转换工具。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from typing import Any

from backend.nodes.core_nodes.support.roi import normalize_bbox_xyxy
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError


def require_contours_payload(
    payload: object,
    *,
    node_id: str | None = None,
) -> dict[str, object]:
    """校验并规范化 contours.v1 payload。

    参数：
    - payload：待校验的 contours.v1 payload。
    - node_id：当前节点 id，用于错误详情定位。

    返回：
    - dict[str, object]：规范化后的 contours.v1 payload。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "contours 节点要求 contours.v1 payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            "contours.v1 payload 缺少有效 items 数组",
            details={"node_id": node_id},
        )

    normalized_items: list[dict[str, object]] = []
    for fallback_index, raw_item in enumerate(raw_items):
        normalized_items.append(
            _normalize_contour_item(
                raw_item,
                fallback_index=fallback_index,
                node_id=node_id,
            )
        )

    normalized_payload = dict(payload)
    normalized_payload["items"] = normalized_items
    normalized_payload["count"] = _read_count(payload.get("count"), default_value=len(normalized_items), node_id=node_id)

    source_image = payload.get("source_image")
    if isinstance(source_image, dict):
        normalized_payload["source_image"] = require_image_payload(source_image)
    elif source_image is not None:
        raise InvalidRequestError(
            "contours.v1 payload 的 source_image 必须是 image-ref 对象",
            details={"node_id": node_id},
        )
    source_object_key = payload.get("source_object_key")
    if isinstance(source_object_key, str) and source_object_key.strip():
        normalized_payload["source_object_key"] = source_object_key.strip()
    elif source_object_key is not None:
        normalized_payload.pop("source_object_key", None)
    return normalized_payload


def resolve_contours_source_image(
    *,
    contours_payload: dict[str, object],
    image_payload: object | None,
) -> dict[str, object] | None:
    """优先读取显式 image 输入，否则回退到 contours.source_image。

    参数：
    - contours_payload：已规范化的 contours.v1 payload。
    - image_payload：节点显式传入的 image-ref payload。

    返回：
    - dict[str, object] | None：可用于 ROI 追溯的 image-ref payload。
    """

    if image_payload is not None:
        return require_image_payload(image_payload)
    source_image = contours_payload.get("source_image")
    if isinstance(source_image, dict):
        return require_image_payload(source_image)
    return None


def contour_points_to_matrix(*, points: list[list[float]], np_module: Any) -> Any:
    """把 contour 点集转换成 OpenCV contour matrix。

    参数：
    - points：contour 点集。
    - np_module：NumPy 模块对象。

    返回：
    - Any：OpenCV 可直接处理的 contour matrix。
    """

    if not points:
        raise InvalidRequestError("contour.points 不能为空")
    integer_points = [[int(round(point[0])), int(round(point[1]))] for point in points]
    return np_module.array(integer_points, dtype=np_module.int32).reshape((-1, 1, 2))


def _normalize_contour_item(
    raw_item: object,
    *,
    fallback_index: int,
    node_id: str | None,
) -> dict[str, object]:
    """规范化单个 contour item。"""

    if not isinstance(raw_item, dict):
        raise InvalidRequestError(
            "contours.v1 payload 的每个 item 必须是对象",
            details={"node_id": node_id},
        )
    normalized_points = _normalize_points(raw_item.get("points"), node_id=node_id)
    normalized_item = dict(raw_item)
    normalized_item["contour_index"] = _read_contour_index(
        raw_item.get("contour_index"),
        default_value=fallback_index,
        node_id=node_id,
    )
    normalized_item["point_count"] = _read_count(
        raw_item.get("point_count"),
        default_value=len(normalized_points),
        node_id=node_id,
    )
    normalized_item["bbox_xyxy"] = normalize_bbox_xyxy(
        raw_item.get("bbox_xyxy"),
        field_name="contour.bbox_xyxy",
        node_id=node_id,
    )
    normalized_item["points"] = normalized_points
    return normalized_item


def _normalize_points(raw_points: object, *, node_id: str | None) -> list[list[float]]:
    """规范化 contour.points。"""

    if not isinstance(raw_points, list) or len(raw_points) < 3:
        raise InvalidRequestError(
            "contour.points 必须是至少 3 个点的数组",
            details={"node_id": node_id},
        )
    normalized_points: list[list[float]] = []
    for point_index, raw_point in enumerate(raw_points):
        if not isinstance(raw_point, list) or len(raw_point) < 2:
            raise InvalidRequestError(
                "contour.points 中的每个点必须包含 x 与 y",
                details={"node_id": node_id, "point_index": point_index},
            )
        point_x, point_y = raw_point[:2]
        if (
            isinstance(point_x, bool)
            or isinstance(point_y, bool)
            or not isinstance(point_x, (int, float))
            or not isinstance(point_y, (int, float))
        ):
            raise InvalidRequestError(
                "contour.points 中的点坐标必须是数值",
                details={"node_id": node_id, "point_index": point_index},
            )
        normalized_points.append([float(point_x), float(point_y)])
    return normalized_points


def _read_contour_index(raw_value: object, *, default_value: int, node_id: str | None) -> int:
    """读取 contour_index。"""

    if is_empty_parameter(raw_value):
        return int(default_value)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(
            "contour_index 必须是非负整数",
            details={"node_id": node_id},
        )
    return int(raw_value)


def _read_count(raw_value: object, *, default_value: int, node_id: str | None) -> int:
    """读取 count 或 point_count。"""

    if is_empty_parameter(raw_value):
        return int(default_value)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(
            "contours.v1 count 字段必须是非负整数",
            details={"node_id": node_id},
        )
    return int(raw_value)

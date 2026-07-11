"""roi.v1 / roi-list.v1 payload 构造和校验。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.roi.geometry import (
    normalize_bbox_xyxy,
    normalize_polygon_xy,
)
from backend.service.application.errors import InvalidRequestError


def build_roi_payload(
    *,
    roi_id: str,
    display_name: str | None,
    roi_kind: str,
    bbox_xyxy: list[float],
    polygon_xy: list[list[float]],
    area: int,
    source_image: object | None = None,
) -> dict[str, object]:
    """构建规范化后的 roi.v1 payload。"""

    payload: dict[str, object] = {
        "roi_id": roi_id,
        "roi_kind": roi_kind,
        "bbox_xyxy": [float(value) for value in bbox_xyxy],
        "polygon_xy": [[float(point[0]), float(point[1])] for point in polygon_xy],
        "area": int(area),
    }
    if display_name:
        payload["display_name"] = display_name
    if isinstance(source_image, dict):
        payload["source_image"] = dict(source_image)
    return payload


def require_roi_payload(payload: object, *, node_id: str | None = None) -> dict[str, object]:
    """校验并规范化 roi.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "ROI 节点要求 roi.v1 payload 必须是对象",
            details={"node_id": node_id},
        )
    roi_id = payload.get("roi_id")
    roi_kind = payload.get("roi_kind")
    bbox_xyxy = payload.get("bbox_xyxy")
    polygon_xy = payload.get("polygon_xy")
    area = payload.get("area")
    if not isinstance(roi_id, str) or not roi_id.strip():
        raise InvalidRequestError("roi.v1 payload 缺少有效 roi_id", details={"node_id": node_id})
    if roi_kind not in {"bbox", "polygon"}:
        raise InvalidRequestError("roi.v1 payload 缺少有效 roi_kind", details={"node_id": node_id})
    normalized_bbox = normalize_bbox_xyxy(bbox_xyxy, field_name="bbox_xyxy", node_id=node_id)
    normalized_polygon = normalize_polygon_xy(polygon_xy, field_name="polygon_xy", node_id=node_id)
    if isinstance(area, bool) or not isinstance(area, int) or area < 0:
        raise InvalidRequestError("roi.v1 payload 缺少有效 area", details={"node_id": node_id})
    return build_roi_payload(
        roi_id=roi_id.strip(),
        display_name=str(payload.get("display_name")).strip()
        if isinstance(payload.get("display_name"), str)
        else None,
        roi_kind=str(roi_kind),
        bbox_xyxy=normalized_bbox,
        polygon_xy=normalized_polygon,
        area=int(area),
        source_image=payload.get("source_image"),
    )


def build_roi_list_payload(roi_items: list[dict[str, object]]) -> dict[str, object]:
    """构建明确的 roi-list.v1 payload。

    参数：
    - roi_items：已经规范化或可规范化的 roi.v1 列表。

    返回：
    - dict[str, object]：包含 items 和 count 的 ROI 列表 payload。
    """

    normalized_items = [require_roi_payload(item) for item in roi_items]
    return {
        "format_id": "amvision.roi-list.v1",
        "items": normalized_items,
        "count": len(normalized_items),
    }


def require_roi_list_payload(
    payload: object,
    *,
    node_id: str | None = None,
    field_name: str = "rois",
) -> dict[str, object]:
    """校验并规范化 roi-list.v1 payload。

    参数：
    - payload：roi-list.v1、roi.v1 数组或可展开的 ROI 容器。
    - node_id：当前节点 id，用于错误定位。
    - field_name：错误消息中显示的字段名称。

    返回：
    - dict[str, object]：规范化后的 roi-list.v1 payload。
    """

    return build_roi_list_payload(
        iter_roi_payloads(payload, node_id=node_id, field_name=field_name)
    )


def iter_roi_payloads(
    payload: object,
    *,
    node_id: str | None = None,
    field_name: str = "rois",
) -> list[dict[str, object]]:
    """把单个 ROI、多个 ROI、roi-list.v1 或 value.v1 包装的 ROI 列表统一规范化。

    参数：
    - payload：可为 roi.v1、roi.v1 数组、roi-list.v1、value.v1，或包含 items 的对象。
    - node_id：当前节点 id，用于错误定位。
    - field_name：错误消息中使用的字段名称。

    返回：
    - list[dict[str, object]]：规范化后的 ROI 列表。
    """

    if payload is None:
        return []
    if isinstance(payload, tuple):
        payload = list(payload)
    if isinstance(payload, list):
        normalized_items: list[dict[str, object]] = []
        for item in payload:
            normalized_items.extend(
                iter_roi_payloads(item, node_id=node_id, field_name=field_name)
            )
        return normalized_items
    if not isinstance(payload, dict):
        raise InvalidRequestError(
            f"{field_name} 必须是 roi.v1、roi-list.v1、roi.v1 数组或 value.v1",
            details={"node_id": node_id},
        )
    if "value" in payload:
        return iter_roi_payloads(payload.get("value"), node_id=node_id, field_name=field_name)
    if "items" in payload:
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise InvalidRequestError(
                f"{field_name}.items 必须是 ROI 数组",
                details={"node_id": node_id},
            )
        return iter_roi_payloads(raw_items, node_id=node_id, field_name=field_name)
    return [require_roi_payload(payload, node_id=node_id)]

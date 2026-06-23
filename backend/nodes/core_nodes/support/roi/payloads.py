"""roi.v1 payload 构造和校验。"""

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


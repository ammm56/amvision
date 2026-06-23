"""装配节点几何 helper。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


def compute_bbox_center(bbox_xyxy: object, *, node_name: str) -> tuple[float, float]:
    """根据 bbox_xyxy 计算中心点。"""

    if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
        raise InvalidRequestError(f"{node_name} 需要长度为 4 的 bbox_xyxy")
    x1_value = float(bbox_xyxy[0])
    y1_value = float(bbox_xyxy[1])
    x2_value = float(bbox_xyxy[2])
    y2_value = float(bbox_xyxy[3])
    return (x1_value + x2_value) / 2.0, (y1_value + y2_value) / 2.0

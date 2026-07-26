"""OpenCV shared detections payload 工具。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


def iter_detection_items(detections_payload: object) -> list[dict[str, object]]:
    """把 detections.v1 payload 规范化为 item 列表。"""

    if not isinstance(detections_payload, dict):
        raise InvalidRequestError("当前节点要求 detections payload 必须是对象")
    raw_items = detections_payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 detections.items 必须是数组")
    normalized_items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("当前节点要求每个 detection item 必须是对象")
        normalized_items.append(item)
    return normalized_items


def build_detection_label(*, item: dict[str, object], draw_scores: bool) -> str:
    """根据 detection item 生成要绘制的标签文本。"""

    label_parts: list[str] = []
    class_name = item.get("class_name")
    if isinstance(class_name, str) and class_name.strip():
        label_parts.append(class_name.strip())
    score = item.get("score")
    if draw_scores and isinstance(score, (int, float)):
        label_parts.append(f"{float(score):.2f}")
    return " ".join(label_parts)

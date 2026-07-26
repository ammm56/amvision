"""OpenCV shared payload 公共小工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload


def fill_source_image_fields(payload: dict[str, object]) -> None:
    """规范化 payload 中的 source_image 和 source_object_key。"""

    source_image = payload.get("source_image")
    if isinstance(source_image, dict):
        payload["source_image"] = require_image_payload(source_image)
    resolved_source_object_key = payload.get("source_object_key")
    if isinstance(resolved_source_object_key, str) and resolved_source_object_key:
        return
    normalized_source_image = payload.get("source_image")
    if not isinstance(normalized_source_image, dict):
        return
    source_object_key = normalized_source_image.get("object_key")
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key

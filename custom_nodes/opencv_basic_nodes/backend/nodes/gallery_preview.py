"""Gallery Preview 节点实现。"""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import require_image_refs_payload, require_positive_int


NODE_TYPE_ID = "custom.opencv.gallery-preview"


def _build_gallery_item(image_item: dict[str, object]) -> dict[str, object]:
    """把单个 image-ref 条目转换为 gallery preview 项。

    参数：
    - image_item：单个图片引用条目。

    返回：
    - dict[str, object]：gallery preview 使用的图片项。
    """

    gallery_item = {
        "image": image_item,
        "caption": PurePosixPath(str(image_item["object_key"])).name,
    }
    crop_index = image_item.get("crop_index")
    if isinstance(crop_index, int):
        gallery_item["caption"] = f"Crop {crop_index}"
        gallery_item["crop_index"] = crop_index
    bbox_xyxy = image_item.get("bbox_xyxy")
    if isinstance(bbox_xyxy, list):
        gallery_item["bbox_xyxy"] = bbox_xyxy
    return gallery_item


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 image-refs payload 转换为可直接进入 HTTP 响应的 gallery body。"""

    image_refs_payload = require_image_refs_payload(request.input_values.get("images"))
    gallery_items = [_build_gallery_item(image_item) for image_item in image_refs_payload["items"]]
    max_items_raw = request.parameters.get("max_items")
    if max_items_raw is not None:
        max_items = require_positive_int(max_items_raw, field_name="max_items")
        gallery_items = gallery_items[:max_items]
    response_body: dict[str, object] = {
        "type": "gallery-preview",
        "count": len(gallery_items),
        "total_count": int(image_refs_payload.get("count", len(image_refs_payload["items"]))),
        "items": gallery_items,
    }
    source_object_key = image_refs_payload.get("source_object_key")
    if isinstance(source_object_key, str) and source_object_key:
        response_body["source_object_key"] = source_object_key
    title = request.parameters.get("title")
    if isinstance(title, str) and title.strip():
        response_body["title"] = title.strip()
    return {"body": response_body}
"""Gallery Preview 节点实现。"""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.nodes.runtime_support import build_response_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import require_image_refs_payload, require_positive_int


NODE_TYPE_ID = "custom.opencv.gallery-preview"


def _build_gallery_item(
    request: WorkflowNodeExecutionRequest,
    *,
    image_item: dict[str, object],
    response_transport_mode: str,
    output_dir: str | None,
    item_index: int,
) -> dict[str, object]:
    """把单个 image-ref 条目转换为 gallery preview 项。

    参数：
    - request：当前节点执行请求。
    - image_item：单个图片引用条目。
    - response_transport_mode：响应传输方式。
    - output_dir：可选输出目录。
    - item_index：当前图片序号。

    返回：
    - dict[str, object]：gallery preview 使用的图片项。
    """

    output_object_key = None
    if isinstance(output_dir, str) and output_dir.strip():
        base_name = _build_gallery_output_name(image_item=image_item, item_index=item_index)
        output_object_key = f"{output_dir.strip().rstrip('/')}/{base_name}"
    response_image = build_response_image_payload(
        request,
        image_payload=image_item,
        response_transport_mode=response_transport_mode,
        object_key=output_object_key,
        variant_name=f"gallery-preview-{item_index:03d}",
    )
    default_caption = "Image"
    if response_image["transport_kind"] == "storage-ref":
        default_caption = PurePosixPath(str(response_image["object_key"])).name
    elif isinstance(image_item.get("object_key"), str) and str(image_item["object_key"]).strip():
        default_caption = PurePosixPath(str(image_item["object_key"])).name

    gallery_item = {
        "image": response_image,
        "caption": default_caption,
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
    response_transport_mode = str(request.parameters.get("response_transport_mode", "inline-base64"))
    output_dir = request.parameters.get("output_dir")
    normalized_output_dir = output_dir.strip() if isinstance(output_dir, str) and output_dir.strip() else None
    gallery_items = [
        _build_gallery_item(
            request,
            image_item=image_item,
            response_transport_mode=response_transport_mode,
            output_dir=normalized_output_dir,
            item_index=index,
        )
        for index, image_item in enumerate(image_refs_payload["items"], start=1)
    ]
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


def _build_gallery_output_name(*, image_item: dict[str, object], item_index: int) -> str:
    """为 gallery item 生成稳定输出文件名。"""

    raw_object_key = image_item.get("object_key")
    if isinstance(raw_object_key, str) and raw_object_key.strip():
        return PurePosixPath(raw_object_key.strip()).name
    crop_index = image_item.get("crop_index")
    if isinstance(crop_index, int):
        return f"crop-{crop_index:03d}.png"
    return f"image-{item_index:03d}.png"
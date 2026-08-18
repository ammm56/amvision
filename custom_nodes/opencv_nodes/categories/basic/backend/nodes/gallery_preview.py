"""Gallery Preview 节点实现。"""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.nodes.output_targets import (
    WorkflowOutputDirectory,
    resolve_optional_output_directory,
)
from backend.nodes.runtime_support import (
    build_preview_response_image_payload,
    load_image_matrix_from_payload,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    build_image_crop_batch_timestamp,
    build_image_crop_output_name,
    build_persisted_output_image_matrix_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    require_image_refs_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import (
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.gallery-preview"


def _build_gallery_item(
    request: WorkflowNodeExecutionRequest,
    *,
    image_item: dict[str, object],
    response_transport_mode: str,
    output_directory: WorkflowOutputDirectory | None,
    item_index: int,
    batch_timestamp: str | None,
) -> dict[str, object]:
    """把单个 image-ref 条目转换为 gallery preview 项。

    参数：
    - request：当前节点执行请求。
    - image_item：单个图片引用条目。
    - response_transport_mode：响应传输方式。
    - output_directory：可选输出目录。
    - item_index：当前图片序号。
    - batch_timestamp：当前批次共用的输出时间戳。

    返回：
    - dict[str, object]：gallery preview 使用的图片项。
    """

    response_source = image_item
    if output_directory is not None and batch_timestamp is not None:
        cv2_module, np_module = require_opencv_imports()
        normalized_payload, image_matrix = load_image_matrix_from_payload(
            request,
            image_payload=image_item,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        output_name = build_image_crop_output_name(
            batch_timestamp=batch_timestamp,
            item_index=item_index,
        )
        response_source = build_persisted_output_image_matrix_payload(
            request,
            source_payload=normalized_payload,
            image_matrix=image_matrix,
            output_directory=output_directory,
            output_name=output_name,
            keep_raw_memory=False,
            media_type="image/png",
            error_message="Gallery Preview 无法编码输出图片",
        )
    response_image = build_preview_response_image_payload(
        request,
        image_payload=response_source,
        response_transport_mode=response_transport_mode,
        variant_name=f"gallery-preview-{item_index:03d}",
    )
    default_caption = "Image"
    if response_image["transport_kind"] == "storage-ref":
        default_caption = PurePosixPath(str(response_image["object_key"])).name
    elif (
        isinstance(image_item.get("object_key"), str)
        and str(image_item["object_key"]).strip()
    ):
        default_caption = PurePosixPath(str(image_item["object_key"])).name
    saved_output = response_source.get("saved_output")
    if isinstance(saved_output, dict):
        local_path = saved_output.get("local_path")
        object_key = saved_output.get("object_key")
        if isinstance(local_path, str) and local_path:
            default_caption = PurePosixPath(local_path.replace("\\", "/")).name
        elif isinstance(object_key, str) and object_key:
            default_caption = PurePosixPath(object_key).name

    gallery_item = {
        "image": response_image,
        "caption": default_caption,
    }
    if isinstance(saved_output, dict):
        gallery_item["saved_output"] = dict(saved_output)
    crop_index = image_item.get("crop_index")
    if isinstance(crop_index, int):
        gallery_item["caption"] = f"Crop {crop_index}"
        gallery_item["crop_index"] = crop_index
    bbox_xyxy = image_item.get("bbox_xyxy")
    if isinstance(bbox_xyxy, list):
        gallery_item["bbox_xyxy"] = bbox_xyxy
    return gallery_item


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 image-refs payload 转换为可直接进入 HTTP 响应的 gallery body。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 gallery-preview body 的节点输出。
    """

    image_refs_payload = require_image_refs_payload(request.input_values.get("images"))
    response_transport_mode = str(
        request.parameters.get("response_transport_mode", "inline-base64")
    )
    output_directory = resolve_optional_output_directory(
        request.parameters.get("output_dir")
    )
    output_batch_timestamp = (
        build_image_crop_batch_timestamp() if output_directory is not None else None
    )
    image_items = image_refs_payload["items"]
    max_items_raw = request.parameters.get("max_items")
    if max_items_raw is not None:
        max_items = require_positive_int(max_items_raw, field_name="max_items")
        image_items = image_items[:max_items]
    gallery_items = [
        _build_gallery_item(
            request,
            image_item=image_item,
            response_transport_mode=response_transport_mode,
            output_directory=output_directory,
            item_index=index,
            batch_timestamp=output_batch_timestamp,
        )
        for index, image_item in enumerate(image_items, start=1)
    ]
    response_body: dict[str, object] = {
        "type": "gallery-preview",
        "count": len(gallery_items),
        "total_count": int(
            image_refs_payload.get("count", len(image_refs_payload["items"]))
        ),
        "items": gallery_items,
    }
    source_object_key = image_refs_payload.get("source_object_key")
    if isinstance(source_object_key, str) and source_object_key:
        response_body["source_object_key"] = source_object_key
    title = request.parameters.get("title")
    if isinstance(title, str) and title.strip():
        response_body["title"] = title.strip()
    return {"body": response_body}

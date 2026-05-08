"""Crop Export 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_output_image_payload,
    build_crop_object_key,
    clip_bbox,
    iter_detection_items,
    load_image_matrix,
    normalize_bbox,
    normalize_optional_output_dir,
    require_non_negative_int,
    require_opencv_imports,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.crop-export"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据 detection bbox 导出裁剪图集合。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, image_object_key, image_matrix = load_image_matrix(request)

    image_height, image_width = image_matrix.shape[:2]
    box_padding = require_non_negative_int(request.parameters.get("box_padding", 0), field_name="box_padding")
    max_crops_raw = request.parameters.get("max_crops")
    max_crops = require_positive_int(max_crops_raw, field_name="max_crops") if max_crops_raw is not None else None
    output_dir = normalize_optional_output_dir(request.parameters.get("output_dir"))
    exported_crops: list[dict[str, object]] = []
    for detection_index, detection_item in enumerate(iter_detection_items(request.input_values.get("detections")), start=1):
        if max_crops is not None and len(exported_crops) >= max_crops:
            break
        x1, y1, x2, y2 = normalize_bbox(detection_item.get("bbox_xyxy"))
        clipped_bbox = clip_bbox(
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            image_width=image_width,
            image_height=image_height,
            box_padding=box_padding,
        )
        if clipped_bbox is None:
            continue
        crop_x1, crop_y1, crop_x2, crop_y2 = clipped_bbox
        crop_image = image_matrix[crop_y1:crop_y2, crop_x1:crop_x2]
        if crop_image.size == 0:
            continue
        success, encoded_image = cv2_module.imencode(".png", crop_image)
        if success is not True:
            raise ServiceConfigurationError(
                "OpenCV crop export 后无法编码输出图片",
                details={"node_id": request.node_id, "detection_index": detection_index},
            )
        crop_object_key = (
            build_crop_object_key(
                request,
                source_object_key=image_object_key,
                output_dir=output_dir,
                detection_index=detection_index,
            )
            if output_dir is not None
            else None
        )
        crop_payload = build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image.tobytes(),
            object_key=crop_object_key,
            variant_name=f"crop-{detection_index:03d}",
            output_extension=".png",
            width=int(crop_image.shape[1]),
            height=int(crop_image.shape[0]),
            media_type="image/png",
        )
        crop_payload["bbox_xyxy"] = [crop_x1, crop_y1, crop_x2, crop_y2]
        crop_payload["crop_index"] = len(exported_crops) + 1
        exported_crops.append(crop_payload)
    return {
        "crops": {
            "items": exported_crops,
            "count": len(exported_crops),
            "source_image": dict(image_payload),
            **({"source_object_key": image_object_key} if image_object_key is not None else {}),
        }
    }
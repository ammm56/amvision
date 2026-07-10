"""Crop 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import require_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_int,
)


NODE_TYPE_ID = "custom.opencv.crop"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按输入 roi.v1 裁剪图片。"""

    image_payload, _, image_matrix = load_image_matrix(request)
    image_height, image_width = image_matrix.shape[:2]
    roi_payload = require_roi_payload(request.input_values.get("roi"), node_id=request.node_id)
    crop_x1, crop_y1, crop_x2, crop_y2 = _resolve_crop_bbox(
        roi_payload=roi_payload,
        padding=_read_padding(request.parameters.get("padding")),
        image_width=image_width,
        image_height=image_height,
    )
    cropped_image = image_matrix[crop_y1:crop_y2, crop_x1:crop_x2]
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=cropped_image,
        error_message="OpenCV crop 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="crop",
        output_extension=".png",
        width=int(cropped_image.shape[1]),
        height=int(cropped_image.shape[0]),
        media_type="image/png",
    )
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "crop_source": "roi",
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_payload["roi_kind"],
                "crop_bbox_xyxy": [crop_x1, crop_y1, crop_x2, crop_y2],
                "output_width": int(cropped_image.shape[1]),
                "output_height": int(cropped_image.shape[0]),
            }
        ),
    }


def _resolve_crop_bbox(
    *,
    roi_payload: dict[str, object],
    padding: int,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    """把 roi.v1 的 bbox 转成图像边界内的整数裁剪区域。"""

    bbox_xyxy = roi_payload["bbox_xyxy"]
    x1_value = float(bbox_xyxy[0])
    y1_value = float(bbox_xyxy[1])
    x2_value = float(bbox_xyxy[2])
    y2_value = float(bbox_xyxy[3])
    crop_x1 = max(0, min(image_width, int(math.floor(x1_value)) - padding))
    crop_y1 = max(0, min(image_height, int(math.floor(y1_value)) - padding))
    crop_x2 = max(0, min(image_width, int(math.ceil(x2_value)) + padding))
    crop_y2 = max(0, min(image_height, int(math.ceil(y2_value)) + padding))
    if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
        raise InvalidRequestError(
            "crop 节点解析后的 ROI 裁剪区域为空",
            details={
                "roi_id": roi_payload.get("roi_id"),
                "roi_kind": roi_payload.get("roi_kind"),
                "crop_bbox_xyxy": [crop_x1, crop_y1, crop_x2, crop_y2],
                "image_width": image_width,
                "image_height": image_height,
            },
        )
    return crop_x1, crop_y1, crop_x2, crop_y2


def _read_padding(raw_value: object) -> int:
    """读取裁剪 padding。"""

    if raw_value in {None, ""}:
        return 0
    return require_non_negative_int(raw_value, field_name="padding")

"""Crop 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import require_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
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
    padding = _read_padding(request.parameters.get("padding"))
    polygon_background_fill = _read_polygon_background_fill(
        request.parameters.get("polygon_background_fill")
    )
    crop_x1, crop_y1, crop_x2, crop_y2 = _resolve_crop_bbox(
        roi_payload=roi_payload,
        padding=padding,
        image_width=image_width,
        image_height=image_height,
    )
    cropped_image = image_matrix[crop_y1:crop_y2, crop_x1:crop_x2].copy()
    polygon_mask_applied = roi_payload["roi_kind"] == "polygon"
    if polygon_mask_applied:
        cropped_image = _apply_polygon_mask(
            cropped_image=cropped_image,
            polygon_xy=roi_payload["polygon_xy"],
            crop_x1=crop_x1,
            crop_y1=crop_y1,
            background_fill=polygon_background_fill,
        )
    output_payload = build_output_image_matrix_payload(
        request,
        source_payload=image_payload,
        image_matrix=cropped_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="crop",
        output_extension=".png",
        media_type="image/png",
        error_message="OpenCV crop 后无法编码输出图片",
    )
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "crop_source": "roi",
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_payload["roi_kind"],
                "crop_bbox_xyxy": [crop_x1, crop_y1, crop_x2, crop_y2],
                "polygon_mask_applied": polygon_mask_applied,
                "polygon_background_fill": polygon_background_fill if polygon_mask_applied else None,
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


def _apply_polygon_mask(
    *,
    cropped_image: object,
    polygon_xy: object,
    crop_x1: int,
    crop_y1: int,
    background_fill: str,
) -> object:
    """对 polygon ROI 的外接矩形裁剪图应用 polygon mask。"""

    cv2_module, np_module = require_opencv_imports()
    shifted_points = np_module.asarray(
        [
            [int(round(float(point[0]) - crop_x1)), int(round(float(point[1]) - crop_y1))]
            for point in polygon_xy
        ],
        dtype=np_module.int32,
    ).reshape((-1, 1, 2))
    output_image = cropped_image.copy()
    mask = np_module.zeros(output_image.shape[:2], dtype=np_module.uint8)
    cv2_module.fillPoly(mask, [shifted_points], 255)
    output_image[mask == 0] = _build_background_fill_value(output_image, background_fill)
    return output_image


def _build_background_fill_value(image_matrix: object, background_fill: str) -> object:
    """根据图片通道数构建 polygon 外部背景填充值。"""

    fill_channel_value = 255 if background_fill == "white" else 0
    shape = getattr(image_matrix, "shape", ())
    if len(shape) < 3:
        return fill_channel_value
    channel_count = int(shape[2])
    if channel_count == 4:
        return [fill_channel_value, fill_channel_value, fill_channel_value, 255]
    return [fill_channel_value] * channel_count


def _read_padding(raw_value: object) -> int:
    """读取裁剪 padding。"""

    if is_empty_parameter(raw_value):
        return 0
    return require_non_negative_int(raw_value, field_name="padding")


def _read_polygon_background_fill(raw_value: object) -> str:
    """读取 polygon ROI 外部背景填充色。"""

    if is_empty_parameter(raw_value):
        return "black"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("polygon_background_fill 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"black", "white"}:
        raise InvalidRequestError("polygon_background_fill 仅支持 black 或 white")
    return normalized_value

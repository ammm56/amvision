"""Crop 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._roi_node_support import require_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_optional_object_key,
    require_non_negative_int,
    require_number,
)


NODE_TYPE_ID = "custom.opencv.crop"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 ROI 或显式矩形参数裁剪输入图片。"""

    image_payload, _, image_matrix = load_image_matrix(request)
    image_height, image_width = image_matrix.shape[:2]
    crop_x1, crop_y1, crop_x2, crop_y2, crop_source, crop_summary = _resolve_crop_bbox(
        request,
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
                "crop_source": crop_source,
                "crop_bbox_xyxy": [crop_x1, crop_y1, crop_x2, crop_y2],
                "output_width": int(cropped_image.shape[1]),
                "output_height": int(cropped_image.shape[0]),
                **crop_summary,
            }
        ),
    }


def _resolve_crop_bbox(
    request: WorkflowNodeExecutionRequest,
    *,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int, str, dict[str, object]]:
    """解析裁剪 bbox。"""

    padding = _read_padding(request.parameters.get("padding"))
    raw_roi_payload = request.input_values.get("roi")
    if raw_roi_payload is not None:
        roi_payload = require_roi_payload(raw_roi_payload, node_id=request.node_id)
        bbox_xyxy = roi_payload["bbox_xyxy"]
        x1_value = float(bbox_xyxy[0])
        y1_value = float(bbox_xyxy[1])
        x2_value = float(bbox_xyxy[2])
        y2_value = float(bbox_xyxy[3])
        crop_source = "roi"
        crop_summary = {
            "roi_id": roi_payload["roi_id"],
            "roi_kind": roi_payload["roi_kind"],
        }
    else:
        x_value = _read_required_coordinate(request.parameters.get("x"), field_name="x")
        y_value = _read_required_coordinate(request.parameters.get("y"), field_name="y")
        width_value = _read_required_positive_extent(request.parameters.get("width"), field_name="width")
        height_value = _read_required_positive_extent(request.parameters.get("height"), field_name="height")
        x1_value = x_value
        y1_value = y_value
        x2_value = x_value + width_value
        y2_value = y_value + height_value
        crop_source = "parameters"
        crop_summary = {
            "x": round(x_value, 4),
            "y": round(y_value, 4),
            "width": round(width_value, 4),
            "height": round(height_value, 4),
        }

    crop_x1 = max(0, min(image_width, int(math.floor(x1_value)) - padding))
    crop_y1 = max(0, min(image_height, int(math.floor(y1_value)) - padding))
    crop_x2 = max(0, min(image_width, int(math.ceil(x2_value)) + padding))
    crop_y2 = max(0, min(image_height, int(math.ceil(y2_value)) + padding))
    if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
        raise InvalidRequestError(
            "crop 节点解析后的裁剪区域为空",
            details={
                "crop_source": crop_source,
                "crop_bbox_xyxy": [crop_x1, crop_y1, crop_x2, crop_y2],
                "image_width": image_width,
                "image_height": image_height,
            },
        )
    return crop_x1, crop_y1, crop_x2, crop_y2, crop_source, crop_summary


def _read_padding(raw_value: object) -> int:
    """读取裁剪 padding。"""

    if raw_value in {None, ""}:
        return 0
    return require_non_negative_int(raw_value, field_name="padding")


def _read_required_coordinate(raw_value: object, *, field_name: str) -> float:
    """读取必填坐标参数。"""

    if raw_value in {None, ""}:
        raise InvalidRequestError(f"{field_name} 必须提供数值")
    return require_number(raw_value, field_name=field_name)


def _read_required_positive_extent(raw_value: object, *, field_name: str) -> float:
    """读取必填正向宽高。"""

    normalized_value = _read_required_coordinate(raw_value, field_name=field_name)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value

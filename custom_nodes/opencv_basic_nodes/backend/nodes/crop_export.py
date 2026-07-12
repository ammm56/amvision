"""Crop Export 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

import math

from backend.nodes.core_nodes.support.roi import iter_roi_payloads
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    build_crop_object_key,
    clip_bbox,
    load_image_matrix,
    normalize_optional_output_dir,
)
from custom_nodes._opencv_shared.backend.runtime.payloads import iter_detection_items
from custom_nodes._opencv_shared.backend.runtime.geometry import normalize_bbox
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_int,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.crop-export"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据 detection bbox 或 ROI list 导出裁剪图集合。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, image_object_key, image_matrix = load_image_matrix(request)

    image_height, image_width = image_matrix.shape[:2]
    raw_box_padding = request.parameters.get("box_padding")
    box_padding = 0 if is_empty_parameter(raw_box_padding) else require_non_negative_int(raw_box_padding, field_name="box_padding")
    max_crops_raw = request.parameters.get("max_crops")
    if max_crops_raw == "":
        max_crops_raw = None
    max_crops = require_positive_int(max_crops_raw, field_name="max_crops") if max_crops_raw is not None else None
    output_dir = normalize_optional_output_dir(request.parameters.get("output_dir"))
    polygon_background_fill = _read_polygon_background_fill(
        request.parameters.get("polygon_background_fill")
    )
    crop_specs = _resolve_crop_specs(request)
    exported_crops: list[dict[str, object]] = []
    for source_index, crop_spec in enumerate(crop_specs, start=1):
        if max_crops is not None and len(exported_crops) >= max_crops:
            break
        x1, y1, x2, y2 = crop_spec["bbox_xyxy"]
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
        crop_image = image_matrix[crop_y1:crop_y2, crop_x1:crop_x2].copy()
        if crop_image.size == 0:
            continue
        polygon_mask_applied = crop_spec["source_kind"] == "roi" and crop_spec.get("roi_kind") == "polygon"
        if polygon_mask_applied:
            crop_image = _apply_polygon_mask(
                cv2_module=cv2_module,
                np_module=np_module,
                cropped_image=crop_image,
                polygon_xy=crop_spec["polygon_xy"],
                crop_x1=crop_x1,
                crop_y1=crop_y1,
                background_fill=polygon_background_fill,
            )
        crop_object_key = (
            build_crop_object_key(
                request,
                source_object_key=image_object_key,
                output_dir=output_dir,
                detection_index=source_index,
            )
            if output_dir is not None
            else None
        )
        crop_payload = build_output_image_matrix_payload(
            request,
            source_payload=image_payload,
            image_matrix=crop_image,
            object_key=crop_object_key,
            variant_name=f"crop-{source_index:03d}",
            output_extension=".png",
            media_type="image/png",
            error_message="OpenCV crop export 后无法编码输出图片",
        )
        crop_payload["bbox_xyxy"] = [crop_x1, crop_y1, crop_x2, crop_y2]
        crop_payload["crop_index"] = len(exported_crops) + 1
        crop_payload["crop_source"] = crop_spec["source_kind"]
        if crop_spec["source_kind"] == "roi":
            crop_payload["roi_id"] = crop_spec.get("roi_id")
            crop_payload["roi_kind"] = crop_spec.get("roi_kind")
            crop_payload["polygon_mask_applied"] = polygon_mask_applied
            crop_payload["polygon_background_fill"] = (
                polygon_background_fill if polygon_mask_applied else None
            )
        elif crop_spec.get("class_name") is not None:
            crop_payload["class_name"] = crop_spec.get("class_name")
        exported_crops.append(crop_payload)
    return {
        "crops": {
            "items": exported_crops,
            "count": len(exported_crops),
            "source_image": dict(image_payload),
            **({"source_object_key": image_object_key} if image_object_key is not None else {}),
        }
    }


def _resolve_crop_specs(request: WorkflowNodeExecutionRequest) -> list[dict[str, object]]:
    """按优先级解析 ROI list 或 detections 裁剪来源。"""

    raw_rois = request.input_values.get("rois")
    if raw_rois is not None:
        return _build_roi_crop_specs(raw_rois, node_id=request.node_id)
    raw_detections = request.input_values.get("detections")
    if raw_detections is None:
        raise InvalidRequestError(
            "crop-export 节点需要 detections 或 rois 输入",
            details={"node_id": request.node_id},
        )
    return _build_detection_crop_specs(raw_detections)


def _build_detection_crop_specs(raw_detections: object) -> list[dict[str, object]]:
    """把 detections.v1 转为裁剪规格。"""

    crop_specs: list[dict[str, object]] = []
    for detection_item in iter_detection_items(raw_detections):
        x1, y1, x2, y2 = normalize_bbox(detection_item.get("bbox_xyxy"))
        crop_specs.append(
            {
                "source_kind": "detection",
                "bbox_xyxy": (x1, y1, x2, y2),
                "class_name": detection_item.get("class_name"),
            }
        )
    return crop_specs


def _build_roi_crop_specs(raw_rois: object, *, node_id: str) -> list[dict[str, object]]:
    """把 ROI list 转为裁剪规格。"""

    crop_specs: list[dict[str, object]] = []
    for roi_payload in iter_roi_payloads(raw_rois, node_id=node_id, field_name="rois"):
        bbox_xyxy = roi_payload["bbox_xyxy"]
        x1 = int(math.floor(float(bbox_xyxy[0])))
        y1 = int(math.floor(float(bbox_xyxy[1])))
        x2 = int(math.ceil(float(bbox_xyxy[2])))
        y2 = int(math.ceil(float(bbox_xyxy[3])))
        crop_specs.append(
            {
                "source_kind": "roi",
                "bbox_xyxy": (x1, y1, x2, y2),
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_payload["roi_kind"],
                "polygon_xy": roi_payload["polygon_xy"],
            }
        )
    return crop_specs


def _apply_polygon_mask(
    *,
    cv2_module: object,
    np_module: object,
    cropped_image: object,
    polygon_xy: object,
    crop_x1: int,
    crop_y1: int,
    background_fill: str,
) -> object:
    """对 polygon ROI 的外接矩形裁剪图应用 polygon mask。"""

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

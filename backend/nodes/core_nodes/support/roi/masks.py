"""ROI 和 region mask 构造函数。"""

from __future__ import annotations

import math

import cv2
import numpy as np

from backend.nodes.core_nodes.support.region import resolve_region_source_image_size
from backend.nodes.core_nodes.support.roi.geometry import (
    normalize_bbox_xyxy,
    normalize_polygon_xy,
)
from backend.nodes.runtime_support import load_image_bytes_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.images import decode_image_bytes_to_matrix
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def resolve_roi_canvas_size(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    roi_payload: dict[str, object],
) -> tuple[int, int]:
    """解析 ROI 与 regions 计算所需的画布宽高。"""

    try:
        _source_payload, image_width, image_height = resolve_region_source_image_size(
            request,
            regions_payload=regions_payload,
            image_payload=None,
        )
        return image_width, image_height
    except InvalidRequestError:
        return derive_canvas_size_from_payloads(
            regions_payload=regions_payload,
            roi_payload=roi_payload,
        )


def derive_canvas_size_from_payloads(
    *,
    regions_payload: dict[str, object],
    roi_payload: dict[str, object],
) -> tuple[int, int]:
    """从 bbox、polygon 和 mask payload 自行推导画布宽高。"""

    max_x = 1.0
    max_y = 1.0
    for region_item in regions_payload["items"]:
        bbox_xyxy = region_item.get("bbox_xyxy")
        if isinstance(bbox_xyxy, list) and len(bbox_xyxy) == 4:
            max_x = max(max_x, float(bbox_xyxy[2]))
            max_y = max(max_y, float(bbox_xyxy[3]))
        polygon_xy = region_item.get("polygon_xy")
        if isinstance(polygon_xy, list):
            for point_value in polygon_xy:
                if isinstance(point_value, list) and len(point_value) == 2:
                    max_x = max(max_x, float(point_value[0]))
                    max_y = max(max_y, float(point_value[1]))
        mask_payload = region_item.get("mask_image")
        if isinstance(mask_payload, dict):
            width_value = mask_payload.get("width")
            height_value = mask_payload.get("height")
            if isinstance(width_value, int) and width_value > 0:
                max_x = max(max_x, float(width_value))
            if isinstance(height_value, int) and height_value > 0:
                max_y = max(max_y, float(height_value))
    bbox_xyxy = roi_payload["bbox_xyxy"]
    max_x = max(max_x, float(bbox_xyxy[2]))
    max_y = max(max_y, float(bbox_xyxy[3]))
    for point_value in roi_payload["polygon_xy"]:
        max_x = max(max_x, float(point_value[0]))
        max_y = max(max_y, float(point_value[1]))
    return max(1, int(math.ceil(max_x))), max(1, int(math.ceil(max_y)))


def build_roi_mask(
    *,
    roi_payload: dict[str, object],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把 roi.v1 转为二值 mask。"""

    if roi_payload["roi_kind"] == "bbox":
        return build_bbox_mask(
            bbox_xyxy=roi_payload["bbox_xyxy"],
            image_width=image_width,
            image_height=image_height,
        )
    return build_polygon_mask(
        polygon_xy=roi_payload["polygon_xy"],
        image_width=image_width,
        image_height=image_height,
    )


def build_region_mask(
    request: WorkflowNodeExecutionRequest,
    *,
    region_item: dict[str, object],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把单个 region item 转为二值 mask。"""

    mask_payload = region_item.get("mask_image")
    if isinstance(mask_payload, dict):
        normalized_payload, image_bytes = load_image_bytes_from_payload(
            request,
            image_payload=mask_payload,
        )
        image_matrix = decode_image_bytes_to_matrix(
            cv2_module=cv2,
            np_module=np,
            image_bytes=image_bytes,
            image_payload=normalized_payload,
            imdecode_flags=cv2.IMREAD_GRAYSCALE,
            error_message="region 的 mask_image 无法解码为灰度图",
            copy_raw=True,
        )
        if image_matrix.shape[1] != image_width or image_matrix.shape[0] != image_height:
            image_matrix = cv2.resize(
                image_matrix,
                (image_width, image_height),
                interpolation=cv2.INTER_NEAREST,
            )
        return (image_matrix > 0).astype(np.uint8)
    polygon_xy = region_item.get("polygon_xy")
    if isinstance(polygon_xy, list) and len(polygon_xy) >= 3:
        return build_polygon_mask(
            polygon_xy=normalize_polygon_xy(polygon_xy, field_name="polygon_xy", node_id=None),
            image_width=image_width,
            image_height=image_height,
        )
    return build_bbox_mask(
        bbox_xyxy=normalize_bbox_xyxy(region_item.get("bbox_xyxy"), field_name="bbox_xyxy", node_id=None),
        image_width=image_width,
        image_height=image_height,
    )


def build_bbox_mask(
    *,
    bbox_xyxy: list[float],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把 bbox 转为二值 mask。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    x1_index = max(0, min(image_width, int(math.floor(x1_value))))
    y1_index = max(0, min(image_height, int(math.floor(y1_value))))
    x2_index = max(0, min(image_width, int(math.ceil(x2_value))))
    y2_index = max(0, min(image_height, int(math.ceil(y2_value))))
    mask_matrix = np.zeros((image_height, image_width), dtype=np.uint8)
    if x2_index > x1_index and y2_index > y1_index:
        mask_matrix[y1_index:y2_index, x1_index:x2_index] = 1
    return mask_matrix


def build_polygon_mask(
    *,
    polygon_xy: list[list[float]],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把 polygon 转为二值 mask。"""

    polygon_array = np.array(
        [[[int(round(point[0])), int(round(point[1]))] for point in polygon_xy]],
        dtype=np.int32,
    )
    mask_matrix = np.zeros((image_height, image_width), dtype=np.uint8)
    cv2.fillPoly(mask_matrix, polygon_array, 1)
    return mask_matrix

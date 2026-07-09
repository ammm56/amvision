"""regions.v1 mask 与画布解析支撑函数。"""

from __future__ import annotations

import math

import cv2
import numpy as np

from backend.nodes.core_nodes.support.region.images import resolve_region_source_image_size
from backend.nodes.runtime_support import load_image_bytes_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.images import decode_image_bytes_to_matrix
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def derive_region_canvas_size(*, regions_payload: dict[str, object]) -> tuple[int, int]:
    """从 regions.v1 自身推导连通域分析所需的画布宽高。"""

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
    return max(1, int(math.ceil(max_x))), max(1, int(math.ceil(max_y)))


def resolve_region_canvas_size(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
) -> tuple[int, int]:
    """解析 region 二值化分析所需的画布宽高。"""

    try:
        _resolved_payload, image_width, image_height = resolve_region_source_image_size(
            request,
            regions_payload=regions_payload,
            image_payload=None,
        )
        return image_width, image_height
    except InvalidRequestError:
        return derive_region_canvas_size(regions_payload=regions_payload)


def build_bbox_mask(
    *,
    bbox_xyxy: list[float],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把 bbox_xyxy 栅格化为二值 mask。"""

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
    """把 polygon_xy 栅格化为二值 mask。"""

    polygon_array = np.array(
        [[[int(round(point[0])), int(round(point[1]))] for point in polygon_xy]],
        dtype=np.int32,
    )
    mask_matrix = np.zeros((image_height, image_width), dtype=np.uint8)
    cv2.fillPoly(mask_matrix, polygon_array, 1)
    return mask_matrix


def build_region_binary_mask(
    request: WorkflowNodeExecutionRequest,
    *,
    region_item: dict[str, object],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把单个 region item 解析成二值 mask。"""

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
            polygon_xy=_normalize_polygon_xy(polygon_xy),
            image_width=image_width,
            image_height=image_height,
        )
    return build_bbox_mask(
        bbox_xyxy=_normalize_bbox_xyxy(region_item.get("bbox_xyxy")),
        image_width=image_width,
        image_height=image_height,
    )


def _normalize_bbox_xyxy(raw_value: object) -> list[float]:
    """规范化 region 内的 bbox_xyxy。"""

    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise InvalidRequestError("region 的 bbox_xyxy 必须是长度为 4 的数值数组")
    normalized_values: list[float] = []
    for item_value in raw_value:
        if isinstance(item_value, bool) or not isinstance(item_value, (int, float)):
            raise InvalidRequestError("region 的 bbox_xyxy 必须全部是数值")
        normalized_values.append(float(item_value))
    x1_value, y1_value, x2_value, y2_value = normalized_values
    if x2_value < x1_value or y2_value < y1_value:
        raise InvalidRequestError("region 的 bbox_xyxy 要求 x2>=x1 且 y2>=y1")
    return normalized_values


def _normalize_polygon_xy(raw_value: object) -> list[list[float]]:
    """规范化 region 内的 polygon_xy。"""

    if not isinstance(raw_value, list) or len(raw_value) < 3:
        raise InvalidRequestError("region 的 polygon_xy 必须是至少 3 个点的数组")
    normalized_points: list[list[float]] = []
    for point_value in raw_value:
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError("region 的 polygon_xy 中的点必须是长度为 2 的数组")
        x_value, y_value = point_value
        if (
            isinstance(x_value, bool)
            or isinstance(y_value, bool)
            or not isinstance(x_value, (int, float))
            or not isinstance(y_value, (int, float))
        ):
            raise InvalidRequestError("region 的 polygon_xy 中的点坐标必须是数值")
        normalized_points.append([float(x_value), float(y_value)])
    return normalized_points

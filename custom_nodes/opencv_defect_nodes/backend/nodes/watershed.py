"""Watershed 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_float,
    require_non_negative_int,
    require_positive_int,
    require_uint8_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.watershed"


def _read_foreground_threshold(raw_value: object) -> int:
    """读取前景阈值。"""

    if raw_value in {None, ""}:
        return 1
    return require_uint8_int(raw_value, field_name="foreground_threshold")


def _read_distance_threshold_ratio(raw_value: object) -> float:
    """读取 sure foreground 距离阈值比例。"""

    if raw_value in {None, ""}:
        return 0.35
    normalized_value = require_non_negative_float(raw_value, field_name="distance_threshold_ratio")
    if normalized_value > 1.0:
        raise InvalidRequestError("distance_threshold_ratio 必须位于 0 到 1 之间")
    return float(normalized_value)


def _to_bgr(image_matrix: object, *, cv2_module: object) -> object:
    """把输入图片统一转换为 BGR 三通道。"""

    if len(image_matrix.shape) == 2:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_GRAY2BGR)
    channel_count = int(image_matrix.shape[2])
    if channel_count == 4:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGRA2BGR)
    if channel_count == 1:
        return cv2_module.cvtColor(image_matrix[:, :, 0], cv2_module.COLOR_GRAY2BGR)
    return image_matrix


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把粘连前景通过 watershed 拆分为带边界隔离的二值结果。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    source_image_payload = request.input_values.get("source_image")
    if source_image_payload is None:
        source_image_matrix = _to_bgr(image_matrix, cv2_module=cv2_module)
    else:
        _source_payload, _, raw_source_image_matrix = load_image_matrix(request, input_name="source_image")
        if raw_source_image_matrix.shape[0] != image_matrix.shape[0] or raw_source_image_matrix.shape[1] != image_matrix.shape[1]:
            raise InvalidRequestError(
                "watershed 节点要求 source_image 与 image 的尺寸一致",
                details={
                    "image_shape": list(image_matrix.shape),
                    "source_image_shape": list(raw_source_image_matrix.shape),
                },
            )
        source_image_matrix = _to_bgr(raw_source_image_matrix, cv2_module=cv2_module)

    foreground_threshold = _read_foreground_threshold(request.parameters.get("foreground_threshold"))
    opening_kernel_size = (
        3
        if request.parameters.get("opening_kernel_size") in {None, ""}
        else require_positive_int(request.parameters.get("opening_kernel_size"), field_name="opening_kernel_size")
    )
    opening_iterations = (
        1
        if request.parameters.get("opening_iterations") in {None, ""}
        else require_non_negative_int(request.parameters.get("opening_iterations"), field_name="opening_iterations")
    )
    background_dilate_iterations = (
        1
        if request.parameters.get("background_dilate_iterations") in {None, ""}
        else require_non_negative_int(
            request.parameters.get("background_dilate_iterations"),
            field_name="background_dilate_iterations",
        )
    )
    boundary_gap_iterations = (
        1
        if request.parameters.get("boundary_gap_iterations") in {None, ""}
        else require_non_negative_int(
            request.parameters.get("boundary_gap_iterations"),
            field_name="boundary_gap_iterations",
        )
    )
    distance_threshold_ratio = _read_distance_threshold_ratio(request.parameters.get("distance_threshold_ratio"))

    binary_image = np_module.where(image_matrix > foreground_threshold, 255, 0).astype(np_module.uint8)
    kernel = np_module.ones((opening_kernel_size, opening_kernel_size), dtype=np_module.uint8)
    opened_image = (
        cv2_module.morphologyEx(
            binary_image,
            cv2_module.MORPH_OPEN,
            kernel,
            iterations=opening_iterations,
        )
        if opening_iterations > 0
        else binary_image
    )
    sure_background = (
        cv2_module.dilate(opened_image, kernel, iterations=background_dilate_iterations)
        if background_dilate_iterations > 0
        else opened_image
    )
    distance_matrix = cv2_module.distanceTransform(opened_image, cv2_module.DIST_L2, 5)
    max_distance = float(distance_matrix.max()) if int(np_module.count_nonzero(distance_matrix)) > 0 else 0.0
    distance_threshold = max_distance * distance_threshold_ratio
    if max_distance > 0.0:
        _ret_value, sure_foreground = cv2_module.threshold(
            distance_matrix,
            distance_threshold,
            255,
            cv2_module.THRESH_BINARY,
        )
        sure_foreground = sure_foreground.astype(np_module.uint8)
    else:
        sure_foreground = np_module.zeros_like(opened_image, dtype=np_module.uint8)
    unknown_region = cv2_module.subtract(sure_background, sure_foreground)
    marker_count, markers = cv2_module.connectedComponents(sure_foreground)
    markers = markers + 1
    markers[unknown_region == 255] = 0
    watershed_markers = cv2_module.watershed(source_image_matrix.copy(), markers.astype(np_module.int32))

    boundary_mask = (watershed_markers == -1).astype(np_module.uint8)
    separated_mask = np_module.where(watershed_markers > 1, 255, 0).astype(np_module.uint8)
    if boundary_gap_iterations > 0 and int(np_module.count_nonzero(boundary_mask)) > 0:
        boundary_gap_mask = cv2_module.dilate(
            boundary_mask,
            np_module.ones((3, 3), dtype=np_module.uint8),
            iterations=boundary_gap_iterations,
        )
        separated_mask[boundary_gap_mask > 0] = 0
    watershed_region_labels = [
        int(label_value)
        for label_value in np_module.unique(watershed_markers)
        if int(label_value) > 1
    ]

    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=separated_mask,
        error_message="OpenCV watershed 后无法编码输出图片",
    )
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="watershed",
            output_extension=".png",
            width=int(separated_mask.shape[1]),
            height=int(separated_mask.shape[0]),
            media_type="image/png",
        ),
        "summary": build_value_payload(
            {
                "foreground_threshold": int(foreground_threshold),
                "opening_kernel_size": int(opening_kernel_size),
                "opening_iterations": int(opening_iterations),
                "background_dilate_iterations": int(background_dilate_iterations),
                "boundary_gap_iterations": int(boundary_gap_iterations),
                "distance_threshold_ratio": distance_threshold_ratio,
                "input_foreground_pixel_count": int(np_module.count_nonzero(binary_image)),
                "opened_foreground_pixel_count": int(np_module.count_nonzero(opened_image)),
                "sure_foreground_pixel_count": int(np_module.count_nonzero(sure_foreground)),
                "sure_background_pixel_count": int(np_module.count_nonzero(sure_background)),
                "unknown_pixel_count": int(np_module.count_nonzero(unknown_region)),
                "seed_component_count": max(0, int(marker_count) - 1),
                "watershed_region_count": len(watershed_region_labels),
                "boundary_pixel_count": int(np_module.count_nonzero(boundary_mask)),
                "max_distance": round(max_distance, 4),
                "distance_threshold": round(distance_threshold, 4),
            }
        ),
    }

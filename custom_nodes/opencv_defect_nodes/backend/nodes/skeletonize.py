"""Skeletonize 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_int,
    require_uint8_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.skeletonize"


def _read_foreground_threshold(raw_value: object) -> int:
    """读取前景阈值。"""

    if raw_value in {None, ""}:
        return 1
    return require_uint8_int(raw_value, field_name="foreground_threshold")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把二值前景规整成单像素近似骨架。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    foreground_threshold = _read_foreground_threshold(request.parameters.get("foreground_threshold"))
    max_iterations = (
        None
        if request.parameters.get("max_iterations") in {None, ""}
        else require_non_negative_int(request.parameters.get("max_iterations"), field_name="max_iterations")
    )

    working_image = np_module.where(image_matrix > foreground_threshold, 255, 0).astype(np_module.uint8)
    skeleton_image = np_module.zeros_like(working_image)
    kernel = cv2_module.getStructuringElement(cv2_module.MORPH_CROSS, (3, 3))
    iteration_count = 0
    hit_max_iterations = False
    while True:
        eroded_image = cv2_module.erode(working_image, kernel)
        opened_image = cv2_module.dilate(eroded_image, kernel)
        skeleton_slice = cv2_module.subtract(working_image, opened_image)
        skeleton_image = cv2_module.bitwise_or(skeleton_image, skeleton_slice)
        working_image = eroded_image
        iteration_count += 1
        if int(np_module.count_nonzero(working_image)) == 0:
            break
        if max_iterations is not None and iteration_count >= max_iterations:
            hit_max_iterations = True
            break

    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=skeleton_image,
        error_message="OpenCV skeletonize 后无法编码输出图片",
    )
    input_foreground_pixel_count = int(np_module.count_nonzero(image_matrix > foreground_threshold))
    skeleton_pixel_count = int(np_module.count_nonzero(skeleton_image))
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="skeletonize",
            output_extension=".png",
            width=int(skeleton_image.shape[1]),
            height=int(skeleton_image.shape[0]),
            media_type="image/png",
        ),
        "summary": build_value_payload(
            {
                "foreground_threshold": int(foreground_threshold),
                "max_iterations": max_iterations,
                "iteration_count": int(iteration_count),
                "hit_max_iterations": hit_max_iterations,
                "input_foreground_pixel_count": input_foreground_pixel_count,
                "skeleton_pixel_count": skeleton_pixel_count,
                "skeleton_ratio": round(
                    float(skeleton_pixel_count / input_foreground_pixel_count)
                    if input_foreground_pixel_count > 0
                    else 0.0,
                    6,
                ),
            }
        ),
    }

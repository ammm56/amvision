"""Absdiff Threshold 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_binary_threshold_mode,
    normalize_optional_object_key,
    require_opencv_imports,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.absdiff-threshold"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对差分图执行阈值化，提取前景变化区域。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    raw_threshold = request.parameters.get("threshold")
    threshold_value = 25 if raw_threshold in {None, ""} else require_uint8_int(raw_threshold, field_name="threshold")
    raw_max_value = request.parameters.get("max_value")
    max_value = 255 if raw_max_value in {None, ""} else require_uint8_int(raw_max_value, field_name="max_value")
    raw_threshold_type = request.parameters.get("threshold_type")
    threshold_type = normalize_binary_threshold_mode(
        "binary" if raw_threshold_type in {None, ""} else raw_threshold_type,
        cv2_module=cv2_module,
    )
    _, threshold_image = cv2_module.threshold(
        image_matrix,
        threshold_value,
        max_value,
        threshold_type,
    )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=threshold_image,
        error_message="OpenCV absdiff-threshold 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="absdiff-threshold",
        output_extension=".png",
        width=int(threshold_image.shape[1]),
        height=int(threshold_image.shape[0]),
        media_type="image/png",
    )
    foreground_pixel_count = int(np_module.count_nonzero(threshold_image))
    total_pixel_count = int(threshold_image.shape[0] * threshold_image.shape[1])
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "threshold": int(threshold_value),
                "max_value": int(max_value),
                "threshold_type": "binary"
                if threshold_type == cv2_module.THRESH_BINARY
                else "binary-inv",
                "foreground_pixel_count": foreground_pixel_count,
                "foreground_ratio": round(
                    float(foreground_pixel_count / total_pixel_count) if total_pixel_count > 0 else 0.0,
                    6,
                ),
            }
        ),
    }

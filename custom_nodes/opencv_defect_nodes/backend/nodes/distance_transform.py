"""Distance Transform 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_optional_object_key,
    require_non_negative_float,
    require_opencv_imports,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.distance-transform"


def _read_foreground_threshold(raw_value: object) -> int:
    """读取前景阈值。"""

    if raw_value in {None, ""}:
        return 1
    return require_uint8_int(raw_value, field_name="foreground_threshold")


def _read_distance_type(raw_value: object, *, cv2_module) -> tuple[str, int]:
    """读取距离类型。"""

    if raw_value in {None, ""}:
        return "l2", cv2_module.DIST_L2
    if not isinstance(raw_value, str):
        raise InvalidRequestError("distance-transform 节点的 distance_type 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value == "l1":
        return normalized_value, cv2_module.DIST_L1
    if normalized_value == "l2":
        return normalized_value, cv2_module.DIST_L2
    if normalized_value == "c":
        return normalized_value, cv2_module.DIST_C
    raise InvalidRequestError("distance-transform 节点的 distance_type 仅支持 l1、l2 或 c")


def _read_mask_size(raw_value: object, *, cv2_module) -> tuple[object, int]:
    """读取 mask_size。"""

    if raw_value in {None, ""}:
        return 3, cv2_module.DIST_MASK_3
    if raw_value == "precise":
        return "precise", cv2_module.DIST_MASK_PRECISE
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("distance-transform 节点的 mask_size 必须是 3、5 或 precise")
    if raw_value == 3:
        return 3, cv2_module.DIST_MASK_3
    if raw_value == 5:
        return 5, cv2_module.DIST_MASK_5
    raise InvalidRequestError("distance-transform 节点的 mask_size 仅支持 3、5 或 precise")


def _read_normalize_output(raw_value: object) -> bool:
    """读取 normalize_output。"""

    if raw_value in {None, ""}:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("distance-transform 节点的 normalize_output 必须是布尔值")
    return raw_value


def _read_output_scale(raw_value: object) -> float:
    """读取输出缩放倍数。"""

    if raw_value in {None, ""}:
        return 1.0
    return require_non_negative_float(raw_value, field_name="output_scale")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对二值前景执行距离变换。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    foreground_threshold = _read_foreground_threshold(request.parameters.get("foreground_threshold"))
    distance_type_name, distance_type = _read_distance_type(request.parameters.get("distance_type"), cv2_module=cv2_module)
    mask_size_label, mask_size = _read_mask_size(request.parameters.get("mask_size"), cv2_module=cv2_module)
    normalize_output = _read_normalize_output(request.parameters.get("normalize_output"))
    output_scale = _read_output_scale(request.parameters.get("output_scale"))

    binary_image = np_module.where(image_matrix > foreground_threshold, 255, 0).astype(np_module.uint8)
    distance_matrix = cv2_module.distanceTransform(binary_image, distance_type, mask_size)
    non_zero_distance_pixels = int(np_module.count_nonzero(distance_matrix))
    if normalize_output:
        preview_image = cv2_module.normalize(distance_matrix, None, 0, 255, cv2_module.NORM_MINMAX).astype(np_module.uint8)
    else:
        preview_image = np_module.clip(distance_matrix * output_scale, 0, 255).astype(np_module.uint8)

    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=preview_image,
        error_message="OpenCV distance-transform 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="distance-transform",
        output_extension=".png",
        width=int(preview_image.shape[1]),
        height=int(preview_image.shape[0]),
        media_type="image/png",
    )
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "foreground_threshold": int(foreground_threshold),
                "distance_type": distance_type_name,
                "mask_size": mask_size_label,
                "normalize_output": normalize_output,
                "output_scale": round(float(output_scale), 4),
                "non_zero_distance_pixels": non_zero_distance_pixels,
                "max_distance": round(float(distance_matrix.max()) if non_zero_distance_pixels > 0 else 0.0, 4),
                "mean_distance": round(
                    float(distance_matrix[distance_matrix > 0].mean()) if non_zero_distance_pixels > 0 else 0.0,
                    4,
                ),
            }
        ),
    }

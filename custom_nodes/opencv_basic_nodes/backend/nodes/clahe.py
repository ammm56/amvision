"""CLAHE 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

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
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.clahe"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 CLAHE 局部对比度增强。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    clip_limit = _read_clip_limit(request.parameters.get("clip_limit"))
    tile_grid_size = _read_tile_grid_size(request.parameters.get("tile_grid_size"))
    apply_to_luminance = _read_bool(
        request.parameters.get("apply_to_luminance"),
        field_name="apply_to_luminance",
        default_value=True,
    )
    clahe_filter = cv2_module.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_grid_size, tile_grid_size))

    if len(image_matrix.shape) == 2:
        output_image = clahe_filter.apply(image_matrix)
    elif apply_to_luminance:
        lab_matrix = cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2_module.split(lab_matrix)
        enhanced_l_channel = clahe_filter.apply(l_channel)
        output_image = cv2_module.cvtColor(
            cv2_module.merge((enhanced_l_channel, a_channel, b_channel)),
            cv2_module.COLOR_LAB2BGR,
        )
    else:
        output_channels = [clahe_filter.apply(channel_matrix) for channel_matrix in cv2_module.split(image_matrix)]
        output_image = cv2_module.merge(output_channels)

    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=output_image,
        error_message="OpenCV clahe 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="clahe",
        output_extension=".png",
        width=int(output_image.shape[1]),
        height=int(output_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}


def _read_clip_limit(raw_value: object) -> float:
    """读取 CLAHE clip_limit。"""

    if is_empty_parameter(raw_value):
        return 2.0
    normalized_value = require_non_negative_float(raw_value, field_name="clip_limit")
    if normalized_value <= 0:
        raise InvalidRequestError("clip_limit 必须大于 0")
    return normalized_value


def _read_tile_grid_size(raw_value: object) -> int:
    """读取 CLAHE tile_grid_size。"""

    if is_empty_parameter(raw_value):
        return 8
    return require_positive_int(raw_value, field_name="tile_grid_size")


def _read_bool(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数。"""

    if is_empty_parameter(raw_value):
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value

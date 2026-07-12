"""Laplacian 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

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
    require_number,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.laplacian"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 Laplacian 二阶边缘增强。"""

    cv2_module, np_module = require_opencv_imports()
    convert_to_grayscale = _read_optional_bool(
        request.parameters.get("convert_to_grayscale"),
        field_name="convert_to_grayscale",
        default_value=True,
    )
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=(cv2_module.IMREAD_GRAYSCALE if convert_to_grayscale else cv2_module.IMREAD_COLOR),
    )
    kernel_size = _read_kernel_size(request.parameters.get("kernel_size"))
    scale = _read_scale(request.parameters.get("scale"))
    delta = _read_delta(request.parameters.get("delta"))

    output_image = cv2_module.convertScaleAbs(
        cv2_module.Laplacian(
            image_matrix,
            cv2_module.CV_32F,
            ksize=kernel_size,
            scale=scale,
            delta=delta,
        )
    )
    summary_matrix = _build_summary_matrix(output_image=output_image, cv2_module=cv2_module)
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=output_image,
        error_message="OpenCV laplacian 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="laplacian",
        output_extension=".png",
        width=int(output_image.shape[1]),
        height=int(output_image.shape[0]),
        media_type="image/png",
    )
    non_zero_pixel_count = int(np_module.count_nonzero(summary_matrix))
    total_pixel_count = int(summary_matrix.shape[0] * summary_matrix.shape[1])
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "kernel_size": kernel_size,
                "scale": float(scale),
                "delta": float(delta),
                "convert_to_grayscale": convert_to_grayscale,
                "width": int(output_image.shape[1]),
                "height": int(output_image.shape[0]),
                "mean_edge_intensity": round(float(summary_matrix.mean()), 4),
                "max_edge_intensity": int(summary_matrix.max()) if total_pixel_count > 0 else 0,
                "non_zero_pixel_count": non_zero_pixel_count,
                "non_zero_ratio": round(
                    float(non_zero_pixel_count / total_pixel_count) if total_pixel_count > 0 else 0.0,
                    6,
                ),
            }
        ),
    }


def _build_summary_matrix(*, output_image, cv2_module):
    """把 Laplacian 输出统一规整为单通道摘要矩阵。"""

    if len(output_image.shape) == 2:
        return output_image
    return output_image.max(axis=2)


def _read_kernel_size(raw_value: object) -> int:
    """读取 Laplacian kernel size。"""

    if is_empty_parameter(raw_value):
        return 3
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("kernel_size 必须是整数")
    if raw_value not in {1, 3, 5, 7}:
        raise InvalidRequestError("kernel_size 仅支持 1、3、5 或 7")
    return int(raw_value)


def _read_scale(raw_value: object) -> float:
    """读取 Laplacian scale。"""

    if is_empty_parameter(raw_value):
        return 1.0
    return float(require_non_negative_float(raw_value, field_name="scale"))


def _read_delta(raw_value: object) -> float:
    """读取 Laplacian delta。"""

    if is_empty_parameter(raw_value):
        return 0.0
    return float(require_number(raw_value, field_name="delta"))


def _read_optional_bool(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数。"""

    if is_empty_parameter(raw_value):
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value

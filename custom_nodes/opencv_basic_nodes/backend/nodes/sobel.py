"""Sobel 节点实现。"""

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
    require_number,
    require_opencv_imports,
)


NODE_TYPE_ID = "custom.opencv.sobel"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 Sobel 边缘增强。"""

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
    direction = _read_direction(request.parameters.get("direction"))
    kernel_size = _read_kernel_size(request.parameters.get("kernel_size"))
    scale = _read_scale(request.parameters.get("scale"))
    delta = _read_delta(request.parameters.get("delta"))

    if direction == "x":
        output_image = cv2_module.convertScaleAbs(
            cv2_module.Sobel(
                image_matrix,
                cv2_module.CV_32F,
                1,
                0,
                ksize=kernel_size,
                scale=scale,
                delta=delta,
            )
        )
    elif direction == "y":
        output_image = cv2_module.convertScaleAbs(
            cv2_module.Sobel(
                image_matrix,
                cv2_module.CV_32F,
                0,
                1,
                ksize=kernel_size,
                scale=scale,
                delta=delta,
            )
        )
    else:
        sobel_x = cv2_module.convertScaleAbs(
            cv2_module.Sobel(
                image_matrix,
                cv2_module.CV_32F,
                1,
                0,
                ksize=kernel_size,
                scale=scale,
                delta=delta,
            )
        )
        sobel_y = cv2_module.convertScaleAbs(
            cv2_module.Sobel(
                image_matrix,
                cv2_module.CV_32F,
                0,
                1,
                ksize=kernel_size,
                scale=scale,
                delta=delta,
            )
        )
        output_image = cv2_module.addWeighted(sobel_x, 1.0, sobel_y, 1.0, 0.0)

    summary_matrix = _build_summary_matrix(output_image=output_image, cv2_module=cv2_module)
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=output_image,
        error_message="OpenCV sobel 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="sobel",
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
                "direction": direction,
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
    """把 Sobel 输出统一规整为单通道摘要矩阵。"""

    if len(output_image.shape) == 2:
        return output_image
    return output_image.max(axis=2)


def _read_direction(raw_value: object) -> str:
    """读取 Sobel 方向。"""

    if raw_value in {None, ""}:
        return "xy"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("direction 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"x", "y", "xy"}:
        raise InvalidRequestError("direction 仅支持 x、y 或 xy")
    return normalized_value


def _read_kernel_size(raw_value: object) -> int:
    """读取 Sobel kernel size。"""

    if raw_value in {None, ""}:
        return 3
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("kernel_size 必须是整数")
    if raw_value not in {1, 3, 5, 7}:
        raise InvalidRequestError("kernel_size 仅支持 1、3、5 或 7")
    return int(raw_value)


def _read_scale(raw_value: object) -> float:
    """读取 Sobel scale。"""

    if raw_value in {None, ""}:
        return 1.0
    return float(require_non_negative_float(raw_value, field_name="scale"))


def _read_delta(raw_value: object) -> float:
    """读取 Sobel delta。"""

    if raw_value in {None, ""}:
        return 0.0
    return float(require_number(raw_value, field_name="delta"))


def _read_optional_bool(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数。"""

    if raw_value in {None, ""}:
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value

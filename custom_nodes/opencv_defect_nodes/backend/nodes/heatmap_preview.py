"""Heatmap Preview 节点实现。"""

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
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.heatmap-preview"
_COLORMAP_CODES = {
    "turbo": "COLORMAP_TURBO",
    "jet": "COLORMAP_JET",
    "hot": "COLORMAP_HOT",
    "inferno": "COLORMAP_INFERNO",
    "viridis": "COLORMAP_VIRIDIS",
    "magma": "COLORMAP_MAGMA",
    "plasma": "COLORMAP_PLASMA",
}


def _read_colormap_name(raw_value: object) -> str:
    """读取 colormap 参数。"""

    if raw_value in (None, ""):
        return "turbo"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("colormap 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in _COLORMAP_CODES:
        raise InvalidRequestError(
            "colormap 不在支持的列表中",
            details={"supported_values": sorted(_COLORMAP_CODES)},
        )
    return normalized_value


def _read_normalize_mode(raw_value: object) -> str:
    """读取归一化模式。"""

    if raw_value in (None, ""):
        return "minmax"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("normalize_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"minmax", "none"}:
        raise InvalidRequestError(
            "normalize_mode 不在支持的列表中",
            details={"supported_values": ["minmax", "none"]},
        )
    return normalized_value


def _read_blend_alpha(raw_value: object) -> float:
    """读取底图混合透明度。"""

    if raw_value in (None, ""):
        return 0.55
    normalized_value = require_non_negative_float(raw_value, field_name="blend_alpha")
    if normalized_value > 1.0:
        raise InvalidRequestError("blend_alpha 必须位于 0 到 1 之间")
    return float(normalized_value)


def _to_single_channel(image_matrix: object, *, cv2_module: object) -> object:
    """把输入图片统一转换为单通道强度图。"""

    if len(image_matrix.shape) == 2:
        return image_matrix
    channel_count = int(image_matrix.shape[2])
    if channel_count == 1:
        return image_matrix[:, :, 0]
    if channel_count == 4:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGRA2GRAY)
    return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGR2GRAY)


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


def _normalize_uint8_matrix(
    intensity_matrix: object,
    *,
    cv2_module: object,
    np_module: object,
    normalize_mode: str,
) -> tuple[object, dict[str, object]]:
    """把强度图规范化为可直接上色的 uint8 矩阵。"""

    intensity_float = intensity_matrix.astype(np_module.float32, copy=False)
    pixel_count = int(intensity_float.size)
    input_min = float(intensity_float.min()) if pixel_count > 0 else 0.0
    input_max = float(intensity_float.max()) if pixel_count > 0 else 0.0
    input_mean = float(intensity_float.mean()) if pixel_count > 0 else 0.0
    if normalize_mode == "none":
        normalized_matrix = np_module.clip(intensity_float, 0.0, 255.0).astype(np_module.uint8)
    elif input_max > input_min:
        normalized_matrix = cv2_module.normalize(
            intensity_float,
            None,
            0,
            255,
            cv2_module.NORM_MINMAX,
        ).astype(np_module.uint8)
    else:
        normalized_matrix = np_module.zeros_like(intensity_float, dtype=np_module.uint8)
    normalized_pixel_count = int(normalized_matrix.size)
    hotspot_threshold = 224
    return normalized_matrix, {
        "input_min": input_min,
        "input_max": input_max,
        "input_mean": round(input_mean, 4),
        "normalized_min": int(normalized_matrix.min()) if normalized_pixel_count > 0 else 0,
        "normalized_max": int(normalized_matrix.max()) if normalized_pixel_count > 0 else 0,
        "normalized_mean": round(float(normalized_matrix.mean()) if normalized_pixel_count > 0 else 0.0, 4),
        "non_zero_ratio": round(
            float(np_module.count_nonzero(normalized_matrix) / normalized_pixel_count)
            if normalized_pixel_count > 0
            else 0.0,
            6,
        ),
        "hotspot_threshold": hotspot_threshold,
        "hotspot_pixel_ratio": round(
            float(np_module.count_nonzero(normalized_matrix >= hotspot_threshold) / normalized_pixel_count)
            if normalized_pixel_count > 0
            else 0.0,
            6,
        ),
    }


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把差异/强度图渲染为伪彩色热力图。"""

    cv2_module, np_module = require_opencv_imports()
    colormap_name = _read_colormap_name(request.parameters.get("colormap"))
    normalize_mode = _read_normalize_mode(request.parameters.get("normalize_mode"))
    blend_alpha = _read_blend_alpha(request.parameters.get("blend_alpha"))

    image_payload, _, image_matrix = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    intensity_matrix = _to_single_channel(image_matrix, cv2_module=cv2_module)
    normalized_matrix, normalized_summary = _normalize_uint8_matrix(
        intensity_matrix,
        cv2_module=cv2_module,
        np_module=np_module,
        normalize_mode=normalize_mode,
    )
    heatmap_matrix = cv2_module.applyColorMap(
        normalized_matrix,
        getattr(cv2_module, _COLORMAP_CODES[colormap_name]),
    )

    base_image_payload = request.input_values.get("base_image")
    used_base_image = base_image_payload is not None
    output_image_matrix = heatmap_matrix
    if used_base_image:
        _base_payload, _, base_image_matrix = load_image_matrix(request, input_name="base_image")
        if base_image_matrix.shape[0] != heatmap_matrix.shape[0] or base_image_matrix.shape[1] != heatmap_matrix.shape[1]:
            raise InvalidRequestError(
                "heatmap-preview 节点要求 base_image 与 image 的尺寸一致",
                details={
                    "image_shape": list(image_matrix.shape),
                    "base_image_shape": list(base_image_matrix.shape),
                },
            )
        output_image_matrix = cv2_module.addWeighted(
            _to_bgr(base_image_matrix, cv2_module=cv2_module),
            1.0 - blend_alpha,
            heatmap_matrix,
            blend_alpha,
            0.0,
        )

    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=output_image_matrix,
        error_message="OpenCV heatmap-preview 后无法编码输出图片",
    )
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="heatmap-preview",
            output_extension=".png",
            width=int(output_image_matrix.shape[1]),
            height=int(output_image_matrix.shape[0]),
            media_type="image/png",
        ),
        "summary": build_value_payload(
            {
                "colormap": colormap_name,
                "normalize_mode": normalize_mode,
                "blend_alpha": blend_alpha,
                "used_base_image": used_base_image,
                "width": int(output_image_matrix.shape[1]),
                "height": int(output_image_matrix.shape[0]),
                **normalized_summary,
            }
        ),
    }

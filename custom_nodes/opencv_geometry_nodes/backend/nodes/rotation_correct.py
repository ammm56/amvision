"""Rotation Correct 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

import math

from backend.nodes.core_nodes.support.logic import build_value_payload, extract_value_by_path, require_value_payload
from backend.nodes.debug_image_panel import (
    build_checkbox_control,
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_line_overlay,
    build_numeric_control,
    is_debug_image_panel_enabled,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    normalize_resize_interpolation,
    require_number,
    require_uint8_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.rotation-correct"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按给定角度对输入图片做旋转矫正。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    try:
        requested_angle_deg, angle_source = _resolve_requested_angle_deg(request)
    except InvalidRequestError:
        if not is_debug_image_panel_enabled(request):
            raise
        return _build_waiting_for_angle_response(request, image_payload=image_payload, image_matrix=image_matrix)
    negate_angle = _read_optional_bool(
        request.parameters.get("negate_angle"),
        field_name="negate_angle",
        default_value=(angle_source == "input"),
    )
    applied_angle_deg = -requested_angle_deg if negate_angle else requested_angle_deg
    expand_canvas = _read_optional_bool(
        request.parameters.get("expand_canvas"),
        field_name="expand_canvas",
        default_value=False,
    )
    raw_interpolation = request.parameters.get("interpolation")
    interpolation = (
        cv2_module.INTER_LINEAR
        if is_empty_parameter(raw_interpolation)
        else normalize_resize_interpolation(raw_interpolation, cv2_module=cv2_module)
    )
    border_mode = _resolve_border_mode(
        request.parameters.get("border_mode"),
        cv2_module=cv2_module,
    )
    border_value = _read_optional_border_value(request.parameters.get("border_value"))

    source_height, source_width = image_matrix.shape[:2]
    rotation_center = (source_width / 2.0, source_height / 2.0)
    rotation_matrix = cv2_module.getRotationMatrix2D(rotation_center, applied_angle_deg, 1.0)
    if expand_canvas:
        abs_cos = abs(rotation_matrix[0, 0])
        abs_sin = abs(rotation_matrix[0, 1])
        output_width = int(math.ceil(source_height * abs_sin + source_width * abs_cos))
        output_height = int(math.ceil(source_height * abs_cos + source_width * abs_sin))
        rotation_matrix[0, 2] += output_width / 2.0 - rotation_center[0]
        rotation_matrix[1, 2] += output_height / 2.0 - rotation_center[1]
    else:
        output_width = int(source_width)
        output_height = int(source_height)

    if len(image_matrix.shape) == 3:
        border_value_argument = (border_value, border_value, border_value)
    else:
        border_value_argument = border_value
    output_image = cv2_module.warpAffine(
        image_matrix,
        rotation_matrix,
        (output_width, output_height),
        flags=interpolation,
        borderMode=border_mode,
        borderValue=border_value_argument,
    )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=output_image,
        error_message="OpenCV rotation-correct 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="rotation-correct",
        output_extension=".png",
        width=int(output_width),
        height=int(output_height),
        media_type="image/png",
    )
    outputs: dict[str, object] = {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "angle_source": angle_source,
                "requested_angle_deg": round(float(requested_angle_deg), 4),
                "applied_angle_deg": round(float(applied_angle_deg), 4),
                "negate_angle": negate_angle,
                "expand_canvas": expand_canvas,
                "source_width": int(source_width),
                "source_height": int(source_height),
                "output_width": int(output_width),
                "output_height": int(output_height),
            }
        ),
    }
    outputs.update(
        _build_rotation_debug_preview(
            request,
            image_payload=image_payload,
            image_matrix=image_matrix,
            angle_deg=requested_angle_deg,
            negate_angle=negate_angle,
            expand_canvas=expand_canvas,
        )
    )
    return outputs


def _build_waiting_for_angle_response(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: dict[str, object],
    image_matrix: object,
) -> dict[str, object]:
    """参数未完整时返回原图和取角度面板，方便编辑态先画参考线。"""

    outputs: dict[str, object] = {
        "image": image_payload,
        "summary": build_value_payload(
            {
                "state": "waiting-for-angle",
                "message": "请在调试图中画参考线，或填写 angle_deg / angle 输入。",
            }
        ),
    }
    outputs.update(
        _build_rotation_debug_preview(
            request,
            image_payload=image_payload,
            image_matrix=image_matrix,
            angle_deg=0.0,
            negate_angle=False,
            expand_canvas=False,
        )
    )
    return outputs


def _build_rotation_debug_preview(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: dict[str, object],
    image_matrix: object,
    angle_deg: float,
    negate_angle: bool,
    expand_canvas: bool,
) -> dict[str, object]:
    """构造 Rotation Correct 的统一图像取参面板。"""

    source_height, source_width = image_matrix.shape[:2]
    return build_debug_image_preview_output(
        request,
        image_payload=image_payload,
        title="Rotation Angle",
        artifact_name="rotation-correct-debug-preview",
        overlays=(
            _build_angle_line_overlay(
                image_width=int(source_width),
                image_height=int(source_height),
                angle_deg=float(angle_deg),
            ),
        ),
        interaction=build_debug_panel_interaction(
            tools=[
                build_interaction_tool(
                    "line",
                    "参考线取角度",
                    ["angle_deg"],
                    extra={
                        "angle_tolerance_deg": 5.0,
                        "search_padding_ratio": 0.18,
                        "search_padding_min": 8.0,
                    },
                )
            ],
            controls=[
                build_numeric_control(
                    "angle_deg",
                    "Angle Deg",
                    round(float(angle_deg), 4),
                    min_value=-180.0,
                    max_value=180.0,
                    step=0.1,
                ),
                build_checkbox_control("negate_angle", "Negate Angle", negate_angle),
                build_checkbox_control("expand_canvas", "Expand Canvas", expand_canvas),
            ],
        ),
    )


def _build_angle_line_overlay(*, image_width: int, image_height: int, angle_deg: float) -> dict[str, object]:
    """按当前角度生成穿过图像中心的参考线 overlay。"""

    center_x = float(image_width) / 2.0
    center_y = float(image_height) / 2.0
    half_length = max(1.0, min(float(image_width), float(image_height)) * 0.4)
    angle_rad = math.radians(float(angle_deg))
    delta_x = math.cos(angle_rad) * half_length
    delta_y = math.sin(angle_rad) * half_length
    return build_line_overlay(
        overlay_id="angle_deg",
        label=f"angle {round(float(angle_deg), 2)}",
        line_xyxy=[
            center_x - delta_x,
            center_y - delta_y,
            center_x + delta_x,
            center_y + delta_y,
        ],
        target_parameters=["angle_deg"],
        parameters={"angle_deg": round(float(angle_deg), 4)},
    )


def _resolve_requested_angle_deg(request: WorkflowNodeExecutionRequest) -> tuple[float, str]:
    """解析请求角度。"""

    raw_angle_payload = request.input_values.get("angle")
    if raw_angle_payload is not None:
        angle_payload = require_value_payload(raw_angle_payload, field_name="angle")
        angle_path = _read_optional_text(request.parameters.get("angle_path"), field_name="angle_path")
        resolved_value = (
            extract_value_by_path(root=angle_payload["value"], path=angle_path)
            if angle_path is not None
            else angle_payload["value"]
        )
        return float(require_number(resolved_value, field_name="angle")), "input"
    raw_angle_deg = request.parameters.get("angle_deg")
    if is_empty_parameter(raw_angle_deg):
        raise InvalidRequestError("rotation-correct 节点要求 angle 输入或 angle_deg 参数至少提供一个")
    return float(require_number(raw_angle_deg, field_name="angle_deg")), "parameter"


def _resolve_border_mode(raw_value: object, *, cv2_module) -> int:
    """解析边界填充模式。"""

    if is_empty_parameter(raw_value):
        return cv2_module.BORDER_CONSTANT
    if not isinstance(raw_value, str):
        raise InvalidRequestError("border_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value == "constant":
        return cv2_module.BORDER_CONSTANT
    if normalized_value == "replicate":
        return cv2_module.BORDER_REPLICATE
    if normalized_value == "reflect":
        return cv2_module.BORDER_REFLECT
    if normalized_value == "reflect101":
        return cv2_module.BORDER_REFLECT_101
    if normalized_value == "wrap":
        return cv2_module.BORDER_WRAP
    raise InvalidRequestError("border_mode 仅支持 constant、replicate、reflect、reflect101 或 wrap")


def _read_optional_border_value(raw_value: object) -> int:
    """读取边界填充值。"""

    if is_empty_parameter(raw_value):
        return 0
    return require_uint8_int(raw_value, field_name="border_value")


def _read_optional_bool(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数。"""

    if is_empty_parameter(raw_value):
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _read_optional_text(raw_value: object, *, field_name: str) -> str | None:
    """读取可选文本参数。"""

    if is_empty_parameter(raw_value):
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None

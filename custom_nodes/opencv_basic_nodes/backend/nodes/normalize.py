"""Normalize 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_optional_object_key,
    require_number,
    require_opencv_imports,
)


NODE_TYPE_ID = "custom.opencv.normalize"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 min-max 归一化。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    alpha_value = _read_alpha_beta(request.parameters.get("alpha"), field_name="alpha", default_value=0.0)
    beta_value = _read_alpha_beta(request.parameters.get("beta"), field_name="beta", default_value=255.0)
    if beta_value < alpha_value:
        raise InvalidRequestError("normalize 节点要求 beta 不能小于 alpha")
    per_channel = _read_bool(request.parameters.get("per_channel"), field_name="per_channel", default_value=False)

    if per_channel and len(image_matrix.shape) == 3:
        normalized_channels = [
            cv2_module.normalize(channel_matrix, None, alpha_value, beta_value, cv2_module.NORM_MINMAX)
            for channel_matrix in cv2_module.split(image_matrix)
        ]
        normalized_image = cv2_module.merge(normalized_channels)
    else:
        normalized_image = cv2_module.normalize(
            image_matrix,
            None,
            alpha_value,
            beta_value,
            cv2_module.NORM_MINMAX,
        )

    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=normalized_image,
        error_message="OpenCV normalize 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="normalize",
        output_extension=".png",
        width=int(normalized_image.shape[1]),
        height=int(normalized_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}


def _read_alpha_beta(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取 normalize 上下限。"""

    if raw_value in {None, ""}:
        return float(default_value)
    return float(require_number(raw_value, field_name=field_name))


def _read_bool(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数。"""

    if raw_value in {None, ""}:
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value

"""Resize 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_optional_object_key,
    normalize_resize_interpolation,
    require_opencv_imports,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.resize"


def _read_optional_dimension(raw_value: object, *, field_name: str) -> int | None:
    """读取可选 resize 维度。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name=field_name)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按给定尺寸缩放输入图片，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    target_width = _read_optional_dimension(request.parameters.get("width"), field_name="width")
    target_height = _read_optional_dimension(request.parameters.get("height"), field_name="height")
    if target_width is None and target_height is None:
        raise InvalidRequestError("resize 节点要求 width 与 height 至少提供一个")

    source_height, source_width = image_matrix.shape[:2]
    if target_width is None:
        assert target_height is not None
        target_width = max(1, int(round(source_width * (target_height / float(source_height)))))
    elif target_height is None:
        target_height = max(1, int(round(source_height * (target_width / float(source_width)))))

    raw_interpolation = request.parameters.get("interpolation")
    if raw_interpolation in {None, ""}:
        interpolation = (
            cv2_module.INTER_AREA
            if target_width <= source_width and target_height <= source_height
            else cv2_module.INTER_LINEAR
        )
    else:
        interpolation = normalize_resize_interpolation(raw_interpolation, cv2_module=cv2_module)

    resized_image = cv2_module.resize(
        image_matrix,
        (int(target_width), int(target_height)),
        interpolation=interpolation,
    )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=resized_image,
        error_message="OpenCV resize 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="resize",
        output_extension=".png",
        width=int(target_width),
        height=int(target_height),
        media_type="image/png",
    )
    return {"image": output_payload}

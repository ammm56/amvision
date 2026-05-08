"""Canny 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_output_image_payload,
    load_image_matrix,
    normalize_optional_object_key,
    require_aperture_size,
    require_non_negative_float,
    require_opencv_imports,
)


NODE_TYPE_ID = "custom.opencv.canny"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 Canny 边缘检测，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )

    threshold1 = require_non_negative_float(request.parameters.get("threshold1", 50), field_name="threshold1")
    threshold2 = require_non_negative_float(request.parameters.get("threshold2", 150), field_name="threshold2")
    aperture_size = require_aperture_size(request.parameters.get("aperture_size", 3))
    l2_gradient = bool(request.parameters.get("l2_gradient", False))
    output_image = cv2_module.Canny(
        image_matrix,
        threshold1,
        threshold2,
        apertureSize=aperture_size,
        L2gradient=l2_gradient,
    )
    success, encoded_image = cv2_module.imencode(".png", output_image)
    if success is not True:
        raise ServiceConfigurationError(
            "OpenCV Canny 后无法编码输出图片",
            details={"node_id": request.node_id},
        )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image.tobytes(),
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="canny",
        output_extension=".png",
        width=int(output_image.shape[1]),
        height=int(output_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}
"""Binary Threshold 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_float,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.binary-threshold"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把输入图片转为灰度后二值化，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )

    raw_threshold = request.parameters.get("threshold")
    threshold = 127 if raw_threshold in {None, ""} else require_non_negative_float(raw_threshold, field_name="threshold")
    raw_max_value = request.parameters.get("max_value")
    max_value = 255 if raw_max_value in {None, ""} else require_non_negative_float(raw_max_value, field_name="max_value")
    _, threshold_image = cv2_module.threshold(image_matrix, threshold, max_value, cv2_module.THRESH_BINARY)
    success, encoded_image = cv2_module.imencode(".png", threshold_image)
    if success is not True:
        raise ServiceConfigurationError(
            "OpenCV 二值化后无法编码输出图片",
            details={"node_id": request.node_id},
        )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image.tobytes(),
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="binary-threshold",
        output_extension=".png",
        width=int(threshold_image.shape[1]),
        height=int(threshold_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}

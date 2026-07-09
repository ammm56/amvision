"""Morphology 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_kernel_shape,
    normalize_morphology_operation,
    normalize_odd_kernel_size,
    normalize_optional_object_key,
    require_positive_int,
    resolve_morphology_operation,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.morphology"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 morphology 操作，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )

    raw_operation = request.parameters.get("operation")
    operation_name = normalize_morphology_operation("open" if raw_operation in {None, ""} else raw_operation)
    raw_kernel_shape = request.parameters.get("shape")
    kernel_shape = normalize_kernel_shape("rect" if raw_kernel_shape in {None, ""} else raw_kernel_shape, cv2_module=cv2_module)
    raw_kernel_size = request.parameters.get("kernel_size")
    kernel_size = 3 if raw_kernel_size in {None, ""} else normalize_odd_kernel_size(raw_kernel_size)
    raw_iterations = request.parameters.get("iterations")
    iterations = 1 if raw_iterations in {None, ""} else require_positive_int(raw_iterations, field_name="iterations")
    kernel = cv2_module.getStructuringElement(kernel_shape, (kernel_size, kernel_size))
    if operation_name == "erode":
        output_image = cv2_module.erode(image_matrix, kernel, iterations=iterations)
    elif operation_name == "dilate":
        output_image = cv2_module.dilate(image_matrix, kernel, iterations=iterations)
    else:
        output_image = cv2_module.morphologyEx(
            image_matrix,
            resolve_morphology_operation(operation_name, cv2_module=cv2_module),
            kernel,
            iterations=iterations,
        )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=output_image,
        error_message="OpenCV morphology 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name=f"morphology-{operation_name}",
        output_extension=".png",
        width=int(output_image.shape[1]),
        height=int(output_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}

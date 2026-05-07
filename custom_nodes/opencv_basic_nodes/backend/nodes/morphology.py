"""Morphology 节点实现。"""

from __future__ import annotations

from backend.nodes.runtime_support import resolve_image_input, write_image_bytes
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    normalize_kernel_shape,
    normalize_morphology_operation,
    normalize_odd_kernel_size,
    normalize_optional_object_key,
    require_opencv_imports,
    require_positive_int,
    require_dataset_path,
    resolve_morphology_operation,
)


NODE_TYPE_ID = "custom.opencv.morphology"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 morphology 操作，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    _, image_payload, image_object_key = resolve_image_input(request)
    image_matrix = cv2_module.imread(str(require_dataset_path(request, image_object_key)), cv2_module.IMREAD_GRAYSCALE)
    if image_matrix is None:
        raise ServiceConfigurationError(
            "OpenCV 无法读取输入图片",
            details={"node_id": request.node_id, "object_key": image_object_key},
        )

    operation_name = normalize_morphology_operation(request.parameters.get("operation", "open"))
    kernel_shape = normalize_kernel_shape(request.parameters.get("shape", "rect"), cv2_module=cv2_module)
    kernel_size = normalize_odd_kernel_size(request.parameters.get("kernel_size", 3))
    iterations = require_positive_int(request.parameters.get("iterations", 1), field_name="iterations")
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
    success, encoded_image = cv2_module.imencode(".png", output_image)
    if success is not True:
        raise ServiceConfigurationError(
            "OpenCV morphology 后无法编码输出图片",
            details={"node_id": request.node_id},
        )
    output_payload = write_image_bytes(
        request,
        source_payload=image_payload,
        content=encoded_image.tobytes(),
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name=f"morphology-{operation_name}",
        output_extension=".png",
        width=int(output_image.shape[1]),
        height=int(output_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}
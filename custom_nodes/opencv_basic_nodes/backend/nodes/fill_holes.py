"""Fill Holes 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_optional_object_key,
    require_opencv_imports,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.fill-holes"


def _read_foreground_threshold(raw_value: object) -> int:
    """读取前景阈值。"""

    if raw_value in {None, ""}:
        return 1
    return require_uint8_int(raw_value, field_name="foreground_threshold")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """填充白色前景内部孔洞。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    foreground_threshold = _read_foreground_threshold(request.parameters.get("foreground_threshold"))
    binary_image = np_module.where(image_matrix > foreground_threshold, 255, 0).astype(np_module.uint8)
    padded_binary_image = cv2_module.copyMakeBorder(
        binary_image,
        1,
        1,
        1,
        1,
        cv2_module.BORDER_CONSTANT,
        value=0,
    )
    floodfilled_image = padded_binary_image.copy()
    floodfill_mask = np_module.zeros(
        (padded_binary_image.shape[0] + 2, padded_binary_image.shape[1] + 2),
        dtype=np_module.uint8,
    )
    cv2_module.floodFill(floodfilled_image, floodfill_mask, (0, 0), 255)
    hole_mask_image = cv2_module.bitwise_not(floodfilled_image)
    filled_image = cv2_module.bitwise_or(padded_binary_image, hole_mask_image)[1:-1, 1:-1]

    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=filled_image,
        error_message="OpenCV fill-holes 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="fill-holes",
        output_extension=".png",
        width=int(filled_image.shape[1]),
        height=int(filled_image.shape[0]),
        media_type="image/png",
    )
    input_foreground_pixel_count = int(np_module.count_nonzero(binary_image))
    output_foreground_pixel_count = int(np_module.count_nonzero(filled_image))
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "foreground_threshold": int(foreground_threshold),
                "input_foreground_pixel_count": input_foreground_pixel_count,
                "output_foreground_pixel_count": output_foreground_pixel_count,
                "filled_hole_pixel_count": int(output_foreground_pixel_count - input_foreground_pixel_count),
            }
        ),
    }

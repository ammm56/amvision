"""从种子点执行固定或浮动范围 flood fill。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    read_bool,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.flood-fill"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """以指定种子点生成 flood fill 区域 mask。"""

    cv2, np = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    x = read_int(
        request.parameters.get("seed_x"),
        field_name="seed_x",
        default=0,
        minimum=0,
        maximum=int(image.shape[1]) - 1,
    )
    y = read_int(
        request.parameters.get("seed_y"),
        field_name="seed_y",
        default=0,
        minimum=0,
        maximum=int(image.shape[0]) - 1,
    )
    lo_diff = read_float(
        request.parameters.get("lo_diff"),
        field_name="lo_diff",
        default=10.0,
        minimum=0.0,
        maximum=255.0,
    )
    up_diff = read_float(
        request.parameters.get("up_diff"),
        field_name="up_diff",
        default=10.0,
        minimum=0.0,
        maximum=255.0,
    )
    connectivity = read_int(
        request.parameters.get("connectivity"),
        field_name="connectivity",
        default=4,
        minimum=4,
        maximum=8,
    )
    if connectivity not in {4, 8}:
        raise InvalidRequestError("connectivity 仅支持 4 或 8")
    fixed_range = read_bool(
        request.parameters.get("fixed_range"),
        field_name="fixed_range",
        default=False,
    )
    mask = np.zeros((image.shape[0] + 2, image.shape[1] + 2), dtype=np.uint8)
    flags = connectivity | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    if fixed_range:
        flags |= cv2.FLOODFILL_FIXED_RANGE
    fill_value = (255,) * (1 if len(image.shape) == 2 else int(image.shape[2]))
    count, _, mask_result, rect = cv2.floodFill(
        image.copy(),
        mask,
        (x, y),
        fill_value,
        (lo_diff,) * len(fill_value),
        (up_diff,) * len(fill_value),
        flags,
    )
    result = mask_result[1:-1, 1:-1]
    return {
        "mask": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=result,
            variant_name="flood-fill",
            output_object_key=request.parameters.get("output_object_key"),
        ),
        "summary": build_value_payload(
            {
                "filled_pixel_count": int(count),
                "seed_xy": [x, y],
                "bbox_xywh": [int(value) for value in rect],
                "fixed_range": fixed_range,
            }
        ),
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]

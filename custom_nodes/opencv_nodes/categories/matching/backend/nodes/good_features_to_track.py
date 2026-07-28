"""使用 Shi-Tomasi 或 Harris 响应检测强角点。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_gray,
    read_bool,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.good-features-to-track"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """检测适合跟踪的强角点并输出点集。"""

    cv2, _ = require_opencv_imports()
    image_payload, source_key, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2)
    max_corners = read_int(
        request.parameters.get("max_corners"),
        field_name="max_corners",
        default=200,
        minimum=1,
    )
    quality = read_float(
        request.parameters.get("quality_level"),
        field_name="quality_level",
        default=0.01,
        minimum=1e-9,
        maximum=1.0,
    )
    min_distance = read_float(
        request.parameters.get("min_distance"),
        field_name="min_distance",
        default=5.0,
        minimum=0.0,
    )
    block_size = read_int(
        request.parameters.get("block_size"),
        field_name="block_size",
        default=3,
        minimum=2,
    )
    use_harris = read_bool(
        request.parameters.get("use_harris"),
        field_name="use_harris",
        default=False,
    )
    corners = cv2.goodFeaturesToTrack(
        gray,
        maxCorners=max_corners,
        qualityLevel=quality,
        minDistance=min_distance,
        blockSize=block_size,
        useHarrisDetector=use_harris,
    )
    points = [] if corners is None else corners.reshape(-1, 2).astype(float).tolist()
    return {
        "points": build_value_payload(
            {
                "image_points": points,
                "point_count": len(points),
                "detector": "harris" if use_harris else "shi-tomasi",
                "source_image": image_payload,
                "source_object_key": source_key,
            }
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]

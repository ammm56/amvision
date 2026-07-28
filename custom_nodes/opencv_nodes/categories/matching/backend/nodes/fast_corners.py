"""使用 FAST 检测角点。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_gray,
    read_bool,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.fast-corners"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 FAST 检测并按响应值截取角点。"""

    cv2, _ = require_opencv_imports()
    image_payload, source_key, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2)
    threshold = read_int(
        request.parameters.get("threshold"),
        field_name="threshold",
        default=10,
        minimum=1,
        maximum=255,
    )
    nonmax = read_bool(
        request.parameters.get("nonmax_suppression"),
        field_name="nonmax_suppression",
        default=True,
    )
    detector = cv2.FastFeatureDetector_create(
        threshold=threshold,
        nonmaxSuppression=nonmax,
    )
    keypoints = sorted(
        detector.detect(gray, None),
        key=lambda item: float(item.response),
        reverse=True,
    )
    max_features = read_int(
        request.parameters.get("max_features"),
        field_name="max_features",
        default=500,
        minimum=1,
    )
    keypoints = keypoints[:max_features]
    points = [[float(item.pt[0]), float(item.pt[1])] for item in keypoints]
    return {
        "points": build_value_payload(
            {
                "image_points": points,
                "responses": [float(item.response) for item in keypoints],
                "point_count": len(points),
                "detector": "fast",
                "source_image": image_payload,
                "source_object_key": source_key,
            }
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
